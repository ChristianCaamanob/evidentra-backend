"""
Estadistica clasica para el modulo Investigador — Fases 1 y 2 del pipeline de analisis.

Fase 1 · Depuracion de datos (screening):
  - descriptivos por item y por puntaje total (media, DE, asimetria, curtosis, min, max)
  - supuestos: normalidad del puntaje total (Shapiro-Wilk), efectos techo/piso
  - datos perdidos: tasa por item, casos completos, diagnostico de aleatoriedad

Fase 2 · Analisis de items (Teoria Clasica de los Tests):
  - dificultad clasica (p), discriminacion (biserial-puntual y r item-total corregida)
  - fiabilidad: alfa de Cronbach (+ alfa si se elimina), omega de McDonald (1 factor),
    error tipico de medicion (SEM), lambda-2 y lambda-6 de Guttman

Todo sobre la matriz 0/1 (persona x item) seudonimizada (G2). No altera notas (G1).
Solo numpy/scipy/statsmodels — sin dependencias nuevas.
"""
from __future__ import annotations

import numpy as np
from scipy import stats
from scipy.stats import norm, multivariate_normal
from scipy.optimize import brentq

from app.core.errors import conflict


# ─────────── Correlación tetracórica (rigor para ítems dicotómicos) ───────────

def tetrachoric_corr(x, y) -> float:
    """Correlación tetracorica EXACTA: r del modelo normal bivariado latente que reproduce
    la tabla 2x2 observada (root-find sobre la CDF normal bivariada). Es el metodo correcto
    para items dicotomicos; Pearson/phi subestima la asociacion latente."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y)); x = x[m]; y = y[m]
    if x.size < 3:
        return np.nan
    p1 = np.mean(x > 0.5); p2 = np.mean(y > 0.5)
    if p1 in (0.0, 1.0) or p2 in (0.0, 1.0):
        return np.nan
    p00 = np.mean((x < 0.5) & (y < 0.5))
    tx = norm.ppf(1 - p1); ty = norm.ppf(1 - p2)

    def cell00(r):
        return multivariate_normal(mean=[0, 0], cov=[[1, r], [r, 1]]).cdf([tx, ty])

    lo, hi = cell00(-0.999), cell00(0.999)
    if not (min(lo, hi) <= p00 <= max(lo, hi)):
        return float(np.clip(np.corrcoef(x, y)[0, 1], -0.99, 0.99))
    try:
        return float(brentq(lambda r: cell00(r) - p00, -0.999, 0.999, xtol=1e-6))
    except Exception:
        return float(np.clip(np.corrcoef(x, y)[0, 1], -0.99, 0.99))


def tetrachoric_matrix(X) -> np.ndarray:
    """Matriz de correlaciones tetracoricas (k x k) de una matriz 0/1."""
    X = np.asarray(X, float); k = X.shape[1]
    R = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            r = tetrachoric_corr(X[:, i], X[:, j])
            R[i, j] = R[j, i] = 0.0 if (r is None or np.isnan(r)) else r
    return R


def _limpia(X) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    if X.ndim != 2 or X.shape[0] < 3 or X.shape[1] < 3:
        raise conflict("Datos insuficientes para el analisis clasico (>=3 personas y >=3 items).")
    return X


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), d)


# ─────────────────────────── FASE 1 ───────────────────────────

def descriptivos(X) -> dict:
    """Descriptivos por item y del puntaje total (ignora NaN por columna)."""
    X = _limpia(X)
    items = []
    for j in range(X.shape[1]):
        col = X[:, j]; col = col[~np.isnan(col)]
        items.append({
            "item": j + 1, "n": int(col.size),
            "media": _r(np.mean(col)) if col.size else None,
            "de": _r(np.std(col, ddof=1)) if col.size > 1 else None,
            "asimetria": _r(stats.skew(col)) if col.size > 2 else None,
            "curtosis": _r(stats.kurtosis(col)) if col.size > 2 else None,  # exceso (0 = normal)
            "min": _r(np.min(col)) if col.size else None,
            "max": _r(np.max(col)) if col.size else None,
        })
    total = np.nansum(X, axis=1)
    return {
        "items": items,
        "total": {
            "n": int(total.size), "media": _r(np.mean(total)), "de": _r(np.std(total, ddof=1)),
            "asimetria": _r(stats.skew(total)), "curtosis": _r(stats.kurtosis(total)),
            "min": _r(np.min(total)), "max": _r(np.max(total)),
        },
    }


def supuestos(X) -> dict:
    """Normalidad del puntaje total (Shapiro-Wilk) + efectos techo/piso."""
    X = _limpia(X)
    total = np.nansum(X, axis=1)
    n_items = X.shape[1]
    normal = {}
    if 3 <= total.size <= 5000 and np.std(total) > 0:
        W, p = stats.shapiro(total)
        normal = {"prueba": "Shapiro-Wilk", "W": _r(W), "p": _r(p, 4),
                  "veredicto": "compatible con normalidad" if p >= 0.05 else "se aparta de la normalidad"}
    else:
        normal = {"prueba": "Shapiro-Wilk", "veredicto": "no evaluable (muestra o varianza)"}
    piso = float(np.mean(total <= np.min(total))) * 100
    techo = float(np.mean(total >= n_items)) * 100  # max posible = n_items (todo correcto)
    return {
        "normalidad_total": normal,
        "techo_pct": _r(techo, 1), "piso_pct": _r(piso, 1),
        "alerta_techo": techo >= 15, "alerta_piso": piso >= 15,
        "nota": "Techo/piso > 15% sugieren rango restringido; considerar items mas dificiles/faciles.",
    }


def datos_perdidos(X) -> dict:
    """Tasa de perdidos por item y total + diagnostico practico de aleatoriedad (MCAR).
    Para cada item con perdidos, compara el puntaje total de quienes lo respondieron vs
    quienes no (t de Welch): si difieren sistematicamente, los perdidos NO son MCAR."""
    X = _limpia(X)
    n, k = X.shape
    miss = np.isnan(X)
    por_item = []
    total_score = np.nansum(X, axis=1)
    sistematico = 0
    for j in range(k):
        m = miss[:, j]; pct = float(np.mean(m)) * 100
        fila = {"item": j + 1, "perdidos_pct": _r(pct, 1)}
        if 0 < m.sum() < n and (~m).sum() >= 2:
            try:
                t, p = stats.ttest_ind(total_score[m], total_score[~m], equal_var=False, nan_policy="omit")
                fila["p_mcar"] = _r(p, 4)
                if p is not None and not np.isnan(p) and p < 0.05:
                    sistematico += 1
            except Exception:
                pass
        por_item.append(fila)
    total_perdidos = float(np.mean(miss)) * 100
    completos = int(np.sum(~miss.any(axis=1)))
    return {
        "perdidos_total_pct": _r(total_perdidos, 1),
        "casos_completos": completos, "n": int(n),
        "por_item": por_item,
        "items_no_aleatorios": sistematico,
        "veredicto": ("sin datos perdidos" if total_perdidos == 0 else
                      ("perdidos compatibles con MCAR" if sistematico == 0 else
                       f"{sistematico} item(s) con perdidos NO aleatorios (asociados al desempeno)")),
        "metodo": "Comparacion observado/perdido por item (diagnostico practico de MCAR).",
    }


# ─────────────────────────── FASE 2 ───────────────────────────

def _cov(X):
    """Matriz de covarianzas por pares completos (maneja NaN)."""
    return np.ma.cov(np.ma.masked_invalid(X), rowvar=False, allow_masked=True).filled(0.0)


def alfa_cronbach(X) -> dict:
    X = _limpia(X)
    k = X.shape[1]
    var_items = np.nanvar(X, axis=0, ddof=1)
    total = np.nansum(X, axis=1)
    var_total = np.var(total, ddof=1)
    if var_total <= 0:
        return {"alfa": None, "nota": "varianza total nula"}
    alfa = k / (k - 1) * (1 - var_items.sum() / var_total)
    # alfa si se elimina el item j
    si_elimina = []
    for j in range(k):
        idx = [i for i in range(k) if i != j]
        tot = np.nansum(X[:, idx], axis=1); vt = np.var(tot, ddof=1)
        vi = np.nansum(np.nanvar(X[:, idx], axis=0, ddof=1))
        a = (k - 1) / (k - 2) * (1 - vi / vt) if (k > 2 and vt > 0) else None
        si_elimina.append(_r(a))
    return {"alfa": _r(alfa), "alfa_si_elimina": si_elimina,
            "veredicto": _veredicto_fiab(alfa)}


def _veredicto_fiab(a):
    if a is None:
        return "no evaluable"
    if a >= 0.9:
        return "excelente"
    if a >= 0.8:
        return "buena"
    if a >= 0.7:
        return "aceptable"
    if a >= 0.6:
        return "cuestionable"
    return "insuficiente"


def _cargas_1factor(R):
    """Cargas del primer factor principal sobre una matriz de correlacion R (k x k)."""
    R = np.nan_to_num(np.asarray(R, float), nan=0.0)
    np.fill_diagonal(R, 1.0)
    vals, vecs = np.linalg.eigh(R)
    lam1 = max(vals[-1], 0.0)
    v = vecs[:, -1]
    if np.sum(v) < 0:
        v = -v
    return np.clip(np.sqrt(lam1) * v, -0.999, 0.999)


def omega_mcdonald(X) -> dict:
    """Omega de McDonald categorico: cargas de 1 factor sobre la correlacion TETRACORICA
    (metodo correcto para items dicotomicos, no Pearson)."""
    X = _limpia(X)
    lam = _cargas_1factor(tetrachoric_matrix(X))
    sum_l = float(np.sum(lam))
    err = float(np.sum(1.0 - lam ** 2))
    if (sum_l ** 2 + err) <= 0:
        return {"omega": None}
    omega = sum_l ** 2 / (sum_l ** 2 + err)
    return {"omega": _r(omega), "veredicto": _veredicto_fiab(omega),
            "nota": "Omega categorico (1 factor sobre correlacion tetracorica)."}


def sem(X, fiab=None) -> dict:
    """Error tipico de medicion: SEM = DE_total * sqrt(1 - fiabilidad)."""
    X = _limpia(X)
    total = np.nansum(X, axis=1)
    de = np.std(total, ddof=1)
    if fiab is None:
        fiab = alfa_cronbach(X).get("alfa")
    if fiab is None:
        return {"sem": None}
    s = de * np.sqrt(max(0.0, 1 - fiab))
    return {"sem": _r(s), "de_total": _r(de), "fiabilidad_usada": _r(fiab),
            "ic95_semiancho": _r(1.96 * s),
            "nota": "IC95% de la puntuacion verdadera ~= observada +/- 1.96*SEM."}


def guttman(X) -> dict:
    """Lambda-2 y lambda-6 de Guttman (cotas de fiabilidad)."""
    X = _limpia(X)
    k = X.shape[1]
    C = _cov(X)
    Vt = float(np.sum(C))
    if Vt <= 0:
        return {"lambda2": None, "lambda6": None}
    off = C.copy(); np.fill_diagonal(off, 0.0)
    C1 = float(np.sum(off))
    C2 = float(np.sum(off ** 2))
    lam2 = (C1 + np.sqrt(k / (k - 1) * C2)) / Vt if k > 1 else None
    # lambda-6: 1 - sum(e_i^2)/Vt, e_i^2 = (1 - SMC_i) * var_i
    try:
        Rr = np.ma.corrcoef(np.ma.masked_invalid(X), rowvar=False, allow_masked=True).filled(0.0)
        np.fill_diagonal(Rr, 1.0)
        Rinv = np.linalg.pinv(Rr)
        smc = 1.0 - 1.0 / np.clip(np.diag(Rinv), 1e-6, None)
        var_i = np.diag(C)
        e2 = (1.0 - np.clip(smc, 0, 1)) * var_i
        lam6 = 1.0 - float(np.sum(e2)) / Vt
    except Exception:
        lam6 = None
    return {"lambda2": _r(lam2), "lambda6": _r(lam6),
            "nota": "lambda-2 >= alfa siempre; son cotas inferiores de la fiabilidad."}


def analisis_items_tct(X) -> dict:
    """Dificultad (p), discriminacion (biserial-puntual y r item-total corregida) por item."""
    X = _limpia(X)
    k = X.shape[1]
    total = np.nansum(X, axis=1)
    filas = []
    for j in range(k):
        col = X[:, j]
        p = float(np.nanmean(col))
        resto = np.nansum(np.delete(X, j, axis=1), axis=1)  # total sin el item (corregida)
        try:
            rpb = np.corrcoef(np.nan_to_num(col), resto)[0, 1]
        except Exception:
            rpb = None
        try:
            r_tot = np.corrcoef(np.nan_to_num(col), total)[0, 1]
        except Exception:
            r_tot = None
        flag = "buena" if (rpb is not None and rpb >= 0.30) else ("aceptable" if (rpb is not None and rpb >= 0.20) else "revisar")
        filas.append({
            "item": j + 1, "dificultad_p": _r(p),
            "nivel": ("facil" if p >= 0.85 else "dificil" if p <= 0.30 else "media"),
            "discriminacion_corregida": _r(rpb), "r_item_total": _r(r_tot),
            "calidad": flag,
        })
    return {"items": filas, "n_items": k,
            "nota": "p = proporcion de aciertos; discriminacion corregida = r del item con el total SIN ese item (>=0.30 buena)."}


def reporte_completo(X) -> dict:
    """Agrega Fase 1 + Fase 2 en un solo objeto (para el endpoint)."""
    X = _limpia(X)
    alfa = alfa_cronbach(X)
    return {
        "descriptivos": descriptivos(X),
        "supuestos": supuestos(X),
        "datos_perdidos": datos_perdidos(X),
        "items_tct": analisis_items_tct(X),
        "fiabilidad": {
            "alfa_cronbach": alfa,
            "omega_mcdonald": omega_mcdonald(X),
            "sem": sem(X, alfa.get("alfa")),
            "guttman": guttman(X),
        },
    }
