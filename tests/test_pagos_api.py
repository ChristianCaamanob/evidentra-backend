"""
Monetizacion: planes/entitlements, ciclo de vida (trial -> checkout -> webhook idempotente ->
vencimiento -> cancelacion), la guardia requiere_plan (rol != plan) y los endpoints.
"""
from __future__ import annotations

from datetime import timedelta

import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.suscripcion  # noqa: F401

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual, requiere_plan
from app.models.base import Base
from app.services import pagos_service as pg
from app.services import planes_service as planes
from app.services.pagos_service import _ahora

from fastapi.testclient import TestClient

CUENTA = "11111111-1111-1111-1111-111111111111"
_PROF = type("U", (), {"id": CUENTA, "rol": "profesor"})()
_CREADOR = type("U", (), {"id": "999", "rol": "creador"})()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine)
    s = TS()
    try:
        yield s
    finally:
        s.close()


# ── registro de planes ──────────────────────────────────────────────────────────────
def test_entitlements_son_acumulativos():
    free = planes.entitlements_de_plan("free")
    pro = planes.entitlements_de_plan("profesor_pro")
    inv = planes.entitlements_de_plan("investigador")
    ent = planes.entitlements_de_plan("enterprise")
    assert free < pro < inv < ent            # subconjuntos estrictos
    assert planes.F_PSICOMETRIA in inv and planes.F_PSICOMETRIA not in pro
    assert planes.F_BANCO_IA in pro and planes.F_BANCO_IA not in free


def test_catalogo_precios():
    cat = planes.listar_planes()
    assert cat["profesor_pro"]["precio_clp"] == 7990
    assert cat["investigador"]["precio_clp"] == 29990
    assert cat["enterprise"]["precio_clp"] is None


# ── ciclo de vida ─────────────────────────────────────────────────────────────────────
def test_trial_da_premium_del_profesor(db):
    sus = pg.iniciar_trial(db, CUENTA)
    assert sus.estado == "trial" and sus.plan == "profesor_pro"
    ents = pg.entitlements_actuales(db, CUENTA, "profesor")
    assert planes.F_BANCO_IA in ents and planes.F_PSICOMETRIA not in ents
    # idempotente: segunda llamada no crea otra.
    assert pg.iniciar_trial(db, CUENTA).id == sus.id


def test_trial_vencido_cae_a_free(db):
    sus = pg.iniciar_trial(db, CUENTA)
    sus.fin_periodo = _ahora() - timedelta(days=1)   # ya vencio
    db.commit()
    assert pg.plan_efectivo(sus) == "free"
    assert planes.F_BANCO_IA not in pg.entitlements_actuales(db, CUENTA, "profesor")


def test_checkout_y_webhook_activan(db):
    pg.iniciar_trial(db, CUENTA)
    out = pg.iniciar_checkout(db, CUENTA, "investigador", cliente_pago=pg.gateway_fake())
    assert out["monto_clp"] == 29990 and out["token"].startswith("tok_")

    evento = {"token": out["token"], "tipo": "pago_confirmado", "plan": "investigador",
              "monto_clp": 29990, "idempotency_key": "flow-evt-1"}
    r1 = pg.procesar_evento(db, "fake", evento)
    assert r1["procesado"] is True and r1["estado"] == "activa" and r1["plan"] == "investigador"
    assert pg.tiene_feature(db, CUENTA, planes.F_PSICOMETRIA, "profesor") is True

    # webhook repetido -> no-op (idempotente).
    r2 = pg.procesar_evento(db, "fake", evento)
    assert r2["procesado"] is False


def test_checkout_enterprise_no_autoservicio(db):
    pg.iniciar_trial(db, CUENTA)
    with pytest.raises(HTTPException) as e:
        pg.iniciar_checkout(db, CUENTA, "enterprise", cliente_pago=pg.gateway_fake())
    assert e.value.status_code == 409


def test_cancelar_conserva_hasta_fin_periodo(db):
    pg.iniciar_trial(db, CUENTA)
    pg.iniciar_checkout(db, CUENTA, "investigador", cliente_pago=pg.gateway_fake())
    sus = pg.suscripcion_de(db, CUENTA)
    pg.procesar_evento(db, "fake", {"token": sus.ref_externa, "tipo": "pago_confirmado",
                                    "plan": "investigador", "idempotency_key": "e1"})
    pg.cancelar(db, CUENTA)
    # cancelada pero vigente -> conserva investigador hasta fin_periodo.
    assert pg.plan_efectivo(pg.suscripcion_de(db, CUENTA)) == "investigador"


# ── guardia requiere_plan (rol != plan) ────────────────────────────────────────────────
def test_requiere_plan_bloquea_y_permite(db):
    guard = requiere_plan(planes.F_PSICOMETRIA)
    pg.iniciar_trial(db, CUENTA)                     # trial = profesor_pro, sin psicometria
    with pytest.raises(HTTPException) as e:
        guard(usuario=_PROF, db=db)
    assert e.value.status_code == 402

    # el creador pasa siempre.
    assert guard(usuario=_CREADOR, db=db) is _CREADOR

    # tras pagar investigador, pasa.
    pg.iniciar_checkout(db, CUENTA, "investigador", cliente_pago=pg.gateway_fake())
    sus = pg.suscripcion_de(db, CUENTA)
    pg.procesar_evento(db, "fake", {"token": sus.ref_externa, "tipo": "pago_confirmado",
                                    "plan": "investigador", "idempotency_key": "e2"})
    assert guard(usuario=_PROF, db=db) is _PROF


# ── endpoints ───────────────────────────────────────────────────────────────────────
@pytest.fixture()
def cliente():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        s = TS()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _PROF
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_endpoints_flujo(cliente):
    assert cliente.get("/api/v1/planes").json()["investigador"]["precio_clp"] == 29990

    t = cliente.post("/api/v1/suscripciones/trial").json()
    assert t["estado"] == "trial" and planes.F_BANCO_IA in t["entitlements"]

    ck = cliente.post("/api/v1/suscripciones/checkout", json={"plan": "investigador"}).json()
    assert ck["monto_clp"] == 29990 and ck["url"].startswith("https://pago.fake/")

    wh = cliente.post("/api/v1/pagos/webhook/fake",
                      json={"token": ck["token"], "tipo": "pago_confirmado",
                            "plan": "investigador", "idempotency_key": "ep-1"}).json()
    assert wh["procesado"] is True and wh["plan"] == "investigador"

    mia = cliente.get("/api/v1/suscripciones/mia").json()
    assert mia["plan_efectivo"] == "investigador" and planes.F_PSICOMETRIA in mia["entitlements"]

    cancel = cliente.post("/api/v1/suscripciones/cancelar").json()
    assert cancel["estado"] == "cancelada"
