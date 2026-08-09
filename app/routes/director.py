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


@router.get("/decisiones")
def decisiones_listar(nivel: str | None = None, estado: str | None = None, tipo: str | None = None,
                      db: Session = Depends(get_db), usuario: Teacher = Depends(req_direccion)):
    """Lista las decisiones/planes (memoria institucional). Filtros por nivel/estado/tipo.
    Aplica RBAC POR ÁMBITO: cada usuario ve solo lo de sus ámbitos (con descenso progresivo);
    sin membresías → acceso agregado legacy (ve todo)."""
    from app.services import gobernanza_ambito_service as _gas
    q = db.query(DecisionGov)
    if nivel:
        q = q.filter(DecisionGov.nivel == nivel)
    if estado:
        q = q.filter(DecisionGov.estado == estado)
    if tipo:
        q = q.filter(DecisionGov.tipo == tipo)
    items = q.order_by(DecisionGov.updated_at.desc()).all()
    ms = _gas.membresias_activas(db, usuario)
    visibles = [d for d in items if _gas.puede_ver(usuario, ms, d.nivel, d.ambito or "")]
    return {"n": len(visibles), "decisiones": [_dg_dto(d) for d in visibles], "ambito_aplicado": bool(ms)}


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


@router.delete("/decisiones/{did}", status_code=204)
def decisiones_borrar(did: UUID, db: Session = Depends(get_db),
                      usuario: Teacher = Depends(req_direccion)):
    """Elimina una decisión ERRÓNEA (solo su autor o el creador). La bitácora es la memoria
    auditable de una decisión válida; un registro creado por error sí puede corregirse."""
    d = db.get(DecisionGov, did)
    if not d:
        raise not_found("Decisión no encontrada.")
    if str(d.autor_id) != str(usuario.id) and usuario.rol != "creador":
        raise forbidden("Solo el autor o el creador puede eliminar esta decisión.")
    db.delete(d)
    db.commit()
    return None


# ───────────────────────── RBAC por ÁMBITO (Fase 0A · gobernanza escalonada)
from app.models.membresia import Membresia, NIVELES as _NIVELES, ACCIONES as _ACCIONES, DETALLE as _DETALLE
from app.services import gobernanza_ambito_service as gas

req_creador_local = requiere_rol()   # solo creador (gestiona membresías)


class MembresiaCrear(BaseModel):
    teacher_id: UUID
    nivel: Literal["departamento", "carrera", "escuela", "facultad", "decanatura"]
    ambito: str = Field(default="", max_length=160)
    acciones: list[Literal["observar", "comentar", "solicitar", "aprobar", "intervenir"]] = ["observar"]
    detalle: Literal["agregado", "seudonimizado", "identificable"] = "agregado"
    finalidad: str = Field(default="", max_length=300)
    vigente_hasta: str | None = None   # ISO date/datetime opcional


class AccesoPersonalCrear(BaseModel):
    ambito: str = Field(default="", max_length=160)
    sujeto_ref: str = Field(default="", max_length=160)
    finalidad: str = Field(min_length=3, max_length=300)
    justificacion: str = Field(min_length=3)
    emergencia: bool = False


@router.get("/mis-ambitos", dependencies=[Depends(req_direccion)])
def mis_ambitos(db: Session = Depends(get_db), usuario: Teacher = Depends(req_direccion)):
    """Ámbitos (membresías activas y vigentes) del usuario. Vacío = acceso agregado legacy."""
    ms = gas.membresias_activas(db, usuario)
    return {"rol": usuario.rol, "n": len(ms), "ambitos": [gas.dto_membresia(m) for m in ms],
            "legacy_agregado": (len(ms) == 0)}


@router.get("/membresias", dependencies=[Depends(req_creador_local)])
def membresias_listar(teacher_id: UUID | None = None, db: Session = Depends(get_db)):
    """Lista de membresías (solo creador). Filtro opcional por teacher_id."""
    q = db.query(Membresia)
    if teacher_id:
        q = q.filter(Membresia.teacher_id == teacher_id)
    ms = q.order_by(Membresia.created_at.desc()).all()
    return {"n": len(ms), "membresias": [gas.dto_membresia(m) for m in ms]}


@router.post("/membresias", status_code=201)
def membresias_crear(body: MembresiaCrear, db: Session = Depends(get_db),
                     usuario: Teacher = Depends(req_creador_local)):
    """Otorga una membresía por ámbito (solo creador)."""
    from datetime import datetime
    vh = None
    if body.vigente_hasta:
        try:
            vh = datetime.fromisoformat(body.vigente_hasta.replace("Z", "+00:00"))
        except ValueError:
            from app.core.errors import unprocessable
            raise unprocessable("vigente_hasta debe ser fecha ISO (AAAA-MM-DD).")
    m = Membresia(teacher_id=body.teacher_id, nivel=body.nivel, ambito=body.ambito.strip(),
                  acciones=",".join(body.acciones) or "observar", detalle=body.detalle,
                  finalidad=body.finalidad.strip(), vigente_hasta=vh, otorgada_por=usuario.id, activa=True)
    db.add(m)
    db.commit()
    db.refresh(m)
    return gas.dto_membresia(m)


@router.delete("/membresias/{mid}", status_code=204)
def membresias_revocar(mid: UUID, db: Session = Depends(get_db),
                       usuario: Teacher = Depends(req_creador_local)):
    """Revoca (desactiva) una membresía (solo creador)."""
    m = db.get(Membresia, mid)
    if not m:
        raise not_found("Membresía no encontrada.")
    m.activa = False
    db.commit()
    return None


@router.post("/acceso-personal", status_code=201)
def acceso_personal(body: AccesoPersonalCrear, db: Session = Depends(get_db),
                    usuario: Teacher = Depends(req_direccion)):
    """Registra un acceso a dato personal (descenso hasta la persona) — exige finalidad + justificación."""
    try:
        log = gas.registrar_acceso_personal(db, usuario, body.ambito, body.sujeto_ref,
                                            body.finalidad, body.justificacion, body.emergencia)
    except ValueError as e:
        from app.core.errors import unprocessable
        raise unprocessable(str(e))
    return {"id": str(log.id), "registrado": True, "ts": log.created_at.isoformat() if log.created_at else None}


@router.get("/staff", dependencies=[Depends(req_creador_local)])
def staff_listar(db: Session = Depends(get_db)):
    """Lista de staff con sus membresías activas (solo creador) — para el gestor de ámbitos."""
    ts = db.query(Teacher).order_by(Teacher.name).all()
    out = []
    for t in ts:
        ms = gas.membresias_activas(db, t)
        out.append({"id": str(t.id), "nombre": t.name, "email": t.email, "rol": t.rol,
                    "membresias": [gas.dto_membresia(m) for m in ms]})
    return {"n": len(out), "staff": out}
