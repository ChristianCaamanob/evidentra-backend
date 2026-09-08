"""
El aviso de que Runi está caído.

Tres veces en el piloto la IA dejó de responder a TODO el curso —clave inválida, cuenta sin saldo,
clave rechazada— y las tres veces el docente se enteró porque una estudiante le mostró la pantalla.
Un producto que depende de una credencial externa tiene que avisar cuando esa credencial se cae.
"""
from __future__ import annotations

import pytest

from app.services import salud_ia_service as sia


@pytest.fixture(autouse=True)
def _limpiar():
    sia._cache.clear()
    yield
    sia._cache.clear()


def _falla(monkeypatch, mensaje):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(sia, "_ping", lambda: (_ for _ in ()).throw(RuntimeError(mensaje)))


def _responde(monkeypatch, contador):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def ok():
        contador["n"] += 1

    monkeypatch.setattr(sia, "_ping", ok)


def test_cada_causa_dice_QUE_HACER_no_solo_que_fallo(monkeypatch):
    """«Error» no sirve: hay que decirle al CEO dónde tocar."""
    casos = {
        "Your credit balance is too low": ("sin_saldo", "Billing"),
        "authentication_error: invalid x-api-key": ("clave_invalida", "console.anthropic.com"),
        "model not_found_error": ("modelo_invalido", "EVALYS_EXPERTO_MODEL"),
        "rate_limit_error 429": ("limite", "solo"),
        "overloaded_error 529": ("sobrecargado", "solo"),
    }
    for mensaje, (estado, pista) in casos.items():
        sia._cache.clear()
        _falla(monkeypatch, mensaje)
        d = sia.estado()
        assert d["estado"] == estado and not d["ok"], mensaje
        assert pista.lower() in d["que_hacer"].lower(), (mensaje, d["que_hacer"])


def test_sin_clave_lo_dice_sin_llamar_al_proveedor(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = sia.estado()
    assert d["estado"] == "sin_clave" and "Render" in d["que_hacer"]


def test_se_cachea_para_no_gastar_una_llamada_por_visita(monkeypatch):
    """El panel del profesor se pinta muchas veces al día; el chequeo cuesta una llamada real."""
    llamadas = {"n": 0}
    _responde(monkeypatch, llamadas)
    assert sia.estado()["ok"]
    for _ in range(5):
        sia.estado()
    assert llamadas["n"] == 1
    assert sia.estado()["cacheado"]


def test_forzar_salta_la_cache(monkeypatch):
    """Al rotar la clave, el CEO tiene que poder comprobarlo sin esperar la caché."""
    llamadas = {"n": 0}
    _responde(monkeypatch, llamadas)
    sia.estado()
    sia.estado(forzar=True)
    assert llamadas["n"] == 2


def test_caido_se_recomprueba_antes_que_sano(monkeypatch):
    """Cuando está roto conviene mirar seguido: es el momento en que alguien lo está arreglando."""
    assert sia._TTL_MAL < sia._TTL_OK


def test_la_bandeja_del_docente_lleva_el_estado(monkeypatch):
    """Es donde el profesor mira todos los días: ahí se entera él antes que sus estudiantes."""
    from app.services import silabo_service as sil
    _falla(monkeypatch, "authentication_error")
    d = sil._salud_ia()
    assert d["estado"] == "clave_invalida"


def test_un_diagnostico_caido_no_puede_tumbar_la_bandeja(monkeypatch):
    from app.services import silabo_service as sil
    monkeypatch.setattr(sia, "estado", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sil._salud_ia()["ok"]          # ante la duda, no se alarma al docente sin motivo
