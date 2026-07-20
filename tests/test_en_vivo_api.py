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
        # Con banco de ítems (enunciado + opciones + justificación) para el modo digital.
        contenido = {
            1: ("¿Porción con más pliegues circulares?",
                [{"letra": "A", "texto": "Colon"}, {"letra": "B", "texto": "Yeyuno"},
                 {"letra": "C", "texto": "Ciego"}, {"letra": "D", "texto": "Íleon"}],
                "El yeyuno tiene pliegues circulares más altos y paredes más gruesas."),
            2: ("¿Arteria del colon ascendente?",
                [{"letra": "A", "texto": "Mesentérica inferior"}, {"letra": "B", "texto": "Renal"},
                 {"letra": "C", "texto": "Mesentérica superior"}, {"letra": "D", "texto": "Esplénica"}],
                "La mesentérica superior irriga el colon derecho."),
            3: ("¿Elemento más anterior del pedículo renal?",
                [{"letra": "A", "texto": "Vena renal"}, {"letra": "B", "texto": "Arteria"},
                 {"letra": "C", "texto": "Uréter"}, {"letra": "D", "texto": "Pelvis"}],
                "La vena renal es la estructura más anterior."),
        }
        for qn, ans in [(1, "B"), (2, "C"), (3, "A")]:
            enun, ops, just = contenido[qn]
            s.add(AnswerKeyItem(answer_key_id=ak.id, question_number=qn, version="A",
                                correct_answer=ans, weight=1.0,
                                question_type=QUESTION_TYPE_MULTIPLE_CHOICE,
                                enunciado=enun, opciones_json=ops, justificacion=just))
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


def test_grid_y_config_en_resultados(entorno):
    """resultados() expone la grilla alumno×pregunta (Live Results) + la config de sesión."""
    aid, c = entorno["aid"], entorno["client"]
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo",
                 json={"retro_alumno": True, "revelar_correccion": True}).json()["codigo"]
    ana_id, ana_tk = _unir(c, cod, "Ana")
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")   # pregunta 1
    c.post(f"/api/v1/en-vivo/{cod}/responder",
           json={"participante_id": ana_id, "token": ana_tk, "respuesta": "B"})
    res = c.get(f"/api/v1/en-vivo/{cod}/resultados").json()
    assert res["modo_ritmo"] == "docente" and res["retro_alumno"] is True
    fila = next(g for g in res["grid"] if g["participante"] == "Ana")
    assert fila["respuestas"]["1"] == {"letra": "B", "correcta": True}
    assert fila["aciertos"] == 1


def test_self_paced_con_shuffle_y_feedback(entorno):
    """Ritmo-alumno + barajado de opciones: mi-estado da enunciado+opciones; responder por
    posición mostrada mapea a la letra canónica y da feedback inmediato + justificación."""
    aid, c = entorno["aid"], entorno["client"]
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo",
                 json={"modo_ritmo": "alumno", "shuffle_opciones": True,
                       "retro_alumno": True, "revelar_correccion": True}).json()["codigo"]
    pid, tk = _unir(c, cod, "Sole")
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")   # abre la sala (self-paced)

    # el alumno ve su pregunta actual con enunciado y 4 opciones (con texto).
    me = c.get(f"/api/v1/en-vivo/{cod}/mi-estado",
               params={"participante_id": pid, "token": tk}).json()
    assert me["modo_ritmo"] == "alumno" and me["pregunta"] is not None
    q = me["pregunta"]
    assert q["enunciado"] and len(q["opciones"]) == 4
    assert q["numero_mostrado"] == 1

    # responde eligiendo la posición cuyo texto es "Yeyuno" (la correcta de la P1).
    pos_yeyuno = next(o["pos"] for o in q["opciones"] if o["texto"] == "Yeyuno")
    r = c.post(f"/api/v1/en-vivo/{cod}/responder",
               json={"participante_id": pid, "token": tk, "opcion_idx": pos_yeyuno}).json()
    assert r["correcta"] is True and r["correcta_letra"] == "B"

    # falla la P2 a propósito → feedback con justificación real.
    me2 = c.get(f"/api/v1/en-vivo/{cod}/mi-estado",
                params={"participante_id": pid, "token": tk}).json()
    q2 = me2["pregunta"]; assert q2["numero_mostrado"] == 2
    pos_mal = next(o["pos"] for o in q2["opciones"] if o["texto"] == "Renal")  # incorrecta
    r2 = c.post(f"/api/v1/en-vivo/{cod}/responder",
                json={"participante_id": pid, "token": tk, "opcion_idx": pos_mal}).json()
    assert r2["correcta"] is False
    assert "mesentérica superior" in r2["justificacion"].lower()


