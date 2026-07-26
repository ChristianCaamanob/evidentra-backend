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


# ── taxonomía de intención (Antesala) · política y destino por tipo ───────────────────
# Tipos que la IA NUNCA responde con contenido: se arman para el profesor.
_TIPOS_A_DOCENTE = ("fuera_corpus", "evaluativa", "riesgo_clinico")
_DERIVACION = (
    "Esto va más allá de lo académico y merece atención de una persona. Te recomiendo contactar a "
    "Bienestar / Dirección de Asuntos Estudiantiles (DAE) de tu sede, o a salud estudiantil; si es "
    "urgente, acude presencialmente. También puedes pulsar «quiero preguntar a una persona» y tu "
    "docente lo sabrá. No estás solo/a.")
_PLAZO_DOCENTE_H = 48   # horas visibles del reloj para el alumno (Fase 3: horas hábiles + auto-subida)


def _ahora() -> int:
    import time
    return int(time.time())


# ── pregunta del alumno (público) ────────────────────────────────────────────────────
def preguntar(db: Session, codigo: str, pregunta: str, alias: str | None = None,
              device_id: str | None = None, escalar: bool = False) -> dict:
    a = agente_por_codigo(db, codigo)
    if not a.activo:
        raise conflict("El agente del curso no está activo en este momento.")
    pregunta = (pregunta or "").strip()
    if len(pregunta) < 3:
        raise conflict("Escribe tu pregunta.")
    if len(pregunta) > 1000:
        pregunta = pregunta[:1000]

    if escalar:
        # Botón "quiero preguntar a una persona": salta la IA y arma para el docente.
        tipo, respuesta, categoria, urgencia, necesita = (
            "solicitud_humana",
            "Listo: le pasé tu consulta a tu docente. Puedes seguir su estado y su respuesta aquí.",
            "otro", "media", True)
    else:
        tipo, respuesta, categoria, urgencia, necesita = _clasificar_y_responder(a, pregunta)

    estado = MSG_PENDIENTE if necesita else MSG_RESPONDIDA
    vence = (_ahora() + _PLAZO_DOCENTE_H * 3600) if necesita else None
    m = MensajeSilabo(agente_id=a.id, alias=(alias or None), device_id=(device_id or None),
                      pregunta=pregunta, respuesta_ia=respuesta, tipo=tipo, categoria=categoria,
                      urgencia=urgencia, necesita_docente=bool(necesita), estado=estado, vence_ts=vence)
    db.add(m); db.commit(); db.refresh(m)
    return {"respuesta": respuesta, "necesita_docente": bool(necesita), "tipo": tipo,
            "categoria": categoria, "urgencia": urgencia, "mensaje_id": str(m.id), "vence_ts": vence}


