"""
Chat de la Pandilla — servicio de mensajes de grupo por curso. Poda rolling (7 días).
Solo miembros verificados participan (owner_key/curso/nombre salen del token de membresía).
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.pand_chat import PandChat

_RETENCION = _dt.timedelta(days=7)
_MAX_LEN = 500
_FEED = 80


def enviar(db: Session, owner_key: str, curso: str, nombre: str, char, texto) -> dict:
    t = str(texto or "").strip()
    if not t:
        raise unprocessable("Escribe un mensaje.")
    t = t[:_MAX_LEN]
    cur = str(curso or "").strip()[:40]
    m = PandChat(curso=cur, owner_key=owner_key,
                 nombre=(str(nombre or "").strip()[:80] or None),
                 char=(str(char or "").strip()[:40] or None),
                 texto=t, created_at=_dt.datetime.utcnow())
    db.add(m)
    db.commit()
    try:   # poda rolling: mensajes del curso más antiguos que la retención
        lim = _dt.datetime.utcnow() - _RETENCION
        db.query(PandChat).filter(PandChat.curso == cur, PandChat.created_at < lim).delete()
        db.commit()
    except Exception:   # noqa: BLE001
        db.rollback()
    return {"ok": True, "id": str(m.id)}


def mensajes(db: Session, owner_key: str, curso: str) -> dict:
    cur = str(curso or "").strip()[:40]
    if not cur:
        return {"ok": True, "mensajes": []}
    filas = (db.query(PandChat).filter(PandChat.curso == cur)
             .order_by(PandChat.created_at.desc()).limit(_FEED).all())
    filas = list(reversed(filas))
    out = [{"id": str(x.id), "mio": (x.owner_key == owner_key), "nombre": x.nombre,
            "char": x.char, "texto": x.texto,
            "created_at": x.created_at.isoformat() if x.created_at else None} for x in filas]
    return {"ok": True, "mensajes": out}
