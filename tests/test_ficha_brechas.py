"""P3 · brechas por RA del estudiante a través del curso (ficha_service)."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models.course import Course
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.models.scan import Scan
from app.models.student import Student
from app.models.curriculo import LearningOutcome
from app.services import ficha_service


def _sembrar(engine):
    with Session(engine) as s:
        c = Course(name="Anatomía", code="DANA0010",
                   grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(c); s.commit(); s.refresh(c)
        s.add(LearningOutcome(course_id=c.id, code="RA1", text="Reconoce estructuras", orden=1))
        s.add(LearningOutcome(course_id=c.id, code="RA2", text="Integra funciones", orden=2))
        s.add(Student(course_id=c.id, rut="1-9", nombres="Ana", apellido_paterno="Soto"))
        s.commit()

        def _asm(nombre, tipo):
            a = Assessment(course_id=c.id, name=nombre, tipo=tipo,
                           grading_scale="chile_1_7", passing_threshold=60.0)
            s.add(a); s.commit(); s.refresh(a)
            ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
            s.add(ak); s.commit(); s.refresh(ak)
            return a, ak

        # Solemne (OMR): q1,q2 -> RA1 ; q3,q4 -> RA2 ; correcta "A".
        a1, ak1 = _asm("Solemne 1", "solemne")
        for q in (1, 2, 3, 4):
            s.add(AnswerKeyItem(answer_key_id=ak1.id, question_number=q, version="A",
                                correct_answer="A", weight=1.0,
                                learning_outcome_id=("RA1" if q <= 2 else "RA2")))
        # Ana: [A,A,B,B] -> RA1 2/2 ; RA2 0/2
        s.add(Scan(assessment_id=a1.id, student_identifier="1-9", status="scored",
                   detected_version="A", requires_review=False, origen=None,
                   raw_ocr_payload_json={"answers": ["A", "A", "B", "B"]}))

        # Control en vivo: q1 -> RA1 ; q2 -> RA2 ; correcta "A".
        a2, ak2 = _asm("Control en vivo", "control")
        s.add(AnswerKeyItem(answer_key_id=ak2.id, question_number=1, version="A",
                            correct_answer="A", weight=1.0, learning_outcome_id="RA1"))
        s.add(AnswerKeyItem(answer_key_id=ak2.id, question_number=2, version="A",
                            correct_answer="A", weight=1.0, learning_outcome_id="RA2"))
        # Ana: [B,A] -> RA1 0/1 ; RA2 1/1
        s.add(Scan(assessment_id=a2.id, student_identifier="1-9", status="en_vivo",
                   detected_version="A", requires_review=False, origen="en_vivo",
                   raw_ocr_payload_json={"answers": ["B", "A"]}))
        s.commit()
        return str(c.id)


@pytest.fixture()
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    return e


def _por_ra(res):
    return {r["code"]: r for r in res["por_ra"]}


def test_brechas_agrega_por_ra_a_traves_del_curso(engine):
    cid = uuid.UUID(_sembrar(engine))
    with Session(engine) as s:
        res = ficha_service.brechas_estudiante(s, cid, "1-9")
    ra = _por_ra(res)
    # RA1 = (2 de solemne + 0 de control) / 3 = 66.7% -> En desarrollo, NO brecha
    assert ra["RA1"]["items_evaluados"] == 3 and ra["RA1"]["logro_pct"] == 66.7
    assert ra["RA1"]["brecha"] is False and ra["RA1"]["nivel"] == "En desarrollo"
    # RA2 = (0 de solemne + 1 de control) / 3 = 33.3% -> brecha
    assert ra["RA2"]["items_evaluados"] == 3 and ra["RA2"]["logro_pct"] == 33.3
    assert ra["RA2"]["brecha"] is True
    # desglose por tipo de prueba
    assert ra["RA1"]["por_tipo"] == {"solemne": 100.0, "control": 0.0}
    assert ra["RA2"]["por_tipo"] == {"solemne": 0.0, "control": 100.0}
    # resumen
    assert res["resumen"]["n_ra_programa"] == 2 and res["resumen"]["n_ra_evaluados"] == 2
    assert res["resumen"]["n_brechas"] == 1 and res["resumen"]["n_pruebas"] == 2
    assert res["estudiante"]["nombre"] == "Soto, Ana"


def test_brechas_filtra_por_origen(engine):
    cid = uuid.UUID(_sembrar(engine))
    with Session(engine) as s:
        omr = _por_ra(ficha_service.brechas_estudiante(s, cid, "1-9", origen="omr"))
        vivo = _por_ra(ficha_service.brechas_estudiante(s, cid, "1-9", origen="en_vivo"))
    # Solo OMR (solemne): RA1 100% (2/2), RA2 0% (0/2, brecha)
    assert omr["RA1"]["logro_pct"] == 100.0 and omr["RA2"]["logro_pct"] == 0.0
    assert omr["RA2"]["brecha"] is True
    # Solo en vivo (control): RA1 0% (0/1, brecha), RA2 100% (1/1)
    assert vivo["RA1"]["logro_pct"] == 0.0 and vivo["RA1"]["brecha"] is True
    assert vivo["RA2"]["logro_pct"] == 100.0


def test_informe_personalizado_plantilla(engine, monkeypatch):
    """Sin clave IA, el informe cae a plantilla determinista: constata brechas reales y propone
    escenarios de aprendizaje, anclado a los datos (línea roja: no inventa RA)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cid = uuid.UUID(_sembrar(engine))
    with Session(engine) as s:
        res = ficha_service.informe_personalizado(s, cid, "1-9")
    assert res["motor"] == "plantilla determinista" and res["borrador"] is True
    txt = res["informe"]
    assert "Escenarios estratégicos de aprendizaje" in txt
    assert "RA2" in txt and "Integra funciones" in txt        # la brecha real, con su texto literal
    assert "RA9" not in txt                                    # no inventa RA inexistentes
    assert res["datos"]["resumen"]["n_brechas"] == 1          # anclaje: los hechos van adjuntos


