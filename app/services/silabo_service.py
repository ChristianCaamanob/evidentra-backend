"""Escudo de comunicación — lógica del agente de sílabo + bandeja clasificada (Pilar II).

La IA responde SOLO con el contexto del curso que cargó el docente. Si la pregunta no está
cubierta o requiere una decisión humana (cambio de fecha, excepción, nota), la marca para la
bandeja del docente. Todo se persiste clasificado (categoría + urgencia + estado).
"""
from __future__ import annotations

import json
import logging
import re
import secrets

from sqlalchemy.orm import Session

from app.core.errors import not_found, conflict
from app.models.silabo import (
    SilaboAgente, MensajeSilabo, RuniBitacora, MSG_RESPONDIDA, MSG_PENDIENTE, MSG_RESUELTA,
)

import hashlib
import os as _os

logger = logging.getLogger("evalys")

# ── Bitácora encadenada por hash (auditable, sin datos personales). Regla dura: sin bitácora no hay respuesta.
_REGLAS_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "config", "runi-reglas-eticas.yaml")
_REGLAS_VER_CACHE = None
def reglas_version() -> str:
    global _REGLAS_VER_CACHE
    if _REGLAS_VER_CACHE is None:
        try:
            t = open(_REGLAS_PATH, encoding="utf-8").read()
            m = re.search(r'version:\s*"?([\d.]+)', t)
            _REGLAS_VER_CACHE = m.group(1) if m else "0"
        except Exception:
            _REGLAS_VER_CACHE = "0"
    return _REGLAS_VER_CACHE
def _seudonimo(device_id) -> str:
    if not device_id:
        return "anon"
    return hashlib.sha256(("runi::" + str(device_id)).encode("utf-8")).hexdigest()[:32]
def _sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
    return h.hexdigest()
def _ultimo_hash(db: Session, agente_id) -> str:
    last = (db.query(RuniBitacora).filter(RuniBitacora.agente_id == agente_id)
            .order_by(RuniBitacora.created_at.desc()).first())
    return last.hash if (last and last.hash) else ("GENESIS::" + str(agente_id))
def bitacora_append(db: Session, agente_id, device_id, evento: str, meta: dict, contenido: str = "") -> RuniBitacora:
    """Agrega una entrada a la cadena (NO hace commit; se confirma junto al mensaje → sin bitácora no hay respuesta)."""
    prev = _ultimo_hash(db, agente_id)
    seud = _seudonimo(device_id)
    ver = reglas_version()
    ch = _sha(contenido)
    canon = json.dumps({"e": evento, "m": meta or {}, "c": ch, "s": seud, "v": ver}, sort_keys=True, ensure_ascii=False)
    b = RuniBitacora(agente_id=agente_id, seudonimo=seud, evento=evento, meta=(meta or {}),
                     contenido_hash=ch, prev_hash=prev, hash=_sha(prev, canon), reglas_version=ver)
    db.add(b)
    return b
def verificar_bitacora(db: Session, agente_id) -> dict:
    """Recorre la cadena y confirma que nadie la alteró (cada hash = sha256(prev + entrada canónica))."""
    entradas = (db.query(RuniBitacora).filter(RuniBitacora.agente_id == agente_id)
                .order_by(RuniBitacora.created_at.asc()).all())
    prev = "GENESIS::" + str(agente_id)
    for i, b in enumerate(entradas):
        canon = json.dumps({"e": b.evento, "m": b.meta or {}, "c": b.contenido_hash, "s": b.seudonimo,
                            "v": b.reglas_version}, sort_keys=True, ensure_ascii=False)
        if b.prev_hash != prev or b.hash != _sha(prev, canon):
            return {"ok": False, "entradas": len(entradas), "rota_en": i + 1}
        prev = b.hash
    return {"ok": True, "entradas": len(entradas)}
def bitacora_estado(db: Session, course_id) -> dict:
    a = agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "verificacion": {"ok": True, "entradas": 0}, "reglas_version": reglas_version(), "ultimas": []}
    ults = (db.query(RuniBitacora).filter(RuniBitacora.agente_id == a.id)
            .order_by(RuniBitacora.created_at.desc()).limit(25).all())
    return {"agente": _agente_dict(a), "verificacion": verificar_bitacora(db, a.id),
            "reglas_version": reglas_version(),
            "ultimas": [{"ts": (b.created_at.isoformat() if b.created_at else None), "evento": b.evento,
                         "meta": b.meta or {}, "seudonimo": (b.seudonimo or "")[:8],
                         "hash": (b.hash or "")[:12]} for b in ults]}


# ── Perfil longitudinal (memoria pedagógica del estudiante): transparente y BORRABLE. Backbone del seguimiento.
def _iso_semana(dt):
    try:
        return dt.strftime("%G-S%V")
    except Exception:
        return "?"
def _resumen_pedagogico(temas, total, vacios_temas, baja_conf) -> str:
    if not total:
        return ("Aún no tenemos historial juntos. Pregúntame lo que quieras y voy recordando en qué te "
                "puedo ayudar mejor. Todo esto lo puedes revisar y borrar cuando quieras.")
    top = [t["tema"] for t in temas[:2] if t["tema"] != "Sin clasificar"]
    parts = ["Llevas " + str(total) + " consulta" + ("s" if total != 1 else "") +
             (" — sobre todo de " + ", ".join(top) + "." if top else ".")]
    if vacios_temas:
        parts.append("Encontraste vacíos en " + ", ".join(vacios_temas[:2]) + ": ahí conviene reforzar.")
    if baja_conf:
        parts.append("Te sientes menos seguro en " + ", ".join(baja_conf[:2]) + ".")
    return " ".join(parts)
def perfil_estudiante(db: Session, codigo: str, device_id: str) -> dict:
    a = agente_por_codigo(db, codigo)
    if not device_id:
        return {"nombre_curso": a.nombre_curso, "total": 0, "vacios": 0,
                "resumen": _resumen_pedagogico([], 0, [], []), "temas": [], "por_semana": []}
    msgs = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
            .order_by(MensajeSilabo.created_at.asc()).all())
    acad = [m for m in msgs if (getattr(m, "tipo", None) or "") not in _TIPOS_NO_ACADEMICO]
    temas = {}
    for m in acad:
        key = (getattr(m, "tema", None) or "").strip() or "Sin clasificar"
        t = temas.get(key)
        if not t:
            t = temas[key] = {"tema": key, "total": 0, "vacios": 0, "confianza": None}
        t["total"] += 1
        if m.necesita_docente:
            t["vacios"] += 1
        if getattr(m, "confianza", None):
            t["confianza"] = m.confianza          # última confianza declarada en ese tema
    lista = sorted(temas.values(), key=lambda x: x["total"], reverse=True)
    vacios_temas = [t["tema"] for t in lista if t["vacios"] > 0 and t["tema"] != "Sin clasificar"]
    baja_conf = [t["tema"] for t in lista if t.get("confianza") == "baja" and t["tema"] != "Sin clasificar"]
    sem = {}
    for m in acad:
        k = _iso_semana(m.created_at)
        sem[k] = sem.get(k, 0) + 1
    por_semana = [{"semana": k, "n": sem[k]} for k in sorted(sem.keys())][-8:]
    total = len(acad)
    return {"nombre_curso": a.nombre_curso, "total": total,
            "vacios": sum(1 for m in acad if m.necesita_docente),
            "resumen": _resumen_pedagogico(lista, total, vacios_temas, baja_conf),
            "temas": lista[:12], "por_semana": por_semana,
            "ultima": (acad[-1].created_at.isoformat() if acad else None)}