def test_mi_resultado_nota_y_repaso(entorno):
    """Al cerrar, el alumno recibe nota (mismo motor que el escaneo), % logro y detalle
    por pregunta con justificación de las incorrectas. Gated por retro_alumno."""
    aid, c = entorno["aid"], entorno["client"]
    # sin retro: no habilitado
    cod0 = c.post(f"/api/v1/assessments/{aid}/en-vivo", json={"retro_alumno": False}).json()["codigo"]
    p0, t0 = _unir(c, cod0, "X")
    r0 = c.get(f"/api/v1/en-vivo/{cod0}/mi-resultado", params={"participante_id": p0, "token": t0}).json()
    assert r0["habilitado"] is False

    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo", json={"retro_alumno": True}).json()["codigo"]
    pid, tk = _unir(c, cod, "Ana")
    # P1 correcta (B), P2 incorrecta (A; correcta C), P3 sin responder.
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder", json={"participante_id": pid, "token": tk, "respuesta": "B"})
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder", json={"participante_id": pid, "token": tk, "respuesta": "A"})
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")   # P3
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")   # cierra

    r = c.get(f"/api/v1/en-vivo/{cod}/mi-resultado", params={"participante_id": pid, "token": tk}).json()
    assert r["habilitado"] is True
    assert r["correctas"] == 1 and r["incorrectas"] == 2
    assert r["pct_logro"] == 33.3
    assert isinstance(r["nota"], (int, float)) and r["aprobado"] is False
    # la P2 (incorrecta) trae justificación; la P1 (correcta) no.
    d2 = next(d for d in r["detalle"] if d["numero"] == 2)
    assert d2["ok"] is False and "mesentérica superior" in d2["justificacion"].lower()
    d1 = next(d for d in r["detalle"] if d["numero"] == 1)
    assert d1["ok"] is True and "justificacion" not in d1


def test_banco_items_guardar_y_leer(entorno):
    """El docente edita el contenido de un ítem (enunciado/opciones/justificación) sin tocar
    la letra correcta; se lee de vuelta para editarlo."""
    aid, c = entorno["aid"], entorno["client"]
    # leer contenido actual (el seed ya trae contenido)
    g = c.get(f"/api/v1/en-vivo/banco/{aid}", params={"version": "A"}).json()
    assert g["n_preguntas"] == 3
    assert any(it["enunciado"] for it in g["items"])

    # actualizar el enunciado y la justificación de la P1 (no cambia 'correcta')
    save = c.post(f"/api/v1/en-vivo/banco/{aid}", json={"version": "A", "items": [
        {"question_number": 1, "enunciado": "Enunciado editado P1",
         "opciones": [{"letra": "A", "texto": "uno"}, {"letra": "B", "texto": "dos"},
                      {"letra": "C", "texto": "tres"}, {"letra": "D", "texto": "cuatro"}],
         "justificacion": "Nueva justificación"}]})
    assert save.status_code == 200 and save.json()["actualizados"] == 1

    g2 = c.get(f"/api/v1/en-vivo/banco/{aid}", params={"version": "A"}).json()
    p1 = next(it for it in g2["items"] if it["question_number"] == 1)
    assert p1["enunciado"] == "Enunciado editado P1"
    assert p1["correcta"] == "B"   # intacta
    assert p1["justificacion"] == "Nueva justificación"


def test_drilldown_por_pregunta_en_resultados(entorno):
    """resultados().por_pregunta trae el detalle para el drill-down: opciones con texto+%,
    correcta, justificación y RA."""
    aid, c = entorno["aid"], entorno["client"]
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo", json={}).json()["codigo"]
    pid, tk = _unir(c, cod, "Ana")
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    c.post(f"/api/v1/en-vivo/{cod}/responder", json={"participante_id": pid, "token": tk, "respuesta": "B"})
    pp = c.get(f"/api/v1/en-vivo/{cod}/resultados").json()["por_pregunta"][0]
    assert pp["enunciado"] and pp["justificacion"]
    assert pp["pct_correcta"] == 100.0 and pp["pct_incorrecta"] == 0.0
    opB = next(o for o in pp["opciones"] if o["letra"] == "B")
    assert opB["texto"] == "Yeyuno" and opB["correcta"] is True and opB["pct"] == 100.0


