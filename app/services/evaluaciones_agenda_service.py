"""
Evaluaciones de la agenda (v2.0): CRUD por curso (docente) + lectura pública por código de agente Runi (alumno).
"""
from __future__ import annotations

import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.evaluacion_agenda import EvaluacionAgenda

_TIPO_COLOR = {"prueba": "#ff6b81", "certamen": "#ff6b81", "examen": "#e21e2b",
               "entrega": "#f0954a", "taller": "#9d7cff", "control": "#f6bd60"}


def _norm_fecha(v) -> str:
    s = str(v or "").strip()[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else ""


def _norm_hora(v) -> str:
    s = re.sub(r"[^0-9:]", "", str(v or ""))
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2))
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else ""


def _dict(e: EvaluacionAgenda) -> dict:
    return {"id": str(e.id), "titulo": e.titulo, "fecha": e.fecha, "hora": e.hora,
            "tipo": e.tipo, "ponderacion": e.ponderacion, "detalle": e.detalle, "color": e.color}


def crear(db: Session, course_id, payload: dict) -> dict:
    p = payload or {}
    fecha = _norm_fecha(p.get("fecha"))
    titulo = str(p.get("titulo") or "").strip()[:200]
    if not titulo or not fecha:
        raise unprocessable("La evaluación necesita al menos título y fecha (YYYY-MM-DD).")
    tipo = (str(p.get("tipo") or "prueba").strip().lower()[:40]) or "prueba"
    e = EvaluacionAgenda(
        course_id=course_id, titulo=titulo, fecha=fecha, hora=_norm_hora(p.get("hora")) or None,
        tipo=tipo, ponderacion=(str(p.get("ponderacion") or "").strip()[:20] or None),
        detalle=(str(p.get("detalle") or "").strip()[:400] or None),
        color=(_TIPO_COLOR.get(tipo) or "#ff6b81"))
    db.add(e); db.commit()
    return {"ok": True, "evaluacion": _dict(e)}


def listar(db: Session, course_id) -> dict:
    filas = db.query(EvaluacionAgenda).filter(EvaluacionAgenda.course_id == course_id).all()
    return {"ok": True, "evaluaciones": sorted([_dict(e) for e in filas], key=lambda x: (x["fecha"], x["hora"] or ""))}


def eliminar(db: Session, eval_id) -> dict:
    try:
        eid = _uuid.UUID(str(eval_id))
    except (ValueError, TypeError):
        raise not_found("Evaluación no válida.")
    e = db.query(EvaluacionAgenda).filter(EvaluacionAgenda.id == eid).first()
    if not e:
        raise not_found("Evaluación no encontrada.")
    db.delete(e); db.commit()
    return {"ok": True}


def listar_por_silabo(db: Session, codigo: str) -> dict:
    """Lectura pública para el alumno: por el código del agente Runi → curso → evaluaciones futuras/recientes."""
    from app.services import silabo_service as sil
    a = sil.agente_por_codigo(db, codigo)
    try:
        cid = _uuid.UUID(str(a.course_id))
    except Exception:  # noqa: BLE001
        return {"ok": True, "evaluaciones": []}
    return listar(db, cid)
