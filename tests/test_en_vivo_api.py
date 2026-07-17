"""
Modo EN VIVO: ciclo completo crear -> unir -> avanzar -> responder -> resultados ->
matriz -> cerrar, mas los bordes (pausa, doble respuesta, token invalido, union tardia).
"""
from __future__ import annotations

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
import app.models.validacion  # noqa: F401
import app.models.aprendizaje  # noqa: F401
import app.models.grupo  # noqa: F401
import app.models.en_vivo  # noqa: F401

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_db, usuario_actual
from app.models.base import Base
from app.models.course import Course
from app.models.assessment import Assessment
from app.models.answer_key import (
    AnswerKey, AnswerKeyItem, QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_OPEN_RESPONSE)

_CREADOR = type("U", (), {"rol": "creador"})()


def _sembrar(engine):
    with Session(engine) as s:
        course = Course(name="Morfologia", code="DMOR0030",
                        grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(course); s.commit(); s.refresh(course)
        a = Assessment(course_id=course.id, name="Quiz en vivo",
                       grading_scale="chile_1_7", passing_threshold=60.0)
        s.add(a); s.commit(); s.refresh(a)
        ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
        s.add(ak); s.commit(); s.refresh(ak)
        # 3 MC (version A) + 1 anulado + 1 desarrollo: solo las 3 MC cuentan en vivo.
        for qn, ans in [(1, "B"), (2, "C"), (3, "A")]:
            s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=qn, version="A",
                                correct_answer=ans, weight=1.0,
                                question_type=QUESTION_TYPE_MULTIPLE_CHOICE))
        s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=4, version="A",
                            correct_answer="D", weight=1.0, is_annulled=True,
                            question_type=QUESTION_TYPE_MULTIPLE_CHOICE))
        s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=5, version="A",
                            correct_answer="", weight=1.0,
                            question_type=QUESTION_TYPE_OPEN_RESPONSE))
        s.commit()
        return str(a.id)


@pytest.fixture()
def entorno():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    aid = _sembrar(engine)
    TS = sessionmaker(bind=engine)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[usuario_actual] = lambda: _CREADOR
    yield {"aid": aid, "client": TestClient(app), "engine": engine}
    app.dependency_overrides.clear()


def _unir(c, cod, alias):
    r = c.post(f"/api/v1/en-vivo/{cod}/unir", json={"alias": alias})
    assert r.status_code == 200, r.text
    return r.json()["participante_id"], r.json()["token"]


def test_ciclo_completo_en_vivo(entorno):
    aid, c = entorno["aid"], entorno["client"]

    # crear sala: solo las 3 MC cuentan; arranca en lobby.
    r = c.post(f"/api/v1/assessments/{aid}/en-vivo")
    assert r.status_code == 200, r.text
    ses = r.json()
    cod = ses["codigo"]
    assert ses["n_preguntas"] == 3 and ses["estado"] == "lobby"

    # se unen dos participantes.
    ana_id, ana_tk = _unir(c, cod, "Ana")
    beto_id, beto_tk = _unir(c, cod, "Beto")
    est = c.get(f"/api/v1/en-vivo/{cod}/estado").json()
    assert est["n_participantes"] == 2 and est["estado"] == "lobby"

    # pregunta 1: Ana correcto (B), Beto incorrecto (A).
    assert c.post(f"/api/v1/en-vivo/{cod}/avanzar").json()["pregunta_actual"] == 1
    r1 = c.post(f"/api/v1/en-vivo/{cod}/responder",
                json={"participante_id": ana_id, "token": ana_tk, "respuesta": "b"})
    assert r1.status_code == 200 and r1.json()["correcta"] is True     # case-insensitive
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": beto_id, "token": beto_tk, "respuesta": "A"})

    # no se puede responder dos veces la misma pregunta.
    dup = c.post(f"/api/v1/en-vivo/{cod}/responder",
                 json={"participante_id": ana_id, "token": ana_tk, "respuesta": "C"})
    assert dup.status_code == 409

    # token invalido -> 404.
    bad = c.post(f"/api/v1/en-vivo/{cod}/responder",
                 json={"participante_id": ana_id, "token": "xxx", "respuesta": "B"})
    assert bad.status_code == 404
    assert c.get(f"/api/v1/en-vivo/{cod}/estado").json()["respuestas_pregunta_actual"] == 2

    # pregunta 2 con pausa en medio: no se aceptan respuestas en pausa.
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/pausar")
    pausado = c.post(f"/api/v1/en-vivo/{cod}/responder",
                     json={"participante_id": ana_id, "token": ana_tk, "respuesta": "C"})
    assert pausado.status_code == 409
    c.post(f"/api/v1/en-vivo/{cod}/reanudar")
    for pid, tk in [(ana_id, ana_tk), (beto_id, beto_tk)]:
        c.post(f"/api/v1/en-vivo/{cod}/responder",
               json={"participante_id": pid, "token": tk, "respuesta": "C"})   # ambos correcto

    # pregunta 3: solo Ana responde (A, correcto).
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": ana_id, "token": ana_tk, "respuesta": "A"})

    # avanzar sin mas preguntas -> cierra.
    fin = c.post(f"/api/v1/en-vivo/{cod}/avanzar").json()
    assert fin["estado"] == "cerrada"

    # resultados: Ana 3 aciertos (lidera), Beto 1 (solo q2).
    res = c.get(f"/api/v1/en-vivo/{cod}/resultados").json()
    assert len(res["por_pregunta"]) == 3
    assert res["por_pregunta"][0]["pct_correcta"] == 50.0    # q1: 1 de 2
    assert res["ranking"][0]["participante"] == "Ana" and res["ranking"][0]["aciertos"] == 3
    beto = next(x for x in res["ranking"] if x["participante"] == "Beto")
    assert beto["aciertos"] == 1

    # matriz binaria participante x item para la psicometria.
    mat = c.get(f"/api/v1/en-vivo/{cod}/matriz").json()
    por = dict(zip(mat["participantes"], mat["matriz"]))
    assert por["Ana"] == [1, 1, 1]
    assert por["Beto"] == [0, 1, 0]

    # union tardia (sesion cerrada) -> 409.
    tarde = c.post(f"/api/v1/en-vivo/{cod}/unir", json={"alias": "Caro"})
    assert tarde.status_code == 409


