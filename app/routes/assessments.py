from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.api.deps import get_db
from app.schemas.assessment import (
    ActivateAssessmentOut,
    AssessmentOut,
    AssessmentReadinessOut,
    AttachAssessmentDocumentIn,
)
from app.services import assessment_service
from app.services.sheet_service import generate_answer_sheet_pdf

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


@router.get("/{assessment_id}/generate-sheet")
def generate_sheet(
    assessment_id: UUID,
    version: str = Query(default="A", description="Versión de la hoja: A o B"),
    db: Session = Depends(get_db),
):
    """
    Genera y devuelve la hoja de respuesta PDF para una evaluación.
    El docente puede elegir la versión (A o B).
    Todo lo demás se toma de la evaluación y el curso en la base de datos.
    """
    assessment = assessment_service.get_assessment(db, assessment_id)
    course = assessment.course

    n_questions = getattr(assessment, 'n_questions', 40)
    # Asegurar que sea par para las dos columnas
    if n_questions % 2 != 0:
        n_questions += 1

    pdf_bytes = generate_answer_sheet_pdf(
        assessment_id=str(assessment_id),
        course_id=str(assessment.course_id),
        course_name=course.name,
        assessment_name=assessment.name,
        n_questions=n_questions,
        version=version.upper(),
        date="2026",
        scale_min=1.0,
        scale_max=7.0,
        passing=4.0,
        threshold_pct=getattr(course, 'passing_threshold', 60),
    )

    filename = f"Evidentra_{assessment.name.replace(' ', '_')}_Ver{version.upper()}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

