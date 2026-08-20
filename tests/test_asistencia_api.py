"""
Asistencia (AS1): nómina, sesión con ventana horaria, QR dinámico firmado (HMAC), marca,
panel docente y override. La cripto de passkeys (AS2/AS3) se prueba aparte.
"""
from __future__ import annotations

import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.asistencia  # noqa: F401

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.course import Course

_CREADOR = type("U", (), {"rol": "creador", "id": "t-1"})()


def _sembrar(engine):
    with Session(engine) as s:
        c = Course(name="Anatomía", code="ANAT-2026", grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(c); s.commit(); s.refresh(c)
        return str(c.id)


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    cid = _sembrar(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _CREADOR
    yield {"cid": cid, "client": TestClient(app), "engine": engine}
    app.dependency_overrides.clear()


def test_flujo_asistencia_qr_firmado(entorno):
    cid, c = entorno["cid"], entorno["client"]

    # 1) importar nómina (JSON)
    r = c.post(f"/api/v1/asistencia/{cid}/nomina", json={"filas": [
        {"nombre": "Ana Pérez", "correo": "ana@u.cl", "identificador": "A1", "seccion": "1"},
        {"nombre": "Beto Soto", "correo": "beto@u.cl", "identificador": "B2", "seccion": "1"}]})
    assert r.status_code == 200 and r.json()["creados"] == 2

    nomina = c.get(f"/api/v1/asistencia/{cid}/nomina").json()["matriculas"]
    assert len(nomina) == 2 and all(m["estado"] == "invitado" for m in nomina)
    ana = next(m for m in nomina if m["nombre"] == "Ana Pérez")

    # validación presencial
    assert c.post(f"/api/v1/asistencia/matricula/{ana['id']}/validar").json()["estado"] == "validado"

    # 2) abrir sesión con ventana horaria que incluye "ahora"
    now = datetime.now(timezone.utc)
    ses = c.post(f"/api/v1/asistencia/{cid}/sesiones", json={
        "titulo": "Clase 1", "fecha": "2026-07-17",
        "inicio": (now - timedelta(minutes=1)).isoformat(),
        "fin": (now + timedelta(hours=1)).isoformat()}).json()
    cod = ses["codigo"]
    assert ses["estado"] == "abierta"

    # 3) QR vigente (desafío firmado + bucket)
    qr = c.get(f"/api/v1/asistencia/sesion/{cod}/qr").json()
    # Derivado de la constante, no cableado: el ritmo de rotación se ajustó porque con 4 s
    # la cámara del alumno no alcanzaba a enfocar el código antes de que cambiara.
    from app.services.asistencia_service import BUCKET_SEG
    assert qr["token"] and qr["rota_cada"] == BUCKET_SEG and 0 <= qr["vence_en"] <= BUCKET_SEG

    # 4) marca con el desafío correcto -> presente
    r = c.post(f"/api/v1/asistencia/sesion/{cod}/marcar",
               json={"matricula_id": ana["id"], "token": qr["token"], "bucket": qr["bucket"]})
    assert r.status_code == 200 and r.json()["estado"] == "presente"

    # marca duplicada -> idempotente
    r2 = c.post(f"/api/v1/asistencia/sesion/{cod}/marcar",
                json={"matricula_id": ana["id"], "token": qr["token"], "bucket": qr["bucket"]})
    assert r2.json()["duplicada"] is True

    # desafío inválido (token falso) -> 409
    bad = c.post(f"/api/v1/asistencia/sesion/{cod}/marcar",
                 json={"matricula_id": ana["id"], "token": "xxxx", "bucket": qr["bucket"]})
    assert bad.status_code == 409

    # bucket viejo (vencido) -> 409
    viejo = c.post(f"/api/v1/asistencia/sesion/{cod}/marcar",
                   json={"matricula_id": ana["id"], "token": qr["token"], "bucket": qr["bucket"] - 5})
    assert viejo.status_code == 409

    # 5) panel docente — la sesión y cada marca registran fecha/hora (auditoría)
    est = c.get(f"/api/v1/asistencia/sesion/{cod}/estado").json()
    assert est["total"] == 2 and est["presentes"] == 1 and est["ausentes"] == 1
    assert est["fecha"] == "2026-07-17" and est["inicio"] and est["fin"]
    assert est["abierta_at"] and est["abierta_por"]           # momento y autor de la apertura
    fila_ana = next(f for f in est["filas"] if f["matricula_id"] == ana["id"])
    assert fila_ana["presente"] and fila_ana["hora"]          # hora exacta en que marcó

    # 6) override manual del docente (Beto presente)
    beto = next(m for m in nomina if m["nombre"] == "Beto Soto")
    o = c.post(f"/api/v1/asistencia/sesion/{cod}/override",
               json={"matricula_id": beto["id"], "estado": "presente"})
    assert o.json()["estado"] == "presente"
    assert c.get(f"/api/v1/asistencia/sesion/{cod}/estado").json()["presentes"] == 2


def test_export_asistencia_xlsx(entorno):
    """El informe de asistencia exporta a Excel con fecha/hora y detalle por alumno."""
    cid, c = entorno["cid"], entorno["client"]
    from datetime import datetime, timedelta, timezone
    c.post(f"/api/v1/asistencia/{cid}/nomina", json={"filas": [{"nombre": "Ana", "correo": "a@u.cl"}]})
    mid = c.get(f"/api/v1/asistencia/{cid}/nomina").json()["matriculas"][0]["id"]
    now = datetime.now(timezone.utc)
    cod = c.post(f"/api/v1/asistencia/{cid}/sesiones", json={
        "titulo": "Clase", "fecha": "2026-07-17",
        "inicio": (now - timedelta(minutes=1)).isoformat(),
        "fin": (now + timedelta(hours=1)).isoformat()}).json()["codigo"]
    qr = c.get(f"/api/v1/asistencia/sesion/{cod}/qr").json()
    c.post(f"/api/v1/asistencia/sesion/{cod}/marcar",
           json={"matricula_id": mid, "token": qr["token"], "bucket": qr["bucket"]})
    r = c.post(f"/api/v1/asistencia/sesion/{cod}/informe/xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_fuera_de_ventana_rechaza(entorno):
    """Marca fuera de la ventana horaria -> rechazada."""
    cid, c = entorno["cid"], entorno["client"]
    c.post(f"/api/v1/asistencia/{cid}/nomina", json={"filas": [{"nombre": "Zoe", "correo": "z@u.cl"}]})
    mid = c.get(f"/api/v1/asistencia/{cid}/nomina").json()["matriculas"][0]["id"]
    now = datetime.now(timezone.utc)
    # ventana ya cerrada (en el pasado)
    ses = c.post(f"/api/v1/asistencia/{cid}/sesiones", json={
        "titulo": "Vieja", "fecha": "2026-07-17",
        "inicio": (now - timedelta(hours=2)).isoformat(),
        "fin": (now - timedelta(hours=1)).isoformat()}).json()
    qr = c.get(f"/api/v1/asistencia/sesion/{ses['codigo']}/qr").json()
    r = c.post(f"/api/v1/asistencia/sesion/{ses['codigo']}/marcar",
               json={"matricula_id": mid, "token": qr["token"], "bucket": qr["bucket"]})
    assert r.status_code == 409 and "ventana" in r.json()["detail"].lower()
