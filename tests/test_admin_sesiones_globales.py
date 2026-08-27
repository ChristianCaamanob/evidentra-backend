"""El CEO debe poder ver QUÉ sesiones de grupo están abiertas en toda la plataforma.

Antes del piloto no existía: cada tipo se listaba solo por su código o por su evaluación, y
las salas de estudio que abren los propios alumnos no las listaba NADIE — existían y eran
invisibles para cualquier rol. Solo lectura, coherente con el modo fantasma de la consola.
"""
from __future__ import annotations

import importlib
import pkgutil
import uuid
from datetime import datetime, timedelta, timezone

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
from app.models.course import Course
from app.models.asistencia import SesionAsistencia

API = "/api/v1"
_CEO = type("U", (), {"rol": "creador", "id": "ceo-1", "email": "ceo@evalys.cl"})()
_PROFE = type("U", (), {"rol": "profesor", "id": "p-1", "email": "profe@evalys.cl"})()


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
    app.dependency_overrides[usuario_actual] = lambda: _CEO
    yield {"c": TestClient(app), "eng": eng}
    app.dependency_overrides.clear()


def _curso(eng, nombre="Obstetricia", code="OBS-1"):
    with Session(eng) as s:
        c = Course(name=nombre, code=code, grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(c); s.commit(); s.refresh(c)
        return str(c.id)


def test_sin_nada_abierto_responde_vacio_pero_bien_formado(ent):
    r = ent["c"].get(f"{API}/admin/consola/sesiones")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["resumen"]["abiertas"] == 0
    for k in ("salas_estudio", "en_vivo", "asistencia", "grupos_trabajo"):
        assert d[k] == [], f"{k} debía venir vacío"


def test_ve_la_sala_de_estudio_que_abre_un_alumno(ent):
    c, eng = ent["c"], ent["eng"]
    cid = _curso(eng)
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 120, "activo": True, "config": {}})
    cod_sil = c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]

    sala = c.post(f"{API}/salas", json={"silabo": cod_sil, "titulo": "Repaso de parto",
                                        "alias": "Ana", "device_id": "dev-ana"})
    assert sala.status_code in (200, 201), sala.text
    cod_sala = sala.json()["codigo"]

    d = c.get(f"{API}/admin/consola/sesiones").json()
    assert d["resumen"]["salas_estudio"] == 1
    una = d["salas_estudio"][0]
    assert una["codigo"] == cod_sala
    assert una["curso"] == "Obstetricia", "debe decir de qué curso es"
    assert una["abierta_por"] == "Ana", "debe decir quién la abrió"


def test_ve_la_sesion_de_asistencia_abierta_con_presentes(ent):
    c, eng = ent["c"], ent["eng"]
    cid = _curso(eng, "Fisiología", "FIS-1")
    ahora = datetime.now(timezone.utc)
    with Session(eng) as s:
        ses = SesionAsistencia(course_id=uuid.UUID(cid), abierta_por="p-1", titulo="Clase 1",
                               fecha=ahora.date().isoformat(), inicio=ahora - timedelta(minutes=5),
                               fin=ahora + timedelta(hours=2), estado="abierta",
                               codigo="ABC123", secreto="s3cr3t0")
        s.add(ses); s.commit()

    d = c.get(f"{API}/admin/consola/sesiones").json()
    assert d["resumen"]["asistencia"] == 1
    a = d["asistencia"][0]
    assert a["codigo"] == "ABC123" and a["curso"] == "Fisiología"
    assert a["presentes"] == 0, "aún nadie marcó"


def test_una_sesion_cerrada_ya_no_aparece(ent):
    c, eng = ent["c"], ent["eng"]
    cid = _curso(eng, "Anatomía", "ANA-1")
    ahora = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(SesionAsistencia(course_id=uuid.UUID(cid), abierta_por="p-1", titulo="Ayer",
                               fecha=ahora.date().isoformat(), inicio=ahora - timedelta(hours=3),
                               fin=ahora - timedelta(hours=1), estado="cerrada",
                               codigo="XYZ999", secreto="s"))
        s.commit()
    d = c.get(f"{API}/admin/consola/sesiones").json()
    assert d["asistencia"] == [], "el panel es de sesiones ABIERTAS"


