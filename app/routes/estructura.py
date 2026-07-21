"""
Router de la ESTRUCTURA INSTITUCIONAL (config 'Lego'): Facultades / Departamentos / Profesores
como bloques que se ensamblan sobre los cursos reales.

Lectura: cualquier staff con acceso a datos (profesor/investigador/director/creador) — así el
constructor funciona también en modo demostración desde una cuenta docente.
Escritura: director + creador (metadata organizativa; no altera notas — G1).
"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, requiere_rol, req_lectura_datos
from app.models.teacher import ROL_DIRECTOR
from app.services import estructura_service

router = APIRouter(prefix="/estructura", tags=["estructura"])

req_editar = requiere_rol(ROL_DIRECTOR)   # director + creador (creador pasa siempre)


@router.get("", dependencies=[Depends(req_lectura_datos)])
def obtener(db: Session = Depends(get_db)):
    """Config actual + los cursos reales disponibles para ensamblar."""
    return estructura_service.estado(db)


@router.put("", dependencies=[Depends(req_editar)])
def guardar(body: dict = Body(...), db: Session = Depends(get_db)):
    """Guarda la config y sincroniza los nombres de facultad/departamento sobre los cursos."""
    payload = body.get("payload") if isinstance(body, dict) and "payload" in body else body
    return estructura_service.guardar(db, payload or {})
