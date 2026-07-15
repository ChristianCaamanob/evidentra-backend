"""Consistencia de la medición cualitativa (Fase C · rigor mixed-methods).

Da a lo cualitativo la fiabilidad que Q1 exige:

  · Acuerdo entre codificadores — Cohen's κ (1960) por código + κ medio, con la banda
    interpretativa de Landis & Koch (1977). Para análisis temático (Braun & Clarke) donde
    dos codificadores (p. ej. IA y humano, o dos pasadas) asignan códigos a respuestas abiertas.
  · Estabilidad de una prevalencia — intervalo de Wilson (1927), cerrado y sin simulación,
    para acotar la prevalencia de una concepción/tema (¿es estable o ruido muestral?).

Python puro (sin numpy); todo determinista para que el CI lo verifique.
Referencias: Cohen (1960); Landis & Koch (1977); Krippendorff (2004); Wilson (1927).
"""
from __future__ import annotations

import math
from collections import Counter


# ───────────────────────────── acuerdo entre dos codificadores
def cohen_kappa(a: list, b: list) -> float | None:
    """κ de Cohen para dos series de etiquetas nominales alineadas (misma longitud)."""
    n = len(a)
    if n == 0 or len(b) != n:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    cats = set(a) | set(b)
    pe = sum((ca.get(c, 0) / n) * (cb.get(c, 0) / n) for c in cats)
    if pe >= 1.0:
        return 1.0
    return round((po - pe) / (1 - pe), 3)


def interpretar_kappa(k: float | None) -> str:
    """Bandas de Landis & Koch (1977)."""
    if k is None:
        return "sin datos"
    if k < 0:
        return "peor que el azar"
    if k <= 0.20:
        return "leve"
    if k <= 0.40:
        return "aceptable"
    if k <= 0.60:
        return "moderado"
    if k <= 0.80:
        return "sustancial"
    return "casi perfecto"


def consistencia_multilabel(sets_a: list, sets_b: list, codigos: list) -> dict:
    """Fiabilidad de una codificación multi-etiqueta (cada respuesta puede llevar varios códigos).

    sets_a / sets_b: por respuesta, el conjunto de códigos que asignó cada codificador.
    Reporta κ por código (presencia/ausencia binaria), κ medio, acuerdo exacto y Jaccard medio.
    """
    n = len(sets_a)
    if n == 0 or len(sets_b) != n:
        return {"n": 0, "kappa_medio": None, "kappa_por_codigo": {}, "acuerdo_exacto_pct": 0.0,
                "jaccard_medio": None, "interpretacion": "sin datos"}
    exact, jac = 0, []
    for a, b in zip(sets_a, sets_b):
        sa, sb = set(a), set(b)
        if sa == sb:
            exact += 1
        u = sa | sb
        jac.append(len(sa & sb) / len(u) if u else 1.0)
    kappas = {}
    for c in codigos:
        va = [1 if c in set(x) else 0 for x in sets_a]
        vb = [1 if c in set(x) else 0 for x in sets_b]
        kappas[c] = cohen_kappa(va, vb)
    ks = [v for v in kappas.values() if v is not None]
    k_medio = round(sum(ks) / len(ks), 3) if ks else None
    return {
        "n": n,
        "kappa_medio": k_medio,
        "kappa_por_codigo": kappas,
        "acuerdo_exacto_pct": round(exact / n * 100, 1),
        "jaccard_medio": round(sum(jac) / len(jac), 3) if jac else None,
        "interpretacion": interpretar_kappa(k_medio),
        "referencia": "Cohen (1960) κ por código; Landis & Koch (1977) bandas; multi-etiqueta.",
    }


# ───────────────────────────── estabilidad de una prevalencia (IC de Wilson)
def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    """IC de Wilson (%) para una proporción k/n. Cerrado, sin simulación (determinista)."""
    if n <= 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    medio = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return [round(max(0.0, centro - medio) * 100, 1), round(min(1.0, centro + medio) * 100, 1)]


def prevalencia_estable(k: int, n: int, ancho_max_pp: float = 20.0) -> dict:
    """Prevalencia con IC de Wilson y veredicto de estabilidad (ancho del IC en puntos %)."""
    ci = wilson_ci(k, n)
    ancho = round(ci[1] - ci[0], 1)
    return {"prevalencia_pct": round(k / n * 100, 1) if n else 0.0, "ic95": ci,
            "ancho_pp": ancho, "estable": ancho <= ancho_max_pp}
