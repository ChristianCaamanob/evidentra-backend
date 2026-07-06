"""
Test: una rubrica de N niveles (Excelente/Bueno/Regular/Deficiente) SI recibe psicometria
(R y MFRM), gracias a la normalizacion a la escala canonica de 3 en cargar_registros_validacion.
Antes, esos niveles no mapeaban y la analitica quedaba vacia.
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
NIVELES = [{"nivel": "Excelente", "puntos": 3}, {"nivel": "Bueno", "puntos": 2},
           {"nivel": "Regular", "puntos": 1}, {"nivel": "Deficiente", "puntos": 0}]
L = ["Excelente", "Bueno", "Regular", "Deficiente"]


def _sembrar(engine, n=6):
    ids = {"alumnos": []}
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Infografia", modalidad="oral",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        for qn, crit in enumerate(["Contenido", "Estructura"], start=1):
            it = AnswerKeyItem(answer_key_id=ak.id, question_number=qn, version="A",
                               correct_answer="", question_type="open_response", weight=1.0)
            s.add(it); s.commit(); s.refresh(it)
            s.add(RubricCriterion(answer_key_item_id=it.id, name=crit, weight=1.0, order=0,
                                  niveles_json=NIVELES))
        s.commit()
        for i in range(n):
            st = Student(course_id=course.id, rut=f"rut-{i}", nombres=f"al{i}")
            s.add(st); s.commit(); s.refresh(st)
            ids["alumnos"].append(str(st.id))
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
    c = TestClient(app)
    # Validar cada alumno en 4 niveles, con la IA a veces un escalon distinta del docente.
    for i, sid in enumerate(ids["alumnos"]):
        crits = []
        for j, crit in enumerate(["Contenido", "Estructura"]):
            nd = L[(i + j) % 4]
            ni = L[min((i + j) % 4 + (1 if (i + j) % 2 == 0 else 0), 3)]   # IA <= docente a veces
            crits.append({"criterio": crit, "nivel_ia": ni, "confianza_ia": 0.8,
                          "nivel_docente": nd})
        c.post(f"/api/v1/assessments/{ids['assessment']}/students/{sid}/rubrica/validar",
               json={"docente": "prof", "criterios": crits})
    yield {"ids": ids, "client": c}
    app.dependency_overrides.clear()


def test_psicometria_rubrica_de_4_niveles(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['ids']['assessment']}/rubrica/psicometria")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_estudiantes"] == 6 and body["n_criterios"] == 2   # NO quedo vacia
    assert "coef_g_relativo" in body["g_theory"]


def test_mfrm_rubrica_de_4_niveles(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['ids']['assessment']}/rubrica/mfrm")
    assert r.status_code == 200, r.text
    assert r.json()["disponible"] is True
