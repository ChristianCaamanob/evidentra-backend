"""
I6 - MFRM (Medicion de Rasch de Multiples Facetas) para respuestas de desarrollo.

Extiende el motor de Rasch (I1, 2 facetas: persona x item) a TRES facetas:

    logit del paso k = (theta_persona - delta_item - sigma_evaluador) - tau_k

sobre categorias ordenadas (no_logrado=0, parcial=1, logrado=2) con el modelo de
escala de calificacion de Andrich (RSM). La faceta nueva -el EVALUADOR- captura la
SEVERIDAD de quien corrige. En Evalys los dos evaluadores son la IA (pre-calificacion
F2) y el DOCENTE (validacion F3): MFRM cuantifica, en logits, cuanto mas severa o
indulgente es la IA que el docente, y produce medidas JUSTAS de la habilidad del
estudiante corregidas por esa severidad.

Es el puente F -> Investigador: la trazabilidad de F3 (nivel_ia -> nivel_docente por
criterio) es exactamente el dato crudo que MFRM necesita. Con el se calibra la IA como
un "evaluador mas" y se defiende la equidad de la correccion ante acreditacion.

Referencias: Linacre (1989/1994) Many-Facet Rasch Measurement; Andrich (1978) Rating
Scale Model; Eckes (2015) Introduction to Many-Facet Rasch Measurement.

Solo numpy. Estimacion por Maxima Verosimilitud Conjunta (JMLE), como I1.
"""
from __future__ import annotations

import numpy as np

# Mapeo nivel cualitativo <-> categoria ordinal del RSM.
NIVEL_A_CAT = {"no_logrado": 0, "parcial": 1, "logrado": 2}
CAT_A_NIVEL = {v: k for k, v in NIVEL_A_CAT.items()}


def observaciones_desde_registros(registros: list[dict]) -> list[dict]:
    """
    Convierte la trazabilidad de F3 en observaciones MFRM. Cada criterio de cada alumno
    aporta DOS observaciones (mismo par persona-item, distinto evaluador): la de la IA y
    la del docente. Asi ambos quedan en la misma escala y su severidad es comparable.
    """
    obs = []
    for r in registros:
        persona = r.get("alumno") or r.get("persona") or r.get("respuesta_ref", "?").split("#")[0]
        item = r.get("criterio", "?")
        # Nivel canonico (3) si el registro trae la normalizacion de N niveles; si no, el crudo.
        niv_ia = r.get("nivel_ia_canon") or r.get("nivel_ia")
        niv_doc = r.get("nivel_docente_canon") or r.get("nivel_docente")
        if niv_ia in NIVEL_A_CAT:
            obs.append({"persona": persona, "item": item, "evaluador": "IA",
                        "categoria": NIVEL_A_CAT[niv_ia]})
        if niv_doc in NIVEL_A_CAT:
            obs.append({"persona": persona, "item": item, "evaluador": "docente",
                        "categoria": NIVEL_A_CAT[niv_doc]})
    return obs


def _sep_rel(vals: np.ndarray, ses: np.ndarray) -> float:
    """Fiabilidad de separacion de Rasch: (var verdadera) / (var observada)."""
    vals = np.asarray(vals, dtype=float)
    ses = np.asarray(ses, dtype=float)
    if len(vals) < 2:
        return 0.0
    var_obs = float(vals.var(ddof=1))
    mse = float(np.mean(ses ** 2))
    return float(max(0.0, (var_obs - mse) / var_obs)) if var_obs > mse else 0.0


