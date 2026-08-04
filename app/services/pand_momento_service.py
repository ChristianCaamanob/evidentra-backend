"""
Momentos de la Pandilla — servicio CRUD efímero (24 h) + moderación.

Un momento activo por estudiante (upsert por owner_key). `feed` devuelve el propio momento sólo si
sigue vigente (< 24 h) y no está oculto. `reportar` incrementa reportes y oculta al superar el umbral.
Sin historial: al vencer, borrar o superar reportes, desaparece del feed.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.pand_momento import PandMomento

_TTL = _dt.timedelta(hours=24)
_MAX_B64 = 8 * 1024 * 1024          # ~8 MB de data-URL (imagen ya reescalada en cliente)
_REPORT_HIDE = 3                    # se oculta al alcanzar N reportes


def _vigente(r: PandMomento) -> bool:
    try:
        ca = r.created_at
        if ca is None:
            return True
        if ca.tzinfo is not None:
            ca = ca.replace(tzinfo=None)
        return (_dt.datetime.utcnow() - ca) < _TTL
    except Exception:
        return True


def _dict(r: PandMomento, con_imagen: bool = True) -> dict:
    d = {"id": str(r.id), "char": r.char, "nombre": r.nombre, "caption": r.caption,
         "created_at": r.created_at.isoformat() if r.created_at else None}
    if con_imagen:
        d["imagen"] = r.imagen
    return d


def publicar(db: Session, owner_key: str, payload: dict) -> dict:
    p = payload or {}
    img = str(p.get("imagen") or "").strip()
    if not img.startswith("data:image/"):
        raise unprocessable("Necesito una foto válida para tu momento.")
    if len(img) > _MAX_B64:
        raise unprocessable("La foto es muy pesada. Prueba con una más liviana.")
    r = db.query(PandMomento).filter(PandMomento.owner_key == owner_key).first()
    if r is None:
        r = PandMomento(owner_key=owner_key)
        db.add(r)
    r.imagen = img
    r.caption = (str(p.get("caption") or "").strip()[:140] or None)
    r.char = (str(p.get("char") or "").strip()[:40] or None)
    r.nombre = (str(p.get("nombre") or "").strip()[:80] or None)
    r.curso = (str(p.get("curso") or "").strip()[:40] or None)
    r.reportes = 0
    r.oculto = False
    r.created_at = _dt.datetime.utcnow()   # renueva la ventana de 24 h
    db.commit()
    return {"ok": True, "momento": _dict(r, con_imagen=False)}


def feed(db: Session, owner_key: str, curso: str = "") -> dict:
    """Devuelve tu momento + los momentos vigentes de tus compañeros del MISMO curso (grupo real)."""
    r = db.query(PandMomento).filter(PandMomento.owner_key == owner_key).first()
    mio = _dict(r, con_imagen=True) if (r is not None and not r.oculto and _vigente(r)) else None
    companeros = []
    cur = str(curso or "").strip()[:40]
    if cur:
        filas = db.query(PandMomento).filter(PandMomento.curso == cur,
                                             PandMomento.owner_key != owner_key).all()
        vis = [x for x in filas if (not x.oculto) and _vigente(x) and (x.imagen or "").startswith("data:image/")]
        vis.sort(key=lambda x: x.created_at or _dt.datetime.min, reverse=True)
        companeros = [_dict(x, con_imagen=True) for x in vis]
    return {"ok": True, "mio": mio, "companeros": companeros}


def eliminar(db: Session, owner_key: str) -> dict:
    r = db.query(PandMomento).filter(PandMomento.owner_key == owner_key).first()
    if r is not None:
        db.delete(r); db.commit()
    return {"ok": True, "mio": None}


def reportar(db: Session, mid) -> dict:
    try:
        u = _uuid.UUID(str(mid))
    except (ValueError, TypeError):
        raise not_found("Momento no válido.")
    r = db.query(PandMomento).filter(PandMomento.id == u).first()
    if r is None:
        raise not_found("Ese momento ya no existe.")
    r.reportes = int(r.reportes or 0) + 1
    if r.reportes >= _REPORT_HIDE:
        r.oculto = True
    db.commit()
    return {"ok": True, "oculto": bool(r.oculto), "reportes": r.reportes}