def monitoreo_curso(db: Session, course_id) -> dict:
    """Monitoreo docente (read-only) UNIFICADO por estudiante: cruza TODOS los módulos (Runi, agenda,
    avisos, recordatorios, reuniones) resolviendo la identidad device_id → owner_key → cuenta."""
    a = agente_de_curso(db, course_id)
    if not a:
        return {"ok": True, "estudiantes": [], "resumen": {}, "sin_agente": True}
    from app.models.device_identity import DeviceIdentity
    from app.models.push import StudentCourseFollow, PushSubscription
    from app.models.agenda import AgendaBloque
    from app.models.recordatorio import RecordatorioPersonal
    from app.models.reunion import Disponibilidad, Reserva
    from app.models.student_account import StudentAccount
    # OJO con los dos tipos: SilaboAgente.course_id es String(64), pero StudentCourseFollow
    # y EvaluacionAgenda lo tienen como UUID. Pasarles el texto reventaba dentro de
    # SQLAlchemy ('str' object has no attribute 'hex') → 500 sin CORS → el panel mostraba
    # "No se pudo cargar el monitoreo" sin decir por qué.
    cid = str(a.course_id)
    try:
        cid_uuid = _uuid(cid)
    except Exception:  # noqa: BLE001  — agente huérfano o id no canónico: no rompe el panel
        cid_uuid = None

    # Mapa de identidad: device_id → owner_key (+ nombre de cuenta).
    idmap = {d.device_id: d for d in db.query(DeviceIdentity).all()}

    def _resolver(device_id):
        d = idmap.get(device_id)
        if d:
            return d.owner_key, d.nombre
        dev = re.sub(r"[^0-9a-zA-Z_-]", "", str(device_id or "anon"))[:64] or "anon"
        return "dev:" + dev, None

    def _nombre_de_owner(ow):
        if ow.startswith("sid:"):
            try:
                c = db.query(StudentAccount).filter(StudentAccount.id == _uuid(ow[4:])).first()
                if c:
                    return (_nombre_amable(c.nombres, c.apellido_paterno) or c.nombres or "Estudiante")
            except Exception:  # noqa: BLE001
                pass
        return None

    # 1) Actividad con Runi, agrupada por owner_key resuelto (unifica varios dispositivos de un mismo alumno).
    msgs = (db.query(MensajeSilabo).filter(MensajeSilabo.agente_id == a.id)
            .order_by(MensajeSilabo.created_at.asc()).all())
    est = {}
    for m in msgs:
        ow, nom = _resolver(m.device_id or "")
        e = est.get(ow)
        if not e:
            e = est[ow] = {"owner": ow, "nombre": nom, "alias": None, "consultas": 0, "academicas": 0,
                           "temas": {}, "vacios": 0, "escaladas": 0,
                           "conf": {"baja": 0, "media": 0, "alta": 0}, "ultima": None, "recientes": []}
        if nom and not e["nombre"]:
            e["nombre"] = nom
        if m.alias:
            e["alias"] = m.alias
        e["consultas"] += 1
        if (getattr(m, "tipo", None) or "") not in _TIPOS_NO_ACADEMICO:
            e["academicas"] += 1
            key = (getattr(m, "tema", None) or "").strip() or "Sin clasificar"
            e["temas"][key] = e["temas"].get(key, 0) + 1
        if m.necesita_docente:
            e["vacios"] += 1
        if getattr(m, "estado", None) in ("pendiente", "escalada") or (m.nivel and m.nivel >= 3 and m.necesita_docente):
            e["escaladas"] += 1
        if getattr(m, "confianza", None) in e["conf"]:
            e["conf"][m.confianza] += 1
        e["ultima"] = m.created_at.isoformat() if m.created_at else e["ultima"]
        e["recientes"].append({"pregunta": (m.pregunta or "")[:160], "tema": getattr(m, "tema", None),
                               "confianza": getattr(m, "confianza", None),
                               "ts": m.created_at.isoformat() if m.created_at else None})

    # 2) Incluir también a quien sigue el curso aunque no haya consultado a Runi.
    seguidores = (db.query(StudentCourseFollow).filter(StudentCourseFollow.course_id == cid_uuid).all()
                  if cid_uuid else [])
    for f in seguidores:
        if f.owner_key not in est:
            est[f.owner_key] = {"owner": f.owner_key, "nombre": None, "alias": None, "consultas": 0,
                                "academicas": 0, "temas": {}, "vacios": 0, "escaladas": 0,
                                "conf": {"baja": 0, "media": 0, "alta": 0}, "ultima": None, "recientes": []}

    # 3) Señales por-estudiante de los OTROS módulos (todo por owner_key).
    salida = []
    con_avisos = 0
    for ow, e in est.items():
        agenda_n = db.query(AgendaBloque).filter(AgendaBloque.owner_key == ow).count()
        avisos = db.query(PushSubscription).filter(PushSubscription.owner_key == ow).first() is not None
        if avisos:
            con_avisos += 1
        recs = db.query(RecordatorioPersonal).filter(RecordatorioPersonal.owner_key == ow).count()
        reun = (db.query(Disponibilidad).filter(Disponibilidad.owner_key == ow).count()
                + db.query(Reserva).filter(Reserva.invitado_owner_key == ow).count())
        temas_top = sorted(e["temas"].items(), key=lambda x: x[1], reverse=True)
        nombre = e["nombre"] or _nombre_de_owner(ow) or e["alias"] or "Estudiante s/ nombre"
        salida.append({
            "owner": ow, "nombre": nombre, "identificado": ow.startswith("sid:"),
            "consultas": e["consultas"], "academicas": e["academicas"],
            "temas_n": len(e["temas"]), "temas_top": [{"tema": t, "n": n} for t, n in temas_top[:5]],
            "vacios": e["vacios"], "escaladas": e["escaladas"], "conf": e["conf"],
            "ultima": e["ultima"], "recientes": list(reversed(e["recientes"]))[:6],
            "modulos": {"agenda": agenda_n, "avisos": avisos, "recordatorios": recs, "reuniones": reun}})
    salida.sort(key=lambda x: (x["ultima"] or "", x["consultas"]), reverse=True)

    resumen = {"estudiantes": len(salida), "consultas_totales": len(msgs),
               "con_avisos": con_avisos,
               "con_agenda": sum(1 for s in salida if s["modulos"]["agenda"] > 0),
               "identificados": sum(1 for s in salida if s["identificado"])}
    try:
        from app.models.evaluacion_agenda import EvaluacionAgenda
        resumen["evaluaciones_cargadas"] = (db.query(EvaluacionAgenda).filter(
            EvaluacionAgenda.course_id == cid_uuid).count() if cid_uuid else 0)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "estudiantes": salida, "resumen": resumen,
            "nombre_curso": a.nombre_curso, "codigo": a.codigo}


def set_confianza(db: Session, mensaje_id, device_id, confianza) -> dict:
    confianza = (confianza or "").strip().lower()
    if confianza not in ("baja", "media", "alta"):
        raise conflict("Confianza no válida.")
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Consulta no encontrada.")
    if device_id and m.device_id and str(m.device_id) != str(device_id):
        raise conflict("Solo puedes marcar tu propia consulta.")
    m.confianza = confianza
    db.commit()
    # CABLE North Star: al registrar su confianza, la consulta se vuelve un Episodio de Aprendizaje
    # (objetivo=tema, feedback dado, cierre=respuesta) + comprobación diferida 7d. Aditivo: si falla,
    # nunca rompe la acción del alumno.
    try:
        from app.services import episode_service as _eps
        a = db.query(SilaboAgente).filter(SilaboAgente.id == m.agente_id).first()
        # pseudo_id consistente con el frontend ('stu:'+device) para que el alumno vea su propio progreso.
        pid = "stu:" + str(device_id or m.device_id or "anon")
        # course_id del episodio = CÓDIGO del sílabo (consistente con el repaso del frontend y el dashboard docente).
        _eps.registrar_silabo(db, pid, (a.codigo if a else None), (m.tema or "consulta"),
                              confianza, (m.respuesta_ia or "")[:500])
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return {"ok": True, "confianza": confianza}
def borrar_memoria(db: Session, codigo: str, device_id: str) -> dict:
    """Derecho a borrar: elimina las consultas de ESE estudiante (su memoria). La BITÁCORA (auditoría,
    seudonimizada y sin texto personal) se conserva por integridad — no expone al estudiante."""
    a = agente_por_codigo(db, codigo)
    if not device_id:
        raise conflict("Falta identificar el dispositivo.")
    n = (db.query(MensajeSilabo)
         .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
         .delete(synchronize_session=False))
    db.commit()
    return {"borradas": int(n or 0)}
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CATEGORIAS = ("fechas", "contenido", "evaluación", "logística", "otro")


def _generar_codigo(db: Session) -> str:
    for _ in range(30):
        cod = "".join(secrets.choice(_ALFABETO) for _ in range(6))
        if not db.query(SilaboAgente).filter(SilaboAgente.codigo == cod).first():
            return cod
    return "".join(secrets.choice(_ALFABETO) for _ in range(8))


def _json_robusto(crudo: str) -> dict:
    t = (crudo or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("sin objeto JSON")
    return json.loads(t[i:j + 1])


# ── agente (docente) ─────────────────────────────────────────────────────────────────
def agente_de_curso(db: Session, course_id) -> SilaboAgente | None:
    return db.query(SilaboAgente).filter(SilaboAgente.course_id == str(course_id)).first()


def info_por_curso(db: Session, course_code: str) -> dict:
    """Resuelve el CÓDIGO ACADÉMICO del ramo (p.ej. OBMA1008) → agente Runi, para que el alumno
    pueda entrar con el código que sí conoce. Devuelve el código del agente si está publicado."""
    from sqlalchemy import func
    from app.models.course import Course
    cc = str(course_code or "").strip()
    if not cc:
        return {"ok": False, "motivo": "vacio"}
    c = db.query(Course).filter(func.lower(Course.code) == cc.lower()).first()
    if not c:
        return {"ok": False, "motivo": "curso_no_existe"}
    a = agente_de_curso(db, c.id)
    if not a:
        return {"ok": False, "motivo": "sin_agente", "nombre_curso": c.name}
    return {"ok": True, "codigo": a.codigo, "activo": bool(a.activo), "nombre_curso": c.name}


def agente_por_codigo(db: Session, codigo: str) -> SilaboAgente:
    a = db.query(SilaboAgente).filter(SilaboAgente.codigo == str(codigo).upper()).first()
    if not a:
        raise not_found("Agente de sílabo no encontrado.")
    return a


def crear_o_actualizar(db: Session, course_id, contexto: str, activo: bool,
                       nombre_curso: str | None = None, config: dict | None = None) -> SilaboAgente:
    a = agente_de_curso(db, course_id)
    if not a:
        a = SilaboAgente(course_id=str(course_id), codigo=_generar_codigo(db),
                         contexto=contexto or "", activo=bool(activo),
                         nombre_curso=nombre_curso, config=config or {})
        db.add(a)
    else:
        a.contexto = contexto if contexto is not None else a.contexto
        a.activo = bool(activo)
        if nombre_curso:
            a.nombre_curso = nombre_curso
        if config is not None:
            a.config = config
    db.commit(); db.refresh(a)
    return a


def join_url(codigo: str, base: str) -> str:
    base = (base or "").rstrip("/")
    return f"{base}/app.html?silabo={codigo}" if base else codigo


# ── Nivel 2 · Ayudante (opcional) ─────────────────────────────────────────────────────
def configurar_ayudante(db: Session, course_id, activo: bool) -> SilaboAgente:
    a = agente_de_curso(db, course_id)
    if not a:
        raise conflict("Primero configure y publique el agente del curso.")
    a.ayudante_activo = bool(activo)
    if activo and not a.ayudante_codigo:
        a.ayudante_codigo = _generar_codigo(db)
    db.commit(); db.refresh(a)
    return a


def ayudante_url(codigo: str, base: str) -> str:
    base = (base or "").rstrip("/")
    return f"{base}/app.html?ayudante={codigo}" if base else codigo


def agente_por_ayudante_codigo(db: Session, codigo: str) -> SilaboAgente:
    a = db.query(SilaboAgente).filter(SilaboAgente.ayudante_codigo == str(codigo).upper()).first()
    if not a:
        raise not_found("Tablero de ayudante no encontrado.")
    return a


def _escalar_vencidos(db: Session, a: SilaboAgente) -> None:
    """Vencimiento automático: los pendientes de NIVEL 2 que pasaron su plazo suben solos al profesor."""
    ahora = _ahora()
    venc = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.estado == MSG_PENDIENTE,
                    MensajeSilabo.nivel == 2).all())
    cambios = 0
    for m in venc:
        if m.vence_ts and m.vence_ts <= ahora:
            m.nivel = 3
            m.vence_ts = ahora + _PLAZO_DOCENTE_H * 3600
            m.motivo_escalamiento = (m.motivo_escalamiento or "Sin respuesta del ayudante en el plazo")
            cambios += 1
    if cambios:
        db.commit()


