"""
Test de integracion del cableado de desarrollo (Fase 2): POST validar (persiste F3) y los
GET de rubrica (MFRM, psicometria R, aprendizaje F4) que consumen lo persistido.
"""
from __future__ import annotations

# Registrar modelos antes de create_all (FKs).
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
from app.models.answer_key import AnswerKey
from app.models.scan import Scan

CRITERIOS = ["Tesis", "Evidencia", "Estructura"]
# 6 estudiantes x 3 criterios: nivel del docente (verdad) y de la IA (mas severa a veces).
DOCENTE = [
    ["logrado", "logrado", "parcial"],
    ["logrado", "parcial", "parcial"],
    ["parcial", "parcial", "no_logrado"],
    ["logrado", "logrado", "logrado"],
    ["parcial", "no_logrado", "no_logrado"],
    ["logrado", "parcial", "logrado"],
]
_BAJA = {"logrado": "parcial", "parcial": "no_logrado", "no_logrado": "no_logrado"}


def _sembrar(engine):
    scan_ids = []
    with Session(engine) as s:
        course = Course(name="Anatomia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Ensayo 1",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        s.add(AnswerKey(assessment_id=a.id, status="valid", is_valid=True)); s.commit()
        for i in range(len(DOCENTE)):
            sc = Scan(assessment_id=a.id, student_identifier=f"{i}", status="scored",
                      detected_version="A", requires_review=False,
                      raw_ocr_payload_json={"answers": []})
            s.add(sc); s.commit(); s.refresh(sc)
            scan_ids.append(str(sc.id))
        return str(a.id), scan_ids


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid, scan_ids = _sembrar(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield {"assessment_id": aid, "scan_ids": scan_ids, "client": TestClient(app)}
    app.dependency_overrides.clear()


def _validar_todos(entorno):
    c = entorno["client"]
    for i, sid in enumerate(entorno["scan_ids"]):
        criterios = []
        for j, crit in enumerate(CRITERIOS):
            nd = DOCENTE[i][j]
            ni = _BAJA[nd] if (i + j) % 2 == 0 else nd     # IA mas severa la mitad de las veces
            criterios.append({"criterio": crit, "nivel_ia": ni, "confianza_ia": 0.7,
                              "nivel_docente": nd, "comentario": None})
        r = c.post(f"/api/v1/results/{sid}/validar",
                   json={"docente": "prof.caamano", "rubrica_version_hash": "abc123",
                         "criterios": criterios})
        assert r.status_code == 200, r.text
    return c


def test_validar_persiste_y_devuelve_acuerdo(entorno):
    r = entorno["client"].post(
        f"/api/v1/results/{entorno['scan_ids'][0]}/validar",
        json={"docente": "prof.caamano", "rubrica_version_hash": "abc123",
              "criterios": [{"criterio": "Tesis", "nivel_ia": "parcial", "confianza_ia": 0.6,
                             "nivel_docente": "logrado", "comentario": "La analogia valia."}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_registrados"] == 1
    assert body["rubrica_version_hash"] == "abc123"
    assert "qwk" in body["acuerdo"]


def test_sin_validaciones_da_conflict(entorno):
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/rubrica/psicometria")
    assert r.status_code == 409       # aun no hay validaciones


def test_flujo_completo_mfrm(entorno):
    _validar_todos(entorno)
    r = entorno["client"].get(f"/api/v1/assessments/{entorno['assessment_id']}/rubrica/mfrm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disponible"] is True
    assert body["direccion"] in ("ia_mas_severa", "ia_mas_indulgente", "equivalente")


def test_flujo_completo_psicometria(entorno):
    _validar_todos(entorno)
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/rubrica/psicometria")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_estudiantes"] == 6 and body["n_criterios"] == 3
    assert "coef_g_relativo" in body["g_theory"]


def test_flujo_completo_aprendizaje(entorno):
    _validar_todos(entorno)
    r = entorno["client"].get(
        f"/api/v1/assessments/{entorno['assessment_id']}/rubrica/aprendizaje")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "propuestas" in body and "n_senales" in body
