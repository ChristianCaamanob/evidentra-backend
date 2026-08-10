"""La Guarida de Runi · lógica de pausa restaurativa con TIEMPO DE SERVIDOR.

El servidor es la fuente de verdad del término (`end_at`) y del tiempo real (`actual_seconds`).
El cliente sólo anima el conteo entre sincronizaciones; al restaurar una pestaña vuelve a preguntar
`active` y recibe el `remaining_ms` recalculado por el servidor. Nunca se penaliza el descanso.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.runi_break import RuniBreak, ZONAS


def _as_uuid(v):
    if isinstance(v, _uuid.UUID):
        return v
    try:
        return _uuid.UUID(str(v))
    except Exception:  # noqa: BLE001
        raise not_found("Pausa no encontrada.")

_MIN_OK = {2, 5, 10, 15}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _dto(b: RuniBreak) -> dict:
    now = _now()
    end = _aware(b.end_at) or now
    remaining = int(max(0, (end - now).total_seconds() * 1000))
    return {
        "break_id": str(b.id), "estado": b.estado, "zone": b.zone,
        "planned_minutes": b.planned_minutes, "extended_count": b.extended_count,
        "added_minutes_total": b.added_minutes_total, "actual_seconds": b.actual_seconds,
        "started_at": _aware(b.started_at).isoformat() if b.started_at else None,
        "end_at": end.isoformat(),
        "server_now": now.isoformat(),
        "remaining_ms": remaining if b.estado == "active" else 0,
        "outcome_source": b.outcome_source,
    }


def start(db: Session, pseudo_id: str, zone: str, planned_minutes: int,
          course_id: str | None = None, source_session_id: str | None = None) -> dict:
    pid = (pseudo_id or "").strip()
    if not pid:
        raise unprocessable("Falta pseudo_id (identidad seudonimizada).")
    z = zone if zone in ZONAS else "calm"
    m = int(planned_minutes or 5)
    if m not in _MIN_OK:
        m = 5
    now = _now()
    b = RuniBreak(pseudo_id=pid[:80], course_id=(str(course_id)[:64] if course_id else None),
                  source_session_id=(str(source_session_id)[:80] if source_session_id else None),
                  zone=z, planned_minutes=m, extended_count=0, added_minutes_total=0,
                  estado="active", started_at=now, end_at=now + timedelta(minutes=m))
    db.add(b)
    db.commit()
    db.refresh(b)
    return _dto(b)


def state(db, break_id, action: str, added_minutes: int = 5, source: str | None = None) -> dict:
    b = db.get(RuniBreak, _as_uuid(break_id))
    if not b:
        raise not_found("Pausa no encontrada.")
    now = _now()
    if action == "extend":
        add = int(added_minutes or 5)
        if add not in _MIN_OK:
            add = 5
        # extender NO reinicia: suma tiempo al término actual (o a 'ahora' si ya venció)
        base = max(_aware(b.end_at) or now, now)
        b.end_at = base + timedelta(minutes=add)
        b.extended_count = (b.extended_count or 0) + 1
        b.added_minutes_total = (b.added_minutes_total or 0) + add
        b.estado = "active"
    elif action in ("complete", "end_early", "return", "finish_day"):
        mapa = {"complete": "completed", "end_early": "ended_early", "return": "returned", "finish_day": "finished_day"}
        b.estado = mapa[action]
        b.closed_at = now
        b.actual_seconds = int(max(0, (now - (_aware(b.started_at) or now)).total_seconds()))
        if source:
            b.outcome_source = str(source)[:40]
    else:
        raise unprocessable("Acción de pausa desconocida.")
    db.commit()
    db.refresh(b)
    return _dto(b)


def active(db: Session, pseudo_id: str) -> dict:
    """La pausa activa más reciente del estudiante (para restaurar al reabrir la pestaña)."""
    pid = (pseudo_id or "").strip()
    if not pid:
        return {"active": None}
    b = (db.query(RuniBreak)
         .filter(RuniBreak.pseudo_id == pid, RuniBreak.estado == "active")
         .order_by(RuniBreak.started_at.desc()).first())
    return {"active": _dto(b) if b else None}
