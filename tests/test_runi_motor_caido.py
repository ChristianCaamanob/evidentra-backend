"""Cuando el MOTOR de IA está caído, Runi no debe culpar a la pregunta del estudiante.

Evidencia del piloto: el 11 y el 18 de agosto Runi respondía anatomía con detalle; el 27,
con la clave de API rechazada, TODA pregunta —incluido un «hola»— caía en «No pude resolver
tu duda ahora mismo… ¿puedes reformularla?». Dos daños: al estudiante se le pedía reformular
una pregunta que estaba bien, y cada intento se registraba como 'fuera_corpus', que es uno de
los tipos que van al docente y pesa en las métricas — o sea, le ensuciaba el mapa de vacíos
con temas que Runi jamás llegó a intentar.
"""
from __future__ import annotations

import pytest

from app.services import silabo_service as sil


@pytest.mark.parametrize("mensaje", [
    "Error code: 401 - {'type':'authentication_error','message':'API key is invalid.'}",
    "rate_limit_error: 429",
    "Connection error.",
    "overloaded_error 529",
    "Read timeout",
])
def test_reconoce_las_caidas_del_motor(mensaje):
    assert sil._es_falla_de_servicio(RuntimeError(mensaje)) is True, mensaje


@pytest.mark.parametrize("mensaje", [
    "json inválido",
    "list index out of range",
    "KeyError: 'tipo'",
])
def test_no_confunde_un_bug_nuestro_con_una_caida(mensaje):
    assert sil._es_falla_de_servicio(ValueError(mensaje)) is False, mensaje


def test_el_motor_caido_no_se_registra_como_vacio_del_silabo():
    """'servicio_caido' NO puede estar entre los tipos que van al docente."""
    assert "servicio_caido" not in sil._TIPOS_A_DOCENTE
    assert "fuera_corpus" in sil._TIPOS_A_DOCENTE, "el tipo real sigue existiendo"


def test_con_el_motor_caido_el_mensaje_es_honesto(monkeypatch):
    from app.services import correccion_experta_service as ce
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-falsa-para-llegar-al-motor")

    def _revienta(*a, **k):
        raise RuntimeError("Error code: 401 - authentication_error: API key is invalid.")
    monkeypatch.setattr(ce, "_llamar_anthropic", _revienta)
    monkeypatch.setattr(ce, "_llamar_anthropic_vision", _revienta)

    class _AgenteFalso:
        contexto = "Programa del curso de Anatomía"
        config = {}
        nombre_curso = "Anatomía"
        codigo = "ABC123"

    tipo, resp = sil._clasificar_y_responder(_AgenteFalso(), "hola", 0)[:2]
    assert tipo == "servicio_caido", f"quedó como {tipo}: le miente al docente"
    assert "No es tu pregunta" in resp, resp
    assert "reformul" not in resp.lower(), "no debe pedir reformular una pregunta que estaba bien"


def test_sin_clave_configurada_tampoco_se_escala_al_docente(monkeypatch):
    """Sin clave el motor no existe; escalarlo llena la bandeja del docente de humo."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _AgenteFalso:
        contexto = "Programa"
        config = {}
        nombre_curso = "Anatomía"
        codigo = "ABC123"

    tipo, resp, _cat, _urg, necesita = sil._clasificar_y_responder(_AgenteFalso(), "hola", 0)[:5]
    assert tipo == "servicio_caido", f"quedó como {tipo}"
    assert necesita is False, "no debe escalarse al docente: no es una duda, es una caída"
    assert "No es tu pregunta" in resp


# ── La agenda es contexto: Runi no debe escalarle al docente lo que él ya escribió ──────
def test_las_evaluaciones_de_la_agenda_entran_al_contexto():
    """El docente cargó «SOLEMNE N°1 · 10-09 · 30%»; que Runi le pregunte a él la fecha
    que él mismo escribió no tiene sentido, y llena su bandeja de derivaciones."""
    import types
    import uuid as _u
    from app.services import silabo_service as sil

    fecha = "2026-09-10"

    class _Eval:
        titulo, hora, tipo, ponderacion = "SOLEMNE Nº1", None, "certamen", "30%"
    _Eval.fecha = fecha

    class _Q:
        def filter(self, *a, **k):
            return self
        def order_by(self, *a, **k):
            return self
        def all(self):
            return [_Eval()]

    class _DB:
        def query(self, *a, **k):
            return _Q()

    a = types.SimpleNamespace(course_id=str(_u.uuid4()))
    bloque = sil._bloque_agenda(_DB(), a)
    assert "SOLEMNE" in bloque and fecha in bloque and "30%" in bloque, bloque
    assert "oficiales" in bloque, "hay que decirle al modelo que son datos del docente"


def test_sin_agenda_el_bloque_queda_vacio():
    from app.services import silabo_service as sil
    assert sil._bloque_agenda(None, None) == ""