def estimar_mfrm(observaciones: list[dict], n_cat: int = 3,
                 max_iter: int = 400, tol: float = 1e-4) -> dict:
    """
    Estima el MFRM (RSM de 3 facetas) por JMLE sobre una lista de observaciones
    [{persona, item, evaluador, categoria}], categoria en 0..n_cat-1.

    Identificabilidad: delta (items) y sigma (evaluadores) se centran en 0; los umbrales
    tau se centran en 0; theta (personas) absorbe la localizacion. Convencion de signo:
    sigma > 0 => evaluador SEVERO (baja la categoria esperada); sigma < 0 => INDULGENTE.
    """
    K = int(n_cat)
    cats = np.arange(K, dtype=float)
    if not observaciones:
        raise ValueError("Sin observaciones para estimar el MFRM.")

    personas = sorted({o["persona"] for o in observaciones})
    items = sorted({o["item"] for o in observaciones})
    evals = sorted({o["evaluador"] for o in observaciones})
    pi = {p: i for i, p in enumerate(personas)}
    ii = {v: i for i, v in enumerate(items)}
    ri = {v: i for i, v in enumerate(evals)}
    P, I, R = len(personas), len(items), len(evals)

    p_idx = np.array([pi[o["persona"]] for o in observaciones])
    i_idx = np.array([ii[o["item"]] for o in observaciones])
    r_idx = np.array([ri[o["evaluador"]] for o in observaciones])
    x = np.array([int(o["categoria"]) for o in observaciones], dtype=float)

    theta = np.zeros(P)
    delta = np.zeros(I)
    sigma = np.zeros(R)
    tau = np.linspace(-1.0, 1.0, K - 1) if K > 1 else np.zeros(0)
    Nk = np.array([float(np.sum(x == k)) for k in range(K)])  # conteos observados por categoria

    def _probs(th, de, si, ta):
        t = th[p_idx] - de[i_idx] - si[r_idx]                 # (N,)
        C = np.concatenate([[0.0], np.cumsum(ta)])            # (K,) umbrales acumulados
        psi = cats[None, :] * t[:, None] - C[None, :]         # (N,K)
        psi -= psi.max(axis=1, keepdims=True)
        num = np.exp(psi)
        return num / num.sum(axis=1, keepdims=True)

    def _EV(Pmat):
        E = Pmat @ cats
        V = (Pmat @ (cats ** 2)) - E ** 2
        return E, np.clip(V, 1e-9, None)

    for _ in range(max_iter):
        prev = np.concatenate([theta, delta, sigma, tau])

        E, V = _EV(_probs(theta, delta, sigma, tau))          # personas: dE/dtheta = +V
        theta += np.bincount(p_idx, weights=(x - E), minlength=P) / \
            np.clip(np.bincount(p_idx, weights=V, minlength=P), 1e-6, None)
        theta = np.clip(theta, -8, 8)

        E, V = _EV(_probs(theta, delta, sigma, tau))          # items: dE/ddelta = -V
        delta += np.bincount(i_idx, weights=(E - x), minlength=I) / \
            np.clip(np.bincount(i_idx, weights=V, minlength=I), 1e-6, None)
        delta -= delta.mean()
        delta = np.clip(delta, -8, 8)

        E, V = _EV(_probs(theta, delta, sigma, tau))          # evaluadores: dE/dsigma = -V
        sigma += np.bincount(r_idx, weights=(E - x), minlength=R) / \
            np.clip(np.bincount(r_idx, weights=V, minlength=R), 1e-6, None)
        sigma -= sigma.mean()
        sigma = np.clip(sigma, -8, 8)

        if K > 1:                                             # umbrales tau (Andrich)
            Ek = np.clip(_probs(theta, delta, sigma, tau).sum(axis=0), 1e-6, None)
            Nc = np.clip(Nk, 1e-6, None)
            for k in range(1, K):
                tau[k - 1] += (np.log(Ek[k]) - np.log(Ek[k - 1])) - \
                              (np.log(Nc[k]) - np.log(Nc[k - 1]))
            tau -= tau.mean()

        if np.max(np.abs(np.concatenate([theta, delta, sigma, tau]) - prev)) < tol:
            break

    # Ajuste e informacion finales
    Pmat = _probs(theta, delta, sigma, tau)
    E, V = _EV(Pmat)
    resid = x - E
    z2 = (resid ** 2) / V                                     # residual estandarizado^2

    def _se(idx, n):
        return 1.0 / np.sqrt(np.clip(np.bincount(idx, weights=V, minlength=n), 1e-6, None))

    se_theta, se_delta, se_sigma = _se(p_idx, P), _se(i_idx, I), _se(r_idx, R)

    def _fit(idx, n):
        outfit = np.bincount(idx, weights=z2, minlength=n) / \
            np.clip(np.bincount(idx, minlength=n), 1, None)
        infit = np.bincount(idx, weights=resid ** 2, minlength=n) / \
            np.clip(np.bincount(idx, weights=V, minlength=n), 1e-6, None)
        return outfit, infit

    out_r, in_r = _fit(r_idx, R)
    out_i, in_i = _fit(i_idx, I)

    def _cal(msq):
        if msq < 0.5: return "sobreajuste"
        if msq <= 1.5: return "productivo"
        if msq <= 2.0: return "poco_productivo"
        return "desajuste"

    evaluadores = [{
        "evaluador": evals[r],
        "severidad_logits": round(float(sigma[r]), 3),
        "se": round(float(se_sigma[r]), 3),
        "tendencia": ("severo" if sigma[r] > 0.15 else "indulgente" if sigma[r] < -0.15 else "neutral"),
        "infit_msq": round(float(in_r[r]), 2),
        "outfit_msq": round(float(out_r[r]), 2),
        "ajuste": _cal(float(in_r[r])),
    } for r in range(R)]
    evaluadores.sort(key=lambda e: e["severidad_logits"], reverse=True)

    items_out = [{
        "item": items[j], "dificultad_logits": round(float(delta[j]), 3),
        "se": round(float(se_delta[j]), 3),
        "infit_msq": round(float(in_i[j]), 2), "outfit_msq": round(float(out_i[j]), 2),
    } for j in range(I)]

    personas_out = [{
        "persona": personas[p],
        "habilidad_logits": round(float(theta[p]), 3),   # medida JUSTA (corregida por severidad)
        "se": round(float(se_theta[p]), 3),
    } for p in range(P)]

    rel_ev = _sep_rel(sigma, se_sigma)
    rango = float(sigma.max() - sigma.min()) if R > 1 else 0.0
    # Practicamente intercambiables si el rango de severidad es pequeno (<0.5 logits,
    # regla de Linacre), aunque la fiabilidad los separe estadisticamente.
    intercambiables = rango < 0.5
    return {
        "modelo": "MFRM - RSM de 3 facetas (persona x item x evaluador), JMLE",
        "n_observaciones": int(len(x)), "n_personas": P, "n_items": I, "n_evaluadores": R,
        "evaluadores": evaluadores,
        "items": items_out,
        "personas": personas_out,
        "umbrales_tau": [round(float(t), 3) for t in tau.tolist()],
        "fiabilidad_separacion_evaluadores": round(rel_ev, 3),
        "rango_severidad_logits": round(rango, 3),
        "evaluadores_intercambiables": bool(intercambiables),
        "nota_separacion": ("Los evaluadores son intercambiables en severidad (diferencia "
                            "< 0,5 logits; buena senal para la IA como corrector)."
                            if intercambiables else
                            "Los evaluadores difieren de forma practica y fiable en severidad "
                            "(>= 0,5 logits); conviene corregir por evaluador."),
    }


