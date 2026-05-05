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
