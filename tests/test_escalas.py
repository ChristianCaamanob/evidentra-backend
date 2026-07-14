"""
Registro de escalas internacionales: un MISMO % de logro se traduce a la escala de
cada pais, y la linea de aprobacion se mueve con la exigencia (50/60/70).

El invariante es el % de logro; la exigencia decide donde cae el aprobado y la escala
como se renderiza. Chile debe quedar bit-a-bit identico a la implementacion previa.
"""
from __future__ import annotations

import pytest

from app.services.result_service import (
    calculate_grade, convertir_multiescala, listar_escalas, GRADING_SCALES,
)

# Escalas lineales y su valor de aprobacion (piso, aprueba, techo/reprueba).
LINEALES = {
    "chile_1_7": 4.0, "mexico_10": 6.0, "colombia_5": 3.0, "brasil_10": 6.0,
    "espana_10": 5.0, "francia_20": 10.0, "europe_10": 5.0, "alemania_5": 4.0,
}
EXIGENCIAS = [50.0, 60.0, 70.0]


# ── el corte: en la exigencia exacta, cada escala da su nota de aprobacion ──────────
@pytest.mark.parametrize("ex", EXIGENCIAS)
@pytest.mark.parametrize("escala,nota_aprueba", LINEALES.items())
def test_en_la_exigencia_da_la_nota_de_aprobacion(escala, nota_aprueba, ex):
    grade, _, passed = calculate_grade(ex, escala, ex)   # logro == exigencia
    assert grade == pytest.approx(nota_aprueba), f"{escala}@{ex}%"
    assert passed is True


@pytest.mark.parametrize("ex", EXIGENCIAS)
@pytest.mark.parametrize("escala", LINEALES.keys())
def test_bajo_la_exigencia_reprueba(escala, ex):
    # Con margen claro reprueba en toda escala (Alemania tiene pendiente suave en el
    # tramo de reprobacion, por eso se usa un margen holgado; el borde fino se prueba aparte).
    _, _, passed = calculate_grade(ex - 10, escala, ex)
    assert passed is False


def test_redondeo_medio_arriba_en_el_borde():
    # Comportamiento ELEGIDO: 1 decimal, redondeo estandar (no bancario). La aprobacion
    # sigue a la nota redondeada -> un logro que redondea a 4,0 aprueba (no "4,0 reprobado").
    g, lbl, passed = calculate_grade(59.5, "chile_1_7", 60.0)   # 3,975 -> 4,0
    assert lbl == "4.0" and g == 4.0 and passed is True
    # Y un caso lejano del borde sigue reprobando con su decimal:
    g2, lbl2, passed2 = calculate_grade(50.0, "chile_1_7", 60.0)  # 3,5
    assert lbl2 == "3.5" and passed2 is False


# ── extremos: 0% al piso, 100% al techo (o al optimo en Alemania) ───────────────────
@pytest.mark.parametrize("ex", EXIGENCIAS)
def test_extremos_escala_high(ex):
    # Chile: 0% -> 1.0 ; 100% -> 7.0 (independiente de la exigencia)
    assert calculate_grade(0.0, "chile_1_7", ex)[0] == 1.0
    assert calculate_grade(100.0, "chile_1_7", ex)[0] == 7.0
    # Francia 0-20
    assert calculate_grade(0.0, "francia_20", ex)[0] == 0.0
    assert calculate_grade(100.0, "francia_20", ex)[0] == 20.0


@pytest.mark.parametrize("ex", EXIGENCIAS)
def test_alemania_es_invertida(ex):
    # 100% de logro -> 1,0 (optimo); 0% -> 5,0 (reprueba); en la exigencia -> 4,0.
    assert calculate_grade(100.0, "alemania_5", ex)[0] == 1.0
    assert calculate_grade(0.0, "alemania_5", ex)[0] == 5.0
    assert calculate_grade(ex, "alemania_5", ex)[0] == 4.0
    # monotonia inversa: mas logro -> nota menor (mejor)
    g_bajo = calculate_grade(ex + 5, "alemania_5", ex)[0]
    g_alto = calculate_grade(ex + 20, "alemania_5", ex)[0]
    assert g_alto < g_bajo