# ── taxonomía de intención (Antesala) · política y destino por tipo ───────────────────
# Tipos que la IA NUNCA responde con contenido: se arman para el profesor.
_TIPOS_A_DOCENTE = ("fuera_corpus", "evaluativa", "riesgo_clinico")
# Tipos que SIEMPRE se derivan a Secretaría Académica + Dirección (no los trata la Antesala ni el
# docente por este canal): salud, justificaciones y denuncias/ética/acoso.
_TIPOS_DERIVACION = ("personal_salud", "justificacion", "denuncia")
_PLAZO_DOCENTE_H = 48   # horas visibles del reloj para el alumno (Fase 3: horas hábiles + auto-subida)
_PLAZO_AYUDANTE_H = 24  # nivel 2: si el ayudante no responde en 24 h, sube solo al profesor


def _derivacion_texto(a: SilaboAgente) -> str:
    cfg = a.config or {}
    sec = str(cfg.get("contacto_secretaria") or "").strip()
    dire = str(cfg.get("contacto_direccion") or "").strip()
    partes = ["Esto no lo resuelve la Antesala. Por su naturaleza —salud, justificaciones o denuncias/"
              "situaciones personales— debe dirigirlo SIEMPRE a la Secretaría Académica y a la Dirección "
              "de su carrera, que son las instancias que corresponden."]
    if sec:
        partes.append("Secretaría Académica: " + sec + ".")
    if dire:
        partes.append("Dirección: " + dire + ".")
    partes.append("Si es urgente o afecta su salud, acuda de forma presencial. No está solo/a.")
    return " ".join(partes)


def _ahora() -> int:
    import time
    return int(time.time())


# ── similitud semántica ligera (sin embeddings): Jaccard de tokens normalizados ───────
import unicodedata as _ud

_STOP = {"a", "al", "ante", "aqui", "asi", "el", "la", "los", "las", "un", "una", "unos", "unas",
         "de", "del", "en", "y", "o", "u", "que", "cual", "cuales", "cuanto", "cuanta", "cuantos",
         "cuantas", "como", "para", "por", "con", "sin", "se", "su", "sus", "mi", "mis", "es", "son",
         "hay", "tiene", "tienen", "cuando", "donde", "quien", "cuál", "qué", "cómo", "sobre", "esta",
         "este", "esto", "estas", "estos", "me", "te", "lo", "le", "les", "yo", "tu", "si", "no", "mas",
         "muy", "ya", "he", "ha", "va", "vale"}


def _tokens(texto: str) -> set:
    t = _ud.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not _ud.combining(c))       # sin tildes
    t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOP}


_UMBRAL_SIM = 0.5   # ≥ 0.5 de Jaccard Y ≥ 2 palabras-tema en común = equivalente


def _jaccard(a: set, b: set) -> float:
    """Similitud PRECISION-FIRST: exige ≥ 2 palabras de contenido en común (evita fusionar dos
    preguntas por un solo término compartido). Nota: es LÉXICO — capta redacciones parecidas, no
    sinónimos profundos (eso requiere embeddings, mejora futura)."""
    if not a or not b or len(a & b) < 2:
        return 0.0
    return len(a & b) / len(a | b)


def _es_equivalente(t_a: set, texto_b: str) -> bool:
    return _jaccard(t_a, _tokens(texto_b)) >= _UMBRAL_SIM


def _buscar_cache(db: Session, a: SilaboAgente, pregunta: str):
    """Consistencia + economía: si una pregunta equivalente YA fue respondida y sigue vigente,
    devuelve la MISMA respuesta (prefiere la del docente). Invalida si el contexto se editó
    después (a.updated_at) o si la respuesta venció."""
    t_q = _tokens(pregunta)
    if not t_q:
        return None
    corte = getattr(a, "updated_at", None)
    ahora = _ahora()
    recientes = (db.query(MensajeSilabo)
                 .filter(MensajeSilabo.agente_id == a.id)
                 .order_by(MensajeSilabo.created_at.desc()).limit(300).all())
    mejor, mejor_sim = None, 0.0
    for m in recientes:
        # AUTO-CACHE seguro: solo reusa la respuesta CANÓNICA del DOCENTE (no auto-reusa la de la IA,
        # que en léxico podría confundir "cuándo/dónde"). Es la consistencia que pide el diseño.
        if not (m.respuesta_docente or "").strip():
            continue
        if corte and getattr(m, "created_at", None) and m.created_at < corte:
            continue                                        # contexto cambió después
        if getattr(m, "vence_ts", None) and m.vence_ts and m.vence_ts <= ahora:
            continue                                        # respuesta vencida
        sim = _jaccard(t_q, _tokens(m.pregunta))
        if sim > mejor_sim and sim >= _UMBRAL_SIM:
            mejor, mejor_sim = m, sim
    if not mejor:
        return None
    return {"respuesta": mejor.respuesta_docente,
            "tipo": getattr(mejor, "tipo", "conceptual") or "conceptual",
            "categoria": mejor.categoria or "otro", "por_docente": True,
            "cita": getattr(mejor, "cita", None)}


# ── memoria conversacional: las últimas vueltas del MISMO dispositivo, para que Runi entienda las
# continuaciones breves ("sí", "seguimos", "y eso", "explícalo mejor") en vez de derivarlas por falta de contexto.
def _historial_reciente(db: Session, agente_id, device_id, n: int = 4) -> str:
    if not device_id:
        return ""
    msgs = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == agente_id, MensajeSilabo.device_id == str(device_id))
            .order_by(MensajeSilabo.created_at.desc()).limit(n).all())
    partes = []
    for m in reversed(msgs):
        partes.append("Estudiante: " + (m.pregunta or "")[:280])
        r = (m.respuesta_docente or m.respuesta_ia or "").strip()
        if r:
            partes.append("Runi: " + r[:380])
    return "\n".join(partes)[:2500]


# ── pregunta del alumno (público) ────────────────────────────────────────────────────
def preguntar(db: Session, codigo: str, pregunta: str, alias: str | None = None,
              device_id: str | None = None, escalar: bool = False, material: str | None = None,
              imagenes: list | None = None) -> dict:
    a = agente_por_codigo(db, codigo)
    if not a.activo:
        raise conflict("El agente del curso no está activo en este momento.")
    pregunta = (pregunta or "").strip()
    # Con imágenes adjuntas la pregunta puede ser corta ("¿qué es esto?"); igual exigimos algo escrito.
    if len(pregunta) < 3 and not imagenes:
        raise conflict("Escriba su pregunta.")
    if len(pregunta) > 1000:
        pregunta = pregunta[:1000]
    # Carga universal: MATERIAL DE ESTUDIO del estudiante (Fase 1 texto; Fase 2 imágenes/foto). Se extrae/lee
    # en su dispositivo, no se almacena aquí. Runi conversa sobre él como aprendizaje, no como parámetro del curso.
    material = (material or "").strip()[:16000] or None
    imagenes = [im for im in (imagenes or []) if isinstance(im, dict) and (im.get("data"))][:6] or None
    # v4-F5 · modo evaluación FORZADO en servidor: en ventana de evaluación (modo 'cerrado') se NIEGAN adjuntos y
    # cámara aquí (no solo en el cliente). La abstención de resolver contenido evaluable ya la aplica la política 'cerrado'.
    if str((a.config or {}).get("modo_pedagogico") or "").lower() == "cerrado":
        imagenes = None
        material = None
    if imagenes and len(pregunta) < 3:
        pregunta = "Explícame lo que ves en la(s) imagen(es) que te adjunté."

    # Emoji/expresión: solo emojis (sin palabras) → Runi REACCIONA cálido, sin buscar en el material ni derivar.
    if not escalar and not imagenes and _es_expresion(pregunta):
        reaccion = _reaccion_emoji(pregunta)
        ev = _evidencia(decision="Reacción de Runi a tu emoji (no busqué en el material).", fuente="ninguna")
        m = MensajeSilabo(agente_id=a.id, alias=(alias or None), device_id=(device_id or None),
                          pregunta=pregunta, respuesta_ia=reaccion, tipo="expresion", categoria="otro",
                          cita=None, tema=None, fuente="ninguna", evidencia=ev, urgencia="baja",
                          necesita_docente=False, estado=MSG_RESPONDIDA, vence_ts=None, nivel=1,
                          respondido_por="ia")
        db.add(m)
        bitacora_append(db, a.id, device_id, "expresion",
                        {"tipo": "expresion", "fuente": "ninguna", "decision": "reaccion", "nivel": 1},
                        contenido=(pregunta + "\n" + reaccion))
        db.commit(); db.refresh(m)
        return {"respuesta": reaccion, "necesita_docente": False, "tipo": "expresion", "cache": False,
                "cita": None, "categoria": "otro", "urgencia": "baja", "mensaje_id": str(m.id),
                "vence_ts": None, "evidencia": ev}

    cache_hit, cita, tema, fuente, evidencia = False, None, None, None, None
    if escalar:
        # Botón "quiero preguntar a una persona": salta la IA y arma para el docente.
        tipo, respuesta, categoria, urgencia, necesita = (
            "solicitud_humana",
            "Listo: le llevé tu consulta a tu docente. Puedes seguir su estado y su respuesta aquí.",
            "otro", "media", True)
        fuente = "ninguna"
        evidencia = _evidencia(decision="Tu docente responde tu consulta por este canal.",
                               necesita=True, fuente="ninguna")
    else:
        # Con material/imágenes adjuntos NO se reutiliza caché (la respuesta depende de ESE material del alumno).
        cache = None if (material or imagenes) else _buscar_cache(db, a, pregunta)
        if cache:
            # Consistencia: una pregunta equivalente ya respondida → la MISMA respuesta, sin re-inferir.
            tipo, respuesta, categoria, urgencia, necesita = (
                cache["tipo"], cache["respuesta"], cache["categoria"], "baja", False)
            cita = cache.get("cita"); tema = cache.get("tema"); fuente = cache.get("fuente"); cache_hit = True
            # La respuesta CANÓNICA del docente es evidencia sólida (él la confirmó).
            evidencia = _evidencia(decision="Esta respuesta la confirmó tu docente.",
                                   fuente="corpus", cita=(cita or respuesta), certeza_sug="solida")
        else:
            intentos = _intentos_equivalentes(db, a, pregunta, device_id)
            historial = _historial_reciente(db, a.id, device_id)
            vinculo = None   # v4-F2 · modo de vínculo elegido por el estudiante (adapta el tono de Runi)
            try:
                from app.services import experiencia_service as _xs
                vinculo = _xs.tono_de_modo(db, "stu:" + str(device_id or "anon"))
            except Exception:  # noqa: BLE001
                vinculo = None
            tipo, respuesta, categoria, urgencia, necesita, cita, tema, fuente, evidencia = \
                _clasificar_y_responder(a, pregunta, intentos, material=material, imagenes=imagenes, db=db,
                                        historial=historial, vinculo=vinculo)

    # ── Motor de ética: consecuencia 0–5 + Puerta 3 (verificación de SALIDA sobre la respuesta ya generada).
    from app.services import etica_service as etica
    _certeza = (evidencia or {}).get("certeza")
    if cache_hit or escalar:
        _p3 = {"veredicto": "ok"}                       # respuesta del docente / confirmación → de confianza
    else:
        _p3 = etica.puerta3_verificar(respuesta, a.contexto or "", tipo, cita, fuente, _certeza, necesita)
        if _p3["veredicto"] == "detenido":
            # PARADA SEGURA: la salida pudo fabricar un dato del curso. No se entrega; la confirma el docente.
            necesita = True
            respuesta = ("Prefiero no arriesgarme con este dato sin confirmarlo: se lo llevé a tu docente y "
                         "verás aquí su respuesta.")
            fuente = "ninguna"; cita = None
            evidencia = _evidencia(decision="Verificación de salida (Puerta 3): el dato no estaba respaldado "
                                            "por el material; lo confirma tu docente.",
                                   necesita=True, fuente="ninguna", motivo="Puerta 3 detuvo la entrega")
            _certeza = evidencia.get("certeza")
    _consec = etica.clasificar_consecuencia(tipo, fuente, necesita, _certeza)
    if evidencia is not None:
        evidencia["consecuencia"] = etica.consecuencia_dict(_consec)
        evidencia["puerta3"] = _p3["veredicto"]

    estado = MSG_PENDIENTE if necesita else MSG_RESPONDIDA
    # BARANDA (decisión CEO jul-28): el PROFESOR recibe TODO primero y siempre. El ayudante NUNCA intercepta la
    # cola (podría contener algo sensible) — solo ve lo que el profesor le DELEGA explícitamente. Por eso todo lo
    # pendiente entra directo a NIVEL 3 (profesor); el ayudante recibe por delegación (delegar_al_ayudante).
    if necesita:
        nivel = 3
        vence = _ahora() + _PLAZO_DOCENTE_H * 3600
        respondido_por = None
    else:
        nivel = 1
        vence = None
        respondido_por = "docente" if cache_hit else "ia"
    m = MensajeSilabo(agente_id=a.id, alias=(alias or None), device_id=(device_id or None),
                      pregunta=pregunta, respuesta_ia=respuesta, tipo=tipo, categoria=categoria, cita=cita,
                      tema=tema, fuente=fuente, evidencia=evidencia,
                      urgencia=urgencia, necesita_docente=bool(necesita), estado=estado, vence_ts=vence,
                      nivel=nivel, respondido_por=respondido_por)
    db.add(m)
    # Regla dura "sin bitácora no hay respuesta": la entrada de auditoría se confirma en la MISMA transacción
    # que el mensaje. Si no se puede escribir, el commit falla y el estudiante NO recibe respuesta (parada segura).
    _evento = "parada" if _p3.get("veredicto") == "detenido" else ("derivacion" if necesita else "consulta")
    bitacora_append(db, a.id, device_id, _evento,
                    {"tipo": tipo, "tema": tema, "fuente": fuente, "categoria": categoria,
                     "decision": ("derivado" if necesita else "respondido"), "nivel": nivel,
                     "certeza": (evidencia or {}).get("certeza"), "consecuencia": _consec,
                     "puerta3": _p3.get("veredicto"), "cache": bool(cache_hit)},
                    contenido=((pregunta or "") + "\n" + (respuesta or "")))
    db.commit(); db.refresh(m)
    return {"respuesta": respuesta, "necesita_docente": bool(necesita), "tipo": tipo, "cache": cache_hit,
            "cita": cita, "categoria": categoria, "urgencia": urgencia, "mensaje_id": str(m.id), "vence_ts": vence,
            "evidencia": evidencia}


