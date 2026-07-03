"""
Test de aceptacion del hito C2-import-curriculo (loop de avance de Evalys).

DoD que verifica (de estados.json):
  1. Se carga DMOR0030 y sus RA quedan almacenados LITERALMENTE (sin reformular).
  2. Postura propositiva (G6): la importacion preserva el texto aprobado.
  3. La importacion es idempotente (recargar no duplica).
"""
from __future__ import annotations
import uuid

# Registra todos los modelos para que Base.metadata quede completa.
import app.models.course  # noqa: F401
import app.models.teacher  # noqa: F401
import app.models.student  # noqa: F401
import app.models.assessment  # noqa: F401
import app.models.answer_key  # noqa: F401
import app.models.scan  # noqa: F401
import app.models.result  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.password_reset  # noqa: F401
import app.models.curriculo  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.course import Course
from app.models.curriculo import LearningOutcome
from app.services import curriculo_service


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _curso(s) -> Course:
    c = Course(name="Morfologia", code="DMOR0030")
    s.add(c)
    s.commit()
    s.refresh(c)
    return c


def test_carga_dmor0030():
    """Se cargan los RA de DMOR0030 y quedan vinculados al curso."""
    with _session() as s:
        c = _curso(s)
        ras = curriculo_service.import_dmor0030(s, c.id)
        assert len(ras) == len(curriculo_service.DMOR0030_RA)
        en_db = s.query(LearningOutcome).filter(LearningOutcome.course_id == c.id).count()
        assert en_db == len(curriculo_service.DMOR0030_RA)


def test_preservacion_literal_del_texto():
    """
    El texto del RA se almacena EXACTAMENTE como llega: acentos, mayusculas,
    puntuacion y espacios intactos. Nada de reformular (postura propositiva).
    """
    texto_original = "  Analizar, de forma CRITICA, la (des)composicion morfo-funcional — sin omitir tildes: á é í.  "
    with _session() as s:
        c = _curso(s)
        curriculo_service.import_curriculo(s, c.id, [{"code": "RA1", "text": texto_original}])
        lo = s.query(LearningOutcome).filter(
            LearningOutcome.course_id == c.id, LearningOutcome.code == "RA1"
        ).one()
        assert lo.text == texto_original, "el texto del RA debe preservarse caracter por caracter"


def test_importacion_idempotente():
    """Reimportar el mismo programa actualiza, no duplica."""
    with _session() as s:
        c = _curso(s)
        curriculo_service.import_dmor0030(s, c.id)
        curriculo_service.import_dmor0030(s, c.id)  # segunda vez
        en_db = s.query(LearningOutcome).filter(LearningOutcome.course_id == c.id).count()
        assert en_db == len(curriculo_service.DMOR0030_RA), "no debe duplicar RA al recargar"


def test_orden_preservado():
    """Los RA se devuelven en el orden del programa."""
    with _session() as s:
        c = _curso(s)
        ras = curriculo_service.import_dmor0030(s, c.id)
        ordenes = [r.orden for r in ras]
        assert ordenes == sorted(ordenes)
