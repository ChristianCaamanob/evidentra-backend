"""Poder muestral (Fase 2.1): advertencia honesta de baja potencia por técnica."""
from app.services.poder_muestral_service import evaluar


def test_rasch_adecuado_con_200():
    r = evaluar("rasch", 250, 12)
    assert r["suficiente"] is True and r["advertencia"] is None


def test_dina_insuficiente_con_250():
    # DINA necesita ~500; 250 debe marcarse insuficiente CON advertencia (no se oculta).
    r = evaluar("dina", 250, 20)
    assert r["suficiente"] is False
    assert r["advertencia"] and "500" in r["advertencia"]


def test_tri_exige_mas_que_rasch():
    assert evaluar("tri", 300, 12)["suficiente"] is False   # 2PL pide ~500
    assert evaluar("rasch", 300, 12)["suficiente"] is True


def test_dif_usa_grupo_mas_pequeno():
    # Aunque el total sea grande, si el grupo chico < 200 -> insuficiente.
    r = evaluar("dif", 1000, n_grupo_min=120)
    assert r["suficiente"] is False and "120" in r["advertencia"]


def test_cfa_razon_sujeto_item_baja():
    # n≥200 pero razón sujeto:ítem < 5 -> se marca no suficiente por estructura inestable.
    r = evaluar("cfa", 210, 60)   # razón 3.5
    assert r["razon_sujeto_item"] == 3.5 and r["suficiente"] is False
