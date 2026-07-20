"""
Motor del modo EN VIVO. Corrige cada respuesta al vuelo contra la pauta (AnswerKey) y,
al cerrar, entrega la matriz binaria participante x item que alimenta la MISMA psicometria
del resto de la plataforma. Sincronizacion por polling (GET estado); WebSockets es una
optimizacion posterior, no cambia el contrato.
"""
from __future__ import annotations

import random
import secrets
import time
import uuid

from app.core.errors import conflict, not_found
from app.models.answer_key import AnswerKey, QUESTION_TYPE_MULTIPLE_CHOICE
from app.models.assessment import Assessment
from app.models.en_vivo import (
    SesionEnVivo, ParticipanteVivo, RespuestaVivo, EventoIntegridad,
    ESTADO_LOBBY, ESTADO_ACTIVA, ESTADO_PAUSADA, ESTADO_CERRADA,
    RITMO_DOCENTE, RITMO_ALUMNO,
)
from app.models.scan import Scan
from app.services import result_service

# Prefijo del identificador de los escaneos generados por el modo en vivo. Permite
# reconocerlos (origen trazable) y hace idempotente el cierre (no se duplican).
_SCAN_PREFIX = "envivo:"

# Alfabeto sin caracteres ambiguos (0/O, 1/I) para dictar el codigo en voz alta.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generar_codigo(db, largo: int = 6) -> str:
    for _ in range(30):
        cod = "".join(secrets.choice(_ALFABETO) for _ in range(largo))
        if not db.query(SesionEnVivo).filter(SesionEnVivo.codigo == cod).first():
            return cod
    raise conflict("No se pudo generar un codigo de sala unico.")


def _sesion(db, codigo: str) -> SesionEnVivo:
    s = db.query(SesionEnVivo).filter(SesionEnVivo.codigo == str(codigo).upper()).first()
    if not s:
        raise not_found("Sesion en vivo no encontrada.")
    return s


def _items_mc(db, assessment_id, version: str) -> list:
    """Items de alternativas de la version, ordenados por numero de pregunta.

    El modo en vivo solo corre preguntas de seleccion multiple (las de desarrollo
    necesitan validacion docente y no se auto-corrigen al vuelo).
    """
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak or not ak.is_valid:
        raise conflict("La pauta no esta validada; no se puede iniciar el modo en vivo.")
    items = [it for it in ak.items
             if it.version.upper() == version.upper() and not it.is_annulled
             and it.question_type == QUESTION_TYPE_MULTIPLE_CHOICE]
    items.sort(key=lambda it: it.question_number)
    return items


def _letras_item(it) -> list:
    """Letras canónicas de un ítem: las de su banco de opciones, o A-D por defecto."""
    if it.opciones_json:
        ls = [str(o.get("letra", "")).strip().upper() for o in it.opciones_json if o.get("letra")]
        if ls:
            return ls
    return ["A", "B", "C", "D"]


_IMAGEN_MAX_CHARS = 3_500_000    # ~2.5 MB en base64; suficiente para una foto de laboratorio


def _limpiar_imagen(v) -> str | None:
    """Acepta SOLO un data URI de imagen (base64), acotado en tamaño. Cadena vacía => None
    (permite BORRAR la imagen). Cualquier otra cosa (URL externa, script) se descarta."""
    s = str(v or "").strip()
    if not s:
        return None
    if not s.startswith("data:image/"):
        return None
    return s[:_IMAGEN_MAX_CHARS]


def _items_contenido(db, assessment_id, version: str) -> list:
    """Ítems MC enriquecidos con su contenido (banco de ítems) para el modo en vivo digital.

    ordinal = posición 1..N entre las MC (lo que se persiste en RespuestaVivo.question_number
    y en la matriz psicométrica); qn = número real de pregunta en la pauta.
    """
    out = []
    for i, it in enumerate(_items_mc(db, assessment_id, version), start=1):
        opciones = it.opciones_json or []
        out.append({
            "ordinal": i, "qn": it.question_number,
            "correcta": str(it.correct_answer).strip().upper(),
            "enunciado": it.enunciado, "imagen": getattr(it, "enunciado_imagen", None),
            "opciones": opciones,
            "letras": _letras_item(it), "tiene_opciones": bool(opciones),
            "justificacion": it.justificacion, "ra": it.learning_outcome_id,
            "bloom": it.bloom_level, "unidad": it.unidad, "weight": it.weight or 1.0,
        })
    return out


def _gen_layout(items: list, shuffle_p: bool, shuffle_o: bool, rng: random.Random) -> dict:
    """Distribución personal (barajado) de un participante.

    q_order = orden de los ordinales de pregunta; opt_map[ordinal] = letras canónicas en el
    orden en que se MOSTRARÁN (posición i muestra la letra opt_map[ordinal][i]). El barajado
    de opciones solo aplica a ítems con banco de opciones (barajar letras sin texto no aporta).
    """
    q_order = [it["ordinal"] for it in items]
    if shuffle_p:
        rng.shuffle(q_order)
    opt_map = {}
    for it in items:
        disp = list(it["letras"])
        if shuffle_o and it["tiene_opciones"] and len(disp) > 1:
            rng.shuffle(disp)
        opt_map[str(it["ordinal"])] = disp
    return {"q_order": q_order, "opt_map": opt_map}


# ── ciclo de vida (docente) ──────────────────────────────────────────────────────────
def crear_sesion(db, assessment_id, version: str = "A", config: dict | None = None) -> SesionEnVivo:
    items = _items_mc(db, assessment_id, version)
    if not items:
        raise conflict("La evaluacion no tiene preguntas de alternativas para el modo en vivo.")
    cfg = config or {}
    modo = RITMO_ALUMNO if str(cfg.get("modo_ritmo", "")).lower() == RITMO_ALUMNO else RITMO_DOCENTE
    shuffle_p = bool(cfg.get("shuffle_preguntas"))
    shuffle_o = bool(cfg.get("shuffle_opciones"))
    # Barajar preguntas exige ritmo por-alumno: en ritmo-docente la pregunta es global y
    # no puede ser distinta para cada estudiante.
    if shuffle_p:
        modo = RITMO_ALUMNO
    s = SesionEnVivo(assessment_id=str(assessment_id), codigo=_generar_codigo(db),
                     estado=ESTADO_LOBBY, pregunta_actual=0, n_preguntas=len(items),
                     version=version.upper(),
                     retro_alumno=bool(cfg.get("retro_alumno")),
                     revelar_correccion=bool(cfg.get("revelar_correccion", True)),
                     mascota_motivacional=bool(cfg.get("mascota_motivacional", True)),
                     duracion_min=max(0, int(cfg.get("duracion_min") or 0)),
                     modo_ritmo=modo, shuffle_preguntas=shuffle_p, shuffle_opciones=shuffle_o,
                     requiere_seb=bool(cfg.get("requiere_seb")))
    db.add(s); db.commit(); db.refresh(s)
    return s


def verificar_seb_o_error(db, s, request):
    """Si la sala EXIGE Safe Exam Browser, valida que la petición venga de SEB; si no, corta."""
    if not getattr(s, "requiere_seb", False):
        return
    from app.services import seb_service
    v = seb_service.verificar(request.headers, str(request.url), getattr(s, "seb_config_key", None))
    if not v["seb"]:
        raise conflict("Esta evaluación exige Safe Exam Browser. Ábrela con SEB usando el archivo "
                       ".seb que te compartió el docente.")


def _ahora() -> int:
    return int(time.time())


def _arrancar_timer(s) -> None:
    """Estampa el inicio de la cuenta regresiva la PRIMERA vez que la sala se abre (si hay límite)."""
    if int(getattr(s, "duracion_min", 0) or 0) > 0 and not getattr(s, "timer_inicio_ts", None):
        s.timer_inicio_ts = _ahora()


def segundos_restantes(s, p) -> int | None:
    """Segundos que le quedan a ESTE alumno (plazo global + su extensión). None = sin límite
    o aún no arrancó. Puede ser negativo → tiempo agotado."""
    dur = int(getattr(s, "duracion_min", 0) or 0)
    ini = getattr(s, "timer_inicio_ts", None)
    if dur <= 0 or not ini:
        return None
    deadline = int(ini) + dur * 60 + int(getattr(p, "tiempo_extra_seg", 0) or 0)
    return deadline - _ahora()


def _tiempo_agotado(s, p) -> bool:
    r = segundos_restantes(s, p)
    return r is not None and r <= 0


