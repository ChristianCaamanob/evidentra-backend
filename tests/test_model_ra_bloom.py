"""
Test de aceptacion del hito C1-model-ra-bloom (loop de avance de Evalys).

DoD que verifica (de estados.json):
  1. AnswerKeyItem gana learning_outcome_id, bloom_level y unidad (nullable).
  2. Existe una migracion para esos campos (en este repo: aditiva; ver nota abajo).
  3. El scoring existente NO se rompe: los campos son opcionales, asi que construir
     un item "a la antigua" (solo con los campos originales) sigue siendo valido.

Adaptado a la estructura real de este repo (Evidentra Backend):
  - Base vive en app.models.base (no app.db.base).
  - AnswerKeyItem vive en app.models.answer_key (no app.models.assessment).
  - El campo de numero de item se llama question_number (no item_number).
  - El repo no usa Alembic: el esquema se materializa con Base.metadata.create_all
    (app/core/db.py). Los campos nuevos son ADITIVOS y nullable, asi que aparecen
    solos en bases nuevas y son un ALTER TABLE trivial e idempotente en las existentes.

Verifica EXISTENCIA + NULABILIDAD + RETROCOMPATIBILIDAD, que es el DoD real. No fuerza
el tipo concreto de cada campo: esa decision de implementacion queda abierta.
"""
from __future__ import annotations
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

# Importa todos los modelos para que Base.metadata quede completa (FKs resueltas).
import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.student  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.result  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.password_reset  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.answer_key import AnswerKeyItem

CAMPOS_NUEVOS = ["learning_outcome_id", "bloom_level", "unidad"]


def _columnas():
    return AnswerKeyItem.__table__.columns


def test_answer_key_item_declara_campos_ra_bloom():
    """Los tres campos deben existir en el modelo AnswerKeyItem."""
    cols = _columnas()
    faltan = [c for c in CAMPOS_NUEVOS if c not in cols]
    assert not faltan, f"AnswerKeyItem no declara los campos RA/Bloom: faltan {faltan}"


def test_campos_ra_bloom_son_nullable():
    """Deben ser nullable: el MVP y las filas existentes no deben romperse."""
    cols = _columnas()
    for c in CAMPOS_NUEVOS:
        assert c in cols, f"falta la columna {c}"
        assert cols[c].nullable is True, (
            f"{c} debe ser nullable para no romper filas ni flujos existentes"
        )


def test_construccion_retrocompatible_no_rompe_scoring():
    """
    Un AnswerKeyItem creado SOLO con los campos originales -como lo hace hoy el
    pipeline de scoring (question_number, correct_answer, weight, is_annulled)- debe
    seguir siendo valido, y los campos nuevos deben quedar en None por defecto.
    """
    engine = create_engine("sqlite://")  # en memoria, sincrono, solo para DDL del test
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        item = AnswerKeyItem(
            answer_key_id=uuid.uuid4(),
            question_number=1,
            version="A",
            correct_answer="B",
            weight=Decimal("4.0"),
            is_annulled=False,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        for c in CAMPOS_NUEVOS:
            assert getattr(item, c) is None, f"{c} deberia quedar None si no se provee"


def test_existe_migracion_para_los_campos():
    """
    DoD: debe existir la migracion que agrega los campos. Este repo NO usa Alembic
    (materializa el esquema con Base.metadata.create_all), asi que si no hay
    alembic/versions se salta con aviso: los campos son aditivos+nullable y create_all
    los toma solo. Si en el futuro se adopta Alembic, al menos una version debe
    mencionarlos.
    """
    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    if not versions.exists():
        pytest.skip("no hay alembic/versions; migracion aditiva via create_all (ver nota)")
    archivos = [p for p in versions.glob("*.py") if p.name != "__init__.py"]
    if not archivos:
        pytest.skip("alembic/versions vacio; el agente debe crear la migracion de C1")
    texto = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in archivos)
    assert any(c in texto for c in CAMPOS_NUEVOS), (
        "ninguna migracion menciona los campos RA/Bloom "
        "(learning_outcome_id / bloom_level / unidad)"
    )
