"""
Router del modo EN VIVO (quiz sincronico estilo Socrative).

Docente (requiere rol profesor/investigador):
  POST /assessments/{id}/en-vivo            -> abre una sala; retorna codigo + QR
  POST /en-vivo/{codigo}/avanzar            -> pasa a la siguiente pregunta (o cierra)
  POST /en-vivo/{codigo}/pausar             -> congela la sala
  POST /en-vivo/{codigo}/reanudar           -> reactiva la sala
  POST /en-vivo/{codigo}/cerrar             -> termina la sesion
  GET  /en-vivo/{codigo}/resultados         -> distribucion por pregunta + ranking (en vivo)
  GET  /en-vivo/{codigo}/matriz             -> matriz binaria participante x item (psicometria)

Participantes (publico, sin login: los estudiantes se unen con el codigo):
  POST /en-vivo/{codigo}/unir               -> entra a la sala; retorna participante_id + token
  POST /en-vivo/{codigo}/responder          -> responde la pregunta activa
  GET  /en-vivo/{codigo}/estado             -> polling: estado, pregunta_actual, conteos

Gobernanza: en vivo NO se salta la corrección con pauta ya validada; al cerrar, la
matriz alimenta la misma psicometría (Rasch/KR-20), sin silos.
"""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.config import settings
from app.services import en_vivo_service as ev
from app.services import exportador_service

router = APIRouter(tags=["en-vivo"])


def _sesion_dict(s) -> dict:
    return {"codigo": s.codigo, "estado": s.estado, "pregunta_actual": s.pregunta_actual,
            "n_preguntas": s.n_preguntas}


# ── docente ──────────────────────────────────────────────────────────────────────────
@router.post("/assessments/{assessment_id}/en-vivo", dependencies=[Depends(req_profesor)])
def crear_sesion(assessment_id: UUID, request: Request, payload: dict | None = None,
                 db: Session = Depends(get_db)):
    payload = payload or {}
    version = payload.get("version", "A")
    # config: retro_alumno, revelar_correccion, modo_ritmo, shuffle_preguntas, shuffle_opciones
    s = ev.crear_sesion(db, assessment_id, version=version, config=payload)
    # Base pública para el QR: config explícita > header Origin de la petición.
    base = settings.public_app_url or request.headers.get("origin") or ""
    enlace = ev.join_url(s.codigo, base)
    return {**_sesion_dict(s), "join_url": enlace,
            "qr": ev.qr_data_url(enlace if base else s.codigo),
            **ev._config_dict(s)}


@router.get("/assessments/{assessment_id}/en-vivo/historial", dependencies=[Depends(req_profesor)])
def historial(assessment_id: UUID, db: Session = Depends(get_db)):
    """Salas en vivo anteriores de esta evaluación (código, fecha, estado, participantes). Permite
    volver a una sesión pasada: su informe/integridad se abren con el código."""
    return ev.historial_sesiones(db, assessment_id)


@router.post("/en-vivo/{codigo}/avanzar", dependencies=[Depends(req_profesor)])
def avanzar(codigo: str, db: Session = Depends(get_db)):
    return _sesion_dict(ev.avanzar(db, codigo))


@router.post("/en-vivo/{codigo}/pausar", dependencies=[Depends(req_profesor)])
def pausar(codigo: str, db: Session = Depends(get_db)):
    return _sesion_dict(ev.pausar(db, codigo))


@router.post("/en-vivo/{codigo}/reanudar", dependencies=[Depends(req_profesor)])
def reanudar(codigo: str, db: Session = Depends(get_db)):
    return _sesion_dict(ev.reanudar(db, codigo))


@router.post("/en-vivo/{codigo}/cerrar", dependencies=[Depends(req_profesor)])
def cerrar(codigo: str, db: Session = Depends(get_db)):
    return ev.cerrar(db, codigo)  # incluye scans_incorporados


