from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.schemas.answer_key import AnswerKeyValidationOut, ValidateAnswerKeyOut
from app.services import answer_key_service

router = APIRouter(prefix="/answer-keys", tags=["answer-keys"])


@router.get("/{assessment_id}/validation", response_model=AnswerKeyValidationOut)
def get_validation(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.get_validation(db, assessment_id)


@router.post("/{assessment_id}/validate", response_model=ValidateAnswerKeyOut,
             dependencies=[Depends(req_profesor)])
def validate_answer_key(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.validate_answer_key(db, assessment_id)

from app.schemas.answer_key import AnswerKeyItemsOut, SaveItemsIn

@router.get("/{assessment_id}/items")
def get_items(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.get_items(db, assessment_id)

@router.post("/{assessment_id}/items", dependencies=[Depends(req_profesor)])
def save_items(assessment_id: UUID, payload: SaveItemsIn, db: Session = Depends(get_db)):
    return answer_key_service.save_items(
        db, assessment_id,
        payload.version, payload.n_questions,
        payload.answers, payload.annulled
    )

from fastapi import UploadFile, File, Form
from typing import Optional
from app.services.scan_engine import scan_sheet
from app.services.answer_key_service import save_items_from_scan

@router.post("/scan-answer-key", dependencies=[Depends(req_profesor)])
async def scan_answer_key(
    file: UploadFile = File(...),
    assessment_id: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    image_bytes = await file.read()
    hint_n = 0
    if assessment_id:
        from app.models.assessment import Assessment
        _a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
        if _a:
            hint_n = getattr(_a, "n_questions", 0) or getattr(_a, "version_count", 0) or 0
    scan_result = scan_sheet(image_bytes, n_questions_hint=hint_n)
    if not scan_result.success:
        raise HTTPException(status_code=400, detail=scan_result.error or "Error al escanear")
    result = save_items_from_scan(db, scan_result, assessment_id=assessment_id, version=version)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
