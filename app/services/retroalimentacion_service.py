"""
Fase 4 (módulo F · corrección de desarrollo) — Informe de retroalimentación que CRUZA la
Tabla de Especificaciones (RA / competencia / unidad) con el desempeño del estudiante.

Flujo (por estudiante):
  1) corrige cada respuesta con el motor experto (Fase 3, correccion_experta_service);
  2) mapea cada pregunta a su RA (AnswerKeyItem.learning_outcome_id → LearningOutcome.text),
     con caída a 'unidad' y luego 'General';
  3) agrega por RA (puntaje, nivel, brechas unidas);
  4) SINTETIZA un informe empático y propositivo con estrategias de estudio basadas en
     evidencia POR RA, para lograr el resultado de aprendizaje.

Doctrina: G1 — la IA PROPONE la retroalimentación; el docente la valida/edita. G2 —
seudonimizado. En áreas jurisdiccionales/consenso, se hereda la transparencia de Fase 3.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

from app.models.answer_key import QUESTION_TYPE_OPEN_RESPONSE
from app.models.curriculo import LearningOutcome
from app.services import correccion_experta_service as ce

_ORDEN_NIVEL = {"no_logrado": 0, "parcial": 1, "logrado": 2}
_NIVEL_INV = {0: "no_logrado", 1: "parcial", 2: "logrado"}


def _mapa_ra(db, course_id) -> dict:
    """code → {texto, unidad} para el curso (Tabla de Especificaciones / programa)."""
    m = {}
    if not course_id:
        return m
    for lo in db.query(LearningOutcome).filter(LearningOutcome.course_id == course_id).all():
        m[(lo.code or "").strip()] = {"texto": lo.text or "", "unidad": lo.unidad or ""}
    return m


def _clave_ra(it, ra_map) -> tuple[str, str, str]:
    """Devuelve (clave, etiqueta_ra, unidad) para agrupar la pregunta por RA/unidad/General."""
    code = (getattr(it, "learning_outcome_id", None) or "").strip()
    if code:
        info = ra_map.get(code, {})
        etiqueta = (code + " · " + info.get("texto", "")).strip(" ·") if info.get("texto") else code
        return ("ra:" + code, etiqueta, info.get("unidad") or (getattr(it, "unidad", None) or ""))
    uni = (getattr(it, "unidad", None) or "").strip()
    if uni:
        return ("uni:" + uni, "Unidad: " + uni, uni)
    return ("general", "General (sin RA declarado)", "")


def _sintetizar(por_ra: list, estudiante: str, llamar=None) -> dict:
    """Un solo llamado al modelo: informe global empático + estrategias por RA (evidencia)."""
    if llamar is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    resumen = [{"ra": g["ra"], "unidad": g["unidad"], "nivel": g["nivel"],
                "puntaje_pct": g["puntaje_pct"], "brechas": g["brechas"]} for g in por_ra]
    system = (
        "Eres un tutor académico experto y empático. Redactas retroalimentación para un "
        "estudiante seudonimizado a partir de su desempeño por resultado de aprendizaje (RA). "
        "PROPONES; el docente valida. Sé cálido, concreto y propositivo. Las estrategias de "
        "estudio deben ser EFICIENTES y basadas en evidencia (p. ej. práctica de recuperación, "
        "repaso espaciado, autoexplicación, intercalado, ejemplos trabajados), aterrizadas al RA. "
        "Responde SOLO con un objeto JSON.")
    user = (
        "DESEMPEÑO POR RA (Tabla de Especificaciones cruzada con la prueba):\n"
        + json.dumps(resumen, ensure_ascii=False, indent=1)
        + "\n\nDevuelve SOLO este JSON:\n"
        "{\n"
        '  "mensaje_global": "<2-4 frases cálidas: fortalezas primero, luego foco de mejora>",\n'
        '  "por_ra": [{"ra": "<etiqueta del RA tal cual>", "sintesis": "<1-2 frases del logro/brecha>", '
        '"estrategias": ["<estrategia concreta basada en evidencia para lograr ESTE RA>", "..."]}],\n'
        '  "siguiente_paso": "<la acción de estudio más rentable ahora, en una frase>"\n'
        "}")
    try:
        crudo = (llamar or ce._llamar_anthropic)(system, user)
        t = crudo.strip(); i, j = t.find("{"), t.rfind("}")
        d = json.loads(t[i:j + 1])
        # Indexa estrategias por RA para fusionarlas en la salida.
        idx = {}
        for r in (d.get("por_ra") or []):
            idx[str(r.get("ra", "")).strip()] = {
                "sintesis": str(r.get("sintesis", ""))[:600],
                "estrategias": ce._lista(r.get("estrategias"), 5)}
        return {"mensaje_global": str(d.get("mensaje_global", ""))[:1200],
                "siguiente_paso": str(d.get("siguiente_paso", ""))[:400],
                "por_ra_idx": idx}
    except Exception as e:
        logger.warning("Síntesis Fase 4 falló: %s", f"{type(e).__name__}: {e}"[:200])
        return {}


def generar_informe(db, assessment, respuestas: list, estudiante: str = "Estudiante", llamar=None) -> dict:
    """
    respuestas = [{item_id, respuesta}]. Devuelve el informe cruzado por RA (Fase 4).
    `llamar` inyectable para tests. Sin API key → disponible=False (no rompe).
    """
    from app.models.answer_key import AnswerKey, AnswerKeyItem
    if llamar is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "disponible": False,
                "error": "El informe de retroalimentación necesita el motor de IA (ANTHROPIC_API_KEY)."}

    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment.id).first()
    if not ak:
        return {"ok": False, "disponible": True, "error": "La evaluación no tiene pauta."}
    items_by_id = {str(it.id): it for it in ak.items if it.question_type == QUESTION_TYPE_OPEN_RESPONSE}
    ra_map = _mapa_ra(db, getattr(assessment, "course_id", None))

    grupos: dict[str, dict] = {}
    n_corr = 0
    transparencias = set()
    for r in respuestas:
        it = items_by_id.get(str(r.get("item_id")))
        resp = (r.get("respuesta") or "").strip()
        if not it or not resp:
            continue
        cfg = {"enunciado": it.enunciado or "",
               "respuesta_optima": (it.respuesta_optima or it.correct_answer or ""),
               "nivel_rigor": getattr(it, "nivel_rigor", None) or "estricto",
               "area_conocimiento": getattr(it, "area_conocimiento", None) or "general",
               "fuente_estandar": getattr(it, "fuente_estandar", None) or "",
               "criterios": [{"name": c.name, "descriptor": c.descriptor} for c in (it.rubric_criteria or [])]}
        res = ce.corregir(resp, cfg, llamar=llamar)
        if not res.get("ok"):
            continue
        p = res["propuesta"]; n_corr += 1
        clave, etiqueta, unidad = _clave_ra(it, ra_map)
        g = grupos.setdefault(clave, {"ra": etiqueta, "unidad": unidad, "preguntas": [],
                                      "puntajes": [], "niveles": [], "brechas": []})
        g["preguntas"].append(it.question_number)
        g["puntajes"].append(float(p.get("puntaje_sugerido") or 0))
        g["niveles"].append(_ORDEN_NIVEL.get(p.get("nivel_global"), 1))
        g["brechas"].extend(p.get("brechas") or [])
        if p.get("naturaleza_estandar") == "C" and p.get("transparencia"):
            transparencias.add(p["transparencia"])

    if not n_corr:
        return {"ok": False, "disponible": True,
                "error": "No hubo respuestas corregibles (revisa item_id y textos)."}

    por_ra = []
    for g in grupos.values():
        pj = sum(g["puntajes"]) / len(g["puntajes"]) if g["puntajes"] else 0.0
        nv = _NIVEL_INV.get(round(sum(g["niveles"]) / len(g["niveles"])) if g["niveles"] else 1, "parcial")
        # deduplica brechas conservando orden
        vis, uniq = set(), []
        for b in g["brechas"]:
            k = b.strip().lower()
            if k and k not in vis:
                vis.add(k); uniq.append(b)
        por_ra.append({"ra": g["ra"], "unidad": g["unidad"],
                       "preguntas": sorted(set(g["preguntas"])),
                       "puntaje_pct": round(pj * 100), "nivel": nv, "brechas": uniq[:6]})
    por_ra.sort(key=lambda x: x["puntaje_pct"])   # lo más débil primero (foco de mejora)

    sint = _sintetizar(por_ra, estudiante, llamar=llamar)
    idx = sint.get("por_ra_idx", {})
    for g in por_ra:
        extra = idx.get(g["ra"].strip(), {})
        g["sintesis"] = extra.get("sintesis", "")
        g["estrategias"] = extra.get("estrategias", [])

    puntaje_global = round(sum(g["puntaje_pct"] for g in por_ra) / len(por_ra))
    return {
        "ok": True, "disponible": True, "estudiante": estudiante,
        "n_preguntas": n_corr, "n_ra": len(por_ra), "puntaje_global_pct": puntaje_global,
        "mensaje_global": sint.get("mensaje_global", ""),
        "siguiente_paso": sint.get("siguiente_paso", ""),
        "por_ra": por_ra,
        "transparencia": " · ".join(sorted(transparencias))[:800],
        "doctrina": "La IA propone esta retroalimentación; el docente la valida y edita (G1).",
    }
