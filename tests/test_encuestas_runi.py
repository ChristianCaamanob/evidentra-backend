"""Encuestas de Runi, con piloto por RUT antes de soltarlas al curso.

El CEO lo pidió así: «necesito pilotearlo en Runi sólo en mi perfil, RUT 13620686-9, antes
de hacerlo masivo». La lista blanca quedó como capacidad general: cualquier encuesta puede
estrenarse con dos o tres personas y después abrirse a todos.
"""
from __future__ import annotations

import importlib
import pkgutil
import uuid

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.student import Student

API = "/api/v1"
_CEO_RUT = "13620686-9"


@pytest.fixture()
def ent():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng)

    def _db():
        d = TS()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[usuario_actual] = lambda: type(
        "U", (), {"rol": "creador", "id": "t", "email": "a@b.cl", "name": "Prof. Caamaño"})()
    c = TestClient(app)

    cid = c.post(f"{API}/courses/", json={"name": "Obstetricia", "code": "OBS-ENC",
                                          "grading_scale": "chile_1_7",
                                          "passing_threshold": 60.0}).json()["id"]
    with Session(eng) as s:
        s.add(Student(course_id=uuid.UUID(cid), rut=_CEO_RUT, nombres="Christian",
                      apellido_paterno="Caamaño"))
        s.add(Student(course_id=uuid.UUID(cid), rut="22222222-2", nombres="Ana",
                      apellido_paterno="Pérez"))
        s.commit()
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 200, "activo": True, "config": {}})
    cod = c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]

    def tok(rut):
        return c.post(f"{API}/silabo/{cod}/identificar", json={"valor": rut}).json()["ubicacion_token"]

    yield {"c": c, "cid": cid, "cod": cod, "tok": tok}
    app.dependency_overrides.clear()


def _crear(ent, **kw):
    body = {"pregunta": "¿Cómo te sientes con el ritmo del curso?",
            "opciones": ["Muy cómoda", "Bien", "Justo", "Me cuesta seguirlo"]}
    body.update(kw)
    return ent["c"].post(f"{API}/courses/{ent['cid']}/encuestas", json=body)


def test_crear_encuesta(ent):
    r = _crear(ent)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pregunta"].startswith("¿Cómo te sientes")
    assert len(d["opciones"]) == 4 and d["total"] == 0
    assert d["opciones"][0]["pct"] == 0, "sin votos no puede haber porcentaje"


def test_piloto_solo_para_el_rut_indicado(ent):
    """El corazón del pedido: la ve el CEO y NADIE más."""
    _crear(ent, solo_ruts=[_CEO_RUT])
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]

    mias = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok(_CEO_RUT)}).json()
    assert len(mias["encuestas"]) == 1, "el perfil del piloto no la ve"
    assert mias["encuestas"][0]["piloto"] is True

    otras = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok("22222222-2")}).json()
    assert otras["encuestas"] == [], "una compañera vio una encuesta en piloto"

    anon = c.post(f"{API}/silabo/{cod}/encuestas", json={}).json()
    assert anon["encuestas"] == [], "se vio sin identificarse siquiera"


def test_el_rut_se_reconoce_escrito_de_cualquier_forma(ent):
    """13.620.686-9, 136206869 y 13620686-9 son la misma persona."""
    _crear(ent, solo_ruts=["13.620.686-9"])
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    d = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok(_CEO_RUT)}).json()
    assert len(d["encuestas"]) == 1, "la lista blanca no toleró los puntos del RUT"


def test_votar_y_contar(ent):
    eid = _crear(ent, solo_ruts=[_CEO_RUT]).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    d = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 1}).json()
    assert d["total"] == 1 and d["mi_voto"] == 1
    assert d["opciones"][1]["n"] == 1 and d["opciones"][1]["pct"] == 100


def test_cambiar_de_opinion_no_infla_el_grafico(ent):
    """Si cada cambio sumara una fila, el gráfico mostraría quién insistió más."""
    eid = _crear(ent).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    t = tok(_CEO_RUT)
    c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar", json={"token": t, "opcion": 0})
    d = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar", json={"token": t, "opcion": 3}).json()
    assert d["total"] == 1, f"se acumularon votos: {d['total']}"
    assert d["opciones"][0]["n"] == 0 and d["opciones"][3]["n"] == 1


def test_no_se_puede_votar_en_una_que_no_te_toca(ent):
    eid = _crear(ent, solo_ruts=[_CEO_RUT]).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    r = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
               json={"token": tok("22222222-2"), "opcion": 0})
    assert r.status_code == 409


def test_sin_identidad_no_se_vota(ent):
    eid = _crear(ent).json()["id"]
    r = ent["c"].post(f"{API}/silabo/{ent['cod']}/encuestas/{eid}/votar", json={"opcion": 0})
    assert r.status_code >= 400, "votó alguien sin identificarse"


def test_abrirla_a_todo_el_curso(ent):
    """Terminado el piloto, se crea sin lista blanca y la ve todo el mundo."""
    _crear(ent)
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    for rut in (_CEO_RUT, "22222222-2"):
        d = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok(rut)}).json()
        assert len(d["encuestas"]) == 1, f"{rut} no la vio"
        assert d["encuestas"][0]["piloto"] is False


def test_cerrada_no_recibe_votos(ent):
    eid = _crear(ent).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    c.post(f"{API}/encuestas/{eid}/cerrar", json={"abierta": False})
    r = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 0})
    assert r.status_code == 409


def test_limites_de_forma(ent):
    assert _crear(ent, opciones=["Solo una"]).status_code == 422
    assert _crear(ent, pregunta="  ").status_code == 422
    assert _crear(ent, opciones=["a", "b", "c", "d", "e", "f", "g"]).status_code == 422
