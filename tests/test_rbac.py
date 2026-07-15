"""RBAC — garantías de autorización que el CI protege:

- Sin token: psicometría y export responden 401.
- Director: PUEDE exportar (lectura/export), pero NO escribe ni ve la psicometría profunda.
- Docente (profesor): auth pasa en escritura.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.core.db import SessionLocal
from app.models.teacher import Teacher, ROL_DIRECTOR
from app.services.auth_service import create_token, _token_payload, hash_password


@pytest.fixture(scope="module")
def client():
    with TestClient(m.app) as c:
        yield c


def _docente_token(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "docente@evalys.demo", "password": "evalys2026"})
    return r.json()["token"]


def _director_token():
    db = SessionLocal()
    try:
        t = db.query(Teacher).filter(Teacher.email == "director@rbac.test").first()
        if not t:
            t = Teacher(email="director@rbac.test", hashed_password=hash_password("x"),
                        name="Director RBAC", rol=ROL_DIRECTOR)
            db.add(t); db.commit(); db.refresh(t)
        return create_token(_token_payload(t))
    finally:
        db.close()


def _ids(client, tok):
    H = {"Authorization": "Bearer " + tok}
    cs = client.get("/api/v1/courses/", headers=H).json()
    arr = cs if isinstance(cs, list) else cs.get("items", [])
    cid = arr[0]["id"]
    a = client.get(f"/api/v1/assessments/by-course/{cid}", headers=H).json()
    aarr = a if isinstance(a, list) else a.get("items", [])
    return cid, (aarr[0]["id"] if aarr else None)


def test_sin_token_psicometria_y_export_401(client):
    z = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/assessments/{z}/psicometria/rasch").status_code == 401
    assert client.get(f"/api/v1/courses/{z}/export/consolidado.csv").status_code == 401


def test_director_puede_exportar(client):
    cid, _ = _ids(client, _docente_token(client))
    r = client.get(f"/api/v1/courses/{cid}/export/consolidado.csv",
                   headers={"Authorization": "Bearer " + _director_token()})
    assert r.status_code not in (401, 403), r.status_code   # director exporta (auth pasa)


def test_director_no_ve_psicometria_profunda(client):
    cid, aid = _ids(client, _docente_token(client))
    if not aid:
        pytest.skip("sin assessment sembrado")
    r = client.get(f"/api/v1/assessments/{aid}/psicometria/rasch",
                   headers={"Authorization": "Bearer " + _director_token()})
    assert r.status_code == 403   # req_investigador excluye a director


def test_director_no_escribe(client):
    cid, _ = _ids(client, _docente_token(client))
    r = client.post("/api/v1/assessments/",
                    headers={"Authorization": "Bearer " + _director_token()},
                    json={"name": "no-debe-crear", "course_id": cid, "n_questions": 10})
    assert r.status_code == 403   # director es solo lectura


def test_docente_si_escribe(client):
    tok = _docente_token(client)
    cid, _ = _ids(client, tok)
    r = client.post("/api/v1/assessments/", headers={"Authorization": "Bearer " + tok},
                    json={"name": "rbac-docente-ok", "course_id": cid, "n_questions": 10})
    assert r.status_code not in (401, 403), r.status_code   # profesor sí puede escribir
