from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.assessment import (
    ActivateAssessmentOut,
    AssessmentOut,
    AssessmentReadinessOut,
    AttachAssessmentDocumentIn,
)
from app.services import assessment_service

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment(db, assessment_id)


@router.get("/{assessment_id}/readiness", response_model=AssessmentReadinessOut)
def get_assessment_readiness(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment_readiness(db, assessment_id)


@router.post("/{assessment_id}/attach-document", response_model=AssessmentReadinessOut)
def attach_document(
    assessment_id: UUID,
    payload: AttachAssessmentDocumentIn,
    db: Session = Depends(get_db),
):
    return assessment_service.attach_document(db, assessment_id, payload.assessment_document_url)


@router.post("/{assessment_id}/activate", response_model=ActivateAssessmentOut)
def activate_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.activate_assessment(db, assessment_id)
