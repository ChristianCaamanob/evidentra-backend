"""
Test de I8a - PCM (Modelo de Credito Parcial).

Validacion contra referencia externa (girth.pcm_jml, misma familia de estimador) y por
recuperacion de parametros plantados.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.irt_politomico_service import estimar_pcm, curvas_categoria


def _datos_pcm(seed=3, n=400):
    girth = pytest.importorskip("girth")
    from girth.synthetic import create_synthetic_irt_polytomous as syn
    rng = np.random.default_rng(seed)
    diff = np.array([[-1.2, 0.3], [-0.2, 1.1], [-0.7, 0.6], [0.3, 1.4], [-0.4, 0.9]])
    theta = rng.normal(0, 1.2, n)
    data = syn(diff, np.ones(len(diff)), theta, model="PCM", seed=seed)  # items x personas, 1..3
    return data, data.T - 1, theta, diff


def test_pcm_valida_contra_girth():
    girth = pytest.importorskip("girth")
    data, X, theta_true, diff = _datos_pcm()
    mine = estimar_pcm(X)
    g = np.array(girth.pcm_jml(data)["Difficulty"])
    mth = np.array([it["umbrales"] for it in mine["items"]])
    mm = mth - mth.mean(); gg = g - g.mean()          # alinear localizacion
    r = np.corrcoef(mm.ravel(), gg.ravel())[0, 1]
    assert r > 0.95                                    # coincide con la referencia externa


def test_pcm_recupera_theta():
    _, X, theta_true, _ = _datos_pcm()
    mine = estimar_pcm(X)
    th = np.array([p["theta"] for p in mine["personas"]])
    assert np.corrcoef(th, theta_true)[0, 1] > 0.7


def test_pcm_recupera_orden_de_dificultad_items():
    _, X, _, diff = _datos_pcm()
    mine = estimar_pcm(X)
    dm = np.array([it["dificultad_media"] for it in mine["items"]])
    assert np.corrcoef(dm, diff.mean(axis=1))[0, 1] > 0.9


def test_pcm_detecta_umbrales_desordenados():
    # Item con categoria intermedia casi no usada -> umbrales desordenados esperables.
    rng = np.random.default_rng(1)
    n = 300
    X = rng.integers(0, 3, size=(n, 4)).astype(float)
    # item 0: fuerza 0 y 2, casi nunca 1 (categoria media colapsada)
    col = rng.random(n)
    X[:, 0] = np.where(col < 0.5, 0, 2)
    X[rng.random(n) < 0.03, 0] = 1
    rep = estimar_pcm(X)
    # el item con la categoria media vacia debe salir con umbrales desordenados
    assert 1 in rep["umbrales_desordenados"] or any(
        not it["umbrales_ordenados"] for it in rep["items"])


def test_curvas_categoria_suman_uno():
    c = curvas_categoria([-1.0, 1.0])
    P = np.array(c["curvas"])            # (K, n_grid)
    assert np.allclose(P.sum(axis=0), 1.0, atol=2e-3)   # tolerancia por redondeo a 3 decimales
    assert P.shape[0] == 3               # 3 categorias para 2 umbrales
