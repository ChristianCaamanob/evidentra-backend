"""
Research OS · Fase 3 — modalidades `living_case` (caso ramificado) y contrato compartido.

`living_case`: caso con decisiones → consecuencias → corrección de rumbo → transferencia. Contenido objetivo
compartido por `conceptId`/`difficultyBand` con las otras modalidades. El outcome inmediato = calidad del
razonamiento (decisiones seguras/correctas) 0–1. Contenido demo agnóstico a disciplina (no clínico universalizado).
Las 3 modalidades comparten conceptId + dificultad + resultado inmediato + evaluación diferida equivalente.
"""
from __future__ import annotations

# Caso demo (discipline-neutral): tomar una decisión de estudio bajo incertidumbre, con consecuencias y transferencia.
_CASOS = {
    "estudio-bajo-presion": {
        "id": "estudio-bajo-presion", "conceptId": "autorregulacion", "difficultyBand": 3,
        "titulo": "Tres días para la evaluación",
        "steps": {
            "s0": {"prompt": "Tienes 3 días y 4 temas: dos que dominas y dos flojos. ¿Por dónde partes?",
                   "options": [
                       {"id": "a", "label": "Repaso lo que ya domino (me da seguridad)", "safe": False,
                        "consequence": "Te sientes bien, pero el tiempo se va en lo que ya sabías; los vacíos siguen ahí.", "next": "s1"},
                       {"id": "b", "label": "Ataco primero los dos temas flojos con recuperación activa", "safe": True,
                        "consequence": "Cuesta más, pero cierras brechas donde de verdad importa.", "next": "s1"},
                       {"id": "c", "label": "Leo todo de corrido varias veces", "safe": False,
                        "consequence": "Se siente productivo, pero releer sin recuperar deja poco. Ilusión de saber.", "next": "s1"}]},
            "s1": {"prompt": "A mitad de camino te das cuenta de que un tema flojo no entra. ¿Qué haces?",
                   "options": [
                       {"id": "a", "label": "Lo dejo fuera y refuerzo lo demás con autoevaluación", "safe": True,
                        "consequence": "Decisión madura: priorizas con criterio y consolidas lo alcanzable.", "next": "final"},
                       {"id": "b", "label": "Me quedo toda la noche para alcanzar a verlo", "safe": False,
                        "consequence": "Llegas agotado; el sueño perdido borra parte de lo estudiado.", "next": "final"}]},
        },
        "transfer": {"prompt": "Nueva situación: un compañero te pide un consejo de estudio para SU examen. ¿Qué le dices en una frase?",
                     "criterion": "prioriza brechas + recuperación activa + descanso"},
    }
}


def caso_inicio(case_id: str = "estudio-bajo-presion") -> dict:
    c = _CASOS.get(case_id) or _CASOS["estudio-bajo-presion"]
    s = c["steps"]["s0"]
    return {"ok": True, "caseId": c["id"], "conceptId": c["conceptId"], "difficultyBand": c["difficultyBand"],
            "titulo": c["titulo"], "stepId": "s0", "prompt": s["prompt"],
            "options": [{"id": o["id"], "label": o["label"]} for o in s["options"]]}  # consecuencia OCULTA hasta elegir


def caso_paso(case_id: str, step_id: str, option_id: str, elecciones: list | None = None) -> dict:
    c = _CASOS.get(case_id)
    if not c:
        return {"ok": False, "error": "caso no encontrado"}
    st = c["steps"].get(step_id)
    if not st:
        return {"ok": False, "error": "paso no encontrado"}
    op = next((o for o in st["options"] if o["id"] == option_id), None)
    if not op:
        return {"ok": False, "error": "opción no válida"}
    nxt = op["next"]
    out = {"ok": True, "consequence": op["consequence"], "safe": op.get("safe", False)}
    if nxt == "final":
        out["final"] = True
        out["transfer"] = c["transfer"]   # pregunta de transferencia (situación nueva)
    else:
        ns = c["steps"][nxt]
        out["stepId"] = nxt
        out["prompt"] = ns["prompt"]
        out["options"] = [{"id": o["id"], "label": o["label"]} for o in ns["options"]]
    return out


def caso_score(case_id: str, elecciones: list) -> dict:
    """Outcome inmediato 0–1 = proporción de decisiones seguras/correctas tomadas."""
    c = _CASOS.get(case_id)
    if not c:
        return {"ok": False, "error": "caso no encontrado"}
    seguras, total = 0, 0
    orden = ["s0", "s1"]
    for i, sid in enumerate(orden):
        st = c["steps"].get(sid)
        if not st or i >= len(elecciones or []):
            continue
        op = next((o for o in st["options"] if o["id"] == elecciones[i]), None)
        if op:
            total += 1
            if op.get("safe"):
                seguras += 1
    score = round(seguras / total, 3) if total else 0.0
    return {"ok": True, "score01": score, "safeChoices": seguras, "decisions": total}
