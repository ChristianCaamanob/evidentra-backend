from sqlalchemy.orm import Session
from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository
from app.models.course import Course

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()


def _grade_chile(percentage: float, passing_threshold: float = 60.0) -> float:
    """Escala chilena 1-7. Exigencia configurable (default 60%)."""
    p = passing_threshold / 100.0
    if percentage >= passing_threshold:
        grade = 4.0 + 3.0 * (percentage / 100.0 - p) / (1.0 - p)
    else:
        grade = 1.0 + 3.0 * (percentage / 100.0) / p
    return round(min(7.0, max(1.0, grade)), 1)


def get_result(db: Session, scan_id):
    scan = scan_repo.get(db, scan_id)
    if not scan:
        raise not_found("Escaneo no encontrado.")
    if scan.requires_review:
        raise conflict("El escaneo aún requiere revisión.")

    answer_key = answer_key_repo.get_by_assessment_id(db, scan.assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no está validada.")

    # Obtener respuestas del alumno desde el OCR payload
    ocr = scan.raw_ocr_payload_json or {}
    student_answers = ocr.get("answers", [])
    version = scan.detected_version or "A"

    # Obtener pauta de la versión detectada
    key_items = {
        item.question_number: item
        for item in answer_key.items
        if item.version.upper() == version.upper() and not item.is_annulled
    }

    if not key_items:
        raise conflict(f"No hay pauta validada para versión {version}.")

    n_total = len(key_items)
    correct = []
    incorrect = []
    annulled = []
    omitted = []

    for q_num, item in sorted(key_items.items()):
        idx = q_num - 1
        student_ans = student_answers[idx] if idx < len(student_answers) else None
        if item.is_annulled:
            annulled.append(q_num)
            continue
        if student_ans is None:
            omitted.append(q_num)
        elif student_ans.upper() == item.correct_answer.upper():
            correct.append(q_num)
        else:
            incorrect.append({"question": q_num, "student": student_ans, "correct": item.correct_answer})

    n_correct = len(correct)
    n_incorrect = len(incorrect)
    n_omitted = len(omitted)
    n_annulled = len(annulled)
    n_effective = n_total - n_annulled

    raw_score = sum(
        item.weight for q_num, item in key_items.items()
        if q_num in correct
    )
    total_weight = sum(item.weight for item in key_items.values())
    percentage = round((raw_score / total_weight * 100) if total_weight > 0 else 0, 1)

    # Obtener exigencia del curso
    from app.models.assessment import Assessment
    assessment = db.query(Assessment).filter(Assessment.id == scan.assessment_id).first()
    course = db.query(Course).filter(Course.id == assessment.course_id).first() if assessment else None
    passing_threshold = course.passing_threshold if course and course.passing_threshold else 60.0

    final_grade = _grade_chile(percentage, passing_threshold)
    pass_status = "approved" if final_grade >= 4.0 else "failed"

    return {
        "scan_id": str(scan.id),
        "student_identifier": scan.student_identifier,
        "version": version,
        "n_total": n_total,
        "n_effective": n_effective,
        "n_correct": n_correct,
        "n_incorrect": n_incorrect,
        "n_omitted": n_omitted,
        "n_annulled": n_annulled,
        "raw_score": round(raw_score, 2),
        "percentage": percentage,
        "passing_threshold": passing_threshold,
        "final_grade": final_grade,
        "pass_status": pass_status,
        "correct_questions": correct,
        "incorrect_questions": incorrect,
        "omitted_questions": omitted,
    }
