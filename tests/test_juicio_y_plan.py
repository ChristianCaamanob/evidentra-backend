"""
Evidencia juzgada por Runi + plan semanal propio: lo que destraba el ascenso.

El repaso pedía «¿cómo se aplica esto? da un ejemplo», la estudiante escribía la respuesta y ese
texto **se descartaba**; lo único que quedaba era si ella misma se había puesto «Lo supe». Con eso no
se puede saber si conectó dos ideas ni si supo aplicar algo a un caso nuevo, así que las medallas 4,
5, 7 y 8 eran inalcanzables y el ascenso se cortaba en el tramo 4.

La regla que estos tests defienden por encima de todo: **una medalla no se gana ni se pierde por un
juicio del modelo solo**. Hace falta que el autorreporte y Runi coincidan.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import pkgutil
import uuid as _uuid

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.episode import Episode
from app.services import juicio_service as js
from app.services import plan_semanal_service as ps

PS = "stu:juez"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture()
def runi(monkeypatch):
    """Un Runi de mentira que devuelve lo que le digamos, sin llamar al modelo."""
    caja = {"correcto": True, "conceptos": ["a", "b", "c"], "razon": "ok"}
    monkeypatch.setattr(js, "_juzgar_con_ia", lambda *a, **k: (dict(caja) if caja else None))
    return caja


# ── el juicio ────────────────────────────────────────────────────────────────────────
def test_solo_cuenta_cuando_ambos_coinciden(db, runi):
    r = js.juzgar(db, PS, "aplicar", "pelvis", "Un caso de parto obstruido…", auto_reporte=True)
    assert r["concordancia"] and js.senales(db, PS)["novelTransferCases"] == 1


def test_si_runi_dice_que_no_y_ella_que_si_no_abre_puerta(db, runi):
    runi["correcto"] = False
    r = js.juzgar(db, PS, "aplicar", "pelvis", "Es el hueso de la cadera.", auto_reporte=True)
    assert not r["concordancia"]
    assert js.senales(db, PS)["novelTransferCases"] == 0
    assert "no coincidimos" in r["mensaje"].lower()


def test_si_ella_se_subestima_se_le_dice(db, runi):
    r = js.juzgar(db, PS, "recordar", "pelvis", "Respuesta buena pero insegura", auto_reporte=False)
    assert r["juicio"] is True and not r["concordancia"]
    assert "dura contigo" in r["mensaje"]


def test_el_motor_caido_no_es_una_respuesta_incorrecta(db, monkeypatch):
    """Dar por mala una respuesta porque la IA no contesta sería la injusticia que esto evita."""
    monkeypatch.setattr(js, "_juzgar_con_ia", lambda *a, **k: None)
    r = js.juzgar(db, PS, "aplicar", "pelvis", "Un caso concreto…", auto_reporte=True)
    assert r["juicio"] is None and r["sin_juicio"] and not r["concordancia"]
    assert "no pude revisarlo" in r["mensaje"].lower()


def test_la_respuesta_siempre_se_guarda(db, monkeypatch):
    monkeypatch.setattr(js, "_juzgar_con_ia", lambda *a, **k: None)
    js.juzgar(db, PS, "recordar", "pelvis", "lo que escribí", auto_reporte=True)
    assert js.mis_juicios(db, PS)["juicios"][0]["ra"] == "pelvis"


# ── anti-farming ─────────────────────────────────────────────────────────────────────
def test_la_misma_respuesta_repetida_no_vuelve_a_contar(db, runi):
    for _ in range(4):
        js.juzgar(db, PS, "aplicar", "pelvis", "  El MISMO caso   clínico.  ", auto_reporte=True)
    assert js.senales(db, PS)["novelTransferCases"] == 1


def test_conectar_A_con_B_es_la_misma_conexion_que_B_con_A(db, runi):
    js.juzgar(db, PS, "conectar", "pelvis", "El periné cierra el estrecho inferior.", auto_reporte=True, ra_b="periné")
    js.juzgar(db, PS, "conectar", "Periné", "Dicho al revés, con otras palabras.", auto_reporte=True, ra_b="Pelvis")
    assert js.senales(db, PS)["linkedConcepts"] == 1        # es la misma conexión
    js.juzgar(db, PS, "conectar", "pelvis", "El útero se apoya en el suelo pélvico.", auto_reporte=True, ra_b="útero")
    assert js.senales(db, PS)["linkedConcepts"] == 2        # otro par, otra conexión


def test_integrar_exige_tres_conceptos(db, runi):
    runi["conceptos"] = ["a", "b"]
    js.juzgar(db, PS, "integrar", "pelvis", "solo dos cosas", auto_reporte=True)
    assert js.senales(db, PS)["integratedOutcomes"] == 0
    runi["conceptos"] = ["a", "b", "c", "d"]
    js.juzgar(db, PS, "integrar", "pelvis", "cuatro conceptos articulados", auto_reporte=True)
    s = js.senales(db, PS)
    assert s["integratedOutcomes"] == 1 and s["conceptsIntegrated"] == 4


def test_un_tipo_invalido_se_rechaza(db, runi):
    with pytest.raises(Exception):
        js.juzgar(db, PS, "inventado", "pelvis", "x", auto_reporte=True)


# ── plan semanal ─────────────────────────────────────────────────────────────────────
def _episodios(db, n, cuando):
    for _ in range(n):
        db.add(Episode(id=_uuid.uuid4(), pseudo_id=PS, ra="x", verificado=True, completo=True,
                       started_at=cuando))
    db.commit()


def test_el_plan_lo_pone_ella_y_se_mide_con_episodios_verificados(db):
    ps.fijar(db, PS, 4)
    e = ps.estado(db, PS)
    assert e["meta"] == 4 and e["hechos"] == 0 and not e["cumplida"]
    _episodios(db, 3, _dt.datetime.utcnow())
    assert not ps.estado(db, PS)["cumplida"]      # 3 de 4 = 75%, por debajo del 80%
    _episodios(db, 1, _dt.datetime.utcnow())
    assert ps.estado(db, PS)["cumplida"]


def test_el_umbral_es_80_por_ciento(db):
    ps.fijar(db, PS, 5)
    _episodios(db, 3, _dt.datetime.utcnow())
    assert not ps.estado(db, PS)["cumplida"]      # 60%
    _episodios(db, 1, _dt.datetime.utcnow())
    assert ps.estado(db, PS)["cumplida"]          # 80%


def test_la_semana_en_curso_no_se_cuenta_como_cumplida(db):
    """Todavía puede completarse: contarla ahora sería adelantar un logro que no ocurrió."""
    ps.fijar(db, PS, 1)
    _episodios(db, 3, _dt.datetime.utcnow())
    assert ps.semanas_cumplidas(db, PS) == 0


def test_una_semana_pasada_cumplida_si_cuenta(db):
    pasada = _dt.date.today() - _dt.timedelta(days=7)
    ps.fijar(db, PS, 2, semana=ps.semana_de(pasada))
    _episodios(db, 2, _dt.datetime.combine(pasada, _dt.time(12, 0)))
    assert ps.semanas_cumplidas(db, PS) == 1


def test_una_meta_absurda_se_rechaza(db):
    for mala in (0, -3, 99, "muchos"):
        with pytest.raises(Exception):
            ps.fijar(db, PS, mala)


def test_la_sugerencia_mira_la_semana_pasada(db):
    pasada = _dt.date.today() - _dt.timedelta(days=7)
    _episodios(db, 3, _dt.datetime.combine(pasada, _dt.time(12, 0)))
    assert ps.estado(db, PS)["sugerencia"] == 4      # lo que lograste, +1


# ── el motor de logros ya no dice «en preparación» ───────────────────────────────────
def test_las_puertas_bloqueadas_quedan_instrumentadas(db, runi):
    from app.services import logros_service as ls
    est = ls.estado(db, PS)
    textos = [t for m in est["medals"] for t in m["falta_evidencia"]]
    assert not [t for t in textos if "en preparación" in t]


def test_una_transferencia_juzgada_se_ve_en_el_motor(db, runi):
    from app.services import logros_service as ls
    js.juzgar(db, PS, "aplicar", "pelvis", "Un caso nuevo y concreto", auto_reporte=True)
    sig = ls.estado(db, PS)["signals"]
    assert sig["novelTransferCases"] == 1
