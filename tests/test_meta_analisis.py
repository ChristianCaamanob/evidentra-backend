"""Metaanálisis (Fase D): efectos aleatorios, heterogeneidad, Egger, utilidades."""
import math
from app.services import meta_analisis_service as M


def test_hedges_g():
    g = M.hedges_g(10, 2, 30, 8, 2, 30)   # d≈1.0, corregido ~0.987
    assert 0.95 < g["y"] < 1.0 and g["v"] > 0


def test_ln_or_conocido():
    r = M.ln_or(20, 100, 10, 100)          # OR=2.25 -> ln=0.8109; var=0.1736
    assert abs(r["y"] - 0.8109) < 0.001 and abs(r["v"] - 0.17361) < 0.001


def test_or_con_cero_usa_correccion():
    r = M.ln_or(0, 50, 10, 50)             # cero -> corrección de continuidad, no explota
    assert r["y"] < 0 and math.isfinite(r["v"])


def test_fisher_z():
    r = M.fisher_z(0.5, 28)
    assert abs(r["y"] - 0.5493) < 0.001 and abs(r["v"] - 1 / 25) < 1e-9


def test_sintesis_efectos_aleatorios():
    est = [{"y": 0.10, "v": 0.02}, {"y": 0.30, "v": 0.03}, {"y": 0.35, "v": 0.015},
           {"y": 0.65, "v": 0.04}, {"y": 0.45, "v": 0.025}]
    r = M.sintetizar(est, "smd")
    assert r["k"] == 5
    assert 0.33 < r["combinado"]["estimador"] < 0.36
    # HKSJ debe ser MÁS ancho que el normal (t vs z)
    hk = r["combinado"]["ic95_hksj"]; nm = r["combinado"]["ic95_normal"]
    assert hk[0] < nm[0] and hk[1] > nm[1]
    assert 25 < r["heterogeneidad"]["I2"] < 40
    assert r["heterogeneidad"]["nivel"] == "moderada"
    assert r["combinado"]["intervalo_prediccion"] is not None
    assert abs(sum(f["peso_pct"] for f in r["forest"]) - 100) < 0.5


def test_menos_de_dos_estudios_error():
    r = M.sintetizar([{"y": 0.2, "v": 0.01}], "smd")
    assert "error" in r


def test_t_y_p_valores():
    assert abs(M._t_two_sided_p(2.2, 10) - 0.0524) < 0.002
    assert abs(M._t_quantile(0.975, 10) - 2.228) < 0.01


def test_egger_detecta_simetria():
    # Efectos simétricos -> sin sesgo evidente
    est = [{"y": 0.30, "v": 0.01}, {"y": 0.32, "v": 0.02}, {"y": 0.28, "v": 0.04},
           {"y": 0.31, "v": 0.08}]
    r = M.sintetizar(est, "smd")
    assert r["egger"] is not None and r["egger"]["sesgo_probable"] is False
