"""
B9/B10 · Motor de logros de Runi (servidor). La evidencia = el Episodio de Aprendizaje Verificado.

Regla central (spec v3): una medalla exige XP acumulado Y una puerta de evidencia; los puntos por sí
solos nunca desbloquean. Anti-farming: acciones pasivas 0 XP, evidencia idéntica repetida no cuenta,
sin castigo por perder racha. El cliente solo REPRESENTA; el desbloqueo lo decide el servidor y queda
en un recibo inmutable (`MedalUnlock`).

Señales derivadas de las tablas reales: Episode (verificado/completo/started_at), ConfidenceObs
(confidence/correct), RetentionCheck (done/correct → comprobación diferida). Las señales aún no
instrumentadas (transferencia novel, apoyo entre pares validado, maestría longitudinal del curso)
quedan en 0 y su medalla permanece PENDIENTE con explicación honesta, nunca se inventan.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.episode import ConfidenceObs, Episode, RetentionCheck
from app.models.logros import MedalUnlock

_RULES = None


def _rules() -> dict:
    global _RULES
    if _RULES is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "progression_rules_v3.json")
        with open(path, "r", encoding="utf-8") as fh:
            _RULES = json.load(fh)
    return _RULES


# ── señales de evidencia (desde el EAV) ───────────────────────────────────────
def _signals(db: Session, pseudo_id: str) -> dict:
    eps = db.query(Episode).filter(Episode.pseudo_id == pseudo_id).all()
    obs = db.query(ConfidenceObs).filter(ConfidenceObs.pseudo_id == pseudo_id).all()
    checks = db.query(RetentionCheck).filter(RetentionCheck.pseudo_id == pseudo_id).all()

    verificados = sum(1 for e in eps if e.verificado)
    completos = sum(1 for e in eps if e.completo)
    dias_activos = len({(e.started_at.date() if e.started_at else None) for e in eps if e.started_at})
    checks_done = [c for c in checks if c.done_at is not None]
    checks_ok = [c for c in checks_done if c.correct]
    retencion = (len(checks_ok) / len(checks_done)) if checks_done else None

    # errores de alta confianza (conf≥80 e incorrecto) y su corrección posterior (mismo RA, obs correcta después)
    alta_conf_err = [o for o in obs if o.confidence >= 80 and o.correct is False]
    ras_err = {o.ra for o in alta_conf_err if o.ra}
    corregidos = 0
    for ra in ras_err:
        err_ts = min((o.created_at for o in alta_conf_err if o.ra == ra and o.created_at), default=None)
        if err_ts and any(o.ra == ra and o.correct is True and o.created_at and o.created_at > err_ts for o in obs):
            corregidos += 1

    # "duda valiente": marcó baja confianza (≤40) y aun así resultó correcta (reconocer la incertidumbre y resolverla)
    duda_valiente = sum(1 for o in obs if o.confidence <= 40 and o.correct is True)

    # F7 · señales de Maestría compartida (Pandilla), instrumentadas con anti-farming
    try:
        from app.services import pandilla_logros_service as pls
        sm = pls.senales(db, pseudo_id)
    except Exception:  # noqa: BLE001
        sm = {"validatedPeerSupports": 0, "sharedGroupGoalsCompleted": 0, "courseDefinedLongitudinalMastery": False}
    return {
        "verifiedLearningEpisodes": verificados,
        "completedEpisodes": completos,
        "activeDays": dias_activos,
        "delayedChecks": len(checks_done),
        "delayedChecksCorrect": len(checks_ok),
        "delayedRetentionPct": round(retencion * 100, 1) if retencion is not None else None,
        "correctedHighConfidenceErrors": corregidos,
        "resolvedUncertaintyEvents": duda_valiente,
        # Maestría compartida (F7) — reales
        "validatedPeerSupports": sm.get("validatedPeerSupports", 0),
        "sharedGroupGoalsCompleted": sm.get("sharedGroupGoalsCompleted", 0),
        "courseDefinedLongitudinalMastery": bool(sm.get("courseDefinedLongitudinalMastery", False)),
        # aún no instrumentadas (honestas en 0 → medalla pendiente, nunca inventada)
        "novelTransferCases": 0,
        "linkedConcepts": 0,
        "conceptsIntegrated": 0,
        "integratedOutcomes": 0,
        "weeklyPlanCompletionAtLeast80Percent": 0,
    }


_DIMS = None


def _dims_cat() -> list:
    """Catálogo v4 de las 7 dimensiones (id/label/color/earnsFrom). Cae a un default si falta el archivo."""
    global _DIMS
    if _DIMS is None:
        try:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "runi_v4", "universal-reward-dimensions.json")
            with open(path, "r", encoding="utf-8") as fh:
                _DIMS = json.load(fh).get("dimensions", [])
        except Exception:  # noqa: BLE001
            _DIMS = []
    return _DIMS


def dimensiones(sig: dict) -> list:
    """v4-F4 · reparte la evidencia REAL en las 7 dimensiones (cada una con su evidencia propia; NO se suman
    en una nota única ni forman ranking). Adaptador v3→v4: episodio/diferida/transfer→dominio, error alta conf
    corregido→valentía, apoyo validado/meta→comunidad. Las no instrumentadas quedan en 0 (honesto)."""
    puntos = {
        "mastery": sig["verifiedLearningEpisodes"] * 18 + sig["delayedChecks"] * 25,
        "courage": sig["correctedHighConfidenceErrors"] * 30 + sig["resolvedUncertaintyEvents"] * 15,
        "consistency": sig["activeDays"] * 12,
        "community": sig["validatedPeerSupports"] * 20 + sig["sharedGroupGoalsCompleted"] * 40,
        "curiosity": 0, "creation": 0, "integrity": 0,
    }
    instrumentadas = {"mastery", "courage", "consistency", "community"}
    ayuda = {
        "mastery": "Episodios verificados, retención diferida y transferencia.",
        "curiosity": "Preguntas productivas, hipótesis y exploración de fuentes (en preparación).",
        "consistency": "Sesiones planificadas y práctica distribuida en el tiempo.",
        "courage": "Declarar incertidumbre y corregir errores de alta confianza.",
        "community": "Apoyo entre pares validado y metas compartidas.",
        "creation": "Iteración de artefactos y soluciones originales (en preparación).",
        "integrity": "Citar fuentes, declarar límites y uso responsable de IA (en preparación).",
    }
    out = []
    for d in (_dims_cat() or []):
        did = d.get("id")
        out.append({"id": did, "label": d.get("label", did), "color": d.get("color", "#7785a3"),
                    "points": int(puntos.get(did, 0)), "instrumented": did in instrumentadas,
                    "earns": ayuda.get(did, "")})
    return out


def _xp(sig: dict) -> int:
    ev = _rules()["xpEvents"]
    vle = ev["verifiedLearningEpisode"]
    base_vle = (vle["min"] + vle["max"]) // 2   # 18 XP por episodio verificado (dentro del rango del spec)
    total = (sig["verifiedLearningEpisodes"] * base_vle
             + sig["delayedChecks"] * ev["delayedCheck"]
             + sig["correctedHighConfidenceErrors"] * ev["correctedHighConfidenceError"]
             + sig["novelTransferCases"] * ev["novelTransferCase"]
             + sig["validatedPeerSupports"] * ev["validatedPeerSupport"])
    return int(total)


# ── evaluación de la puerta de evidencia (por medalla) ───────────────────────
# etiqueta humana no punitiva + progreso 0..1 por condición
def _cond(sig: dict, key: str, need):
    """Devuelve (fraccion_cumplida_0a1, texto_humano, instrumentada)."""
    S = sig
    def frac(val, target):
        try:
            return max(0.0, min(1.0, float(val) / float(target))) if target else 1.0
        except Exception:  # noqa: BLE001
            return 0.0
    tbl = {
        "verifiedLearningEpisodes": lambda: (frac(S["verifiedLearningEpisodes"], need),
                                             f"Completa {need} episodios verificados (llevas {S['verifiedLearningEpisodes']})", True),
        "activeDays": lambda: (frac(S["activeDays"], need),
                               f"Estudia en {need} días distintos (llevas {S['activeDays']})", True),
        "resolvedUncertaintyEvents": lambda: (frac(S["resolvedUncertaintyEvents"], need),
                                              f"Resuelve {need} dudas que marcaste con baja confianza (llevas {S['resolvedUncertaintyEvents']})", True),
        "delayedChecks": lambda: (frac(S["delayedChecks"], need),
                                  f"Haz {need} repaso(s) diferido(s) (llevas {S['delayedChecks']})", True),
        "correctedHighConfidenceErrors": lambda: (frac(S["correctedHighConfidenceErrors"], need),
                                                  f"Corrige {need} error(es) que diste con alta confianza (llevas {S['correctedHighConfidenceErrors']})", True),
        "delayedRetentionAtLeast75Percent": lambda: ((1.0 if (S["delayedRetentionPct"] or 0) >= 75 else 0.0),
                                                     "Mantén ≥75% de retención en repasos a 7–21 días", True),
        "linkedConcepts": lambda: (0.0, f"Conecta {need} conceptos entre sí (en preparación)", False),
        "novelTransferCases": lambda: (0.0, f"Resuelve {need} caso(s) nuevo(s) de transferencia (en preparación)", False),
        "conceptsIntegrated": lambda: (0.0, f"Integra {need} conceptos en un resultado (en preparación)", False),
        "integratedOutcomes": lambda: (0.0, "Logra un resultado de aprendizaje integrado (en preparación)", False),
        "weeklyPlanCompletionAtLeast80Percent": lambda: (0.0, f"Cumple ≥80% de tu plan semanal en {need} semanas (en preparación)", False),
        "validatedPeerSupports": lambda: (frac(S["validatedPeerSupports"], need),
                                          f"Ayuda a {need} compañeros con validación (llevas {S['validatedPeerSupports']})", True),
        "sharedGroupGoalsCompleted": lambda: (frac(S["sharedGroupGoalsCompleted"], need),
                                             f"Completa {need} meta(s) grupal(es) con tu Pandilla (llevas {S['sharedGroupGoalsCompleted']})", True),
        "courseDefinedLongitudinalMastery": lambda: ((1.0 if S["courseDefinedLongitudinalMastery"] else 0.0),
                                                     "Alcanza la maestría longitudinal que define tu curso (la certifica tu docente)", True),
    }
    f = tbl.get(key)
    if not f:
        # condiciones auxiliares de una misma puerta (ej. delayDaysMin/Max) no cuentan como barra
        return None
    return f()


def _gate(sig: dict, gate: dict):
    """Evalúa la puerta: progreso 0..1 (mínimo entre condiciones instrumentadas), lista de faltantes, satisfecha?"""
    fracs, faltantes, satisfecha = [], [], True
    for k, need in gate.items():
        if k in ("delayDaysMin", "delayDaysMax"):
            continue
        r = _cond(sig, k, need)
        if r is None:
            continue
        fr, texto, instrumentada = r
        fracs.append(fr)
        if fr < 1.0:
            satisfecha = False
            faltantes.append(texto)
    prog = min(fracs) if fracs else 0.0
    return prog, faltantes, satisfecha


# ── estado completo (persiste desbloqueos con recibo inmutable) ──────────────
def estado(db: Session, pseudo_id: str) -> dict:
    if not pseudo_id:
        return {"ok": False, "error": "falta pseudo_id"}
    rules = _rules()
    sig = _signals(db, pseudo_id)
    xp = _xp(sig)
    ya = {u.medal_id: u for u in db.query(MedalUnlock).filter(MedalUnlock.pseudo_id == pseudo_id).all()}
    tiers_by_medal = {}
    for t in rules["tiers"]:
        for m in t["medals"]:
            tiers_by_medal[m] = {"id": t["id"], "label": t["label"]}
    medals_out = []
    nuevos = []
    for m in rules["medals"]:
        mid = m["id"]
        xp_need = m["xp"]
        xp_prog = min(1.0, xp / xp_need) if xp_need else 1.0
        g_prog, faltantes, g_ok = _gate(sig, m.get("gate", {}))
        elegible = (xp >= xp_need) and g_ok
        desbloqueada = mid in ya
        # persistir desbloqueo (una vez, inmutable) cuando es elegible
        if elegible and not desbloqueada:
            rec = MedalUnlock(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, medal_id=mid, slug=m["slug"],
                              rule_version=rules.get("version", "3.0.0"), xp_at_unlock=xp, evidence=sig)
            db.add(rec)
            try:
                db.commit()
                ya[mid] = rec
                desbloqueada = True
                nuevos.append(mid)
                # La medalla es el logro; el cofre y los Lumis son el reconocimiento. Van DESPUÉS
                # del recibo y nunca pueden tumbarlo (ver recompensa_service).
                from app.services import recompensa_service as _rw
                _rw.al_desbloquear_medalla(db, pseudo_id, mid, m["slug"])
            except Exception:  # noqa: BLE001
                db.rollback()
                desbloqueada = mid in ya
        progreso = 100 if desbloqueada else round(min(xp_prog, g_prog) * 100)
        faltan_xp = max(0, xp_need - xp)
        tier = tiers_by_medal.get(mid, {})
        medals_out.append({
            "id": mid, "slug": m["slug"], "tier": tier.get("id"), "tier_label": tier.get("label"),
            "xp_need": xp_need, "unlocked": desbloqueada, "eligible": elegible, "progress": progreso,
            "falta_xp": (0 if desbloqueada else faltan_xp),
            "falta_evidencia": ([] if desbloqueada else faltantes),
            "unlocked_at": (ya[mid].unlocked_at.isoformat() if mid in ya and ya[mid].unlocked_at else None),
        })
    # próxima medalla accionable (la de menor progreso aún no desbloqueada)
    pendientes = [x for x in medals_out if not x["unlocked"]]
    proxima = max(pendientes, key=lambda x: x["progress"]) if pendientes else None
    return {"ok": True, "rule_version": rules.get("version"), "xp": xp, "signals": sig,
            "dimensiones": dimensiones(sig),
            "tiers": rules["tiers"], "medals": medals_out,
            "desbloqueadas": sum(1 for x in medals_out if x["unlocked"]),
            "total": len(medals_out), "nuevas": nuevos,
            "proxima": ({"id": proxima["id"], "slug": proxima["slug"], "progress": proxima["progress"],
                         "falta_xp": proxima["falta_xp"], "falta_evidencia": proxima["falta_evidencia"]} if proxima else None)}
