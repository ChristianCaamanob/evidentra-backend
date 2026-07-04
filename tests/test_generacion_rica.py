"""
Test de forma del hito E2-generacion-rica.

E2 es gate humano (G1): la validacion del contenido es del docente. Esto verifica la
parte automatizable: seudonimizacion (G2) y forma de la generacion rica.
"""
from __future__ import annotations

import pytest

from app.services import generacion_service as gen

DATOS = {
    "estudiante": {"nombre": "Juan Perez", "identificador": "11.111.111-1", "curso": "Morfologia"},
    "evaluacion": {"nombre": "Solemne 1", "version": "A"},
    "desempeno": {"porcentaje": 66.7, "nivel": "en_desarrollo", "correctas": 20},
    "dimensiones_bloom": [{"clave": "Comprension", "total": 30, "correctas": 20, "porcentaje": 66.7}],
    "brechas": [
        {"ra": "RA3", "unidad": "Unidad 1", "porcentaje": 43.0,
         "ra_texto": "Relaciona los tejidos basicos...", "que_muestra": "Lograste 3 de 7 en RA3."},
    ],
    "fortalezas": [{"ra": "RA1", "porcentaje": 100.0, "ra_texto": "Generalidades..."}],
    "metadata": {"contrato_version": "1.0"},
}


def test_vista_seudonimizada_sin_identificatorios():
    v = gen.vista_seudonimizada(DATOS)
    assert "estudiante" not in v
    assert gen._sin_identificatorios(v)


def test_seudonimizacion_detecta_fuga():
    malo = {"desempeno": {"rut": "11.111.111-1"}}  # identificatorio de persona escondido
    with pytest.raises(ValueError):
        gen.vista_seudonimizada(malo)


def test_enriquecer_brechas_bien_formadas():
    out = gen.enriquecer(DATOS, corpus=gen.CORPUS_DMOR0030)
    assert out["seudonimizado"] is True
    assert out["requiere_validacion_docente"] is True  # G1
    assert len(out["brechas"]) == 1
    b = out["brechas"][0]
    for campo in ("ra", "que_muestra", "por_que_importa", "recomendacion"):
        assert b.get(campo), f"la brecha rica debe traer {campo}"
    # el corpus de RA3 se uso
    assert "tejidos basicos" in b["por_que_importa"].lower()


def test_plan_tiene_sesiones():
    out = gen.enriquecer(DATOS, corpus=gen.CORPUS_DMOR0030)
    plan = out["plan_consolidacion"]
    assert plan["sesiones"], "el plan debe tener al menos una sesion"
    assert plan["sesiones"][0]["foco"] == "RA3"


def test_salida_no_filtra_identificatorios():
    out = gen.enriquecer(DATOS, corpus=gen.CORPUS_DMOR0030)
    assert gen._sin_identificatorios(out), "la generacion rica no debe contener identificadores"


def test_sin_brechas_mensaje_de_profundizacion():
    datos = dict(DATOS); datos["brechas"] = []
    out = gen.enriquecer(datos, corpus=gen.CORPUS_DMOR0030)
    assert out["brechas"] == []
    assert "superior" in out["mensaje"].lower() or "profundizar" in out["mensaje"].lower()