# ── Chile identico a la formula previa (no regresion) ───────────────────────────────
def test_chile_no_regresiona():
    # Con exigencia 60, logro 80 -> 4 + (0.2/0.4)*3 = 5.5
    assert calculate_grade(80.0, "chile_1_7", 60.0)[0] == 5.5
    # logro 30, exigencia 60 -> 1 + 3*(0.3/0.6) = 2.5, reprueba
    g, lbl, passed = calculate_grade(30.0, "chile_1_7", 60.0)
    assert g == 2.5 and passed is False and lbl == "2.5"


def test_valores_concretos_por_pais():
    # Mismo logro 80%, exigencia 60% -> punto medio superior en cada escala.
    assert calculate_grade(80.0, "mexico_10", 60.0)[0] == 8.0     # 6 + 0.5*(10-6)
    assert calculate_grade(80.0, "espana_10", 60.0)[0] == 7.5     # 5 + 0.5*(10-5)
    assert calculate_grade(80.0, "alemania_5", 60.0)[0] == 2.5    # 4 - 0.5*(4-1)


# ── bandas fijas (referencia internacional) ─────────────────────────────────────────
def test_bandas_letras_estandar():
    assert calculate_grade(95.0, "usa_letter", 60.0)[1] == "A"
    assert calculate_grade(72.0, "usa_letter", 60.0)[1] == "C-"
    assert calculate_grade(75.0, "usa_letter", 60.0)[1] == "C"
    assert calculate_grade(55.0, "usa_letter", 60.0)[1] == "F"
    assert calculate_grade(85.0, "ects", 60.0)[1] == "B"
    assert calculate_grade(72.0, "uk_honours", 60.0)[1] == "First Class"
    assert calculate_grade(55.0, "uk_honours", 60.0)[1] == "Lower Second (2:2)"


@pytest.mark.parametrize("ex", EXIGENCIAS)
def test_bandas_fijas_aprueban_en_su_corte(ex):
    # Diseño: por defecto las bandas son FIJAS (estándar). La aprobación sigue el corte de la
    # banda que aprueba (USA D=60%), NO la exigencia elegida.
    _, _, passed_60 = calculate_grade(60.0, "usa_letter", ex)   # D -> aprueba
    _, _, passed_59 = calculate_grade(59.0, "usa_letter", ex)   # F -> reprueba
    assert passed_60 is True and passed_59 is False


@pytest.mark.parametrize("ex", EXIGENCIAS)
def test_bandas_moviles_siguen_la_exigencia(ex):
    # Opt-in (banda_movil=True): la línea de aprobación se mueve a la exigencia elegida.
    _, _, passed_justo = calculate_grade(ex, "usa_letter", ex, banda_movil=True)
    _, _, passed_bajo = calculate_grade(ex - 1, "usa_letter", ex, banda_movil=True)
    assert passed_justo is True and passed_bajo is False


# ── invariante: mismo logro -> mismo veredicto de aprobacion en TODA escala ──────────
@pytest.mark.parametrize("ex", EXIGENCIAS)
@pytest.mark.parametrize("logro", [35.0, 55.0, 65.0, 88.0])
def test_aprobacion_consistente_entre_escalas(logro, ex):
    # El invariante "mismo logro -> mismo veredicto" vale para escalas NUMÉRICAS (siguen la
    # exigencia). Las de BANDAS son de corte fijo por estándar (no siguen la exigencia por
    # defecto), así que se excluyen de este invariante intencionalmente.
    from app.services.result_service import GRADING_SCALES
    numericas = {k for k, v in GRADING_SCALES.items() if v["compute"]["kind"] != "band"}
    conv = convertir_multiescala(logro, ex)
    veredictos = {k: v["passed"] for k, v in conv.items() if k in numericas}
    esperado = logro >= ex
    assert all(v is esperado for v in veredictos.values()), veredictos


def test_multiescala_traduce_un_mismo_logro():
    conv = convertir_multiescala(80.0, 60.0, escalas=["chile_1_7", "mexico_10", "francia_20"])
    assert conv["chile_1_7"]["grade"] == 5.5
    assert conv["mexico_10"]["grade"] == 8.0
    assert conv["francia_20"]["grade"] == 15.0     # 10 + 0.5*(20-10)


# ── metadata publica ────────────────────────────────────────────────────────────────
def test_listar_escalas_no_expone_compute():
    meta = listar_escalas()
    assert "chile_1_7" in meta and "mexico_10" in meta and "alemania_5" in meta
    assert all("compute" not in v for v in meta.values())
    assert meta["chile_1_7"]["region"] == "CL"
