from pydantic import BaseModel


class AnswerKeyValidationOut(BaseModel):
    is_valid: bool
    annulled_items_count: int
    invalid_weight_count: int
    invalid_partial_rule_count: int
    version_coverage_ok: bool
    validation_issues: list[str]


class ValidateAnswerKeyOut(BaseModel):
    is_valid: bool
    status: str

from typing import List
class AnswerKeyItemOut(BaseModel):
    id: str
    question_number: int
    version: str
    correct_answer: str
    weight: float
    is_annulled: bool
    class Config:
        from_attributes = True
class AnswerKeyItemsOut(BaseModel):
    items: List[AnswerKeyItemOut]
    versions: List[str]
    n_questions: int
class SaveItemsIn(BaseModel):
    version: str
    n_questions: int
    answers: List[str]
    annulled: List[int] = []
