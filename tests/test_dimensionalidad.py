"""
Test de I7 - Dimensionalidad y fiabilidad ampliada.

Validacion contra resultados conocidos (sin cajas negras):
  - alpha coincide EXACTO con la forma matricial de covarianza (camino independiente).
  - el analisis paralelo recupera el numero de factores PLANTADO (1 y 2).
  - KMO alto en datos factorables, bajo en items independientes.
  - la EFA agrupa los items por su factor de origen.
  - el veredicto de unidimensionalidad distingue 1 factor de 2.
"""
from __future__ import annotations

import numpy as np

from app.services import dimensionalidad_service as dz


def _un_factor(seed=1, n=400, k=6, carga=0.7):
    rng = np.random.default_rng(seed)
    f = rng.standard_normal(n)
    u = rng.standard_normal((n, k))
    return carga * f[:, None] + np.sqrt(1 - carga ** 2) * u


def _dos_factores(seed=2, n=400, carga=0.7):
    rng = np.random.default_rng(seed)
    f1, f2 = rng.standard_normal(n), rng.standard_normal(n)
    u = rng.standard_normal((n, 6))
    cols = []
    for j in range(6):
        f = f1 if j < 3 else f2
        cols.append(carga * f + np.sqrt(1 - carga ** 2) * u[:, j])
    return np.column_stack(cols)


def _independientes(seed=3, n=400, k=6):
    return np.random.default_rng(seed).standard_normal((n, k))


def test_alpha_coincide_con_forma_matricial():
    X = _un_factor()
    a = dz.alpha_cronbach(X)["alpha"]
    C = np.cov(X, rowvar=False)
    k = X.shape[1]
    a_ref = k / (k - 1) * (1 - np.trace(C) / C.sum())     # forma matricial, camino independiente
    assert abs(a - round(float(a_ref), 3)) < 1e-3


def test_alpha_sube_con_items_mas_correlacionados():
    baja = dz.alpha_cronbach(_un_factor(carga=0.4))["alpha"]
    alta = dz.alpha_cronbach(_un_factor(carga=0.8))["alpha"]
    assert alta > baja
    assert 0 <= baja <= 1 and 0 <= alta <= 1


def test_analisis_paralelo_recupera_un_factor():
    pa = dz.analisis_paralelo(_un_factor())
    assert pa["n_factores_sugeridos"] == 1


def test_analisis_paralelo_recupera_dos_factores():
    pa = dz.analisis_paralelo(_dos_factores())
    assert pa["n_factores_sugeridos"] == 2


def test_analisis_paralelo_es_determinista():
    X = _un_factor()
    assert dz.analisis_paralelo(X, seed=17) == dz.analisis_paralelo(X, seed=17)


def test_kmo_alto_en_factorable_bajo_en_independiente():
    kmo_fac = dz.kmo(dz.matriz_correlacion(_un_factor()))["kmo"]
    kmo_ind = dz.kmo(dz.matriz_correlacion(_independientes()))["kmo"]
    assert kmo_fac > 0.7
    assert kmo_ind < 0.6


def test_bartlett_factorable_en_un_factor():
    R = dz.matriz_correlacion(_un_factor())
    b = dz.bartlett_esfericidad(R, 400)
    assert b["factorable"] is True and b["p_value"] < 0.05


def test_efa_agrupa_items_por_factor():
    R = dz.matriz_correlacion(_dos_factores())
    f = dz.efa(R, 2)
    cargas = np.array(f["cargas"])
    dominante = np.argmax(np.abs(cargas), axis=1)          # a que factor carga mas cada item
    # los items 0-2 comparten factor; 3-5 comparten el otro; y son distintos entre grupos
    assert len(set(dominante[:3])) == 1
    assert len(set(dominante[3:])) == 1
    assert dominante[0] != dominante[3]


def test_omega_en_rango_y_cerca_de_alpha_unidim():
    X = _un_factor(carga=0.75)
    om = dz.omega_mcdonald(dz.matriz_correlacion(X))["omega"]
    al = dz.alpha_cronbach(X)["alpha"]
    assert 0 <= om <= 1
    assert abs(om - al) < 0.1                               # congenericos: cercanos


def test_veredicto_unidimensional_en_un_factor():
    rep = dz.analizar_dimensionalidad(_un_factor(), dicotomico=False)
    assert rep["unidimensional"] is True
    assert "UNIDIMENSIONAL" in rep["veredicto"]
    assert rep["n_factores"]["n_factores_sugeridos"] == 1


def test_veredicto_multidimensional_en_dos_factores():
    rep = dz.analizar_dimensionalidad(_dos_factores(), dicotomico=False)
    assert rep["unidimensional"] is False
    assert rep["n_factores"]["n_factores_sugeridos"] == 2
    assert "MULTIDIMENSIONAL" in rep["veredicto"]


def test_veredicto_dicotomico_usa_analisis_paralelo():
    # Datos Rasch-like dicotomicos: phi atenua la varianza, pero PA detecta 1 factor ->
    # el veredicto debe declararlo unidimensional con fuerza 'moderada' (no bloquear por umbral).
    rng = np.random.default_rng(42)
    n, k = 300, 8
    theta = rng.normal(0, 1, n); dif = np.linspace(-1.5, 1.5, k)
    P = 1 / (1 + np.exp(-(theta[:, None] - dif[None, :])))
    X = (rng.random((n, k)) < P).astype(float)
    rep = dz.analizar_dimensionalidad(X, dicotomico=True)
    assert rep["n_factores"]["n_factores_sugeridos"] == 1
    assert rep["unidimensional"] is True
    assert "moderada" in rep["fuerza_evidencia"] or "fuerte" in rep["fuerza_evidencia"]
    assert "tetracorica" in rep["fuerza_evidencia"] or rep["fuerza_evidencia"] == "fuerte"


def test_kr20_dicotomico_razonable():
    X = (_un_factor(carga=0.7) > 0).astype(float)           # dicotomiza
    val = dz.kr20(X)["kr20"]
    assert 0.5 < val <= 1.0


def test_icc_positiva_en_un_factor():
    icc = dz.icc_2k(_un_factor(carga=0.7))
    assert icc["icc_2_k"] > 0.5
    assert -1 <= icc["icc_2_1"] <= 1