@router.get("/en-vivo/{codigo}/resultados", dependencies=[Depends(req_profesor)])
def resultados(codigo: str, db: Session = Depends(get_db)):
    return ev.resultados(db, codigo)


@router.get("/en-vivo/{codigo}/matriz", dependencies=[Depends(req_profesor)])
def matriz(codigo: str, db: Session = Depends(get_db)):
    return ev.matriz_binaria(db, codigo)


@router.get("/en-vivo/{codigo}/informe", dependencies=[Depends(req_profesor)])
def informe(codigo: str, db: Session = Depends(get_db)):
    """Informe integral de la sala (psicometría TCT + resultados por RA + estudiantes)."""
    return ev.informe_en_vivo(db, codigo)


@router.post("/en-vivo/{codigo}/informe/{formato}", dependencies=[Depends(req_profesor)])
def informe_export(codigo: str, formato: str, perfil: str = "docente", db: Session = Depends(get_db)):
    """Descarga el informe de la sala. perfil=docente (bajada pedagógica + distribución de notas +
    integridad por alumno) | investigador (pool psicométrico completo)."""
    if formato not in ("docx", "pdf", "xlsx"):
        from app.core.errors import unprocessable
        raise unprocessable("Formato no soportado (docx | pdf | xlsx).")
    payload = ev.informe_payload(db, codigo, formato, perfil=perfil)
    data, media = exportador_service.exportar(formato, payload)
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", f"informe_en_vivo_{codigo}")[:80]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.{formato}"'})


# ── banco de ítems (contenido para el modo digital) ──────────────────────────────────
@router.get("/en-vivo/banco/{assessment_id}", dependencies=[Depends(req_profesor)])
def banco_get(assessment_id: UUID, version: str = "A", db: Session = Depends(get_db)):
    return ev.contenido_items(db, assessment_id, version)