def _norm_rut(r) -> str:
    """Normaliza un RUT para comparar: quita puntos/guion/espacios, K en minúscula. '12.345.678-K' → '12345678k'."""
    return re.sub(r"[^0-9kK]", "", str(r or "")).lower()


def _norm_id(v) -> str:
    """Normaliza una matrícula/ID académico para comparar: solo alfanumérico, minúscula. 'A-2021.123' → 'a2021123'."""
    return re.sub(r"[^0-9a-zA-Z]", "", str(v or "")).lower()


def _nombre_amable(*partes) -> str:
    """Nombre legible para mostrar: junta partes, quita la barra de 'APELLIDOS/NOMBRES' y colapsa espacios."""
    s = " ".join(p for p in partes if p).strip().replace("/", " ")
    return re.sub(r"\s+", " ", s).strip()


def identificar_por_rut(db: Session, codigo: str, valor: str) -> dict:
    """El alumno se identifica con su RUT **o** su número de matrícula contra la NÓMINA del curso del sílabo.
    (Las universidades entregan nóminas a veces por RUT y a veces por matrícula.) Busca en la nómina académica
    (Student: rut o matricula) y en la de asistencia (AsistenciaMatricula: rut o identificador). Devuelve el
    nombre real si aparece; si no, {ok: False} (no revela nada fuera de la nómina). NO es autenticación fuerte
    (ni el RUT ni la matrícula son secretos) — para VER UBICACIÓN se exige además passkey (Fase 2)."""
    import uuid as _uuid
    from app.models.student import Student
    from app.models.asistencia import AsistenciaMatricula
    a = agente_por_codigo(db, codigo)
    nr, nid = _norm_rut(valor), _norm_id(valor)
    if len(nr) < 7 and len(nid) < 4:
        raise conflict("Escribe tu RUT completo o tu número de matrícula.")
    try:
        cid = _uuid.UUID(str(a.course_id))
    except Exception:  # noqa: BLE001
        return {"ok": False}

    def _cuerpo(x):
        """RUT sin su dígito verificador. Mucha gente lo escribe sin el DV, y rechazarlo por
        eso mandaba a un alumno que SÍ está en la nómina a pedirle al docente que lo agregue."""
        x = str(x or "")
        return x[:-1] if len(x) >= 8 else x

    def _match_rut(campo):
        cn = _norm_rut(campo)
        if len(nr) < 7 or not cn:
            return False
        return cn == nr or _cuerpo(cn) == nr or cn == _cuerpo(nr)

    def _match_id(campo):
        return len(nid) >= 4 and bool(campo) and _norm_id(campo) == nid

    def _resp(nombre, rut_n, matricula):
        # La identidad por RUT/matrícula YA autoriza compartir/ver ubicación (owner_key = 'rut:<rut o id>').
        from app.services import pandilla_service as pand
        clave = "rut:" + (rut_n or _norm_id(matricula) or nid or nr)
        tok = pand.token_ubicacion(clave, cid, nombre)
        return {"ok": True, "nombre": nombre or "Estudiante", "rut": rut_n, "matricula": matricula,
                "ubicacion_token": tok}

    # 1) Nómina académica (Student): por RUT o por matrícula.
    for st in db.query(Student).filter(Student.course_id == cid).all():
        if _match_rut(st.rut) or _match_id(getattr(st, "matricula", None)):
            return _resp(_nombre_amable(st.nombres, st.apellido_paterno), _norm_rut(st.rut) or None,
                         getattr(st, "matricula", None))
    # 2) Nómina de asistencia (AsistenciaMatricula): por RUT o por identificador académico (matrícula).
    for m in db.query(AsistenciaMatricula).filter(AsistenciaMatricula.course_id == cid).all():
        if _match_rut(m.rut) or _match_id(m.identificador):
            return _resp(_nombre_amable(m.nombre), _norm_rut(m.rut) or None, m.identificador)
    # Distinguir "no calzas" de "este curso aún no tiene nómina": con la nómina vacía, el
    # mensaje culpaba al alumno de un dato mal escrito y lo mandaba a hablar con su docente
    # por la razón equivocada.
    n_acad = db.query(Student).filter(Student.course_id == cid).count()
    n_asis = db.query(AsistenciaMatricula).filter(AsistenciaMatricula.course_id == cid).count()
    if not n_acad and not n_asis:
        return {"ok": False, "sin_nomina": True, "n_nomina": 0}
    return {"ok": False, "sin_nomina": False, "n_nomina": n_acad + n_asis}


def _intentos_equivalentes(db: Session, a: SilaboAgente, pregunta: str, device_id: str | None) -> int:
    """Cuántas veces ESTE dispositivo ya preguntó algo equivalente (regla de rendición)."""
    if not device_id:
        return 0
    t = _tokens(pregunta)
    if not t:
        return 0
    prev = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
            .order_by(MensajeSilabo.created_at.desc()).limit(40).all())
    return sum(1 for m in prev if _es_equivalente(t, m.pregunta))


# Expresión (emoji): el estudiante manda SOLO emojis/stickers, sin palabras → Runi reacciona cálido y NO
# busca en el material ni deriva al docente (evita un Q&A absurdo sobre un emoji).
_SHORTCODE_RE = re.compile(r":[a-z0-9-]{2,40}:")
def _es_expresion(texto: str) -> bool:
    t = (texto or "").strip()
    if not t:
        return False
    sin = _SHORTCODE_RE.sub(" ", t)                       # quita los :slug: y ve si queda alguna palabra
    return not re.search(r"[0-9A-Za-zÁÉÍÓÚÑáéíóúñ]", sin)
_REACCIONES_EMOJI = (
    "¡Jaja, gracias! :celebremos-runi: Cuando quieras seguimos con la materia.",
    "Te leo :de-acuerdo-listo: ¿Vemos algún tema del curso?",
    ":te-apoyo-aprendizaje: Aquí estoy para lo que necesites estudiar.",
    "¡Me encanta tu energía! :motivacion-aprendizaje: ¿Con qué tema seguimos?",
    "Anotado :gracias: Cuando quieras te ayudo con la materia.",
)
def _reaccion_emoji(texto: str) -> str:
    return _REACCIONES_EMOJI[len(texto or "") % len(_REACCIONES_EMOJI)]


