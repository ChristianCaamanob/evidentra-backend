"""
F7 · Maestría compartida (Pandilla). Apoyo entre pares y metas grupales = público con pseudo_id;
otorgar maestría longitudinal = req_profesor (docente/creador).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.ratelimit import limit
from app.services import pandilla_logros_service as pls

router = APIRouter(tags=["pandilla-logros"])


# ── apoyo entre pares ─────────────────────────────────────────────────────────
@router.post("/pandilla/apoyo")
@limit("40/minute")
def apoyo_registrar(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return pls.registrar_apoyo(db, p.get("helper", ""), p.get("beneficiary", ""),
                               p.get("course_id", ""), p.get("kind", "explicacion"), p.get("nota", ""))


@router.post("/pandilla/apoyo/{support_id}/validar")
@limit("40/minute")
def apoyo_validar(request: Request, support_id: str, payload: dict, db: Session = Depends(get_db)):
    return pls.validar_apoyo(db, support_id, (payload or {}).get("validador", ""))


@router.get("/pandilla/apoyos")
def apoyos_listar(pseudo_id: str = "", db: Session = Depends(get_db)):
    return pls.apoyos_de(db, pseudo_id)


# ── metas grupales ────────────────────────────────────────────────────────────
@router.post("/pandilla/meta")
@limit("20/minute")
def meta_crear(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return pls.meta_crear(db, p.get("course_id", ""), p.get("sala_code", ""), p.get("titulo", ""),
                          p.get("meta_n", 5), p.get("creador", ""))


@router.post("/pandilla/meta/{goal_id}/aportar")
@limit("60/minute")
def meta_aportar(request: Request, goal_id: str, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return pls.meta_aportar(db, goal_id, p.get("pseudo_id", ""), p.get("n", 1))


@router.get("/pandilla/metas")
def metas_listar(course: str = "", db: Session = Depends(get_db)):
    return pls.metas_de_curso(db, course)


# ── maestría longitudinal (docente) ──────────────────────────────────────────
@router.post("/pandilla/maestria", dependencies=[Depends(req_profesor)])
@limit("30/minute")
def maestria_otorgar(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return pls.otorgar_maestria(db, p.get("course_id", ""), p.get("pseudo_id", ""),
                                p.get("docente", ""), p.get("nota", ""))
