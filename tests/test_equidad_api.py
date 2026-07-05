"""
Test de integracion del cableado de equidad (Fase 3b): DIF e invarianza por sexo/dependencia,
con las tres salvaguardas de la Ley 21.719 (lista blanca, consentimiento, minimo por grupo).
"""
from __future__ import annotations

import numpy as np

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
from app.api.deps import get_db
from app.models.base import Base
from app.models.course import Course
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.models.scan import Scan
from app.models.student import Student


def _sembrar(engine, n_por_grupo=30, k=6, item_dif=2, shift=1.8, seed=1, consent_f=30):
    rng = np.random.default_rng(seed)
    b = np.linspace(-1.2, 1.2, k)
    with Session(engine) as s:
        course = Course(name="Anatomia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Solemne 1",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        for q in range(1, k + 1):
            s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                                correct_answer="A", weight=1.0))
        s.commit()
        for grupo in ("M", "F"):
            for i in range(n_por_grupo):
                rut = f"{grupo}-{i}"
                consiente = True if grupo == "M" else (i < consent_f)
                s.add(Student(course_id=course.id, rut=rut, sexo=grupo,
                              dependencia=("municipal" if i % 2 == 0 else "particular"),
                              consiente_equidad=consiente))
                theta = rng.normal(0, 1)
                bb = b.copy()
                if grupo == "F":
                    bb[item_dif] += shift                # DIF plantado contra el grupo focal
                P = 1 / (1 + np.exp(-(theta - bb)))
                answers = ["A" if c else "B" for c in (rng.random(k) < P)]
                s.add(Scan(assessment_id=a.id, student_identifier=rut, status="scored",
                           detected_version="A", requires_review=False,
                           raw_ocr_payload_json={"answers": answers}))
        s.commit()
        return str(a.id)


def _cliente(engine):
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine)
    yield {"assessment_id": aid, "client": _cliente(engine)}
    app.dependency_overrides.clear()


def test_dif_por_sexo_marca_item_plantado(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dif?grupo=sexo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert 3 in body["items_con_dif"]                 # el item 3 (index 2) tiene DIF plantado
    assert body["_meta"]["comparados"] == ["M", "F"] or body["_meta"]["comparados"] == ["F", "M"]
    assert body["grupos"]["n_ref"] >= 10 and body["grupos"]["n_focal"] >= 10


def test_invarianza_por_sexo_marca_item(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/invarianza?grupo=sexo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert 3 in body["items_no_invariantes"]
    assert body["invariante"] is False


def test_dif_por_dependencia_corre(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dif?grupo=dependencia")
    assert r.status_code == 200, r.text          # 2 dependencias con datos -> corre


def test_variable_no_permitida_da_422(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dif?grupo=rut")
    assert r.status_code == 422                   # lista blanca (Ley 21.719)


def test_minimo_por_grupo_protege_reidentificacion():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine, consent_f=5)           # solo 5 mujeres consienten (< 10)
    client = _cliente(engine)
    try:
        r = client.get(f"/api/v1/assessments/{aid}/psicometria/dif?grupo=sexo")
        assert r.status_code == 409               # grupo focal < minimo -> no se analiza
    finally:
        app.dependency_overrides.clear()


def test_solo_consentidos_se_incluyen(entorno):
    # Todos consienten en el fixture base -> el DIF por sexo usa 60; ninguno excluido por consentimiento.
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dif?grupo=sexo")
    assert r.json()["_meta"]["excluidos_sin_consentimiento"] == 0
