from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMBaseSchema


class AssessmentOut(ORMBaseSchema):
    id: UUID
    course_id: UUID
    name: str
    status: str
    assessment_document_url: str | None
    has_versions: bool
    version_count: int
    has_answer_key: bool
    briefing_level: str
    modalidad: str = "alternativas"
    created_at: datetime
    updated_at: datetime


class AssessmentReadinessOut(BaseModel):
    is_ready: bool
    has_versions: bool
    has_answer_key: bool
    has_assessment_document: bool
    briefing_level: str
    missing_required_fields: list[str]


class AttachAssessmentDocumentIn(BaseModel):
    assessment_document_url: str


class ActivateAssessmentOut(BaseModel):
    id: UUID
    status: str
