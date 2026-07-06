"""
Banco de preguntas: generacion de items de alternativas alineados a C3 (RA -> Bloom).

  POST /assessments/{id}/preguntas/generar
      payload = {ra_id? | ra_texto?, ra_code?, bloom, n, dificultad,
                 n_alternativas?, norma?, contexto?}

Si se pasa ra_id, el texto del RA se resuelve desde el curriculo del curso (texto literal,
G6). Lo generado son BORRADORES (la IA propone; el docente aprueba, G1) y viene trazado a su
RA y nivel de Bloom (C3). No se persiste ni entra a la pauta automaticamente.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.errors import not_found, unprocessable
from app.models.assessment import Assessment
from app.models.curriculo import LearningOutcome
from app.services import generador_preguntas_service as gen

router = APIRouter(tags=["banco"])


@router.post("/assessments/{assessment_id}/preguntas/generar",
             dependencies=[Depends(req_profesor)])
def generar_preguntas(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise not_found("Evaluacion no encontrada.")

    ra_texto = (payload.get("ra_texto") or "").strip()
    ra_code = payload.get("ra_code")
    ra_id = payload.get("ra_id")
    if ra_id:
        try:
            ra = db.query(LearningOutcome).filter(
                LearningOutcome.id == UUID(str(ra_id)),
                LearningOutcome.course_id == assessment.course_id).first()
        except ValueError:
            ra = None
        if not ra:
            raise not_found("Resultado de aprendizaje no encontrado en este curso.")
        ra_texto, ra_code = ra.text, ra.code
    if not ra_texto:
        raise unprocessable("Indica un ra_id del curso o el ra_texto a cubrir.")

    return gen.generar_preguntas(
        ra_texto=ra_texto,
        bloom=payload.get("bloom", "aplicar"),
        n=payload.get("n", 5),
        dificultad=payload.get("dificultad", "media"),
        ra_code=ra_code,
        n_alternativas=payload.get("n_alternativas", 4),
        norma=payload.get("norma"),
        contexto=payload.get("contexto"),
    )