def reporte_severidad_ia(registros: list[dict], escala_max: int = 2) -> dict:
    """
    Puente F -> Investigador: toma la trazabilidad de F3 y devuelve, en lenguaje del
    docente, cuanto se desvia la IA del docente en severidad, mas la interpretacion.

    escala_max: categoria maxima (2 => logrado). Convierte los logits a un efecto
    aproximado en la escala de niveles para leerlo sin logits.
    """
    obs = observaciones_desde_registros(registros)
    modelo = estimar_mfrm(obs)
    por_nombre = {e["evaluador"]: e for e in modelo["evaluadores"]}
    ia, doc = por_nombre.get("IA"), por_nombre.get("docente")
    if not ia or not doc:
        return {"disponible": False, "motivo": "Faltan registros de IA y/o docente.",
                "modelo": modelo}

    dif = round(ia["severidad_logits"] - doc["severidad_logits"], 3)
    if dif > 0.15:
        veredicto = "La IA es MAS SEVERA que el docente (tiende a subcalificar)."
    elif dif < -0.15:
        veredicto = "La IA es MAS INDULGENTE que el docente (tiende a sobrecalificar)."
    else:
        veredicto = "La IA y el docente son equivalentes en severidad: la IA esta bien calibrada."

    return {
        "disponible": True,
        "severidad_ia_logits": ia["severidad_logits"],
        "severidad_docente_logits": doc["severidad_logits"],
        "diferencia_logits": dif,
        "direccion": "ia_mas_severa" if dif > 0 else "ia_mas_indulgente" if dif < 0 else "equivalente",
        "calibrada": abs(dif) <= 0.15,
        "veredicto": veredicto,
        "ajuste_ia": {"infit_msq": ia["infit_msq"], "outfit_msq": ia["outfit_msq"],
                      "estado": ia["ajuste"]},
        "fiabilidad_separacion_evaluadores": modelo["fiabilidad_separacion_evaluadores"],
        "recomendacion": (
            "Diferencia despreciable: se puede confiar en la pre-calificacion de la IA con "
            "auditoria ligera." if abs(dif) <= 0.15 else
            "Diferencia relevante: corregir el umbral de la IA en esa direccion o subir el nivel "
            "de auditoria hasta recalibrar."),
        "gobernanza": "Diagnostico del modulo Investigador; no altera notas (G1). Datos "
                      "seudonimizados (G2).",
        "modelo": modelo,
    }
