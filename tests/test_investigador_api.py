"""
Test de integracion del cableado Investigador (Fase 1): pegamento + endpoints
GET /assessments/{id}/psicometria/{rasch,dimensionalidad}.

Siembra una evaluacion real (escaneos con payload OCR) en SQLite en memoria y ejerce
tanto el servicio de matriz como los endpoints via TestClient.
"""
from __future__ import annotations

import uuid

import numpy as np

# Registrar todos los modelos antes de create_all (FKs).
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
from app.services import matriz_service


def _sembrar(engine, n=30, k=8, seed=1, anular_ultimo=False, en_revision=0, con_ra=True):
    rng = np.random.default_rng(seed)
    theta = rng.normal(0, 1, n)
    b = np.linspace(-1.5, 1.5, k)
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Solemne 1",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        for q in range(1, k + 1):
            s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                                correct_answer="A", weight=1.0,
                                is_annulled=(anular_ultimo and q == k),
                                learning_outcome_id=(f"RA{(q % 3) + 1}" if con_ra else None),
                                bloom_level="aplicar"))
        s.commit()
        for i in range(n):
            P = 1 / (1 + np.exp(-(theta[i] - b)))
            correcto = rng.random(k) < P
            answers = ["A" if c else "B" for c in correcto]
            s.add(Scan(assessment_id=a.id, student_identifier=f"{i}", status="scored",
                       detected_version="A", requires_review=False,
                       raw_ocr_payload_json={"answers": answers}))
        for j in range(en_revision):   # escaneos en revision: deben ignorarse
            s.add(Scan(assessment_id=a.id, student_identifier=f"rev{j}", status="uploaded",
                       detected_version="A", requires_review=True,
                       raw_ocr_payload_json={"answers": ["A"] * k}))
        s.commit()
        return str(a.id)


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine)
    TestingSession = sessionmaker(bind=engine)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield {"engine": engine, "assessment_id": aid, "client": TestClient(app),
           "Session": TestingSession}
    app.dependency_overrides.clear()


def test_pegamento_arma_matriz(entorno):
    with Session(entorno["engine"]) as s:
        datos = matriz_service.cargar_matriz_respuestas(s, uuid.UUID(entorno["assessment_id"]))
    assert datos["X"].shape == (30, 8)
    assert datos["items"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(p.startswith("e:") for p in datos["personas"])   # seudonimizado (G2)
    assert set(np.unique(datos["X"])) <= {0.0, 1.0}


def test_pegamento_excluye_anulados_e_ignora_en_revision():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine, n=20, k=6, anular_ultimo=True, en_revision=4)
    with Session(engine) as s:
        datos = matriz_service.cargar_matriz_respuestas(s, uuid.UUID(aid))
    assert datos["items"] == [1, 2, 3, 4, 5]      # el item 6 anulado se excluye
    assert datos["n_personas"] == 20              # los 4 en revision se ignoran


def test_endpoint_rasch(entorno):
    r = entorno["client"].get(f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/rasch")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_meta"]["n_personas"] == 30
    assert len(body["items"]) == 8
    assert all("pregunta" in it for it in body["items"])       # numero real de pregunta
    assert "fiabilidad" in body


def test_endpoint_dimensionalidad(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dimensionalidad")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "veredicto" in body and "fiabilidad" in body
    assert body["_meta"]["n_personas"] == 30
    assert body["n_factores"]["n_factores_sugeridos"] >= 1


def test_endpoint_dina(entorno):
    r = entorno["client"].get(f"/api/v1/assessments/{entorno['assessment_id']}/psicometria/dina")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["atributos"]) == 3                 # RA1, RA2, RA3 derivados de C3
    assert body["_meta"]["base_atributos"] == "ra"
    assert len(body["personas"]) == 30
    assert all("pregunta" in it for it in body["items"])


def test_dina_sin_etiquetas_c3_da_conflict():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine, con_ra=False)               # items sin RA -> no hay Q-matrix
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    try:
        r = TestClient(app).get(f"/api/v1/assessments/{aid}/psicometria/dina")
        assert r.status_code == 409                    # faltan etiquetas C3
    finally:
        app.dependency_overrides.clear()


def test_datos_insuficientes_da_conflict():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine, n=2, k=8)              # < 3 personas
    with Session(engine) as s:
        with pytest.raises(Exception):
            matriz_service.cargar_matriz_respuestas(s, uuid.UUID(aid))
