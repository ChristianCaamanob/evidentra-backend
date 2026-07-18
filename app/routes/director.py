"""
Router del DIRECTOR: panorama académico agregado por Departamento/Facultad para decisiones
estratégicas en tiempo real. Lectura agregada y seudonimizada (G2); no altera notas (G1).
"""
import re

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, requiere_rol
from app.models.teacher import ROL_DIRECTOR, ROL_INVESTIGADOR
from app.services import director_service, exportador_service

router = APIRouter(prefix="/director", tags=["director"])

# El panorama transversal es para Dirección/CEO; el investigador también lo consume (trazabilidad).
req_direccion = requiere_rol(ROL_DIRECTOR, ROL_INVESTIGADOR)


@router.get("/panorama", dependencies=[Depends(req_direccion)])
def panorama(facultad: str | None = None, departamento: str | None = None,
             umbral: float = 60.0, db: Session = Depends(get_db)):
    """Logro por RA agregado por curso → departamento → facultad, con las brechas más frecuentes."""
    return director_service.panorama(db, facultad, departamento, umbral_brecha=umbral)


@router.post("/panorama/{formato}", dependencies=[Depends(req_direccion)])
def panorama_export(formato: str, facultad: str | None = None, departamento: str | None = None,
                    umbral: float = 60.0, db: Session = Depends(get_db)):
    """Descarga el panorama en Word/PDF/Excel para las decisiones de Dirección."""
    if formato not in ("docx", "pdf", "xlsx"):
        from app.core.errors import unprocessable
        raise unprocessable("Formato no soportado (docx | pdf | xlsx).")
    out = director_service.panorama_export_payload(db, facultad, departamento, umbral_brecha=umbral)
    data, media = exportador_service.exportar(formato, out["payload"])
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", "panorama_direccion")[:80]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.{formato}"'})
