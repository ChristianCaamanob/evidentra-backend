"""
F2 - Pre-calificacion de respuestas de desarrollo (motor del modulo F).

La IA PROPONE, el docente DECIDE (G1). Evalua una respuesta abierta criterio por
criterio, respetando la parametrizacion que fijo el docente (F1):

  - nivel_exigencia (estricto / tolerante / flexible) cambia la regla de correccion.
  - anclas de calibracion (few-shot): respuestas de ejemplo ya corregidas fijan el estandar.
  - sinonimos / equivalencias aceptadas y norma terminologica de la disciplina.
  - penaliza_forma: si los errores formales (ortografia, termino inexacto) descuentan.
  - umbral_confianza: bajo el, la respuesta se marca 'requiere_revision' (a manos del docente).
  - politica_creativo: ante lo inesperado-valido, marcar para el docente en vez de reprobar.

Salida por criterio: {nivel, confianza, evidencia, justificacion, requiere_revision}.
La NOTA queda PENDIENTE de validacion docente. El motor del modelo (LLM) entra por el
seam `coder`; por defecto se usa un grader determinista basado en las anclas, util para
tests y uso sin modelo.

Gobernanza: trabaja sobre respuestas seudonimizadas (G2); no emite la nota (G1, G4).
"""
from __future__ import annotations

import re
import unicodedata

from app.models.answer_key import (
    EXIGENCIA_ESTRICTO, EXIGENCIA_TOLERANTE, EXIGENCIA_FLEXIBLE,
    LOGRO_LOGRADO, LOGRO_PARCIAL, LOGRO_NO,
)

_STOP = {"el", "la", "los", "las", "un", "una", "de", "del", "y", "o", "que", "se",
         "en", "a", "con", "por", "para", "su", "sus", "es", "al", "lo", "como", "mas",
         "esta", "este", "cuando", "the", "of"}


