"""La Guarida de Runi · rutas públicas de pausa (estudiante sin login, identidad seudonimizada).

El tiempo de término lo calcula/valida el SERVIDOR. Aditivo, sin auth de staff, rate-limited, como
el resto de la superficie del estudiante (analytics/episodes). Nunca recibe RUT/nombre.
"""
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from fastapi import Depends

from app.api.deps import get_db, req_lectura_datos
from app.core.ratelimit import limit
from app.services import runi_break_service as rb

router = APIRouter(prefix="/runi/guarida", tags=["runi-guarida"])


@router.post("/break/start")
@limit("60/minute")
def break_start(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rb.start(db, p.get("pseudo_id", ""), p.get("zone", "calm"), int(p.get("planned_minutes", 5) or 5),
                    course_id=p.get("course_id"), source_session_id=p.get("source_session_id"))


@router.post("/break/{break_id}/state")
@limit("120/minute")
def break_state(request: Request, break_id: str, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rb.state(db, break_id, p.get("action", ""), int(p.get("added_minutes", 5) or 5), source=p.get("source"))


@router.get("/break/active")
def break_active(pseudo_id: str = "", db: Session = Depends(get_db)):
    return rb.active(db, pseudo_id)


@router.get("/panel", dependencies=[Depends(req_lectura_datos)])
def guarida_panel(course_id: str | None = None, days: int = 30, db: Session = Depends(get_db)):
    """Panel de recuperación y retorno (staff, seudonimizado, agregado). Cierra el círculo del North Star."""
    return rb.panel(db, course_id=course_id, days=days)