def avanzar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_CERRADA:
        raise conflict("La sesion ya esta cerrada.")
    # Ritmo por-alumno: el docente no avanza pregunta a pregunta; 'avanzar' solo ABRE la sala
    # (lobby -> activa) y cada estudiante recorre su propia secuencia a su ritmo.
    if s.modo_ritmo == RITMO_ALUMNO:
        s.estado = ESTADO_ACTIVA
        if s.pregunta_actual == 0:
            s.pregunta_actual = 1                 # nominal: marca "empezó" (no dirige a los alumnos)
        _arrancar_timer(s)
        db.commit(); db.refresh(s)
        return s
    _arrancar_timer(s)
    cierra = s.pregunta_actual >= s.n_preguntas
    if cierra:
        s.estado = ESTADO_CERRADA                 # se acabaron las preguntas -> cierra
    else:
        s.pregunta_actual += 1
        s.estado = ESTADO_ACTIVA
    db.commit(); db.refresh(s)
    if cierra:
        _persistir_scans(db, s)                   # auto-cierre también alimenta la psicometría
    return s


def pausar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_ACTIVA:
        s.estado = ESTADO_PAUSADA
        db.commit(); db.refresh(s)
    return s


def reanudar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_PAUSADA:
        s.estado = ESTADO_ACTIVA
        db.commit(); db.refresh(s)
    return s


def cerrar(db, codigo: str) -> dict:
    """Cierra la sala y VUELCA las respuestas a escaneos (Scan) del mismo assessment.

    Así el modo en vivo deja de ser un silo: los mismos motores psicométricos del módulo
    Profesor/Investigador (que leen `Scan.raw_ocr_payload_json`) ven esta evidencia. No
    escribe notas ni Result (gobernanza G1: en vivo no altera calificaciones); solo aporta
    la matriz de correctitud. Idempotente: si ya se persistió, no duplica.
    """
    s = _sesion(db, codigo)
    s.estado = ESTADO_CERRADA
    db.commit(); db.refresh(s)
    n = _persistir_scans(db, s)
    return {"codigo": s.codigo, "estado": s.estado, "pregunta_actual": s.pregunta_actual,
            "n_preguntas": s.n_preguntas, "scans_incorporados": n}


