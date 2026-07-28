"""Evalys Evidence Core — expedientes científicos versionados.

Lectura pública (metadatos de producto, sin datos personales): el distintivo "Respaldado por Evalys
Evidence" se muestra a docentes y estudiantes. Edición reservada al "responsable de aprobación"
(rol director/creador): las ediciones se guardan en BD y se fusionan sobre el catálogo base del código.

  GET  /evidence/expedientes            -> índice (base + ediciones de BD)
  GET  /evidence/expedientes/{clave}    -> expediente completo (acepta alias, p. ej. 'omega')
  PUT  /evidence/expedientes/{clave}    -> guarda una edición (req director) · versiona y firma
  GET  /evidence/etica/escala           -> escala de consecuencias 0–5 (transparencia)
"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, requiere_rol
from app.core.errors import not_found
from app.models.teacher import Teacher, ROL_DIRECTOR
from app.services import evidence_core_service as ec

router = APIRouter(prefix="/evidence", tags=["evidence"])

# "Responsable de aprobación": dirección académica (el creador siempre pasa).
req_responsable = requiere_rol(ROL_DIRECTOR)


@router.get("/expedientes")
def expedientes(db: Session = Depends(get_db)):
    return {"expedientes": ec.listar(db)}


@router.get("/expedientes/{clave}")
def expediente(clave: str, db: Session = Depends(get_db)):
    e = ec.obtener(clave, db)
    if not e:
        raise not_found("Expediente científico no encontrado.")
    return e


@router.put("/expedientes/{clave}")
def guardar_expediente(clave: str, payload: dict, db: Session = Depends(get_db),
                       usuario: Teacher = Depends(req_responsable)):
    fecha = datetime.date.today().isoformat()
    return ec.guardar(db, clave, payload or {}, getattr(usuario, "email", None), fecha=fecha)


@router.get("/etica/escala")
def escala_consecuencias():
    """Escala de consecuencias 0–5 del motor de ética (transparencia; sin datos personales)."""
    from app.services import etica_service as etica
    return {"escala": etica.ESCALA_CONSECUENCIAS}
