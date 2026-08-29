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
    # Defectos elegidos: el estudiante NO ve el recuento y NO puede cambiar su voto.
    assert d["ver_resultados"] is False and d["permite_cambio"] is False


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


def test_votar_registra_solo_TU_respuesta(ent):
    """Por defecto el estudiante ve QUÉ eligió él, no cómo va el curso."""
    eid = _crear(ent, solo_ruts=[_CEO_RUT]).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    d = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 1}).json()
    assert d["mi_voto"] == 1
    assert d["total"] is None, "el total no puede viajar al estudiante"
    assert "n" not in d["opciones"][1] and "pct" not in d["opciones"][1], (
        "los conteos NO deben salir del servidor: ocultarlos solo en pantalla no sirve, "
        "bastaría mirar la respuesta de red")


def test_con_resultados_visibles_si_se_ve_el_recuento(ent):
    """Cuando el docente lo permite explícitamente, vuelve el gráfico completo."""
    eid = _crear(ent, solo_ruts=[_CEO_RUT], ver_resultados=True).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    d = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 1}).json()
    assert d["total"] == 1 and d["opciones"][1]["pct"] == 100


def test_el_docente_SIEMPRE_ve_el_recuento(ent):
    """Aunque el alumno no lo vea: es quien tiene que tomar la decisión."""
    _crear(ent, solo_ruts=[_CEO_RUT])
    d = ent["c"].get(f"{API}/courses/{ent['cid']}/encuestas").json()["encuestas"][0]
    assert d["total"] == 0 and "pct" in d["opciones"][0]


def test_no_se_puede_cambiar_la_respuesta(ent):
    """Se responde una vez y queda: es lo que hace que el resultado sirva para decidir."""
    eid = _crear(ent).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    t = tok(_CEO_RUT)
    assert c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
                  json={"token": t, "opcion": 0}).status_code == 200
    r = c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar", json={"token": t, "opcion": 3})
    assert r.status_code == 409, "pudo cambiar su voto"
    assert "Ya respondiste" in r.json()["detail"]
    # y el voto original sigue intacto
    d = ent["c"].get(f"{API}/courses/{ent['cid']}/encuestas").json()["encuestas"][0]
    assert d["opciones"][0]["n"] == 1 and d["opciones"][3]["n"] == 0


def test_si_el_docente_lo_permite_si_se_puede_cambiar(ent):
    eid = _crear(ent, permite_cambio=True).json()["id"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    t = tok(_CEO_RUT)
    c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar", json={"token": t, "opcion": 0})
    assert c.post(f"{API}/silabo/{cod}/encuestas/{eid}/votar",
                  json={"token": t, "opcion": 3}).status_code == 200
    d = ent["c"].get(f"{API}/courses/{ent['cid']}/encuestas").json()["encuestas"][0]
    assert d["opciones"][3]["n"] == 1 and d["opciones"][0]["n"] == 0, "debe MOVER, no acumular"


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


# ── Editar una encuesta ya publicada ──────────────────────────────────────────────────
# Sin esto, corregir una errata obligaba a borrar y volver a crear -perdiendo los votos-.

def test_corregir_una_errata_sin_perder_la_encuesta(ent):
    e = _crear(ent, opciones=["MARTES 08 DE SEPTIEMBRE", "MIÉCOLES 09 DE SPETIEMBRE"]).json()
    r = ent["c"].patch(f"{API}/encuestas/{e['id']}",
                       json={"opciones": ["MARTES 08 DE SEPTIEMBRE", "MIÉRCOLES 09 DE SEPTIEMBRE"]})
    assert r.status_code == 200, r.text
    assert r.json()["opciones"][1]["texto"] == "MIÉRCOLES 09 DE SEPTIEMBRE"
    assert r.json()["id"] == e["id"], "debe ser la MISMA encuesta, no una nueva"


def test_con_votos_se_corrige_el_texto_pero_no_se_agregan_opciones(ent):
    """Los votos guardan el índice: agregar o quitar movería lo que la gente eligió."""
    e = _crear(ent).json()
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    c.post(f"{API}/silabo/{cod}/encuestas/{e['id']}/votar",
           json={"token": tok(_CEO_RUT), "opcion": 2})

    ok = c.patch(f"{API}/encuestas/{e['id']}",
                 json={"opciones": ["Muy cómoda", "Bien", "Justo, pero llego", "Me cuesta seguirlo"]})
    assert ok.status_code == 200, "corregir el texto debe seguir permitido"
    assert ok.json()["opciones"][2]["n"] == 1, "el voto se mantuvo donde estaba"

    mal = c.patch(f"{API}/encuestas/{e['id']}", json={"opciones": ["Sí", "No"]})
    assert mal.status_code == 409, "quitar opciones con votos cambiaría lo que eligieron"


def test_se_puede_abrir_al_curso_editando_la_lista_blanca(ent):
    """Terminado el piloto: se quita la lista y la ve todo el curso, con sus votos intactos."""
    e = _crear(ent, solo_ruts=[_CEO_RUT]).json()
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    assert c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok("22222222-2")}).json()["encuestas"] == []

    c.patch(f"{API}/encuestas/{e['id']}", json={"solo_ruts": []})
    d = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok("22222222-2")}).json()
    assert len(d["encuestas"]) == 1 and d["encuestas"][0]["piloto"] is False


