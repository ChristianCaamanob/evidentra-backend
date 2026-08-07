"""
Research OS · Fase 3 — modalidad `teach_runi` (el estudiante le EXPLICA a Runi).

Runi hace una pregunta aclaratoria y evalúa la explicación con una **rúbrica versionada**. La IA puede
ABSTENERSE (`needs_human_review`) cuando su incertidumbre supera el umbral; una muestra + TODAS las
abstenciones van a revisión humana ciega. La IA NUNCA modifica calificaciones oficiales: esto es evidencia
de investigación (research_ai_reviews), separada de la evaluación académica.
"""
from __future__ import annotations

import json
import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.research import ResearchAIReview

RUBRIC_VERSION = "teach-runi-v1"
PROMPT_VERSION = "v1"
_ABSTAIN_THRESHOLD = 0.35   # incertidumbre ≥ umbral → needs_human_review
_MODEL = "claude-opus-4-8"

# Rúbrica versionada: 4 criterios 0–1
_CRITERIOS = ["exactitud", "completitud", "claridad", "uso_de_terminos"]


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


def _json_robusto(txt: str) -> dict | None:
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


def _juez(tema: str, explicacion: str, contexto: str = "") -> dict:
    """Juez LLM (reusa el patrón de B11). Devuelve criterios 0–1, incertidumbre, pregunta aclaratoria."""
    from app.services import correccion_experta_service as ce
    system = (
        "Eres un evaluador pedagógico experto y calibrado. El estudiante EXPLICA un tema (modalidad 'enséñale a "
        "Runi'). Evalúa la explicación con una rúbrica de 4 criterios, cada uno 0.0–1.0: exactitud (¿es correcto?), "
        "completitud (¿cubre lo esencial?), claridad (¿se entiende?), uso_de_terminos (¿usa el vocabulario adecuado?). "
        "Sé HONESTO con tu incertidumbre: si la explicación es ambigua, muy breve, fuera de tema o no puedes juzgarla "
        "con confianza, sube 'incertidumbre'. Formula UNA pregunta aclaratoria breve que ayude al estudiante a "
        'profundizar. Devuelve SOLO JSON: {"exactitud":0-1,"completitud":0-1,"claridad":0-1,"uso_de_terminos":0-1,'
        '"incertidumbre":0-1,"pregunta_aclaratoria":"≤160 car","justificacion":"≤200 car"}.'
    )
    user = ("TEMA: " + (tema or "(sin tema)") + "\n\n"
            + ("CONTEXTO DEL CURSO:\n" + contexto + "\n\n" if contexto else "")
            + "EXPLICACIÓN DEL ESTUDIANTE:\n" + (explicacion or "(vacía)"))
    crudo = ce._llamar_anthropic(system, user, max_tokens=400)
    d = _json_robusto(crudo) or {}
    return d


def evaluar(db: Session, participant: str, concept_id: str, tema: str, explicacion: str, contexto: str = "") -> dict:
    if not participant or not (explicacion or "").strip():
        return {"ok": False, "error": "falta participante o explicación"}
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # sin modelo → se abstiene y escala a humano (nunca inventa un puntaje)
        rev = _guardar(db, participant, concept_id, None, 1.0, {}, "needs_human_review", True)
        return {"ok": True, "aiDecision": "needs_human_review", "humanReviewRequired": True,
                "clarifyingQuestion": "¿Puedes desarrollar tu explicación con un ejemplo?", "reviewId": rev.id}
    try:
        d = _juez(tema, explicacion, contexto)
    except Exception:  # noqa: BLE001
        rev = _guardar(db, participant, concept_id, None, 1.0, {}, "needs_human_review", True)
        return {"ok": True, "aiDecision": "needs_human_review", "humanReviewRequired": True,
                "clarifyingQuestion": "¿Puedes desarrollar tu explicación con un ejemplo?", "reviewId": rev.id}
    crit = {}
    for k in _CRITERIOS:
        try:
            crit[k] = max(0.0, min(1.0, float(d.get(k, 0))))
        except Exception:  # noqa: BLE001
            crit[k] = 0.0
    try:
        incert = max(0.0, min(1.0, float(d.get("incertidumbre", 1.0))))
    except Exception:  # noqa: BLE001
        incert = 1.0
    score = round(sum(crit.values()) / len(_CRITERIOS), 3)
    abstiene = incert >= _ABSTAIN_THRESHOLD
    decision = "needs_human_review" if abstiene else "scored"
    rev = _guardar(db, participant, concept_id, (None if abstiene else score), incert, crit, decision, abstiene)
    return {"ok": True, "aiDecision": decision, "score01": (None if abstiene else score),
            "criterionScores": crit, "uncertainty01": incert, "humanReviewRequired": abstiene,
            "clarifyingQuestion": str(d.get("pregunta_aclaratoria", ""))[:160],
            "justificacion": str(d.get("justificacion", ""))[:200], "reviewId": rev.id,
            "rubricVersion": RUBRIC_VERSION}


def _guardar(db, participant, concept_id, score, incert, crit, decision, human_req) -> ResearchAIReview:
    rev = ResearchAIReview(id=_uid(), participant_pseudo=participant, concept_id=(concept_id or ""),
                           modality="teach_runi", ai_decision=decision, score01=score, uncertainty01=incert,
                           criterion_scores=crit, rubric_version=RUBRIC_VERSION, model_version=_MODEL,
                           prompt_version=PROMPT_VERSION, human_review_required=human_req)
    db.add(rev)
    db.commit()
    return rev


# ── revisión humana ciega (docente) ──────────────────────────────────────────
def pendientes_revision(db: Session, limite: int = 50) -> dict:
    rs = (db.query(ResearchAIReview)
          .filter(ResearchAIReview.human_review_required == True, ResearchAIReview.human_verdict.is_(None))  # noqa: E712
          .order_by(ResearchAIReview.created_at.asc()).limit(limite).all())
    return {"ok": True, "pendientes": [{"id": r.id, "concept_id": r.concept_id, "ai_decision": r.ai_decision,
            "uncertainty01": r.uncertainty01, "criterion_scores": r.criterion_scores,
            "created_at": r.created_at.isoformat() if r.created_at else None} for r in rs]}


def revisar(db: Session, review_id: str, verdict: str, score01: float | None, quien: str = "") -> dict:
    import datetime as _dt
    r = db.query(ResearchAIReview).filter(ResearchAIReview.id == review_id).first()
    if not r:
        return {"ok": False, "error": "revisión no encontrada"}
    if verdict not in ("agree", "adjust", "reject"):
        return {"ok": False, "error": "verdict inválido"}
    r.human_verdict = verdict
    if score01 is not None:
        try:
            r.human_score01 = max(0.0, min(1.0, float(score01)))
        except Exception:  # noqa: BLE001
            pass
    r.reviewed_by = quien or None
    r.reviewed_at = _dt.datetime.utcnow()
    db.commit()
    return {"ok": True, "verdict": verdict}
