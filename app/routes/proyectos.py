"""Proyectos de investigación (CRUD) — cada investigador es dueño de los suyos.

Contenedor persistente que habilita: varios proyectos independientes, selección de
cursos/grupos (tipo 'datos'), y corpus+cribado persistidos (tipo 'revision'). El creador
(rol) puede ver todo; un investigador solo ve/edita los propios.
"""
from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_investigador
from app.core.errors import not_found, forbidden
from app.models.proyecto import Proyecto, TIPOS, ESTADOS
from app.models.teacher import Teacher, ROL_CREADOR

logger = logging.getLogger("evidentra.proyectos")
router = APIRouter(prefix="/investigacion/proyectos", tags=["investigador"])


# ───────────────────────────── esquemas
class ProyectoCrear(BaseModel):
    tipo: Literal["datos", "revision", "experimental"]
    titulo: str = Field(min_length=2, max_length=300)
    pregunta: str | None = Field(default=None, max_length=1000)
    datos: dict[str, Any] = Field(default_factory=dict)


class ProyectoActualizar(BaseModel):
    titulo: str | None = Field(default=None, min_length=2, max_length=300)
    pregunta: str | None = Field(default=None, max_length=1000)
    estado: Literal["borrador", "activo", "archivado"] | None = None
    datos: dict[str, Any] | None = None          # se FUSIONA con lo existente (merge superficial)


def _dto(p: Proyecto) -> dict:
    return {"id": str(p.id), "tipo": p.tipo, "titulo": p.titulo, "pregunta": p.pregunta,
            "estado": p.estado, "datos": p.datos or {},
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def _mio(db: Session, pid: UUID, usuario: Teacher) -> Proyecto:
    p = db.get(Proyecto, pid)
    if not p:
        raise not_found("Proyecto no encontrado.")
    if str(p.investigador_id) != str(usuario.id) and usuario.rol != ROL_CREADOR:
        raise forbidden("Este proyecto pertenece a otro investigador.")
    return p


# ───────────────────────────── endpoints
@router.get("")
def listar(db: Session = Depends(get_db), usuario: Teacher = Depends(req_investigador)):
    """Lista los proyectos del investigador (el creador ve todos), más recientes primero."""
    q = db.query(Proyecto)
    if usuario.rol != ROL_CREADOR:
        q = q.filter(Proyecto.investigador_id == usuario.id)
    proyectos = q.order_by(Proyecto.updated_at.desc()).all()
    return {"n": len(proyectos), "proyectos": [_dto(p) for p in proyectos]}


@router.post("", status_code=201)
def crear(body: ProyectoCrear, db: Session = Depends(get_db),
          usuario: Teacher = Depends(req_investigador)):
    """Crea un proyecto (datos | revision | experimental) propiedad del investigador."""
    p = Proyecto(investigador_id=usuario.id, tipo=body.tipo, titulo=body.titulo.strip(),
                 pregunta=(body.pregunta or None), estado="borrador", datos=body.datos or {})
    db.add(p)
    db.commit()
    db.refresh(p)
    return _dto(p)


@router.get("/{pid}")
def obtener(pid: UUID, db: Session = Depends(get_db),
            usuario: Teacher = Depends(req_investigador)):
    return _dto(_mio(db, pid, usuario))


@router.patch("/{pid}")
def actualizar(pid: UUID, body: ProyectoActualizar, db: Session = Depends(get_db),
               usuario: Teacher = Depends(req_investigador)):
    """Actualiza campos; `datos` se fusiona (merge superficial) para no pisar el resto del estado."""
    p = _mio(db, pid, usuario)
    if body.titulo is not None:
        p.titulo = body.titulo.strip()
    if body.pregunta is not None:
        p.pregunta = body.pregunta or None
    if body.estado is not None:
        p.estado = body.estado
    if body.datos is not None:
        merged = dict(p.datos or {})
        merged.update(body.datos)
        p.datos = merged
    db.commit()
    db.refresh(p)
    return _dto(p)


@router.delete("/{pid}", status_code=204)
def borrar(pid: UUID, db: Session = Depends(get_db),
           usuario: Teacher = Depends(req_investigador)):
    p = _mio(db, pid, usuario)
    db.delete(p)
    db.commit()
    return None
