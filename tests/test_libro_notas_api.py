"""
Test del libro de notas unificado (P): una evaluacion MIXTA (alternativas + desarrollo)
produce una sola nota por estudiante, ponderada por item, con el desarrollo VALIDADO por el
docente y marca de 'pendiente' para quien aun no fue validado.
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
from app.models.scan import Scan
from app.models.validacion import RegistroValidacion
from app.services.matriz_service import _pseudo

_CREADOR = type("U", (), {"rol": "creador"})()

# 3 estudiantes: respuestas de alternativas (q1 correcta="A", q2 correcta="B").
ALUMNOS = {
    "A": ["A", "B"],   # ambas correctas
    "B": ["A", "X"],   # q1 ok, q2 mal
    "C": ["A", "B"],   # ambas correctas
}
# Validacion del desarrollo (q3, criterios C1/C2). "C" queda SIN validar -> pendiente.
DEV = {
    "A": {"C1": "logrado", "C2": "logrado"},
    "B": {"C1": "parcial", "C2": "no_logrado"},
}


def _sembrar(engine):
    with Session(engine) as s:
        course = Course(name="Anatomia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Mixta 1",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        # q1, q2 alternativas; q3 desarrollo con 2 criterios
        s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                            correct_answer="A", weight=1.0))
        s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=2, version="A",
                            correct_answer="B", weight=1.0))
        item3 = AnswerKeyItem(answer_key_id=ak.id, question_number=3, version="A",
                              correct_answer="", question_type="open_response", weight=1.0)
        s.add(item3); s.commit(); s.refresh(item3)
        s.add(RubricCriterion(answer_key_item_id=item3.id, name="C1", weight=1.0, order=0))
        s.add(RubricCriterion(answer_key_item_id=item3.id, name="C2", weight=1.0, order=1))
        s.commit()
        for nombre, respuestas in ALUMNOS.items():
            sc = Scan(assessment_id=a.id, student_identifier=nombre, status="scored",
                      detected_version="A", requires_review=False,
                      raw_ocr_payload_json={"answers": respuestas})
            s.add(sc); s.commit(); s.refresh(sc)
            pseudo = _pseudo(sc.id)
            for crit, nivel in DEV.get(nombre, {}).items():
                s.add(RegistroValidacion(
                    respuesta_ref=f"{pseudo}#{crit}", criterio=crit, nivel_ia=nivel,
                    confianza_ia=0.9, nivel_docente=nivel, accion="aprobado",
                    docente="prof.caamano", assessment_id=str(a.id)))
        s.commit()
        return str(a.id)


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _CREADOR
    yield {"assessment_id": aid, "client": TestClient(app)}
    app.dependency_overrides.clear()


def test_libro_notas_mixto(entorno):
    r = entorno["client"].get(f"/api/v1/assessments/{entorno['assessment_id']}/libro-notas")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_estudiantes"] == 3
    assert body["composicion"] == {"items_alternativas": 2, "items_desarrollo": 1, "mixta": True}
    por = {round(e["logro_pct"]): e for e in body["estudiantes"]}
    # Alumno A: 2 MC ok + desarrollo logrado/logrado -> 100% -> 7,0
    assert 100 in por and por[100]["nota"] == 7.0
    # Exactamente un estudiante con desarrollo pendiente (C, sin validar)
    assert body["resumen"]["pendientes_desarrollo"] == 1
    assert sum(1 for e in body["estudiantes"] if e["desarrollo_pendiente"]) == 1


def test_libro_notas_exige_rol(entorno):
    # sin el override de creador, el endpoint exige autenticacion
    app.dependency_overrides.pop(usuario_actual, None)
    r = entorno["client"].get(f"/api/v1/assessments/{entorno['assessment_id']}/libro-notas")
    assert r.status_code == 401
