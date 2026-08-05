"""
Consentimiento versionado + chequeo de privacidad. Voluntario, versionado, revocable.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy.orm import Session

from app.models.consent import Consent

VERSION_ACTUAL = "v1"


def _dict(c: Consent) -> dict:
    return {"version": c.version, "scope": c.scope, "granted": bool(c.granted and not c.revoked_at),
            "quiz_score": c.quiz_score, "al_dia": (c.version == VERSION_ACTUAL and c.granted and not c.revoked_at),
            "granted_at": c.granted_at.isoformat() if c.granted_at else None,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None}


def estado(db: Session, pseudo_id: str) -> dict:
    c = db.query(Consent).filter(Consent.pseudo_id == str(pseudo_id or "")).first()
    return {"ok": True, "version_actual": VERSION_ACTUAL, "consent": (_dict(c) if c else None)}


def aceptar(db: Session, pseudo_id: str, scope: str = "social,analitica", quiz_score=None) -> dict:
    pid = str(pseudo_id or "").strip()
    if not pid:
        from app.core.errors import unprocessable
        raise unprocessable("Falta pseudo_id.")
    c = db.query(Consent).filter(Consent.pseudo_id == pid).first()
    if c is None:
        c = Consent(pseudo_id=pid); db.add(c)
    c.version = VERSION_ACTUAL
    c.scope = str(scope or "social,analitica")[:120]
    c.granted = True
    c.revoked_at = None
    c.granted_at = _dt.datetime.utcnow()
    if quiz_score is not None:
        try:
            c.quiz_score = max(0, min(100, int(quiz_score)))
        except (ValueError, TypeError):
            pass
    db.commit()
    return {"ok": True, "consent": _dict(c)}


def revocar(db: Session, pseudo_id: str) -> dict:
    c = db.query(Consent).filter(Consent.pseudo_id == str(pseudo_id or "")).first()
    if c is not None:
        c.granted = False
        c.revoked_at = _dt.datetime.utcnow()
        db.commit()
    return {"ok": True, "consent": (_dict(c) if c else None)}
