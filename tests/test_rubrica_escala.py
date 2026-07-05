"""
Test del robustecimiento de rubricas: niveles parametrizables con puntajes propios
(Excelente/Bueno/Regular/Deficiente = 3/2/1/0) + factores, reproducidos en el libro de notas.
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
from app.services import rubrica_escala_service as esc

_CREADOR = type("U", (), {"rol": "creador"})()

# Niveles al estilo de la rubrica real (Presentacion Infografia DMOR 0030).
NIVELES = [
    {"nivel": "Excelente", "puntos": 3, "descriptor": "Claro, completo e integrado."},
    {"nivel": "Bueno", "puntos": 2, "descriptor": "Adecuado, con leves omisiones."},
    {"nivel": "Regular", "puntos": 1, "descriptor": "Parcial o superficial."},
    {"nivel": "Deficiente", "puntos": 0, "descriptor": "Incompleto o incorrecto."},
]


# ── unitario de la escala ───────────────────────────────────────────────────────────────
def test_fraccion_logro_por_puntajes():
    assert esc.fraccion_logro(NIVELES, "Excelente") == 1.0
    assert round(esc.fraccion_logro(NIVELES, "Bueno"), 3) == 0.667
    assert round(esc.fraccion_logro(NIVELES, "Regular"), 3) == 0.333
    assert esc.fraccion_logro(NIVELES, "Deficiente") == 0.0
    assert esc.fraccion_logro(NIVELES, "inexistente") == 0.0


def test_fraccion_default_sin_niveles():
    # Sin niveles definidos -> escala de 3 por defecto (logrado=1, parcial=0.5, no_logrado=0).
    assert esc.fraccion_logro(None, "logrado") == 1.0
    assert esc.fraccion_logro(None, "parcial") == 0.5
    assert esc.fraccion_logro(None, "no_logrado") == 0.0


def test_nivel_canonico_por_rango():
    assert esc.nivel_canonico(NIVELES, "Excelente") == "logrado"     # el mejor
    assert esc.nivel_canonico(NIVELES, "Deficiente") == "no_logrado"  # el peor
    assert esc.nivel_canonico(NIVELES, "Bueno") == "parcial"          # intermedio
    assert esc.nivel_canonico(NIVELES, "Regular") == "parcial"


# ── integracion: libro de notas con niveles + factores ──────────────────────────────────
def _sembrar(engine):
    ids = {}
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Presentacion infografia",
                       modalidad="oral", grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        # 2 items (criterios) con factor 2 y 1, cada uno con la escala de 4 niveles.
        for qn, (crit, factor, seccion) in enumerate([
                ("Contenido", 2.0, "Contenido"), ("Tiempo", 1.0, "Organizacion")], start=1):
            it = AnswerKeyItem(answer_key_id=ak.id, question_number=qn, version="A",
                               correct_answer="", question_type="open_response", weight=factor)
            s.add(it); s.commit(); s.refresh(it)
            s.add(RubricCriterion(answer_key_item_id=it.id, name=crit, weight=1.0, order=0,
                                  niveles_json=NIVELES, seccion=seccion, ambito="grupal"))
        s.commit()
        for nombre in ("Ana", "Beto"):
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


def _validar(c, aid, sid, niveles):
    return c.post(f"/api/v1/assessments/{aid}/students/{sid}/rubrica/validar",
                  json={"docente": "prof", "criterios": [
                      {"criterio": k, "nivel_docente": v} for k, v in niveles.items()]})


def test_libro_con_niveles_y_factores(entorno):
    ids, c = entorno["ids"], entorno["client"]
    _validar(c, ids["assessment"], ids["Ana"], {"Contenido": "Excelente", "Tiempo": "Excelente"})
    _validar(c, ids["assessment"], ids["Beto"], {"Contenido": "Excelente", "Tiempo": "Regular"})
    body = c.get(f"/api/v1/assessments/{ids['assessment']}/libro-notas").json()
    por = {e["logro_pct"]: e for e in body["estudiantes"]}
    # Ana: todo Excelente -> 100% -> 7,0
    assert 100.0 in por and por[100.0]["nota"] == 7.0
    # Beto: Contenido Excelente (frac 1, factor 2) + Tiempo Regular (frac 1/3, factor 1)
    #       = (1*2 + 0.333*1) / 3 = 77,8%
    assert 77.8 in por
