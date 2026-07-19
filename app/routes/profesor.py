"""
Router del modulo Profesor: la vista unificada de correccion. Alternativas y desarrollo NO
son modulos separados -conviven en la misma evaluacion- y se resumen en un libro de notas
unico.

  GET /assessments/{id}/libro-notas   -> nota final combinada por estudiante (P)
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.services import libro_notas_service

router = APIRouter(tags=["profesor"])
logger = logging.getLogger("evalys")


@router.get("/assessments/{assessment_id}/libro-notas", dependencies=[Depends(req_profesor)])
def libro_notas(assessment_id: UUID, db: Session = Depends(get_db)):
    """Libro de notas unificado: alternativas (auto) + desarrollo (validado), ponderado por item."""
    try:
        return libro_notas_service.libro_notas(db, assessment_id)
    except Exception:
        logger.error(f"Error en libro_notas {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/analisis", dependencies=[Depends(req_profesor)])
def analisis(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """Centro de Análisis · agregado de la evaluación: KPIs, logro por RA, distribución de notas
    y trazabilidad de la evidencia (origen/escaneos). origen=omr|en_vivo|(omitir=ambos)."""
    if origen not in (None, "", "omr", "en_vivo"):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service
    try:
        return ficha_service.analisis_evaluacion(db, assessment_id, origen=(origen or None))
    except Exception:
        logger.error(f"Error en analisis {assessment_id}: {traceback.format_exc()}")
        raise