def _norm(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    palabras = re.findall(r"[a-z0-9]+", t)
    return [w for w in palabras if w not in _STOP and len(w) > 2]


def _tokens(texto: str) -> set[str]:
    return set(_norm(texto))


def _similitud(a: set[str], b: set[str]) -> float:
    """Coeficiente de solapamiento (respecto del ancla): que tanto de la idea aparece."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(b)


def _canonico_presente(respuesta_tok: set[str], sinonimos: list[str] | None) -> bool:
    if not sinonimos:
        return False
    for s in sinonimos:
        st = _tokens(s)
        if st and st <= respuesta_tok:   # todos los tokens del termino presentes
            return True
    return False


def _grade_por_anclas(respuesta: str, criterio: dict) -> dict:
    """Grader determinista: asigna el nivel del ancla mas parecida, ajustado por exigencia."""
    rtok = _tokens(respuesta)
    anclas = criterio.get("anclas") or []
    exig = criterio.get("nivel_exigencia", EXIGENCIA_TOLERANTE)
    sin = criterio.get("sinonimos") or []

    # Concepto objetivo: anclas 'logrado' + sinonimos + nombre del criterio.
    if anclas:
        sims = [(_similitud(rtok, _tokens(a["texto"])), a["nivel"], a["texto"]) for a in anclas]
        sims.sort(key=lambda x: -x[0])
        mejor_sim, base_nivel, evid = sims[0]
        segundo = sims[1][0] if len(sims) > 1 else 0.0
        margen = mejor_sim - segundo
    else:
        objetivo = set().union(*[_tokens(s) for s in sin]) if sin else _tokens(criterio.get("name", ""))
        mejor_sim = _similitud(rtok, objetivo)
        base_nivel = LOGRO_LOGRADO if mejor_sim >= 0.6 else LOGRO_PARCIAL if mejor_sim >= 0.3 else LOGRO_NO
        margen = mejor_sim
        evid = criterio.get("name", "")

    canonico = _canonico_presente(rtok, sin)
    requiere = False
    justif = ""

    if exig == EXIGENCIA_ESTRICTO:
        # exige el concepto correcto y completo (termino canonico presente)
        if base_nivel == LOGRO_LOGRADO and sin and not canonico:
            base_nivel = LOGRO_PARCIAL
            justif = "La idea aparece pero sin el termino canonico de la norma; en estricto no cuenta como logrado."
        conf = min(0.95, mejor_sim * (1.0 if canonico else 0.7))
    elif exig == EXIGENCIA_FLEXIBLE:
        # premia la comprension central; lo inesperado-valido se marca, no se reprueba
        if base_nivel == LOGRO_NO and mejor_sim >= 0.15:
            base_nivel = LOGRO_PARCIAL
        if mejor_sim < 0.2 and len(rtok) >= 4:
            requiere = True
            justif = "Respuesta poco alineada a las anclas pero no trivial: se marca para revision docente (posible enfoque valido)."
        conf = min(0.9, 0.4 + mejor_sim)
    else:  # tolerante
        conf = min(0.92, mejor_sim + (0.1 if canonico else 0.0))

    umbral = criterio.get("umbral_confianza", 0.7)
    if conf < umbral:
        requiere = True
        justif = justif or f"Confianza {round(conf,2)} bajo el umbral {umbral}: se envia a revision docente."
    justif = justif or f"Coincide con un ejemplo '{base_nivel}' del docente (similitud {round(mejor_sim,2)})."
    return {"nivel": base_nivel, "confianza": round(float(conf), 2),
            "evidencia": evid, "justificacion": justif, "requiere_revision": bool(requiere)}


def precalificar_criterio(respuesta: str, criterio: dict, coder=None) -> dict:
    """
    Pre-califica UN criterio. coder opcional (seam LLM): callable(respuesta, criterio)->dict
    con {nivel, confianza, evidencia, justificacion}. Por defecto usa las anclas.
    """
    base = (coder(respuesta, criterio) if coder else _grade_por_anclas(respuesta, criterio))
    # asegurar campos y regla de revision segun umbral (tambien para el seam LLM)
    umbral = criterio.get("umbral_confianza", 0.7)
    base.setdefault("requiere_revision", base.get("confianza", 0) < umbral)
    if base.get("confianza", 0) < umbral:
        base["requiere_revision"] = True
    return {"criterio": criterio.get("name"), "peso": criterio.get("peso", criterio.get("weight", 1.0)),
            "nivel_exigencia": criterio.get("nivel_exigencia", EXIGENCIA_TOLERANTE), **base}


_PUNTAJE = {LOGRO_LOGRADO: 1.0, LOGRO_PARCIAL: 0.5, LOGRO_NO: 0.0}


def precalificar_respuesta(respuesta: str, criterios: list[dict], coder=None,
                           norma_terminologica: str | None = None) -> dict:
    """
    Pre-califica una respuesta contra todos los criterios de la rubrica.
    Devuelve el detalle por criterio + un puntaje propuesto (PENDIENTE de validacion docente).
    """
    detalle = [precalificar_criterio(respuesta, c, coder=coder) for c in criterios]
    total_peso = sum(d["peso"] for d in detalle) or 1.0
    puntaje = sum(_PUNTAJE.get(d["nivel"], 0.0) * d["peso"] for d in detalle) / total_peso
    revisar = [d["criterio"] for d in detalle if d["requiere_revision"]]
    return {
        "criterios": detalle,
        "puntaje_propuesto": round(puntaje, 3),         # 0-1, ponderado
        "requiere_revision": bool(revisar),
        "criterios_a_revisar": revisar,
        "norma_terminologica": norma_terminologica,
        "estado_nota": "pendiente_validacion_docente",  # G1: la IA no pone la nota
        "seudonimizado": True,                           # G2
        "gobernanza": "Propuesta de la IA; la calificacion final es del docente (indelegable, G1). "
                      "Requiere consentimiento del estudiante (G4).",
    }


# ───────────────────────────────────────────── calidad IA vs docente (para F3)
def qwk(a: list, b: list, categorias: list | None = None) -> float:
    """
    Kappa de Cohen ponderado cuadraticamente (QWK): el estandar de acuerdo IA<->docente.
    a, b: listas de niveles (mismos casos). >=0.70 aceptable, >=0.80 operativo.
    """
    cats = categorias or [LOGRO_NO, LOGRO_PARCIAL, LOGRO_LOGRADO]
    idx = {c: i for i, c in enumerate(cats)}
    K = len(cats)
    n = len(a)
    if n == 0 or len(b) != n:
        return 0.0
    O = [[0] * K for _ in range(K)]
    for x, y in zip(a, b):
        O[idx[x]][idx[y]] += 1
    row = [sum(O[i]) for i in range(K)]
    col = [sum(O[i][j] for i in range(K)) for j in range(K)]
    num = den = 0.0
    for i in range(K):
        for j in range(K):
            w = (i - j) ** 2 / (K - 1) ** 2
            e = row[i] * col[j] / n
            num += w * O[i][j]
            den += w * e
    return round(1 - num / den, 3) if den > 0 else 1.0
