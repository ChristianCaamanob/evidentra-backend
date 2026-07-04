"""
Test del motor IRT / Rasch (I1).

Verifica el ordenamiento (items dificiles -> b alto; personas habiles -> theta alto),
la presencia de informacion/fiabilidad, y la coherencia con la dificultad clasica.
"""
from __future__ import annotations

import numpy as np

from app.services import irt_service as irt


def _matriz_ordenada():
    """15 personas x 5 items. Item 0 el mas facil, item 4 el mas dificil (patron Guttman ruidoso)."""
    n, k = 15, 5
    rng = np.random.default_rng(7)
    # dificultad creciente por item; habilidad creciente por persona
    dif = np.linspace(-1.5, 1.5, k)
    hab = np.linspace(-1.5, 2.0, n)
    from scipy.special import expit
    P = expit(hab[:, None] - dif[None, :])
    X = (rng.random((n, k)) < P).astype(int)
    # asegurar no-extremos: forzar variacion
    X[0, 0] = 1; X[-1, -1] = 1; X[0, -1] = 0; X[-1, 0] = 1
    return X


def test_orden_dificultad_items():
    X = _matriz_ordenada()
    out = irt.estimar_rasch(X)
    bs = [it["b"] for it in out["items"]]
    # el ultimo item (mas dificil por construccion) debe tener b mayor que el primero
    assert bs[-1] > bs[0]


def test_orden_habilidad_personas():
    X = _matriz_ordenada()
    out = irt.estimar_rasch(X)
    # persona con mas aciertos -> mayor theta
    r = X.sum(1)
    thetas = np.array([p["theta"] for p in out["personas"]])
    assert thetas[np.argmax(r)] >= thetas[np.argmin(r)]


def test_estructura_salida():
    out = irt.estimar_rasch(_matriz_ordenada())
    assert out["modelo"].startswith("Rasch")
    assert 0.0 <= out["fiabilidad"]["separacion_personas"] <= 1.0
    assert len(out["informacion_test"]["theta_grid"]) == len(out["informacion_test"]["info"])
    it0 = out["items"][0]
    for campo in ("b", "se_b", "infit_msq", "outfit_msq", "ajuste"):
        assert campo in it0


def test_b_centrado_en_cero():
    out = irt.estimar_rasch(_matriz_ordenada())
    bs = np.array([it["b"] for it in out["items"]])
    assert abs(bs.mean()) < 1e-6 or abs(float(bs.mean())) < 0.05  # identificabilidad: media(b)=0


def test_coherencia_con_dificultad_clasica():
    X = _matriz_ordenada()
    out = irt.estimar_rasch(X)
    p_clasica = X.mean(0)                       # proporcion de aciertos por item
    b = np.array([it["b"] for it in out["items"]])
    # b (dificultad) debe correlacionar negativamente con la facilidad clasica
    assert float(np.corrcoef(p_clasica, b)[0, 1]) < -0.8
