"""P3 · Panorama del Director: agregado por Departamento/Facultad."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Registrar todas las tablas que toca la agregación (ficha + validación + grupo).
import app.models.curriculo  # noqa: F401
import app.models.validacion  # noqa: F401
import app.models.grupo  # noqa: F401
import app.models.student  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.answer_key  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.course  # noqa: F401
from app.core.db import Base, _seed_ficha_p3
from app.services import director_service


@pytest.fixture()
def db():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    with Session(e) as s:
        _seed_ficha_p3(s)
        yield s


def test_panorama_agrupa_por_facultad_departamento(db):
    p = director_service.panorama(db)
    assert p["global"]["n_cursos"] == 2 and p["global"]["n_estudiantes"] == 12
    assert p["global"]["logro_promedio"] is not None
    assert len(p["facultades"]) == 1                                   # una facultad
    fac = p["facultades"][0]
    assert fac["facultad"] == "Facultad de Medicina" and fac["n_cursos"] == 2
    deps = {d["departamento"] for d in fac["departamentos"]}
    assert deps == {"Departamento de Anatomía", "Departamento de Fisiología"}
    assert p["global"]["top_brechas"] and p["global"]["top_brechas"][0]["n"] >= 1


def test_panorama_filtra_por_departamento(db):
    p = director_service.panorama(db, departamento="Departamento de Fisiología")
    assert p["global"]["n_cursos"] == 1
    assert len(p["facultades"]) == 1
    cursos = p["facultades"][0]["departamentos"][0]["cursos"]
    assert len(cursos) == 1 and cursos[0]["curso"] == "Demo · Fisiología"


def test_panorama_export_payload(db):
    out = director_service.panorama_export_payload(db)
    pl = out["payload"]
    assert pl["titulo"] and pl["tablas"] and pl["hojas"]
    t = pl["tablas"][0]
    assert t["headers"][0] == "Unidad"
    # facultad + 2 deptos + 2 cursos + TOTAL = 6 filas
    assert len(t["rows"]) == 6 and t["rows"][-1][0] == "TOTAL"
