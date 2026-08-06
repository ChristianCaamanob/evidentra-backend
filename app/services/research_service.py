"""
Research OS v1 · Fase 1 — gateway de eventos + consentimiento.

Reglas duras (CODE_MASTER_PROMPT): validar contra el esquema v1; RECHAZAR propiedades desconocidas o datos
sensibles; idempotencia por `eventId`; append-only; responder SIN identidad real; no confiar en timestamps/
asignaciones/puntajes del cliente para decisiones (solo se registran como declarados). La telemetría de
investigación solo se persiste con consentimiento `consented`; revocar detiene nueva telemetría (las funciones
pedagógicas NO dependen de esto). Separada de la analítica operativa y de la evaluación académica.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.research import (ResearchAuditLog, ResearchConsent, ResearchEvent, ResearchParticipant)

SCHEMA_VERSION = "1.0.0"

_EVENT_NAMES = {
    "session_started", "session_ended", "consent_updated", "experiment_assigned", "challenge_presented",
    "challenge_started", "attempt_submitted", "confidence_recorded", "hint_requested", "feedback_opened",
    "challenge_completed", "assessment_completed", "reward_earned", "voluntary_return_detected",
    "ai_score_created", "ai_scoring_abstained", "human_review_completed", "technical_incident",
}
_TOP_KEYS = {"schemaVersion", "eventId", "eventName", "occurredAt", "sessionId", "studyId", "experimentId",
             "assignmentId", "appVersion", "contentVersion", "payload", "participantPseudoId"}
_PAYLOAD_KEYS = {"challengeId", "conceptId", "modality", "conditionId", "difficultyBand", "score01",
                 "confidence01", "correctness01", "activeSeconds", "hintsUsed", "assessmentWindow",
                 "rewardTier", "aiDecision", "technicalCode"}
_ENUMS = {
    "modality": {"adaptive_practice", "teach_runi", "living_case", "none"},
    "assessmentWindow": {"baseline", "immediate", "day_7", "day_21", "day_45"},
    "rewardTier": {"spark", "achievement", "milestone", "legendary"},
    "aiDecision": {"not_used", "scored", "abstained", "needs_human_review"},
}
_RANGES = {"difficultyBand": (1, 5), "score01": (0, 1), "confidence01": (0, 1), "correctness01": (0, 1),
           "activeSeconds": (0, 14400), "hintsUsed": (0, 100)}

FLAGS = {"researchTelemetryV1": False, "researchConsentV1": False, "adaptivePracticePilot": False,
         "teachRuniPilot": False, "livingCasePilot": False, "delayedAssessmentScheduler": False,
         "researchDashboardV1": False, "aiScoringHumanReview": False, "rewardExperimentV1": False}


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


# ── validación estricta del esquema v1 ────────────────────────────────────────
def _validar(e: dict) -> dict:
    if not isinstance(e, dict):
        raise unprocessable("Evento inválido.")
    desconocidas = set(e.keys()) - _TOP_KEYS
    if desconocidas:
        raise unprocessable("Propiedades no permitidas: " + ", ".join(sorted(desconocidas)))
    if str(e.get("schemaVersion")) != SCHEMA_VERSION:
        raise unprocessable("schemaVersion no soportada (requiere " + SCHEMA_VERSION + ").")
    for k in ("eventId", "eventName", "occurredAt", "sessionId", "studyId", "appVersion", "payload"):
        if e.get(k) in (None, ""):
            raise unprocessable("Falta campo requerido: " + k)
    if e.get("eventName") not in _EVENT_NAMES:
        raise unprocessable("eventName no catalogado: " + str(e.get("eventName")))
    payload = e.get("payload")
    if not isinstance(payload, dict):
        raise unprocessable("payload debe ser objeto.")
    p_desc = set(payload.keys()) - _PAYLOAD_KEYS
    if p_desc:
        raise unprocessable("payload con propiedades no permitidas: " + ", ".join(sorted(p_desc)))
    for k, vals in _ENUMS.items():
        if k in payload and payload[k] not in vals:
            raise unprocessable("payload." + k + " fuera del enum.")
    for k, (lo, hi) in _RANGES.items():
        if k in payload and payload[k] is not None:
            try:
                v = float(payload[k])
            except Exception:  # noqa: BLE001
                raise unprocessable("payload." + k + " no numérico.")
            if v < lo or v > hi:
                raise unprocessable("payload." + k + " fuera de rango [" + str(lo) + "," + str(hi) + "].")
    return e


# ── consentimiento ────────────────────────────────────────────────────────────
def _asegurar_participante(db: Session, pseudo: str) -> None:
    if not db.query(ResearchParticipant).filter(ResearchParticipant.participant_pseudo == pseudo).first():
        db.add(ResearchParticipant(id=_uid(), participant_pseudo=pseudo))


def consent_estado(db: Session, pseudo: str) -> dict:
    c = db.query(ResearchConsent).filter(ResearchConsent.participant_pseudo == pseudo).first()
    return {"ok": True, "state": (c.state if c else "not_asked"), "version": (c.version if c else "v1")}


def consent_set(db: Session, pseudo: str, aceptar: bool, version: str = "v1", purpose: str = "", source: str = "") -> dict:
    if not pseudo:
        return {"ok": False, "error": "falta participant"}
    _asegurar_participante(db, pseudo)
    estado = "consented" if aceptar else "declined"
    c = db.query(ResearchConsent).filter(ResearchConsent.participant_pseudo == pseudo).first()
    if c:
        c.state = estado; c.version = version; c.purpose = (purpose or c.purpose); c.source = (source or c.source)
    else:
        db.add(ResearchConsent(id=_uid(), participant_pseudo=pseudo, state=estado, version=version,
                               purpose=(purpose or None), source=(source or None)))
    db.add(ResearchAuditLog(id=_uid(), actor_pseudo_role="participant", action="consent_" + estado, detail=version))
    db.commit()
    return {"ok": True, "state": estado}


def consent_revoke(db: Session, pseudo: str) -> dict:
    c = db.query(ResearchConsent).filter(ResearchConsent.participant_pseudo == pseudo).first()
    if c:
        c.state = "revoked"
    else:
        db.add(ResearchConsent(id=_uid(), participant_pseudo=pseudo, state="revoked"))
    db.add(ResearchAuditLog(id=_uid(), actor_pseudo_role="participant", action="consent_revoked"))
    db.commit()
    return {"ok": True, "state": "revoked"}


# ── gateway de eventos ────────────────────────────────────────────────────────
def ingest(db: Session, evento: dict) -> dict:
    pseudo = str((evento or {}).get("participantPseudoId") or "").strip()
    if not pseudo:
        raise unprocessable("Falta participantPseudoId (seudónimo de investigación).")
    e = _validar(evento)
    # solo se persiste con consentimiento; revocar/declinar → se descarta (las funciones pedagógicas NO dependen de esto)
    st = consent_estado(db, pseudo)["state"]
    if st != "consented":
        return {"ok": True, "stored": False, "reason": "no_consent", "state": st}
    eid = str(e["eventId"])
    ya = db.query(ResearchEvent).filter(ResearchEvent.event_id == eid).first()
    if ya:
        return {"ok": True, "stored": False, "duplicate": True, "serverEventId": ya.server_event_id}  # idempotente
    sev = _uid()
    db.add(ResearchEvent(server_event_id=sev, event_id=eid, schema_version=SCHEMA_VERSION,
                         event_name=e["eventName"], participant_pseudo=pseudo, session_id=str(e["sessionId"]),
                         study_id=str(e["studyId"]), experiment_id=(e.get("experimentId") or None),
                         assignment_id=(e.get("assignmentId") or None), app_version=str(e["appVersion"]),
                         content_version=(e.get("contentVersion") or None), occurred_at=str(e["occurredAt"]),
                         payload=e.get("payload") or {}))
    db.commit()
    # responde SIN identidad real
    return {"ok": True, "stored": True, "serverEventId": sev, "receivedAt": _dt.datetime.utcnow().isoformat()}


_CATALOG = None


def _catalogo() -> dict:
    global _CATALOG
    if _CATALOG is None:
        import json
        import os
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "research", "experiment-catalog.json"), "r", encoding="utf-8") as fh:
                _CATALOG = json.load(fh)
        except Exception:  # noqa: BLE001
            _CATALOG = {"catalogVersion": "1.0.0", "experiments": []}
    return _CATALOG


def flags(db: Session | None = None) -> dict:
    cat = _catalogo()
    return {"ok": True, "flags": FLAGS, "schema_version": SCHEMA_VERSION,
            "catalog_version": cat.get("catalogVersion"), "experiments": cat.get("experiments", [])}