def _persistir_scans(db, s: SesionEnVivo) -> int:
    """Convierte cada participante que respondió en un Scan (answers por nº de pregunta real).

    Devuelve cuántos escaneos se crearon (0 si ya existían = idempotente, o si nadie jugó).
    """
    aid = uuid.UUID(s.assessment_id)
    # Idempotencia por SESIÓN (robusta y portable): el student_identifier ahora puede ser el
    # RUT del alumno real, así que ya no basta el prefijo; buscamos por la marca de sesión en
    # el payload de los scans en vivo del assessment (conjunto pequeño, filtrado por status).
    for sc in db.query(Scan).filter(Scan.assessment_id == aid, Scan.status == "en_vivo").all():
        if (sc.raw_ocr_payload_json or {}).get("sesion") == s.codigo:
            return 0  # ya se volcó este cierre; no duplicar

    items = _items_mc(db, aid, s.version)
    if not items:
        return 0
    # ordinal (1..N en vivo) -> nº de pregunta real de la pauta
    ordinal_a_real = {i: it.question_number for i, it in enumerate(items, start=1)}
    max_q = max(ordinal_a_real.values())

    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()
    por_part: dict[uuid.UUID, dict[int, str]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = r.respuesta

    # Resolver student_id (nómina) -> RUT, para que el scan en vivo se IMPUTE al alumno real
    # y entre al libro de notas / psicometría / equidad con la misma llave que un escaneo OMR.
    from app.models.student import Student
    ruts: dict[str, str] = {}
    sids = [p.student_id for p in parts if p.student_id]
    if sids:
        uu = []
        for sid in set(sids):
            try: uu.append(uuid.UUID(str(sid)))
            except (ValueError, TypeError): pass
        if uu:
            for st in db.query(Student).filter(Student.id.in_(uu)).all():
                if st.rut:
                    ruts[str(st.id)] = st.rut.strip()

    creados = 0
    for p in parts:
        elecciones = por_part.get(p.id)
        if not elecciones:
            continue  # participante que no respondió nada: no aporta fila
        answers: list = [None] * max_q
        for ordinal, letra in elecciones.items():
            real = ordinal_a_real.get(ordinal)
            if real:
                answers[real - 1] = letra
        rut = ruts.get(str(p.student_id)) if p.student_id else None
        # Identificado -> RUT (liga al alumno real); anónimo -> alias seudonimizado por sesión.
        ident = (rut or (_SCAN_PREFIX + s.codigo + ":" + str(p.id)[:8]))[:100]
        db.add(Scan(
            assessment_id=aid,
            student_identifier=ident, origen="en_vivo",
            status="en_vivo", detected_version=s.version, requires_review=False,
            raw_ocr_payload_json={"answers": answers, "origen": "en_vivo",
                                  "sesion": s.codigo, "alias": p.alias,
                                  "student_id": str(p.student_id) if p.student_id else None,
                                  "participante_id": str(p.id),
                                  "identificado": bool(rut)},
        ))
        creados += 1
    db.commit()
    return creados


def historial_sesiones(db, assessment_id) -> dict:
    """Historial navegable de salas EN VIVO de un assessment: cada sesión pasada con su código,
    fecha, estado, nº de participantes y cuántos respondieron. Recupera la evidencia que hoy
    solo era hallable por código: base para consultar resultados por prueba/estudiante.
    """
    aid = str(assessment_id)
    ses = (db.query(SesionEnVivo).filter(SesionEnVivo.assessment_id == aid)
           .order_by(SesionEnVivo.created_at.desc()).all())
    if not ses:
        return {"assessment_id": aid, "sesiones": [], "n": 0}
    ids = [s.id for s in ses]
    # conteos por sesión en 2 consultas (evita N+1)
    n_part: dict = {}
    for pid, sid in db.query(ParticipanteVivo.id, ParticipanteVivo.sesion_id).filter(
            ParticipanteVivo.sesion_id.in_(ids)).all():
        n_part[sid] = n_part.get(sid, 0) + 1
    respondieron: dict = {}
    vistos: set = set()
    for sid, pid in db.query(RespuestaVivo.sesion_id, RespuestaVivo.participante_id).filter(
            RespuestaVivo.sesion_id.in_(ids)).all():
        k = (sid, pid)
        if k in vistos:
            continue
        vistos.add(k)
        respondieron[sid] = respondieron.get(sid, 0) + 1
    filas = []
    for s in ses:
        filas.append({
            "codigo": s.codigo, "estado": s.estado, "version": s.version,
            "creada": s.created_at.isoformat() if s.created_at else None,
            "n_preguntas": s.n_preguntas, "pregunta_actual": s.pregunta_actual,
            "n_participantes": n_part.get(s.id, 0),
            "n_respondieron": respondieron.get(s.id, 0),
            "requiere_seb": bool(s.requiere_seb),
        })
    return {"assessment_id": aid, "sesiones": filas, "n": len(filas)}


def nomina_sesion(db, codigo: str) -> dict:
    """Nómina del curso de la sala para que el ALUMNO se identifique al unirse (público, por
    código). Devuelve SOLO nombres + id opaco (nunca el RUT: proporcionalidad, Ley 21.719) y
    marca los ya tomados en esta sala. Impersonar un nombre es posible (seguridad media web v1);
    el docente ve quién entró y la identidad fuerte es la vía passkey del módulo de Asistencia.
    """
    s = _sesion(db, codigo)
    from app.models.student import Student
    asm = db.query(Assessment).filter(Assessment.id == uuid.UUID(s.assessment_id)).first()
    if not asm:
        return {"codigo": codigo, "alumnos": [], "tomados": []}
    ests = (db.query(Student).filter(Student.course_id == asm.course_id)
            .order_by(Student.apellido_paterno, Student.apellido_materno, Student.nombres).all())
    def _nombre(e):
        ap = " ".join(x for x in (e.apellido_paterno, e.apellido_materno) if x).strip()
        n = (e.nombres or "").strip()
        return (ap + (", " + n if n else "")).strip() or (e.rut or "Alumno")
    alumnos = [{"id": str(e.id), "nombre": _nombre(e)} for e in ests]
    tomados = [p.student_id for p in db.query(ParticipanteVivo)
               .filter(ParticipanteVivo.sesion_id == s.id).all() if p.student_id]
    return {"codigo": codigo, "alumnos": alumnos, "tomados": tomados, "n": len(alumnos)}


# ── participantes ────────────────────────────────────────────────────────────────────
def unir(db, codigo: str, alias: str, student_id: str | None = None,
         device_id: str | None = None) -> ParticipanteVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_CERRADA:
        raise conflict("La sesion ya esta cerrada; no admite mas participantes.")
    # LV10 · Candado por dispositivo: si este navegador YA tiene un participante en la sala,
    # se RETOMA ese mismo (no se crea otro). Asi un alumno no puede volver a entrar y rendir
    # por un companero desde el mismo equipo (evita el doble registro). Es honesto: no frena
    # incognito/otro dispositivo; para blindaje fuerte esta el passkey de Asistencia.
    device_id = (device_id or "").strip()[:64] or None
    if device_id:
        existente = (db.query(ParticipanteVivo)
                     .filter(ParticipanteVivo.sesion_id == s.id,
                             ParticipanteVivo.device_id == device_id)
                     .order_by(ParticipanteVivo.created_at.asc())
                     .first())
        if existente:
            # Trazabilidad: si el mismo equipo re-entra intentando ser OTRA persona (otro
            # student_id, o un alias distinto sin nomina), queda registrado como evidencia.
            nuevo_sid = str(student_id) if student_id else None
            distinto = (nuevo_sid and existente.student_id and nuevo_sid != existente.student_id) \
                or (not nuevo_sid and not existente.student_id
                    and (alias or "").strip()[:80] and (alias or "").strip()[:80] != existente.alias)
            if distinto:
                try:
                    db.add(EventoIntegridad(
                        sesion_id=s.id, participante_id=existente.id, tipo="reingreso_bloqueado",
                        meta_json={"alias_intentado": (alias or "").strip()[:80],
                                   "student_id_intentado": nuevo_sid,
                                   "device_id": device_id}))
                    db.commit()
                except Exception:
                    db.rollback()
            return existente
    alias = (alias or "").strip()[:80] or "Anonimo"
    # Identificado: el alias pasa a ser el nombre de la ficha (el docente ve la identidad real,
    # no un alias tecleado). El vínculo real se hace por student_id -> RUT al cerrar.
    if student_id:
        from app.models.student import Student
        try:
            st = db.query(Student).filter(Student.id == uuid.UUID(str(student_id))).first()
        except (ValueError, TypeError):
            st = None
        if st:
            ap = " ".join(x for x in (st.apellido_paterno, st.apellido_materno) if x).strip()
            nom = ((st.nombres or "").strip() + " " + ap).strip()
            if nom:
                alias = nom[:80]
        else:
            student_id = None   # id que no existe en la nómina: no lo ligamos
    # Distribución personal (barajado por-alumno) fijada al entrar: estable durante la sesión.
    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    layout = _gen_layout(items, s.shuffle_preguntas, s.shuffle_opciones, random.Random())
    p = ParticipanteVivo(sesion_id=s.id, alias=alias,
                         student_id=str(student_id) if student_id else None,
                         device_id=device_id,
                         token=secrets.token_urlsafe(24), layout_json=layout, progreso=0)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _participante(db, s, participante_id, token) -> ParticipanteVivo:
    try:
        pid = uuid.UUID(str(participante_id))
    except ValueError:
        raise not_found("Participante no valido.")
    p = db.query(ParticipanteVivo).filter(
        ParticipanteVivo.id == pid, ParticipanteVivo.sesion_id == s.id).first()
    if not p or p.token != token:
        raise not_found("Participante no valido para esta sesion.")
    return p


def _participante_por_id(db, s, participante_id) -> ParticipanteVivo:
    """Lookup por id SIN token (acciones del docente: extender tiempo, cerrar/reabrir)."""
    try:
        pid = uuid.UUID(str(participante_id))
    except ValueError:
        raise not_found("Participante no valido.")
    p = db.query(ParticipanteVivo).filter(
        ParticipanteVivo.id == pid, ParticipanteVivo.sesion_id == s.id).first()
    if not p:
        raise not_found("Participante no encontrado en esta sesion.")
    return p


def _ordinal_actual(s, p, n_items: int) -> int:
    """Ordinal (1..N) de la pregunta que le toca al participante ahora, o 0 si ninguna."""
    if s.modo_ritmo == RITMO_ALUMNO:
        q_order = (p.layout_json or {}).get("q_order") or list(range(1, n_items + 1))
        idx = p.progreso                       # cuántas lleva respondidas
        return q_order[idx] if 0 <= idx < len(q_order) else 0
    return s.pregunta_actual                    # ritmo-docente: pregunta global


def responder(db, codigo: str, participante_id, token: str,
              respuesta: str | None = None, opcion_idx: int | None = None) -> dict:
    s = _sesion(db, codigo)
    if s.estado != ESTADO_ACTIVA:
        raise conflict("La sesion no esta recibiendo respuestas en este momento.")
    p = _participante(db, s, participante_id, token)
    if getattr(p, "bloqueado", False):
        raise conflict("El docente cerró tu evaluación. No puedes seguir respondiendo.")
    if _tiempo_agotado(s, p):
        raise conflict("Se acabó el tiempo. Tu evaluación se cerró automáticamente.")

    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    ordinal = _ordinal_actual(s, p, len(items))
    if not (1 <= ordinal <= len(items)):
        raise conflict("No hay una pregunta activa para ti.")
    item = items[ordinal - 1]

    if db.query(RespuestaVivo).filter(
            RespuestaVivo.participante_id == p.id,
            RespuestaVivo.question_number == ordinal).first():
        raise conflict("Ya respondiste esta pregunta.")

    # La letra elegida puede venir como letra canónica (bots/legado) o como posición
    # MOSTRADA (opcion_idx) que se mapea a canónica vía el layout barajado del participante.
    if opcion_idx is not None:
        disp = ((p.layout_json or {}).get("opt_map") or {}).get(str(ordinal)) or item["letras"]
        try:
            elegida = str(disp[int(opcion_idx)]).strip().upper()
        except (IndexError, ValueError, TypeError):
            raise conflict("Opción no válida.")
    else:
        elegida = str(respuesta or "").strip().upper()[:10]

    correcta = elegida == item["correcta"]
    db.add(RespuestaVivo(sesion_id=s.id, participante_id=p.id, question_number=ordinal,
                         respuesta=elegida, correcta=correcta))
    if s.modo_ritmo == RITMO_ALUMNO:
        p.progreso = (p.progreso or 0) + 1
    db.commit()

    out = {"question_number": ordinal, "respuesta": elegida, "correcta": correcta,
           "fin": (s.modo_ritmo == RITMO_ALUMNO and p.progreso >= len(items))}
    if s.revelar_correccion:                    # feedback inmediato (config del docente)
        out["correcta_letra"] = item["correcta"]
        textos = {str(o.get("letra", "")).strip().upper(): o.get("texto", "")
                  for o in item["opciones"]}
        if textos.get(item["correcta"]):
            out["correcta_texto"] = textos[item["correcta"]]
        if not correcta and item.get("justificacion"):
            out["justificacion"] = item["justificacion"]
    return out


def extender_tiempo(db, codigo: str, participante_id, extra_min: int, reabrir: bool = True) -> dict:
    """El docente REABRE y/o EXTIENDE el tiempo de UN alumno (llegó tarde / se le agotó).
    Semántica intuitiva: le deja `extra_min` minutos CONTADOS DESDE AHORA (no importa cuánto
    se pasó). Si la sala no tiene temporizador, solo reabre. Decisión humana, registrada."""
    s = _sesion(db, codigo)
    p = _participante_por_id(db, s, participante_id)
    extra_min = max(0, int(extra_min or 0))
    dur = int(getattr(s, "duracion_min", 0) or 0)
    ini = getattr(s, "timer_inicio_ts", None)
    if dur > 0 and ini:
        base_sin_extra = int(ini) + dur * 60           # plazo del alumno SIN su extensión
        objetivo = _ahora() + extra_min * 60           # queremos que venza dentro de `extra_min`
        p.tiempo_extra_seg = max(0, objetivo - base_sin_extra)
    if reabrir:
        p.bloqueado = False
        p.bloqueado_motivo = None
    db.add(EventoIntegridad(sesion_id=s.id, participante_id=p.id, tipo="tiempo_extendido",
                            duration_ms=extra_min * 60000,
                            meta_json={"extra_min": extra_min, "reabierto": bool(reabrir)}))
    db.commit(); db.refresh(p)
    return {"participante_id": str(p.id), "alias": p.alias,
            "segundos_restantes": segundos_restantes(s, p),
            "tiempo_extra_seg": int(getattr(p, "tiempo_extra_seg", 0) or 0),
            "bloqueado": bool(p.bloqueado)}


def _config_dict(s) -> dict:
    return {"modo_ritmo": s.modo_ritmo, "retro_alumno": s.retro_alumno,
            "revelar_correccion": s.revelar_correccion,
            "mascota_motivacional": bool(getattr(s, "mascota_motivacional", True)),
            "duracion_min": int(getattr(s, "duracion_min", 0) or 0),
            "timer_activo": bool(int(getattr(s, "duracion_min", 0) or 0) > 0 and getattr(s, "timer_inicio_ts", None)),
            "shuffle_preguntas": s.shuffle_preguntas, "shuffle_opciones": s.shuffle_opciones,
            "requiere_seb": bool(getattr(s, "requiere_seb", False))}


# ── lecturas (polling) ───────────────────────────────────────────────────────────────
def estado(db, codigo: str) -> dict:
    s = _sesion(db, codigo)
    n_part = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).count()
    n_resp = (db.query(RespuestaVivo).filter(
        RespuestaVivo.sesion_id == s.id,
        RespuestaVivo.question_number == s.pregunta_actual).count()
        if s.pregunta_actual else 0)
    return {"codigo": s.codigo, "estado": s.estado, "pregunta_actual": s.pregunta_actual,
            "n_preguntas": s.n_preguntas, "n_participantes": n_part,
            "respuestas_pregunta_actual": n_resp, **_config_dict(s)}


