"""
Research OS v1 · Fase 1 — Research Event Gateway + consentimiento + flags/catálogo.
Todo con `participantPseudoId` (seudónimo de investigación, separado de la identidad institucional).
El gateway valida contra el esquema v1, es idempotente y append-only; responde SIN identidad real.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.ratelimit import limit
from app.services import research_service as rs

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/events")
@limit("300/minute")
def research_events(request: Request, payload: dict, db: Session = Depends(get_db)):
    return rs.ingest(db, payload or {})


@router.get("/consent")
def research_consent_get(participant: str = "", db: Session = Depends(get_db)):
    return rs.consent_estado(db, participant)


@router.post("/consent")
@limit("30/minute")
def research_consent_set(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rs.consent_set(db, p.get("participant", ""), bool(p.get("consent", True)),
                          p.get("version", "v1"), p.get("purpose", ""), p.get("source", ""))


@router.post("/consent/revoke")
@limit("30/minute")
def research_consent_revoke(request: Request, payload: dict, db: Session = Depends(get_db)):
    return rs.consent_revoke(db, (payload or {}).get("participant", ""))


@router.get("/flags")
def research_flags(db: Session = Depends(get_db)):
    return rs.flags(db)
