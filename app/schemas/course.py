from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMBaseSchema


class CourseOut(ORMBaseSchema):
    id: UUID
    name: str
    code: str
    status: str
    program_document_url: str | None
    has_learning_structure: bool
    grading_scale: str | None
    passing_threshold: float | None
    base_score_type: str | None
    created_at: datetime
    updated_at: datetime


class CourseReadinessOut(BaseModel):
    is_ready: bool
    has_program_document: bool
    has_learning_structure: bool
    missing_required_fields: list[str]


class CompleteCourseStructureIn(BaseModel):
    has_learning_structure: bool = True


class ActivateCourseOut(BaseModel):
    id: UUID
    status: str
