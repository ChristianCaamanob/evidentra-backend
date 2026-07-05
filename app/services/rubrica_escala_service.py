"""
Escala de logro parametrizable por criterio (robustecimiento para rubricas analiticas reales).

Una rubrica puede definir SUS PROPIOS niveles con puntajes y descriptores -p. ej. Excelente=3,
Bueno=2, Regular=1, Deficiente=0- en vez de los 3 niveles por defecto. Este modulo traduce un
nivel a:

  - fraccion_logro : fraccion de logro en [0,1] = puntos(nivel) / max(puntos). Es lo que usa el
                     libro de notas para el puntaje exacto de la rubrica.
  - nivel_canonico : el nivel arbitrario mapeado a la escala ordenada de 3
                     (no_logrado/parcial/logrado) que consumen R, MFRM, DIF -por rango del nivel.

Si el criterio no define niveles_json, se usa la escala de 3 por defecto (compatibilidad total).
"""
from __future__ import annotations

import unicodedata

NIVELES_DEFECTO = [
    {"nivel": "logrado", "puntos": 2},
    {"nivel": "parcial", "puntos": 1},
    {"nivel": "no_logrado", "puntos": 0},
]
CANONICOS = ("no_logrado", "parcial", "logrado")


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.lower().strip().replace(" ", "_")


def _niveles(niveles):
    return niveles if niveles else NIVELES_DEFECTO


def max_puntos(niveles) -> float:
    return max((float(n.get("puntos", 0)) for n in _niveles(niveles)), default=1.0) or 1.0


def fraccion_logro(niveles, nivel_label) -> float:
    """Fraccion de logro [0,1] del nivel alcanzado (puntos/max). 0 si no coincide."""
    ns = _niveles(niveles)
    objetivo = _norm(nivel_label)
    mx = max_puntos(ns)
    for n in ns:
        if _norm(n.get("nivel")) == objetivo:
            return max(0.0, min(1.0, float(n.get("puntos", 0)) / mx))
    return 0.0


def nivel_canonico(niveles, nivel_label) -> str:
    """Mapea un nivel arbitrario a la escala canonica de 3 por su RANGO (mejor->peor):
    el mejor -> logrado, el peor -> no_logrado, los intermedios -> parcial."""
    ns = _niveles(niveles)
    objetivo = _norm(nivel_label)
    idx = next((i for i, n in enumerate(ns) if _norm(n.get("nivel")) == objetivo), None)
    if idx is None:
        return "no_logrado"
    if len(ns) == 1 or idx == 0:
        return "logrado"
    if idx == len(ns) - 1:
        return "no_logrado"
    return "parcial"
