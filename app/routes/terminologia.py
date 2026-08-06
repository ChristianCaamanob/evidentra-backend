"""
F5 · Rutas de gobernanza terminológica. Escritura (importar/vincular/seed) = req_profesor (docente/creador);
lectura (resolver/perfil) pública para que el cliente resuelva conceptId→término vigente.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.ratelimit import limit
from app.services import terminologia_service as ts

router = APIRouter(tags=["terminologia"])


# ── lectura pública ──────────────────────────────────────────────────────────
@router.get("/terminologia/perfiles")
def term_perfiles(db: Session = Depends(get_db)):
    return ts.listar_perfiles(db)


@router.get("/terminologia/perfil/{profile_id}")
def term_perfil(profile_id: str, db: Session = Depends(get_db)):
    return ts.perfil(db, profile_id)


@router.get("/terminologia/resolver")
def term_resolver(profile: str = "", concept: str = "", fallback: str = "", db: Session = Depends(get_db)):
    return ts.resolver(db, profile, concept, fallback)


@router.get("/terminologia/curso/{course}/resolver")
def term_resolver_curso(course: str, concept: str = "", fallback: str = "", db: Session = Depends(get_db)):
    return ts.resolver_por_curso(db, course, concept, fallback)


@router.get("/terminologia/buscar")
def term_buscar(profile: str = "", texto: str = "", db: Session = Depends(get_db)):
    return ts.buscar(db, profile, texto)


# ── escritura (gobernanza) ───────────────────────────────────────────────────
@router.post("/terminologia/importar", dependencies=[Depends(req_profesor)])
@limit("20/minute")
def term_importar(request: Request, payload: dict, db: Session = Depends(get_db)):
    return ts.importar(db, payload or {})


@router.post("/terminologia/vincular", dependencies=[Depends(req_profesor)])
@limit("30/minute")
def term_vincular(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return ts.vincular_curso(db, p.get("course_code", ""), p.get("profile_id", ""))


@router.post("/terminologia/seed", dependencies=[Depends(req_profesor)])
@limit("10/minute")
def term_seed(request: Request, db: Session = Depends(get_db)):
    return ts.sembrar(db)
