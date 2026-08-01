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
from app.core.ratelimit import limit
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
        cod_ay = data["agente"].get("ayudante_codigo")
        if cod_ay:
            ay = sil.ayudante_url(cod_ay, base)
            data["agente"]["ayudante_join_url"] = ay
            data["agente"]["ayudante_qr"] = _qr(ay) if base else ""
    return data


@router.get("/courses/{course_id}/silabo/mapa", dependencies=[Depends(req_profesor)])
def mapa(course_id: UUID, db: Session = Depends(get_db)):
    return sil.mapa_confusion(db, course_id)


@router.get("/courses/{course_id}/silabo/bitacora", dependencies=[Depends(req_profesor)])
def bitacora(course_id: UUID, db: Session = Depends(get_db)):
    return sil.bitacora_estado(db, course_id)


@router.get("/courses/{course_id}/silabo/comite", dependencies=[Depends(req_profesor)])
def comite(course_id: UUID, db: Session = Depends(get_db)):
    from app.services import etica_service as etica
    return etica.informe_comite(db, course_id)


@router.post("/silabo/mensaje/{mensaje_id}/responder", dependencies=[Depends(req_profesor)])
def responder(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.responder_docente(db, mensaje_id, (payload or {}).get("respuesta", ""), quien="docente")


@router.post("/silabo/mensaje/{mensaje_id}/delegar", dependencies=[Depends(req_profesor)])
def delegar(mensaje_id: UUID, db: Session = Depends(get_db)):
    return sil.delegar_al_ayudante(db, mensaje_id)


# ── Nivel 2 · Ayudante (opcional) ─────────────────────────────────────────────────────
@router.post("/courses/{course_id}/silabo/ayudante", dependencies=[Depends(req_profesor)])
def config_ayudante(course_id: UUID, request: Request, payload: dict, db: Session = Depends(get_db)):
    a = sil.configurar_ayudante(db, course_id, activo=bool((payload or {}).get("activo")))
    base = settings.public_app_url or request.headers.get("origin") or ""
    enlace = sil.ayudante_url(a.ayudante_codigo, base) if a.ayudante_codigo else ""
    return {"ayudante_activo": a.ayudante_activo, "ayudante_codigo": a.ayudante_codigo,
            "join_url": enlace, "qr": _qr(enlace) if (enlace and base) else ""}


@router.get("/ayudante/{codigo}")
def ayudante_info(codigo: str, db: Session = Depends(get_db)):
    a = sil.agente_por_ayudante_codigo(db, codigo)
    return {"codigo": codigo, "activo": a.ayudante_activo, "nombre_curso": a.nombre_curso}


@router.get("/ayudante/{codigo}/turno")
def ayudante_turno(codigo: str, db: Session = Depends(get_db)):
    return sil.tablero_ayudante(db, codigo)


@router.post("/ayudante/mensaje/{mensaje_id}/responder")
def ayudante_responder(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.responder_docente(db, mensaje_id, (payload or {}).get("respuesta", ""), quien="ayudante")


@router.post("/ayudante/mensaje/{mensaje_id}/subir")
def ayudante_subir(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.subir_al_profesor(db, mensaje_id, (payload or {}).get("motivo", ""))


@router.post("/silabo/mensaje/{mensaje_id}/estado", dependencies=[Depends(req_profesor)])
def estado(mensaje_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return sil.marcar_estado(db, mensaje_id, (payload or {}).get("estado", ""))


@router.post("/silabo/mensaje/{mensaje_id}/al-contexto", dependencies=[Depends(req_profesor)])
def al_contexto(mensaje_id: UUID, db: Session = Depends(get_db)):
    return sil.agregar_al_contexto(db, mensaje_id)


# ── público (alumno, sin login) ──────────────────────────────────────────────────────
@router.get("/silabo/{codigo}")
def info_publica(codigo: str, db: Session = Depends(get_db)):
    a = sil.agente_por_codigo(db, codigo)
    return {"codigo": a.codigo, "activo": a.activo, "nombre_curso": a.nombre_curso}


@router.post("/silabo/{codigo}/preguntar")
def preguntar(codigo: str, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return sil.preguntar(db, codigo, payload.get("pregunta", ""), payload.get("alias"),
                         device_id=payload.get("device_id"), escalar=bool(payload.get("escalar")),
                         material=payload.get("material"), imagenes=payload.get("imagenes"))


@router.post("/silabo/{codigo}/identificar")
@limit("10/minute")
def identificar(codigo: str, request: Request, payload: dict, db: Session = Depends(get_db)):
    # El alumno se identifica con su RUT O su matrícula contra la NÓMINA del curso → devuelve su nombre real.
    # Rate-limit por IP (anti enumeración). No revela nombres fuera de la nómina.
    payload = payload or {}
    valor = payload.get("valor") or payload.get("rut") or payload.get("matricula") or ""
    return sil.identificar_por_rut(db, codigo, valor)


@router.post("/silabo/{codigo}/pandilla/passkey/reto")
@limit("12/minute")
def pandilla_passkey_reto(codigo: str, request: Request, payload: dict, db: Session = Depends(get_db)):
    # Compuerta passkey → ubicación (Fase 2): opciones de aserción para probar la passkey del alumno.
    from app.services import pandilla_service as pand
    payload = payload or {}
    valor = payload.get("valor") or payload.get("rut") or payload.get("matricula") or ""
    return pand.reto_ubicacion(db, codigo, valor, request.headers.get("origin"))


@router.post("/silabo/{codigo}/pandilla/passkey/verificar")
@limit("12/minute")
def pandilla_passkey_verificar(codigo: str, request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import pandilla_service as pand
    payload = payload or {}
    return pand.verificar_ubicacion(db, codigo, payload.get("credential"), payload.get("reto_token"),
                                    request.headers.get("origin"))


@router.get("/silabo/{codigo}/mis-consultas")
def mis_consultas(codigo: str, device_id: str = "", db: Session = Depends(get_db)):
    return sil.mis_consultas(db, codigo, device_id)


@router.get("/silabo/{codigo}/perfil")
def perfil(codigo: str, device_id: str = "", db: Session = Depends(get_db)):
    return sil.perfil_estudiante(db, codigo, device_id)


@router.post("/silabo/{codigo}/confianza")
def confianza(codigo: str, payload: dict, db: Session = Depends(get_db)):
    payload = payload or {}
    return sil.set_confianza(db, payload.get("mensaje_id"), payload.get("device_id"), payload.get("confianza", ""))


@router.post("/silabo/{codigo}/borrar-memoria")
def borrar_memoria(codigo: str, payload: dict, db: Session = Depends(get_db)):
    return sil.borrar_memoria(db, codigo, (payload or {}).get("device_id", ""))