def test_informe_psicometrico_y_por_ra(entorno):
    """El informe integra psicometría (dificultad, discriminación, KR-20), resultados por RA
    y estudiantes con nota; y se exporta a Word/PDF/Excel."""
    aid, c = entorno["aid"], entorno["client"]
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo", json={}).json()["codigo"]
    # dos participantes con patrones distintos para que haya variación
    a_id, a_tk = _unir(c, cod, "Ana")
    b_id, b_tk = _unir(c, cod, "Beto")
    for qn, (aA, aB) in zip([1, 2, 3], [("B", "A"), ("C", "C"), ("A", "D")]):
        c.post(f"/api/v1/en-vivo/{cod}/avanzar")
        c.post(f"/api/v1/en-vivo/{cod}/responder", json={"participante_id": a_id, "token": a_tk, "respuesta": aA})
        c.post(f"/api/v1/en-vivo/{cod}/responder", json={"participante_id": b_id, "token": b_tk, "respuesta": aB})
    inf = c.get(f"/api/v1/en-vivo/{cod}/informe").json()
    assert inf["n_participantes"] == 2 and inf["n_items"] == 3
    assert len(inf["items"]) == 3 and "dificultad_p" in inf["items"][0]
    assert inf["por_ra"] and "logro_pct" in inf["por_ra"][0]
    assert len(inf["estudiantes"]) == 2 and "nota" in inf["estudiantes"][0]
    # Ana acertó 3/3 → aprobada; Beto 1/3 (solo P2=C)
    ana = next(e for e in inf["estudiantes"] if e["alias"] == "Ana")
    assert ana["aciertos"] == 3 and ana["aprobado"] is True
    # exportación XLSX (openpyxl es dependencia dura) por el endpoint real
    r = c.post(f"/api/v1/en-vivo/{cod}/informe/xlsx")
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"   # zip (xlsx)
    # el payload docx/pdf se arma bien (el render depende de python-docx/reportlab, en prod)
    from app.services import en_vivo_service as ev
    with Session(entorno["engine"]) as db:
        pl = ev.informe_payload(db, cod, "docx")
    assert pl["titulo"] and pl["secciones"] and pl["tablas"]
    # Hay tabla por RA (el perfil docente la titula "Logro por…"; el investigador "Resultados por…").
    assert any("Resultado de Aprendizaje" in t["titulo"] for t in pl["tablas"])


def test_no_se_puede_iniciar_sin_pauta_valida(entorno):
    # Evaluacion nueva sin AnswerKey valida -> 409 al crear la sala.
    c = entorno["client"]
    r = c.post(f"/api/v1/assessments/00000000-0000-0000-0000-000000000000/en-vivo")
    assert r.status_code == 409