@router.post("/en-vivo/banco/{assessment_id}", dependencies=[Depends(req_profesor)])
def banco_guardar(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return ev.guardar_contenido_items(db, assessment_id,
                                      payload.get("version", "A"), payload.get("items", []))


@router.post("/en-vivo/banco-proponer", dependencies=[Depends(req_profesor)])
def banco_proponer(payload: dict, db: Session = Depends(get_db)):
    return ev.proponer_desde_texto(payload.get("texto", ""),
                                   payload.get("n_alternativas", 4))


@router.post("/en-vivo/banco-importar/{assessment_id}", dependencies=[Depends(req_profesor)])
def banco_importar(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Crea la pauta de alternativas (con letra correcta) desde preguntas estructuradas y la
    valida, para poder abrir la sala en vivo. Módulo de importación de preguntas."""
    return ev.importar_preguntas(db, assessment_id,
                                 payload.get("version", "A"), payload.get("items", []))


# ── participantes (publico) ──────────────────────────────────────────────────────────
@router.post("/en-vivo/{codigo}/unir")
def unir(codigo: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    ev.verificar_seb_o_error(db, ev._sesion(db, codigo), request)   # gate SEB si la sala lo exige
    p = ev.unir(db, codigo, payload.get("alias", ""), payload.get("student_id"))
    return {"participante_id": str(p.id), "token": p.token, "alias": p.alias}


@router.post("/en-vivo/{codigo}/responder")
def responder(codigo: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    ev.verificar_seb_o_error(db, ev._sesion(db, codigo), request)
    return ev.responder(db, codigo, payload.get("participante_id"),
                        payload.get("token", ""), respuesta=payload.get("respuesta"),
                        opcion_idx=payload.get("opcion_idx"))


@router.get("/en-vivo/{codigo}/nomina")
def nomina(codigo: str, db: Session = Depends(get_db)):
    """Nómina del curso (nombres, sin RUT) para que el alumno se identifique al unirse."""
    return ev.nomina_sesion(db, codigo)


@router.get("/en-vivo/{codigo}/estado")
def estado(codigo: str, db: Session = Depends(get_db)):
    return ev.estado(db, codigo)


@router.get("/en-vivo/{codigo}/mi-estado")
def mi_estado(codigo: str, participante_id: str, token: str, request: Request, db: Session = Depends(get_db)):
    ev.verificar_seb_o_error(db, ev._sesion(db, codigo), request)
    return ev.estado_participante(db, codigo, participante_id, token)


@router.get("/en-vivo/{codigo}/seb-config", dependencies=[Depends(req_profesor)])
def seb_config(codigo: str, request: Request, db: Session = Depends(get_db)):
    """Genera y descarga el archivo .seb (config de Safe Exam Browser) de la sala; guarda la
    config key para verificar que las peticiones vengan de SEB."""
    from app.services import seb_service
    s = ev._sesion(db, codigo)
    base = settings.public_app_url or request.headers.get("origin") or ""
    join_url = ev.join_url(s.codigo, base)
    xml, key = seb_service.generar_config(join_url)
    s.seb_config_key = key
    if not s.requiere_seb:
        s.requiere_seb = True                       # descargar el .seb activa la exigencia
    db.commit()
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", f"evalys_sala_{s.codigo}")[:60]
    return Response(content=xml, media_type="application/seb",
                    headers={"Content-Disposition": f'attachment; filename="{fn}.seb"'})


@router.get("/en-vivo/{codigo}/mi-resultado")
def mi_resultado(codigo: str, participante_id: str, token: str, db: Session = Depends(get_db)):
    return ev.mi_resultado(db, codigo, participante_id, token)


# ── integridad (LV8): telemetría del alumno + panel/cierre del docente ────────────────
@router.post("/en-vivo/{codigo}/evento")
def integridad_evento(codigo: str, payload: dict, db: Session = Depends(get_db)):
    """Ingesta de telemetría del ALUMNO (público, con token del participante). Acepta un lote
    de eventos de ventana/foco. Hora de servidor; inmutable."""
    from app.services import integridad_service
    s = ev._sesion(db, codigo)
    p = ev._participante(db, s, payload.get("participante_id"), payload.get("token", ""))
    eventos = payload.get("eventos")
    if eventos is None:                     # también acepta un evento suelto
        eventos = [{k: payload.get(k) for k in ("tipo", "question_number", "duration_ms", "sequence", "meta")}]
    return integridad_service.registrar_eventos(db, s, p, eventos)


@router.get("/en-vivo/{codigo}/integridad", dependencies=[Depends(req_profesor)])
def integridad_panel(codigo: str, db: Session = Depends(get_db)):
    """Panel de supervisión del DOCENTE: evidencia por alumno + semáforo (en vivo y final)."""
    from app.services import integridad_service
    s = ev._sesion(db, codigo)
    return integridad_service.resumen_participantes(db, s)


@router.get("/en-vivo/{codigo}/integridad/{participante_id}", dependencies=[Depends(req_profesor)])
def integridad_timeline(codigo: str, participante_id: str, db: Session = Depends(get_db)):
    """Línea temporal de incidencias de un alumno (evidencia detallada para decidir)."""
    from app.services import integridad_service
    s = ev._sesion(db, codigo)
    return integridad_service.timeline_participante(db, s, participante_id)


@router.post("/en-vivo/{codigo}/participante/{participante_id}/bloquear", dependencies=[Depends(req_profesor)])
def integridad_bloquear(codigo: str, participante_id: str, payload: dict | None = None,
                        db: Session = Depends(get_db)):
    """El DOCENTE cierra (o reabre) selectivamente la prueba a un alumno. Decisión humana."""
    from app.services import integridad_service
    payload = payload or {}
    s = ev._sesion(db, codigo)
    return integridad_service.bloquear(db, s, participante_id,
                                       bool(payload.get("bloquear", True)),
                                       payload.get("motivo"))
