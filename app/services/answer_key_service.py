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


def get_items(db, assessment_id):
    answer_key = repo.get_by_assessment_id(db, assessment_id)
    if not answer_key:
        raise not_found("Pauta no encontrada.")
    versions = repo.get_versions(db, answer_key.id)
    n_questions = max((i.question_number for i in answer_key.items), default=0)
    return {
        "items": [{"id": str(i.id), "question_number": i.question_number,
                   "version": i.version, "correct_answer": i.correct_answer,
                   "weight": i.weight, "is_annulled": i.is_annulled}
                  for i in answer_key.items],
        "versions": versions,
        "n_questions": n_questions,
    }


def save_items(db, assessment_id, version: str, n_questions: int, answers: list, annulled: list):
    from app.models.answer_key import AnswerKeyItem
    answer_key = repo.get_by_assessment_id(db, assessment_id)
    if not answer_key:
        raise not_found("Pauta no encontrada.")
    repo.delete_items_by_version(db, answer_key.id, version)
    items = []
    for i, ans in enumerate(answers[:n_questions], start=1):
        items.append(AnswerKeyItem(
            answer_key_id=answer_key.id,
            question_number=i,
            version=version.upper(),
            correct_answer=ans.upper() if ans else "A",
            weight=1.0,
            is_annulled=(i in annulled),
        ))
    repo.add_items(db, items)
    answer_key.is_valid = False
    answer_key.status = "draft"
    repo.save(db, answer_key)
    return {"saved": len(items), "version": version}


def save_items_from_scan(db, scan_result, assessment_id=None, version=None):
    from app.models.answer_key import AnswerKeyItem
    import uuid as _uuid
    qr = scan_result.qr
    assessment_id = assessment_id or (qr.assessment_id if qr else None)
    if not assessment_id:
        return {"error": "No se pudo identificar la evaluacion (sin assessment_id ni QR)"}
    version = scan_result.detected_version or version or (qr.version if qr else None) or "A"
    answers = scan_result.answers or []
    n_questions = len(answers)
    if n_questions == 0:
        return {"error": "No se detectaron respuestas"}
    answer_key = repo.get_by_assessment_id(db, assessment_id)
    if not answer_key:
        return {"error": f"No existe pauta para assessment {assessment_id}"}
    repo.delete_items_by_version(db, answer_key.id, version.upper())
    items = []
    for i, ans in enumerate(answers, start=1):
        items.append(AnswerKeyItem(
            answer_key_id=answer_key.id,
            question_number=i,
            version=version.upper(),
            correct_answer=ans.upper() if ans else "A",
            weight=1.0,
            is_annulled=False,
        ))
    repo.add_items(db, items)
    answer_key.is_valid = False
    answer_key.status = "draft"
    repo.save(db, answer_key)
    return {
        "ok": True,
        "assessment_id": str(assessment_id),
        "version": version.upper(),
        "n_questions": n_questions,
        "answers": [a or "?" for a in answers],
        "ambiguous": scan_result.ambiguous or [],
        "debug_image": scan_result.debug_image,
    }
