"""Escudo de comunicación (Pilar II) — rutas del agente de sílabo + bandeja.

Docente (req_profesor):
  POST /courses/{cid}/silabo             -> crea/actualiza el agente (contexto + activo)
  GET  /courses/{cid}/silabo             -> agente + enlace público + bandeja clasificada
  POST /silabo/mensaje/{id}/responder    -> responde un mensaje de la bandeja
  POST /silabo/mensaje/{id}/estado       -> cambia el estado (pendiente/resuelta/…)

Público (alumno, sin login):
  GET  /silabo/{codigo}                  -> ¿activo? + nombre del curso (para la página del alumno)
  POST /silabo/{codigo}/preguntar        -> pregunta -> respuesta de la IA (o derivación al docente)
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.config import settings
from app.models.course import Course
from app.services import silabo_service as sil

router = APIRouter(tags=["silabo"])


def _qr(texto: str) -> str:
    try:
        from app.services import en_vivo_service as ev
        return ev.qr_data_url(texto)
    except Exception:
        return ""


def _nombre_curso(db, course_id) -> str | None:
    try:
        c = db.query(Course).filter(Course.id == course_id).first()
        return getattr(c, "name", None)
    except Exception:
        return None


@router.post("/courses/{course_id}/silabo", dependencies=[Depends(req_profesor)])
def guardar_agente(course_id: UUID, request: Request, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    a = sil.crear_o_actualizar(db, course_id, contexto=payload.get("contexto", ""),
                               activo=bool(payload.get("activo")),
                               nombre_curso=_nombre_curso(db, course_id),
                               config=payload.get("config"))
    base = settings.public_app_url or request.headers.get("origin") or ""
    enlace = sil.join_url(a.codigo, base)
    return {**sil._agente_dict(a), "join_url": enlace, "qr": _qr(enlace if base else a.codigo)}


@router.get("/courses/{course_id}/silabo", dependencies=[Depends(req_profesor)])
def ver_agente(course_id: UUID, request: Request, solo_pendientes: bool = False,
               db: Session = Depends(get_db)):
    data = sil.bandeja(db, course_id, solo_pendientes=solo_pendientes)
    base = settings.public_app_url or request.headers.get("origin") or ""
    if data.get("agente"):
        enlace = sil.join_url(data["agente"]["codigo"], base)
        data["agente"]["join_url"] = enlace
        data["agente"]["qr"] = _qr(enlace if base else data["agente"]["codigo"])
    return data


@router.post("/silabo/mensaje/{mensaje_id}/responder", dependencies=[Depends(req_profesor)])
def responder(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.responder_docente(db, mensaje_id, (payload or {}).get("respuesta", ""))


@router.post("/silabo/mensaje/{mensaje_id}/estado", dependencies=[Depends(req_profesor)])
def estado(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.marcar_estado(db, mensaje_id, (payload or {}).get("estado", ""))


# ── público (alumno, sin login) ──────────────────────────────────────────────────────
@router.get("/silabo/{codigo}")
def info_publica(codigo: str, db: Session = Depends(get_db)):
    a = sil.agente_por_codigo(db, codigo)
    return {"codigo": a.codigo, "activo": a.activo, "nombre_curso": a.nombre_curso}


@router.post("/silabo/{codigo}/preguntar")
def preguntar(codigo: str, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return sil.preguntar(db, codigo, payload.get("pregunta", ""), payload.get("alias"))
