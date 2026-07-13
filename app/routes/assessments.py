from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.api.deps import get_db, req_profesor
from app.schemas.assessment import (
    ActivateAssessmentOut,
    AssessmentOut,
    AssessmentReadinessOut,
    AttachAssessmentDocumentIn,
)
from app.services import assessment_service
from app.services import result_service
from app.services.sheet_service import generate_answer_sheet_pdf

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment(db, assessment_id)


@router.get("/{assessment_id}/readiness", response_model=AssessmentReadinessOut)
def get_assessment_readiness(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment_readiness(db, assessment_id)


@router.post("/{assessment_id}/attach-document", response_model=AssessmentReadinessOut,
             dependencies=[Depends(req_profesor)])
def attach_document(
    assessment_id: UUID,
    payload: AttachAssessmentDocumentIn,
    db: Session = Depends(get_db),
):
    return assessment_service.attach_document(db, assessment_id, payload.assessment_document_url)


@router.post("/{assessment_id}/activate", response_model=ActivateAssessmentOut,
             dependencies=[Depends(req_profesor)])
def activate_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.activate_assessment(db, assessment_id)


@router.get("/{assessment_id}/generate-sheet")
def generate_sheet(
    assessment_id: UUID,
    version: str = Query(default="A", description="Versión de la hoja: A o B"),
    n_questions: int = Query(default=0, description="N° de preguntas. 0 = usar el configurado en la evaluación"),
    db: Session = Depends(get_db),
):
    """
    Genera y devuelve la hoja de respuesta PDF para una evaluación.
    El docente puede elegir la versión (A o B) y el número de preguntas.
    """
    assessment = assessment_service.get_assessment(db, assessment_id)
    course = assessment.course

    # Usar el n_questions del query param si viene, sino el del modelo
    nq = n_questions if n_questions > 0 else getattr(assessment, 'n_questions', 40)
    # Asegurar que sea par para las dos columnas
    if nq % 2 != 0:
        nq += 1

    pdf_bytes = generate_answer_sheet_pdf(
        assessment_id=str(assessment_id),
        course_id=str(assessment.course_id),
        course_name=course.name,
        assessment_name=assessment.name,
        n_questions=nq,
        version=version.upper(),
        date="2026",
        scale_min=1.0,
        scale_max=7.0,
        passing=4.0,
        threshold_pct=getattr(course, 'passing_threshold', 60),
    )

    filename = f"Evidentra_{assessment.name.replace(' ', '_')}_Ver{version.upper()}_{nq}P.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



from pydantic import BaseModel as _BaseModel

class AssessmentIn(_BaseModel):
    name: str
    course_id: str
    n_questions: int = 40
    versions: str = "A"
    grading_scale: str = "chile_1_7"
    passing_threshold: float = 60.0
    # Paso 0: modalidad elegida al crear (alternativas | desarrollo | mixta | oral).
    modalidad: str = "alternativas"
    # Solo desarrollo/mixta: cuántas preguntas de desarrollo sembrar (peso por puntaje).
    n_desarrollo: int = 0

@router.get("/by-course/{course_id}")
def list_assessments(course_id: UUID, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment, modalidad_norm
    from app.models.answer_key import AnswerKey
    assessments = db.query(Assessment).filter(Assessment.course_id == course_id).order_by(Assessment.created_at.desc()).all()
    result = []
    for a in assessments:
        ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == a.id).first()
        result.append({
            "id": str(a.id),
            "name": a.name,
            "status": a.status,
            "n_questions": a.version_count or 40,
            "has_answer_key": ak is not None,
            "answer_key_valid": ak.is_valid if ak else False,
            "modalidad": modalidad_norm(a.modalidad),
            "created_at": str(a.created_at)[:10] if a.created_at else None,
        })
    return result

@router.post("/", dependencies=[Depends(req_profesor)])
def create_assessment(payload: AssessmentIn, db: Session = Depends(get_db)):
    import uuid as _uuid
    from app.models.assessment import Assessment, MODALIDADES, MODALIDAD_ALTERNATIVAS, modalidad_norm
    from app.models.answer_key import (
        AnswerKey, AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE,
    )
    modalidad = modalidad_norm(payload.modalidad)
    if modalidad not in MODALIDADES:
        modalidad = MODALIDAD_ALTERNATIVAS
    es_desarrollo = modalidad in ("desarrollo", "mixta")
    # En desarrollo puro, n_questions describe las preguntas de desarrollo (no la grilla OCR).
    a = Assessment(
        course_id=_uuid.UUID(payload.course_id),
        name=payload.name,
        status="draft",
        modalidad=modalidad,
        has_versions=len(payload.versions) > 1,
        version_count=payload.n_questions,
        n_questions=payload.n_questions,
        has_answer_key=False,
        briefing_level="initial",
        grading_scale=payload.grading_scale,
        passing_threshold=payload.passing_threshold,
    )
    db.add(a)
    db.flush()
    ak = AnswerKey(
        assessment_id=a.id,
        status="draft",
        is_valid=False,
        version_coverage_ok=True,
        annulled_items_count=0,
        invalid_weight_count=0,
        invalid_partial_rule_count=0,
    )
    db.add(ak)
    db.flush()
    # Desarrollo/mixta: sembrar preguntas abiertas iniciales para que el gestor no arranque vacío
    # y para que el flujo (inferencia por question_type) reconozca la modalidad de inmediato.
    n_seed = 0
    if es_desarrollo:
        n_seed = payload.n_desarrollo if payload.n_desarrollo > 0 else (
            payload.n_questions if modalidad == "desarrollo" else 1)
        n_seed = max(1, min(n_seed, 40))
        for i in range(1, n_seed + 1):
            db.add(AnswerKeyItem(
                answer_key_id=ak.id, question_number=i, version="A",
                correct_answer="", weight=10.0, is_annulled=False,
                question_type=QUESTION_TYPE_OPEN_RESPONSE, enunciado=None,
            ))
    db.commit()
    db.refresh(a)
    return {"id": str(a.id), "name": a.name, "course_id": str(a.course_id),
            "status": a.status, "n_questions": payload.n_questions,
            "modalidad": a.modalidad, "n_desarrollo": n_seed}


@router.get("/{assessment_id}/config")
def get_assessment_config(assessment_id: UUID, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment, modalidad_norm
    from app.services.result_service import listar_escalas
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    return {
        "id": str(a.id),
        "name": a.name,
        "n_questions": a.n_questions or a.version_count or 40,
        "grading_scale": a.grading_scale or "chile_1_7",
        "passing_threshold": a.passing_threshold or 60.0,
        "status": a.status,
        "modalidad": modalidad_norm(a.modalidad),
        "course_id": str(a.course_id),
        "available_scales": listar_escalas(),
    }

@router.patch("/{assessment_id}/config", dependencies=[Depends(req_profesor)])
def update_assessment_config(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    if "grading_scale" in payload:
        a.grading_scale = payload["grading_scale"]
    if "passing_threshold" in payload:
        a.passing_threshold = float(payload["passing_threshold"])
    if "name" in payload:
        a.name = payload["name"]
    if "n_questions" in payload:
        a.n_questions = int(payload["n_questions"])
        a.version_count = int(payload["n_questions"])
    db.commit()
    db.refresh(a)
    return {"id": str(a.id), "name": a.name, "grading_scale": a.grading_scale, "passing_threshold": a.passing_threshold}


@router.get("/grading-scales/list")
def list_grading_scales():
    from app.services.result_service import listar_escalas
    return listar_escalas()


@router.get("/{assessment_id}/results")
def list_assessment_results(assessment_id: UUID, db: Session = Depends(get_db)):
    return result_service.list_results_for_assessment(db, assessment_id)
