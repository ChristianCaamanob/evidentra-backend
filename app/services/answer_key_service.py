from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository

repo = AnswerKeyRepository()


def _build_validation(answer_key) -> dict:
    items = answer_key.items
    invalid_weight_count = sum(1 for item in items if item.weight <= 0)
    invalid_partial_rule_count = sum(
        1 for item in items if item.partial_credit_rule_json == {"invalid": True}
    )
    version_coverage_ok = answer_key.version_coverage_ok
    validation_issues: list[str] = []

    if invalid_weight_count > 0:
        validation_issues.append("las ponderaciones de la pauta")
    if invalid_partial_rule_count > 0:
        validation_issues.append("la regla de puntaje parcial de la pauta")
    if not version_coverage_ok:
        validation_issues.append("la cobertura por versión")

    return {
        "is_valid": len(validation_issues) == 0,
        "annulled_items_count": sum(1 for item in items if item.is_annulled),
        "invalid_weight_count": invalid_weight_count,
        "invalid_partial_rule_count": invalid_partial_rule_count,
        "version_coverage_ok": version_coverage_ok,
        "validation_issues": validation_issues,
    }


def get_validation(db: Session, assessment_id):
    answer_key = repo.get_by_assessment_id(db, assessment_id)
    if not answer_key:
        raise not_found("Pauta no encontrada para la evaluación.")
    return _build_validation(answer_key)


def validate_answer_key(db: Session, assessment_id):
    answer_key = repo.get_by_assessment_id(db, assessment_id)
    if not answer_key:
        raise not_found("Pauta no encontrada para la evaluación.")

    validation = _build_validation(answer_key)
    if not validation["is_valid"]:
        raise conflict("La pauta no puede validarse porque presenta inconsistencias estructurales.")

    answer_key.is_valid = True
    answer_key.status = "validated"
    answer_key.invalid_partial_rule_count = 0
    repo.save(db, answer_key)
    return {"is_valid": answer_key.is_valid, "status": answer_key.status}