def test_ra_derivados_sin_tabla_formal(engine):
    """Sin Tabla de Especificaciones cargada, los RA se derivan del etiquetado de los ítems
    (así la ficha funciona con la evidencia existente en producción)."""
    cid = _sembrar(engine)
    with Session(engine) as s:
        # borrar la Tabla formal, dejando solo el etiquetado C1 de los ítems
        from app.models.curriculo import LearningOutcome
        s.query(LearningOutcome).delete()
        s.commit()
        res = ficha_service.brechas_estudiante(s, uuid.UUID(cid), "1-9")
    ra = _por_ra(res)
    assert res["tabla_cargada"] is False
    assert set(ra.keys()) == {"RA1", "RA2"}                    # derivados de los ítems
    assert ra["RA1"]["en_tabla"] is False and ra["RA2"]["en_tabla"] is False
    assert ra["RA2"]["logro_pct"] == 33.3 and ra["RA2"]["brecha"] is True
    assert res["resumen"]["n_ra_programa"] == 0                # no hay tabla formal
    assert set(res["ra_fuera_de_tabla"]) == {"RA1", "RA2"}


def test_ra_sin_evaluar_se_reporta(engine):
    """Un RA del programa sin ítems asociados aparece como 'sin evaluar' (cobertura honesta)."""
    cid = _sembrar(engine)
    with Session(engine) as s:
        s.add(LearningOutcome(course_id=uuid.UUID(cid), code="RA3", text="No evaluado aún", orden=3))
        s.commit()
        res = ficha_service.brechas_estudiante(s, uuid.UUID(cid), "1-9")
    ra = _por_ra(res)
    assert ra["RA3"]["items_evaluados"] == 0 and ra["RA3"]["logro_pct"] is None
    assert ra["RA3"]["nivel"] == "sin evaluar" and ra["RA3"]["brecha"] is None
    assert "RA3" in res["resumen"]["ra_sin_evaluar"]
