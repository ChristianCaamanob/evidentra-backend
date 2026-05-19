from uuid import UUID
from typing import Any, List, Optional
from pydantic import BaseModel


class ImmediateResultOut(BaseModel):
    scan_id: UUID
    raw_score: float
    percentage: float
    final_grade: float
    grade_label: Optional[str] = None
    pass_status: str
    percentile: Optional[int] = None
    grading_scale: Optional[str] = None
    passing_threshold: Optional[float] = None
    version: Optional[str] = None
    n_total: Optional[int] = None
    n_effective: Optional[int] = None
    n_correct: Optional[int] = None
    n_incorrect: Optional[int] = None
    n_omitted: Optional[int] = None
    n_annulled: Optional[int] = None
    student_identifier: Optional[str] = None
    student_name: Optional[str] = None
    student: Optional[Any] = None
    correct_questions: Optional[List[int]] = None
    incorrect_questions: Optional[List[Any]] = None
    omitted_questions: Optional[List[int]] = None
