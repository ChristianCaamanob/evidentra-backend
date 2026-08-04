"""
Notas de la Pandilla — servicio CRUD efímero (24 h).

Una nota activa por estudiante (upsert por owner_key). `mi_nota` devuelve la del propio alumno
sólo si sigue vigente (< 24 h). Sin historial: al vencer o borrar, desaparece.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy.orm import Session

from app.models.pand_nota import PandNota

_TTL = _dt.timedelta(hours=24)


def _vigente(r: PandNota) -> bool:
    try:
        ca = r.created_at
        if ca is None:
            return True
        if ca.tzinfo is not None:
            ca = ca.replace(tzinfo=None)
        return (_dt.datetime.utcnow() - ca) < _TTL
    except Exception:
        return True


def _dict(r: PandNota) -> dict:
    return {"id": str(r.id), "texto": r.texto, "char": r.char, "nombre": r.nombre,
            "created_at": r.created_at.isoformat() if r.created_at else None}


def set_nota(db: Session, owner_key: str, payload: dict) -> dict:
    p = payload or {}
    texto = str(p.get("texto") or "").strip()[:90]
    if not texto:
        return eliminar(db, owner_key)
    r = db.query(PandNota).filter(PandNota.owner_key == owner_key).first()
    if r is None:
        r = PandNota(owner_key=owner_key)
        db.add(r)
    r.texto = texto
    r.char = (str(p.get("char") or "").strip()[:40] or None)
    r.nombre = (str(p.get("nombre") or "").strip()[:80] or None)
    r.created_at = _dt.datetime.utcnow()   # renueva la ventana de 24 h
    db.commit()
    return {"ok": True, "nota": _dict(r)}


def mi_nota(db: Session, owner_key: str) -> dict:
    r = db.query(PandNota).filter(PandNota.owner_key == owner_key).first()
    if r is None or not _vigente(r):
        return {"ok": True, "nota": None}
    return {"ok": True, "nota": _dict(r)}


def eliminar(db: Session, owner_key: str) -> dict:
    r = db.query(PandNota).filter(PandNota.owner_key == owner_key).first()
    if r is not None:
        db.delete(r); db.commit()
    return {"ok": True, "nota": None}
