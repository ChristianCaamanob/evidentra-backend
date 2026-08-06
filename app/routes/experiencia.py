"""
v4 · Rutas del motor de experiencia. Catálogos + resolución = públicos (el resolver es determinista y no
confía en el cliente para permisos). Vincular facultad a un curso = req_profesor. El estudiante guarda su
modo de vínculo por pseudo_id (su elección).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.ratelimit import limit
from app.services import experiencia_service as xs

router = APIRouter(tags=["experiencia-v4"])


@router.get("/experiencia/catalogos")
def exp_catalogos(db: Session = Depends(get_db)):
    return xs.catalogos(db)


@router.post("/experiencia/resolver")
@limit("120/minute")
def exp_resolver(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return xs.resolver(db, p.get("student") or {}, p.get("relation") or {}, p.get("ctx") or {})


@router.get("/experiencia/relacion")
def exp_relacion_get(pseudo_id: str = "", db: Session = Depends(get_db)):
    return xs.relacion_get(db, pseudo_id)


@router.post("/experiencia/relacion")
@limit("40/minute")
def exp_relacion_set(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return xs.relacion_set(db, p.get("pseudo_id", ""), p.get("primary_mode", "companion"), p.get("proactivity", "medium"))


@router.post("/experiencia/vincular-facultad", dependencies=[Depends(req_profesor)])
@limit("30/minute")
def exp_vincular_facultad(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return xs.vincular_facultad(db, p.get("course_code", ""), p.get("faculty_pack_id", "general"))
