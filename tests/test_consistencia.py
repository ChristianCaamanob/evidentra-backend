"""Consistencia mixed-methods (Fase C): κ de Cohen, Wilson, multilabel."""
from app.services import consistencia_service as C


def test_kappa_acuerdo_perfecto():
    a = ["x", "y", "z", "x"]
    assert C.cohen_kappa(a, a) == 1.0


def test_kappa_conocido():
    # Ejemplo clásico 2x2: a=[1,1,0,0,1,0], b=[1,0,0,0,1,0]
    a = [1, 1, 0, 0, 1, 0]
    b = [1, 0, 0, 0, 1, 0]
    k = C.cohen_kappa(a, b)
    # po=5/6=.833; pe: pa1=3/6,.pb1=2/6 -> pe=(.5*.333)+(.5*.667)=.5 ; κ=(.833-.5)/.5=.667
    assert abs(k - 0.667) < 0.01
    assert C.interpretar_kappa(k) == "sustancial"


def test_interpretar_bandas():
    assert C.interpretar_kappa(-0.1) == "peor que el azar"
    assert C.interpretar_kappa(0.15) == "leve"
    assert C.interpretar_kappa(0.35) == "aceptable"
    assert C.interpretar_kappa(0.5) == "moderado"
    assert C.interpretar_kappa(0.9) == "casi perfecto"


def test_wilson_ci():
    lo, hi = C.wilson_ci(50, 100)
    assert lo < 50.0 < hi and 39 < lo < 41 and 59 < hi < 61   # ~[40.2, 59.8]
    assert C.wilson_ci(0, 0) == [0.0, 0.0]


def test_prevalencia_estable():
    grande = C.prevalencia_estable(150, 500)   # n grande -> IC estrecho
    chico = C.prevalencia_estable(3, 10)       # n chico -> IC ancho
    assert grande["estable"] is True and chico["estable"] is False
    assert grande["prevalencia_pct"] == 30.0


def test_multilabel():
    sets_a = [{"c1", "c2"}, {"c1"}, {"c3"}, set()]
    sets_b = [{"c1", "c2"}, {"c1"}, {"c3"}, {"c1"}]
    r = C.consistencia_multilabel(sets_a, sets_b, ["c1", "c2", "c3"])
    assert r["n"] == 4
    assert r["acuerdo_exacto_pct"] == 75.0        # 3 de 4 coinciden exacto
    assert r["kappa_por_codigo"]["c2"] == 1.0     # c2 perfecto
    assert r["kappa_medio"] is not None
