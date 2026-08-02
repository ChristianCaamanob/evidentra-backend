"""
Recordatorios personales del alumno (v2.0) — CRUD + alarma push cuando llega la hora.

La "alarma" se materializa en el barrido push (`tick`): cuando la fecha/hora del recordatorio ya llegó
(hora de Chile, ~UTC-4) y aún no se avisó, se envía la notificación y se marca `avisado`.
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.recordatorio import RecordatorioPersonal

_CL_OFFSET = _dt.timedelta(hours=-4)


def _now_cl() -> _dt.datetime:
    return _dt.datetime.utcnow() + _CL_OFFSET


def _norm_fecha(v) -> str:
    s = str(v or "").strip()[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else ""


def _norm_hora(v) -> str:
    s = re.sub(r"[^0-9:]", "", str(v or ""))
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2))
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else ""


def _dict(r: RecordatorioPersonal) -> dict:
    return {"id": str(r.id), "titulo": r.titulo, "fecha": r.fecha, "hora": r.hora,
            "nota": r.nota, "color": r.color or "#34e5a8", "hecho": bool(r.hecho),
            "avisado": bool(r.avisado)}


def crear(db: Session, owner_key: str, payload: dict) -> dict:
    p = payload or {}
    titulo = str(p.get("titulo") or "").strip()[:160]
    fecha = _norm_fecha(p.get("fecha"))
    hora = _norm_hora(p.get("hora")) or "08:00"
    if not titulo or not fecha:
        raise unprocessable("El recordatorio necesita al menos título y fecha.")
    r = RecordatorioPersonal(owner_key=owner_key, titulo=titulo, fecha=fecha, hora=hora,
                             nota=(str(p.get("nota") or "").strip()[:300] or None),
                             color=(p.get("color") or "#34e5a8"))
    db.add(r); db.commit()
    return {"ok": True, "recordatorio": _dict(r)}


def listar(db: Session, owner_key: str) -> dict:
    filas = db.query(RecordatorioPersonal).filter(RecordatorioPersonal.owner_key == owner_key).all()
    return {"ok": True, "recordatorios": sorted([_dict(r) for r in filas], key=lambda x: (x["fecha"], x["hora"]))}


def eliminar(db: Session, owner_key: str, rid) -> dict:
    try:
        u = _uuid.UUID(str(rid))
    except (ValueError, TypeError):
        raise not_found("Recordatorio no válido.")
    r = db.query(RecordatorioPersonal).filter(RecordatorioPersonal.id == u,
                                              RecordatorioPersonal.owner_key == owner_key).first()
    if not r:
        raise not_found("Recordatorio no encontrado.")
    db.delete(r); db.commit()
    return {"ok": True}


def tick(db: Session) -> int:
    """Envía la alarma de los recordatorios cuya hora ya llegó y no se han avisado. Idempotente."""
    from app.services import push_service as ps
    ahora = _now_cl()
    pendientes = db.query(RecordatorioPersonal).filter(RecordatorioPersonal.avisado == False).all()  # noqa: E712
    enviados = 0
    for r in pendientes:
        try:
            cuando = _dt.datetime.fromisoformat(r.fecha + "T" + (r.hora or "08:00"))
        except ValueError:
            continue
        if cuando <= ahora:
            payload = {"title": "⏰ " + (r.titulo or "Recordatorio"),
                       "body": (r.nota or "Tu recordatorio de Runi.") + " 🦊",
                       "tag": "recordatorio-" + str(r.id), "url": "/?agenda=1",
                       "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}
            enviados += ps.enviar_a_owner(db, r.owner_key, payload)
            r.avisado = True
            db.commit()
    return enviados
