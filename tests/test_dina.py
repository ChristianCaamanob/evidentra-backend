"""
Test de I9 - DINA (diagnostico cognitivo).

Validacion por recuperacion de parametros y perfiles plantados:
  - guessing/slip estimados correlacionan con los verdaderos.
  - los perfiles de atributos se clasifican con alta exactitud.
  - se cumple la monotonicidad (1-s > g) y el cuello de botella se identifica.
"""
from __future__ import annotations

import numpy as np

from app.services import dina_service as di


def _Q():
    # 9 items x 3 atributos (con items de 1 y de 2 atributos, y uno de 3)
    return np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1],
        [1, 1, 0], [1, 0, 1], [0, 1, 1],
        [1, 1, 1], [1, 0, 0], [0, 1, 0],
    ], dtype=float)


def _simula(seed=0, N=600, prevalencia=(0.5, 0.5, 0.35)):
    rng = np.random.default_rng(seed)
    Q = _Q(); J, K = Q.shape
    alpha = np.column_stack([(rng.random(N) < p).astype(float) for p in prevalencia])
    g_true = rng.uniform(0.05, 0.22, J)
    s_true = rng.uniform(0.05, 0.22, J)
    eta = np.ones((N, J))
    for k in range(K):
        eta *= np.where(Q[:, k][None, :] == 1, alpha[:, k][:, None], 1.0)
    P = eta * (1 - s_true) + (1 - eta) * g_true
    X = (rng.random((N, J)) < P).astype(float)
    return X, Q, alpha, g_true, s_true


def test_recupera_guessing_y_slip():
    X, Q, alpha, g_true, s_true = _simula()
    m = di.estimar_dina(X, Q)
    g_est = np.array([it["guessing"] for it in m["items"]])
    s_est = np.array([it["slip"] for it in m["items"]])
    assert np.corrcoef(g_est, g_true)[0, 1] > 0.6
    assert np.corrcoef(s_est, s_true)[0, 1] > 0.6
    assert np.abs(g_est - g_true).mean() < 0.08
    assert np.abs(s_est - s_true).mean() < 0.08


def test_clasifica_perfiles_con_exactitud():
    X, Q, alpha, _, _ = _simula(seed=1)
    m = di.estimar_dina(X, Q)
    perf = np.array([p["perfil"] for p in m["personas"]])
    exactitud = (perf == alpha).mean()          # exactitud a nivel de atributo
    assert exactitud > 0.85


def test_monotonicidad_todos_los_items():
    X, Q, *_ = _simula(seed=2)
    m = di.estimar_dina(X, Q)
    assert all(it["monotono"] for it in m["items"])   # 1 - s > g en todos


def test_prevalencia_recuperada():
    X, Q, alpha, *_ = _simula(seed=3, prevalencia=(0.6, 0.4, 0.25))
    m = di.estimar_dina(X, Q)
    prev_est = np.array([a["prevalencia_dominio"] for a in m["atributos"]])
    prev_true = alpha.mean(axis=0)
    assert np.abs(prev_est - prev_true).max() < 0.12


def test_cuello_de_botella_es_el_menos_dominado():
    X, Q, alpha, *_ = _simula(seed=4, prevalencia=(0.7, 0.6, 0.2))   # A3 el mas escaso
    m = di.estimar_dina(X, Q)
    assert m["atributo_cuello_botella"] == "A3"


def test_perfil_legible():
    X, Q, *_ = _simula(seed=5)
    m = di.estimar_dina(X, Q)
    txt = di.perfil_legible(m["personas"][0], ["Interpretar", "Calcular", "Inferir"])
    assert "Domina:" in txt and "reforzar" in txt.lower()
