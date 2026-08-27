"""Grupos de la Pandilla: los forman los alumnos y se entra escaneando un QR.

El CEO lo pidió durante el piloto: «no veo dónde invitar a los amigos de la pandilla para
formar los grupos; debiera generar un QR que escaneen sus compañeros». No existía nada:
el hub solo tenía identidad, personaje, disponibilidad y mapa.
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

    cid = c.post(f"{API}/courses/", json={"name": "Obstetricia", "code": "OBS-G",
                                          "grading_scale": "chile_1_7",
                                          "passing_threshold": 60.0}).json()["id"]
    with Session(eng) as s:
        for rut, nom in [("11111111-1", "Ana"), ("22222222-2", "Luis"), ("33333333-3", "Sofía")]:
            s.add(Student(course_id=uuid.UUID(cid), rut=rut, nombres=nom, apellido_paterno="Pérez"))
        s.commit()
    c.post(f"{API}/courses/{cid}/silabo", json={"contexto": "x" * 200, "activo": True, "config": {}})
    cod = c.get(f"{API}/courses/{cid}/silabo").json()["agente"]["codigo"]

    def token(rut):
        """El alumno se identifica contra la nómina: eso le da su token de identidad."""
        d = c.post(f"{API}/silabo/{cod}/identificar", json={"valor": rut}).json()
        assert d.get("ok"), d
        return d["ubicacion_token"]

    yield {"c": c, "cod": cod, "token": token, "cid": cid}
    app.dependency_overrides.clear()


def test_crear_grupo_devuelve_codigo_y_QR(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo",
               json={"token": tok("11111111-1"), "nombre": "Las Matronas"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert len(g["codigo"]) == 6, g["codigo"]
    assert g["qr"].startswith("data:image/png"), "sin QR no hay forma de invitar"
    assert "?grupo=" in g["join_url"]
    assert g["soy_creador"] is True and g["n_miembros"] == 1
    assert g["miembros"][0]["nombre"] == "Ana Pérez", "el creador entra con su nombre real"


def test_un_companero_se_une_escaneando(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo",
               json={"token": tok("11111111-1"), "nombre": "Las Matronas"}).json()
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse",
               json={"token": tok("22222222-2")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n_miembros"] == 2
    assert d["soy_miembro"] is True and d["soy_creador"] is False
    nombres = sorted(m["nombre"] for m in d["miembros"])
    assert nombres == ["Ana Pérez", "Luis Pérez"]


def test_escanear_dos_veces_no_duplica(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": tok("11111111-1")}).json()
    t = tok("22222222-2")
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse", json={"token": t})
    d = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse", json={"token": t}).json()
    assert d["n_miembros"] == 2, "volver a escanear el QR es normal, no debe duplicar"


def test_sin_identificarse_no_se_entra(ent):
    """El owner_key sale del token, nunca del cuerpo: si no, cualquiera dice ser otro."""
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": tok("11111111-1")}).json()
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse",
               json={"owner_key": "rut:99999999-9"})       # sin token
    assert r.status_code >= 400, "entró alguien que no se identificó"


def test_el_grupo_de_otro_curso_no_sirve(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": tok("11111111-1")}).json()
    # otro curso, con su propio sílabo
    cid2 = c.post(f"{API}/courses/", json={"name": "Otro", "code": "OTRO-G",
                                           "grading_scale": "chile_1_7",
                                           "passing_threshold": 60.0}).json()["id"]
    c.post(f"{API}/courses/{cid2}/silabo", json={"contexto": "y" * 200, "activo": True, "config": {}})
    cod2 = c.get(f"{API}/courses/{cid2}/silabo").json()["agente"]["codigo"]
    r = c.post(f"{API}/silabo/{cod2}/pandilla/grupo/{g['codigo']}/unirse",
               json={"token": tok("22222222-2")})
    assert r.status_code == 409, r.text


def test_mis_grupos_y_salir(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    t = tok("11111111-1")
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": t, "nombre": "Las Matronas"}).json()
    mios = c.post(f"{API}/silabo/{cod}/pandilla/mis-grupos", json={"token": t}).json()
    assert len(mios["grupos"]) == 1 and mios["grupos"][0]["nombre"] == "Las Matronas"

    d = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/salir", json={"token": t}).json()
    assert d["disuelto"] is True, "si se va el último, el grupo no debe quedar fantasma"
    mios = c.post(f"{API}/silabo/{cod}/pandilla/mis-grupos", json={"token": t}).json()
    assert mios["grupos"] == []


def test_solo_el_creador_cierra_el_grupo(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo", json={"token": tok("11111111-1")}).json()
    t2 = tok("22222222-2")
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse", json={"token": t2})
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/abierto",
               json={"token": t2, "abierto": False})
    assert r.status_code == 409, "un miembro cualquiera no puede cerrar el grupo"

    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/abierto",
               json={"token": tok("11111111-1"), "abierto": False})
    assert r.status_code == 200 and r.json()["abierto"] is False
    # y ya nadie más entra
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse",
               json={"token": tok("33333333-3")})
    assert r.status_code == 409, "el grupo cerrado siguió aceptando gente"


# ── Vida DENTRO del grupo: chat propio, sala y meta compartida ────────────────────────
# El grupo era solo una lista de integrantes: nada colgaba de él. El CEO lo preguntó
# directo («¿qué permite hacer dentro del grupo?») y la respuesta honesta era: nada.

def _grupo_con_dos(ent):
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    t1, t2 = tok("11111111-1"), tok("22222222-2")
    g = c.post(f"{API}/silabo/{cod}/pandilla/grupo",
               json={"token": t1, "nombre": "Las Matronas"}).json()
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{g['codigo']}/unirse", json={"token": t2})
    return g["codigo"], t1, t2


def test_el_chat_del_grupo_es_solo_del_grupo(ent):
    c, cod = ent["c"], ent["cod"]
    gcod, t1, t2 = _grupo_con_dos(ent)
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat",
               json={"token": t1, "texto": "¿Nos juntamos a las 6?"})
    assert r.status_code == 200, r.text
    feed = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat/feed",
                  json={"token": t2}).json()
    msgs = feed["mensajes"]
    assert len(msgs) == 1 and msgs[0]["texto"] == "¿Nos juntamos a las 6?"
    assert msgs[0]["mio"] is False, "para el segundo alumno el mensaje es ajeno"
    assert msgs[0]["nombre"] == "Ana Pérez"


def test_quien_no_es_del_grupo_no_lee_el_chat(ent):
    """Tener el código alcanza para PEDIR entrar, no para leer lo que el equipo conversa."""
    c, cod, tok = ent["c"], ent["cod"], ent["token"]
    gcod, t1, _t2 = _grupo_con_dos(ent)
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat", json={"token": t1, "texto": "secreto"})
    ajeno = tok("33333333-3")                      # está en el curso, pero no en el grupo
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat/feed", json={"token": ajeno})
    assert r.status_code == 409, f"leyó el chat sin ser miembro: {r.text[:150]}"
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat",
               json={"token": ajeno, "texto": "hola"})
    assert r.status_code == 409, "escribió en un grupo ajeno"


def test_el_chat_del_grupo_no_se_mezcla_con_el_del_curso(ent):
    c, cod = ent["c"], ent["cod"]
    gcod, t1, _ = _grupo_con_dos(ent)
    c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat", json={"token": t1, "texto": "del grupo"})
    # el chat del curso vive en otro ámbito
    curso_feed = c.get(f"{API}/alumno/pandilla/chat", params={"membresia_token": t1}).json()
    textos = [m["texto"] for m in curso_feed.get("mensajes", [])]
    assert "del grupo" not in textos, "el mensaje privado del grupo se filtró al curso entero"


def test_abrir_sala_de_estudio_avisa_en_el_chat_del_grupo(ent):
    c, cod = ent["c"], ent["cod"]
    gcod, t1, t2 = _grupo_con_dos(ent)
    r = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/sala",
               json={"token": t1, "device_id": "dev-ana"})
    assert r.status_code == 200, r.text
    sala = r.json()["sala"]
    assert sala.get("codigo"), sala
    feed = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/chat/feed",
                  json={"token": t2}).json()["mensajes"]
    assert any(sala["codigo"] in m["texto"] for m in feed), \
        "el código de la sala no llegó al chat: habría que pasarlo por fuera"


def test_meta_compartida_crear_y_aportar(ent):
    c, cod = ent["c"], ent["cod"]
    gcod, t1, t2 = _grupo_con_dos(ent)
    vacia = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/meta", json={"token": t1}).json()
    assert vacia["meta"] is None

    m = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/meta",
               json={"token": t1, "titulo": "Repasar parto normal"}).json()
    assert m["meta"]["titulo"] == "Repasar parto normal"

    d = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/meta",
               json={"token": t2, "aporte": 2}).json()
    assert d["meta"]["progreso"] == 2
    ap = d["meta"]["aportes"][0]
    assert ap["nombre"] == "Luis Pérez", "el grupo debe ver QUIÉN aportó, no un pseudo_id"
    assert ap["soy_yo"] is True and ap["cantidad"] == 2

    # volver a aportar SUMA al propio (hay un aporte por persona y meta)
    d = c.post(f"{API}/silabo/{cod}/pandilla/grupo/{gcod}/meta",
               json={"token": t2, "aporte": 3}).json()
    assert len(d["meta"]["aportes"]) == 1 and d["meta"]["progreso"] == 5
    assert d["meta"]["completado"] is True, "llegó a la meta por defecto (5)"


def test_el_docente_ve_como_se_organizo_su_clase(ent):
    c, cod, cid = ent["c"], ent["cod"], ent["cid"]
    gcod, _t1, _t2 = _grupo_con_dos(ent)
    r = c.get(f"{API}/courses/{cid}/pandilla/grupos")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resumen"]["n_grupos"] == 1
    assert d["resumen"]["n_estudiantes_en_grupo"] == 2
    g = d["grupos"][0]
    assert g["codigo"] == gcod and sorted(g["integrantes"]) == ["Ana Pérez", "Luis Pérez"]
    # y NUNCA lo que conversan dentro
    assert "mensajes" not in g and "chat" not in str(d).lower()
