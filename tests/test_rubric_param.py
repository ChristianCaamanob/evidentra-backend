"""
Test de la parametrizacion docente de la rubrica (F1, blueprint modulo F):
nivel de exigencia + variables cauteladas + anclas de calibracion + norma terminologica.
"""
from __future__ import annotations
import uuid

import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.student  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.result  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.password_reset  # noqa: F401
import app.models.curriculo  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.course import Course
from app.models.answer_key import (
    AnswerKey, AnswerKeyItem, RubricCriterion, RubricAncla,
    EXIGENCIA_TOLERANTE, EXIGENCIA_ESTRICTO, NIVELES_EXIGENCIA,
    LOGRO_LOGRADO, LOGRO_PARCIAL, LOGRO_NO,
)


def _session():
    e = create_engine("sqlite://"); Base.metadata.create_all(e); return Session(e)


def test_criterio_defaults_parametrizacion():
    """El criterio trae defaults sensatos: configurar es opcional, no engorroso."""
    with _session() as s:
        ak = AnswerKey(assessment_id=uuid.uuid4(), status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        it = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                           correct_answer="", weight=10.0, is_annulled=False,
                           question_type="open_response")
        it.rubric_criteria = [RubricCriterion(name="Función del urotelio", weight=0.3)]
        s.add(it); s.commit(); s.refresh(it)
        c = it.rubric_criteria[0]
        assert c.nivel_exigencia == EXIGENCIA_TOLERANTE   # default
        assert c.penaliza_forma is False
        assert c.umbral_confianza == 0.7
        assert c.politica_creativo == "marcar"


def test_criterio_estricto_con_sinonimos():
    with _session() as s:
        ak = AnswerKey(assessment_id=uuid.uuid4(), status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        it = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                           correct_answer="", weight=10.0, is_annulled=False)
        it.rubric_criteria = [RubricCriterion(
            name="Distensibilidad", weight=1.0, nivel_exigencia=EXIGENCIA_ESTRICTO,
            penaliza_forma=True, sinonimos_json=["distensibilidad", "estiramiento", "acomodación"],
            umbral_confianza=0.85)]
        s.add(it); s.commit(); s.refresh(it)
        c = it.rubric_criteria[0]
        assert c.nivel_exigencia in NIVELES_EXIGENCIA
        assert "estiramiento" in c.sinonimos_json
        assert c.umbral_confianza == 0.85


def test_anclas_de_calibracion():
    """Las anclas (few-shot) se guardan ordenadas y ligadas al criterio."""
    with _session() as s:
        ak = AnswerKey(assessment_id=uuid.uuid4(), status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        it = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A",
                           correct_answer="", weight=10.0, is_annulled=False)
        crit = RubricCriterion(name="Función del urotelio", weight=1.0)
        crit.anclas = [
            RubricAncla(texto="Permite que la vejiga se distienda.", nivel=LOGRO_LOGRADO, order=0),
            RubricAncla(texto="Deja pasar la orina.", nivel=LOGRO_PARCIAL, order=1),
            RubricAncla(texto="Protege de la abrasión.", nivel=LOGRO_NO, order=2),
        ]
        it.rubric_criteria = [crit]
        s.add(it); s.commit(); s.refresh(crit)
        assert len(crit.anclas) == 3
        assert crit.anclas[0].nivel == LOGRO_LOGRADO
        assert [a.order for a in crit.anclas] == [0, 1, 2]


def test_curso_norma_terminologica():
    with _session() as s:
        c = Course(name="Morfología", code="DMOR0030", norma_terminologica="TA2 (IFAA)")
        s.add(c); s.commit(); s.refresh(c)
        assert c.norma_terminologica == "TA2 (IFAA)"
        # aditivo: un curso sin norma sigue siendo válido
        c2 = Course(name="Otro", code="X1")
        s.add(c2); s.commit(); s.refresh(c2)
        assert c2.norma_terminologica is None
