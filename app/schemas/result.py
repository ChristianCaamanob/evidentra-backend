from uuid import UUID

from pydantic import BaseModel


class ImmediateResultOut(BaseModel):
    scan_id: UUID
    raw_score: float
    percentage: float
    final_grade: float
    pass_status: str
    percentile: int
