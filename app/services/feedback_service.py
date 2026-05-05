from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.repositories.assessment_repo import AssessmentRepository

assessment_repo = AssessmentRepository()


def get_feedback_artifact(db: Session, assessment_id, artifact: str):
    assessment = assessment_repo.get(db, assessment_id)
    if not assessment:
        raise not_found("Evaluación no encontrada.")

    payloads = {
        "academic": {
            "title": "Briefing académico",
            "items": [
                "Brecha dominante del curso: RA2.",
                "Preguntas 7, 14 y 18 concentran el mayor conflicto.",
                "Se recomienda reforzar la unidad 3.",
            ],
        },
        "student": {
            "title": "Briefing estudiantil",
            "items": [
                "Tu principal brecha se relaciona con RA2.",
                "Revisa nuevamente la unidad 3.",
                "Prioriza los tópicos con confusión recurrente.",
            ],
        },
        "quality": {
            "title": "Informe de calidad",
            "items": [
                "RA2 presenta la mayor fricción transversal.",
                "Se sugiere reforzamiento previo al examen final.",
                "La cohorte 2026 supera a 2025 en RA1, no en RA2.",
            ],
        },
        "research": {
            "title": "Capa Research",
            "items": [
                "Comparar cohorte 2025 vs 2026 por RA.",
                "Estimar tamaño de efecto en unidad 3.",
                "Preparar discusión preliminar y conclusiones tentativas.",
            ],
        },
    }
    return {"artifact_type": artifact, **payloads[artifact]}
