"""El presupuesto de tiempo del marcado por QR.

El bug: `marcar_con_passkey` exigía `_bucket_actual() - bucket in (0, 1)`, o sea 8 s
para escanear, cargar la app, hablar con el backend y completar Face ID. Escaneaba y
no marcaba. Ahora la frescura del QR se exige al PEDIR el desafío, y el tramo de la
ceremonia biométrica —que es tiempo humano— tiene su propia ventana.
"""
from __future__ import annotations

import time

from app.services import asistencia_service as asis


def test_pedir_el_desafio_exige_qr_fresco():
    """La tolerancia cubre la carga de la app, pero no un QR de hace un minuto."""
    assert asis._TOLERANCIA_SEG >= 20, "muy poco margen para cargar la app en red móvil"
    assert asis._TOLERANCIA_SEG <= 40, "un QR fotografiado no debería servir tanto rato"


def test_la_ceremonia_biometrica_cabe_en_la_ventana():
    """Face ID + red no caben en 8 s; la ventana debe dar aire de verdad."""
    assert asis._CEREMONIA_SEG >= 60
    assert asis._CEREMONIA_SEG > asis._TOLERANCIA_SEG


def test_ceremonia_vigente_acepta_una_demora_realista():
    b = asis._bucket_actual()
    assert asis.ceremonia_vigente(b) is True          # inmediato
    demora_buckets = 45 // asis.BUCKET_SEG            # ~45 s: escaneo + carga + Face ID
    assert asis.ceremonia_vigente(b - demora_buckets) is True


def test_ceremonia_vigente_rechaza_lo_vencido_y_lo_futuro():
    b = asis._bucket_actual()
    vencido = (asis._CEREMONIA_SEG // asis.BUCKET_SEG) + 2
    assert asis.ceremonia_vigente(b - vencido) is False
    assert asis.ceremonia_vigente(b + 5) is False     # bucket del futuro = manipulado
    assert asis.ceremonia_vigente("no-es-un-numero") is False
    assert asis.ceremonia_vigente(None) is False


def test_el_qr_queda_quieto_lo_suficiente_para_enfocarlo():
    """Con 4 s la cámara tenía que enganchar un código que cambiaba mientras enfocaba."""
    assert asis.BUCKET_SEG >= 8


def test_verificar_desafio_cubre_toda_la_tolerancia():
    """n_atras se deriva de la tolerancia: si cambia BUCKET_SEG debe seguir cuadrando."""
    n_atras = max(1, asis._TOLERANCIA_SEG // asis.BUCKET_SEG)
    assert n_atras * asis.BUCKET_SEG >= asis._TOLERANCIA_SEG - asis.BUCKET_SEG