def test_sin_identidad_se_avisa_que_hay_algo_esperando_sin_revelarlo(ent):
    """El estudiante veía una pantalla vacía creyendo que no había nada que responder."""
    _crear(ent, solo_ruts=[_CEO_RUT])
    d = ent["c"].post(f"{API}/silabo/{ent['cod']}/encuestas", json={}).json()
    assert d["encuestas"] == [], "no puede filtrarse el contenido"
    assert d["requieren_identidad"] == 1, "pero sí hay que avisar que existe"
    # y ni la pregunta ni las opciones aparecen por ningún lado
    assert "Solemne" not in str(d) and "cómoda" not in str(d)


def test_identificado_no_queda_nada_esperando(ent):
    _crear(ent, solo_ruts=[_CEO_RUT])
    d = ent["c"].post(f"{API}/silabo/{ent['cod']}/encuestas",
                      json={"token": ent["tok"](_CEO_RUT)}).json()
    assert len(d["encuestas"]) == 1 and d["requieren_identidad"] == 0


# ── Ventana: fecha de activación y de cierre ──────────────────────────────────────────
import datetime as _dt


def _iso(h):
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=h)).isoformat()


def test_programada_no_se_ve_ni_se_vota(ent):
    """Antes de su fecha de activación no existe para el estudiante."""
    e = _crear(ent, solo_ruts=[_CEO_RUT], abre_at=_iso(3), cierra_at=_iso(48)).json()
    assert e["estado"] == "programada" and e["abre_at"]
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    assert c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok(_CEO_RUT)}).json()["encuestas"] == []
    r = c.post(f"{API}/silabo/{cod}/encuestas/{e['id']}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 0})
    assert r.status_code == 409 and "todavía no se abre" in r.json()["detail"]


def test_dentro_de_la_ventana_se_ve_y_se_vota(ent):
    e = _crear(ent, solo_ruts=[_CEO_RUT], abre_at=_iso(-1), cierra_at=_iso(24)).json()
    assert e["estado"] == "abierta"
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    d = c.post(f"{API}/silabo/{cod}/encuestas", json={"token": tok(_CEO_RUT)}).json()
    assert len(d["encuestas"]) == 1 and d["encuestas"][0]["cierra_at"]
    assert c.post(f"{API}/silabo/{cod}/encuestas/{e['id']}/votar",
                  json={"token": tok(_CEO_RUT), "opcion": 0}).status_code == 200


def test_pasada_la_fecha_de_cierre_se_cierra_sola(ent):
    """La ventana manda sobre el interruptor: es lo que se espera al poner una fecha."""
    e = _crear(ent, solo_ruts=[_CEO_RUT], abre_at=_iso(-48), cierra_at=_iso(-1)).json()
    assert e["estado"] == "cerrada", e
    c, tok, cod = ent["c"], ent["tok"], ent["cod"]
    r = c.post(f"{API}/silabo/{cod}/encuestas/{e['id']}/votar",
               json={"token": tok(_CEO_RUT), "opcion": 0})
    assert r.status_code == 409 and "cerrada" in r.json()["detail"]


def test_sin_fechas_sigue_funcionando_como_antes(ent):
    e = _crear(ent).json()
    assert e["estado"] == "abierta" and e["abre_at"] is None and e["cierra_at"] is None
