"""
Ingesta de eventos de analítica con ESQUEMA ESTRICTO (EVENT_CATALOG v1).

Regla: si falta un campo requerido del envelope, el `event` no está en el catálogo, el `domain`
no coincide, o faltan `props` requeridas → el evento se RECHAZA (422) y NO se persiste.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.analytics import AnalyticsEvent

CATALOG_VERSION = "v1"

# event → (domain, [props requeridas])
EVENT_SCHEMA: dict[str, tuple[str, list[str]]] = {
    # producto
    "qr_open": ("producto", ["codigo"]),
    "app_open": ("producto", []),
    "signup": ("producto", ["rol"]),
    "first_value": ("producto", ["tipo"]),
    "action_start": ("producto", ["action"]),
    "action_complete": ("producto", ["action"]),
    "schedule_loaded": ("producto", ["bloques"]),
    "course_connected": ("producto", ["course_id"]),
    "recommendation_shown": ("producto", ["rec_id"]),
    "recommendation_accepted": ("producto", ["rec_id"]),
    "recommendation_rejected": ("producto", ["rec_id", "motivo"]),
    "nav_error": ("producto", ["pantalla"]),
    "post_task_survey": ("producto", ["sat", "seq"]),
    "video_open": ("producto", ["code"]),
    "video_error": ("producto", ["code"]),
    # aprendizaje (eventos atómicos; el objeto Episode se arma vía episode_service)
    "episode_start": ("aprendizaje", ["course_id", "ra"]),
    "retrieval_attempt": ("aprendizaje", ["item_id", "ra"]),
    "response_submitted": ("aprendizaje", ["item_id", "correct", "confidence"]),
    "feedback_shown": ("aprendizaje", ["item_id"]),
    "episode_close": ("aprendizaje", []),
    "check_immediate": ("aprendizaje", ["item_id", "correct"]),
    "check_deferred": ("aprendizaje", ["item_id", "correct", "ventana"]),
    "transfer_item": ("aprendizaje", ["item_id", "correct"]),
    "mastery_update": ("aprendizaje", ["ra", "nivel"]),
    # identidad
    "identity_verified": ("identidad", ["course_id", "metodo"]),
    "consent_set": ("identidad", ["version", "scope"]),
    "personalization_changed": ("identidad", ["clave"]),
    # seguridad / privacidad
    "location_share_on": ("seguridad", ["precision"]),
    "location_share_off": ("seguridad", []),
    "privacy_quiz": ("seguridad", ["score"]),
    "privacy_revoke": ("seguridad", ["ok"]),
    "content_report": ("seguridad", ["tipo"]),
    "admin_access": ("seguridad", ["recurso"]),
    "moderation_action": ("seguridad", ["accion"]),
}

_DEVICES = {"movil", "tablet", "desktop"}


def _validar(e: dict) -> dict:
    ev = str(e.get("event") or "")
    if ev not in EVENT_SCHEMA:
        raise unprocessable(f"Evento desconocido o no catalogado: '{ev}'.")
    dom, req = EVENT_SCHEMA[ev]
    if str(e.get("event_version") or CATALOG_VERSION) != CATALOG_VERSION:
        raise unprocessable("Versión de evento no soportada.")
    if not (e.get("pseudo_id") or "").strip():
        raise unprocessable("Falta pseudo_id (identidad seudonimizada).")
    props = e.get("props") or {}
    faltan = [k for k in req if props.get(k) is None]
    if faltan:
        raise unprocessable(f"Evento '{ev}' incompleto; faltan props: {', '.join(faltan)}.")
    dev = e.get("device")
    if dev is not None and dev not in _DEVICES:
        raise unprocessable("device inválido.")
    return {"event": ev, "domain": dom, "props": props}


def ingest(db: Session, payload: dict) -> dict:
    """Un evento. Rechaza (422) si es inválido/incompleto."""
    e = payload or {}
    v = _validar(e)
    row = AnalyticsEvent(event=v["event"], event_version=CATALOG_VERSION, domain=v["domain"],
                         pseudo_id=str(e.get("pseudo_id"))[:80], course_id=(str(e.get("course_id"))[:64] if e.get("course_id") else None),
                         session_id=(str(e.get("session_id"))[:80] if e.get("session_id") else None),
                         segment=(str(e.get("segment"))[:40] if e.get("segment") else None),
                         device=e.get("device"), props=v["props"], client_ts=(str(e.get("ts"))[:40] if e.get("ts") else None))
    db.add(row); db.commit()
    return {"ok": True, "id": str(row.id)}


def ingest_batch(db: Session, eventos: list) -> dict:
    """Lote: valida todos ANTES de persistir (todo-o-nada) para no dejar mezclas parciales."""
    eventos = eventos or []
    if not isinstance(eventos, list) or not eventos:
        raise unprocessable("Se esperaba una lista de eventos.")
    if len(eventos) > 100:
        raise unprocessable("Máximo 100 eventos por lote.")
    validados = [(_validar(e), e) for e in eventos]   # lanza 422 si alguno es inválido
    for v, e in validados:
        db.add(AnalyticsEvent(event=v["event"], event_version=CATALOG_VERSION, domain=v["domain"],
                              pseudo_id=str(e.get("pseudo_id"))[:80], course_id=(str(e.get("course_id"))[:64] if e.get("course_id") else None),
                              session_id=(str(e.get("session_id"))[:80] if e.get("session_id") else None),
                              segment=(str(e.get("segment"))[:40] if e.get("segment") else None),
                              device=e.get("device"), props=v["props"], client_ts=(str(e.get("ts"))[:40] if e.get("ts") else None)))
    db.commit()
    return {"ok": True, "aceptados": len(validados)}
