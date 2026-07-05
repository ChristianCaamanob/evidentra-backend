"""
Test de RBAC: la matriz de roles (profesor/investigador/director/creador) tanto a nivel de
las guardas (unitario) como en endpoints reales con JWT.
"""
from __future__ import annotations

import uuid

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
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api import deps
from app.api.deps import req_profesor, req_investigador, req_lectura_datos, req_creador
from app.models.base import Base
from app.models.teacher import Teacher
from app.services import auth_service


def _u(rol):
    return type("U", (), {"rol": rol})()


# ── matriz de permisos a nivel de guarda (unitario) ─────────────────────────────────────
def test_guarda_investigador():
    assert req_investigador(usuario=_u("investigador")).rol == "investigador"
    assert req_investigador(usuario=_u("creador"))                 # creador siempre pasa
    for rol in ("profesor", "director"):
        with pytest.raises(HTTPException):
            req_investigador(usuario=_u(rol))


def test_guarda_profesor_incluye_investigador():
    for rol in ("profesor", "investigador", "creador"):
        assert req_profesor(usuario=_u(rol))                       # investigador es superconjunto
    for rol in ("director",):
        with pytest.raises(HTTPException):
            req_profesor(usuario=_u(rol))


def test_guarda_lectura_datos_incluye_director():
    for rol in ("profesor", "investigador", "director", "creador"):
        assert req_lectura_datos(usuario=_u(rol))                  # director ve/exporta datos


def test_guarda_creador_solo_creador():
    assert req_creador(usuario=_u("creador"))
    for rol in ("profesor", "investigador", "director"):
        with pytest.raises(HTTPException):
            req_creador(usuario=_u(rol))


# ── autorizacion real por endpoint (JWT) ────────────────────────────────────────────────
@pytest.fixture()
def tokens():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    toks = {}
    with Session(engine) as s:
        for rol in ("profesor", "investigador", "director", "creador"):
            t = Teacher(email=f"{rol}@evalys.cl", hashed_password="x", name=rol.title(), rol=rol)
            s.add(t); s.commit(); s.refresh(t)
            toks[rol] = auth_service.create_token(auth_service._token_payload(t))
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[deps.get_db] = _override      # NO se overridea usuario_actual: auth real
    yield {"client": TestClient(app), "tok": toks, "aid": str(uuid.uuid4())}
    app.dependency_overrides.clear()


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_investigador_endpoint_sin_token_401(tokens):
    r = tokens["client"].get(f"/api/v1/assessments/{tokens['aid']}/psicometria/rasch")
    assert r.status_code == 401


def test_investigador_endpoint_rol_incorrecto_403(tokens):
    for rol in ("profesor", "director"):
        r = tokens["client"].get(
            f"/api/v1/assessments/{tokens['aid']}/psicometria/rasch", headers=_h(tokens["tok"][rol]))
        assert r.status_code == 403, rol


def test_investigador_endpoint_rol_correcto_pasa_la_guarda(tokens):
    # investigador y creador pasan la guarda; como no hay datos, el cuerpo devuelve 409
    # (NO 401/403) -> prueba que la autorizacion dejo pasar.
    for rol in ("investigador", "creador"):
        r = tokens["client"].get(
            f"/api/v1/assessments/{tokens['aid']}/psicometria/rasch", headers=_h(tokens["tok"][rol]))
        assert r.status_code not in (401, 403), rol


def test_profesor_endpoint_scope(tokens):
    # precalificar es scope profesor: profesor/investigador/creador pasan (luego 404 por item
    # inexistente); director NO (403); sin token 401.
    url = f"/api/v1/answer-key-items/{uuid.uuid4()}/precalificar"
    assert tokens["client"].post(url, json={"respuesta": "x"}).status_code == 401
    assert tokens["client"].post(url, json={"respuesta": "x"},
                                 headers=_h(tokens["tok"]["director"])).status_code == 403
    for rol in ("profesor", "investigador", "creador"):
        r = tokens["client"].post(url, json={"respuesta": "x"}, headers=_h(tokens["tok"][rol]))
        assert r.status_code not in (401, 403), rol


def test_token_lleva_el_rol():
    t = type("T", (), {"id": uuid.uuid4(), "email": "a@b.cl", "rol": "investigador"})()
    payload = auth_service.decode_token(auth_service.create_token(auth_service._token_payload(t)))
    assert payload["rol"] == "investigador" and payload["email"] == "a@b.cl"
