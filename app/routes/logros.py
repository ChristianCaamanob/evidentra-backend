"""
B9/B10 · Logros de Runi. El alumno consulta su propio estado por `pseudo_id` (seudonimizado, sin login).
El desbloqueo SIEMPRE lo decide el servidor (XP + puerta de evidencia); el cliente solo representa.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import logros_service as ls

router = APIRouter(tags=["logros"])


@router.get("/logros/estado")
def logros_estado(pseudo_id: str = "", db: Session = Depends(get_db)):
    return ls.estado(db, pseudo_id)
