"""
El Reto de Runi: Runi deja de esperar y propone.

Diagnóstico del CEO sobre su propio producto: Runi es pasivo. Si la estudiante no entra, no pasa
nada. Estos tests protegen las cuatro reglas que hacen que «algo nuevo cada vez» sea sostenible y no
un truco de enganche:

1. **Ninguna pregunta llega sin que el docente la apruebe.** Una pregunta mal generada de anatomía
   aplicada no es un bug cosmético: enseña algo falso.
2. **Una pregunta no se repite a quien ya la respondió.** Es lo que hace que siempre haya algo nuevo.
3. **2 o 3 por sesión**, nunca una rueda infinita.
4. **No todas reciben lo mismo en el mismo orden**, aunque el banco sea uno solo.
"""
from __future__ import annotations

import importlib
import pkgutil

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.reto import RetoPregunta
from app.services import reto_service as rt

CID = "3f2a1c44-8d21-4e6b-9a70-5c1e2d3f4a5b"
ANA, LUZ = "stu:ana", "stu:luz"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar(db, n=10, estado="aprobada", tema="Pelvis ósea", peso=1):
    filas = []
    for i in range(n):
        filas.append(RetoPregunta(
            course_id=CID, tema=tema, peso=peso, enunciado=f"Pregunta {i} sobre {tema}",
            alternativas={"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"},
            correcta="B", justificacion="Porque sí.", nivel="recordar", estado=estado))
    db.add_all(filas); db.commit()
    return filas


# ── lo que se aprueba y lo que no ────────────────────────────────────────────────────
def test_una_propuesta_sin_aprobar_no_le_llega_a_nadie(db):
    _sembrar(db, 5, estado="propuesta")
    assert rt.sesion(db, CID, ANA)["preguntas"] == []


def test_una_descartada_tampoco(db):
    _sembrar(db, 5, estado="descartada")
    assert rt.sesion(db, CID, ANA)["preguntas"] == []


def test_aprobar_exige_que_la_correcta_exista(db):
    p = _sembrar(db, 1, estado="propuesta")[0]
    p.correcta = "Z"; db.commit()
    with pytest.raises(Exception):
        rt.revisar(db, p.id, "aprobar")


def test_editar_y_aprobar_en_un_solo_paso(db):
    p = _sembrar(db, 1, estado="propuesta")[0]
    r = rt.revisar(db, p.id, "aprobar", {"enunciado": "Corregida", "correcta": "C"})
    assert r["pregunta"]["estado"] == "aprobada"
    assert r["pregunta"]["enunciado"] == "Corregida" and r["pregunta"]["correcta"] == "C"


def test_la_pregunta_escrita_por_el_docente_nace_aprobada(db):
    r = rt.crear_manual(db, CID, {"tema": "Periné", "enunciado": "¿Cuál?",
                                  "alternativas": {"A": "esta", "B": "otra"}, "correcta": "A"})
    assert r["pregunta"]["estado"] == "aprobada" and r["pregunta"]["origen"] == "docente"
    assert len(rt.sesion(db, CID, ANA)["preguntas"]) == 1


def test_una_pregunta_manual_incompleta_se_rechaza(db):
    for mala in ({"enunciado": "sin alternativas"},
                 {"enunciado": "x", "alternativas": {"A": "sola"}, "correcta": "A"},
                 {"enunciado": "x", "alternativas": {"A": "u", "B": "d"}, "correcta": "Z"}):
        with pytest.raises(Exception):
            rt.crear_manual(db, CID, mala)


# ── la sesión ────────────────────────────────────────────────────────────────────────
def test_nunca_mas_de_tres_por_sesion(db):
    _sembrar(db, 40)
    assert len(rt.sesion(db, CID, ANA)["preguntas"]) == rt.POR_SESION
    assert len(rt.sesion(db, CID, ANA, n=99)["preguntas"]) == rt.POR_SESION


def test_lo_ya_respondido_no_vuelve_a_salir(db):
    _sembrar(db, 6)
    vistas = set()
    for _ in range(2):
        s = rt.sesion(db, CID, ANA)
        for q in s["preguntas"]:
            assert q["id"] not in vistas, "le salió de nuevo una que ya había respondido"
            vistas.add(q["id"])
            rt.responder(db, q["id"], ANA, "B")
    assert len(vistas) == 6


def test_la_sesion_no_revela_la_respuesta(db):
    _sembrar(db, 3)
    for q in rt.sesion(db, CID, ANA)["preguntas"]:
        assert "correcta" not in q and "justificacion" not in q


def test_quedarse_sin_preguntas_no_es_un_error(db):
    _sembrar(db, 2)
    for q in rt.sesion(db, CID, ANA)["preguntas"]:
        rt.responder(db, q["id"], ANA, "B")
    s = rt.sesion(db, CID, ANA)
    assert s["ok"] and s["sin_pendientes"] and s["preguntas"] == []


def test_dos_estudiantes_no_reciben_la_misma_lista_en_el_mismo_orden(db):
    _sembrar(db, 30)
    a = [q["id"] for q in rt.sesion(db, CID, ANA)["preguntas"]]
    l = [q["id"] for q in rt.sesion(db, CID, LUZ)["preguntas"]]
    assert a != l


def test_lo_que_mas_pesa_en_la_tabla_sale_primero(db):
    _sembrar(db, 5, tema="Tema liviano", peso=1)
    _sembrar(db, 5, tema="Pelvis ósea", peso=40)
    temas = {q["tema"] for q in rt.sesion(db, CID, ANA)["preguntas"]}
    assert temas == {"Pelvis ósea"}


