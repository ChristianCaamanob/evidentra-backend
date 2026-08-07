"""
Research OS v1 · Fase 1 — Research Event Gateway + consentimiento + flags/catálogo.
Todo con `participantPseudoId` (seudónimo de investigación, separado de la identidad institucional).
El gateway valida contra el esquema v1, es idempotente y append-only; responde SIN identidad real.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
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


# ── motor experimental (Fase 2) ───────────────────────────────────────────────
@router.post("/assignments")
@limit("60/minute")
def research_assign(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rs.asignar(db, p.get("experiment", ""), p.get("participant", ""), p.get("strata") or {})


@router.get("/assignments/{experiment_id}")
def research_assignment_get(experiment_id: str, participant: str = "", db: Session = Depends(get_db)):
    return rs.asignacion_de(db, experiment_id, participant)


@router.post("/deviations")
@limit("30/minute")
def research_deviation(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rs.registrar_desviacion(db, p.get("experiment", ""), p.get("participant", ""),
                                   p.get("kind", "deviation"), p.get("reason", ""))


# ── Fase 3 · modalidad teach_runi ─────────────────────────────────────────────
@router.post("/teach/evaluate")
@limit("40/minute")
def research_teach_eval(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import teach_runi_service as tr
    p = payload or {}
    part = p.get("participant", "")
    if not rs.FLAGS.get("teachRuniPilot", False):
        return {"ok": False, "reason": "flag_off", "flag": "teachRuniPilot"}
    if rs.consent_estado(db, part)["state"] != "consented":
        return {"ok": False, "reason": "no_consent"}
    return tr.evaluar(db, part, p.get("conceptId", ""), p.get("tema", ""), p.get("explicacion", ""), p.get("contexto", ""))


# ── Fase 4 · scheduler de medición longitudinal (7/21/45 días, ítems paralelos) ──
@router.post("/assessment/schedule")
@limit("60/minute")
def research_assessment_schedule(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import research_assessment_service as ra
    p = payload or {}
    part = p.get("participant", "")
    if not rs.FLAGS.get("delayedAssessmentScheduler", False):
        return {"ok": False, "reason": "flag_off", "flag": "delayedAssessmentScheduler"}
    if rs.consent_estado(db, part)["state"] != "consented":
        return {"ok": False, "reason": "no_consent"}
    return ra.programar(db, part, p.get("conceptId", ""), int(p.get("difficultyBand", 3) or 3),
                        p.get("transferDistance", "near"), p.get("immediateScore"))


@router.get("/assessment/due")
def research_assessment_due(participant: str = "", db: Session = Depends(get_db)):
    from app.services import research_assessment_service as ra
    return ra.due(db, participant)


@router.post("/assessment/{assessment_id}/respond")
@limit("60/minute")
def research_assessment_respond(request: Request, assessment_id: str, payload: dict, db: Session = Depends(get_db)):
    from app.services import research_assessment_service as ra
    p = payload or {}
    return ra.responder(db, assessment_id, p.get("score01", 0), p.get("confidence01"), p.get("activeSeconds"))


# ── Fase 3 · modalidad living_case (caso ramificado) ─────────────────────────
@router.get("/case/start")
def research_case_start(case: str = "estudio-bajo-presion", db: Session = Depends(get_db)):
    from app.services import modalidades_service as ms
    if not rs.FLAGS.get("livingCasePilot", False):
        return {"ok": False, "reason": "flag_off", "flag": "livingCasePilot"}
    return ms.caso_inicio(case)


@router.post("/case/step")
@limit("120/minute")
def research_case_step(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import modalidades_service as ms
    p = payload or {}
    return ms.caso_paso(p.get("case", "estudio-bajo-presion"), p.get("stepId", ""), p.get("optionId", ""))


@router.post("/case/score")
@limit("60/minute")
def research_case_score(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import modalidades_service as ms
    p = payload or {}
    return ms.caso_score(p.get("case", "estudio-bajo-presion"), p.get("choices") or [])


@router.get("/teach/reviews", dependencies=[Depends(req_profesor)])
def research_teach_reviews(limite: int = 50, db: Session = Depends(get_db)):
    from app.services import teach_runi_service as tr
    return tr.pendientes_revision(db, limite)


@router.post("/teach/reviews/{review_id}", dependencies=[Depends(req_profesor)])
@limit("60/minute")
def research_teach_review(request: Request, review_id: str, payload: dict, db: Session = Depends(get_db)):
    from app.services import teach_runi_service as tr
    p = payload or {}
    return tr.revisar(db, review_id, p.get("verdict", ""), p.get("score01"), p.get("quien", "docente"))