# Meta-estudio: cómo estudiar/prepararse. Runi SIEMPRE puede responderlo (capa C), aunque el LLM falle.
_META_ESTUDIO_RE = re.compile(
    r"c[oó]mo\s+(estudi|prepar|repas|memoriz|aprend|organiz)|"
    r"\b(estudiar|estudio|repasar|repaso|prepararme|preparar|memorizar|mnemot|"
    r"plan de estudio|estrategi|t[eé]cnica|priorizar|organizar (mi|el) (tiempo|estudio)|"
    r"por d[oó]nde (empiezo|parto|comienzo)|c[oó]mo me organiz)", re.I)
def _es_falla_de_servicio(e) -> bool:
    """¿El fallo fue del MOTOR (clave, red, cuota) y no de la pregunta?

    Distinguirlo importa: si el servicio está caído, decirle al estudiante que reformule
    lo manda a repetir para siempre una pregunta que estaba bien, y registrar el intento
    como 'fuera_corpus' le miente al docente sobre qué no cubre su sílabo.
    """
    m = str(e or "").lower()
    señales = ("authentication_error", "api key", "401", "403", "unauthorized",
               "rate_limit", "429", "overloaded", "529", "connection", "timeout",
               "temporarily unavailable", "service unavailable", "503")
    return any(x in m for x in señales)


def _es_meta_estudio(pregunta: str) -> bool:
    return bool(_META_ESTUDIO_RE.search(pregunta or ""))
_FALLBACK_ESTUDIO = (
    "¡Con gusto! Un buen plan es: 1) divide el temario por unidades y prioriza según la ponderación de "
    "cada evaluación; 2) estudia con la bibliografía obligatoria y practica con casos o ejercicios; y "
    "3) haz repaso espaciado y autoevaluación (explícate el tema en voz alta). ¿Por qué unidad o tema "
    "quieres partir? Te armo un plan más específico."
)


# ── Evidence Core · separación de planos + jerarquía de certeza ───────────────────────
# Regla legal+científica: NUNCA presentar como equivalentes un HECHO del curso, una INFERENCIA de
# Runi, una RECOMENDACIÓN y una DECISIÓN docente. Cada salida las separa y declara su certeza.
_ESCALA_CERTEZA = ("solida", "moderada", "preliminar", "insuficiente", "revision_docente")
_CERTEZA_LABEL = {                       # etiqueta corta (badge para docente/estudiante)
    "solida": "Respaldado por el material del curso",
    "moderada": "Bien fundamentado",
    "preliminar": "Orientación general",
    "insuficiente": "Información insuficiente",
    "revision_docente": "Lo confirma tu docente",
}
_CERTEZA_RUNI = {                        # cómo lo TRADUCE Runi al estudiante (cálido, honesto)
    "solida": "Esto sale directo del material de tu curso.",
    "moderada": "Es una explicación bien fundamentada del ámbito.",
    "preliminar": "Es una orientación general; contrástala con tu material.",
    "insuficiente": "Con lo que tengo ahora no me alcanza para asegurarlo.",
    "revision_docente": "Esto lo decide y confirma tu docente.",
}
def _rank_certeza(c: str) -> int:
    return _ESCALA_CERTEZA.index(c) if c in _ESCALA_CERTEZA else 2   # menor = más fuerte


def _nivel_certeza(sugerido, fuente, cita, necesita) -> str:
    """Pisos de HONESTIDAD (Runi nunca sobre-declara): si se deriva → revision_docente; el material
    del curso puede ser 'solida'; el conocimiento propio de Runi NUNCA supera 'moderada' (no es
    evidencia dura); sin respaldo → 'insuficiente'."""
    if necesita:
        return "revision_docente"
    s = (sugerido or "").strip().lower()
    s = s if s in _ESCALA_CERTEZA else None
    if fuente == "corpus" and cita:
        return s if s in ("solida", "moderada") else "moderada"
    if fuente == "general":
        base = s or "moderada"
        return base if _rank_certeza(base) >= _rank_certeza("moderada") else "moderada"  # tope: moderada
    return s or "insuficiente"


def _sep_trunc(s, n: int = 240) -> str:
    return str(s or "").strip()[:n]


def _evidencia(hecho="", inferencia="", recomendacion="", decision="", *,
               fuente=None, cita=None, necesita=False, certeza_sug=None, motivo=None) -> dict:
    """Arma la ficha de evidencia separando los cuatro planos y fijando la certeza con los pisos.
    HECHO solo si lo respalda el material del profesor (jamás se presenta una inferencia como hecho)."""
    hecho = _sep_trunc(hecho)
    if not (fuente == "corpus" and cita):
        hecho = ""                       # sin respaldo textual del curso no hay 'hecho'
    decision = _sep_trunc(decision)
    if necesita and not decision:
        decision = "Tu docente lo revisa y confirma; verás su respuesta por este canal."
    certeza = _nivel_certeza(certeza_sug, fuente, cita, necesita)
    ev = {"hecho": hecho, "inferencia": _sep_trunc(inferencia),
          "recomendacion": _sep_trunc(recomendacion), "decision": decision,
          "certeza": certeza, "certeza_label": _CERTEZA_LABEL[certeza],
          "certeza_runi": _CERTEZA_RUNI[certeza]}
    if motivo:
        ev["certeza_motivo"] = _sep_trunc(motivo, 160)
    return ev


def _bloque_vinculo(vinculo: dict | None) -> str:
    """v4-F2 · Instrucción de VÍNCULO: adapta el TONO/iniciativa de Runi al modo elegido por el estudiante,
    sin cambiar identidad, honestidad ni rigor."""
    if not vinculo:
        return ""
    lbl = vinculo.get("label", "Compañero"); tono = vinculo.get("tone", "cálido y breve")
    des = vinculo.get("challenge", "low"); ini = vinculo.get("initiative", "medium"); mid = vinculo.get("id", "companion")
    matices = {
        "companion": "Acompaña horizontal y cálido; el estudiante marca el ritmo.",
        "mentor": "Muestra la ESTRUCTURA y ayuda a decidir con criterio; sereno y explicativo.",
        "coach": "Empuja a una repetición MEJOR (no solo una más); enérgico, directo y respetuoso.",
        "navigator": "Anticipa el SIGUIENTE PASO y por qué conviene; claro y ordenado.",
        "teammate": "Coordina aportes para que el grupo avance; colaborativo y concreto.",
        "challenger": "Pon a prueba la idea con MÉTODO socrático, exigente y justo, SIN juzgar.",
        "quiet": "Sé MÍNIMO y no intrusivo: responde lo justo, sin sugerencias extra ni celebraciones.",
        "explorer": "Sigue la CURIOSIDAD del estudiante con rigor; imaginativo pero preciso.",
    }
    return ("\nVÍNCULO CON EL ESTUDIANTE (lo eligió él, es reversible): eres Runi en modo «" + lbl + "». Tu TONO es "
            + tono + "; desafío=" + des + "; iniciativa=" + ini + ". " + matices.get(mid, "")
            + " Adapta tu FORMA de acompañar (cómo hablas, cuánto empujas, cuándo celebras) a este vínculo, PERO "
            "mantén intactas tu identidad, tu honestidad y el rigor: nunca inventes, nunca bajes la exactitud ni "
            "contradigas el material del profesor. El vínculo cambia el estilo, jamás la verdad.\n")


def _bloque_agenda(db, a) -> str:
    """Las evaluaciones que el docente cargó en la agenda, como texto para el contexto.

    Son parámetros del curso escritos por él: fecha, tipo y ponderación. Runi puede
    responderlos con la misma autoridad que si estuvieran en el sílabo, porque vienen de
    la misma mano.
    """
    if db is None:
        return ""
    try:
        from app.models.evaluacion_agenda import EvaluacionAgenda
        import uuid as _u
        cid = _u.UUID(str(a.course_id))
        filas = (db.query(EvaluacionAgenda).filter(EvaluacionAgenda.course_id == cid)
                 .order_by(EvaluacionAgenda.fecha.asc()).all())
    except Exception:  # noqa: BLE001
        return ""
    if not filas:
        return ""
    lineas = []
    for e in filas:
        partes = [e.titulo or "Evaluación", e.fecha or ""]
        if e.hora:
            partes.append(e.hora)
        if e.tipo:
            partes.append(str(e.tipo))
        if e.ponderacion:
            partes.append("ponderación " + str(e.ponderacion))
        lineas.append("- " + " · ".join([x for x in partes if x]))
    return ("EVALUACIONES DEL CURSO (cargadas por el docente en la agenda; son oficiales):\n"
            + "\n".join(lineas) + "\n\n")


