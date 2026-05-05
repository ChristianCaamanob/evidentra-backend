from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.feedback import FeedbackArtifactOut
from app.services import feedback_service

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.get("/{assessment_id}", response_model=FeedbackArtifactOut)
def get_feedback_artifact(
    assessment_id: UUID,
    artifact: str = Query(..., pattern="^(academic|student|quality|research)$"),
    db: Session = Depends(get_db),
):
    return feedback_service.get_feedback_artifact(db, assessment_id, artifact)
