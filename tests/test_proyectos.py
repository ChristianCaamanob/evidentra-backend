"""Proyectos de investigación (Fase A): CRUD + dueño + aislamiento entre investigadores."""
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.core.db import SessionLocal
from app.models.teacher import Teacher, ROL_INVESTIGADOR
from app.services.auth_service import create_token, _token_payload, hash_password


@pytest.fixture(scope="module")
def client():
    with TestClient(m.app) as c:
        yield c


def _investigador_token(email="investigador@evalys.demo"):
    db = SessionLocal()
    try:
        t = db.query(Teacher).filter(Teacher.email == email).first()
        if not t:
            t = Teacher(email=email, hashed_password=hash_password("x"),
                        name="Inv " + email, rol=ROL_INVESTIGADOR)
            db.add(t); db.commit(); db.refresh(t)
        return create_token(_token_payload(t))
    finally:
        db.close()


def _H(tok):
    return {"Authorization": "Bearer " + tok}


def test_crud_proyecto(client):
    tok = _investigador_token()
    # crear
    r = client.post("/api/v1/investigacion/proyectos",
                    headers=_H(tok),
                    json={"tipo": "revision", "titulo": "RS sobre feedback formativo",
                          "pregunta": "¿Efecto del feedback en logro?"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["tipo"] == "revision" and r.json()["estado"] == "borrador"

    # listar (aparece)
    lst = client.get("/api/v1/investigacion/proyectos", headers=_H(tok)).json()
    assert any(p["id"] == pid for p in lst["proyectos"])

    # actualizar con merge de datos + estado
    client.patch(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tok),
                 json={"estado": "activo", "datos": {"cribado": {"10.1/a": "incluir"}}})
    got = client.patch(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tok),
                       json={"datos": {"corpus_n": 120}}).json()
    assert got["estado"] == "activo"
    assert got["datos"]["cribado"] == {"10.1/a": "incluir"}  # merge no pisó lo anterior
    assert got["datos"]["corpus_n"] == 120

    # borrar
    assert client.delete(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tok)).status_code == 204
    assert client.get(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tok)).status_code == 404


def test_aislamiento_entre_investigadores(client):
    ta = _investigador_token("inv_a@evalys.test")
    tb = _investigador_token("inv_b@evalys.test")
    pid = client.post("/api/v1/investigacion/proyectos", headers=_H(ta),
                      json={"tipo": "datos", "titulo": "Estudio A"}).json()["id"]
    # B no puede ver ni borrar el proyecto de A
    assert client.get(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tb)).status_code == 403
    assert client.delete(f"/api/v1/investigacion/proyectos/{pid}", headers=_H(tb)).status_code == 403
    # y no aparece en la lista de B
    assert all(p["id"] != pid for p in client.get("/api/v1/investigacion/proyectos", headers=_H(tb)).json()["proyectos"])


def test_sin_token_401(client):
    assert client.get("/api/v1/investigacion/proyectos").status_code == 401


def test_tipo_invalido_422(client):
    tok = _investigador_token()
    r = client.post("/api/v1/investigacion/proyectos", headers=_H(tok),
                    json={"tipo": "loquesea", "titulo": "x"})
    assert r.status_code == 422
