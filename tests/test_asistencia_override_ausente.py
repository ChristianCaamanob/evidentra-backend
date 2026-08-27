"""Marcar AUSENTE tiene que dejar ausente — en el panel, en el contador y en el informe.

El bug: `estado_sesion` calculaba `presente = bool(mk)`, o sea "existe una marca". Pero el
override del docente por AUSENTE también crea una marca (con estado='ausente'), así que
pulsar ✗ dejaba al estudiante PRESENTE y sumando al contador. El docente creía haber
corregido la lista y en realidad la estaba confirmando.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.course import Course
from app.models.asistencia import AsistenciaMatricula, SesionAsistencia
from app.services import asistencia_service as asis


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _escenario(db):
    ahora = datetime.now(timezone.utc)
    c = Course(name="Obstetricia", code="OBS-OV", grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(c); db.commit(); db.refresh(c)
    ses = SesionAsistencia(course_id=c.id, abierta_por="p-1", titulo="Clase",
                           fecha=ahora.date().isoformat(), inicio=ahora - timedelta(minutes=5),
                           fin=ahora + timedelta(hours=2), estado="abierta",
                           codigo="OVR123", secreto="s3cr3t0")
    db.add(ses)
    alumnos = []
    for i, nom in enumerate(["Ana", "Luis", "Sofía"]):
        m = AsistenciaMatricula(course_id=c.id, nombre=nom, correo=f"{nom.lower()}@u.cl")
        db.add(m); alumnos.append(m)
    db.commit()
    for m in alumnos:
        db.refresh(m)
    return ses, alumnos


def test_marcar_ausente_deja_ausente(db):
    ses, alumnos = _escenario(db)
    ana = alumnos[0]
    asis.override_marca(db, ses.codigo, str(ana.id), "presente")
    est = asis.estado_sesion(db, ses.codigo)
    assert est["presentes"] == 1, "el override por presente debe contar"

    asis.override_marca(db, ses.codigo, str(ana.id), "ausente")
    est = asis.estado_sesion(db, ses.codigo)
    fila = [f for f in est["filas"] if f["matricula_id"] == str(ana.id)][0]
    assert fila["presente"] is False, "marcarla ausente la dejaba presente"
    assert fila["estado"] == "ausente"
    assert est["presentes"] == 0, f"el contador siguió sumándola: {est['presentes']}"
    assert est["ausentes"] == 3


def test_ausente_directo_sin_marca_previa(db):
    """Fijar ausente a quien nunca marcó tampoco debe crearlo como presente."""
    ses, alumnos = _escenario(db)
    asis.override_marca(db, ses.codigo, str(alumnos[1].id), "ausente")
    est = asis.estado_sesion(db, ses.codigo)
    assert est["presentes"] == 0
    fila = [f for f in est["filas"] if f["matricula_id"] == str(alumnos[1].id)][0]
    assert fila["presente"] is False and fila["estado"] == "ausente"


def test_el_informe_exportado_no_lo_llama_presente(db):
    """El informe se arma sobre el mismo campo: el error se propagaba al Excel/PDF/Word."""
    ses, alumnos = _escenario(db)
    asis.override_marca(db, ses.codigo, str(alumnos[0].id), "ausente")
    pay = asis.informe_payload(db, ses.codigo, "xlsx")
    texto = str(pay)
    assert "Ausente" in texto, "el informe debe reflejar la ausencia fijada por el docente"
    # y esa alumna NO puede aparecer como Presente en ninguna fila
    filas = [f for f in asis.estado_sesion(db, ses.codigo)["filas"]
             if f["matricula_id"] == str(alumnos[0].id)]
    assert filas and filas[0]["presente"] is False


def test_revisado_sigue_contando_como_presente(db):
    """'revisado' = marcó pero con una anomalía a revisar; sigue estando en clase."""
    ses, alumnos = _escenario(db)
    asis.override_marca(db, ses.codigo, str(alumnos[2].id), "revisado")
    est = asis.estado_sesion(db, ses.codigo)
    assert est["presentes"] == 1, "una anomalía no es una ausencia"
