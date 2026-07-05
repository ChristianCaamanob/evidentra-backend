"""
Test de la modalidad ORAL: una rubrica parametrizada aplicada directamente a cada estudiante
(sin hoja/escaneo). El sujeto es el estudiante de la nomina; validar por estudiante persiste
la trazabilidad y el libro de notas resume por estudiante.
"""
from __future__ import annotations

import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.student  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.answer_key  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.result  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.password_reset  # noqa: F401
import app.models.curriculo  # noqa: F401
import app.models.validacion  # noqa: F401
import app.models.aprendizaje  # noqa: F401

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.course import Course
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem, RubricCriterion
from app.models.student import Student

_CREADOR = type("U", (), {"rol": "creador"})()


def _sembrar(engine):
    ids = {}
    with Session(engine) as s:
        course = Course(name="Anatomia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Interrogacion oral", modalidad="oral",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        item = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                             correct_answer="", question_type="open_response", weight=1.0)
        s.add(item); s.commit(); s.refresh(item)
        s.add(RubricCriterion(answer_key_item_id=item.id, name="C1", weight=1.0, order=0))
        s.add(RubricCriterion(answer_key_item_id=item.id, name="C2", weight=1.0, order=1))
        s.commit()
        for nombre in ("Ana", "Beto", "Caro"):
            st = Student(course_id=course.id, rut=f"rut-{nombre}", nombres=nombre)
            s.add(st); s.commit(); s.refresh(st)
            ids[nombre] = str(st.id)
        ids["assessment"] = str(a.id)
        return ids


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    ids = _sembrar(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _CREADOR
    yield {"ids": ids, "client": TestClient(app)}
    app.dependency_overrides.clear()


def _validar(client, aid, sid, niveles):
    return client.post(
        f"/api/v1/assessments/{aid}/students/{sid}/rubrica/validar",
        json={"docente": "prof.caamano",
              "criterios": [{"criterio": c, "nivel_docente": n} for c, n in niveles.items()]})


def test_validar_oral_por_estudiante(entorno):
    ids = entorno["ids"]
    r = _validar(entorno["client"], ids["assessment"], ids["Ana"],
                 {"C1": "logrado", "C2": "logrado"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modalidad"] == "oral" and body["n_registrados"] == 2


def test_libro_notas_oral(entorno):
    ids, c = entorno["ids"], entorno["client"]
    _validar(c, ids["assessment"], ids["Ana"], {"C1": "logrado", "C2": "logrado"})
    _validar(c, ids["assessment"], ids["Beto"], {"C1": "parcial", "C2": "no_logrado"})
    # Caro queda sin evaluar -> pendiente
    r = c.get(f"/api/v1/assessments/{ids['assessment']}/libro-notas")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_estudiantes"] == 3
    assert body["composicion"] == {"items_alternativas": 0, "items_desarrollo": 1, "mixta": False}
    por = {round(e["logro_pct"]): e for e in body["estudiantes"]}
    assert 100 in por and por[100]["nota"] == 7.0          # Ana: logrado/logrado
    assert body["resumen"]["pendientes_desarrollo"] == 1   # Caro, sin evaluar


def test_estudiante_de_otro_curso_da_conflict(entorno):
    ids, c = entorno["ids"], entorno["client"]
    # student_id inexistente -> 404
    import uuid
    r = c.post(f"/api/v1/assessments/{ids['assessment']}/students/{uuid.uuid4()}/rubrica/validar",
               json={"docente": "x", "criterios": [{"criterio": "C1", "nivel_docente": "logrado"}]})
    assert r.status_code == 404
