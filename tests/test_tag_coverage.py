"""
Test del mecanismo de C3-tag-items (etiquetado item -> RA -> Bloom + cobertura).

C3 es un gate humano: la validacion pedagogica final es del especialista. Esto verifica
la parte AUTOMATIZABLE (la que produce la IA): que el etiquetado se persiste en los
campos de C1 y que el reporte de cobertura se genera bien.
"""
from __future__ import annotations
import uuid
from decimal import Decimal

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
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.services import tag_service


def test_propuesta_cubre_los_30_items():
    tags = tag_service.PROPUESTA_DMOR0030
    assert len(tags) == 30
    items = sorted(t["item"] for t in tags)
    assert items == list(range(1, 31)), "la propuesta debe cubrir los items 1..30"
    # Todos con RA y Bloom
    assert all(t["ra"] and t["bloom"] for t in tags)


def test_coverage_report_estructura_y_conteo():
    tags = tag_service.PROPUESTA_DMOR0030
    md = tag_service.coverage_report(tags, titulo="DMOR0030",
                                     ra_textos={"RA1": "Reconocer la organizacion..."})
    assert "# Etiquetado DMOR0030" in md
    assert "Cobertura por Resultado de Aprendizaje" in md
    assert "Cobertura por nivel Bloom" in md
    assert "30/30" in md  # todos etiquetados
    # Los 4 RA aparecen
    for ra in ("RA1", "RA2", "RA3", "RA4"):
        assert ra in md


def test_reporte_detecta_items_sin_etiquetar():
    tags = [{"item": 1, "ra": "RA1", "bloom": "recordar", "unidad": "U1"},
            {"item": 2, "ra": None, "bloom": None, "unidad": None}]
    md = tag_service.coverage_report(tags)
    assert "1/2" in md
    assert "sin etiquetar" in md.lower()


def test_apply_tags_persiste_en_campos_c1():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        ak = AnswerKey(assessment_id=uuid.uuid4(), status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        for n in (1, 2, 3):
            s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=n, version="A",
                                correct_answer="A", weight=Decimal("1.0"), is_annulled=False))
        s.commit()
        tags = [
            {"item": 1, "ra": "RA1", "bloom": "recordar", "unidad": "Unidad I"},
            {"item": 2, "ra": "RA2", "bloom": "aplicar", "unidad": "Unidad II"},
        ]
        n = tag_service.apply_tags(s, ak.id, tags, version="A")
        assert n == 2
        it1 = s.query(AnswerKeyItem).filter_by(answer_key_id=ak.id, question_number=1).one()
        assert it1.learning_outcome_id == "RA1" and it1.bloom_level == "recordar"
        it3 = s.query(AnswerKeyItem).filter_by(answer_key_id=ak.id, question_number=3).one()
        assert it3.learning_outcome_id is None  # no etiquetado -> sigue nulo (retrocompat)
