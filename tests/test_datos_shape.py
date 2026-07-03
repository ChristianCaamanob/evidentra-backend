"""
Test de aceptacion del hito E1-datos-endpoint (loop de avance de Evalys).

DoD que verifica (de estados.json):
  1. El ensamblado devuelve el contrato `datos` COMPLETO (11 claves).
  2. El ensamblado es determinista y NO usa IA (metadata.ia_utilizada = False),
     por lo que respeta G2 sin necesidad de seudonimizar todavia.
  3. El vinculo curricular (RA/Bloom/unidad) aparece en el mapa de preguntas y en
     las agregaciones (dimensiones_bloom).
"""
from __future__ import annotations
import uuid
from decimal import Decimal

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

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.course import Course
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.models.scan import Scan
from app.models.curriculo import LearningOutcome
from app.services import curriculo_service, informe_service

CONTRATO = [
    "estudiante", "evaluacion", "desempeno", "distribucion_curso",
    "dimensiones_bloom", "mapa_preguntas", "brechas", "fortalezas",
    "plan_consolidacion", "mensaje_personalizado", "metadata",
]

# Pauta de 5 items (version A). Q4 anulada.
PAUTA = [
    # (n, correcta, peso, anulada, ra, bloom, unidad)
    (1, "A", 4.0, False, "RA1", "recordar", "Unidad I"),
    (2, "B", 4.0, False, "RA2", "comprender", "Unidad II"),
    (3, "C", 4.0, False, "RA2", "aplicar", "Unidad II"),
    (4, "D", 4.0, True, "RA3", "analizar", "Unidad III"),
    (5, "A", 4.0, False, "RA3", "analizar", "Unidad III"),
]
# Respuestas del alumno: Q1 ok, Q2 mal, Q3 ok, Q4 anulada, Q5 ok.
RESPUESTAS = ["A", "X", "C", "D", "A"]


@pytest.fixture()
def datos():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030", grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        curriculo_service.import_dmor0030(s, course.id)

        assessment = Assessment(course_id=course.id, name="Solemne 1", grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(assessment); s.commit(); s.refresh(assessment)

        ak = AnswerKey(assessment_id=assessment.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        for (n, correcta, peso, anulada, ra, bloom, unidad) in PAUTA:
            s.add(AnswerKeyItem(
                answer_key_id=ak.id, question_number=n, version="A",
                correct_answer=correcta, weight=Decimal(str(peso)), is_annulled=anulada,
                learning_outcome_id=ra, bloom_level=bloom, unidad=unidad,
            ))
        s.commit()

        scan = Scan(
            assessment_id=assessment.id, student_identifier="11.111.111-1",
            status="scored", detected_version="A", requires_review=False,
            raw_ocr_payload_json={"answers": RESPUESTAS},
        )
        s.add(scan); s.commit(); s.refresh(scan)

        yield informe_service.build_datos(s, scan.id)


def test_datos_tiene_todas_las_claves(datos):
    faltan = [k for k in CONTRATO if k not in datos]
    assert not faltan, f"faltan claves en `datos`: {faltan}"


def test_metadata_sin_ia_y_seudonimizado(datos):
    md = datos["metadata"]
    assert md["ia_utilizada"] is False, "E1 es determinista: no debe declarar uso de IA"
    assert md["seudonimizado"] is True


def test_desempeno_coherente(datos):
    d = datos["desempeno"]
    # 3 correctas (Q1,Q3,Q5) de 4 efectivas (Q4 anulada) -> 75%
    assert d["correctas"] == 3
    assert d["anuladas"] == 1
    assert d["porcentaje"] == 75.0


def test_mapa_preguntas_trae_vinculo_curricular(datos):
    mp = {r["numero"]: r for r in datos["mapa_preguntas"]}
    assert mp[1]["estado"] == "correcta" and mp[1]["bloom"] == "recordar"
    assert mp[2]["estado"] == "incorrecta" and mp[2]["tu_respuesta"] == "X"
    assert mp[4]["estado"] == "anulada"
    # El texto literal del RA (C2) viaja en el mapa.
    assert mp[1]["ra"] == "RA1" and mp[1]["ra_texto"]


def test_dimensiones_bloom_agregadas(datos):
    niveles = {g["clave"] for g in datos["dimensiones_bloom"]}
    assert {"recordar", "comprender", "aplicar", "analizar"} <= niveles


def test_distribucion_curso_presente(datos):
    dc = datos["distribucion_curso"]
    assert dc["n_estudiantes"] >= 1
    assert dc["tu_porcentaje"] == 75.0
    assert dc["tu_percentil"] is not None
