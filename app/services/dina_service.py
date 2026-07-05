"""
I9 - Diagnostico cognitivo (CDM): modelo DINA por EM.

A diferencia de la TRI (una habilidad continua), los modelos de diagnostico cognitivo
entregan un PERFIL de dominio: para cada estudiante, que ATRIBUTOS (destrezas) domina y
cuales no. Es lo que convierte una nota en un diagnostico accionable -"domina interpretar
graficos pero no inferir causalidad"- y orienta la remediacion.

Modelo DINA (Deterministic Inputs, Noisy "And" gate; Junker & Sijtsma, 2001):
  - Q-matrix (item x atributo): que atributos exige cada item.
  - Respuesta ideal eta_pj = 1 si el estudiante domina TODOS los atributos del item j
    (compuerta AND), 0 si le falta alguno.
  - Dos parametros por item:
        slip s_j     = P(errar | domina todo)      -> desliz pese a saber
        guessing g_j = P(acertar | NO domina todo) -> acierto por azar
    P(X_pj=1 | perfil) = (1 - s_j)^eta * g_j^(1-eta).
  - IDI_j = 1 - s_j - g_j: cuanto discrimina el item entre quien domina y quien no.

Estimacion por Esperanza-Maximizacion (EM) marginalizando sobre las 2^K clases latentes
(perfiles de atributos). Clasificacion final por maximo a posteriori (MAP) + probabilidad
marginal de dominio por atributo.

Validado por recuperacion de parametros y perfiles plantados. Solo numpy.

Referencias: Junker & Sijtsma (2001); de la Torre (2009) DINA; Rupp, Templin & Henson (2010).
"""
from __future__ import annotations

import itertools

import numpy as np


def _perfiles(K: int) -> np.ndarray:
    """Las 2^K clases latentes (perfiles de dominio de atributos), binarias."""
    return np.array(list(itertools.product([0, 1], repeat=K)), dtype=float)


def _eta(Q: np.ndarray, perfiles: np.ndarray) -> np.ndarray:
    """Respuesta ideal (clase x item): 1 si el perfil domina TODOS los atributos del item."""
    # eta_cj = prod_k perfiles[c,k] ** Q[j,k]  -> 1 solo si domina cada atributo requerido
    C, K = perfiles.shape
    J = Q.shape[0]
    eta = np.ones((C, J))
    for k in range(K):
        req = Q[:, k]                      # items que requieren el atributo k
        tiene = perfiles[:, k]             # clases que lo dominan
        # si el item requiere k y la clase no lo tiene -> eta=0
        eta *= np.where(req[None, :] == 1, tiene[:, None], 1.0)
    return eta


