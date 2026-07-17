"""
Motor del modo EN VIVO. Corrige cada respuesta al vuelo contra la pauta (AnswerKey) y,
al cerrar, entrega la matriz binaria participante x item que alimenta la MISMA psicometria
del resto de la plataforma. Sincronizacion por polling (GET estado); WebSockets es una
optimizacion posterior, no cambia el contrato.
"""
from __future__ import annotations

import random
import secrets
import uuid

from app.core.errors import conflict, not_found
from app.models.answer_key import AnswerKey, QUESTION_TYPE_MULTIPLE_CHOICE
from app.models.assessment import Assessment
from app.models.en_vivo import (
    SesionEnVivo, ParticipanteVivo, RespuestaVivo,
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
            "enunciado": it.enunciado, "opciones": opciones,
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
                     modo_ritmo=modo, shuffle_preguntas=shuffle_p, shuffle_opciones=shuffle_o)
    db.add(s); db.commit(); db.refresh(s)
    return s


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
        db.commit(); db.refresh(s)
        return s
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
    ya = db.query(Scan).filter(
        Scan.assessment_id == uuid.UUID(s.assessment_id),
        Scan.student_identifier.like(_SCAN_PREFIX + s.codigo + ":%")).first()
    if ya:
        return 0  # ya se volcó este cierre; no duplicar

    items = _items_mc(db, uuid.UUID(s.assessment_id), s.version)
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
        db.add(Scan(
            assessment_id=uuid.UUID(s.assessment_id),
            student_identifier=(_SCAN_PREFIX + s.codigo + ":" + str(p.id)[:8])[:100],
            status="en_vivo", detected_version=s.version, requires_review=False,
            raw_ocr_payload_json={"answers": answers, "origen": "en_vivo",
                                  "sesion": s.codigo, "alias": p.alias},
        ))
        creados += 1
    db.commit()
    return creados


# ── participantes ────────────────────────────────────────────────────────────────────
def unir(db, codigo: str, alias: str, student_id: str | None = None) -> ParticipanteVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_CERRADA:
        raise conflict("La sesion ya esta cerrada; no admite mas participantes.")
    alias = (alias or "").strip()[:80] or "Anonimo"
    # Distribución personal (barajado por-alumno) fijada al entrar: estable durante la sesión.
    items = _items_contenido(db, uuid.UUID(s.assessment_id), s.version)
    layout = _gen_layout(items, s.shuffle_preguntas, s.shuffle_opciones, random.Random())
    p = ParticipanteVivo(sesion_id=s.id, alias=alias,
                         student_id=str(student_id) if student_id else None,
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


def _config_dict(s) -> dict:
    return {"modo_ritmo": s.modo_ritmo, "retro_alumno": s.retro_alumno,
            "revelar_correccion": s.revelar_correccion,
            "shuffle_preguntas": s.shuffle_preguntas, "shuffle_opciones": s.shuffle_opciones}


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

    base = {"estado": s.estado, "modo_ritmo": s.modo_ritmo, "alias": p.alias,
            "n_preguntas": n, "respondidas": respondidas,
            "progreso_pct": round(respondidas / n * 100) if n else 0}

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
        por_pregunta.append({
            "pregunta": i, "correcta": item["correcta"],
            "n_respuestas": ncnt, "n_correctas": n_ok,
            "pct_correcta": round(n_ok / ncnt * 100, 1) if ncnt else 0.0,
            "distribucion": dist,
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
    }


# ── banco de ítems (contenido para el modo en vivo digital) ───────────────────────────
def contenido_items(db, assessment_id, version: str = "A") -> dict:
    """Contenido actual (enunciado/opciones/justificación) por pregunta, para editarlo."""
    items = _items_contenido(db, assessment_id, version)
    return {"version": version.upper(), "n_preguntas": len(items),
            "items": [{"question_number": it["qn"], "ordinal": it["ordinal"],
                       "correcta": it["correcta"], "enunciado": it["enunciado"] or "",
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
        n += 1
    db.commit()
    return {"actualizados": n}


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
              "si el texto la indica (si no, deja 'correcta' en la más plausible y márcalo en "
              "la justificación como 'a confirmar por el docente'). Responde SOLO un arreglo JSON.")
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
