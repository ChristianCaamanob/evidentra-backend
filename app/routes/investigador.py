"""
Router del modulo Investigador (Fase 1 del cableado): expone la psicometria agregada de
una evaluacion. Solo lectura, seudonimizado (G2), no altera notas (G1).

Fase 1 (datos de seleccion multiple, disponibles hoy):
  - GET /assessments/{id}/psicometria/rasch          -> I1 (irt_service)
  - GET /assessments/{id}/psicometria/dimensionalidad -> I7 (dimensionalidad_service)

Los endpoints sobre rubrica (PCM, R, MFRM) y los con grupo (DIF, invarianza) llegan en las
fases 2 y 3, junto con los datos y decisiones que consumen.
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import matriz_service
from app.services import irt_service
from app.services import dimensionalidad_service

router = APIRouter(prefix="/assessments", tags=["investigador"])
logger = logging.getLogger("evalys")


def _meta(datos: dict) -> dict:
    return {"n_personas": datos["n_personas"], "n_items": datos["n_items"],
            "omitidas_pct": datos["omitidas_pct"],
            "gobernanza": "Analisis agregado y seudonimizado (G2); no altera notas (G1)."}


@router.get("/{assessment_id}/psicometria/rasch")
def psicometria_rasch(assessment_id: UUID, db: Session = Depends(get_db)):
    """I1 - Modelo de Rasch (dificultad, habilidad, ajuste, informacion, fiabilidad)."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = irt_service.estimar_rasch(datos["X"])
        for it, num in zip(rep["items"], datos["items"]):
            it["pregunta"] = num                       # numero real de pregunta (no indice)
        rep["_meta"] = _meta(datos)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_rasch {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dimensionalidad")
def psicometria_dimensionalidad(assessment_id: UUID, db: Session = Depends(get_db)):
    """I7 - Dimensionalidad (KMO, Bartlett, analisis paralelo, EFA) + fiabilidad ampliada."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = dimensionalidad_service.analizar_dimensionalidad(datos["X"], dicotomico=True)
        rep["_meta"] = _meta(datos)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dimensionalidad {assessment_id}: {traceback.format_exc()}")
        raise