def estimar_dina(X: np.ndarray, Q: np.ndarray, max_iter: int = 300, tol: float = 1e-5,
                 atributos: list[str] | None = None) -> dict:
    """
    EM para DINA. X: persona x item (0/1). Q: item x atributo (0/1).
    Devuelve parametros de item, perfiles de estudiante y prevalencia de dominio.
    """
    X = np.asarray(X, dtype=float)
    Q = np.asarray(Q, dtype=float)
    N, J = X.shape
    K = Q.shape[1]
    atributos = atributos or [f"A{k+1}" for k in range(K)]

    perfiles = _perfiles(K)                # (C, K)
    C = perfiles.shape[0]
    eta = _eta(Q, perfiles)                # (C, J)

    g = np.full(J, 0.2); s = np.full(J, 0.2)
    pi = np.full(C, 1.0 / C)               # prior sobre perfiles

    for _ in range(max_iter):
        g_old, s_old = g.copy(), s.copy()

        # P(X=1 | clase, item): (1-s) si eta=1, g si eta=0
        p1 = eta * (1 - s)[None, :] + (1 - eta) * g[None, :]     # (C, J)
        p1 = np.clip(p1, 1e-6, 1 - 1e-6)

        # --- E-step: log-verosimilitud por (persona, clase) ---
        logL = X @ np.log(p1).T + (1 - X) @ np.log(1 - p1).T     # (N, C)
        logpost = logL + np.log(pi)[None, :]
        logpost -= logpost.max(axis=1, keepdims=True)
        post = np.exp(logpost)
        post /= post.sum(axis=1, keepdims=True)                  # (N, C) posterior

        # --- M-step ---
        pi = post.mean(axis=0)
        pi = np.clip(pi, 1e-8, None); pi /= pi.sum()

        # Para cada item: separar clases que dominan (eta=1) de las que no (eta=0)
        # totales esperados y aciertos esperados en cada grupo
        # masa esperada de "domina" por item: sum_p sum_c post * eta_cj
        dom = post @ eta                    # (N, J) prob esperada de dominar cada item
        nodom = 1 - dom
        tot_dom = dom.sum(axis=0)           # (J,)
        tot_nodom = nodom.sum(axis=0)
        acierto_dom = (dom * X).sum(axis=0)
        acierto_nodom = (nodom * X).sum(axis=0)

        s = 1 - acierto_dom / np.clip(tot_dom, 1e-8, None)
        g = acierto_nodom / np.clip(tot_nodom, 1e-8, None)
        s = np.clip(s, 1e-4, 0.6); g = np.clip(g, 1e-4, 0.6)     # cotas de regularidad

        if max(np.max(np.abs(g - g_old)), np.max(np.abs(s - s_old))) < tol:
            break

    # --- clasificacion final ---
    p1 = np.clip(eta * (1 - s)[None, :] + (1 - eta) * g[None, :], 1e-6, 1 - 1e-6)
    logL = X @ np.log(p1).T + (1 - X) @ np.log(1 - p1).T
    logpost = logL + np.log(pi)[None, :]
    logpost -= logpost.max(axis=1, keepdims=True)
    post = np.exp(logpost); post /= post.sum(axis=1, keepdims=True)

    map_clase = post.argmax(axis=1)
    perfil_map = perfiles[map_clase]                            # (N, K) 0/1
    prob_dominio = post @ perfiles                              # (N, K) P(dominar atributo k)
    logvero = float((np.log((np.exp(logL) @ pi))).sum()) if C else 0.0

    prevalencia = perfil_map.mean(axis=0)                       # proporcion que domina cada atributo
    idi = 1 - s - g

    return {
        "modelo": "DINA (diagnostico cognitivo) via EM",
        "n_personas": int(N), "n_items": int(J), "n_atributos": int(K),
        "items": [{"item": j + 1, "guessing": round(float(g[j]), 3), "slip": round(float(s[j]), 3),
                   "idi": round(float(idi[j]), 3),
                   "calidad": ("buena" if idi[j] >= 0.4 else "aceptable" if idi[j] >= 0.2 else "pobre"),
                   "monotono": bool((1 - s[j]) > g[j])} for j in range(J)],
        "atributos": [{"atributo": atributos[k], "prevalencia_dominio": round(float(prevalencia[k]), 3)}
                      for k in range(K)],
        "personas": [{"idx": i, "perfil": [int(v) for v in perfil_map[i]],
                      "prob_dominio": [round(float(v), 3) for v in prob_dominio[i]],
                      "n_atributos_dominados": int(perfil_map[i].sum())} for i in range(N)],
        "log_verosimilitud": round(logvero, 2),
        "atributo_cuello_botella": atributos[int(prevalencia.argmin())],
        "gobernanza": "Diagnostico agregado y seudonimizado (G2); orienta remediacion, no altera "
                      "notas (G1). La Q-matrix es responsabilidad del docente/experto (validez de "
                      "contenido).",
    }


def perfil_legible(persona: dict, atributos: list[str]) -> str:
    """Traduce el perfil de una persona a texto: que domina y que no."""
    dom = [a for a, v in zip(atributos, persona["perfil"]) if v == 1]
    nod = [a for a, v in zip(atributos, persona["perfil"]) if v == 0]
    return f"Domina: {', '.join(dom) or '-'}. Por reforzar: {', '.join(nod) or '-'}."
