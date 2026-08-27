"""El presupuesto de tiempo del marcado por QR.

El bug: `marcar_con_passkey` exigía `_bucket_actual() - bucket in (0, 1)`, o sea 8 s
para escanear, cargar la app, hablar con el backend y completar Face ID. Escaneaba y
no marcaba. Ahora la frescura del QR se exige al PEDIR el desafío, y el tramo de la
ceremonia biométrica —que es tiempo humano— tiene su propia ventana.
"""
from __future__ import annotations

import time

from app.services import asistencia_service as asis


def test_pedir_el_desafio_cubre_la_carga_de_la_app():
    """El presupuesto tiene que cubrir enfoque + Safari + ~930 KB + arranque en un teléfono.

    Antes este test exigía además un techo de 40 s "para que un QR fotografiado no sirva
    tanto rato". Ese techo se cayó a propósito: la doctrina del módulo ya asume que un QR
    rotatorio NO frena la retransmisión (basta que un presente mande la foto), así que
    apretarlo cobraba usabilidad sin comprar seguridad. Lo que ata la marca es la passkey
    del dispositivo enrolado. El techo de verdad lo pone la ventana horaria de la sesión.
    """
    assert asis._TOLERANCIA_SEG >= 60, "no alcanza para cargar la app en red móvil"
    assert asis._TOLERANCIA_SEG <= 300, "más que esto ya es un enlace reutilizable, no un QR"


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


# ── El motivo del rechazo debe distinguir las cuatro causas ───────────────────────────
# Todas devolvían "El código QR venció o no es válido", así que el alumno rescaneaba un
# código que a veces no iba a servir nunca (p. ej. si la lista estaba cerrada).
import types
from datetime import datetime, timedelta, timezone


def _sesion_falsa(abierta=True, desde=-1, hasta=+1):
    ahora = datetime.now(timezone.utc)
    return types.SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", secreto="s3cr3t0",
        estado=("abierta" if abierta else "cerrada"),
        inicio=ahora + timedelta(hours=desde), fin=ahora + timedelta(hours=hasta))


def _token_de(s, bucket):
    return asis._firmar(s.secreto, str(s.id), bucket)


def test_motivo_sesion_cerrada():
    s = _sesion_falsa(abierta=False)
    ok, motivo = asis.verificar_desafio(s, _token_de(s, asis._bucket_actual()), asis._bucket_actual())
    assert not ok and "cerrada" in motivo.lower()


def test_motivo_fuera_de_horario_dice_la_ventana():
    s = _sesion_falsa(desde=-5, hasta=-3)          # la lista fue hace horas
    ok, motivo = asis.verificar_desafio(s, _token_de(s, asis._bucket_actual()), asis._bucket_actual())
    assert not ok
    assert "Abre de" in motivo and "UTC" in motivo, motivo
    assert "venció" not in motivo, "no debe confundirse con un QR viejo"


def test_motivo_qr_viejo_dice_cuantos_segundos():
    s = _sesion_falsa()
    viejo = asis._bucket_actual() - (asis._TOLERANCIA_SEG // asis.BUCKET_SEG) - 5
    ok, motivo = asis.verificar_desafio(s, _token_de(s, viejo), viejo)
    assert not ok and " s (" in motivo and str(asis._TOLERANCIA_SEG) in motivo, motivo


def test_motivo_firma_que_no_calza():
    s = _sesion_falsa()
    b = asis._bucket_actual()
    ok, motivo = asis.verificar_desafio(s, "firma-inventada", b)
    assert not ok and "no es válido" in motivo, motivo


def test_desafio_vigente_propaga_el_motivo():
    s = _sesion_falsa(abierta=False)
    challenge, motivo = asis.desafio_vigente(s, _token_de(s, asis._bucket_actual()), asis._bucket_actual())
    assert challenge is None and motivo, "el motivo no puede perderse por el camino"


# ── Gracia en la ventana horaria ──────────────────────────────────────────────────────
# El alumno escaneó en el minuto exacto en que empezaba la clase y el sistema le dijo, sin
# sentido, que "la lista abre a las 03:14 y ahora son las 03:14". Fallaba por SEGUNDOS.

def test_marcar_justo_al_empezar_la_clase_funciona():
    s = _sesion_falsa()
    s.inicio = datetime.now(timezone.utc) + timedelta(seconds=20)   # empieza en 20 s
    s.fin = s.inicio + timedelta(hours=2)
    b = asis._bucket_actual()
    ok, motivo = asis.verificar_desafio(s, _token_de(s, b), b)
    assert ok, f"rechazó a quien llega puntual: {motivo}"


def test_marcar_apenas_termina_la_clase_funciona():
    s = _sesion_falsa()
    s.fin = datetime.now(timezone.utc) - timedelta(seconds=30)      # terminó hace 30 s
    s.inicio = s.fin - timedelta(hours=2)
    b = asis._bucket_actual()
    ok, _ = asis.verificar_desafio(s, _token_de(s, b), b)
    assert ok, "30 s de latencia no deberían costarle la asistencia a nadie"


def test_la_gracia_no_abre_la_lista_de_ayer():
    s = _sesion_falsa(desde=-5, hasta=-3)                            # terminó hace 3 horas
    b = asis._bucket_actual()
    ok, motivo = asis.verificar_desafio(s, _token_de(s, b), b)
    assert not ok and "ya terminó" in motivo, motivo


def test_el_rechazo_viaja_con_los_instantes_para_mostrarlos_en_hora_local():
    """El servidor no conoce la zona del alumno: manda ISO y la app los pinta en su hora."""
    s = _sesion_falsa(desde=-5, hasta=-3)
    b = asis._bucket_actual()
    _ok, motivo = asis.verificar_desafio(s, _token_de(s, b), b)
    partes = motivo.split("|VENTANA|")
    assert len(partes) == 2, f"falta el bloque de instantes: {motivo}"
    isos = partes[1].split("|")
    assert len(isos) == 3, f"deben venir inicio, fin y ahora: {isos}"
    for iso in isos:
        datetime.fromisoformat(iso)      # deben ser parseables
