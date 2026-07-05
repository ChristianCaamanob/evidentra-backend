"""
I8a - IRT politomico: Modelo de Credito Parcial (PCM, Masters 1982) por JMLE.

Extiende el Rasch dicotomico de I1 a items ORDINALES (0..m): preguntas de desarrollo,
rubricas por criterio, escalas parciales. A diferencia del RSM de I6 (umbrales compartidos
entre items), el PCM estima umbrales de paso PROPIOS de cada item (delta_jk), que es lo
apropiado cuando la distancia entre niveles no es la misma en todos los items.

    P(X_pj = x) = exp( sum_{k=1..x} (theta_p - delta_jk) ) / sum_{h=0..m} exp( sum_{k=1..h} ... )

Estima por Maxima Verosimilitud Conjunta (JMLE), la misma maquinaria de I1/I6:
  - theta_p  : habilidad de la persona (+ error estandar).
  - delta_jk : umbrales de paso por item (donde el nivel k se vuelve mas probable que k-1).
  - infit/outfit MSQ por item, curvas de probabilidad de categoria e informacion del test.

Validado contra girth.pcm_jml (misma familia de estimador -> correlacion ~1).

Referencias: Masters (1982) PCM; Wright & Masters (1982) Rating Scale Analysis; Linacre JMLE.
"""
from __future__ import annotations

import numpy as np


def _probs_item(theta: np.ndarray, delta_j: np.ndarray) -> np.ndarray:
    """Matriz (n_personas x K) de probabilidades de categoria para un item (PCM)."""
    K = len(delta_j) + 1
    cats = np.arange(K)
    C = np.concatenate([[0.0], np.cumsum(delta_j)])          # (K,)
    psi = cats[None, :] * theta[:, None] - C[None, :]        # (n,K)
    psi -= psi.max(axis=1, keepdims=True)
    num = np.exp(psi)
    return num / num.sum(axis=1, keepdims=True)


def estimar_pcm(X: np.ndarray, max_iter: int = 400, tol: float = 1e-4) -> dict:
    """
    Estima el PCM por JMLE sobre X (persona x item) con categorias 0..K-1.
    Identificacion: media de theta (no extremos) fijada en 0.
    """
    X = np.asarray(X, dtype=float)
    n, m = X.shape
    K = int(np.nanmax(X)) + 1
    cats = np.arange(K, dtype=float)
    r = np.nansum(X, axis=1)                                  # puntaje por persona (estadistico sufic.)
    maxscore = m * (K - 1)
    persona_extrema = (r == 0) | (r == maxscore)

    # Inicializacion
    p_p = np.clip(r / maxscore, 0.02, 0.98)
    theta = np.log(p_p / (1 - p_p))
    delta = np.zeros((m, K - 1))
    for j in range(m):
        col = X[:, j]
        loc = -np.log(np.clip(col.mean() / (K - 1), 0.02, 0.98) /
                      (1 - np.clip(col.mean() / (K - 1), 0.02, 0.98)))
        delta[j] = loc + np.linspace(-0.7, 0.7, K - 1)

    for _ in range(max_iter):
        delta_old = delta.copy()

        # --- actualizar theta ---
        E = np.zeros(n); V = np.zeros(n)
        for j in range(m):
            P = _probs_item(theta, delta[j])
            ej = P @ cats
            E += ej; V += (P @ (cats ** 2)) - ej ** 2
        theta = theta + (r - E) / np.clip(V, 1e-6, None)
        theta = np.clip(theta, -8, 8)
        theta = theta - theta[~persona_extrema].mean()       # identificacion

        # --- actualizar umbrales por item (calibracion de pasos, Andrich/Masters) ---
        for j in range(m):
            P = _probs_item(theta, delta[j])
            Ek = P.sum(axis=0)                                # esperados por categoria
            Nk = np.array([(X[:, j] == k).sum() for k in range(K)], dtype=float)
            Ek = np.clip(Ek, 1e-6, None); Nk = np.clip(Nk, 1e-6, None)
            for k in range(1, K):
                delta[j, k - 1] += (np.log(Ek[k]) - np.log(Ek[k - 1])) - \
                                   (np.log(Nk[k]) - np.log(Nk[k - 1]))

        if np.max(np.abs(delta - delta_old)) < tol:
            break

    # --- ajuste, SE, informacion ---
    E = np.zeros(n); V = np.zeros(n)
    resid = np.zeros((n, m)); var_pj = np.zeros((n, m))
    for j in range(m):
        P = _probs_item(theta, delta[j])
        ej = P @ cats; vj = (P @ (cats ** 2)) - ej ** 2
        E += ej; V += vj
        resid[:, j] = X[:, j] - ej
        var_pj[:, j] = vj
    se_theta = 1.0 / np.sqrt(np.clip(V, 1e-6, None))
    z2 = (resid ** 2) / np.clip(var_pj, 1e-9, None)
    outfit = z2.mean(axis=0)
    infit = (resid ** 2).sum(axis=0) / np.clip(var_pj.sum(axis=0), 1e-6, None)

    def _cal(msq):
        if msq < 0.5: return "sobreajuste"
        if msq <= 1.5: return "productivo"
        if msq <= 2.0: return "poco_productivo"
        return "desajuste"

    items = [{
        "item": j + 1,
        "umbrales": [round(float(d), 3) for d in delta[j]],
        "dificultad_media": round(float(delta[j].mean()), 3),
        "umbrales_ordenados": bool(all(b > a for a, b in zip(delta[j], delta[j][1:]))),
        "infit_msq": round(float(infit[j]), 2),
        "outfit_msq": round(float(outfit[j]), 2),
        "ajuste": _cal(float(infit[j])),
    } for j in range(m)]

    # Informacion del test sobre grilla de theta
    grid = np.linspace(-4, 4, 41)
    info = np.zeros_like(grid)
    for j in range(m):
        P = _probs_item(grid, delta[j])
        e = P @ cats
        info += (P @ (cats ** 2)) - e ** 2

    return {
        "modelo": "PCM (Modelo de Credito Parcial) JMLE",
        "n_personas": int(n), "n_items": int(m), "n_categorias": int(K),
        "items": items,
        "personas": [{"idx": i, "theta": round(float(theta[i]), 3),
                      "se_theta": round(float(se_theta[i]), 3),
                      "extremo": bool(persona_extrema[i])} for i in range(n)],
        "informacion_test": {"theta_grid": [round(x, 2) for x in grid.tolist()],
                             "info": [round(float(x), 3) for x in info.tolist()]},
        "umbrales_desordenados": [j + 1 for j in range(m) if not items[j]["umbrales_ordenados"]],
    }


def curvas_categoria(delta_j, theta_grid=None) -> dict:
    """Probabilidad de cada categoria a lo largo de theta (para graficar el funcionamiento
    de un item PCM). Devuelve la grilla y una curva por categoria."""
    grid = np.linspace(-4, 4, 41) if theta_grid is None else np.asarray(theta_grid, float)
    P = _probs_item(grid, np.asarray(delta_j, float))
    return {"theta_grid": [round(float(x), 2) for x in grid.tolist()],
            "curvas": [[round(float(v), 3) for v in P[:, k].tolist()] for k in range(P.shape[1])]}
