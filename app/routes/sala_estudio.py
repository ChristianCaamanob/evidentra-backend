"""Sala de estudio en vivo (público, sin cuenta · identidad = nombre de trato + device).

  POST /salas                       -> crea una sala sobre un curso (por su código de sílabo)
  POST /salas/{codigo}/unirse       -> un compañero se une
  POST /salas/{codigo}/postear      -> mensaje del alumno → Runi asiste + premia
  GET  /salas/{codigo}              -> estado en vivo (hilo + presencia + puntos) · usar en poll
  POST /salas/{codigo}/cerrar       -> cierra la sala
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import sala_estudio_service as salas

router = APIRouter(prefix="/salas", tags=["salas"])


@router.post("")
def crear(payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return salas.crear_sala(db, payload.get("silabo", ""), payload.get("titulo", ""),
                            payload.get("alias"), payload.get("device_id"), payload.get("char"))


@router.post("/{codigo}/unirse")
def unirse(codigo: str, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return salas.unirse(db, codigo, payload.get("alias"), payload.get("device_id"), payload.get("char"))


@router.post("/{codigo}/postear")
def postear(codigo: str, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return salas.postear(db, codigo, payload.get("alias"), payload.get("device_id"), payload.get("texto", ""), payload.get("char"))


@router.get("/{codigo}")
def estado(codigo: str, device_id: str = "", alias: str = "", db: Session = Depends(get_db)):
    return salas.estado(db, codigo, device_id or None, alias or None)


@router.post("/{codigo}/cerrar")
def cerrar(codigo: str, payload: dict | None = None, db: Session = Depends(get_db)):
    return salas.cerrar(db, codigo, (payload or {}).get("device_id"))
