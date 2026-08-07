"""
Research OS · Fase 6 — panel investigador (agregación server-side, separada del panel docente).

Reglas: mostrar n junto a cada estimación; **suprimir grupos pequeños** (umbral configurable); intervalos
de confianza donde aplique; sin rankings individuales ni inferencias con n pequeño. Consume datos REALES de
las tablas research_*; si no hay datos, devuelve estado vacío explícito (nunca cifras simuladas).
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.models.research import (ResearchAIReview, ResearchAssessment, ResearchAssignment, ResearchConsent,
                                 ResearchDeviation, ResearchEvent, ResearchParticipant)

SUPRESION = 5   # umbral de supresión de grupos pequeños (configurable)


def _mean_ci(vals: list) -> dict | None:
    """Media + IC95% (normal). Devuelve None si n=0."""
    n = len(vals)
    if n == 0:
        return None
    m = sum(vals) / n
    if n < 2:
        return {"n": n, "mean": round(m, 3), "ci_low": None, "ci_high": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "mean": round(m, 3), "ci_low": round(max(0.0, m - 1.96 * se), 3),
            "ci_high": round(min(1.0, m + 1.96 * se), 3)}


def _supr(stat: dict | None, thr: int = SUPRESION) -> dict:
    """Aplica supresión: si n < umbral, oculta la estimación (solo deja n y una marca)."""
    if not stat:
        return {"n": 0, "suppressed": True}
    if stat.get("n", 0) < thr:
        return {"n": stat["n"], "suppressed": True, "nota": "n<" + str(thr)}
    return {**stat, "suppressed": False}


def resumen(db: Session, thr: int = SUPRESION) -> dict:
    # 1 · Salud del estudio
    n_part = db.query(ResearchParticipant).count()
    consents = db.query(ResearchConsent).all()
    por_estado = {}
    for c in consents:
        por_estado[c.state] = por_estado.get(c.state, 0) + 1
    n_events = db.query(ResearchEvent).count()
    desv = db.query(ResearchDeviation).all()
    por_desv = {}
    for d in desv:
        por_desv[d.kind] = por_desv.get(d.kind, 0) + 1
    salud = {"participantes": n_part, "consentimiento": por_estado, "eventos": n_events,
             "desviaciones": por_desv, "consentidos": por_estado.get("consented", 0)}

    # 2 · Exposición (condición asignada) — n por condición, sin ranking
    asigs = db.query(ResearchAssignment).all()
    por_cond = {}
    for a in asigs:
        por_cond[a.condition_id] = por_cond.get(a.condition_id, 0) + 1
    exposicion = {"asignaciones": len(asigs), "por_condicion": por_cond}

    # 3 · Aprendizaje / retención / transferencia — media + IC + supresión por ventana
    asmts = db.query(ResearchAssessment).filter(ResearchAssessment.done == True).all()  # noqa: E712
    por_ventana = {}
    for w in ("immediate", "day_7", "day_21", "day_45"):
        vals = [a.score01 for a in asmts if a.window == w and a.score01 is not None]
        por_ventana[w] = _supr(_mean_ci(vals), thr)
    transfer = [a.score01 for a in asmts if a.window == "day_21" and a.transfer_distance == "far" and a.score01 is not None]
    aprendizaje = {"por_ventana": por_ventana, "transfer_day_21": _supr(_mean_ci(transfer), thr),
                   "outcome_primario": "transfer_day_21"}

    # 4 · IA evaluadora (teach_runi) — acuerdo, abstenciones, revisiones
    revs = db.query(ResearchAIReview).all()
    n_scored = sum(1 for r in revs if r.ai_decision == "scored")
    n_abst = sum(1 for r in revs if r.ai_decision == "needs_human_review")
    revisados = [r for r in revs if r.human_verdict]
    n_agree = sum(1 for r in revisados if r.human_verdict == "agree")
    ia = {"total": len(revs), "puntuadas": n_scored, "abstenciones": n_abst,
          "revisadas_por_humano": len(revisados),
          "acuerdo_humano": _supr(_mean_ci([1.0 if r.human_verdict == "agree" else 0.0 for r in revisados]), thr)}

    # 9 · Versiones (trazabilidad)
    versiones = {
        "app": sorted({e.app_version for e in db.query(ResearchEvent).all() if e.app_version}),
        "esquema_evento": "1.0.0",
        "rubrica_teach": sorted({r.rubric_version for r in revs if r.rubric_version}),
        "item_set": sorted({a.item_set_version for a in db.query(ResearchAssessment).all() if a.item_set_version}),
        "modelo_ia": sorted({r.model_version for r in revs if r.model_version}),
    }

    return {"ok": True, "supresion_umbral": thr,
            "salud": salud, "exposicion": exposicion, "aprendizaje": aprendizaje, "ia": ia, "versiones": versiones,
            "nota": "Sin rankings individuales. Toda estimación incluye n; los grupos con n<" + str(thr) + " se suprimen."}