def _clasificar_y_responder(a: SilaboAgente, pregunta: str, intentos: int = 0, material: str | None = None,
                            imagenes: list | None = None, historial: str | None = None,
                            vinculo: dict | None = None, db=None):
    """Runi, copiloto de APRENDIZAJE. DOS ámbitos: (1) APRENDIZAJE en general → LIBRE, usa el conocimiento
    de la IA como apoyo estratégico para cerrar brechas, anclado al programa y sin contradecir al profesor;
    (2) PARÁMETROS de la asignatura (fechas/ponderaciones/reglas/alcance/ventana) → ESTRICTO: solo el corpus,
    nunca inventar ni contradecir. Clasifica cada consulta (tipo, tema/RA, fuente) para la trazabilidad del
    profesor. Devuelve (tipo, respuesta, categoria, urgencia, necesita_docente, cita, tema, fuente, evidencia)."""
    import os
    curso = a.nombre_curso or "el curso"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if _es_meta_estudio(pregunta):
            return ("conceptual", _FALLBACK_ESTUDIO, "contenido", "baja", False, None, "estrategia de estudio", "general",
                    _evidencia(recomendacion="Divide por unidades, prioriza por ponderación y repasa con autoevaluación.",
                               fuente="general", certeza_sug="preliminar"))
        # Sin clave configurada el motor no existe: no es que la consulta exceda el sílabo.
        # Marcarla 'fuera_corpus' y escalarla llenaba la bandeja del docente de preguntas que
        # Runi nunca llegó a intentar, y le mentía sobre qué no cubre su material.
        return ("servicio_caido",
                "Ahora mismo no puedo responder: mi conexión con el motor de respuestas está "
                "caída. No es tu pregunta — vuelve a intentarlo en un rato.",
                "otro", "baja", False, None, None, "ninguna",
                _evidencia(decision="Servicio de IA no configurado.", fuente="ninguna",
                           certeza_sug="insuficiente"))
    # Modo pedagógico (config del docente): guiado | mixto | directo | cerrado.
    modo = str((a.config or {}).get("modo_pedagogico") or "directo").lower()
    if modo not in ("guiado", "mixto", "directo", "cerrado"):
        modo = "directo"
    # Regla de rendición: si el estudiante ya intentó ≥2 veces algo equivalente, se responde DIRECTO.
    rendido = intentos >= 2
    modo_efectivo = "directo" if (rendido and modo in ("guiado", "mixto")) else modo
    politica_modo = {
        "guiado": "Solo para contenido EVALUABLE cercano a una prueba: NO des la respuesta completa; da UNA pista mínima y devuelve la pregunta. El aprendizaje general (conceptos, técnicas, temas del ámbito) respóndelo normal.",
        "mixto": "En contenido evaluable cercano a una prueba: primero una pista; si insiste o se frustra, resuelve completo. El aprendizaje general respóndelo normal.",
        "directo": "Responde completo, claro y con razonamiento.",
        "cerrado": "VENTANA DE EVALUACIÓN ABIERTA: responde SOLO parámetros/logística (fechas, salas, reglas). NO resuelvas contenido evaluable; ofrece ayudar a estudiar después.",
    }[modo_efectivo]
    rendicion = (" El estudiante ya insistió; ENTREGA la respuesta completa con el razonamiento (regla de rendición)."
                 if rendido else " Si muestra frustración clara, entrega la respuesta completa.")
    try:
        from app.services import correccion_experta_service as ce
        system = (
            f"Eres Runi, copiloto de APRENDIZAJE del curso {curso}. Tu misión es ayudar a APRENDER en todo el "
            "ámbito de la asignatura y su aprendizaje. Tienes DOS ámbitos con reglas DISTINTAS:\n"
            "  (1) PARÁMETROS DE LA ASIGNATURA — fechas, plazos, ponderaciones, reglas, salas, requisitos, alcance "
            "del temario y ventana de evaluación. Aquí eres ESTRICTO: usa SOLO el CONTEXTO DEL CURSO; JAMÁS inventes "
            "ni estimes un parámetro que no esté escrito, y NO contradigas el material del profesor. Si un parámetro "
            "no está en el contexto, dilo con honestidad y márcalo para el docente (fuera_corpus).\n"
            "  (2) APRENDIZAJE EN GENERAL — explicar conceptos, resolver dudas de contenido, dar contexto, técnicas "
            "de estudio, temas relacionados del ámbito. Aquí tienes LIBERTAD para responder con TU CONOCIMIENTO como "
            "apoyo estratégico para cerrar brechas: claro, riguroso y propositivo, ANCLADO al programa del curso y "
            "SIN CONTRADECIR el material del profesor. Esto NO necesita al docente.\n"
            "MÁXIMA RESOLUTIVIDAD (el estudiante quiere que TÚ resuelvas, no que lo derives): responde tú TODO lo que "
            "sea éticamente posible para el aprendizaje. Deriva al profesor SOLO en lo estrictamente inevitable: nota/"
            "recorrección/reclamo, salud o afectivo, denuncia/acoso, o un PARÁMETRO del curso que no está escrito. "
            "Cualquier duda de CONTENIDO o de estudio la resuelves tú, aunque no esté literal en el material.\n"
            "MÉTODO SOCRÁTICO (evita el 'deskilling' cognitivo — que el alumno deje de pensar): al enseñar contenido, "
            "guía con preguntas y descompón el problema en pasos cortos que lleven al estudiante a descubrir la respuesta, "
            "en vez de dártela masticada de entrada. PERO siempre hazlo AVANZAR: si se estanca, insiste, se frustra o "
            "pide la solución, ENTREGA la respuesta completa con su razonamiento. Nunca uses el método socrático como "
            "excusa para no ayudar.\n"
            "PERSONALIZACIÓN: adáptate a las características del estudiante que percibas en la CONVERSACIÓN RECIENTE "
            "(su nivel, sus dudas recurrentes, cómo aprende mejor) para que la experiencia sea cada vez más suya.\n"
            "RESPALDO BIBLIOGRÁFICO OBLIGATORIO (contenido académico): cuando entregues CONTENIDO, respáldalo SIEMPRE. "
            "Si está en el material del profesor → fuente='corpus' + cita exacta. Si usas tu conocimiento del ámbito → "
            "cierra con 1-3 REFERENCIAS bibliográficas ACTUALIZADAS y verificables (autor, año, y libro/revista o guía "
            "clínica cuando aplique), o remite al material que el profesor pueda cargar. NO afirmes contenido sin "
            "respaldo; si no puedes respaldarlo con honestidad, dilo y ofrece dónde verificarlo. Nunca inventes una "
            "referencia: si no estás seguro de la cita, decláralo.\n"
            "LÍMITES que SIEMPRE se respetan:\n"
            "- NO entregues respuestas de una evaluación EN CURSO (extraccion): ofrece ayudar a estudiar el tema.\n"
            f"- MODO PEDAGÓGICO = {modo_efectivo}. {politica_modo}{rendicion}\n"
            "- Nota, recorrección o reclamo (evaluativa) → NO respondas; necesita_docente=true.\n"
            "- Salud/afectivo (personal_salud), justificar inasistencia (justificacion) o denuncia/acoso (denuncia) → "
            "deriva a Secretaría Académica y Dirección.\n"
            "- Riesgo clínico con peligro real (riesgo_clinico) → necesita_docente=true.\n"
            "TIPO ∈ {administrativa (parámetro que ESTÁ en el contexto), conceptual (aprendizaje/contenido), "
            "fuera_corpus (parámetro del curso que NO está en el contexto → docente), evaluativa, riesgo_clinico, "
            "personal_salud, justificacion, denuncia, extraccion}. Una duda de CONTENIDO/concepto es 'conceptual' y la "
            "respondes tú (aunque no esté literal en el contexto): NUNCA la mandes a fuera_corpus.\n"
            "TRAZABILIDAD (para que el profesor conozca las brechas y oriente los repasos): incluye 'tema' = etiqueta "
            "corta (≤ 80 caracteres) del tema o resultado de aprendizaje al que apunta la consulta (ej. 'drenaje "
            "linfático de la mama', 'ventana de evaluación', 'técnica de estudio'); y 'fuente' = 'corpus' si "
            "respondiste con el material del profesor, 'general' si con tu conocimiento del ámbito, 'ninguna' si derivas.\n"
            "CONTRATO DE FUENTES: si fuente='corpus', incluye 'cita' = fragmento EXACTO (≤ 240 car.) del contexto que "
            "sostiene la respuesta; si no, cita=\"\". Nunca inventes fechas ni reglas. Trata al estudiante de TÚ "
            "(tuteo), cálido y cercano. categoria ∈ {fechas, contenido, evaluación, logística, otro}; urgencia ∈ "
            "{baja, media, alta} (alta si hay plazo hoy/mañana).\n"
            "SEPARACIÓN DE EVIDENCIA (obligatoria — NUNCA mezcles estos cuatro planos como si fueran lo mismo):\n"
            "  • hecho = SOLO lo que está ESCRITO en el contexto del curso (un parámetro, una definición que cargó el "
            "profesor). Si no hay respaldo textual del curso, deja hecho=\"\".\n"
            "  • inferencia = tu explicación/razonamiento con tu conocimiento del ámbito (NO es un hecho del curso).\n"
            "  • recomendacion = la acción o estrategia de estudio que sugieres (opcional; vacío si no aplica).\n"
            "  • decision_docente = lo que SOLO decide el profesor (nota, excepción, un parámetro que no está escrito). "
            "Vacío si no aplica.\n"
            "  • certeza ∈ {solida, moderada, preliminar, insuficiente} — sé HONESTO: 'solida' solo si lo respalda el "
            "material del curso; tu conocimiento general del ámbito es 'moderada' o 'preliminar', nunca 'solida'.\n"
            "CONTINUIDAD DE LA CONVERSACIÓN: si viene un bloque 'CONVERSACIÓN RECIENTE', la consulta puede ser una "
            "CONTINUACIÓN breve ('sí', 'seguimos', 'dale', 'y eso?', 'explícalo mejor', 'la otra'). Interprétala SIEMPRE "
            "en el contexto de esa conversación y respóndela como corresponde al hilo; JAMÁS derives al docente ni la "
            "marques fuera_corpus solo por ser corta o ambigua fuera de contexto. Si de verdad no hay a qué se refiere, "
            "pide una breve aclaración (no la derives).\n"
            "MATERIAL DE ESTUDIO DEL ESTUDIANTE: si viene un bloque 'MATERIAL DE ESTUDIO ADJUNTO' o IMÁGENES adjuntas "
            "(fotos de apuntes, láminas, diagramas, pizarra), léelos/míralos como apoyo para EXPLICAR, resumir o "
            "responder sobre su contenido (ámbito de aprendizaje); puedes citarlos o apoyarte en ellos. NO los trates "
            "como parámetros del curso (fechas/reglas/ponderaciones siguen SOLO del contexto del profesor). Si te apoyas "
            "en el material del estudiante, fuente='general' (no es el corpus del profesor).\n"
            'Devuelve SOLO JSON: {"tipo":"..","tema":"..","fuente":"..","respuesta":"..","cita":"..","categoria":"..",'
            '"urgencia":"..","necesita_docente":true|false,"hecho":"..","inferencia":"..","recomendacion":"..",'
            '"decision_docente":"..","certeza":".."}.'
        )
        system += _bloque_vinculo(vinculo)   # v4-F2 · adapta el tono/iniciativa de Runi al vínculo elegido
        ctx = (a.contexto or "")[:20000]
        # La AGENDA es contexto del curso tanto como el sílabo. El docente ya cargó ahí las
        # fechas y ponderaciones de sus evaluaciones; sin esto, «¿cuándo es el Solemne?» se
        # le escalaba a él mismo para que respondiera un dato que YA había escrito.
        ctx = (_bloque_agenda(db, a) + ctx) if ctx else _bloque_agenda(db, a)
        user = "CONTEXTO DEL CURSO:\n" + (ctx or "(el docente aún no cargó material; responde el aprendizaje general y marca fuera_corpus solo los parámetros del curso)")
        if historial:
            user += ("\n\nCONVERSACIÓN RECIENTE (para entender continuaciones breves; NO es contexto del curso):\n"
                     + historial)
        if material:
            user += ("\n\nMATERIAL DE ESTUDIO ADJUNTO POR EL ESTUDIANTE (apoyo para explicar/estudiar; NO son "
                     "parámetros del curso):\n" + material)
        user += "\n\nPREGUNTA DEL ESTUDIANTE:\n" + pregunta
        d, _ultimo_err = None, None
        for _i in range(3):                                  # reintentos: no escales por un fallo transitorio del LLM
            try:
                if imagenes:
                    crudo = ce._llamar_anthropic_vision(system, user, imagenes, max_tokens=1200)
                else:
                    crudo = ce._llamar_anthropic(system, user, max_tokens=1000)
                d = _json_robusto(crudo)
                if d:
                    break
            except Exception as e:  # noqa: BLE001
                _ultimo_err = e
                logger.warning("silabo LLM intento %d/3 falló: %s", _i + 1, str(e)[:120])
        if not d:
            raise (_ultimo_err or RuntimeError("sin respuesta del modelo"))
        tipo = str(d.get("tipo", "otro")).lower().strip()
        cat = str(d.get("categoria", "otro")).lower()
        if cat not in _CATEGORIAS:
            cat = "otro"
        urg = str(d.get("urgencia", "media")).lower()
        if urg not in ("baja", "media", "alta"):
            urg = "media"
        resp = str(d.get("respuesta", "")).strip()
        cita = (str(d.get("cita", "")).strip() or None)
        if cita and cita not in (a.contexto or ""):
            cita = None                                     # solo aceptamos citas que SÍ están en el contexto
        tema = (str(d.get("tema", "")).strip() or None)
        if tema:
            tema = tema[:120]
        fuente = str(d.get("fuente", "")).strip().lower()
        if fuente not in ("corpus", "general", "ninguna"):
            fuente = "corpus" if cita else "general"
        if fuente == "corpus" and not cita:
            fuente = "general"      # 'corpus' sin cita válida = no está respaldado por el material → conocimiento general
        necesita = bool(d.get("necesita_docente", False))
        # Separación de planos (Evidence Core) tal como la propuso el modelo (el servicio la sanea).
        hecho = str(d.get("hecho", "")).strip()
        inferencia = str(d.get("inferencia", "")).strip()
        recomendacion = str(d.get("recomendacion", "")).strip()
        decision = str(d.get("decision_docente", "")).strip()
        certeza_sug = str(d.get("certeza", "")).strip().lower()

        # El SERVICIO aplica la política (no confía la decisión final solo al modelo):
        if tipo == "extraccion":
            return ("extraccion", "No puedo darte respuestas de una evaluación en curso. Pero con gusto te ayudo "
                    "a estudiar el tema si quieres.", "evaluación", "media", False, None, tema, "ninguna",
                    _evidencia(recomendacion="Puedo ayudarte a estudiar el tema para que llegues preparado/a.",
                               decision="Las respuestas de una evaluación en curso las libera tu docente.",
                               fuente="ninguna", certeza_sug="revision_docente"))
        if tipo in _TIPOS_DERIVACION:
            return (tipo, _derivacion_texto(a), "logística", "alta", False, None, tema, "ninguna",
                    _evidencia(decision="Salud, justificaciones y denuncias las atienden Secretaría Académica y Dirección.",
                               fuente="ninguna", certeza_sug="revision_docente"))
        if tipo in _TIPOS_A_DOCENTE:
            if not resp:
                resp = ("Esto necesita a tu docente; se lo llevé y verás aquí su respuesta.")
            return (tipo, resp, cat, urg, True, None, tema, "ninguna",
                    _evidencia(inferencia=inferencia, necesita=True, fuente="ninguna"))
        # administrativa / conceptual / otro: Runi responde
        ev = _evidencia(hecho, inferencia, recomendacion, decision,
                        fuente=fuente, cita=cita, necesita=necesita, certeza_sug=certeza_sug)
        return (tipo or "conceptual", resp or "Déjame reintentar; reformula tu pregunta con un poco más de detalle.",
                cat, urg, necesita, cita, tema, fuente, ev)
    except Exception as e:  # noqa: BLE001
        logger.warning("silabo _clasificar_y_responder falló: %s", str(e)[:150])
        # Si el MOTOR está caído (clave rechazada, red, cuota), no es que la pregunta no se
        # pueda responder: es que no hay con qué responderla. Marcarlo 'fuera_corpus' era
        # doblemente dañino — le decía al estudiante que reformulara una pregunta perfecta, y
        # le ensuciaba al docente el mapa de vacíos con temas que Runi nunca llegó a intentar.
        if _es_falla_de_servicio(e):
            return ("servicio_caido",
                    "Ahora mismo no puedo responder: mi conexión con el motor de respuestas está "
                    "caída. No es tu pregunta — vuelve a intentarlo en un rato.",
                    "otro", "baja", False, None, None, "ninguna",
                    _evidencia(decision="Servicio de IA no disponible.", fuente="ninguna",
                               certeza_sug="insuficiente"))
        # Fallback INTELIGENTE: meta-estudio se responde igual (nunca se escala por un fallo del modelo);
        # solo lo genuinamente no resoluble cae al docente.
        if _es_meta_estudio(pregunta):
            return ("conceptual", _FALLBACK_ESTUDIO, "contenido", "baja", False, None, "estrategia de estudio", "general",
                    _evidencia(recomendacion="Divide por unidades, prioriza por ponderación y repasa con autoevaluación.",
                               fuente="general", certeza_sug="preliminar"))
        return ("fuera_corpus", "No pude resolver tu duda ahora mismo; reintento y, si sigue, la lleva tu docente. "
                "Mientras tanto, ¿puedes reformularla o darme un poco más de detalle?",
                "otro", "media", False, None, None, "ninguna",
                _evidencia(decision="Si no logro resolverlo, lo revisa tu docente.", fuente="ninguna",
                           certeza_sug="insuficiente"))


