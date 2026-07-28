"""Evalys Evidence Core — expedientes científicos versionados (solo lectura pública).

Son METADATOS DE PRODUCTO (constructo, procedimiento, evidencia con DOI/riesgo de sesgo, normas,
limitaciones, versión, responsable) — no contienen datos personales. Por eso son de lectura pública:
el distintivo "Respaldado por Evalys Evidence" debe poder mostrarse tanto al docente como al estudiante.

  GET /evidence/expedientes            -> índice (resumen de cada expediente)
  GET /evidence/expedientes/{clave}    -> expediente completo (acepta alias, p. ej. 'omega' → fiabilidad)
"""
from fastapi import APIRouter

from app.core.errors import not_found
from app.services import evidence_core_service as ec

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/expedientes")
def expedientes():
    return {"expedientes": ec.listar()}


@router.get("/expedientes/{clave}")
def expediente(clave: str):
    e = ec.obtener(clave)
    if not e:
        raise not_found("Expediente científico no encontrado.")
    return e
