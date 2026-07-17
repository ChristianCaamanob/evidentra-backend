"""
AS2 · Enrolamiento WebAuthn: opciones de registro (guarda challenge, exige validación
presencial), verificación con seam inyectable (una credencial activa) y recuperación.
La verificación real de py_webauthn se prueba en CI/prod con un autenticador; aquí se
inyecta un verificador stub para cubrir la lógica de persistencia y estados.
"""
from __future__ import annotations

import types

import app.models.course  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.answer_key  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.student  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.asistencia  # noqa: F401

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.course import Course
from app.models.asistencia import AsistenciaMatricula, DispositivoWebAuthn, MAT_ACTIVO, MAT_VALIDADO
from app.services import asistencia_service as asis
from app.services import asistencia_webauthn as awa

ORIGIN = "https://evalys-web.vercel.app"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine)
    s = TS()
    c = Course(name="Anatomía", code="ANAT-W", grading_scale="chile_1_7", passing_threshold=60.0)
    s.add(c); s.commit(); s.refresh(c)
    asis.importar_nomina(s, c.id, [{"nombre": "Ana", "correo": "ana@u.cl"}])
    yield s
    s.close()


def _matricula(db):
    return db.query(AsistenciaMatricula).first()


def test_opciones_exigen_validacion_presencial(db):
    m = _matricula(db)   # estado = invitado
    with pytest.raises(Exception):
        awa.opciones_registro(db, m.invite_token, ORIGIN)
    # tras validar presencialmente, sí entrega opciones con challenge guardado
    asis.validar_presencial(db, m.id)
    r = awa.opciones_registro(db, m.invite_token, ORIGIN)
    assert "options" in r and r["rp_id"] == "evalys-web.vercel.app"
    assert r["options"]["challenge"]                       # base64url
    db.refresh(m)
    assert m.webauthn_challenge and m.webauthn_challenge_exp


def test_registro_con_stub_una_credencial_activa(db):
    m = _matricula(db)
    asis.validar_presencial(db, m.id)
    awa.opciones_registro(db, m.invite_token, ORIGIN)

    def _stub(credential, expected_challenge, expected_rp_id, expected_origin):
        assert expected_rp_id == "evalys-web.vercel.app" and expected_origin == ORIGIN
        return types.SimpleNamespace(credential_id=b"cred-AAA", credential_public_key=b"pubkey",
                                     sign_count=0, aaguid="aaguid-1")

    out = awa.verificar_registro(db, m.invite_token, {"id": "x"}, ORIGIN, verify_fn=_stub)
    assert out["ok"] and out["estado"] == MAT_ACTIVO
    db.refresh(m)
    assert m.estado == MAT_ACTIVO and m.webauthn_challenge is None
    disp = db.query(DispositivoWebAuthn).filter(DispositivoWebAuthn.matricula_id == m.id).all()
    assert len([d for d in disp if d.activo]) == 1

    # registrar una segunda passkey -> la anterior queda revocada (UNA activa)
    awa.opciones_registro(db, m.invite_token, ORIGIN)
    def _stub2(credential, expected_challenge, expected_rp_id, expected_origin):
        return types.SimpleNamespace(credential_id=b"cred-BBB", credential_public_key=b"pk2",
                                     sign_count=0, aaguid="aaguid-2")
    awa.verificar_registro(db, m.invite_token, {"id": "y"}, ORIGIN, verify_fn=_stub2)
    disp = db.query(DispositivoWebAuthn).filter(DispositivoWebAuthn.matricula_id == m.id).all()
    activos = [d for d in disp if d.activo]
    assert len(activos) == 1 and activos[0].credential_id.startswith("Y3JlZC1CQkI")  # b64u de "cred-BBB"


def test_marcar_con_passkey_sobre_qr(db):
    """Aserción passkey atada al desafío del QR: identifica al alumno por su credencial y
    registra la marca. signCount que no aumenta → bandera (no rechazo)."""
    from datetime import datetime, timedelta, timezone
    from app.services import asistencia_service as asis
    m = _matricula(db)
    asis.validar_presencial(db, m.id)
    awa.opciones_registro(db, m.invite_token, ORIGIN)
    awa.verificar_registro(db, m.invite_token, {"id": "x"}, ORIGIN,
                           verify_fn=lambda **k: types.SimpleNamespace(
                               credential_id=b"cred-AAA", credential_public_key=b"pubkey",
                               sign_count=0, aaguid=""))
    cred_id_b64 = "Y3JlZC1BQUE"   # base64url de "cred-AAA"

    now = datetime.now(timezone.utc)
    s = asis.abrir_sesion(db, m.course_id, "t-1", "Clase", "2026-07-17",
                          (now - timedelta(minutes=1)).isoformat(), (now + timedelta(hours=1)).isoformat())
    qr = asis.qr_actual(db, s.codigo)

    def _va(credential, expected_challenge, expected_rp_id, expected_origin,
            credential_public_key, credential_current_sign_count):
        assert expected_rp_id == "evalys-web.vercel.app" and expected_origin == ORIGIN
        assert isinstance(expected_challenge, (bytes, bytearray)) and len(expected_challenge) == 32
        return types.SimpleNamespace(new_sign_count=1)

    out = awa.marcar_con_passkey(db, s.codigo, qr["bucket"], {"id": cred_id_b64}, ORIGIN,
                                 ip="1.2.3.4", ua="test", verify_fn=_va)
    assert out["estado"] == "presente" and out["duplicada"] is False

    # segunda marca del mismo alumno -> idempotente
    qr2 = asis.qr_actual(db, s.codigo)
    out2 = awa.marcar_con_passkey(db, s.codigo, qr2["bucket"], {"id": cred_id_b64}, ORIGIN,
                                  ip="1.2.3.4", ua="test", verify_fn=_va)
    assert out2["duplicada"] is True

    # QR vencido (bucket viejo) -> rechazo
    with pytest.raises(Exception):
        awa.marcar_con_passkey(db, s.codigo, qr["bucket"] - 10, {"id": cred_id_b64}, ORIGIN,
                               verify_fn=_va)


def test_recuperacion_revoca_y_vuelve_a_validado(db):
    m = _matricula(db)
    asis.validar_presencial(db, m.id)
    awa.opciones_registro(db, m.invite_token, ORIGIN)
    awa.verificar_registro(db, m.invite_token, {"id": "x"}, ORIGIN,
                           verify_fn=lambda **k: types.SimpleNamespace(
                               credential_id=b"c", credential_public_key=b"p", sign_count=0, aaguid=""))
    r = awa.revocar_dispositivos(db, m.id)
    assert r["revocados"] == 1 and r["estado"] == MAT_VALIDADO
    db.refresh(m)
    assert m.estado == MAT_VALIDADO
    assert all(not d.activo for d in db.query(DispositivoWebAuthn).all())