def test_sus_vacios_van_antes_que_el_peso(db):
    """Lo que ya mostró que no domina manda sobre lo que pesa en la tabla."""
    import uuid as _u
    from app.models.episode import ConfidenceObs, Episode
    _sembrar(db, 5, tema="Tema pesado", peso=40)
    _sembrar(db, 5, tema="Periné", peso=1)
    e = Episode(id=_u.uuid4(), pseudo_id=ANA, ra="Periné"); db.add(e); db.flush()
    db.add(ConfidenceObs(episode_id=e.id, pseudo_id=ANA, ra="Periné", item_id="x",
                         correct=False, confidence=90))
    db.commit()
    assert {q["tema"] for q in rt.sesion(db, CID, ANA)["preguntas"]} == {"Periné"}


def test_sin_identidad_no_hay_sesion(db):
    _sembrar(db, 3)
    with pytest.raises(Exception):
        rt.sesion(db, CID, "")


# ── responder ────────────────────────────────────────────────────────────────────────
def test_al_responder_se_revela_la_justificacion(db):
    p = _sembrar(db, 1)[0]
    r = rt.responder(db, p.id, ANA, "B")
    assert r["acerto"] and r["correcta"] == "B" and r["justificacion"] == "Porque sí."


def test_fallar_tambien_explica(db):
    p = _sembrar(db, 1)[0]
    r = rt.responder(db, p.id, ANA, "A")
    assert not r["acerto"] and r["correcta"] == "B" and r["justificacion"]


def test_responder_dos_veces_no_cambia_el_resultado(db):
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "A")
    r = rt.responder(db, p.id, ANA, "B")
    assert r["ya_respondida"] and r["elegida"] == "A" and not r["acerto"]


def test_una_alternativa_inventada_se_rechaza(db):
    p = _sembrar(db, 1)[0]
    with pytest.raises(Exception):
        rt.responder(db, p.id, ANA, "Z")


def test_no_se_puede_responder_una_sin_aprobar(db):
    p = _sembrar(db, 1, estado="propuesta")[0]
    with pytest.raises(Exception):
        rt.responder(db, p.id, ANA, "B")


def test_el_reto_alimenta_la_evidencia_no_es_un_juego_aparte(db):
    """Responder deja un episodio verificado: cuenta para la Cumbre igual que un repaso."""
    from app.models.episode import Episode
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "B", course_id=CID)
    eps = db.query(Episode).filter(Episode.pseudo_id == ANA).all()
    assert len(eps) == 1 and eps[0].origen == "reto" and eps[0].verificado


# ── el estado que ve en Inicio ───────────────────────────────────────────────────────
def test_mi_estado_cuenta_solo_lo_aprobado(db):
    _sembrar(db, 4)
    _sembrar(db, 6, estado="propuesta")
    e = rt.mi_estado(db, CID, ANA)
    assert e["banco"] == 4 and e["respondidos"] == 0 and e["hay_nuevos"]


def test_cuando_respondio_todo_deja_de_haber_nuevos(db):
    ps = _sembrar(db, 2)
    for p in ps:
        rt.responder(db, p.id, ANA, "B")
    e = rt.mi_estado(db, CID, ANA)
    assert e["respondidos"] == 2 and not e["hay_nuevos"] and e["aciertos"] == 2


# ── la lectura de los temas que escribe el docente ───────────────────────────────────
def test_los_temas_se_leen_con_su_peso():
    t = rt._temas_desde("Pelvis ósea 30%\n- Periné | 20\nDiafragma pélvico\n\n  ")
    assert t == [{"tema": "Pelvis ósea", "peso": 30}, {"tema": "Periné", "peso": 20},
                 {"tema": "Diafragma pélvico", "peso": 1}]


def test_generar_sin_temas_o_sin_material_falla_claro(db):
    with pytest.raises(Exception):
        rt.generar(db, CID, "", "material")
    with pytest.raises(Exception):
        rt.generar(db, CID, "Pelvis", "")


# ── el aviso diario ──────────────────────────────────────────────────────────────────
import datetime as _dt


def _tarde():
    """Una hora dentro de la ventana permitida (UTC), para no depender de cuándo corran los tests."""
    return _dt.datetime(2026, 8, 30, 21, 0)


def _seguidor(db, owner="dev:ana"):
    import uuid as _u
    from app.models.push import StudentCourseFollow
    db.add(StudentCourseFollow(course_id=_u.UUID(CID), owner_key=owner)); db.commit()


def test_de_noche_no_se_avisa(db):
    """Un recordatorio académico a las 2 AM no ayuda a aprender: entrena a silenciar la app."""
    _sembrar(db, 3); _seguidor(db)
    r = rt.tick(db, ahora=_dt.datetime(2026, 8, 30, 5, 0))
    assert r["fuera_de_hora"] and r["avisados"] == 0


def test_se_avisa_una_sola_vez_al_dia(db, monkeypatch):
    from app.services import push_service
    monkeypatch.setattr(push_service, "enviar_a_owner", lambda *a, **k: 1)
    _sembrar(db, 3); _seguidor(db)
    assert rt.tick(db, ahora=_tarde())["avisados"] == 1
    for _ in range(4):                      # el barrido corre cada diez minutos
        assert rt.tick(db, ahora=_tarde())["avisados"] == 0


def test_sin_banco_aprobado_no_se_avisa(db, monkeypatch):
    from app.services import push_service
    monkeypatch.setattr(push_service, "enviar_a_owner", lambda *a, **k: 1)
    _sembrar(db, 3, estado="propuesta"); _seguidor(db)
    assert rt.tick(db, ahora=_tarde())["avisados"] == 0


def test_el_aviso_lleva_la_cara_de_runi(db):
    p = rt.payload_push(12)
    assert p["icon"].endswith("icon-192.png") and "Runi" in p["title"]
    assert p["url"] == "/?reto=1"