def estado_participante(db, codigo: str, participante_id, token: str) -> dict:
    """Vista del ALUMNO: su pregunta actual (enunciado + opciones barajadas) y su progreso.

    En ritmo-docente la pregunta la marca la sesión; en ritmo-alumno, la siguiente de su
    propia secuencia. Nunca revela la respuesta correcta antes de responder.
    """
    s = _sesion(db, codigo)
    p = _participante(db, s, participante_id, token)
    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    n = len(items)
    respondidas = db.query(RespuestaVivo).filter(RespuestaVivo.participante_id == p.id).count()

    restante = segundos_restantes(s, p)
    base = {"estado": s.estado, "modo_ritmo": s.modo_ritmo, "alias": p.alias,
            "n_preguntas": n, "respondidas": respondidas,
            "progreso_pct": round(respondidas / n * 100) if n else 0,
            "bloqueado": bool(getattr(p, "bloqueado", False)),
            "bloqueado_motivo": getattr(p, "bloqueado_motivo", None),
            "retro_alumno": bool(getattr(s, "retro_alumno", False)),
            "duracion_min": int(getattr(s, "duracion_min", 0) or 0),
            "segundos_restantes": (max(0, restante) if restante is not None else None),
            "tiempo_agotado": _tiempo_agotado(s, p)}

    if getattr(p, "bloqueado", False):
        base["pregunta"] = None                 # el docente cerró la prueba a este alumno
        return base
    # Temporizador agotado: se cierra solo (como si hubiera terminado); ve su resultado.
    if base["tiempo_agotado"] and s.estado == ESTADO_ACTIVA:
        base["pregunta"] = None
        base["fin"] = True
        return base
    if s.estado in (ESTADO_LOBBY,) or (s.estado != ESTADO_ACTIVA and s.modo_ritmo == RITMO_DOCENTE):
        base["pregunta"] = None                 # esperando (lobby o pausa en ritmo-docente)
        return base
    if s.estado == ESTADO_CERRADA:
        base["pregunta"] = None
        return base

    ordinal = _ordinal_actual(s, p, n)
    if not (1 <= ordinal <= n):
        base["pregunta"] = None                 # terminó su recorrido (self-paced)
        base["fin"] = True
        return base
    item = items[ordinal - 1]
    ya = db.query(RespuestaVivo).filter(
        RespuestaVivo.participante_id == p.id,
        RespuestaVivo.question_number == ordinal).first()

    # Opciones en el orden MOSTRADO del participante; texto si hay banco de ítems.
    disp = ((p.layout_json or {}).get("opt_map") or {}).get(str(ordinal)) or item["letras"]
    textos = {str(o.get("letra", "")).strip().upper(): o.get("texto", "") for o in item["opciones"]}
    opciones = [{"pos": i, "texto": textos.get(letra, "")} for i, letra in enumerate(disp)]

    base["pregunta"] = {
        "ordinal": ordinal,
        "numero_mostrado": (respondidas + 1) if s.modo_ritmo == RITMO_ALUMNO else ordinal,
        "enunciado": item["enunciado"], "tiene_contenido": bool(item["enunciado"]),
        "imagen": item.get("imagen"),
        "opciones": opciones, "ya_respondida": bool(ya),
    }
    if ya and s.revelar_correccion:
        base["pregunta"]["mi_respuesta"] = ya.respuesta
        base["pregunta"]["correcta"] = ya.correcta
    return base


