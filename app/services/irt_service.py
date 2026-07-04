"""
I1 - Motor IRT (modelo de Rasch / 1PL) para el modulo Investigador.

Estima, por Maxima Verosimilitud Conjunta (JMLE):
  - Dificultad de cada item (b, en logits) y su error estandar.
  - Habilidad latente de cada persona (theta, en logits) y su error estandar.
  - Estadisticos de ajuste al modelo por item (infit y outfit MSQ).
  - Funcion de informacion del test y error estandar de medicion (SEM) segun theta.
  - Fiabilidad de separacion de personas e items (analogo Rasch al KR-20).

El modelo de Rasch es el estandar de la medicion educativa moderna: coloca items y
personas en la MISMA escala de intervalo (logits), independizando las propiedades del
item de la muestra. Sobre este objeto se construyen el mapa item-persona (Wright), las
curvas caracteristicas (ICC) y la informacion del test.

Solo numpy + scipy. Trabaja sobre una matriz 0/1 (persona x item) que puede derivarse
del dataset tidy de curso_stats_service.
"""
from __future__ import annotations

import numpy as np
from scipy.special import expit


def matriz_desde_resultado(resultado: dict) -> tuple[np.ndarray, list, list]:
    """Construye la matriz 0/1 (persona x item) desde el resultado de analizar_evaluacion."""
    filas = resultado.get("dataset_largo", [])
    personas = sorted({f["student_id"] for f in filas})
    items = sorted({f["item"] for f in filas})
    pi = {p: i for i, p in enumerate(personas)}
    ii = {it: j for j, it in enumerate(items)}
    X = np.full((len(personas), len(items)), np.nan)
    for f in filas:
        X[pi[f["student_id"]], ii[f["item"]]] = f["correcto"]
    return X, personas, items


def estimar_rasch(X, max_iter: int = 300, tol: float = 1e-4) -> dict:
    """
    Estima el modelo de Rasch por JMLE sobre X (persona x item, 0/1).
    Devuelve parametros, ajuste, informacion y fiabilidad.
    """
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    r = np.nansum(X, axis=1)     # puntaje por persona
    s = np.nansum(X, axis=0)     # puntaje por item
    valido = ~np.isnan(X)

    # Extremos (no estimables con parametro finito): se marcan aparte.
    persona_extrema = (r == 0) | (r == k)
    item_extremo = (s == 0) | (s == n)

    # Inicializacion: dificultad desde la proporcion de aciertos.
    p_i = np.clip(s / np.maximum(valido.sum(0), 1), 0.02, 0.98)
    b = -np.log(p_i / (1 - p_i)); b -= b.mean()
    theta = np.zeros(n)
    p_p = np.clip(r / np.maximum(valido.sum(1), 1), 0.02, 0.98)
    theta = np.log(p_p / (1 - p_p))

    for _ in range(max_iter):
        b_old = b.copy()
        # actualizar theta (Newton-Raphson, una pasada)
        P = expit(theta[:, None] - b[None, :]) * valido
        W = P * (1 - P) * valido
        theta = theta + (r - P.sum(1)) / np.clip(W.sum(1), 1e-6, None)
        theta = np.clip(theta, -6, 6)
        # actualizar b y centrar (identificabilidad)
        P = expit(theta[:, None] - b[None, :]) * valido
        W = P * (1 - P) * valido
        b = b + (P.sum(0) - s) / np.clip(W.sum(0), 1e-6, None)
        b = b - b.mean()
        b = np.clip(b, -6, 6)
        if np.max(np.abs(b - b_old)) < tol:
            break

    # Probabilidades y residuales finales
    P = expit(theta[:, None] - b[None, :])
    W = P * (1 - P)
    resid = (X - P)
    z = resid / np.sqrt(np.clip(W, 1e-9, None))  # residual estandarizado

    # Errores estandar
    se_b = 1.0 / np.sqrt(np.clip((W * valido).sum(0), 1e-6, None))
    se_theta = 1.0 / np.sqrt(np.clip((W * valido).sum(1), 1e-6, None))

    # Ajuste por item: outfit (no ponderado) e infit (ponderado por informacion)
    with np.errstate(invalid="ignore"):
        outfit = np.nanmean(np.where(valido, z ** 2, np.nan), axis=0)
        infit = np.nansum(np.where(valido, resid ** 2, 0), axis=0) / \
            np.clip(np.nansum(np.where(valido, W, 0), axis=0), 1e-6, None)

    # Funcion de informacion del test sobre una grilla de theta
    grid = np.linspace(-4, 4, 41)
    Pg = expit(grid[:, None] - b[None, :])
    info_test = (Pg * (1 - Pg)).sum(1)
    sem = 1.0 / np.sqrt(np.clip(info_test, 1e-6, None))

    # Fiabilidad de separacion (Rasch)
    def _sep_rel(vals, ses):
        vals = np.asarray(vals); ses = np.asarray(ses)
        var_obs = vals.var(ddof=1) if len(vals) > 1 else 0.0
        mse = np.mean(ses ** 2)
        return float(max(0.0, (var_obs - mse) / var_obs)) if var_obs > mse else 0.0

    person_rel = _sep_rel(theta[~persona_extrema], se_theta[~persona_extrema])
    item_rel = _sep_rel(b[~item_extremo], se_b[~item_extremo])

    def _cal_ajuste(msq):
        if msq < 0.5: return "sobreajuste"
        if msq <= 1.5: return "productivo"
        if msq <= 2.0: return "poco_productivo"
        return "desajuste"

    items = [{
        "item": j + 1,
        "b": round(float(b[j]), 3),
        "se_b": round(float(se_b[j]), 3),
        "infit_msq": round(float(infit[j]), 2),
        "outfit_msq": round(float(outfit[j]), 2),
        "ajuste": _cal_ajuste(float(infit[j])),
        "extremo": bool(item_extremo[j]),
    } for j in range(k)]

    personas = [{
        "idx": i,
        "theta": round(float(theta[i]), 3),
        "se_theta": round(float(se_theta[i]), 3),
        "extremo": bool(persona_extrema[i]),
    } for i in range(n)]

    return {
        "modelo": "Rasch (1PL) JMLE",
        "n_personas": int(n), "n_items": int(k),
        "items": items,
        "personas": personas,
        "informacion_test": {"theta_grid": [round(x, 2) for x in grid.tolist()],
                             "info": [round(float(x), 3) for x in info_test.tolist()],
                             "sem": [round(float(x), 3) for x in sem.tolist()]},
        "fiabilidad": {"separacion_personas": round(person_rel, 3),
                       "separacion_items": round(item_rel, 3)},
        "escala": {"b_media": 0.0, "b_de": round(float(b.std(ddof=1)), 3),
                   "theta_media": round(float(theta[~persona_extrema].mean()), 3),
                   "theta_de": round(float(theta[~persona_extrema].std(ddof=1)), 3)},
        "extremos": {"personas": int(persona_extrema.sum()), "items": int(item_extremo.sum())},
    }
