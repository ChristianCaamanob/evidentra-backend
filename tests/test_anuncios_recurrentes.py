"""
Comunicados de una vez vs. recurrentes.

Un aviso puede ser puntual («el certamen se cambió a la sala 302») o algo que hay que recordar cada
semana mientras dure el curso («traigan el delantal a cada práctico»). Antes solo existía lo primero.

Dos reglas que estos tests defienden:
- **Se repite el AVISO, no el anuncio.** No se crean filas nuevas: la bandeja del alumno conserva
  una sola entrada por comunicado, o se llenaría de copias del mismo texto.
- **Todo recurrente tiene fecha de término.** Sin ella se repite hasta que alguien se acuerde de
  apagarlo, y lo que pasa en la práctica es que nadie se acuerda: el alumno silencia los avisos del
  curso y deja de mirar también los importantes.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import pkgutil

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.anuncio import Anuncio
from app.models.base import Base
from app.services import anuncio_service as an

CID = "curso-1"


@pytest.fixture()
def db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    # El push real no se toca en los tests: aquí se mide la lógica de repetición, no la entrega.
    from app.services import push_service
    monkeypatch.setattr(push_service, "enviar_a_curso", lambda *a, **k: 3)
    yield s
    s.close()


def _hoy():
    return _dt.date.today()


def _en(dias):
    return (_hoy() + _dt.timedelta(days=dias)).isoformat()


# ── crear ────────────────────────────────────────────────────────────────────────────
def test_por_defecto_un_comunicado_es_de_una_vez(db):
    d = an.crear(db, CID, {"titulo": "Cambio de sala", "cuerpo": "Vamos a la 302."})
    a = d["anuncio"]
    assert a["repeticion"] == "unica" and not a["recurrente"]
    assert a["repeticion_texto"] == "Se avisa una vez"
    assert not a["vigente"]                       # no tiene que volver a sonar


def test_un_recurrente_sin_fecha_de_termino_recibe_una(db):
    """No se deja pasar: un aviso que se repite para siempre deja de ser un aviso."""
    a = an.crear(db, CID, {"titulo": "Delantal", "repeticion": "semanal"})["anuncio"]
    assert a["repetir_hasta"] and a["repetir_hasta"] > _hoy().isoformat()
    assert a["vigente"] and a["recurrente"]


def test_la_fecha_de_termino_no_puede_estar_en_el_pasado(db):
    with pytest.raises(Exception):
        an.crear(db, CID, {"titulo": "x", "repeticion": "semanal", "repetir_hasta": _en(-1)})


def test_no_se_repite_mas_de_cuatro_meses(db):
    a = an.crear(db, CID, {"titulo": "x", "repeticion": "semanal", "repetir_hasta": _en(900)})["anuncio"]
    tope = (_hoy() + _dt.timedelta(days=an._TOPE_DIAS)).isoformat()
    assert a["repetir_hasta"] == tope


def test_una_repeticion_inventada_se_rechaza(db):
    with pytest.raises(Exception):
        an.crear(db, CID, {"titulo": "x", "repeticion": "cada_hora"})


# ── el barrido ───────────────────────────────────────────────────────────────────────
def test_el_barrido_no_duplica_el_comunicado_en_la_bandeja(db):
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "diaria", "repetir_hasta": _en(30)})
    for _ in range(3):
        an.tick(db)
    assert db.query(Anuncio).count() == 1
    assert len(an.listar_por_course(db, CID)["anuncios"]) == 1


def test_llamarlo_varias_veces_el_mismo_dia_no_manda_varios_avisos(db):
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "diaria", "repetir_hasta": _en(30)})
    assert an.tick(db)["recurrentes_reenviados"] == 0     # ya sonó al crearse, hoy no le toca
    assert an.tick(db)["recurrentes_reenviados"] == 0


def test_cuando_le_toca_vuelve_a_sonar(db):
    a = an.crear(db, CID, {"titulo": "Delantal", "repeticion": "semanal", "repetir_hasta": _en(60)})["anuncio"]
    fila = db.query(Anuncio).first()
    fila.ultimo_envio = _en(-7); db.commit()
    r = an.tick(db)
    assert r["recurrentes_reenviados"] == 1 and r["push_enviados"] == 3
    assert db.query(Anuncio).first().veces_enviado == 2


def test_antes_de_que_le_toque_no_suena(db):
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "semanal", "repetir_hasta": _en(60)})
    fila = db.query(Anuncio).first()
    fila.ultimo_envio = _en(-3); db.commit()      # solo van 3 de los 7 días
    assert an.tick(db)["recurrentes_reenviados"] == 0


def test_pasada_la_fecha_de_termino_deja_de_sonar(db):
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "diaria", "repetir_hasta": _en(5)})
    fila = db.query(Anuncio).first()
    fila.repetir_hasta = _en(-1); fila.ultimo_envio = _en(-9); db.commit()
    assert an.tick(db)["recurrentes_reenviados"] == 0


def test_los_de_una_vez_nunca_entran_al_barrido(db):
    an.crear(db, CID, {"titulo": "Cambio de sala"})
    fila = db.query(Anuncio).first()
    fila.ultimo_envio = _en(-90); db.commit()
    assert an.tick(db)["recurrentes_reenviados"] == 0


def test_hay_un_tope_duro_de_veces(db):
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "diaria", "repetir_hasta": _en(100)})
    fila = db.query(Anuncio).first()
    fila.veces_enviado = an._TOPE_VECES; fila.ultimo_envio = _en(-9); db.commit()
    assert an.tick(db)["recurrentes_reenviados"] == 0


def test_cada_recordatorio_lleva_su_propia_etiqueta(db):
    """Sin eso el sistema operativo reemplaza el aviso anterior y el recordatorio pasa inadvertido."""
    an.crear(db, CID, {"titulo": "Delantal", "repeticion": "semanal", "repetir_hasta": _en(60)})
    fila = db.query(Anuncio).first()
    t1 = an._payload_push(fila)["tag"]
    fila.veces_enviado = 2
    assert an._payload_push(fila)["tag"] != t1


# ── apagarlo ─────────────────────────────────────────────────────────────────────────
def test_detener_apaga_la_repeticion_pero_conserva_el_texto(db):
    a = an.crear(db, CID, {"titulo": "Delantal", "cuerpo": "Todos los prácticos.",
                           "repeticion": "semanal", "repetir_hasta": _en(60)})["anuncio"]
    d = an.detener(db, a["id"])["anuncio"]
    assert d["repeticion"] == "unica" and not d["vigente"]
    assert d["cuerpo"] == "Todos los prácticos."          # sigue en la bandeja
    assert db.query(Anuncio).count() == 1


def test_detener_algo_que_no_existe_falla_claro(db):
    import uuid
    with pytest.raises(Exception):
        an.detener(db, uuid.uuid4())
