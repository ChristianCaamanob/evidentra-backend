"""
Test del seam LLM de F2 (coder_llm): construccion del prompt desde la parametrizacion F1,
parseo/validacion de la respuesta, y red de seguridad hacia el grader determinista.

No hace llamadas reales: inyecta un `llamar` de prueba (stub).
"""
from __future__ import annotations

import pytest

from app.services import coder_llm
from app.services.precalificacion_service import precalificar_criterio

CRIT_ESTRICTO = {
    "name": "Distensibilidad", "nombre": "Distensibilidad", "weight": 1.0,
    "nivel_exigencia": "estricto", "norma_terminologica": "TA2/IFAA",
    "sinonimos": ["distensible"], "umbral_confianza": 0.7,
    "anclas": [{"texto": "permite estirarse y volver a su forma", "nivel": "logrado"},
               {"texto": "es un tejido", "nivel": "no_logrado"}],
}


def test_prompt_incluye_exigencia_norma_y_anclas():
    system, user = coder_llm.construir_prompt("el urotelio es elastico", CRIT_ESTRICTO)
    assert "PROPONES" in system and "JSON" in system
    assert "ESTRICTA" in user                         # la regla de exigencia
    assert "TA2/IFAA" in user                          # la norma (modo estricto)
    assert "permite estirarse y volver a su forma" in user   # ancla como few-shot
    assert "el urotelio es elastico" in user           # la respuesta del estudiante


def test_prompt_flexible_no_impone_norma():
    crit = dict(CRIT_ESTRICTO, nivel_exigencia="flexible")
    _, user = coder_llm.construir_prompt("respuesta", crit)
    assert "FLEXIBLE" in user
    assert "TA2/IFAA" not in user                       # la norma solo se impone en estricto


def test_parsear_respuesta_valida_y_normaliza():
    r = coder_llm.parsear_respuesta(
        'Aqui va: {"nivel": "Logrado", "confianza": 1.4, '
        '"evidencia": "estirarse y volver", "justificacion": "coincide con el ancla"}')
    assert r["nivel"] == "logrado"
    assert r["confianza"] == 1.0                        # se recorta a [0,1]
    assert r["evidencia"] and r["justificacion"]


def test_parsear_respuesta_invalida_lanza():
    with pytest.raises(Exception):
        coder_llm.parsear_respuesta("no hay json aqui")
    with pytest.raises(Exception):
        coder_llm.parsear_respuesta('{"nivel": "excelente"}')   # nivel no reconocido


def test_coder_con_stub_pasa_por_el_seam_de_f2():
    def _fake(system, user):
        return '{"nivel": "parcial", "confianza": 0.8, "evidencia": "x", "justificacion": "y"}'
    coder = coder_llm.coder_llm(llamar=_fake)
    out = precalificar_criterio("una respuesta", CRIT_ESTRICTO, coder=coder)
    assert out["nivel"] == "parcial"
    assert out["criterio"] == "Distensibilidad"        # el seam envuelve con criterio/peso
    assert out["confianza"] == 0.8


def test_coder_seguro_cae_a_anclas_si_falla_el_modelo():
    def _explota(system, user):
        raise RuntimeError("timeout / sin api key")
    coder = coder_llm.coder_llm_seguro(llamar=_explota)
    out = coder("permite estirarse y volver a su forma", CRIT_ESTRICTO)
    # cae al grader determinista por anclas -> devuelve un nivel valido, no revienta
    assert out["nivel"] in ("logrado", "parcial", "no_logrado")


def test_coder_por_defecto_sin_key_es_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert coder_llm.coder_por_defecto() is None       # sin key -> F2 usa su grader determinista
