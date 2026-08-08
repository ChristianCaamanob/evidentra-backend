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


# ───────────────────────── Gobernanza · Decisiones trazables + planes de mejora (memoria institucional)
from typing import Literal
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from app.models.decision_gov import DecisionGov
from app.models.teacher import Teacher
from app.core.errors import not_found, forbidden


class DecisionCrear(BaseModel):
    tipo: Literal["decision", "plan_mejora"] = "decision"
    nivel: Literal["departamento", "carrera", "escuela", "decanatura"] = "departamento"
    ambito: str = Field(default="", max_length=160)
    titulo: str = Field(min_length=2, max_length=300)
    problema: str = ""
    evidencia: str = ""
    alternativas: str = ""
    decision: str = ""
    responsable: str = Field(default="", max_length=200)
    plazo: str = Field(default="", max_length=40)
    indicador: str = ""


class DecisionActualizar(BaseModel):
    titulo: str | None = Field(default=None, max_length=300)
    problema: str | None = None
    evidencia: str | None = None
    alternativas: str | None = None
    decision: str | None = None
    responsable: str | None = Field(default=None, max_length=200)
    plazo: str | None = Field(default=None, max_length=40)
    indicador: str | None = None
    estado: Literal["abierta", "en_curso", "cerrada"] | None = None
    resultado: str | None = None
    revision: Literal["mantener", "ajustar", "detener", ""] | None = None
    evento: str | None = Field(default=None, max_length=400)   # nota para la bitácora (append-only)


def _dg_dto(d: DecisionGov) -> dict:
    return {"id": str(d.id), "tipo": d.tipo, "nivel": d.nivel, "ambito": d.ambito, "titulo": d.titulo,
            "problema": d.problema, "evidencia": d.evidencia, "alternativas": d.alternativas,
            "decision": d.decision, "responsable": d.responsable, "plazo": d.plazo, "indicador": d.indicador,
            "estado": d.estado, "resultado": d.resultado, "revision": d.revision, "bitacora": d.bitacora or [],
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}


def _dg_evento(d: DecisionGov, actor: str, evento: str):
    b = list(d.bitacora or [])
    b.append({"ts": datetime.now(timezone.utc).isoformat(), "actor": actor, "evento": evento})
    d.bitacora = b


@router.get("/decisiones", dependencies=[Depends(req_direccion)])
def decisiones_listar(nivel: str | None = None, estado: str | None = None, tipo: str | None = None,
                      db: Session = Depends(get_db)):
    """Lista las decisiones/planes (memoria institucional). Filtros por nivel/estado/tipo."""
    q = db.query(DecisionGov)
    if nivel:
        q = q.filter(DecisionGov.nivel == nivel)
    if estado:
        q = q.filter(DecisionGov.estado == estado)
    if tipo:
        q = q.filter(DecisionGov.tipo == tipo)
    items = q.order_by(DecisionGov.updated_at.desc()).all()
    return {"n": len(items), "decisiones": [_dg_dto(d) for d in items]}


@router.post("/decisiones", status_code=201)
def decisiones_crear(body: DecisionCrear, db: Session = Depends(get_db),
                     usuario: Teacher = Depends(req_direccion)):
    d = DecisionGov(autor_id=usuario.id, tipo=body.tipo, nivel=body.nivel, ambito=body.ambito.strip(),
                    titulo=body.titulo.strip(), problema=body.problema, evidencia=body.evidencia,
                    alternativas=body.alternativas, decision=body.decision, responsable=body.responsable,
                    plazo=body.plazo, indicador=body.indicador, estado="abierta", bitacora=[])
    _dg_evento(d, getattr(usuario, "nombre", "") or str(usuario.id), "Decisión creada")
    db.add(d)
    db.commit()
    db.refresh(d)
    return _dg_dto(d)


@router.get("/decisiones/{did}", dependencies=[Depends(req_direccion)])
def decisiones_obtener(did: UUID, db: Session = Depends(get_db)):
    d = db.get(DecisionGov, did)
    if not d:
        raise not_found("Decisión no encontrada.")
    return _dg_dto(d)


@router.patch("/decisiones/{did}")
def decisiones_actualizar(did: UUID, body: DecisionActualizar, db: Session = Depends(get_db),
                          usuario: Teacher = Depends(req_direccion)):
    """Actualiza campos y REGISTRA el cambio en la bitácora (append-only, memoria auditable)."""
    d = db.get(DecisionGov, did)
    if not d:
        raise not_found("Decisión no encontrada.")
    cambios = []
    for campo in ("titulo", "problema", "evidencia", "alternativas", "decision", "responsable",
                  "plazo", "indicador", "estado", "resultado", "revision"):
        val = getattr(body, campo)
        if val is not None and val != getattr(d, campo):
            setattr(d, campo, val)
            cambios.append(campo)
    actor = getattr(usuario, "nombre", "") or str(usuario.id)
    if body.evento:
        _dg_evento(d, actor, body.evento.strip())
    elif cambios:
        _dg_evento(d, actor, "Actualizó: " + ", ".join(cambios))
    db.commit()
    db.refresh(d)
    return _dg_dto(d)
