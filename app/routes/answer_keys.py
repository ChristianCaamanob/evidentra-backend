from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.answer_key import AnswerKeyValidationOut, ValidateAnswerKeyOut
from app.services import answer_key_service

router = APIRouter(prefix="/answer-keys", tags=["answer-keys"])


@router.get("/{assessment_id}/validation", response_model=AnswerKeyValidationOut)
def get_validation(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.get_validation(db, assessment_id)


@router.post("/{assessment_id}/validate", response_model=ValidateAnswerKeyOut)
def validate_answer_key(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.validate_answer_key(db, assessment_id)

from app.schemas.answer_key import AnswerKeyItemsOut, SaveItemsIn

@router.get("/{assessment_id}/items")
def get_items(assessment_id: UUID, db: Session = Depends(get_db)):
    return answer_key_service.get_items(db, assessment_id)

@router.post("/{assessment_id}/items")
def save_items(assessment_id: UUID, payload: SaveItemsIn, db: Session = Depends(get_db)):
    return answer_key_service.save_items(
        db, assessment_id,
        payload.version, payload.n_questions,
        payload.answers, payload.annulled
    )
