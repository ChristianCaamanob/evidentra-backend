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
@router.get("/silabo/por-curso/{course_code}")
def silabo_por_curso(course_code: str, db: Session = Depends(get_db)):
    # Resuelve el código ACADÉMICO del ramo → agente Runi (para que el alumno entre con el código que conoce).
    return sil.info_por_curso(db, course_code)


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


@router.post("/silabo/{codigo}/pandilla/ubicacion")
@limit("40/minute")
def pandilla_ubicacion_compartir(codigo: str, request: Request, payload: dict, db: Session = Depends(get_db)):
    # Comparte/actualiza la ubicación (requiere el token de passkey). Voluntaria, temporal, sin historial.
    from app.services import pandilla_service as pand
    p = payload or {}
    return pand.compartir_ubicacion(db, codigo, p.get("ubicacion_token"), p.get("lat"), p.get("lng"),
                                    accuracy=p.get("accuracy"), precision=p.get("precision", "aprox"),
                                    char=p.get("char"), estado=p.get("estado"),
                                    duracion_min=p.get("duracion_min", 30))


@router.get("/silabo/{codigo}/pandilla/ubicaciones")
def pandilla_ubicaciones(codigo: str, ubicacion_token: str = "", db: Session = Depends(get_db)):
    from app.services import pandilla_service as pand
    return pand.ubicaciones_grupo(db, codigo, ubicacion_token)


@router.delete("/silabo/{codigo}/pandilla/ubicacion")
def pandilla_ubicacion_dejar(codigo: str, ubicacion_token: str = "", db: Session = Depends(get_db)):
    from app.services import pandilla_service as pand
    return pand.dejar_ubicacion(db, codigo, ubicacion_token)


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