def mis_consultas(db: Session, codigo: str, device_id: str) -> dict:
    """El estudiante ve SUS consultas con estado, reloj y la respuesta del docente cuando llega."""
    a = agente_por_codigo(db, codigo)
    if not device_id:
        return {"nombre_curso": a.nombre_curso, "consultas": []}
    q = (db.query(MensajeSilabo)
         .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
         .order_by(MensajeSilabo.created_at.desc()).limit(60).all())
    ahora = _ahora()
    out = []
    for m in q:
        restante = None
        if m.estado == MSG_PENDIENTE and m.vence_ts:
            restante = max(0, int(m.vence_ts) - ahora)
        out.append({"id": str(m.id), "pregunta": m.pregunta, "respuesta_ia": m.respuesta_ia,
                    "respuesta_docente": m.respuesta_docente, "estado": m.estado, "tipo": m.tipo,
                    "cita": getattr(m, "cita", None), "confianza": getattr(m, "confianza", None),
                    "evidencia": getattr(m, "evidencia", None),
                    "respondido_por": getattr(m, "respondido_por", None),
                    "necesita_docente": m.necesita_docente, "segundos_restantes": restante,
                    "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None})
    return {"nombre_curso": a.nombre_curso, "consultas": out}


# ── bandeja (docente) ────────────────────────────────────────────────────────────────
def _derivada_dict(m: MensajeSilabo) -> dict:
    """Registro de trazabilidad de una derivación institucional. Muestra el HECHO (tipo + fecha),
    pero el CONTENIDO queda RESERVADO para salud y denuncia (Ley 21.719 · minimización; la denuncia
    puede ser sobre el propio docente → canal institucional separado). Justificación sí se muestra."""
    reservado = getattr(m, "tipo", None) in ("personal_salud", "denuncia")
    return {"id": str(m.id), "tipo": getattr(m, "tipo", None), "alias": m.alias,
            "contenido": (None if reservado else m.pregunta), "reservado": reservado,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}


def bandeja(db: Session, course_id, solo_pendientes: bool = False) -> dict:
    a = agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "mensajes": [], "conteos": {}, "derivadas": [], "derivadas_conteo": {}}
    _escalar_vencidos(db, a)                             # nivel-2 vencidos suben solos al profesor
    q = db.query(MensajeSilabo).filter(MensajeSilabo.agente_id == a.id)
    msgs = q.order_by(MensajeSilabo.created_at.desc()).limit(400).all()
    conteos = {"total": 0, "pendientes": 0, "por_categoria": {}, "con_ayudante": 0}
    salida, derivadas, der_conteo = [], [], {}
    for m in msgs:
        if getattr(m, "tipo", None) in _TIPOS_DERIVACION:
            derivadas.append(_derivada_dict(m))
            der_conteo[m.tipo] = der_conteo.get(m.tipo, 0) + 1
            continue                                    # no entran a la bandeja normal
        conteos["total"] += 1
        if m.estado == MSG_PENDIENTE:
            conteos["pendientes"] += 1
            if getattr(m, "nivel", 3) == 2:
                conteos["con_ayudante"] += 1
        conteos["por_categoria"][m.categoria or "otro"] = conteos["por_categoria"].get(m.categoria or "otro", 0) + 1
        if solo_pendientes and m.estado != MSG_PENDIENTE:
            continue
        salida.append(_msg_dict(m))
    # Agrupar equivalentes ENTRE LOS PENDIENTES: se muestra un representante por grupo con el nº de
    # equivalentes (para "un clic responde a los N"). Los ya resueltos/respondidos pasan sin agrupar.
    pend = [d for d in salida if d["estado"] == MSG_PENDIENTE]
    otros = [d for d in salida if d["estado"] != MSG_PENDIENTE]
    reps, usados = [], set()
    for d in pend:
        if d["id"] in usados:
            continue
        t = _tokens(d["pregunta"])
        grupo = [d]
        for e in pend:
            if e["id"] != d["id"] and e["id"] not in usados and _es_equivalente(t, e["pregunta"]):
                grupo.append(e); usados.add(e["id"])
        usados.add(d["id"])
        d["equivalentes"] = len(grupo)
        d["equivalentes_alias"] = [g.get("alias") for g in grupo if g.get("alias")]
        reps.append(d)
    return {"agente": _agente_dict(a), "mensajes": reps + otros, "conteos": conteos,
            "derivadas": derivadas, "derivadas_conteo": der_conteo}


# ── Mapa de confusión (trazabilidad): agrupa las consultas por TEMA, las jerarquiza por volumen y marca
# las BRECHAS (donde Runi tuvo que derivar) para que el profesor oriente los repasos. Protocolo §8.1.
_TIPOS_NO_ACADEMICO = ("personal_salud", "denuncia", "justificacion", "solicitud_humana")
def mapa_confusion(db: Session, course_id) -> dict:
    a = agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "temas": [], "resumen": {"total": 0}}
    msgs = (db.query(MensajeSilabo).filter(MensajeSilabo.agente_id == a.id)
            .order_by(MensajeSilabo.created_at.desc()).limit(1500).all())
    acad = [m for m in msgs if (getattr(m, "tipo", None) or "") not in _TIPOS_NO_ACADEMICO]
    temas = {}
    for m in acad:
        key = (getattr(m, "tema", None) or "").strip() or "Sin clasificar"
        t = temas.get(key)
        if not t:
            t = temas[key] = {"tema": key, "total": 0, "pendientes": 0, "resueltos": 0, "derivados": 0,
                              "urgencia_alta": 0, "por_fuente": {"corpus": 0, "general": 0, "ninguna": 0},
                              "categorias": {}, "ejemplos": []}
        t["total"] += 1
        if m.necesita_docente:
            t["derivados"] += 1
        if m.estado == MSG_PENDIENTE:
            t["pendientes"] += 1
        if getattr(m, "respuesta_docente", None):
            t["resueltos"] += 1
        if (m.urgencia or "") == "alta":
            t["urgencia_alta"] += 1
        f = (getattr(m, "fuente", None) or "general")
        if f in t["por_fuente"]:
            t["por_fuente"][f] += 1
        cat = m.categoria or "otro"
        t["categorias"][cat] = t["categorias"].get(cat, 0) + 1
        if len(t["ejemplos"]) < 3:
            t["ejemplos"].append((m.pregunta or "")[:160])
    lista = sorted(temas.values(), key=lambda x: (x["total"], x["derivados"]), reverse=True)
    for t in lista:
        t["tasa_derivacion"] = round(t["derivados"] / t["total"], 2) if t["total"] else 0.0
        t["categoria"] = (max(t["categorias"], key=t["categorias"].get) if t["categorias"] else "otro")
        del t["categorias"]
    total = len(acad)
    derivados = sum(1 for m in acad if m.necesita_docente)
    fuente_tot = {"corpus": 0, "general": 0, "ninguna": 0}
    for m in acad:
        f = (getattr(m, "fuente", None) or "general")
        if f in fuente_tot:
            fuente_tot[f] += 1
    resumen = {"total": total, "temas": len(lista), "derivados": derivados,
               "resueltos_runi": total - derivados,
               "tasa_resolucion": round((total - derivados) / total, 2) if total else 0.0,
               "por_fuente": fuente_tot}
    return {"agente": _agente_dict(a), "temas": lista, "resumen": resumen}