def test_cierre_vuelca_escaneos_para_la_psicometria(entorno):
    """Al cerrar, cada participante que respondió se convierte en un Scan del mismo
    assessment (origen 'en_vivo'), con answers ubicadas por nº de pregunta real, para
    que los motores psicométricos (que leen Scan) vean esta evidencia. Idempotente."""
    from app.models.scan import Scan
    aid, c, engine = entorno["aid"], entorno["client"], entorno["engine"]

    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo").json()["codigo"]
    ana_id, ana_tk = _unir(c, cod, "Ana")
    beto_id, beto_tk = _unir(c, cod, "Beto")
    # q1: Ana B (ok), Beto A (mal)
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": ana_id, "token": ana_tk, "respuesta": "B"})
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": beto_id, "token": beto_tk, "respuesta": "A"})
    # q2: ambos C (ok)
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    for pid, tk in [(ana_id, ana_tk), (beto_id, beto_tk)]:
        c.post(f"/api/v1/en-vivo/{cod}/responder",
               json={"participante_id": pid, "token": tk, "respuesta": "C"})
    # q3: solo Ana A (ok)
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": ana_id, "token": ana_tk, "respuesta": "A"})

    # cierre explícito -> reporta cuántos escaneos incorporó (2).
    fin = c.post(f"/api/v1/en-vivo/{cod}/cerrar").json()
    assert fin["estado"] == "cerrada"
    assert fin["scans_incorporados"] == 2

    import uuid as _uuid
    with Session(engine) as s:
        scans = s.query(Scan).filter(Scan.assessment_id == _uuid.UUID(aid)).all()
        assert len(scans) == 2
        by_alias = {sc.raw_ocr_payload_json["alias"]: sc for sc in scans}
        # answers por nº de pregunta real (1..3); origen trazable; sin requerir revisión.
        assert by_alias["Ana"].raw_ocr_payload_json["answers"] == ["B", "C", "A"]
        assert by_alias["Beto"].raw_ocr_payload_json["answers"] == ["A", "C", None]
        assert all(sc.raw_ocr_payload_json["origen"] == "en_vivo" for sc in scans)
        assert all(sc.requires_review is False for sc in scans)

    # idempotente: cerrar de nuevo no duplica.
    again = c.post(f"/api/v1/en-vivo/{cod}/cerrar").json()
    assert again["scans_incorporados"] == 0
    with Session(engine) as s:
        assert s.query(Scan).filter(Scan.assessment_id == _uuid.UUID(aid)).count() == 2


def test_qr_codifica_url_de_union_con_origin(entorno):
    """El QR debe codificar una URL de unión absoluta (?sala=CODE) cuando llega el
    header Origin, para que escanear con el teléfono abra la pantalla del alumno."""
    aid, c = entorno["aid"], entorno["client"]
    r = c.post(f"/api/v1/assessments/{aid}/en-vivo",
               headers={"origin": "https://evalys.example"})
    j = r.json()
    assert j["join_url"] == "https://evalys.example/app.html?sala=" + j["codigo"]
    assert (j["qr"] or "").startswith("data:image/")  # PNG embebido, no solo el código


def test_no_se_puede_iniciar_sin_pauta_valida(entorno):
    # Evaluacion nueva sin AnswerKey valida -> 409 al crear la sala.
    c = entorno["client"]
    r = c.post(f"/api/v1/assessments/00000000-0000-0000-0000-000000000000/en-vivo")
    assert r.status_code == 409
