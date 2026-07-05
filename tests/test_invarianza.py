"""
Test de I8b - Invarianza de medicion de Rasch.

Validacion por recuperacion: si ambos grupos comparten las dificultades de item, la
medicion es invariante; si un item se desplaza en un grupo, ese item -y solo ese- se marca.
"""
from __future__ import annotations

import numpy as np

from app.services.invarianza_service import invarianza_rasch


def _genera(seed, dif_items, n_por_grupo=300, shift_item=None, shift=0.0):
    """Genera respuestas Rasch dicotomicas para 2 grupos con las mismas dificultades,
    salvo (opcionalmente) un item desplazado en el grupo B."""
    rng = np.random.default_rng(seed)
    k = len(dif_items)
    filas, grupos = [], []
    for g, etiqueta in enumerate(["A", "B"]):
        theta = rng.normal(0, 1, n_por_grupo)
        b = np.array(dif_items, dtype=float).copy()
        if etiqueta == "B" and shift_item is not None:
            b[shift_item] += shift
        P = 1 / (1 + np.exp(-(theta[:, None] - b[None, :])))
        X = (rng.random((n_por_grupo, k)) < P).astype(float)
        filas.append(X); grupos += [etiqueta] * n_por_grupo
    return np.vstack(filas), np.array(grupos)


def test_invariante_cuando_grupos_comparten_dificultades():
    dif = [-1.5, -0.8, -0.2, 0.3, 0.9, 1.6]
    X, g = _genera(10, dif)
    rep = invarianza_rasch(X, g)
    assert rep["correlacion_parametros"] > 0.9
    assert rep["invariante"] is True
    assert rep["items_no_invariantes"] == []


def test_marca_item_desplazado():
    dif = [-1.5, -0.8, -0.2, 0.3, 0.9, 1.6]
    X, g = _genera(11, dif, shift_item=2, shift=1.8)      # item 3 (idx 2) mas dificil en B
    rep = invarianza_rasch(X, g)
    assert 3 in rep["items_no_invariantes"]               # el item desplazado se marca
    # los demas no deberian marcarse en masa
    assert len(rep["items_no_invariantes"]) <= 2
    assert rep["invariante"] is False


def test_requiere_dos_grupos():
    dif = [-1.0, 0.0, 1.0]
    X, g = _genera(12, dif)
    g[:] = "A"
    try:
        invarianza_rasch(X, g)
        assert False, "debio exigir 2 grupos"
    except ValueError:
        pass
