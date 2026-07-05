"""
Test del motor MFRM (I6): recuperacion de severidades plantadas + puente desde F3.

Estrategia de validacion (como en Rasch/DIF): se GENERAN datos con un modelo RSM de 3
facetas de parametros conocidos -en particular un evaluador severo, uno neutral y uno
indulgente- y se comprueba que estimar_mfrm recupera el ORDEN y el signo de la severidad.
"""
from __future__ import annotations

import numpy as np

from app.services import mfrm_service as mf


def _genera_datos(seed=7, P=120, I=6, sever=(0.9, 0.0, -0.9)):
    """Genera observaciones RSM de 3 facetas con severidades de evaluador plantadas."""
    rng = np.random.default_rng(seed)
    theta = rng.normal(0, 1.2, P)
    delta = np.linspace(-1.0, 1.0, I)
    tau = np.array([-0.5, 0.5])          # umbrales verdaderos (suman 0)
    cats = np.arange(3)
    C = np.concatenate([[0.0], np.cumsum(tau)])
    obs = []
    for p in range(P):
        for i in range(I):
            for r, s in enumerate(sever):
                t = theta[p] - delta[i] - s
                psi = cats * t - C
                psi -= psi.max()
                pr = np.exp(psi); pr /= pr.sum()
                k = int(rng.choice(3, p=pr))
                obs.append({"persona": f"p{p}", "item": f"i{i}",
                            "evaluador": f"r{r}", "categoria": k})
    return obs, sever


def test_recupera_orden_de_severidad():
    obs, sever = _genera_datos()
    m = mf.estimar_mfrm(obs)
    # ordenados de mas severo a menos severo por el modelo
    orden = [e["evaluador"] for e in m["evaluadores"]]
    assert orden == ["r0", "r1", "r2"], orden           # r0 severo -> r2 indulgente

    sev = {e["evaluador"]: e["severidad_logits"] for e in m["evaluadores"]}
    assert sev["r0"] > sev["r1"] > sev["r2"]             # monotonia estricta
    assert sev["r0"] > 0.3 and sev["r2"] < -0.3          # signo correcto


def test_correlacion_con_severidad_verdadera():
    obs, sever = _genera_datos()
    m = mf.estimar_mfrm(obs)
    sev = {e["evaluador"]: e["severidad_logits"] for e in m["evaluadores"]}
    est = np.array([sev[f"r{r}"] for r in range(len(sever))])
    verdad = np.array(sever)
    r = np.corrcoef(est, verdad)[0, 1]
    assert r > 0.98                                      # recuperacion casi perfecta del orden/magnitud


def test_evaluadores_neutrales_no_se_marcan():
    # Tres evaluadores IGUALES (misma severidad): no debe inventar diferencias.
    obs, _ = _genera_datos(seed=3, sever=(0.0, 0.0, 0.0))
    m = mf.estimar_mfrm(obs)
    sev = [abs(e["severidad_logits"]) for e in m["evaluadores"]]
    assert max(sev) < 0.35                               # todos cerca de 0
    assert m["rango_severidad_logits"] < 0.5            # practicamente sin diferencia
    assert m["evaluadores_intercambiables"] is True      # veredicto practico


def test_puente_desde_registros_f3():
    # Registros estilo F3: la IA sistematicamente mas dura que el docente.
    registros = []
    niveles_doc = ["logrado", "logrado", "parcial", "logrado", "parcial", "logrado"]
    for a in range(15):
        for c, nd in enumerate(niveles_doc):
            # la IA baja un escalon la mitad de las veces (mas severa)
            ni = {"logrado": "parcial", "parcial": "no_logrado"}.get(nd, nd) if (a + c) % 2 == 0 else nd
            registros.append({"alumno": f"al{a}", "criterio": f"crit{c}",
                              "nivel_ia": ni, "nivel_docente": nd})
    rep = mf.reporte_severidad_ia(registros)
    assert rep["disponible"] is True
    assert rep["direccion"] == "ia_mas_severa"
    assert rep["diferencia_logits"] > 0
    assert "severa" in rep["veredicto"].lower()


def test_ia_calibrada_cuando_coincide():
    # IA == docente siempre: debe salir "calibrada".
    registros = []
    niveles = ["logrado", "parcial", "logrado", "no_logrado", "parcial"]
    for a in range(15):
        for c, nv in enumerate(niveles):
            registros.append({"alumno": f"al{a}", "criterio": f"crit{c}",
                              "nivel_ia": nv, "nivel_docente": nv})
    rep = mf.reporte_severidad_ia(registros)
    assert rep["calibrada"] is True
    assert rep["direccion"] == "equivalente"
