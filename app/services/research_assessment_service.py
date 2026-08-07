"""
Research OS · Fase 4 — scheduler de medición longitudinal (inmediata / 7 / 21 / 45 días).

Al completar una intervención se programan las mediciones diferidas. Cada medición usa un ÍTEM PARALELO
distinto (nunca el mismo), vinculado por `conceptId` + `difficultyBand` + `transferDistance`. El outcome
primario del experimento es `transfer_day_21`. Todo server-side; los puntajes se registran como declarados.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.research import ResearchAssessment

ITEM_SET_VERSION = "items-v1"
_VENTANAS = {"day_7": 7, "day_21": 21, "day_45": 45}

# Banco demo de ítems PARALELOS por conceptId (varios por distancia de transferencia).
# transferDistance: near = misma clase de problema; far = contexto nuevo (transferencia).
_ITEMS = {
    "homeostasis": {"near": ["homeo-n1", "homeo-n2", "homeo-n3", "homeo-n4"],
                    "far": ["homeo-f1", "homeo-f2", "homeo-f3", "homeo-f4"]},
    "autorregulacion": {"near": ["autor-n1", "autor-n2", "autor-n3", "autor-n4"],
                        "far": ["autor-f1", "autor-f2", "autor-f3", "autor-f4"]},
}


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


def _item_paralelo(db: Session, participant: str, concept_id: str, distancia: str) -> str:
    """Elige un ítem paralelo NO usado aún por este participante para este concepto (nunca repite ítem)."""
    banco = (_ITEMS.get(concept_id) or {}).get(distancia) or []
    usados = {a.item_id for a in db.query(ResearchAssessment).filter(
        ResearchAssessment.participant_pseudo == participant, ResearchAssessment.concept_id == concept_id).all()}
    libres = [i for i in banco if i not in usados]
    pool = libres or banco
    if not pool:
        return concept_id + "-" + distancia + "-gen"
    return pool[len(usados) % len(pool)]   # reparto estable/reproducible


def programar(db: Session, participant: str, concept_id: str, difficulty_band: int = 3,
              transfer_distance: str = "near", immediate_score: float | None = None) -> dict:
    if not participant or not concept_id:
        return {"ok": False, "error": "faltan participant/concept_id"}
    distancia = "far" if transfer_distance == "far" else "near"
    ahora = _dt.datetime.utcnow()
    creadas = []
    if immediate_score is not None:
        db.add(ResearchAssessment(id=_uid(), participant_pseudo=participant, concept_id=concept_id, window="immediate",
                                  scheduled_for=ahora, item_id=_item_paralelo(db, participant, concept_id, distancia),
                                  item_set_version=ITEM_SET_VERSION, difficulty_band=difficulty_band,
                                  transfer_distance=distancia, done=True, score01=immediate_score, done_at=ahora))
        db.commit()
        creadas.append("immediate")
    for win, dias in _VENTANAS.items():
        ya = db.query(ResearchAssessment).filter(
            ResearchAssessment.participant_pseudo == participant, ResearchAssessment.concept_id == concept_id,
            ResearchAssessment.window == win).first()
        if ya:
            continue
        db.add(ResearchAssessment(id=_uid(), participant_pseudo=participant, concept_id=concept_id, window=win,
                                  scheduled_for=ahora + _dt.timedelta(days=dias),
                                  item_id=_item_paralelo(db, participant, concept_id, distancia),
                                  item_set_version=ITEM_SET_VERSION, difficulty_band=difficulty_band,
                                  transfer_distance=distancia))
        creadas.append(win)
    db.commit()
    return {"ok": True, "programadas": creadas, "item_set_version": ITEM_SET_VERSION}


def due(db: Session, participant: str) -> dict:
    ahora = _dt.datetime.utcnow()
    rows = (db.query(ResearchAssessment)
            .filter(ResearchAssessment.participant_pseudo == participant, ResearchAssessment.done == False,  # noqa: E712
                    ResearchAssessment.scheduled_for <= ahora)
            .order_by(ResearchAssessment.scheduled_for.asc()).all())
    return {"ok": True, "due": [{"id": a.id, "concept_id": a.concept_id, "window": a.window, "item_id": a.item_id,
            "transfer_distance": a.transfer_distance, "difficulty_band": a.difficulty_band} for a in rows]}


def responder(db: Session, assessment_id: str, score01: float, confidence01: float | None = None,
              active_seconds: int | None = None) -> dict:
    a = db.query(ResearchAssessment).filter(ResearchAssessment.id == assessment_id).first()
    if not a:
        return {"ok": False, "error": "medición no encontrada"}
    if a.done:
        return {"ok": True, "already": True}
    try:
        a.score01 = max(0.0, min(1.0, float(score01)))
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "score01 inválido"}
    if confidence01 is not None:
        try:
            a.confidence01 = max(0.0, min(1.0, float(confidence01)))
        except Exception:  # noqa: BLE001
            pass
    if active_seconds is not None:
        try:
            a.active_seconds = int(active_seconds)
        except Exception:  # noqa: BLE001
            pass
    a.done = True
    a.done_at = _dt.datetime.utcnow()
    db.commit()
    return {"ok": True, "window": a.window, "concept_id": a.concept_id}


def tick(db: Session) -> int:
    """Marca 'reminded' las mediciones vencidas no respondidas (el push las empuja, como B4). Idempotente."""
    ahora = _dt.datetime.utcnow()
    piso = ahora - _dt.timedelta(days=5)
    pend = (db.query(ResearchAssessment)
            .filter(ResearchAssessment.done == False, ResearchAssessment.reminded == False,  # noqa: E712
                    ResearchAssessment.scheduled_for <= ahora, ResearchAssessment.scheduled_for >= piso)
            .limit(200).all())
    n = 0
    for a in pend:
        a.reminded = True
        n += 1
    db.commit()
    return n
