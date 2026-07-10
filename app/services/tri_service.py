"""
Fase 3 del pipeline Investigador — Teoria de Respuesta al Item (extensiones).

Rasch (1PL), PCM y MFRM ya existen (validados vs girth). Aqui se agrega:
  - modelo 2PL (discriminacion libre por item) via girth (MML), validado
  - comparacion de modelos 1PL vs 2PL por log-verosimilitud marginal, AIC y BIC
    (misma cuadratura para ambos -> comparables) -> decide si la discriminacion varia
  - independencia local: Q3 de Yen (residuos del 2PL)

Estimacion MML con girth (libreria de referencia). Cuadratura normal estandar para la LL
marginal. Agregado y seudonimizado (G2); no altera notas (G1).
"""
from __future__ import annotations

import numpy as np

from app.core.errors import conflict


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), d)


def _nodos(n=61, lo=-5.0, hi=5.0):
    theta = np.linspace(lo, hi, n)
    w = np.exp(-0.5 * theta ** 2)
    w = w / w.sum()                       # pesos ~ N(0,1) normalizados
    return theta, w


def _ll_marginal(X, a, b, theta, w):
    """Log-verosimilitud marginal de un modelo 2PL/1PL dicotomico: P=1/(1+exp(-a(θ-b)))."""
    a = np.asarray(a, float).reshape(1, -1)          # (1,k)
    b = np.asarray(b, float).reshape(1, -1)
    ll = 0.0
    for i in range(X.shape[0]):
        xi = X[i, :]
        m = ~np.isnan(xi)
        if not m.any():
            continue
        z = a[:, m] * (theta.reshape(-1, 1) - b[:, m])   # (n_nodos, k)
        P = 1.0 / (1.0 + np.exp(-z))
        P = np.clip(P, 1e-9, 1 - 1e-9)
        xi_m = xi[m].reshape(1, -1)
        logp = xi_m * np.log(P) + (1 - xi_m) * np.log(1 - P)    # (n_nodos,k)
        Li = np.exp(logp.sum(axis=1))                          # (n_nodos,)
        marg = float(np.sum(Li * w))
        ll += np.log(max(marg, 1e-300))
    return ll


def _aic_bic(ll, p, n):
    return -2 * ll + 2 * p, -2 * ll + p * np.log(n)


def comparar_modelos(X) -> dict:
    """Ajusta 1PL y 2PL (girth), compara por AIC/BIC y devuelve los parametros 2PL + Q3."""
    import girth
    X = np.asarray(X, float)
    Xc = X[~np.isnan(X).any(axis=1)]
    n, k = Xc.shape
    if n < 30 or k < 4:
        raise conflict("Datos insuficientes para TRI (se recomiendan >=30 personas y >=4 items).")
    data = Xc.astype(int).T                    # girth: item x persona
    theta, w = _nodos()

    r1 = girth.onepl_mml(data)
    a1 = float(np.ravel(r1["Discrimination"])[0])
    b1 = np.ravel(r1["Difficulty"])
    ll1 = _ll_marginal(Xc, np.full(k, a1), b1, theta, w)
    aic1, bic1 = _aic_bic(ll1, k + 1, n)       # 1PL: k dif + 1 discrim comun

    r2 = girth.twopl_mml(data)
    a2 = np.ravel(r2["Discrimination"]); b2 = np.ravel(r2["Difficulty"])
    ll2 = _ll_marginal(Xc, a2, b2, theta, w)
    aic2, bic2 = _aic_bic(ll2, 2 * k, n)       # 2PL: k discrim + k dif

    mejor_aic = "2PL" if aic2 < aic1 else "1PL"
    mejor_bic = "2PL" if bic2 < bic1 else "1PL"
    items = [{"item": j + 1, "discriminacion_a": _r(float(a2[j])), "dificultad_b": _r(float(b2[j])),
              "discrimina": ("alta" if a2[j] >= 1.35 else "moderada" if a2[j] >= 0.65 else "baja")}
             for j in range(k)]

    return {
        "n": int(n), "n_items": k,
        "comparacion": {
            "modelo_1PL": {"logLik": _r(ll1, 1), "AIC": _r(aic1, 1), "BIC": _r(bic1, 1), "n_param": k + 1},
            "modelo_2PL": {"logLik": _r(ll2, 1), "AIC": _r(aic2, 1), "BIC": _r(bic2, 1), "n_param": 2 * k},
            "delta_AIC": _r(aic1 - aic2, 1), "delta_BIC": _r(bic1 - bic2, 1),
            "preferido_AIC": mejor_aic, "preferido_BIC": mejor_bic,
        },
        "items_2PL": items,
        "independencia_local": q3_yen(Xc, a2, b2, theta, w),
        "veredicto": (f"El 2PL ajusta mejor (AIC y BIC): la discriminacion VARIA entre items."
                      if (mejor_aic == "2PL" and mejor_bic == "2PL")
                      else f"El 1PL (Rasch) es suficiente: discriminacion homogenea (respaldado por BIC)."
                      if mejor_bic == "1PL" else "Evidencia mixta entre 1PL y 2PL."),
        "nota": "Estimacion MML (girth). AIC/BIC menores = mejor; BIC penaliza mas la complejidad. "
                "3PL omitido: el parametro de adivinacion no se identifica de forma estable aqui.",
    }


def q3_yen(X, a, b, theta, w) -> dict:
    """Q3 de Yen: correlacion de los residuos del 2PL entre pares de items. |Q3|>0.2 sugiere
    dependencia local (viola el supuesto de independencia condicional)."""
    X = np.asarray(X, float); n, k = X.shape
    a = np.ravel(a); b = np.ravel(b)
    # habilidad EAP por persona
    Z = a.reshape(1, -1) * (theta.reshape(-1, 1) - b.reshape(1, -1))
    P = 1.0 / (1.0 + np.exp(-Z))
    P = np.clip(P, 1e-9, 1 - 1e-9)
    eap = np.empty(n)
    for i in range(n):
        xi = X[i]; m = ~np.isnan(xi)
        logp = (xi[m].reshape(1, -1) * np.log(P[:, m]) + (1 - xi[m]).reshape(1, -1) * np.log(1 - P[:, m])).sum(axis=1)
        post = np.exp(logp - logp.max()) * w
        post = post / post.sum()
        eap[i] = float(np.sum(theta * post))
    # residuos observado - esperado en la habilidad EAP
    Pe = 1.0 / (1.0 + np.exp(-(a.reshape(1, -1) * (eap.reshape(-1, 1) - b.reshape(1, -1)))))
    resid = X - Pe
    R = np.corrcoef(resid, rowvar=False)
    tri = R[np.triu_indices(k, 1)]
    tri = tri[~np.isnan(tri)]
    n_dep = int(np.sum(np.abs(tri) > 0.2))
    return {"q3_max_abs": _r(float(np.max(np.abs(tri))) if tri.size else None),
            "q3_medio": _r(float(np.mean(tri)) if tri.size else None),
            "pares_dependientes": n_dep, "n_pares": int(tri.size),
            "veredicto": ("independencia local sostenida" if n_dep == 0
                          else f"{n_dep} par(es) con posible dependencia local (|Q3|>0,2)"),
            "nota": "Q3 de Yen sobre residuos del 2PL; |Q3|>0,2 = revisar dependencia entre items."}