def test_solo_el_ceo_entra(ent):
    app.dependency_overrides[usuario_actual] = lambda: _PROFE
    r = ent["c"].get(f"{API}/admin/consola/sesiones")
    assert r.status_code == 403, f"un profesor no debe ver la consola: HTTP {r.status_code}"


def test_la_lectura_queda_en_la_bitacora(ent):
    c = ent["c"]
    antes = len(c.get(f"{API}/admin/consola/accesos").json().get("accesos", []))
    c.get(f"{API}/admin/consola/sesiones")
    despues = c.get(f"{API}/admin/consola/accesos").json().get("accesos", [])
    assert len(despues) > antes, "mirar sesiones debe dejar asiento (protege al CEO)"
    assert any(a.get("recurso") == "sesiones" for a in despues), despues[:3]


# ── Los grupos de la Pandilla y sus chats también son "registro" ──────────────────────
# Se construyeron DESPUÉS de este panel y se habían quedado fuera: el CEO veía los grupos
# del docente (nota grupal) pero no los que forman los estudiantes entre ellos, ni sus
# conversaciones. Regla del CEO: «administrador, acceso completo de todo registro».

def _alumno_con_grupo(c, eng):
    """Deja formado un grupo de dos alumnos con un mensaje dentro."""
    import uuid as _u
    from app.models.student import Student
    cid = _curso(eng, "Obstetricia", "OBS-PG")
    with Session(eng) as s:
        for rut, nom in [("11111111-1", "Ana"), ("22222222-2", "Luis")]:
            s.add(Student(course_id=_u.UUID(cid), rut=rut, nombres=nom, apellido_paterno="Pérez"))
        s.commit()
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 200, "activo": True, "config": {}})
    cod = c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]
    tok = lambda rut: c.post(f"{API}/silabo/{cod}/identificar", json={"valor": rut}).json()["ubicacion_token"]
    t1, t2 = tok("11111111-1"), tok("22222222-2")
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": t1, "nombre": "Las Matronas"}).json()
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse", json={"token": t2})
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/chat",
           json={"token": t1, "texto": "Nos juntamos a las 6"})
    return cod, g["codigo"]


def test_el_admin_ve_los_grupos_que_arman_los_alumnos(ent):
    c, eng = ent["c"], ent["eng"]
    _cod, gcod = _alumno_con_grupo(c, eng)
    d = c.get(f"{API}/admin/consola/sesiones").json()
    assert d["resumen"]["grupos_pandilla"] == 1, d["resumen"]
    g = d["grupos_pandilla"][0]
    assert g["codigo"] == gcod
    assert sorted(g["integrantes"]) == ["Ana Pérez", "Luis Pérez"]


def test_el_admin_lee_el_chat_del_grupo(ent):
    c, eng = ent["c"], ent["eng"]
    _cod, gcod = _alumno_con_grupo(c, eng)
    d = c.get(f"{API}/admin/consola/chats").json()
    assert d["resumen"]["n_grupos"] == 1, d["resumen"]
    conv = [x for x in d["conversaciones"] if x["codigo"] == gcod][0]
    assert conv["tipo"] == "grupo" and conv["titulo"] == "Las Matronas"
    assert conv["mensajes"][0]["texto"] == "Nos juntamos a las 6"
    assert conv["mensajes"][0]["nombre"] == "Ana Pérez"


def test_solo_el_ceo_lee_los_chats(ent):
    app.dependency_overrides[usuario_actual] = lambda: _PROFE
    r = ent["c"].get(f"{API}/admin/consola/chats")
    assert r.status_code == 403, "un profesor no debe leer las conversaciones de la Pandilla"


def test_leer_los_chats_deja_asiento_en_la_bitacora(ent):
    c = ent["c"]
    c.get(f"{API}/admin/consola/chats")
    accesos = c.get(f"{API}/admin/consola/accesos").json().get("accesos", [])
    assert any(a.get("recurso") == "chats" for a in accesos), accesos[:3]
