"""Escudo de comunicación — lógica del agente de sílabo + bandeja clasificada (Pilar II).

La IA responde SOLO con el contexto del curso que cargó el docente. Si la pregunta no está
cubierta o requiere una decisión humana (cambio de fecha, excepción, nota), la marca para la
bandeja del docente. Todo se persiste clasificado (categoría + urgencia + estado).
"""
from __future__ import annotations

import json
import logging
import secrets

from sqlalchemy.orm import Session

from app.core.errors import not_found, conflict
from app.models.silabo import (
    SilaboAgente, MensajeSilabo, MSG_RESPONDIDA, MSG_PENDIENTE, MSG_RESUELTA,
)

logger = logging.getLogger("evalys")
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


# ── pregunta del alumno (público) ────────────────────────────────────────────────────
def preguntar(db: Session, codigo: str, pregunta: str, alias: str | None = None) -> dict:
    a = agente_por_codigo(db, codigo)
    if not a.activo:
        raise conflict("El agente del curso no está activo en este momento.")
    pregunta = (pregunta or "").strip()
    if len(pregunta) < 3:
        raise conflict("Escribe tu pregunta.")
    if len(pregunta) > 1000:
        pregunta = pregunta[:1000]

    respuesta, categoria, urgencia, necesita = _responder_ia(a, pregunta)
    m = MensajeSilabo(agente_id=a.id, alias=(alias or None), pregunta=pregunta,
                      respuesta_ia=respuesta, categoria=categoria, urgencia=urgencia,
                      necesita_docente=bool(necesita),
                      estado=(MSG_PENDIENTE if necesita else MSG_RESPONDIDA))
    db.add(m); db.commit(); db.refresh(m)
    return {"respuesta": respuesta, "necesita_docente": bool(necesita),
            "categoria": categoria, "urgencia": urgencia, "mensaje_id": str(m.id)}


def _responder_ia(a: SilaboAgente, pregunta: str):
    """Devuelve (respuesta, categoria, urgencia, necesita_docente). Best-effort: sin IA o si
    falla, deriva al docente con un mensaje honesto."""
    import os
    curso = a.nombre_curso or "el curso"
    if not os.environ.get("ANTHROPIC_API_KEY") or not (a.contexto or "").strip():
        return ("Gracias por tu pregunta. Para responderla con precisión la derivé a tu docente; "
                "te responderá por este canal.", "otro", "media", True)
    try:
        from app.services import correccion_experta_service as ce
        system = (
            f"Eres el asistente oficial del sílabo de {curso}. Respondes dudas de estudiantes 24/7, "
            "SOLO con base en el CONTEXTO DEL CURSO que te doy (sílabo, fechas, reglas, evaluación). "
            "Reglas: (1) Si la respuesta está en el contexto, respóndela clara y breve, citando el dato. "
            "(2) Si NO está en el contexto, o requiere una DECISIÓN del docente (cambiar una fecha, una "
            "excepción, una nota, un caso personal), NO la inventes: dilo con amabilidad y marca "
            "necesita_docente=true. (3) Nunca inventes fechas ni reglas. Tono cercano y respetuoso. "
            "Clasifica la pregunta en categoria ∈ {fechas, contenido, evaluación, logística, otro} y "
            "urgencia ∈ {baja, media, alta} (alta si menciona plazo hoy/mañana o un problema que bloquea). "
            'Devuelve SOLO JSON: {"respuesta":"..","categoria":"..","urgencia":"..","necesita_docente":true|false}.'
        )
        ctx = (a.contexto or "")[:8000]
        user = "CONTEXTO DEL CURSO:\n" + ctx + "\n\nPREGUNTA DEL ESTUDIANTE:\n" + pregunta
        d = _json_robusto(ce._llamar_anthropic(system, user, max_tokens=900))
        cat = str(d.get("categoria", "otro")).lower()
        if cat not in _CATEGORIAS:
            cat = "otro"
        urg = str(d.get("urgencia", "media")).lower()
        if urg not in ("baja", "media", "alta"):
            urg = "media"
        resp = str(d.get("respuesta", "")).strip() or "Derivé tu pregunta a tu docente."
        return (resp, cat, urg, bool(d.get("necesita_docente", False)))
    except Exception as e:  # noqa: BLE001
        logger.warning("silabo _responder_ia falló: %s", str(e)[:150])
        return ("No pude resolver tu duda automáticamente ahora; la derivé a tu docente.",
                "otro", "media", True)


# ── bandeja (docente) ────────────────────────────────────────────────────────────────
def bandeja(db: Session, course_id, solo_pendientes: bool = False) -> dict:
    a = agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "mensajes": [], "conteos": {}}
    q = db.query(MensajeSilabo).filter(MensajeSilabo.agente_id == a.id)
    msgs = q.order_by(MensajeSilabo.created_at.desc()).limit(400).all()
    conteos = {"total": 0, "pendientes": 0, "por_categoria": {}}
    salida = []
    for m in msgs:
        conteos["total"] += 1
        if m.estado == MSG_PENDIENTE:
            conteos["pendientes"] += 1
        conteos["por_categoria"][m.categoria or "otro"] = conteos["por_categoria"].get(m.categoria or "otro", 0) + 1
        if solo_pendientes and m.estado != MSG_PENDIENTE:
            continue
        salida.append(_msg_dict(m))
    return {"agente": _agente_dict(a), "mensajes": salida, "conteos": conteos}


def responder_docente(db: Session, mensaje_id, respuesta: str) -> dict:
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    m.respuesta_docente = (respuesta or "").strip()
    m.estado = MSG_RESUELTA
    db.commit(); db.refresh(m)
    return _msg_dict(m)


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
            "contexto": a.contexto or ""}


def _msg_dict(m: MensajeSilabo) -> dict:
    return {"id": str(m.id), "alias": m.alias, "pregunta": m.pregunta,
            "respuesta_ia": m.respuesta_ia, "categoria": m.categoria, "urgencia": m.urgencia,
            "estado": m.estado, "necesita_docente": m.necesita_docente,
            "respuesta_docente": m.respuesta_docente,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}