def resultados(db, codigo: str) -> dict:
    s = _sesion(db, codigo)
    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    n = len(items)
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()

    por_pregunta = []
    for i, item in enumerate(items, start=1):
        rs = [r for r in resp if r.question_number == i]
        dist: dict[str, int] = {}
        for r in rs:
            dist[r.respuesta] = dist.get(r.respuesta, 0) + 1
        ncnt = len(rs)
        n_ok = sum(1 for r in rs if r.correcta)
        # Distribución por alternativa (para el drill-down): texto + n + % + si es la correcta.
        textos = {str(o.get("letra", "")).strip().upper(): o.get("texto", "") for o in item["opciones"]}
        letras = item["letras"] if item["tiene_opciones"] else ["A", "B", "C", "D"]
        opciones = [{"letra": L, "texto": textos.get(L, ""), "n": dist.get(L, 0),
                     "pct": round(dist.get(L, 0) / ncnt * 100, 1) if ncnt else 0.0,
                     "correcta": L == item["correcta"]} for L in letras]
        por_pregunta.append({
            "pregunta": i, "correcta": item["correcta"],
            "n_respuestas": ncnt, "n_correctas": n_ok, "n_incorrectas": ncnt - n_ok,
            "pct_correcta": round(n_ok / ncnt * 100, 1) if ncnt else 0.0,
            "pct_incorrecta": round((ncnt - n_ok) / ncnt * 100, 1) if ncnt else 0.0,
            "distribucion": dist, "opciones": opciones,
            "enunciado": item["enunciado"], "justificacion": item["justificacion"],
            "ra": item["ra"], "bloom": item["bloom"], "unidad": item["unidad"],
        })

    # Grilla alumno × pregunta (estilo "Live Results"): cada celda = su letra + acierto.
    por_part: dict[uuid.UUID, dict[int, RespuestaVivo]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = r
    grid, ranking = [], []
    for p in parts:
        celdas = por_part.get(p.id, {})
        respuestas = {str(qn): {"letra": r.respuesta, "correcta": r.correcta}
                      for qn, r in celdas.items()}
        aciertos = sum(1 for r in celdas.values() if r.correcta)
        respondidas = len(celdas)
        grid.append({"participante": p.alias, "respondidas": respondidas,
                     "progreso_pct": round(respondidas / n * 100) if n else 0,
                     "aciertos": aciertos, "respuestas": respuestas})
        ranking.append({"participante": p.alias, "aciertos": aciertos, "respondidas": respondidas})
    grid.sort(key=lambda x: x["participante"].lower())
    ranking.sort(key=lambda x: (-x["aciertos"], x["respondidas"]))

    return {"codigo": s.codigo, "estado": s.estado, "n_participantes": len(parts),
            "n_preguntas": n, "por_pregunta": por_pregunta, "ranking": ranking,
            "grid": grid, **_config_dict(s)}


def mi_resultado(db, codigo: str, participante_id, token: str) -> dict:
    """Resultado final del ALUMNO al cerrar: nota, aprobación, % logro y detalle por pregunta
    con justificación de las incorrectas + focos de repaso (RA/Bloom/unidad). Reutiliza el
    MISMO motor de nota que el escaneo (result_service). Se entrega solo si el docente activó
    la retroalimentación al alumno.
    """
    s = _sesion(db, codigo)
    p = _participante(db, s, participante_id, token)
    if not s.retro_alumno:
        return {"habilitado": False, "estado": s.estado}

    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    mis = {r.question_number: r for r in db.query(RespuestaVivo).filter(
        RespuestaVivo.participante_id == p.id).all()}

    peso_total = sum(it["weight"] for it in items) or 1.0
    peso_ok = sum(it["weight"] for it in items
                  if mis.get(it["ordinal"]) and mis[it["ordinal"]].correcta)
    pct = round(peso_ok / peso_total * 100, 1)

    ass = db.query(Assessment).filter(Assessment.id == uuid.UUID(s.assessment_id)).first()
    escala = getattr(ass, "grading_scale", "chile_1_7") or "chile_1_7"
    umbral = float(getattr(ass, "passing_threshold", 60.0) or 60.0)
    nota, nota_label, aprobado = result_service.calculate_grade(pct, escala, umbral)

    detalle = []
    for it in items:
        r = mis.get(it["ordinal"])
        ok = bool(r and r.correcta)
        d = {"numero": it["ordinal"], "correcta_letra": it["correcta"],
             "mi_letra": r.respuesta if r else None, "ok": ok, "respondida": bool(r),
             "ra": it["ra"], "bloom": it["bloom"], "unidad": it["unidad"],
             "enunciado": it["enunciado"]}
        if not ok:                              # justificación real solo en las falladas
            d["justificacion"] = it.get("justificacion")
        detalle.append(d)

    n_ok = sum(1 for it in items if mis.get(it["ordinal"]) and mis[it["ordinal"]].correcta)
    return {
        "habilitado": True, "estado": s.estado, "alias": p.alias,
        "n_preguntas": len(items), "correctas": n_ok,
        "incorrectas": len(items) - n_ok, "pct_logro": pct,
        "nota": nota, "nota_label": nota_label, "aprobado": aprobado,
        "escala": escala, "umbral": umbral,
        "revelar": s.revelar_correccion, "detalle": detalle,
        "mascota_motivacional": bool(getattr(s, "mascota_motivacional", True)),
    }


# ── informe de la sala (psicometría + resultados de aprendizaje) ──────────────────────
def _media(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = _media(xs), _media(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return (num / (dx * dy)) if dx > 0 and dy > 0 else 0.0


def _kr20(matriz, ps):
    """KR-20 (fiabilidad de consistencia interna para ítems dicotómicos), Python puro."""
    k = len(ps)
    if k < 2 or not matriz:
        return None
    totales = [sum(fila) for fila in matriz]
    n = len(totales)
    mt = _media(totales)
    var_total = sum((t - mt) ** 2 for t in totales) / n  # varianza poblacional
    if var_total <= 0:
        return 0.0
    sum_pq = sum(p * (1 - p) for p in ps)
    return round((k / (k - 1)) * (1 - sum_pq / var_total), 3)


def informe_en_vivo(db, codigo: str) -> dict:
    """Informe integral de la sala: psicometría clásica (dificultad, discriminación, KR-20)
    y resultados por Resultado de Aprendizaje (RA). Python puro (sin numpy), sobre la matriz
    de correctitud participante×ítem. Base para exportar a Word/PDF/Excel."""
    s = _sesion(db, codigo)
    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    n_items = len(items)
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()
    por_part: dict[uuid.UUID, dict[int, RespuestaVivo]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = r

    # Matriz 0/1 de quienes respondieron al menos una (evita filas todo-cero que distorsionan).
    matriz, aliases = [], []
    for p in parts:
        celdas = por_part.get(p.id, {})
        if not celdas:
            continue
        matriz.append([1 if (celdas.get(i) and celdas[i].correcta) else 0 for i in range(1, n_items + 1)])
        aliases.append(p.alias)
    n_estud = len(matriz)

    # Dificultad p (proporción de aciertos) y discriminación (biserial-puntual corregida).
    ps, items_stat = [], []
    for j, it in enumerate(items):
        col = [fila[j] for fila in matriz]
        p = _media(col)
        ps.append(p)
        resto = [sum(fila[q] for q in range(n_items) if q != j) for fila in matriz]  # total sin el ítem
        disc = round(_pearson(col, resto), 3)
        items_stat.append({
            "n": it["ordinal"], "enunciado": it["enunciado"] or f"Pregunta {it['ordinal']}",
            "imagen": it.get("imagen"),
            "correcta": it["correcta"], "dificultad_p": round(p, 3),
            "discriminacion": disc, "ra": it["ra"], "bloom": it["bloom"], "unidad": it["unidad"],
            "alerta": ("muy fácil" if p >= 0.9 else "muy difícil" if p <= 0.2 else
                       "baja discriminación" if (n_estud >= 5 and disc < 0.2) else ""),
        })
    kr20 = _kr20(matriz, ps)

    # Resultados por RA (agrupa ítems por learning_outcome_id; logro = dificultad media del bloque).
    por_ra_map: dict[str, list] = {}
    for j, it in enumerate(items):
        clave = it["ra"] or "Sin RA asignado"
        por_ra_map.setdefault(clave, []).append(j)
    por_ra = []
    for ra, idxs in por_ra_map.items():
        logro = round(_media([ps[j] for j in idxs]) * 100, 1)
        nivel = ("Logrado" if logro >= 80 else "En desarrollo" if logro >= 60 else "Inicial")
        por_ra.append({"ra": ra, "n_items": len(idxs), "items": [items[j]["ordinal"] for j in idxs],
                       "logro_pct": logro, "nivel": nivel})
    por_ra.sort(key=lambda x: x["logro_pct"])

    # Estudiantes: aciertos, % y nota (mismo motor que el escaneo).
    ass = db.query(Assessment).filter(Assessment.id == uuid.UUID(s.assessment_id)).first()
    escala = getattr(ass, "grading_scale", "chile_1_7") or "chile_1_7"
    umbral = float(getattr(ass, "passing_threshold", 60.0) or 60.0)
    peso_total = sum(it["weight"] for it in items) or 1.0
    estudiantes = []
    for alias, fila in zip(aliases, matriz):
        peso_ok = sum(items[j]["weight"] for j in range(n_items) if fila[j])
        pct = round(peso_ok / peso_total * 100, 1)
        nota, _lbl, aprob = result_service.calculate_grade(pct, escala, umbral)
        estudiantes.append({"alias": alias, "aciertos": sum(fila), "n_items": n_items,
                            "pct": pct, "nota": nota, "aprobado": aprob})
    estudiantes.sort(key=lambda x: -x["aciertos"])
    aprobados = sum(1 for e in estudiantes if e["aprobado"])

    return {
        "codigo": s.codigo, "evaluacion": getattr(ass, "name", "Evaluación"),
        "curso_id": str(getattr(ass, "course_id", "")) if ass else "",
        "n_participantes": n_estud, "n_items": n_items,
        "kr20": kr20, "dificultad_media": round(_media(ps) * 100, 1) if ps else 0.0,
        "escala": escala, "umbral": umbral,
        "aprobados": aprobados, "reprobados": n_estud - aprobados,
        "nota_media": round(_media([e["nota"] for e in estudiantes]), 2) if estudiantes else None,
        "items": items_stat, "por_ra": por_ra, "estudiantes": estudiantes,
    }


def _interp_kr20(v):
    if v is None:
        return "no estimable (pocos datos)"
    return ("excelente" if v >= 0.9 else "buena" if v >= 0.8 else "aceptable" if v >= 0.7
            else "cuestionable" if v >= 0.6 else "baja")


def _grafico_dist_png(rows):
    """Gráfico de barras REAL (PNG con Pillow) de la distribución de notas. Uniforme en PDF/DOCX/XLSX."""
    import io as _io
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    if not rows:
        return None
    W, H = 640, 340
    ml, mr, mt, mb = 48, 20, 28, 66
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=14); fbold = ImageFont.load_default(size=15)
    except Exception:
        font = ImageFont.load_default(); fbold = font
    labels = [str(r[0]) for r in rows]
    vals = [int(r[1]) for r in rows]
    mx = max(vals + [1])
    pw, ph = W - ml - mr, H - mt - mb
    n = len(vals) or 1
    gap = pw / n
    bw = gap * 0.6
    # ejes
    d.line([(ml, mt), (ml, mt + ph)], fill="#cbd5e1", width=1)
    d.line([(ml, mt + ph), (ml + pw, mt + ph)], fill="#cbd5e1", width=1)
    # marcas del eje Y (0..mx en enteros, hasta 5 divisiones)
    div = max(1, mx)
    paso = 1 if div <= 5 else max(1, round(div / 5))
    v = 0
    while v <= mx:
        y = mt + ph - (v / mx) * ph
        d.line([(ml - 3, y), (ml + pw, y)], fill="#eef2f7", width=1)
        d.text((ml - 6, y), str(v), fill="#94a3b8", font=font, anchor="rm")
        v += paso
    colores = ["#e0555a", "#d19a2e", "#31D6CC", "#34e5a8", "#6F5BD9", "#0F8B8D"]
    for i, val in enumerate(vals):
        x0 = ml + gap * i + (gap - bw) / 2
        bh = (val / mx) * ph
        y0 = mt + ph - bh
        d.rectangle([x0, y0, x0 + bw, mt + ph], fill=colores[i % len(colores)])
        if val:
            d.text((x0 + bw / 2, y0 - 15), str(val), fill="#334155", font=fbold, anchor="mm")
        corta = labels[i].split(" (")[0]
        d.text((x0 + bw / 2, mt + ph + 8), corta, fill="#475569", font=font, anchor="ma")
    buf = _io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


def _dist_notas(estudiantes, escala):
    """Histograma de notas por rango (barras de bloques, robusto en PDF/DOCX/XLSX). Devuelve
    filas [rango, n, barra] + una frase con el rango modal."""
    import math
    notas = [e["nota"] for e in estudiantes if e.get("nota") is not None]
    if not notas:
        return {"rows": [], "texto": "Sin notas para graficar.", "n": 0}
    if escala == "chile_1_7":
        bandas = [("Reprobado (1,0–3,9)", 1.0, 3.95), ("Suficiente (4,0–4,9)", 3.95, 4.95),
                  ("Bueno (5,0–5,9)", 4.95, 5.95), ("Muy bueno (6,0–7,0)", 5.95, 7.01)]
    else:
        lo, hi = min(notas), max(notas)
        paso = max(1.0, (hi - lo) / 5 or 1.0)
        bandas, x = [], math.floor(lo)
        while x < hi + 0.01:
            bandas.append((f"{x:.0f}–{x + paso:.0f}", float(x), x + paso)); x += paso
    conteo = [(lbl, sum(1 for v in notas if a <= v < b)) for lbl, a, b in bandas]
    mx = max((n for _, n in conteo), default=0) or 1
    rows = [[lbl, n, "█" * round(n / mx * 18)] for lbl, n in conteo]
    modal = max(conteo, key=lambda x: x[1])
    return {"rows": rows, "texto": f"La mayoría se ubicó en «{modal[0]}» ({modal[1]} de {len(notas)}).", "n": len(notas)}


def _intg_str(pi):
    """Resumen breve de integridad de un alumno para la tabla del docente."""
    if not pi:
        return "—"
    niv = {"revisar": "Revisar", "aviso": "Aviso", "ok": "OK"}.get(pi["nivel"], pi["nivel"])
    partes = []
    if pi.get("salidas_foco"):
        partes.append(f"{pi['salidas_foco']} salida(s)/{pi['oculto_s']}s")
    if pi.get("respondidas_tras_ausencia"):
        partes.append("respondió tras ausentarse")
    if pi.get("posibles_capturas"):
        partes.append("posible captura")
    if pi.get("pegados"):
        partes.append("pegó texto")
    if pi.get("otra_ventana_encima"):
        partes.append("otra ventana")
    if pi.get("desconexiones"):
        partes.append(f"conexión {pi['desconexiones']}× (involunt.)")
    return niv + (": " + ", ".join(partes) if partes else "")


def informe_payload(db, codigo: str, formato: str, perfil: str = "docente") -> dict:
    """Arma el payload para exportador_service. Dos perfiles:
      - 'docente': bajada pedagógica (interpretación en lenguaje claro), distribución de notas por
        rango, tabla de estudiantes con puntaje/nota + resumen de integridad por alumno.
      - 'investigador': el pool psicométrico completo (TCT por ítem, discriminación, KR-20, RA,
        tabla de integridad detallada) + nota metodológica.
    """
    inf = informe_en_vivo(db, codigo)
    perfil = "investigador" if str(perfil).lower().startswith("invest") else "docente"

    # Integridad por alumno (para fusionar con el resultado y para la tabla detallada).
    _niv = {"revisar": "Revisar", "aviso": "Aviso", "ok": "OK"}
    intg_por_alias, _intg = {}, {"participantes": []}
    try:
        from app.services import integridad_service
        _intg = integridad_service.resumen_participantes(db, _sesion(db, codigo))
        for pi in _intg["participantes"]:
            intg_por_alias[pi["alias"]] = pi
    except Exception:
        pass

    nota_intg = (
        "Evidencia OBJETIVA de actividad de ventana durante la evaluación (Page Visibility, foco, "
        "pantalla completa, copiar/pegar, menú contextual), con hora de servidor e inmutable. "
        "IMPORTANTE: se distingue SALIR de la prueba (cambiar de pestaña/app: voluntario) de los "
        "PROBLEMAS DE CONEXIÓN (caídas de wifi/datos: involuntario, no penaliza). NO constituye por "
        "sí sola prueba de copia; su interpretación es humana y no invalida la evaluación de forma "
        "automática (proporcionalidad y debido proceso; Ley 21.719).")

    # ══════════════ PERFIL DOCENTE ══════════════
    if perfil == "docente":
        dist = _dist_notas(inf["estudiantes"], inf["escala"])
        n = inf["n_participantes"] or 0
        aprob_pct = round(inf["aprobados"] / n * 100) if n else 0
        dificiles = [it for it in inf["items"] if it["dificultad_p"] <= 0.5]
        faciles = [it for it in inf["items"] if it["dificultad_p"] >= 0.85]
        ra_debil = [r for r in inf["por_ra"] if r["logro_pct"] < 60]
        kr = inf["kr20"]
        interp = (
            f"En esta evaluación en vivo respondieron **{n}** estudiante(s). La nota promedio del "
            f"curso fue **{inf['nota_media']}** (escala {inf['escala']}, aprobación desde {inf['umbral']}% "
            f"de logro), y **aprobó el {aprob_pct}%** ({inf['aprobados']} de {n}). {dist['texto']}\n"
            + (f"Las preguntas que más costaron fueron "
               + ", ".join(f"P{it['n']} ({round(it['dificultad_p'] * 100)}% de acierto)" for it in dificiles[:4])
               + ". Conviene **reforzar** esos contenidos" +
               (" — en especial los resultados de aprendizaje: " +
                ", ".join(f"{r['ra']} ({r['logro_pct']}%)" for r in ra_debil[:3]) if ra_debil else "")
               + ".\n" if dificiles else "El curso resolvió bien la mayoría de las preguntas.\n")
            + (f"Dominaron con soltura " + ", ".join(f"P{it['n']}" for it in faciles[:4]) + ".\n" if faciles else "")
            + (f"La prueba mostró una **consistencia {_interp_kr20(kr)}** (KR-20 = {kr}): "
               "sus preguntas miden de forma coherente el mismo aprendizaje.\n" if kr is not None else "")
            + "**Sugerencia pedagógica:** retomar los contenidos débiles con un repaso breve o una "
            "actividad focalizada antes de avanzar; reservar las preguntas dominadas para consolidación.")

        dist_png = _grafico_dist_png(dist["rows"])
        imagenes = ([{"titulo": "Distribución de notas por rango", "png": dist_png}] if dist_png else [])
        t_dist = {"titulo": "Distribución de notas por rango (tabla)",
                  "headers": ["Rango", "N° estudiantes"], "rows": [[r[0], r[1]] for r in dist["rows"]]}
        t_ra_d = {"titulo": "Logro por Resultado de Aprendizaje (RA)",
                  "headers": ["RA", "Logro de la clase %", "Nivel"],
                  "rows": [[r["ra"], r["logro_pct"], r["nivel"]] for r in inf["por_ra"]]}
        t_est_d = {"titulo": "Estudiantes · puntaje, nota e integridad",
                   "headers": ["Estudiante", "Aciertos", "% logro", "Nota", "Aprobado", "Integridad"],
                   "rows": [[e["alias"], f"{e['aciertos']}/{e['n_items']}", e["pct"], e["nota"],
                             "Sí" if e["aprobado"] else "No", _intg_str(intg_por_alias.get(e["alias"]))]
                            for e in inf["estudiantes"]]}
        t_ref = {"titulo": "Preguntas a reforzar",
                 "headers": ["Pregunta", "% de acierto", "RA", "Correcta"],
                 "rows": [["P" + str(it["n"]), round(it["dificultad_p"] * 100), it["ra"] or "—", it["correcta"]]
                          for it in dificiles[:8]]}

        if formato == "xlsx":
            return {"imagenes": imagenes, "hojas": [
                {"nombre": "Interpretación", "headers": ["Informe pedagógico"],
                 "rows": [[interp.replace("**", "")]]},
                {"nombre": "Distribución notas", "headers": t_dist["headers"], "rows": t_dist["rows"]},
                {"nombre": "Estudiantes", "headers": t_est_d["headers"], "rows": t_est_d["rows"]},
                {"nombre": "Por RA", "headers": t_ra_d["headers"], "rows": t_ra_d["rows"]},
                {"nombre": "A reforzar", "headers": t_ref["headers"], "rows": t_ref["rows"]}]}
        return {"titulo": f"Informe pedagógico · {inf['evaluacion']} · Sala {inf['codigo']}",
                "secciones": [
                    {"heading": "Lectura pedagógica de los resultados", "nivel": 1, "texto": interp},
                    {"heading": "Integridad · nota de uso", "nivel": 2, "texto": nota_intg}],
                "imagenes": imagenes,
                "tablas": [t_dist, t_est_d, t_ra_d, t_ref]}

    # ══════════════ PERFIL INVESTIGADOR (pool completo) ══════════════
    titulo = f"Informe de resultados · {inf['evaluacion']} · Sala {inf['codigo']}"
    t_items = {"titulo": "Análisis de ítems (TCT)",
               "headers": ["N°", "Correcta", "Dificultad p", "Discriminación", "RA", "Bloom", "Alerta"],
               "rows": [[it["n"], it["correcta"], it["dificultad_p"], it["discriminacion"],
                         it["ra"] or "—", it["bloom"] or "—", it["alerta"] or "ok"] for it in inf["items"]]}
    t_ra = {"titulo": "Resultados por Resultado de Aprendizaje (RA)",
            "headers": ["RA", "N° ítems", "Logro clase %", "Nivel"],
            "rows": [[r["ra"], r["n_items"], r["logro_pct"], r["nivel"]] for r in inf["por_ra"]]}
    t_est = {"titulo": "Estudiantes", "headers": ["Participante", "Aciertos", "% logro", "Nota", "Aprobado"],
             "rows": [[e["alias"], f"{e['aciertos']}/{e['n_items']}", e["pct"], e["nota"],
                       "Sí" if e["aprobado"] else "No"] for e in inf["estudiantes"]]}

    # Integridad (LV8): evidencia de actividad de ventana como MEDIO DE PRUEBA en el informe,
    # independiente de que el docente cerrara la sala o sancionara. Interpretación humana.
    _niv = {"revisar": "Revisar", "aviso": "Aviso", "ok": "OK"}
    try:
        from app.services import integridad_service
        _intg = integridad_service.resumen_participantes(db, _sesion(db, codigo))
        t_intg = {"titulo": "Integridad · evidencia de actividad de ventana",
                  "headers": ["Participante", "Nivel", "Salió de la prueba (veces)", "Oculto (s)",
                              "Ausencia en preguntas", "Respondió tras ausentarse",
                              "Otra ventana encima", "Ventana reducida", "Posible captura",
                              "Pegados", "Salió pant. completa", "Menú contextual",
                              "Problemas de conexión", "Sin red (s)", "Cerrada por docente"],
                  "rows": [[p["alias"], _niv.get(p["nivel"], p["nivel"]), p["salidas_foco"],
                            p["oculto_s"],
                            ", ".join("P" + str(q) for q in p.get("preguntas_ausencia", [])) or "—",
                            ", ".join("P" + str(x["pregunta"]) + ("✓" if x["correcta"] else "✗")
                                      for x in p.get("respondidas_tras_ausencia", [])) or "—",
                            p.get("otra_ventana_encima", 0), p.get("ventana_reducida", 0),
                            p.get("posibles_capturas", 0),
                            p["pegados"], p["salidas_pantalla_completa"], p["menus_contextual"],
                            p.get("desconexiones", 0), p.get("offline_s", 0),
                            "Sí" if p["bloqueado"] else "No"]
                           for p in _intg["participantes"]]}
    except Exception:
        t_intg = {"titulo": "Integridad", "headers": ["Participante"], "rows": []}
    nota_intg = (
        "Evidencia OBJETIVA de actividad de ventana durante la evaluación (Page Visibility, foco, "
        "pantalla completa, copiar/pegar, menú contextual), con hora de servidor e inmutable. "
        "IMPORTANTE: se distingue SALIR de la prueba (cambiar de pestaña/app: voluntario) de los "
        "PROBLEMAS DE CONEXIÓN (caídas de wifi/datos: involuntario, columna aparte, no penaliza). "
        "NO constituye por sí sola prueba de copia; su interpretación es humana y no invalida la "
        "evaluación de forma automática (proporcionalidad y debido proceso; Ley 21.719). No se "
        "detecta de forma fiable el screenshot del sistema, la foto con otro dispositivo ni el uso "
        "de IA en un equipo aparte.")

    if formato == "xlsx":
        resumen = {"nombre": "Resumen", "headers": ["Métrica", "Valor"], "rows": [
            ["Evaluación", inf["evaluacion"]], ["Sala", inf["codigo"]],
            ["Participantes", inf["n_participantes"]], ["Ítems", inf["n_items"]],
            ["KR-20", inf["kr20"]], ["Dificultad media %", inf["dificultad_media"]],
            ["Nota media", inf["nota_media"]], ["Aprobados", inf["aprobados"]],
            ["Reprobados", inf["reprobados"]]]}
        return {"hojas": [resumen,
                          {"nombre": "Items", "headers": t_items["headers"], "rows": t_items["rows"]},
                          {"nombre": "Por RA", "headers": t_ra["headers"], "rows": t_ra["rows"]},
                          {"nombre": "Estudiantes", "headers": t_est["headers"], "rows": t_est["rows"]},
                          {"nombre": "Integridad", "headers": t_intg["headers"], "rows": t_intg["rows"]}]}

    resumen_txt = (
        f"Evaluación: {inf['evaluacion']}. Sala en vivo {inf['codigo']}. "
        f"Participantes: {inf['n_participantes']}. Ítems de alternativas: {inf['n_items']}. "
        f"Fiabilidad KR-20 = {inf['kr20']} ({_interp_kr20(inf['kr20'])}). "
        f"Dificultad media = {inf['dificultad_media']}% de aciertos. "
        f"Nota media = {inf['nota_media']} (escala {inf['escala']}, exigencia {inf['umbral']}%). "
        f"Aprobados: {inf['aprobados']} · Reprobados: {inf['reprobados']}.")
    metodo = ("Dificultad (p) = proporción de aciertos por ítem (0–1). Discriminación = correlación "
              "biserial-puntual corregida del ítem con el total sin ese ítem (≥0,30 buena). KR-20 = "
              "consistencia interna para ítems dicotómicos. El logro por RA es la dificultad media de "
              "sus ítems. **Gobernanza:** el modo en vivo aporta evidencia de medición; no altera "
              "calificaciones oficiales (G1).")
    return {"titulo": titulo, "secciones": [
        {"heading": "Resumen ejecutivo", "nivel": 1, "texto": resumen_txt},
        {"heading": "Nota metodológica", "nivel": 2, "texto": metodo},
        {"heading": "Integridad · nota de uso", "nivel": 2, "texto": nota_intg}],
        "tablas": [t_ra, t_items, t_est, t_intg]}


# ── banco de ítems (contenido para el modo en vivo digital) ───────────────────────────
def contenido_items(db, assessment_id, version: str = "A") -> dict:
    """Contenido actual (enunciado/opciones/justificación) por pregunta, para editarlo."""
    items = _items_contenido(db, assessment_id, version)
    return {"version": version.upper(), "n_preguntas": len(items),
            "items": [{"question_number": it["qn"], "ordinal": it["ordinal"],
                       "correcta": it["correcta"], "enunciado": it["enunciado"] or "",
                       "imagen": it.get("imagen"),
                       "opciones": it["opciones"] or [], "justificacion": it["justificacion"] or "",
                       "ra": it["ra"], "bloom": it["bloom"], "unidad": it["unidad"]}
                      for it in items]}


def guardar_contenido_items(db, assessment_id, version: str, items: list) -> dict:
    """Persiste enunciado/opciones/justificación en los ítems de alternativas existentes.

    NO toca la letra correcta, el peso ni la validación de la pauta: solo enriquece el
    contenido para mostrar la pregunta en el teléfono y justificar. Empareja por número de
    pregunta + versión. Devuelve cuántos ítems se actualizaron.
    """
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        raise not_found("La evaluación no tiene pauta.")
    por_qn = {}
    for it in ak.items:
        if it.version.upper() == version.upper() and it.question_type == QUESTION_TYPE_MULTIPLE_CHOICE:
            por_qn[int(it.question_number)] = it

    n = 0
    for entrada in (items or []):
        try:
            qn = int(entrada.get("question_number"))
        except (TypeError, ValueError):
            continue
        it = por_qn.get(qn)
        if not it:
            continue
        if "enunciado" in entrada:
            it.enunciado = (str(entrada.get("enunciado") or "").strip() or None)
        if "imagen" in entrada:
            it.enunciado_imagen = _limpiar_imagen(entrada.get("imagen"))
        if "justificacion" in entrada:
            it.justificacion = (str(entrada.get("justificacion") or "").strip() or None)
        if "opciones" in entrada:
            ops = []
            for o in (entrada.get("opciones") or []):
                letra = str(o.get("letra", "")).strip().upper()[:2]
                texto = str(o.get("texto", "")).strip()
                if letra:
                    ops.append({"letra": letra, "texto": texto})
            it.opciones_json = ops or None
        # Corregir la PAUTA (letra correcta) ante un error involuntario del import. Compuerta docente.
        if entrada.get("correcta"):
            c = str(entrada.get("correcta")).strip().upper()[:1]
            if c:
                it.correct_answer = c
        n += 1
    ak.is_valid = True          # sigue validada tras editar contenido/pauta
    ak.status = "validada"
    db.commit()
    return {"actualizados": n}


def eliminar_item(db, assessment_id, version: str, question_number: int) -> dict:
    """Elimina UNA pregunta de alternativas de la pauta y RENUMERA las restantes 1..N
    (los ordinales deben quedar contiguos). Mantiene sincronizado n_questions. Compuerta docente."""
    from app.models.answer_key import QUESTION_TYPE_OPEN_RESPONSE
    version = (version or "A").upper()
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        raise not_found("La evaluación no tiene pauta.")
    mc = sorted([it for it in ak.items
                 if it.version.upper() == version and it.question_type == QUESTION_TYPE_MULTIPLE_CHOICE],
                key=lambda x: int(x.question_number))
    objetivo = next((it for it in mc if int(it.question_number) == int(question_number)), None)
    if not objetivo:
        raise not_found("No existe esa pregunta.")
    db.delete(objetivo)
    db.flush()
    # renumerar contiguo 1..N conservando el orden
    restantes = [it for it in mc if it is not objetivo]
    for i, it in enumerate(restantes, start=1):
        it.question_number = i
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if a is not None:
        a.n_questions = len(restantes)
        if getattr(a, "version_count", None) is not None:
            a.version_count = len(restantes)
    ak.is_valid = bool(restantes)
    ak.status = "validada" if restantes else "draft"
    db.commit()
    return {"eliminados": 1, "restantes": len(restantes)}


def importar_preguntas(db, assessment_id, version: str, items: list) -> dict:
    """Crea la PAUTA de alternativas a partir de preguntas estructuradas (enunciado, opciones,
    letra correcta, justificación) — el módulo de importación de preguntas del modo en vivo.

    A diferencia de guardar_contenido_items (que solo rellena ítems ya existentes), este CREA
    los ítems con su letra correcta y VALIDA la pauta, de modo que la sala en vivo pueda
    iniciarse. Reemplaza los ítems de alternativas de esa versión (idempotente al reimportar);
    no toca las preguntas de desarrollo (open_response) ni sus rúbricas. Compuerta humana (G1):
    el docente revisó las propuestas antes de confirmar.
    """
    from app.models.answer_key import AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE
    items = items or []
    if not items:
        raise conflict("No hay preguntas para importar.")
    version = (version or "A").upper()
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        ak = AnswerKey(assessment_id=str(assessment_id), is_valid=False, status="draft")
        db.add(ak); db.flush()
    # Borra los ítems de alternativas previos de esa versión (conserva open_response/rúbricas).
    for it in list(ak.items):
        if it.version.upper() == version and it.question_type == QUESTION_TYPE_MULTIPLE_CHOICE:
            db.delete(it)
    db.flush()
    creadas = 0
    for i, q in enumerate(items, start=1):
        correcta = (str(q.get("correcta") or "A").strip().upper()[:1]) or "A"
        ops = []
        for o in (q.get("opciones") or []):
            letra = str(o.get("letra", "")).strip().upper()[:2]
            if letra:
                ops.append({"letra": letra, "texto": str(o.get("texto", "")).strip()})
        db.add(AnswerKeyItem(
            answer_key_id=ak.id, question_number=i, version=version,
            correct_answer=correcta, weight=1.0, is_annulled=False,
            question_type=QUESTION_TYPE_MULTIPLE_CHOICE,
            enunciado=(str(q.get("enunciado") or "").strip() or None),
            enunciado_imagen=_limpiar_imagen(q.get("imagen")),
            opciones_json=ops or None,
            justificacion=(str(q.get("justificacion") or "").strip() or None)))
        creadas += 1
    ak.is_valid = True
    ak.status = "validada"
    # Mantén n_questions de la evaluación en sincronía con la pauta importada.
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if a is not None:
        a.n_questions = creadas
        if getattr(a, "version_count", None) is not None:
            a.version_count = creadas
    db.commit()
    return {"creadas": creadas, "version": version, "pauta_validada": True}


def proponer_desde_texto(texto: str, n_alternativas: int = 4, llamar=None) -> dict:
    """Propone ítems estructurados (enunciado/opciones/correcta/justificación) a partir del
    texto de una prueba pegada o extraída del documento. BORRADOR: el docente revisa y
    aprueba antes de guardar (G1, humano-en-el-bucle). No inventa: transcribe/estructura.
    """
    from app.services import generador_preguntas_service as gen
    texto = (texto or "").strip()
    if len(texto) < 20:
        raise conflict("Pega el texto de la prueba (enunciados y alternativas).")
    n_alt = max(2, min(6, int(n_alternativas)))
    letras = ", ".join(gen._LETRAS[:n_alt])
    system = ("Eres un asistente que ESTRUCTURA preguntas de alternativas ya escritas. "
              "No inventes preguntas nuevas ni cambies el contenido: transcribe fielmente el "
              "enunciado y las alternativas del texto dado, identifica la alternativa correcta "
              "si el texto la indica. La correcta suele venir MARCADA como PAUTA de alguna de "
              "estas formas: un asterisco (*), un ticket/checkmark (✓ ✔ ☑ ✅), la palabra "
              "'(correcta)'/'[correcta]', o resaltada en NEGRITA, SUBRAYADA, en OTRO COLOR o "
              "con marca de resaltado. Detecta esa marca y úsala como 'correcta'. Si nada la "
              "indica, deja 'correcta' en la más plausible y márcalo en la justificación como "
              "'a confirmar por el docente'. Responde SOLO un arreglo JSON.")
    user = (f"Extrae las preguntas del siguiente texto. Cada pregunta con {n_alt} alternativas "
            f"({letras}). Formato de cada elemento:\n"
            '[{"enunciado": "<texto>", "alternativas": {"A": "<texto>", ...}, '
            '"correcta": "<letra>", "justificacion": "<por qué la correcta lo es>"}]\n\n'
            f"TEXTO:\n{texto[:12000]}")
    llamar = llamar or gen.generador_por_defecto()
    if not llamar:
        raise conflict("La estructuración con IA no está disponible (sin ANTHROPIC_API_KEY). "
                       "Puedes cargar el contenido manualmente.")
    crudo = llamar(system, user)
    preguntas = gen.parsear_preguntas(crudo, n_alt)   # valida y normaliza
    propuestas = []
    for k, q in enumerate(preguntas, start=1):
        propuestas.append({
            "question_number": k, "enunciado": q["enunciado"],
            "opciones": [{"letra": L, "texto": t} for L, t in q["alternativas"].items()],
            "correcta": q["correcta"], "justificacion": q.get("justificacion", ""),
        })
    return {"propuestas": propuestas, "n": len(propuestas), "borrador": True}


def matriz_binaria(db, codigo: str) -> dict:
    """Matriz participante x item (0/1) para alimentar la psicometria (Rasch, KR-20...).

    El modo en vivo entra a los mismos motores del modulo Investigador sin persistir
    escaneos: es otra fuente de la misma evidencia.
    """
    s = _sesion(db, codigo)
    n = s.n_preguntas
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()
    por_part: dict[uuid.UUID, dict[int, int]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = 1 if r.correcta else 0

    filas, aliases = [], []
    for p in parts:
        celdas = por_part.get(p.id, {})
        filas.append([celdas.get(i, 0) for i in range(1, n + 1)])
        aliases.append(p.alias)
    return {"codigo": s.codigo, "participantes": aliases,
            "items": list(range(1, n + 1)), "matriz": filas}


def join_url(codigo: str, base: str | None = None) -> str:
    """Enlace de unión que codifica el QR. Absoluto si hay base (ideal para escanear con
    el teléfono); relativo si no, para que el frontend lo complete con su propio origen."""
    ruta = "/app.html?sala=" + str(codigo).upper()
    b = (base or "").strip().rstrip("/")
    return (b + ruta) if b else ruta


def qr_data_url(payload: str) -> str | None:
    """PNG en base64 (data URL) para el QR de union. None si la libreria no esta."""
    try:
        import base64
        import io
        import qrcode
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None