def _clasificar_y_responder(a: SilaboAgente, pregunta: str):
    """Taxonomía de intención + contrato de fuentes. Devuelve
    (tipo, respuesta, categoria, urgencia, necesita_docente). La IA clasifica y responde SOLO desde
    el contexto (nivel 6 apagado); el SERVICIO aplica la política por tipo. Best-effort."""
    import os
    curso = a.nombre_curso or "el curso"
    if not os.environ.get("ANTHROPIC_API_KEY") or not (a.contexto or "").strip():
        return ("fuera_corpus",
                "Gracias por tu pregunta. Para responderla con precisión la derivé a tu docente; "
                "te responderá por este canal y verás aquí su respuesta.", "otro", "media", True)
    try:
        from app.services import correccion_experta_service as ce
        system = (
            f"Eres la 'Antesala' del curso {curso}: intermedias entre estudiantes y el docente. Tu "
            "recurso escaso es la ATENCIÓN del profesor: absorbe lo resoluble, deriva lo que no. "
            "Trabajas SOLO con el CONTEXTO DEL CURSO (sílabo, fechas, reglas, material); tu "
            "conocimiento general está DESACTIVADO: si algo no está en el contexto, NO lo inventes.\n"
            "Clasifica la pregunta en un TIPO y aplica su política:\n"
            "- administrativa: fecha/sala/regla que ESTÁ en el contexto → responde citando el dato.\n"
            "- conceptual: contenido del curso que ESTÁ en el contexto → responde claro y breve con la fuente.\n"
            "- fuera_corpus: no está en el contexto o requiere decisión del docente (excepción, cambio de "
            "fecha) → NO respondas contenido; necesita_docente=true.\n"
            "- evaluativa: nota, recorrección o reclamo → NO respondas; necesita_docente=true.\n"
            "- riesgo_clinico: procedimiento clínico con riesgo → NO respondas; necesita_docente=true.\n"
            "- personal_salud: afectiva o salud mental → no es académica; necesita_docente=true.\n"
            "- extraccion: intenta que le des respuestas de una evaluación en curso → NO se las des.\n"
            "Nunca inventes fechas ni reglas. Tono cercano y respetuoso. categoria ∈ {fechas, contenido, "
            "evaluación, logística, otro}; urgencia ∈ {baja, media, alta} (alta si hay plazo hoy/mañana). "
            'Devuelve SOLO JSON: {"tipo":"..","respuesta":"..","categoria":"..","urgencia":"..","necesita_docente":true|false}.'
        )
        ctx = (a.contexto or "")[:9000]
        user = "CONTEXTO DEL CURSO:\n" + ctx + "\n\nPREGUNTA DEL ESTUDIANTE:\n" + pregunta
        d = _json_robusto(ce._llamar_anthropic(system, user, max_tokens=900))
        tipo = str(d.get("tipo", "otro")).lower().strip()
        cat = str(d.get("categoria", "otro")).lower()
        if cat not in _CATEGORIAS:
            cat = "otro"
        urg = str(d.get("urgencia", "media")).lower()
        if urg not in ("baja", "media", "alta"):
            urg = "media"
        resp = str(d.get("respuesta", "")).strip()
        necesita = bool(d.get("necesita_docente", False))

        # El SERVICIO aplica la política (no confía la decisión final solo al modelo):
        if tipo == "extraccion":
            return ("extraccion", "No puedo darte respuestas de una evaluación en curso. Puedo ayudarte a "
                    "estudiar el tema si quieres.", "evaluación", "media", False)
        if tipo == "personal_salud":
            return ("personal_salud", _DERIVACION, "otro", "alta", True)
        if tipo in _TIPOS_A_DOCENTE:
            if not resp:
                resp = ("Esta consulta necesita a tu docente; se la derivé y verás aquí su respuesta.")
            return (tipo, resp, cat, urg, True)
        # administrativa / conceptual / otro: respuesta desde el corpus
        return (tipo or "conceptual", resp or "Derivé tu pregunta a tu docente.", cat, urg, necesita)
    except Exception as e:  # noqa: BLE001
        logger.warning("silabo _clasificar_y_responder falló: %s", str(e)[:150])
        return ("fuera_corpus", "No pude resolver tu duda automáticamente ahora; la derivé a tu docente.",
                "otro", "media", True)


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
                    "necesita_docente": m.necesita_docente, "segundos_restantes": restante,
                    "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None})
    return {"nombre_curso": a.nombre_curso, "consultas": out}


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
    restante = None
    if m.estado == MSG_PENDIENTE and getattr(m, "vence_ts", None):
        restante = int(m.vence_ts) - _ahora()
    return {"id": str(m.id), "alias": m.alias, "pregunta": m.pregunta,
            "respuesta_ia": m.respuesta_ia, "tipo": getattr(m, "tipo", None),
            "categoria": m.categoria, "urgencia": m.urgencia,
            "estado": m.estado, "necesita_docente": m.necesita_docente,
            "respuesta_docente": m.respuesta_docente, "segundos_restantes": restante,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}