# ── Cuenta global del alumno (app Runi): registro + login con passkey ──────────
@router.post("/alumno/registrar/opciones")
@limit("8/minute")
def alumno_reg_opciones(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import alumno_auth as aa
    p = payload or {}
    return aa.registrar_opciones(db, p.get("rut", ""), p.get("nombres") or p.get("nombre", ""),
                                 p.get("apellido_paterno") or p.get("apellido", ""),
                                 p.get("apellido_materno", ""), request.headers.get("origin"))


@router.post("/alumno/registrar/verificar")
@limit("8/minute")
def alumno_reg_verificar(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import alumno_auth as aa
    p = payload or {}
    return aa.registrar_verificar(db, p.get("reg_token"), p.get("credential"), request.headers.get("origin"))


@router.post("/alumno/login/opciones")
@limit("15/minute")
def alumno_login_opciones(request: Request, payload: dict = None, db: Session = Depends(get_db)):
    from app.services import alumno_auth as aa
    return aa.login_opciones(db, request.headers.get("origin"))


@router.post("/alumno/login/verificar")
@limit("15/minute")
def alumno_login_verificar(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import alumno_auth as aa
    p = payload or {}
    return aa.login_verificar(db, p.get("login_token"), p.get("credential"), request.headers.get("origin"))


@router.get("/alumno/sesion")
def alumno_sesion(token: str = "", db: Session = Depends(get_db)):
    from app.services import alumno_auth as aa
    info = aa.sesion_desde_token(db, token)
    return {"ok": bool(info), "alumno": info}


# ── Horario mágico + Agenda (v2.0) ────────────────────────────────────────────
@router.post("/alumno/horario/extraer")
@limit("6/minute")
def alumno_horario_extraer(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import horario_service as hs
    p = payload or {}
    return hs.extraer(p.get("imagenes"), p.get("texto", ""))


@router.post("/alumno/agenda")
@limit("20/minute")
def alumno_agenda_guardar(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return hs.guardar(db, ow, p.get("bloques") or [])


@router.get("/alumno/agenda")
def alumno_agenda_obtener(device_id: str = "", sesion: str = "", db: Session = Depends(get_db)):
    from app.services import horario_service as hs
    return hs.obtener(db, hs.owner_key(db, device_id, sesion))


# ── Evaluaciones del curso (docente carga fecha → agenda del alumno + recordatorios) ──
@router.post("/courses/{course_id}/evaluaciones", dependencies=[Depends(req_profesor)])
def evals_crear(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    from app.services import evaluaciones_agenda_service as ev
    return ev.crear(db, course_id, payload)


@router.get("/courses/{course_id}/evaluaciones", dependencies=[Depends(req_profesor)])
def evals_listar(course_id: UUID, db: Session = Depends(get_db)):
    from app.services import evaluaciones_agenda_service as ev
    return ev.listar(db, course_id)


@router.delete("/evaluaciones/{eval_id}", dependencies=[Depends(req_profesor)])
def evals_eliminar(eval_id: UUID, db: Session = Depends(get_db)):
    from app.services import evaluaciones_agenda_service as ev
    return ev.eliminar(db, eval_id)


@router.get("/silabo/{codigo}/evaluaciones")
def evals_publicas(codigo: str, db: Session = Depends(get_db)):
    from app.services import evaluaciones_agenda_service as ev
    return ev.listar_por_silabo(db, codigo)


# ── Web Push (v2.0 · notificaciones a pantalla bloqueada) ──────────────────────
@router.get("/push/vapid")
def push_vapid(db: Session = Depends(get_db)):
    from app.services import push_service as ps
    return ps.vapid_public(db)


@router.post("/push/subscribe")
@limit("20/minute")
def push_subscribe(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import push_service as ps
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return ps.guardar_sub(db, ow, p.get("subscription") or {})


@router.post("/push/follow")
@limit("30/minute")
def push_follow(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import push_service as ps
    from app.services import horario_service as hs
    from app.services import silabo_service as sil
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    codigo = str(p.get("codigo") or "").strip()
    if not codigo:
        return {"ok": False}
    a = sil.agente_por_codigo(db, codigo)
    if not a or not getattr(a, "course_id", None):
        return {"ok": False}
    return ps.seguir_curso(db, ow, a.course_id, codigo)


@router.post("/push/tick")
@limit("6/minute")
def push_tick(request: Request, db: Session = Depends(get_db)):
    """Barrido idempotente de recordatorios. Seguro de llamar repetidamente (dedupe interno)."""
    from app.services import push_service as ps
    return ps.tick(db)


# ── Reuniones / reservas nativas (v2.0 · Bookings keyless) ─────────────────────
@router.post("/reuniones")
@limit("15/minute")
def reunion_crear(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return rs.crear(db, ow, p.get("anfitrion", ""), p)


@router.get("/reuniones/mias")
def reunion_mias(device_id: str = "", sesion: str = "", db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    return rs.mias(db, hs.owner_key(db, device_id, sesion))


@router.get("/reuniones/agenda")
def reunion_agenda(device_id: str = "", sesion: str = "", db: Session = Depends(get_db)):
    """Reuniones del alumno (como anfitrión y como invitado) para fusionar en su agenda."""
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    return rs.de_alumno(db, hs.owner_key(db, device_id, sesion))


@router.delete("/reuniones/{code}")
@limit("15/minute")
def reunion_eliminar(request: Request, code: str, payload: dict = None, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return rs.eliminar(db, ow, code)


@router.get("/reunion/{code}")
def reunion_publica(code: str, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    return rs.publica(db, code)


@router.post("/reunion/{code}/reservar")
@limit("20/minute")
def reunion_reservar(request: Request, code: str, payload: dict, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    if p.get("sesion") or p.get("device_id"):
        p = dict(p, owner_key=hs.owner_key(db, p.get("device_id", ""), p.get("sesion", "")))
    return rs.reservar(db, code, p)


@router.get("/reunion/video-config")
def reunion_video_config(db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    return rs.video_config()


@router.post("/reunion/video-jwt")
@limit("30/minute")
def reunion_video_jwt(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    nombre = str(p.get("nombre") or "").strip()
    if not nombre and p.get("sesion"):
        try:
            from app.services import alumno_auth as aa
            info = aa.sesion_desde_token(db, p.get("sesion"))
            nombre = (info or {}).get("nombre") or ""
        except Exception:  # noqa: BLE001
            pass
    return rs.video_jwt(str(p.get("room") or "").strip(), nombre, ow, moderador=True)


@router.post("/reunion/reserva/{reserva_id}/cancelar")
@limit("20/minute")
def reunion_cancelar(request: Request, reserva_id: str, payload: dict = None, db: Session = Depends(get_db)):
    from app.services import reunion_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return rs.cancelar(db, ow, reserva_id)


# ── Recordatorios personales del alumno (v2.0 · con alarma push) ───────────────
@router.post("/alumno/recordatorios")
@limit("30/minute")
def recordatorio_crear(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import recordatorio_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return rs.crear(db, ow, p)


@router.get("/alumno/recordatorios")
def recordatorio_listar(device_id: str = "", sesion: str = "", db: Session = Depends(get_db)):
    from app.services import recordatorio_service as rs
    from app.services import horario_service as hs
    return rs.listar(db, hs.owner_key(db, device_id, sesion))


@router.delete("/alumno/recordatorios/{rid}")
@limit("30/minute")
def recordatorio_eliminar(request: Request, rid: str, payload: dict = None, db: Session = Depends(get_db)):
    from app.services import recordatorio_service as rs
    from app.services import horario_service as hs
    p = payload or {}
    ow = hs.owner_key(db, p.get("device_id", ""), p.get("sesion", ""))
    return rs.eliminar(db, ow, rid)


# ── Monitoreo docente por estudiante (v2.0, read-only) ─────────────────────────
@router.get("/courses/{course_id}/monitoreo", dependencies=[Depends(req_profesor)])
def curso_monitoreo(course_id: UUID, db: Session = Depends(get_db)):
    return sil.monitoreo_curso(db, course_id)
