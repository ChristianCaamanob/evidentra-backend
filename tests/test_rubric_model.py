"""
Test de aceptacion del hito F1-rubric-model (loop de avance de Evalys).

DoD que verifica (de estados.json):
  1. question.type (multiple_choice | open_response) en el modelo de pregunta
     (aqui: AnswerKeyItem.question_type).
  2. Tabla rubric_criterion (aqui: rubric_criteria) con nombre, descriptor y peso.
  3. Aditivo: el MVP de multiple_choice sigue funcionando; el esquema materializa
     (create_all) sin romper nada.
"""
from __future__ import annotations
import uuid
from decimal import Decimal

# Registra todos los modelos para que Base.metadata quede completa.
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
from app.models.answer_key import (
    AnswerKey,
    AnswerKeyItem,
    RubricCriterion,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_OPEN_RESPONSE,
    QUESTION_TYPES,
)


def test_answer_key_item_tiene_question_type():
    cols = AnswerKeyItem.__table__.columns
    assert "question_type" in cols, "AnswerKeyItem debe declarar question_type"
    assert set(QUESTION_TYPES) == {QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_OPEN_RESPONSE}


def test_rubric_criterion_tiene_campos_minimos():
    cols = RubricCriterion.__table__.columns
    for c in ("answer_key_item_id", "name", "descriptor", "weight"):
        assert c in cols, f"RubricCriterion debe declarar {c}"


def test_multiple_choice_sigue_funcionando_por_defecto():
    """Un item creado a la antigua queda como multiple_choice, sin criterios."""
    engine = create_engine("sqlite://")
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
        assert item.question_type == QUESTION_TYPE_MULTIPLE_CHOICE
        assert list(item.rubric_criteria) == []


def test_open_response_con_criterios_de_rubrica():
    """Una pregunta de desarrollo puede llevar criterios de rubrica con peso."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        item = AnswerKeyItem(
            answer_key_id=uuid.uuid4(),
            question_number=2,
            version="A",
            correct_answer="",  # sin clave unica: la correccion es por rubrica
            weight=Decimal("10.0"),
            is_annulled=False,
            question_type=QUESTION_TYPE_OPEN_RESPONSE,
        )
        item.rubric_criteria = [
            RubricCriterion(name="Identifica la estructura", descriptor="Reconoce el hueso/region", weight=0.4, order=0),
            RubricCriterion(name="Justifica la funcion", descriptor="Explica el porque", weight=0.6, order=1),
        ]
        s.add(item)
        s.commit()
        s.refresh(item)
        assert item.question_type == QUESTION_TYPE_OPEN_RESPONSE
        assert len(item.rubric_criteria) == 2
        assert round(sum(c.weight for c in item.rubric_criteria), 2) == 1.0
        assert item.rubric_criteria[0].name == "Identifica la estructura"
