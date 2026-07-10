"""
Fase 7 del pipeline Investigador — efectos, comparaciones y correlaciones.

Estadistica que exige la seccion de Resultados de un articulo (APA 7: siempre tamano de
efecto + IC, no solo p):
  - comparacion de 2 grupos sobre el puntaje total: t de Welch + Mann-Whitney (no parametrica)
  - tamanos de efecto con IC95%: d de Cohen y g de Hedges (con correccion muestral)
  - resumen de correlaciones inter-item (Pearson) — cohesion del conjunto

Opera sobre grupos CONSENTIDOS y seudonimizados (G2/G4), como el resto del modulo. No
altera notas (G1). Solo numpy/scipy.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from app.core.errors import conflict


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), d)


def _interpreta_d(d):
    a = abs(d)
    if a < 0.2:
        return "trivial"
    if a < 0.5:
        return "pequeno"
    if a < 0.8:
        return "mediano"
    return "grande"


def comparar_grupos(total, grupo, referencia=None, focal=None) -> dict:
    """Compara el puntaje total entre 2 grupos: medias, t de Welch, Mann-Whitney y tamanos
    de efecto (d de Cohen, g de Hedges) con IC95%."""
    total = np.asarray(total, dtype=float)
    grupo = np.asarray(grupo)
    cats = list(dict.fromkeys(grupo.tolist()))
    if len(cats) < 2:
        raise conflict("Se requieren al menos 2 grupos para comparar.")
    g1, g2 = (referencia, focal) if (referencia in cats and focal in cats) else (cats[0], cats[1])
    x1 = total[grupo == g1]; x2 = total[grupo == g2]
    n1, n2 = x1.size, x2.size
    if n1 < 2 or n2 < 2:
        raise conflict("Cada grupo requiere al menos 2 observaciones.")
    m1, m2 = float(np.mean(x1)), float(np.mean(x2))
    s1, s2 = float(np.std(x1, ddof=1)), float(np.std(x2, ddof=1))
    # t de Welch
    tw, pw = stats.ttest_ind(x1, x2, equal_var=False)
    # Mann-Whitney (no parametrica)
    try:
        u, pmw = stats.mannwhitneyu(x1, x2, alternative="two-sided")
    except Exception:
        u, pmw = (None, None)
    # d de Cohen (SD combinada) y g de Hedges
    sp = np.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (n1 + n2 - 2)) if (n1 + n2 - 2) > 0 else np.nan
    d = (m1 - m2) / sp if sp and sp > 0 else np.nan
    J = 1 - 3 / (4 * (n1 + n2) - 9) if (4 * (n1 + n2) - 9) != 0 else 1.0
    g = d * J
    # IC95% de d (aprox. normal)
    se_d = np.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2))) if not np.isnan(d) else np.nan
    ic = (d - 1.96 * se_d, d + 1.96 * se_d) if not np.isnan(se_d) else (None, None)
    return {
        "grupos": {str(g1): {"n": n1, "media": _r(m1, 2), "de": _r(s1, 2)},
                   str(g2): {"n": n2, "media": _r(m2, 2), "de": _r(s2, 2)}},
        "comparados": [str(g1), str(g2)],
        "welch_t": {"t": _r(tw), "p": _r(pw, 4), "significativo": bool(pw is not None and pw < 0.05)},
        "mann_whitney": {"U": _r(u, 1), "p": _r(pmw, 4)},
        "cohen_d": _r(d), "hedges_g": _r(g),
        "d_ic95": [_r(ic[0]), _r(ic[1])],
        "magnitud": _interpreta_d(d) if not np.isnan(d) else None,
        "interpretacion": (f"Diferencia {_interpreta_d(d)} (d={_r(d)}); "
                           + ("estadisticamente significativa" if (pw is not None and pw < 0.05)
                              else "no significativa") + " al 5%.") if not np.isnan(d) else None,
        "nota": "APA 7: se reporta tamano de efecto + IC95%, no solo el valor p.",
    }


def correlaciones_resumen(X) -> dict:
    """Resumen de correlaciones inter-item (Pearson): media y rango de las correlaciones."""
    X = np.asarray(X, dtype=float)
    if X.shape[1] < 2:
        return {"r_media": None}
    R = np.ma.corrcoef(np.ma.masked_invalid(X), rowvar=False, allow_masked=True).filled(np.nan)
    k = R.shape[0]
    tri = R[np.triu_indices(k, k=1)]
    tri = tri[~np.isnan(tri)]
    if tri.size == 0:
        return {"r_media": None}
    return {"r_media": _r(float(np.mean(tri))), "r_min": _r(float(np.min(tri))),
            "r_max": _r(float(np.max(tri))), "n_pares": int(tri.size),
            "nota": "Correlacion inter-item promedio (cohesion); ideal ~0.15-0.50 para un unico constructo."}