def test_candado_dispositivo_evita_doble_registro(entorno):
    """LV10 · Reproduce el caso del CEO: rindo, obtengo puntaje, reescaneo el MISMO QR e
    intento rendir por un compañero desde el MISMO dispositivo → NO se crea un 2º registro."""
    aid, c = entorno["aid"], entorno["client"]
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo").json()["codigo"]

    DEV_A = "device-telefono-de-ana"

    # 1) Ana entra desde su teléfono (device A) y responde las 3 preguntas (self-paced no hace
    #    falta: usamos ritmo docente avanzando; basta con dejar su participante creado).
    r = c.post(f"/api/v1/en-vivo/{cod}/unir", json={"alias": "Ana", "device_id": DEV_A})
    assert r.status_code == 200, r.text
    ana = r.json()
    ana_id = ana["participante_id"]
    assert ana.get("reanudado") in (False, None)

    # 2) Ana "termina y obtiene su puntaje" → 3) REESCANEA el mismo QR y ELIGE a un compañero
    #    (Beto) desde el MISMO dispositivo. El candado debe DEVOLVER a Ana, no crear a Beto.
    r2 = c.post(f"/api/v1/en-vivo/{cod}/unir", json={"alias": "Beto", "device_id": DEV_A})
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["participante_id"] == ana_id, "El mismo equipo creó un 2º participante (FALLA)"
    assert j2["alias"] == "Ana", "Debe reconectar como Ana, no como Beto"
    assert j2["reanudado"] is True

    # 4) El backend registró la EVIDENCIA trazable del intento de suplantación.
    integ = c.get(f"/api/v1/en-vivo/{cod}/integridad").json()
    fila_ana = [f for f in integ["participantes"] if f["participante_id"] == ana_id][0]
    assert fila_ana["reingresos_bloqueados"] >= 1, "No quedó la evidencia de reingreso"
    assert fila_ana["nivel"] == "revisar"

    # 5) Solo existe UN participante en la sala (no dos).
    est = c.get(f"/api/v1/en-vivo/{cod}/estado").json()
    assert est["n_participantes"] == 1, f"Hay {est['n_participantes']} participantes (debía ser 1)"

    # 6) Control: OTRO dispositivo (el teléfono real de Beto) SÍ puede unirse como Beto.
    r3 = c.post(f"/api/v1/en-vivo/{cod}/unir", json={"alias": "Beto", "device_id": "device-de-beto"})
    assert r3.status_code == 200 and r3.json()["participante_id"] != ana_id
    est2 = c.get(f"/api/v1/en-vivo/{cod}/estado").json()
    assert est2["n_participantes"] == 2


def test_temporizador_autocierre_y_extension(entorno):
    """LV11 · Duración configurable: el alumno ve su cuenta regresiva, al llegar a 0 no puede
    responder (auto-cierre), y el docente puede REABRIR+EXTENDER selectivamente a ese alumno."""
    import time as _t
    from sqlalchemy.orm import Session as _S
    from app.models.en_vivo import SesionEnVivo
    aid, c, engine = entorno["aid"], entorno["client"], entorno["engine"]

    # sala con 10 min de límite
    cod = c.post(f"/api/v1/assessments/{aid}/en-vivo", json={"duracion_min": 10}).json()["codigo"]
    pid, tk = _unir(c, cod, "Ana")
    # aún no arranca el timer (lobby) → sin cuenta
    st0 = c.get(f"/api/v1/en-vivo/{cod}/mi-estado", params={"participante_id": pid, "token": tk}).json()
    assert st0["duracion_min"] == 10 and st0["segundos_restantes"] is None

    # el docente abre la sala → arranca la cuenta regresiva
    c.post(f"/api/v1/en-vivo/{cod}/avanzar")
    st1 = c.get(f"/api/v1/en-vivo/{cod}/mi-estado", params={"participante_id": pid, "token": tk}).json()
    assert 500 < st1["segundos_restantes"] <= 600 and st1["tiempo_agotado"] is False

    # simulamos que pasaron 11 min: retrocedemos el inicio del timer
    with _S(engine) as db:
        s = db.query(SesionEnVivo).filter(SesionEnVivo.codigo == cod).first()
        s.timer_inicio_ts = int(_t.time()) - 11 * 60
        db.commit()

    # el alumno ya no puede responder: tiempo agotado → auto-cierre
    st2 = c.get(f"/api/v1/en-vivo/{cod}/mi-estado", params={"participante_id": pid, "token": tk}).json()
    assert st2["tiempo_agotado"] is True and st2["segundos_restantes"] == 0
    r = c.post(f"/api/v1/en-vivo/{cod}/responder",
               json={"participante_id": pid, "token": tk, "respuesta": "B"})
    assert r.status_code == 409 and "tiempo" in r.json()["detail"].lower()

    # el docente REABRE + EXTIENDE 5 min SOLO a Ana → vuelve a tener ~5 min y puede responder
    rext = c.post(f"/api/v1/en-vivo/{cod}/participante/{pid}/tiempo", json={"extra_min": 5})
    assert rext.status_code == 200, rext.text
    assert 240 < rext.json()["segundos_restantes"] <= 300
    r2 = c.post(f"/api/v1/en-vivo/{cod}/responder",
                json={"participante_id": pid, "token": tk, "respuesta": "B"})
    assert r2.status_code == 200 and r2.json()["correcta"] is True

    # y quedó la evidencia trazable de la extensión
    tl = c.get(f"/api/v1/en-vivo/{cod}/integridad/{pid}").json()
    assert any(e["tipo"] == "tiempo_extendido" for e in tl["eventos"])
