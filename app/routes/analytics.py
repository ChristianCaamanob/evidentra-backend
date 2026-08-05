"""
B1 + B2 — Ingesta de eventos (esquema estricto) + motor del Episodio de Aprendizaje Verificado.

Todo aditivo y no destructivo. Estudiantes (sin login) emiten con `pseudo_id`; las métricas son
solo lectura y quedan tras el rol docente/creador.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.ratelimit import limit
from app.services import analytics_service as ans
from app.services import episode_service as eps

router = APIRouter(tags=["analytics-episodios"])


# ── B2 · Eventos ───────────────────────────────────────────────────────────────
@router.post("/analytics/event")
@limit("120/minute")
def analytics_event(request: Request, payload: dict, db: Session = Depends(get_db)):
    return ans.ingest(db, payload or {})


@router.post("/analytics/events")
@limit("60/minute")
def analytics_events(request: Request, payload: dict, db: Session = Depends(get_db)):
    return ans.ingest_batch(db, (payload or {}).get("eventos") or [])


# ── B1 · Episodios ──────────────────────────────────────────────────────────────
@router.post("/episodes/start")
@limit("60/minute")
def episode_start(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return eps.start(db, p.get("pseudo_id", ""), p.get("course_id", ""), p.get("ra", ""),
                     p.get("objetivo", ""), p.get("origen", ""))


@router.post("/episodes/observe")
@limit("120/minute")
def episode_observe(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return eps.observe(db, p.get("episode_id"), p.get("obs") or p)


@router.post("/episodes/feedback")
@limit("120/minute")
def episode_feedback(request: Request, payload: dict, db: Session = Depends(get_db)):
    return eps.feedback(db, (payload or {}).get("episode_id"))


@router.post("/episodes/close")
@limit("60/minute")
def episode_close(request: Request, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return eps.close(db, p.get("episode_id"), p.get("sintesis", ""), p.get("check_immediate"),
                     p.get("programar_diferida", "7d"))


@router.post("/episodes/diferida/{check_id}")
@limit("60/minute")
def episode_diferida(request: Request, check_id: str, payload: dict, db: Session = Depends(get_db)):
    return eps.responder_diferida(db, check_id, bool((payload or {}).get("correct")))


@router.get("/episodes/pendientes")
def episode_pendientes(pseudo_id: str = "", db: Session = Depends(get_db)):
    return eps.pendientes_diferidas(db, pseudo_id)


@router.get("/episodes/mi-progreso")
def episode_mi_progreso(pseudo_id: str = "", db: Session = Depends(get_db)):
    return eps.mi_progreso(db, pseudo_id)


# ── B12 · Consentimiento + privacidad (versionado, revocable) ────────────────────
@router.get("/alumno/consent")
def consent_estado(pseudo_id: str = "", db: Session = Depends(get_db)):
    from app.services import consent_service as cs
    return cs.estado(db, pseudo_id)


@router.post("/alumno/consent")
@limit("30/minute")
def consent_aceptar(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import consent_service as cs
    p = payload or {}
    return cs.aceptar(db, p.get("pseudo_id", ""), p.get("scope", "social,analitica"), p.get("quiz_score"))


@router.post("/alumno/consent/revocar")
@limit("30/minute")
def consent_revocar(request: Request, payload: dict, db: Session = Depends(get_db)):
    from app.services import consent_service as cs
    return cs.revocar(db, (payload or {}).get("pseudo_id", ""))


@router.get("/episodes/metricas", dependencies=[Depends(req_profesor)])
def episode_metricas(course_id: str = "", dias: int = 7, db: Session = Depends(get_db)):
    return eps.metricas(db, course_id or None, dias)


@router.get("/episodes/resumen-docente", dependencies=[Depends(req_profesor)])
def episode_resumen_docente(course: str = "", dias: int = 14, db: Session = Depends(get_db)):
    return eps.resumen_docente(db, course, dias)
