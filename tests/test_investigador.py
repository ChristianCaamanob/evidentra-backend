"""
Test del modulo Investigador (orquestacion + interpretacion data-driven).
"""
from __future__ import annotations

import numpy as np

from app.services import curso_stats_service as css
from app.services import irt_service as irt
from app.services import investigador_service as inv


def _caso():
    """8 items, 20 alumnos. Item 8 es 'malo': lo aciertan los de bajo puntaje (discrim. negativa)."""
    rng = np.random.default_rng(3)
    n, k = 20, 8
    hab = np.linspace(-1.5, 1.5, n)
    dif = np.linspace(-1.2, 1.2, k)
    from scipy.special import expit
    P = expit(hab[:, None] - dif[None, :])
    X = (rng.random((n, k)) < P).astype(int)
    # item 8 (indice 7) invertido: lo aciertan los de menor habilidad
    X[:, 7] = (hab < np.median(hab)).astype(int)
    pauta = {i + 1: "A" for i in range(k)}
    alumnos = []
    for p in range(n):
        resp = {i + 1: ("A" if X[p, i] == 1 else "B") for i in range(k)}
        alumnos.append({"student_id": f"S{p+1:02d}", "respuestas": resp})
    te = {i + 1: {"ra": f"RA{(i % 3) + 1}", "bloom": "Comprension", "unidad": "U1"} for i in range(k)}
    return alumnos, pauta, te, X


def _analisis():
    alumnos, pauta, te, X = _caso()
    ctt = css.analizar_evaluacion(alumnos, pauta, te_tags=te)
    rasch = irt.estimar_rasch(X)
    return inv.analizar(ctt, rasch)


def test_estructura_completa():
    A = _analisis()
    for k in ("meta", "clasica", "irt", "interpretacion", "codebook", "dataset_largo"):
        assert k in A
    I = A["interpretacion"]
    for k in ("fiabilidad", "targeting", "precision", "jerarquia_dificultad", "items_a_revisar"):
        assert k in I
        if k != "items_a_revisar":
            assert I[k]["texto"]  # interpretacion generada, no vacia


def test_flag_item_malo():
    A = _analisis()
    flags = A["interpretacion"]["items_a_revisar"]
    item8 = next((f for f in flags if f["item"] == 8), None)
    assert item8 is not None, "el item con discriminacion negativa debe quedar marcado"
    assert item8["severidad"] == "alta"
    assert any("negativa" in m for m in item8["motivos"])


def test_targeting_detecta_delta():
    A = _analisis()
    tg = A["interpretacion"]["targeting"]
    assert "delta" in tg and isinstance(tg["delta"], (int, float))
    assert "media_theta" in tg and "media_b" in tg


def test_codebook_documenta_variables():
    A = _analisis()
    vars_ = {c["variable"] for c in A["codebook"]}
    assert any("theta" in v for v in vars_)
    assert any("b" == v or v.startswith("b") for v in vars_)
    assert any("correcto" in v for v in vars_)


def test_meta_advierte_por_instrumento():
    A = _analisis()
    assert "instrumento" in A["meta"]["nota"].lower()
