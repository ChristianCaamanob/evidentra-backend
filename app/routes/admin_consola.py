"""
Consola del Administrador (CEO) — rutas de supervisión, SOLO el rol 'creador' (req_creador).
Solo lectura ("fantasma"): no altera la interacción de nadie. Cada lectura de contenido se registra.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_creador
from app.models.teacher import Teacher
from app.services import admin_consola_service as acs

router = APIRouter(prefix="/admin/consola", tags=["admin-consola"])


@router.get("/resumen")
def admin_resumen(db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.resumen(db, getattr(admin, "email", "") or "")


@router.get("/social")
def admin_social(con_imagen: bool = False, db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.social(db, getattr(admin, "email", "") or "", con_imagen=con_imagen)


@router.get("/accesos")
def admin_accesos(limite: int = 200, db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.accesos(db, getattr(admin, "email", "") or "", limite=limite)