def responder_docente(db: Session, mensaje_id, respuesta: str, quien: str = "docente") -> dict:
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    resp = (respuesta or "").strip()
    m.respuesta_docente = resp
    m.estado = MSG_RESUELTA
    m.respondido_por = quien
    # "Un clic responde a los N": aplica la MISMA respuesta a todos los pendientes equivalentes.
    t = _tokens(m.pregunta)
    n = 1
    if t:
        otros = (db.query(MensajeSilabo)
                 .filter(MensajeSilabo.agente_id == m.agente_id, MensajeSilabo.estado == MSG_PENDIENTE,
                         MensajeSilabo.id != m.id).limit(400).all())
        for o in otros:
            if _es_equivalente(t, o.pregunta):
                o.respuesta_docente = resp
                o.estado = MSG_RESUELTA
                o.respondido_por = quien
                n += 1
    db.commit(); db.refresh(m)
    d = _msg_dict(m); d["respondidos"] = n
    return d


def delegar_al_ayudante(db: Session, mensaje_id) -> dict:
    """El PROFESOR pasa una duda ACADÉMICA puntual a su ayudante (nivel 3 → 2). El ayudante SOLO ve lo delegado
    (nunca intercepta la cola). Lo reservado (salud/denuncia/justificación) NO es delegable. Si el ayudante no
    responde en 24 h, vuelve solo al profesor (_escalar_vencidos)."""
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    a = db.query(SilaboAgente).filter(SilaboAgente.id == m.agente_id).first()
    if not a or not a.ayudante_activo:
        raise conflict("Activa primero el ayudante para poder delegar.")
    if getattr(m, "tipo", None) in _TIPOS_DERIVACION:
        raise conflict("Esto es reservado (salud/denuncia/justificación) y no se delega; va a Secretaría/Dirección.")
    if m.estado != MSG_PENDIENTE:
        raise conflict("Solo se puede delegar una consulta pendiente.")
    m.nivel = 2
    m.vence_ts = _ahora() + _PLAZO_AYUDANTE_H * 3600
    m.motivo_escalamiento = None
    db.commit(); db.refresh(m)
    return _msg_dict(m)


def subir_al_profesor(db: Session, mensaje_id, motivo: str) -> dict:
    """El ayudante sube una consulta al profesor (nivel 2 → 3) con un motivo obligatorio."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise conflict("Indique en una línea por qué la sube al profesor.")
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    m.nivel = 3
    m.motivo_escalamiento = motivo[:255]
    m.vence_ts = _ahora() + _PLAZO_DOCENTE_H * 3600
    db.commit(); db.refresh(m)
    return _msg_dict(m)


def tablero_ayudante(db: Session, codigo: str) -> dict:
    """Cola del ayudante (nivel 2): pendientes agrupados. Sube solos los vencidos antes de listar."""
    a = agente_por_ayudante_codigo(db, codigo)
    if not a.ayudante_activo:
        raise conflict("El tablero de ayudante no está activo.")
    _escalar_vencidos(db, a)
    pend = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.estado == MSG_PENDIENTE,
                    MensajeSilabo.nivel == 2)
            .order_by(MensajeSilabo.created_at.asc()).limit(200).all())
    dicts = [_msg_dict(m) for m in pend]
    # agrupa equivalentes (mismo "1 clic responde a los N")
    reps, usados = [], set()
    for d in dicts:
        if d["id"] in usados:
            continue
        t = _tokens(d["pregunta"])
        n = 1
        for e in dicts:
            if e["id"] != d["id"] and e["id"] not in usados and _es_equivalente(t, e["pregunta"]):
                n += 1; usados.add(e["id"])
        usados.add(d["id"]); d["equivalentes"] = n
        reps.append(d)
    return {"nombre_curso": a.nombre_curso, "consultas": reps}


_FAQ_HEADER = "# Preguntas ya resueltas por el docente (fuente canónica)"


def agregar_al_contexto(db: Session, mensaje_id) -> dict:
    """El corpus crece por uso: promueve una consulta ya respondida a FUENTE del contexto, para que
    la IA responda futuras preguntas parecidas por sí sola (y las cite). Cerrar el círculo (doc #11)."""
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    a = db.query(SilaboAgente).filter(SilaboAgente.id == m.agente_id).first()
    if not a:
        raise not_found("Agente no encontrado.")
    resp = (m.respuesta_docente or m.respuesta_ia or "").strip()
    preg = (m.pregunta or "").strip()
    if not resp or not preg:
        raise conflict("La consulta aún no tiene respuesta para agregar.")
    ctx = a.contexto or ""
    if preg and preg in ctx:
        return {"ok": True, "ya": True}                     # ya estaba
    if _FAQ_HEADER not in ctx:
        ctx = ctx.rstrip() + "\n\n" + _FAQ_HEADER + "\n"
    a.contexto = ctx.rstrip() + "\n\nP: " + preg + "\nR: " + resp
    db.commit(); db.refresh(a)
    return {"ok": True, "agregado": True}


def marcar_estado(db: Session, mensaje_id, estado: str) -> dict:
    if estado not in (MSG_RESPONDIDA, MSG_PENDIENTE, MSG_RESUELTA):
        raise conflict("Estado no válido.")
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    m.estado = estado
    db.commit(); db.refresh(m)
    return _msg_dict(m)


# ── serialización ────────────────────────────────────────────────────────────────────
def _uuid(x):
    import uuid as _u
    try:
        return x if isinstance(x, _u.UUID) else _u.UUID(str(x))
    except (ValueError, TypeError):
        raise not_found("Identificador no válido.")


def _agente_dict(a: SilaboAgente) -> dict:
    return {"id": str(a.id), "codigo": a.codigo, "activo": a.activo,
            "nombre_curso": a.nombre_curso, "tiene_contexto": bool((a.contexto or "").strip()),
            "contexto": a.contexto or "", "config": a.config or {},
            "ayudante_activo": bool(getattr(a, "ayudante_activo", False)),
            "ayudante_codigo": getattr(a, "ayudante_codigo", None)}


def _msg_dict(m: MensajeSilabo) -> dict:
    restante = None
    if m.estado == MSG_PENDIENTE and getattr(m, "vence_ts", None):
        restante = int(m.vence_ts) - _ahora()
    return {"id": str(m.id), "alias": m.alias, "pregunta": m.pregunta,
            "respuesta_ia": m.respuesta_ia, "tipo": getattr(m, "tipo", None),
            "cita": getattr(m, "cita", None), "tema": getattr(m, "tema", None), "fuente": getattr(m, "fuente", None),
            "evidencia": getattr(m, "evidencia", None),
            "categoria": m.categoria, "urgencia": m.urgencia,
            "estado": m.estado, "necesita_docente": m.necesita_docente,
            "nivel": getattr(m, "nivel", 3), "respondido_por": getattr(m, "respondido_por", None),
            "motivo_escalamiento": getattr(m, "motivo_escalamiento", None),
            "respuesta_docente": m.respuesta_docente, "segundos_restantes": restante,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}
