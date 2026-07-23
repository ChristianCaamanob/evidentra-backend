"""
5º módulo · EXAMEN ORAL — router (F1: sesión + segmentos con transcripción literal).

F1 persiste la Capa 2 (transcripción literal por segmento "Respuesta N") y la referencia al
audio local (IndexedDB en el equipo del docente). Las capas 3 (normalización/síntesis) y la
evaluación por 4 criterios llegan en F2–F4. G1: nada se publica sin validación docente.
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.errors import not_found, conflict
from app.models.assessment import Assessment
from app.models.student import Student
from app.models.answer_key import AnswerKey, AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE
from app.models.examen_oral import (
    OralExamSesion, OralExamSegmento, OE_GRABANDO, OE_REVISION, OE_ESTADOS)

logger = logging.getLogger("evalys")
router = APIRouter(prefix="/oral-examen", tags=["examen-oral"])


def _nombre(st) -> str | None:
    return ((getattr(st, "apellido_paterno", "") or "") + " "
            + (getattr(st, "apellido_materno", "") or "") + " "
            + (getattr(st, "nombres", "") or "")).replace("  ", " ").strip() or None


def _preguntas(db, assessment_id) -> list:
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        return []
    items = [it for it in sorted(ak.items, key=lambda x: x.question_number)
             if it.question_type == QUESTION_TYPE_OPEN_RESPONSE]
    return [{"id": str(it.id), "numero": it.question_number, "enunciado": it.enunciado or "",
             "weight": float(it.weight or 1),
             "tiempo_reflexion_seg": getattr(it, "tiempo_reflexion_seg", None),
             "tiempo_max_seg": getattr(it, "tiempo_max_seg", None),
             "respuesta_optima": (it.respuesta_optima or it.correct_answer or ""),
             "conceptos_indispensables": getattr(it, "conceptos_indispensables", None) or "",
             "area_conocimiento": getattr(it, "area_conocimiento", None) or "general"}
            for it in items]


def _sesion_dict(s, db, incluir_segmentos=False) -> dict:
    st = db.get(Student, s.student_id) if s.student_id else None
    d = {"id": str(s.id), "assessment_id": s.assessment_id, "student_id": s.student_id,
         "rut": (getattr(st, "rut", None) if st else None), "nombre": _nombre(st) if st else None,
         "estado": s.estado, "evaluador": s.evaluador, "duracion_seg": s.duracion_seg,
         "nota_final": s.nota_final, "logro_pct": s.logro_pct,
         "n_segmentos": len(s.segmentos)}
    if incluir_segmentos:
        d["segmentos"] = [{
            "id": str(g.id), "pregunta_numero": g.pregunta_numero,
            "answer_key_item_id": g.answer_key_item_id,
            "t_inicio_ms": g.t_inicio_ms, "t_fin_ms": g.t_fin_ms,
            "transcripcion_literal": g.transcripcion_literal or "",
            "version_normalizada": g.version_normalizada or "",
            "sintesis_json": g.sintesis_json, "confianza": g.confianza,
            "sin_respuesta": g.sin_respuesta}
            for g in sorted(s.segmentos, key=lambda x: x.pregunta_numero)]
    return d


@router.get("/assessments/{assessment_id}/preguntas", dependencies=[Depends(req_profesor)])
def preguntas_oral(assessment_id: UUID, db: Session = Depends(get_db)):
    """Preguntas de la evaluación oral (reusa AnswerKeyItem open_response) + nómina del curso."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    roster = (db.query(Student).filter(Student.course_id == asm.course_id).all()
              if asm.course_id else [])
    return {"assessment_id": str(assessment_id), "prueba": asm.name,
            "escala": asm.grading_scale or "chile_1_7",
            "exigencia": asm.passing_threshold if asm.passing_threshold is not None else 60.0,
            "preguntas": _preguntas(db, assessment_id),
            "nomina": [{"student_id": str(st.id), "rut": st.rut, "nombre": _nombre(st)}
                       for st in roster]}


@router.post("/assessments/{assessment_id}/sesion", dependencies=[Depends(req_profesor)])
def crear_o_abrir_sesion(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Crea (o reabre) la sesión de examen oral de un estudiante. payload = {student_id, evaluador?,
    config?}."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    sid = str(payload.get("student_id") or "").strip()
    if not sid:
        raise conflict("Falta el estudiante.")
    s = (db.query(OralExamSesion)
         .filter(OralExamSesion.assessment_id == str(assessment_id),
                 OralExamSesion.student_id == sid).first())
    if not s:
        s = OralExamSesion(assessment_id=str(assessment_id), student_id=sid,
                           evaluador=(payload.get("evaluador") or "docente")[:120],
                           config_json=payload.get("config"))
        db.add(s)
    else:
        if payload.get("config") is not None:
            s.config_json = payload.get("config")
    db.commit(); db.refresh(s)
    return {"sesion": _sesion_dict(s, db, incluir_segmentos=True),
            "preguntas": _preguntas(db, assessment_id)}


@router.post("/sesion/{sesion_id}/segmentos", dependencies=[Depends(req_profesor)])
def guardar_segmentos(sesion_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Persiste (upsert por pregunta) los segmentos con la TRANSCRIPCIÓN LITERAL (Capa 2) y sus
    marcas de tiempo. payload = {estado?, duracion_seg?, audio_ref?, segmentos:[{pregunta_numero,
    item_id?, t_inicio_ms?, t_fin_ms?, transcripcion_literal, sin_respuesta?}]}."""
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    if payload.get("estado") in OE_ESTADOS:
        s.estado = payload["estado"]
    if payload.get("duracion_seg") is not None:
        try:
            s.duracion_seg = float(payload["duracion_seg"])
        except (TypeError, ValueError):
            pass
    if payload.get("audio_ref"):
        s.audio_ref = str(payload["audio_ref"])[:255]
    segs = payload.get("segmentos") or []
    nums = {int(x.get("pregunta_numero") or 0) for x in segs}
    if nums:
        db.query(OralExamSegmento).filter(
            OralExamSegmento.sesion_id == str(sesion_id),
            OralExamSegmento.pregunta_numero.in_(nums)).delete(synchronize_session=False)
    n = 0
    for x in segs:
        db.add(OralExamSegmento(
            sesion_id=s.id, pregunta_numero=int(x.get("pregunta_numero") or 0),
            answer_key_item_id=(str(x["item_id"]) if x.get("item_id") else None),
            t_inicio_ms=(int(x["t_inicio_ms"]) if x.get("t_inicio_ms") is not None else None),
            t_fin_ms=(int(x["t_fin_ms"]) if x.get("t_fin_ms") is not None else None),
            transcripcion_literal=((x.get("transcripcion_literal") or "").strip() or None),
            sin_respuesta=bool(x.get("sin_respuesta"))))
        n += 1
    db.commit(); db.refresh(s)
    return {"ok": True, "n_segmentos": n, "sesion": _sesion_dict(s, db, incluir_segmentos=True)}


@router.get("/assessments/{assessment_id}/sesiones", dependencies=[Depends(req_profesor)])
def listar_sesiones(assessment_id: UUID, db: Session = Depends(get_db)):
    ses = (db.query(OralExamSesion)
           .filter(OralExamSesion.assessment_id == str(assessment_id)).all())
    return {"assessment_id": str(assessment_id),
            "sesiones": [_sesion_dict(s, db) for s in ses]}


@router.get("/sesion/{sesion_id}", dependencies=[Depends(req_profesor)])
def obtener_sesion(sesion_id: UUID, db: Session = Depends(get_db)):
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    return _sesion_dict(s, db, incluir_segmentos=True)
