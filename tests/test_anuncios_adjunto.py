"""Un aviso puede llevar un enlace o un archivo.

Pedido del CEO durante el piloto: «en los anuncios deberá poder adjuntar un link o
archivo». Un aviso casi siempre viene con algo que mirar —la pauta, la lectura, el plano
de la sala nueva— y sin adjunto había que mandarlo por otro canal.
"""
from __future__ import annotations

import base64
import importlib
import pkgutil
import uuid

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base

API = "/api/v1"
_PDF = base64.b64encode(b"%PDF-1.4 pauta de la prueba").decode()


@pytest.fixture()
def ent():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng)

    def _db():
        d = TS()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[usuario_actual] = lambda: type(
        "U", (), {"rol": "creador", "id": "t", "email": "a@b.cl", "name": "Prof. Pérez"})()
    c = TestClient(app)
    cid = c.post(f"{API}/courses/", json={"name": "Obstetricia", "code": "OBS-AN",
                                          "grading_scale": "chile_1_7",
                                          "passing_threshold": 60.0}).json()["id"]
    yield {"c": c, "cid": cid}
    app.dependency_overrides.clear()


def test_aviso_con_enlace(ent):
    c, cid = ent["c"], ent["cid"]
    r = c.post(f"{API}/courses/{cid}/anuncios",
               json={"titulo": "Lectura para el martes", "cuerpo": "Revisen el capítulo 4",
                     "url": "https://drive.example/cap4"})
    assert r.status_code == 200, r.text
    a = r.json()["anuncio"]
    assert a["url"] == "https://drive.example/cap4"
    assert a["archivo_url"] is None, "no hay archivo, solo enlace"


def test_aviso_con_archivo_y_su_descarga(ent):
    c, cid = ent["c"], ent["cid"]
    r = c.post(f"{API}/courses/{cid}/anuncios",
               json={"titulo": "Pauta del certamen", "cuerpo": "Adjunto la pauta",
                     "archivo_datos": "data:application/pdf;base64," + _PDF,
                     "archivo_nombre": "pauta.pdf", "archivo_mime": "application/pdf"})
    assert r.status_code == 200, r.text
    a = r.json()["anuncio"]
    assert a["archivo_nombre"] == "pauta.pdf" and a["tamano"] > 0
    assert a["archivo_url"], "sin enlace de descarga el adjunto es inservible"

    d = c.get(a["archivo_url"])
    assert d.status_code == 200
    assert d.content.startswith(b"%PDF"), "el archivo descargado no es el que se subió"


def test_el_listado_no_arrastra_el_base64(ent):
    """Devolver el archivo en cada aviso inflaría la bandeja del alumno a megas por nada."""
    c, cid = ent["c"], ent["cid"]
    c.post(f"{API}/courses/{cid}/anuncios",
           json={"titulo": "Pauta", "archivo_datos": _PDF,
                 "archivo_nombre": "pauta.pdf", "archivo_mime": "application/pdf"})
    lst = c.get(f"{API}/courses/{cid}/anuncios").json()["anuncios"]
    assert lst and "archivo_datos" not in lst[0]
    assert lst[0]["archivo_url"], "pero sí debe decir dónde bajarlo"


def test_archivo_demasiado_grande_se_rechaza_con_alternativa(ent):
    c, cid = ent["c"], ent["cid"]
    grande = base64.b64encode(b"x" * (7 * 1024 * 1024)).decode()
    r = c.post(f"{API}/courses/{cid}/anuncios",
               json={"titulo": "Video", "archivo_datos": grande,
                     "archivo_nombre": "v.mp4", "archivo_mime": "video/mp4"})
    assert r.status_code == 422
    assert "enlace" in r.json()["detail"].lower(), "hay que decirle qué hacer en su lugar"


def test_un_aviso_sin_adjunto_sigue_funcionando(ent):
    c, cid = ent["c"], ent["cid"]
    r = c.post(f"{API}/courses/{cid}/anuncios", json={"titulo": "Cambio de sala", "cuerpo": "Vamos al B-201"})
    assert r.status_code == 200
    a = r.json()["anuncio"]
    assert a["url"] is None and a["archivo_url"] is None and a["tamano"] == 0
