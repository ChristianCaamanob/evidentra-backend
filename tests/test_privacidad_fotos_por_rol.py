"""Regla del CEO (ago-2026): el PROFESOR solo alcanza el chat; el ADMINISTRADOR, todo el registro.

Lo que protege este archivo es el lado del profesor: hoy no ve ninguna foto de sus
estudiantes, y eso no debe cambiar por accidente al agregar campos al monitoreo o a la
bandeja. Las fotos privadas del alumno ni siquiera salen de su teléfono (IndexedDB).
"""
from __future__ import annotations

import importlib
import pkgutil

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

from app.models.silabo import MensajeSilabo
from app.models.pand_momento import PandMomento

_PALABRAS_DE_IMAGEN = ("imagen", "foto", "media", "avatar", "adjunto", "picture", "photo")


def _columnas(modelo):
    return {c.name.lower() for c in modelo.__table__.columns}


def test_el_mensaje_que_ve_el_docente_no_puede_llevar_imagenes():
    """MensajeSilabo alimenta la bandeja y el monitoreo del profesor.

    Si alguien le agrega una columna de imagen, el docente pasaría a ver fotos de sus
    estudiantes sin que nadie lo haya decidido. Esa decisión es del CEO, no un efecto
    colateral de un commit.
    """
    cols = _columnas(MensajeSilabo)
    filtradas = [c for c in cols if any(p in c for p in _PALABRAS_DE_IMAGEN)]
    assert not filtradas, (
        f"MensajeSilabo ganó columna(s) de imagen: {filtradas}. El profesor solo debe "
        "alcanzar el chat; si esto es intencional, hay que decidirlo explícitamente.")


def test_el_monitoreo_docente_no_devuelve_imagenes():
    """La forma de la respuesta de monitoreo_curso no debe incluir medios."""
    import inspect
    from app.services import silabo_service as sil
    fuente = inspect.getsource(sil.monitoreo_curso)
    assert "PandMomento" not in fuente, "el monitoreo del docente no debe leer Momentos (fotos)"
    assert "imagen" not in fuente, "el monitoreo del docente no debe armar campos de imagen"


def test_las_fotos_viven_en_momentos_y_ese_modelo_es_del_ambito_admin():
    """Documenta dónde SÍ están las fotos, para que el límite quede explícito."""
    assert "imagen" in _columnas(PandMomento), (
        "si las fotos dejaron de estar en PandMomento, revisa quién las ve ahora")
