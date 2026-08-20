"""Borrado de estudiantes: uno, uno con evidencia (409 + forzar) y nómina completa.

Hasta ahora /courses/{id}/students solo tenía GET y POST: el docente podía agregar
pero no sacar a nadie. Ninguna tabla declara FK a students.id (guardan el id como
texto), así que el DELETE no falla nunca — el riesgo real es borrar en silencio a
alguien que ya tiene escaneos corregidos. De ahí la confirmación explícita.
"""
from __future__ import annotations

import uuid

import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.student  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.desarrollo_reporte  # noqa: F401
import app.models.examen_oral  # noqa: F401

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.course import Course
from app.models.student import Student
from app.models.assessment import Assessment
from app.models.scan import Scan

_PROFE = type("U", (), {"rol": "creador", "id": "t-1"})()


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _PROFE
    yield {"client": TestClient(app), "TS": TS}
    app.dependency_overrides.clear()


def _curso(TS):
    with Session(TS.kw["bind"]) as s:
        c = Course(name="Morfología", code="MORF-1", grading_scale="chile_1_7",
                   passing_threshold=60.0)
        s.add(c); s.commit(); s.refresh(c)
        return str(c.id)


def _alumno(TS, cid, rut):
    with Session(TS.kw["bind"]) as s:
        a = Student(course_id=uuid.UUID(cid), rut=rut, apellido_paterno="Pérez", nombres="Ana")
        s.add(a); s.commit(); s.refresh(a)
        return str(a.id)


def test_borra_un_alumno_sin_evidencia(entorno):
    cli, TS = entorno["client"], entorno["TS"]
    cid = _curso(TS); sid = _alumno(TS, cid, "11111111-1")

    r = cli.delete(f"/api/v1/courses/{cid}/students/{sid}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert cli.get(f"/api/v1/courses/{cid}/students").json() == []


def test_alumno_con_evidencia_exige_forzar(entorno):
    cli, TS = entorno["client"], entorno["TS"]
    cid = _curso(TS); sid = _alumno(TS, cid, "22222222-2")
    with Session(TS.kw["bind"]) as s:
        a = Assessment(course_id=uuid.UUID(cid), name="Certamen 1", n_questions=10)
        s.add(a); s.commit(); s.refresh(a)
        s.add(Scan(assessment_id=a.id, student_identifier=sid, status="processed"))
        s.commit()

    r = cli.delete(f"/api/v1/courses/{cid}/students/{sid}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["evidencia"]["escaneos"] == 1
    assert len(cli.get(f"/api/v1/courses/{cid}/students").json()) == 1   # sigue ahí

    r2 = cli.delete(f"/api/v1/courses/{cid}/students/{sid}?forzar=true")
    assert r2.status_code == 200, r2.text
    assert cli.get(f"/api/v1/courses/{cid}/students").json() == []


def test_vaciar_nomina_exige_confirmar(entorno):
    cli, TS = entorno["client"], entorno["TS"]
    cid = _curso(TS)
    for i in range(3):
        _alumno(TS, cid, f"3333333{i}-3")

    r = cli.delete(f"/api/v1/courses/{cid}/students")
    assert r.status_code == 400
    assert r.json()["detail"]["n_students"] == 3
    assert len(cli.get(f"/api/v1/courses/{cid}/students").json()) == 3   # nada se borró

    r2 = cli.delete(f"/api/v1/courses/{cid}/students?confirmar=SI")
    assert r2.status_code == 200, r2.text
    assert r2.json()["n_students"] == 3
    assert cli.get(f"/api/v1/courses/{cid}/students").json() == []


def test_alumno_de_otro_curso_no_se_borra(entorno):
    cli, TS = entorno["client"], entorno["TS"]
    cid = _curso(TS); sid = _alumno(TS, cid, "44444444-4")
    with Session(TS.kw["bind"]) as s:
        otro = Course(name="Otro", code="OTRO-1", grading_scale="chile_1_7",
                      passing_threshold=60.0)
        s.add(otro); s.commit(); s.refresh(otro)
        otro_id = str(otro.id)

    r = cli.delete(f"/api/v1/courses/{otro_id}/students/{sid}")
    assert r.status_code == 404
    assert len(cli.get(f"/api/v1/courses/{cid}/students").json()) == 1
