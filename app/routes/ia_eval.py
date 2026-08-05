"""
B11 — Evaluación continua de la IA (Runi). Rutas de gobernanza (solo CEO/owner: req_creador).
Banco experto + corridas por release + regresión. Nada de esto es visible al estudiante.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_creador
from app.core.ratelimit import limit
from app.services import ia_eval_service as iae

router = APIRouter(tags=["ia-eval"], dependencies=[Depends(req_creador)])


@router.get("/ia-eval/casos")
def ia_casos(db: Session = Depends(get_db)):
    return iae.listar_casos(db)


@router.post("/ia-eval/casos")
@limit("30/minute")
def ia_add_caso(request: Request, payload: dict, db: Session = Depends(get_db)):
    return iae.agregar_caso(db, payload or {})


@router.post("/ia-eval/seed")
@limit("10/minute")
def ia_seed(request: Request, db: Session = Depends(get_db)):
    return iae.sembrar(db)


@router.post("/ia-eval/run")
@limit("6/minute")
def ia_run(request: Request, payload: dict | None = None, db: Session = Depends(get_db)):
    return iae.run(db, (payload or {}).get("release", ""))


@router.get("/ia-eval/ultimo")
def ia_ultimo(db: Session = Depends(get_db)):
    return iae.ultimo(db)


@router.get("/ia-eval/historial")
def ia_historial(limite: int = 20, db: Session = Depends(get_db)):
    return iae.historial(db, limite)


@router.get("/ia-eval/run/{run_id}")
def ia_detalle(run_id: str, db: Session = Depends(get_db)):
    return iae.detalle(db, run_id)
