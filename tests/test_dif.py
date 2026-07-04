"""
Test del motor DIF (I2). Valida que detecta un item con sesgo plantado y deja limpios
los items sin DIF, con Mantel-Haenszel y regresion logistica.
"""
from __future__ import annotations

import numpy as np
from scipy.special import expit

from app.services import dif_service as dif


def _cohorte_con_dif():
    """
    120 personas, 8 items, 2 grupos (A/B) equilibrados en habilidad.
    El item 4 tiene DIF UNIFORME: a igual habilidad, el grupo B lo acierta mas
    (favorece a B). El resto no tiene DIF.
    """
    rng = np.random.default_rng(11)
    n, k = 120, 8
    theta = rng.normal(0, 1, n)
    grupo = np.array(["A", "B"])[rng.integers(0, 2, n)]
    dif_item = 3  # indice 0-based del item con DIF
    b = np.linspace(-1, 1, k)
    X = np.zeros((n, k), int)
    for j in range(k):
        ventaja = 0.0
        p = expit(theta - b[j])
        if j == dif_item:
            # +1.3 logits de ventaja para el grupo B a igual habilidad
            p = expit(theta - b[j] + np.where(grupo == "B", 1.3, 0.0))
        X[:, j] = (rng.random(n) < p).astype(int)
    return X, grupo, theta


def test_detecta_item_con_dif():
    X, grupo, theta = _cohorte_con_dif()
    R = dif.analizar_dif(X, grupo, theta, etiqueta_focal="B")
    assert 4 in R["items_con_dif"], "debe detectar DIF en el item 4 (plantado)"
    it4 = next(r for r in R["items"] if r["item"] == 4)
    assert it4["clase"] in ("B", "C")
    # MH debe favorecer al grupo focal (B), que fue ventajado
    assert it4["mh"]["favorece"] == "focal"


def test_items_sin_dif_quedan_limpios():
    X, grupo, theta = _cohorte_con_dif()
    R = dif.analizar_dif(X, grupo, theta, etiqueta_focal="B")
    # a lo sumo 1-2 falsos positivos por azar; el item 4 debe estar y no todos marcados
    assert len(R["items_con_dif"]) <= 3
    assert 4 in R["items_con_dif"]


def test_mantel_haenszel_estructura():
    X, grupo, theta = _cohorte_con_dif()
    g = (grupo == "B").astype(int)
    mh = dif.mantel_haenszel(X[:, 3], g, theta)
    for campo in ("alpha", "delta", "chi2", "p", "clase_ets", "favorece"):
        assert campo in mh


def test_logistica_disponible_y_tipo():
    X, grupo, theta = _cohorte_con_dif()
    g = (grupo == "B").astype(int)
    lr = dif.logistica_dif(X[:, 3], g, theta)
    assert lr.get("disponible") is True
    assert lr["tipo"] in ("uniforme", "no_uniforme", "sin_dif")


def test_requiere_dos_grupos():
    X = np.random.default_rng(1).integers(0, 2, (20, 4))
    grupo = np.array(["A"] * 20)
    try:
        dif.analizar_dif(X, grupo, X.sum(1))
        assert False, "debe exigir 2 grupos"
    except ValueError:
        pass
