def build_course_readiness(course) -> dict:
    missing: list[str] = []
    if not course.program_document_url:
        missing.append("el programa del curso")
    if not course.has_learning_structure:
        missing.append("la estructura académica del curso")
    if not course.grading_scale:
        missing.append("la escala de calificación")
    if course.passing_threshold is None:
        missing.append("el porcentaje de exigencia")
    if not course.base_score_type:
        missing.append("el tipo de puntaje base")

    return {
        "is_ready": len(missing) == 0,
        "has_program_document": bool(course.program_document_url),
        "has_learning_structure": bool(course.has_learning_structure),
        "missing_required_fields": missing,
    }


def build_assessment_readiness(assessment) -> dict:
    missing: list[str] = []
    if not assessment.has_versions:
        missing.append("las versiones de la evaluación")
    if not assessment.has_answer_key:
        missing.append("la pauta")
    if not assessment.assessment_document_url:
        missing.append("la prueba o instrumento de evaluación")

    return {
        "is_ready": len(missing) == 0,
        "has_versions": bool(assessment.has_versions),
        "has_answer_key": bool(assessment.has_answer_key),
        "has_assessment_document": bool(assessment.assessment_document_url),
        "briefing_level": assessment.briefing_level,
        "missing_required_fields": missing,
    }
