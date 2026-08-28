"""Lo del grupo es del GRUPO, no del curso: chat, sala y meta.

Verificación pedida por el CEO. El atacante de estas pruebas no es un desconocido: es un
compañero del MISMO curso, verificado contra la nómina, que simplemente no pertenece al
grupo. Es el caso realista —y el que más incomodaría a una estudiante.
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
        "U", (), {"rol": "creador", "id": "t", "email": "a@b.cl"})()
    c = TestClient(app)

    cid = c.post(f"{API}/courses/", json={"name": "Obstetricia", "code": "OBS-AIS",
                                          "grading_scale": "chile_1_7",
                                          "passing_threshold": 60.0}).json()["id"]
    with Session(eng) as s:
        for rut, nom in [("11111111-1", "Ana"), ("22222222-2", "Luis"), ("33333333-3", "Sofía")]:
            s.add(Student(course_id=uuid.UUID(cid), rut=rut, nombres=nom, apellido_paterno="Pérez"))
        s.commit()
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 200, "activo": True, "config": {}})
    cod = c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]

    def tok(rut):
        return c.post(f"{API}/silabo/{cod}/identificar", json={"valor": rut}).json()["ubicacion_token"]

    dentro = tok("11111111-1")                 # Ana: crea el grupo
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo",
               json={"token": dentro, "nombre": "Las Matronas"}).json()
    fuera = tok("33333333-3")                  # Sofía: MISMO curso, NO del grupo
    yield {"c": c, "cod": cod, "g": g["codigo"], "dentro": dentro, "fuera": fuera}
    app.dependency_overrides.clear()


def _u(ent, ruta):
    return f"{API}/silabo/{ent['cod']}/pandilla/grupo/{ent['g']}{ruta}"


def test_chat_leer_solo_integrantes(ent):
    c = ent["c"]
    c.post(_u(ent, "/chat"), json={"token": ent["dentro"], "texto": "nos juntamos a las 6"})
    r = c.post(_u(ent, "/chat/feed"), json={"token": ent["fuera"]})
    assert r.status_code == 409, f"un compañero ajeno leyó el chat del grupo: {r.text[:150]}"


def test_chat_escribir_solo_integrantes(ent):
    r = ent["c"].post(_u(ent, "/chat"), json={"token": ent["fuera"], "texto": "hola"})
    assert r.status_code == 409, "un compañero ajeno escribió en el chat del grupo"


def test_meta_ver_solo_integrantes(ent):
    c = ent["c"]
    c.post(_u(ent, "/meta"), json={"token": ent["dentro"], "titulo": "Repasar parto"})
    r = c.post(_u(ent, "/meta"), json={"token": ent["fuera"]})
    assert r.status_code == 409, "un ajeno vio la meta del grupo"


def test_meta_aportar_y_crear_solo_integrantes(ent):
    c = ent["c"]
    c.post(_u(ent, "/meta"), json={"token": ent["dentro"], "titulo": "Repasar parto"})
    assert c.post(_u(ent, "/meta"), json={"token": ent["fuera"], "aporte": 3}).status_code == 409
    assert c.post(_u(ent, "/meta"), json={"token": ent["fuera"], "titulo": "otra"}).status_code == 409


def test_abrir_sala_solo_integrantes(ent):
    r = ent["c"].post(_u(ent, "/sala"), json={"token": ent["fuera"], "device_id": "d"})
    assert r.status_code == 409, "un ajeno abrió una sala a nombre del grupo"


def test_cerrar_o_abrir_el_grupo_solo_el_creador(ent):
    r = ent["c"].post(_u(ent, "/abierto"), json={"token": ent["fuera"], "abierto": False})
    assert r.status_code == 409


def test_la_sala_del_grupo_no_queda_abierta_al_curso(ent):
    """Quien tenga el CÓDIGO de la sala no debería entrar si no es del grupo.

    La sala se crea desde el grupo, pero es una SalaEstudio normal: si unirse solo pide el
    código, el aislamiento del grupo se pierde en cuanto ese código circula.
    """
    c = ent["c"]
    d = c.post(_u(ent, "/sala"), json={"token": ent["dentro"], "device_id": "dev-ana"}).json()
    cod_sala = d["sala"]["codigo"]
    r = c.post(f"{API}/salas/{cod_sala}/unirse",
               json={"alias": "Sofía", "device_id": "dev-sofia"})
    assert r.status_code >= 400, (
        "una compañera ajena al grupo entró a su sala solo con el código "
        f"(HTTP {r.status_code})")


def test_los_integrantes_SI_entran_a_su_sala(ent):
    """El aislamiento no puede dejar fuera a los del grupo."""
    c = ent["c"]
    d = c.post(_u(ent, "/sala"), json={"token": ent["dentro"], "device_id": "dev-ana"}).json()
    cod = d["sala"]["codigo"]
    r = c.post(f"{API}/salas/{cod}/unirse",
               json={"alias": "Ana", "device_id": "dev-ana", "token": ent["dentro"]})
    assert r.status_code == 200, r.text


def test_la_sala_de_grupo_tampoco_se_MIRA_desde_fuera(ent):
    """Mirar el estado también es entrar: ahí van los mensajes de la sala."""
    c = ent["c"]
    cod = c.post(_u(ent, "/sala"), json={"token": ent["dentro"], "device_id": "dev-ana"}).json()["sala"]["codigo"]
    r = c.get(f"{API}/salas/{cod}", params={"device_id": "dev-sofia"})
    assert r.status_code >= 400, "se pudo espiar la sala del grupo sin ser integrante"
    r2 = c.get(f"{API}/salas/{cod}", params={"device_id": "dev-ana", "token": ent["dentro"]})
    assert r2.status_code == 200, "un integrante no pudo mirar su propia sala"


def test_las_salas_abiertas_del_curso_siguen_siendo_abiertas(ent):
    """Las salas de estudio normales son públicas a propósito: basta el código.

    El aislamiento aplica SOLO a las que nacen de un grupo; si se hubiera aplicado a
    todas, se habría roto la sala de estudio abierta del curso, que es otra función.
    """
    c, cod_sil = ent["c"], ent["cod"]
    abierta = c.post(f"{API}/salas", json={"silabo": cod_sil, "titulo": "Repaso abierto",
                                           "alias": "Ana", "device_id": "dev-ana"}).json()
    r = c.post(f"{API}/salas/{abierta['codigo']}/unirse",
               json={"alias": "Sofía", "device_id": "dev-sofia"})     # sin token
    assert r.status_code == 200, "se rompió la sala de estudio abierta"
