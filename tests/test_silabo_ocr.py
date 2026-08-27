"""Transcribir un sílabo escaneado (PDF de imagen) a texto.

El CEO no podía cargar su programa: era un PDF de imagen. pdf.js no extrae nada de un
escaneo, así que el cuadro quedaba vacío sin explicación. Ahora las páginas se rasterizan
en el cliente y un modelo con visión las transcribe.
"""
from __future__ import annotations

import pytest

from app.core.errors import unprocessable  # noqa: F401
from app.services import silabo_ocr_service as ocr

_IMG = [{"media_type": "image/jpeg", "data": "QUJD"}]


def test_transcribe_las_paginas_recibidas():
    visto = {}

    def _falso(system, user, imagenes, max_tokens=0):
        visto["system"], visto["user"], visto["n"] = system, user, len(imagenes)
        return "UNIDAD 1: Anatomía pélvica\nCertamen 1 · 30% · 12 de septiembre"

    d = ocr.transcribir(_IMG * 3, llamar=_falso)
    assert d["ok"] and d["paginas"] == 3 and visto["n"] == 3
    assert "Certamen 1" in d["texto"]
    # Es transcripción, no interpretación: el sílabo es la ÚNICA fuente de Runi, y un
    # resumen produciría fechas y ponderaciones inventadas.
    assert "No resumes" in visto["system"] and "no interpretas" in visto["system"].lower()


def test_tope_de_paginas():
    def _falso(system, user, imagenes, max_tokens=0):
        assert len(imagenes) <= 6, "se pasó del tope de imágenes por consulta"
        return "texto"
    d = ocr.transcribir(_IMG * 20, llamar=_falso)
    assert d["paginas"] == 6


def test_sin_paginas_avisa():
    with pytest.raises(Exception) as e:
        ocr.transcribir([], llamar=lambda *a, **k: "x")
    assert "página" in str(e.value).lower() or "pagina" in str(e.value).lower()


def test_si_no_hay_texto_legible_lo_dice():
    with pytest.raises(Exception) as e:
        ocr.transcribir(_IMG, llamar=lambda *a, **k: "   ")
    assert "nítido" in str(e.value) or "legible" in str(e.value)


def test_la_clave_caida_no_se_confunde_con_un_mal_escaneo():
    """Si la IA está caída, culpar al escaneo del docente lo manda a repetirlo en vano."""
    def _falso(*a, **k):
        raise RuntimeError("Error code: 401 - {'type':'authentication_error','message':'API key is invalid.'}")
    with pytest.raises(Exception) as e:
        ocr.transcribir(_IMG, llamar=_falso)
    msg = str(e.value)
    assert "No es tu archivo" in msg, msg
    assert "api key" not in msg.lower(), "no se filtra el error crudo del proveedor"
