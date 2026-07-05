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
