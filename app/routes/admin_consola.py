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


@router.get("/sesiones")
def admin_sesiones(db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    """Qué sesiones de grupo están abiertas AHORA en toda la plataforma (los 4 tipos)."""
    return acs.sesiones(db, getattr(admin, "email", "") or "")


@router.get("/reuniones")
def admin_reuniones(db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.reuniones(db, getattr(admin, "email", "") or "")


@router.get("/dialogos")
def admin_dialogos(limite: int = 60, db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.dialogos(db, getattr(admin, "email", "") or "", limite=limite)


@router.get("/accesos")
def admin_accesos(limite: int = 200, db: Session = Depends(get_db), admin: Teacher = Depends(req_creador)):
    return acs.accesos(db, getattr(admin, "email", "") or "", limite=limite)
