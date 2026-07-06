"""
Generador de preguntas alineado a C3: capas puras (prompt/parser), camino IA con `llamar`
inyectado, fallback determinista a plantilla, y el endpoint que resuelve el RA del curso.
"""
from __future__ import annotations

import json

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
from app.models.curriculo import LearningOutcome
from app.services import generador_preguntas_service as gen

_CREADOR = type("U", (), {"rol": "creador"})()


# ── capas puras ───────────────────────────────────────────────────────────────────────
def test_prompt_incluye_ra_bloom_y_formato():
    system, user = gen.construir_prompt_generacion(
        "Reconoce las estructuras oseas del craneo", "analizar", n=3, dificultad="dificil",
        n_alternativas=4, norma="TA2")
    assert "arreglo JSON" in system
    assert "craneo" in user and "analizar" in user
    assert "3 preguntas" in user and "A, B, C, D" in user
    assert "TA2" in user and "DIFICIL" in user.upper()


def _payload_2_preguntas():
    return json.dumps([
        {"enunciado": "¿Cual hueso forma la frente?", "correcta": "b",
         "alternativas": {"A": "Occipital", "B": "Frontal", "C": "Parietal", "D": "Temporal"},
         "justificacion": "El frontal forma la frente.",
         "distractores": {"A": "confunde posterior con anterior"}},
        {"enunciado": "El agujero magno esta en el hueso...", "correcta": "A",
         "alternativas": {"A": "Occipital", "B": "Frontal", "C": "Etmoides", "D": "Esfenoides"},
         "justificacion": "El agujero magno perfora el occipital."},
    ])


def test_parsear_normaliza_y_valida():
    qs = gen.parsear_preguntas(_payload_2_preguntas(), n_alternativas=4)
    assert len(qs) == 2
    assert qs[0]["correcta"] == "B"                     # 'b' -> 'B'
    assert set(qs[0]["alternativas"]) == {"A", "B", "C", "D"}
    assert "A" in qs[0]["distractores"]                 # distractor de la incorrecta


def test_parsear_descarta_correcta_inexistente():
    mala = json.dumps([{"enunciado": "x", "correcta": "Z",
                        "alternativas": {"A": "1", "B": "2"}}])
    with pytest.raises(ValueError):
        gen.parsear_preguntas(mala, n_alternativas=2)


def test_parsear_sin_json_falla():
    with pytest.raises(ValueError):
        gen.parsear_preguntas("lo siento, no puedo", n_alternativas=4)


# ── camino IA (llamar inyectado) ───────────────────────────────────────────────────────
def test_generar_con_llm_stub_traza_c3():
    llamar = lambda system, user: _payload_2_preguntas()          # noqa: E731
    out = gen.generar_preguntas("RA craneo", "analizar", n=2, dificultad="media",
                                ra_code="RA1", llamar=llamar)
    assert out["origen"] == "ia" and out["meta"]["n_generadas"] == 2
    for q in out["preguntas"]:
        assert q["borrador"] is True and q["ra_code"] == "RA1" and q["bloom"] == "analizar"


def test_generar_recorta_a_n_solicitado():
    llamar = lambda s, u: _payload_2_preguntas()                  # noqa: E731
    out = gen.generar_preguntas("RA", "recordar", n=1, llamar=llamar)
    assert out["meta"]["n_generadas"] == 1


def test_error_del_modelo_cae_a_plantilla():
    def _explota(s, u):
        raise RuntimeError("timeout")
    out = gen.generar_preguntas("RA craneo", "aplicar", n=2, llamar=_explota)
    assert out["origen"] == "plantilla" and len(out["preguntas"]) == 2
    assert all(q["borrador"] for q in out["preguntas"])


def test_plantilla_sin_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = gen.generar_preguntas("Reconoce estructuras del craneo", "comprender", n=3)
    assert out["origen"] == "plantilla" and out["meta"]["n_generadas"] == 3
    assert out["preguntas"][0]["correcta"] == "A"


def test_ra_vacio_es_error():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        gen.generar_preguntas("", "aplicar", n=2)


# ── endpoint ────────────────────────────────────────────────────────────────────────────
def _sembrar(engine):
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Solemne 1",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ra = LearningOutcome(course_id=course.id, code="RA1",
                             text="Reconoce las estructuras oseas del craneo y su funcion.",
                             orden=1)
        s.add(ra); s.commit(); s.refresh(ra)
        return {"assessment": str(a.id), "ra": str(ra.id)}


@pytest.fixture()
def entorno(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)   # camino determinista en test
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


def test_endpoint_resuelve_ra_del_curso(entorno):
    ids, c = entorno["ids"], entorno["client"]
    r = c.post(f"/api/v1/assessments/{ids['assessment']}/preguntas/generar",
               json={"ra_id": ids["ra"], "bloom": "comprender", "n": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["ra_code"] == "RA1" and body["meta"]["n_generadas"] == 4
    assert all(q["borrador"] for q in body["preguntas"])
    assert "docente" in body["aviso"]


def test_endpoint_ra_texto_libre(entorno):
    ids, c = entorno["ids"], entorno["client"]
    r = c.post(f"/api/v1/assessments/{ids['assessment']}/preguntas/generar",
               json={"ra_texto": "Aplica la ley de Ohm", "bloom": "aplicar", "n": 2,
                     "n_alternativas": 5})
    assert r.status_code == 200
    assert len(r.json()["preguntas"][0]["alternativas"]) == 5


def test_endpoint_ra_inexistente_404(entorno):
    ids, c = entorno["ids"], entorno["client"]
    r = c.post(f"/api/v1/assessments/{ids['assessment']}/preguntas/generar",
               json={"ra_id": "00000000-0000-0000-0000-000000000000", "bloom": "recordar"})
    assert r.status_code == 404


def test_endpoint_sin_ra_422(entorno):
    ids, c = entorno["ids"], entorno["client"]
    r = c.post(f"/api/v1/assessments/{ids['assessment']}/preguntas/generar",
               json={"bloom": "recordar", "n": 2})
    assert r.status_code == 422
