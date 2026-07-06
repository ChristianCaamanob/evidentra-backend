"""
Test de puntaje GRUPAL: el criterio grupal se valida UNA VEZ por grupo y aplica identico a
todos los integrantes (consistencia); los criterios individuales difieren por estudiante.
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
import app.models.grupo  # noqa: F401

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
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Presentacion", modalidad="oral",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        # item1: criterio GRUPAL; item2: criterio INDIVIDUAL. Pesos 1 y 1.
        it1 = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                            correct_answer="", question_type="open_response", weight=1.0)
        s.add(it1); s.commit(); s.refresh(it1)
        s.add(RubricCriterion(answer_key_item_id=it1.id, name="Contenido", weight=1.0,
                              order=0, ambito="grupal"))
        it2 = AnswerKeyItem(answer_key_id=ak.id, question_number=2, version="A",
                            correct_answer="", question_type="open_response", weight=1.0)
        s.add(it2); s.commit(); s.refresh(it2)
        s.add(RubricCriterion(answer_key_item_id=it2.id, name="Pregunta", weight=1.0,
                              order=0, ambito="individual"))
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


def test_puntaje_grupal_es_consistente_entre_integrantes(entorno):
    ids, c = entorno["ids"], entorno["client"]
    aid = ids["assessment"]
    # 1) grupo con Ana + Beto (Caro queda fuera)
    g = c.post(f"/api/v1/assessments/{aid}/grupos",
               json={"nombre": "Grupo 1", "integrantes": [ids["Ana"], ids["Beto"]]})
    assert g.status_code == 200, g.text
    grupo_id = g.json()["grupo_id"]

    # 2) criterio GRUPAL validado UNA vez -> aplica a los dos
    r = c.post(f"/api/v1/assessments/{aid}/grupos/{grupo_id}/rubrica/validar",
               json={"docente": "prof", "criterios": [{"criterio": "Contenido",
                                                        "nivel_docente": "logrado"}]})
    assert r.status_code == 200 and set(r.json()["aplica_a"]) == {ids["Ana"], ids["Beto"]}

    # 3) criterio INDIVIDUAL: Ana logrado, Beto no_logrado
    for nombre, nivel in [("Ana", "logrado"), ("Beto", "no_logrado")]:
        c.post(f"/api/v1/assessments/{aid}/students/{ids[nombre]}/rubrica/validar",
               json={"docente": "prof", "criterios": [{"criterio": "Pregunta",
                                                        "nivel_docente": nivel}]})

    libro = c.get(f"/api/v1/assessments/{aid}/libro-notas").json()
    por = {e["logro_pct"]: e for e in libro["estudiantes"]}
    # Ana: grupal logrado (50%) + individual logrado (50%) = 100 -> 7,0
    assert 100.0 in por and por[100.0]["nota"] == 7.0
    # Beto: MISMO grupal logrado (50%) + individual no_logrado (0%) = 50 -> el grupal se aplico igual
    assert 50.0 in por and por[50.0]["aprobado"] is False
    # Caro: sin grupo -> el criterio grupal no aplica -> pendiente
    assert libro["resumen"]["pendientes_desarrollo"] == 1


def test_listar_grupos(entorno):
    ids, c = entorno["ids"], entorno["client"]
    c.post(f"/api/v1/assessments/{ids['assessment']}/grupos",
           json={"nombre": "Grupo 1", "integrantes": [ids["Ana"], ids["Beto"]]})
    r = c.get(f"/api/v1/assessments/{ids['assessment']}/grupos")
    assert r.status_code == 200
    grupos = r.json()["grupos"]
    assert len(grupos) == 1 and set(grupos[0]["integrantes"]) == {ids["Ana"], ids["Beto"]}
