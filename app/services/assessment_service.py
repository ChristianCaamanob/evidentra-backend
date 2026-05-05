from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories.assessment_repo import AssessmentRepository
from app.services.readiness_service import build_assessment_readiness

repo = AssessmentRepository()


def get_assessment(db: Session, assessment_id):
    assessment = repo.get(db, assessment_id)
    if not assessment:
        raise not_found("Evaluación no encontrada.")
    return assessment


def get_assessment_readiness(db: Session, assessment_id):
    assessment = get_assessment(db, assessment_id)
    return build_assessment_readiness(assessment)


def attach_document(db: Session, assessment_id, assessment_document_url: str):
    assessment = get_assessment(db, assessment_id)
    assessment.assessment_document_url = assessment_document_url
    assessment.briefing_level = "advanced"
    repo.save(db, assessment)
    return build_assessment_readiness(assessment)


def activate_assessment(db: Session, assessment_id):
    assessment = get_assessment(db, assessment_id)
    readiness = build_assessment_readiness(assessment)
    if not readiness["is_ready"]:
        raise conflict("La evaluación no puede activarse porque aún faltan elementos obligatorios.")
    assessment.status = "ready"
    repo.save(db, assessment)
    return {"id": assessment.id, "status": assessment.status}
