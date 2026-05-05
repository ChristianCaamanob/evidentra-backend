from uuid import UUID

from pydantic import BaseModel


class ScanReviewOut(BaseModel):
    id: UUID
    status: str
    detected_version: str | None
    requires_review: bool
    ambiguity_count: int
    unresolved_ambiguity_count: int
    review_reasons: list[str]


class ResolveScanReviewIn(BaseModel):
    resolved_by: str | None = None
    note: str | None = None


class ResolveScanReviewOut(BaseModel):
    id: UUID
    status: str
    requires_review: bool
    unresolved_ambiguity_count: int
