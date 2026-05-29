from sqlalchemy.orm import Session
from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository
from app.models.course import Course

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()

# ══════════════════════════════════════════════════════
#  ESCALAS DE CALIFICACIÓN INTERNACIONALES
# ══════════════════════════════════════════════════════

GRADING_SCALES = {
    "chile_1_7": {
        "name": "Escala chilena 1.0 – 7.0",
        "country": "Chile",
        "type": "numeric",
        "min": 1.0, "max": 7.0, "passing": 4.0,
        "description": "Escala nacional chilena. Nota mínima aprobación 4.0."
    },
    "usa_letter": {
        "name": "Escala estadounidense A–F",
        "country": "Estados Unidos",
        "type": "letter",
        "description": "A+ A A- B+ B B- C+ C C- D F"
    },
    "europe_10": {
        "name": "Escala europea 0 – 10",
        "country": "Europa (general)",
        "type": "numeric",
        "min": 0.0, "max": 10.0, "passing": 5.0,
        "description": "Escala 0-10 usada en España, Alemania, Francia y otros."
    },
    "ib_7": {
        "name": "Bachillerato Internacional 1 – 7",
        "country": "Internacional IB",
        "type": "numeric",
        "min": 1.0, "max": 7.0, "passing": 4.0,
        "description": "Escala IB. Aprobación desde 4."
    },
    "uk_honours": {
        "name": "Clasificación Honours UK",
        "country": "Reino Unido",
        "type": "classification",
        "description": "First / 2:1 / 2:2 / Third / Fail"
    },
    "percentage": {
        "name": "Porcentaje 0 – 100%",
        "country": "Universal",
        "type": "numeric",
        "min": 0.0, "max": 100.0, "passing": 60.0,
        "description": "Porcentaje directo sin conversión."
    },
}


def calculate_grade(percentage: float, scale: str, passing_threshold: float = 60.0):
    """Calcula nota según escala seleccionada. Retorna (grade_value, grade_label, passed)."""
    p = passing_threshold / 100.0

    if scale == "chile_1_7":
        if percentage / 100.0 >= p:
            grade = 4.0 + 3.0 * (percentage / 100.0 - p) / (1.0 - p)
        else:
            grade = 1.0 + 3.0 * (percentage / 100.0) / p
        grade = round(min(7.0, max(1.0, grade)), 1)
        return grade, str(grade), grade >= 4.0

    elif scale == "usa_letter":
        if percentage >= 97: label = "A+"
        elif percentage >= 93: label = "A"
        elif percentage >= 90: label = "A-"
        elif percentage >= 87: label = "B+"
        elif percentage >= 83: label = "B"
        elif percentage >= 80: label = "B-"
        elif percentage >= 77: label = "C+"
        elif percentage >= 73: label = "C"
        elif percentage >= 70: label = "C-"
        elif percentage >= 67: label = "D+"
        elif percentage >= 60: label = "D"
        else: label = "F"
        passed = percentage >= passing_threshold
        return percentage, label, passed

    elif scale == "europe_10":
        grade = round(percentage / 10.0, 1)
        return grade, str(grade), grade >= (passing_threshold / 10.0)

    elif scale == "ib_7":
        if percentage >= 97: grade = 7
        elif percentage >= 88: grade = 6
        elif percentage >= 78: grade = 5
        elif percentage >= 67: grade = 4
        elif percentage >= 56: grade = 3
        elif percentage >= 44: grade = 2
        else: grade = 1
        return float(grade), str(grade), grade >= 4

    elif scale == "uk_honours":
        if percentage >= 70: label = "First Class"
        elif percentage >= 60: label = "Upper Second (2:1)"
        elif percentage >= 50: label = "Lower Second (2:2)"
        elif percentage >= 40: label = "Third Class"
        else: label = "Fail"
        passed = percentage >= passing_threshold
        return percentage, label, passed

    elif scale == "percentage":
        return percentage, f"{percentage}%", percentage >= passing_threshold

    else:  # fallback chile
        return calculate_grade(percentage, "chile_1_7", passing_threshold)


# Mantener compatibilidad con código existente
def _grade_chile(percentage: float, passing_threshold: float = 60.0) -> float:
    grade, _, _ = calculate_grade(percentage, "chile_1_7", passing_threshold)
    return grade


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
        if item.version.upper() == version.upper()
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
    total_weight = sum(item.weight for q_num, item in key_items.items() if q_num not in annulled)
    percentage = round((raw_score / total_weight * 100) if total_weight > 0 else 0, 1)

    # Obtener exigencia del curso
    from app.models.assessment import Assessment
    assessment = db.query(Assessment).filter(Assessment.id == scan.assessment_id).first()
    course = db.query(Course).filter(Course.id == assessment.course_id).first() if assessment else None
    # Prioridad: escala del assessment > escala del curso > default
    grading_scale = getattr(assessment, 'grading_scale', None) or (course.grading_scale if course else None) or 'chile_1_7'
    passing_threshold = getattr(assessment, 'passing_threshold', None) or (course.passing_threshold if course else None) or 60.0

    grade_value, grade_label, passed = calculate_grade(percentage, grading_scale, passing_threshold)
    final_grade = grade_value
    pass_status = "approved" if passed else "failed"

    # Match RUT con nómina
    student_name = None
    student_data = None
    if scan.student_identifier and scan.student_identifier != "desconocido":
        from app.models.student import Student
        student = db.query(Student).filter(
            Student.rut == scan.student_identifier,
            Student.course_id == assessment.course_id if assessment else True
        ).first()
        if student:
            student_name = f"{student.apellido_paterno} {student.apellido_materno} {student.nombres}".strip()
            student_data = {
                "rut": student.rut,
                "apellido_paterno": student.apellido_paterno,
                "apellido_materno": student.apellido_materno,
                "nombres": student.nombres,
            }

    return {
        "scan_id": str(scan.id),
        "student": student_data,
        "student_name": student_name or scan.student_identifier,
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
        "grade_label": grade_label,
        "grading_scale": grading_scale,
        "pass_status": pass_status,
        "correct_questions": correct,
        "incorrect_questions": incorrect,
        "omitted_questions": omitted,
        "annulled_questions": annulled,
    }


def list_results_for_assessment(db: Session, assessment_id):
    scans = scan_repo.list_by_assessment(db, assessment_id)
    results = []
    skipped = 0
    for scan in scans:
        try:
            results.append(get_result(db, scan.id))
        except Exception:
            skipped += 1
    return {"assessment_id": str(assessment_id), "count": len(results), "skipped": skipped, "results": results}
