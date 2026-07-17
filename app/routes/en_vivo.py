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
def informe_export(codigo: str, formato: str, db: Session = Depends(get_db)):
    """Descarga el informe de la sala en Word/PDF/Excel (psicométrico + por RA)."""
    if formato not in ("docx", "pdf", "xlsx"):
        from app.core.errors import unprocessable
        raise unprocessable("Formato no soportado (docx | pdf | xlsx).")
    payload = ev.informe_payload(db, codigo, formato)
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


# ── participantes (publico) ──────────────────────────────────────────────────────────
@router.post("/en-vivo/{codigo}/unir")
def unir(codigo: str, payload: dict, db: Session = Depends(get_db)):
    p = ev.unir(db, codigo, payload.get("alias", ""), payload.get("student_id"))
    return {"participante_id": str(p.id), "token": p.token, "alias": p.alias}


@router.post("/en-vivo/{codigo}/responder")
def responder(codigo: str, payload: dict, db: Session = Depends(get_db)):
    return ev.responder(db, codigo, payload.get("participante_id"),
                        payload.get("token", ""), respuesta=payload.get("respuesta"),
                        opcion_idx=payload.get("opcion_idx"))


@router.get("/en-vivo/{codigo}/estado")
def estado(codigo: str, db: Session = Depends(get_db)):
    return ev.estado(db, codigo)


@router.get("/en-vivo/{codigo}/mi-estado")
def mi_estado(codigo: str, participante_id: str, token: str, db: Session = Depends(get_db)):
    return ev.estado_participante(db, codigo, participante_id, token)


@router.get("/en-vivo/{codigo}/mi-resultado")
def mi_resultado(codigo: str, participante_id: str, token: str, db: Session = Depends(get_db)):
    return ev.mi_resultado(db, codigo, participante_id, token)
