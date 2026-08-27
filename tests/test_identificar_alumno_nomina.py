"""El alumno se identifica contra la nómina: formatos de RUT y nómina vacía.

Reportado en el piloto: «me dice que reconoce el curso pero que el profesor me tiene que
autorizar, y estoy inscrito». Dos causas distintas se veían igual: escribir el RUT sin
dígito verificador (rechazo injusto) y que el curso no tuviera nómina cargada (el mensaje
culpaba al alumno de un dato mal escrito).
"""
from __future__ import annotations

import importlib
import pkgutil
import uuid

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.student import Student

API = "/api/v1"


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
        "U", (), {"rol": "creador", "id": "t", "email": "a@b.cl"})()
    yield {"c": TestClient(app), "eng": eng}
    app.dependency_overrides.clear()


def _curso_con_silabo(c, code):
    cid = c.post(f"{API}/courses/", json={"name": "C " + code, "code": code,
                                          "grading_scale": "chile_1_7",
                                          "passing_threshold": 60.0}).json()["id"]
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 200, "activo": True, "config": {}})
    return cid, c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]


@pytest.mark.parametrize("escrito", [
    "12345678-9",     # canónico
    "12.345.678-9",   # con puntos
    "123456789",      # todo junto
    "12345678",       # SIN dígito verificador — mucha gente lo escribe así
    " 12345678-9 ",   # con espacios
])
def test_reconoce_el_rut_como_lo_escriba_el_alumno(ent, escrito):
    c, eng = ent["c"], ent["eng"]
    cid, cod = _curso_con_silabo(c, "RUT")
    with Session(eng) as s:
        s.add(Student(course_id=uuid.UUID(cid), rut="12345678-9",
                      nombres="Ana", apellido_paterno="Pérez"))
        s.commit()
    d = c.post(f"{API}/silabo/{cod}/identificar", json={"valor": escrito}).json()
    assert d.get("ok") is True, f"no reconoció «{escrito}»: {d}"
    assert d["nombre"] == "Ana Pérez"


def test_no_reconoce_a_quien_no_esta(ent):
    c, eng = ent["c"], ent["eng"]
    cid, cod = _curso_con_silabo(c, "AJENO")
    with Session(eng) as s:
        s.add(Student(course_id=uuid.UUID(cid), rut="12345678-9", nombres="Ana",
                      apellido_paterno="Pérez"))
        s.commit()
    d = c.post(f"{API}/silabo/{cod}/identificar", json={"valor": "99999999-9"}).json()
    assert d.get("ok") is False
    assert d.get("sin_nomina") is False, "hay nómina; el problema es que ese RUT no está"


def test_curso_sin_nomina_lo_dice_en_vez_de_culpar_al_alumno(ent):
    c, _ = ent["c"], ent["eng"]
    _cid, cod = _curso_con_silabo(c, "VACIO")
    d = c.post(f"{API}/silabo/{cod}/identificar", json={"valor": "12345678-9"}).json()
    assert d.get("ok") is False
    assert d.get("sin_nomina") is True, "debe distinguirse de un RUT mal escrito"
    assert d.get("n_nomina") == 0
