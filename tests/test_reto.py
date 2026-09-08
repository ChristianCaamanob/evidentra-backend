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

# Los retos solo se sirven dentro de una ventana (ver VENTANAS). Estas son marcas UTC que caen
# dentro de dos ventanas distintas del mismo día en hora de Chile (13:10 y 17:10 locales).
import datetime as _dtt
ABIERTA = _dtt.datetime(2026, 9, 1, 17, 10)          # 13:10 en Chile
ABIERTA2 = _dtt.datetime(2026, 9, 1, 21, 10)         # 17:10 en Chile
CERRADA = _dtt.datetime(2026, 9, 2, 2, 30)           # 22:30 en Chile: ya cerró la última ventana
# Las ventanas con AVISO son (9, 12, 15, 18): estas dos caen al abrirse dos de ellas.
AVISO1 = _dtt.datetime(2026, 9, 1, 16, 5)            # 12:05 en Chile
AVISO2 = _dtt.datetime(2026, 9, 1, 19, 5)            # 15:05 en Chile
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
    assert rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"] == []


def test_una_descartada_tampoco(db):
    _sembrar(db, 5, estado="descartada")
    assert rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"] == []


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
    assert len(rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]) == 1


def test_una_pregunta_manual_incompleta_se_rechaza(db):
    for mala in ({"enunciado": "sin alternativas"},
                 {"enunciado": "x", "alternativas": {"A": "sola"}, "correcta": "A"},
                 {"enunciado": "x", "alternativas": {"A": "u", "B": "d"}, "correcta": "Z"}):
        with pytest.raises(Exception):
            rt.crear_manual(db, CID, mala)


# ── la sesión ────────────────────────────────────────────────────────────────────────
def test_nunca_mas_de_tres_por_sesion(db):
    _sembrar(db, 40)
    assert len(rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]) == rt.POR_SESION
    assert len(rt.sesion(db, CID, ANA, n=99, ahora=ABIERTA)["preguntas"]) == rt.POR_SESION


def test_lo_ya_respondido_no_vuelve_a_salir(db):
    _sembrar(db, 6)
    vistas = set()
    for cuando in (ABIERTA, ABIERTA2):          # una ventana da 3; hacen falta dos para las 6
        preguntas = rt.sesion(db, CID, ANA, ahora=cuando)["preguntas"]
        for q in preguntas:
            assert q["id"] not in vistas, "le salió de nuevo una que ya había respondido"
            vistas.add(q["id"])
        _responder_dentro(db, preguntas, ANA, cuando)
    assert len(vistas) == 6


def test_la_sesion_no_revela_la_respuesta(db):
    _sembrar(db, 3)
    for q in rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]:
        assert "correcta" not in q and "justificacion" not in q


def test_dentro_de_la_misma_ventana_no_se_repite_ninguna(db):
    """Repetir la misma pregunta a los cinco minutos no es repasar: es un bucle."""
    _sembrar(db, 2)
    _responder_dentro(db, rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"], ANA, ABIERTA)
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA)
    assert s["ok"] and s["preguntas"] == []


def test_dos_estudiantes_no_reciben_la_misma_lista_en_el_mismo_orden(db):
    _sembrar(db, 30)
    a = [q["id"] for q in rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]]
    l = [q["id"] for q in rt.sesion(db, CID, LUZ, ahora=ABIERTA)["preguntas"]]
    assert a != l


def test_lo_que_mas_pesa_en_la_tabla_sale_primero(db):
    _sembrar(db, 5, tema="Tema liviano", peso=1)
    _sembrar(db, 5, tema="Pelvis ósea", peso=40)
    temas = {q["tema"] for q in rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]}
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
    assert {q["tema"] for q in rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]} == {"Periné"}


def test_sin_identidad_no_hay_sesion(db):
    _sembrar(db, 3)
    with pytest.raises(Exception):
        rt.sesion(db, CID, "", ahora=ABIERTA)


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
    e = rt.mi_estado(db, CID, ANA, ahora=ABIERTA)
    assert e["banco"] == 4 and e["respondidos"] == 0 and e["hay_nuevos"]


def test_cuando_respondio_todo_entra_en_segunda_vuelta(db):
    """El banco no se acaba: si se acabara, volvería a entrar y no encontraría nada."""
    ps = _sembrar(db, 2)
    for p in ps:
        rt.responder(db, p.id, ANA, "B")
    e = rt.mi_estado(db, CID, ANA, ahora=ABIERTA)
    assert e["respondidos"] == 2 and e["aciertos"] == 2
    assert e["hay_nuevos"] and e["en_repaso"]


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
    """Al ABRIRSE una ventana con aviso (UTC), para no depender de cuándo corran los tests."""
    return _dt.datetime(2026, 8, 30, 16, 5)      # 12:05 en Chile: ventana 12, de las que avisan


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


# ── importar la pauta del docente ────────────────────────────────────────────────────
def _docx(parrafos):
    """Un .docx mínimo. `parrafos` = [(texto, ¿resaltado?)]."""
    import io, zipfile
    def p(t, hl):
        rpr = '<w:rPr><w:highlight w:val="yellow"/></w:rPr>' if hl else ''
        return f'<w:p><w:r>{rpr}<w:t>{t}</w:t></w:r></w:p>'
    doc = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
           + "".join(p(t, h) for t, h in parrafos) + '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


_PAUTA = [("1. ¿Qué hueso forma el estrecho superior?", False),
          ("a) El fémur", False), ("b) El sacro", True),
          ("c) La escápula", False), ("d) El húmero", False),
          ("2. ¿Qué músculo cierra el periné?", False),
          ("a) Elevador del ano", True), ("b) Psoas", False), ("c) Diafragma", False)]


def test_la_pauta_se_lee_con_su_correcta_resaltada():
    qs = rt.parsear_docx(_docx(_PAUTA), "Pelvis")
    assert len(qs) == 2
    assert qs[0]["correcta"] == "B" and qs[0]["alternativas"]["B"] == "El sacro"
    assert qs[1]["correcta"] == "A" and len(qs[1]["alternativas"]) == 3


def test_una_pregunta_sin_marcar_no_entra(db):
    """Adivinar cuál era la correcta sería peor que dejarla fuera: se informa cuántas quedaron."""
    import base64
    sin_marcar = [("3. ¿Qué nervio inerva el periné?", False), ("a) Pudendo", False), ("b) Obturador", False)]
    r = rt.importar_docx(db, CID, base64.b64encode(_docx(_PAUTA + sin_marcar)).decode(), "Pelvis")
    assert r["importadas"] == 2 and r["sin_marcar"] == 1


def test_lo_importado_nace_aprobado_y_le_llega_al_alumno(db):
    import base64
    rt.importar_docx(db, CID, base64.b64encode(_docx(_PAUTA)).decode(), "Pelvis")
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA)
    assert len(s["preguntas"]) == 2
    assert all(q["tema"] == "Pelvis" for q in s["preguntas"])


def test_reimportar_el_mismo_archivo_no_duplica(db):
    import base64
    b64 = base64.b64encode(_docx(_PAUTA)).decode()
    rt.importar_docx(db, CID, b64, "Pelvis")
    r = rt.importar_docx(db, CID, b64, "Pelvis")
    assert r["importadas"] == 0 and r["repetidas"] == 2
    assert db.query(RetoPregunta).count() == 2


def test_un_archivo_que_no_es_docx_falla_claro(db):
    import base64
    with pytest.raises(Exception):
        rt.importar_docx(db, CID, base64.b64encode(b"esto no es un docx").decode())


def test_un_docx_sin_preguntas_lo_dice(db):
    import base64
    vacio = _docx([("Apuntes de clase", False), ("Nada con formato de pregunta", False)])
    with pytest.raises(Exception):
        rt.importar_docx(db, CID, base64.b64encode(vacio).decode())


def test_una_linea_mal_formada_no_corrompe_la_pregunta_anterior():
    """Si un bloque no se reconoce como enunciado, sus alternativas NO pisan las de la anterior."""
    raro = _PAUTA + [("Pregunta sin numerar", False), ("a) Intrusa", False)]
    qs = rt.parsear_docx(_docx(raro), "Pelvis")
    assert qs[1]["alternativas"]["A"] == "Elevador del ano"


# ── publicar el lote y limpiar ───────────────────────────────────────────────────────
def test_publicar_todas_de_una_vez(db):
    """Revisar treinta preguntas con un clic cada una no es una revisión: es una fila de clics."""
    _sembrar(db, 12, estado="propuesta")
    r = rt.aprobar_todas(db, CID)
    assert r["publicadas"] == 12 and r["sin_correcta"] == 0
    assert len(rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]) == rt.POR_SESION


def test_publicar_todas_deja_atras_las_que_no_se_pueden_corregir(db):
    ps = _sembrar(db, 3, estado="propuesta")
    ps[0].correcta = "Z"; db.commit()
    r = rt.aprobar_todas(db, CID)
    assert r["publicadas"] == 2 and r["sin_correcta"] == 1
    assert db.query(RetoPregunta).filter(RetoPregunta.estado == "propuesta").count() == 1


def test_publicar_todas_no_toca_lo_descartado(db):
    _sembrar(db, 2, estado="descartada")
    _sembrar(db, 2, estado="propuesta")
    rt.aprobar_todas(db, CID)
    assert db.query(RetoPregunta).filter(RetoPregunta.estado == "descartada").count() == 2


def test_vaciar_borra_solo_ese_estado(db):
    _sembrar(db, 4, estado="descartada")
    _sembrar(db, 3, estado="aprobada")
    r = rt.vaciar(db, CID, "descartada")
    assert r["eliminadas"] == 4
    assert db.query(RetoPregunta).count() == 3


def test_eliminar_una_publicada_borra_tambien_sus_respuestas(db):
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "B")
    rt.eliminar(db, p.id)
    from app.models.reto import RetoRespuesta
    assert db.query(RetoPregunta).count() == 0 and db.query(RetoRespuesta).count() == 0


def test_vaciar_un_estado_inventado_se_rechaza(db):
    with pytest.raises(Exception):
        rt.vaciar(db, CID, "loquesea")


# ── los porqués: Runi redacta, el docente firma ──────────────────────────────────────
def _runi_dice(monkeypatch, textos):
    """Sustituye la llamada al modelo por una respuesta fija."""
    import json as _j
    from app.services import correccion_experta_service as ce
    def fake(system, user, max_tokens=2600):
        return _j.dumps({"justificaciones": [{"n": i + 1, "texto": t} for i, t in enumerate(textos)]})
    monkeypatch.setattr(ce, "_llamar_anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")


def test_el_borrador_NO_lo_ve_la_estudiante(db, monkeypatch):
    """Una explicación equivocada de anatomía enseña algo falso, igual que una pregunta mala."""
    _sembrar(db, 2)
    for p in db.query(RetoPregunta).all():
        p.justificacion = None
    db.commit()
    _runi_dice(monkeypatch, ["Porque el sacro cierra por detrás.", "Porque el elevador sostiene."])
    r = rt.justificar(db, CID, "material del curso", "Anatomía")
    assert r["redactadas"] == 2
    # La sesión del alumno no trae ni el borrador ni la justificación
    for q in rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]:
        assert "justificacion" not in q and "justificacion_ia" not in q
    # Y al responder tampoco: todavía no hay justificación aceptada
    p = db.query(RetoPregunta).first()
    assert rt.responder(db, p.id, LUZ, "B")["justificacion"] is None


def test_aceptar_el_borrador_lo_hace_visible(db, monkeypatch):
    p = _sembrar(db, 1)[0]
    p.justificacion = None; db.commit()
    _runi_dice(monkeypatch, ["El sacro cierra la pelvis por detrás."])
    rt.justificar(db, CID, "material", "Anatomía")
    rt.usar_justificacion(db, p.id)
    assert rt.responder(db, p.id, ANA, "B")["justificacion"] == "El sacro cierra la pelvis por detrás."
    assert db.query(RetoPregunta).first().justificacion_ia is None


def test_el_docente_puede_corregir_antes_de_aceptar(db, monkeypatch):
    p = _sembrar(db, 1)[0]
    p.justificacion = None; db.commit()
    _runi_dice(monkeypatch, ["Texto flojo."])
    rt.justificar(db, CID, "material")
    rt.usar_justificacion(db, p.id, "Lo escribo yo mejor.")
    assert db.query(RetoPregunta).first().justificacion == "Lo escribo yo mejor."


def test_descartar_el_borrador_no_toca_la_pregunta(db, monkeypatch):
    p = _sembrar(db, 1)[0]
    p.justificacion = None; db.commit()
    _runi_dice(monkeypatch, ["No me convence."])
    rt.justificar(db, CID, "material")
    rt.descartar_justificacion(db, p.id)
    f = db.query(RetoPregunta).first()
    assert f.justificacion_ia is None and f.justificacion is None and f.estado == "aprobada"


def test_no_se_pisan_las_justificaciones_que_ya_tenia(db, monkeypatch):
    """Las que el docente ya escribió no se tocan salvo que lo pida explícitamente."""
    _sembrar(db, 2)          # nacen con justificación "Porque sí."
    _runi_dice(monkeypatch, ["otra cosa", "otra cosa"])
    r = rt.justificar(db, CID, "material")
    assert r["nada_que_hacer"]
    assert all(p.justificacion == "Porque sí." for p in db.query(RetoPregunta).all())


def test_si_el_material_no_alcanza_se_deja_vacio_en_vez_de_inventar(db, monkeypatch):
    ps = _sembrar(db, 2)
    for p in ps:
        p.justificacion = None
    db.commit()
    _runi_dice(monkeypatch, ["Una explicación buena.", ""])
    r = rt.justificar(db, CID, "material")
    assert r["redactadas"] == 1 and r["sin_material"] == 1


def test_aceptar_todas_de_una_vez(db, monkeypatch):
    ps = _sembrar(db, 3)
    for p in ps:
        p.justificacion = None
    db.commit()
    _runi_dice(monkeypatch, ["uno", "dos", "tres"])
    rt.justificar(db, CID, "material")
    assert rt.usar_todas_las_justificaciones(db, CID)["aceptadas"] == 3
    assert all(p.justificacion and not p.justificacion_ia for p in db.query(RetoPregunta).all())


def test_sin_material_no_se_redacta_nada(db):
    _sembrar(db, 1)
    with pytest.raises(Exception):
        rt.justificar(db, CID, "")


# ── las ventanas del día ─────────────────────────────────────────────────────────────
def test_fuera_de_ventana_no_hay_retos(db):
    """«Son como los huevitos de chocolate»: si estuvieran siempre, dejarían de ser un hallazgo."""
    _sembrar(db, 10)
    s = rt.sesion(db, CID, ANA, ahora=CERRADA)
    assert s["ok"] and s["cerrado"] and s["preguntas"] == []
    assert s["ventana"]["proxima_local"] == "08:00"      # mañana, al abrir


def test_dentro_de_ventana_da_tres(db):
    _sembrar(db, 10)
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA)
    assert not s["cerrado"] and len(s["preguntas"]) == 3


def _responder_dentro(db, preguntas, quien, cuando):
    """Responde y ancla la marca de tiempo DENTRO de la ventana indicada.

    La base estampa la hora REAL; los tests trabajan con una fecha fija. Anclar sin condiciones es
    lo que los hace deterministas: la versión anterior solo ajustaba si la marca real era anterior,
    y en cuanto el reloj pasó esa fecha los tests empezaron a fallar solos.
    """
    from app.models.reto import RetoRespuesta
    for q in preguntas:
        rt.responder(db, q["id"], quien, "B", ahora=cuando)
    for r in db.query(RetoRespuesta).filter(RetoRespuesta.pseudo_id == quien).all():
        r.created_at = cuando
    db.commit()


def test_la_ventana_se_agota_al_responder_sus_tres(db):
    _sembrar(db, 20)
    _responder_dentro(db, rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"], ANA, ABIERTA)
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA)
    assert s["cerrado"] and s.get("completa") and s["preguntas"] == []


def test_la_siguiente_ventana_trae_mas(db):
    _sembrar(db, 20)
    _responder_dentro(db, rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"], ANA, ABIERTA)
    assert len(rt.sesion(db, CID, ANA, ahora=ABIERTA2)["preguntas"]) == 3


def test_hay_una_tanda_por_hora_y_ninguna_de_noche():
    """El CEO pasó de «cada 2 horas» a «cada hora, de 08:00 a 19:00».

    Con ventanas seguidas la dosificación ya no la da el hueco entre ellas: la da `POR_SESION`.
    Son 3 y hasta la hora siguiente no hay más, aunque la app esté abierta todo el día.
    """
    assert list(rt.VENTANAS) == list(range(8, 20))
    assert min(rt.VENTANAS) >= 7 and max(rt.VENTANAS) <= 21
    assert rt.POR_SESION == 3


def test_no_se_avisa_en_todas_las_ventanas():
    """Siete notificaciones diarias no crean el hábito: hacen que se silencie la app."""
    assert set(rt.VENTANAS_CON_AVISO) < set(rt.VENTANAS)
    assert len(rt.VENTANAS_CON_AVISO) == 4


def test_una_ventana_sin_aviso_igual_sirve_preguntas(db):
    _sembrar(db, 6)
    once = _dtt.datetime(2026, 9, 1, 15, 10)        # 11:10 local: hay ventana, no hay aviso
    assert len(rt.sesion(db, CID, ANA, ahora=once)["preguntas"]) == 3


def test_la_ventana_dice_cuando_vuelve_a_abrir(db):
    v = rt.ventana_de(CERRADA)
    assert not v["abierta"] and v["proxima_local"] == "08:00" and v["minutos_para_proxima"] == 570
    v2 = rt.ventana_de(ABIERTA)
    assert v2["abierta"] and v2["cierra_local"] == "14:00"


def test_pasadas_todas_las_ventanas_la_proxima_es_manana(db):
    tarde = _dtt.datetime(2026, 9, 2, 3, 0)      # 23:00 en Chile
    assert rt.ventana_de(tarde)["proxima_local"] == "08:00"


def test_el_estado_de_inicio_no_ofrece_nada_fuera_de_ventana(db):
    _sembrar(db, 10)
    e = rt.mi_estado(db, CID, ANA, ahora=CERRADA)
    assert not e["hay_nuevos"] and e["quedan_en_banco"] == 10
    assert rt.mi_estado(db, CID, ANA, ahora=ABIERTA)["hay_nuevos"]


def test_el_aviso_solo_sale_al_abrirse_la_ventana(db, monkeypatch):
    from app.services import push_service
    monkeypatch.setattr(push_service, "enviar_a_owner", lambda *a, **k: 1)
    _sembrar(db, 5); _seguidor(db)
    assert rt.tick(db, ahora=CERRADA)["avisados"] == 0
    tarde_en_ventana = _dtt.datetime(2026, 9, 1, 16, 40)   # 12:40 local: la ventana sigue abierta…
    assert rt.tick(db, ahora=tarde_en_ventana)["avisados"] == 0   # …pero avisar ahora llega tarde
    assert rt.tick(db, ahora=AVISO1)["avisados"] == 1
    assert rt.tick(db, ahora=AVISO1)["avisados"] == 0            # una vez por ventana


def test_cada_ventana_avisa_una_vez(db, monkeypatch):
    from app.services import push_service
    monkeypatch.setattr(push_service, "enviar_a_owner", lambda *a, **k: 1)
    _sembrar(db, 5); _seguidor(db)
    assert rt.tick(db, ahora=AVISO1)["avisados"] == 1
    assert rt.tick(db, ahora=AVISO2)["avisados"] == 1


def test_el_aviso_dice_hasta_cuando(db):
    p = rt.payload_push(20, rt.ventana_de(ABIERTA))
    assert "14:00" in p["body"] and "Runi" in p["title"]


# ── segunda vuelta: el banco rota en vez de acabarse ─────────────────────────────────
def test_agotado_el_banco_las_preguntas_vuelven(db):
    _sembrar(db, 3)
    _responder_dentro(db, rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"], ANA, ABIERTA)
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA2)          # otra ventana
    assert s["repaso"] and len(s["preguntas"]) == 3


def test_en_la_segunda_vuelta_lo_fallado_va_primero(db):
    """Es lo que más conviene repasar, y además lo que la práctica espaciada recomienda."""
    ps = _sembrar(db, 4)
    rt.responder(db, ps[0].id, ANA, "A")                  # falla esta
    for p in ps[1:]:
        rt.responder(db, p.id, ANA, "B")                  # acierta el resto
    from app.models.reto import RetoRespuesta
    for r in db.query(RetoRespuesta).all():
        r.created_at = ABIERTA
    db.commit()
    s = rt.sesion(db, CID, ANA, ahora=ABIERTA2)
    assert s["preguntas"][0]["id"] == str(ps[0].id)


def test_en_segunda_vuelta_se_puede_volver_a_responder(db):
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "A", ahora=ABIERTA)       # falla
    from app.models.reto import RetoRespuesta
    db.query(RetoRespuesta).first().created_at = ABIERTA
    db.commit()
    r = rt.responder(db, p.id, ANA, "B", ahora=ABIERTA2)  # acierta en la vuelta siguiente
    assert r["acerto"] and r.get("repaso")
    assert db.query(RetoRespuesta).count() == 1           # una fila por par, no historial inflado


def test_en_la_misma_ventana_no_se_puede_reintentar(db):
    """Si no, sería adivinar hasta acertar."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "A", ahora=ABIERTA)
    from app.models.reto import RetoRespuesta
    db.query(RetoRespuesta).first().created_at = ABIERTA
    db.commit()
    r = rt.responder(db, p.id, ANA, "B", ahora=ABIERTA)
    assert r["ya_respondida"] and not r["acerto"]


# ── horario de verano ────────────────────────────────────────────────────────────────
def test_las_ventanas_siguen_la_hora_real_de_chile_en_verano_y_en_invierno():
    """Un desfase fijo se rompe solo dos veces al año.

    Visto en producción el 7-sep-2026: Chile había entrado en horario de verano y las ventanas
    quedaron corridas una hora — la de las 21:00 se abría a las 22:00, que ES de noche, justo lo
    que la regla prohíbe.
    """
    # 13:10 en Chile son las 17:10 UTC en invierno y las 16:10 UTC en verano.
    assert rt._local(_dtt.datetime(2026, 7, 1, 17, 10)).strftime("%H:%M") == "13:10"
    assert rt._local(_dtt.datetime(2026, 12, 1, 16, 10)).strftime("%H:%M") == "13:10"


def test_ninguna_ventana_cae_de_noche_en_ninguna_epoca_del_ano():
    for mes in range(1, 13):
        for h in range(24):
            v = rt.ventana_de(_dtt.datetime(2026, mes, 15, h, 30))
            if v["abierta"]:
                assert 8 <= v["hora"] <= 19, (mes, h, v["hora"])


def test_el_inicio_de_la_ventana_vuelve_a_utc_con_la_zona_correcta():
    """Si la vuelta a UTC usara el desfase fijo, «lo respondido en esta ventana» se contaría mal."""
    v = rt.ventana_de(_dtt.datetime(2026, 12, 1, 16, 10))     # verano: 13:10 local
    assert v["abierta"] and v["desde_utc"] == _dtt.datetime(2026, 12, 1, 16, 0)


# ── variantes: más munición sin volver a escribirlo todo ─────────────────────────────
def _runi_variantes(monkeypatch, n_por_tanda=6, correcta="C", omitir=()):
    """Sustituye el modelo por variantes fabricadas, con la correcta rotada."""
    import json as _j
    from app.services import correccion_experta_service as ce
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def fake(system, user, max_tokens=5000):
        vs = []
        for i in range(1, n_por_tanda + 1):
            if i in omitir:
                continue
            vs.append({"n": i, "tema": "Pelvis ósea", "nivel": "recordar",
                       "enunciado": f"Variante {i} · {hash(user) % 9999}",
                       "alternativas": {"A": "uno", "B": "dos", "C": "tres", "D": "cuatro"},
                       "correcta": correcta, "justificacion": "Porque el sacro cierra por detrás."})
        return _j.dumps({"variantes": vs})

    monkeypatch.setattr(ce, "_llamar_anthropic", fake)


def test_las_variantes_nacen_para_revision_no_publicadas(db, monkeypatch):
    """Las escribe la IA: la firma sigue siendo del profesor."""
    _sembrar(db, 3)
    for p in db.query(RetoPregunta).all():
        p.origen = "docente"
    db.commit()
    _runi_variantes(monkeypatch, n_por_tanda=3)
    r = rt.variantes(db, CID, "material del curso", "Anatomía")
    assert r["creadas"] == 3
    nuevas = db.query(RetoPregunta).filter(RetoPregunta.estado == "propuesta").all()
    assert len(nuevas) == 3 and all(p.origen == "ia" for p in nuevas)
    # Y no le llegan a nadie hasta que se aprueben.
    assert len(rt.sesion(db, CID, ANA, ahora=ABIERTA)["preguntas"]) == 3   # solo las 3 originales


def test_la_variante_lleva_su_porque_desde_el_principio(db, monkeypatch):
    _sembrar(db, 1)
    db.query(RetoPregunta).first().origen = "docente"; db.commit()
    _runi_variantes(monkeypatch, n_por_tanda=1)
    rt.variantes(db, CID, "material", "Anatomía")
    v = db.query(RetoPregunta).filter(RetoPregunta.estado == "propuesta").first()
    assert v.justificacion and "sacro" in v.justificacion


def test_no_se_hacen_variantes_de_variantes(db, monkeypatch):
    """Cada ronda sobre una variante aleja un poco más del original: dejan de ser preguntas suyas."""
    _sembrar(db, 2)
    for p in db.query(RetoPregunta).all():
        p.origen = "ia"          # ninguna es del docente
    db.commit()
    _runi_variantes(monkeypatch, n_por_tanda=2)
    with pytest.raises(Exception):
        rt.variantes(db, CID, "material", "Anatomía")


def test_una_variante_repetida_no_entra(db, monkeypatch):
    """Si sale igual que una que ya existe, no aporta nada."""
    import json as _j
    from app.services import correccion_experta_service as ce
    p = _sembrar(db, 1)[0]
    p.origen = "docente"; db.commit()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ce, "_llamar_anthropic", lambda *a, **k: _j.dumps({"variantes": [
        {"n": 1, "tema": "Pelvis ósea", "enunciado": p.enunciado,     # idéntica a la original
         "alternativas": {"A": "u", "B": "d", "C": "t", "D": "c"}, "correcta": "C",
         "justificacion": "x"}]}))
    r = rt.variantes(db, CID, "material", "Anatomía")
    assert r["creadas"] == 0 and r["omitidas"] == 1


def test_si_el_modelo_omite_alguna_se_dice_cuantas(db, monkeypatch):
    """«Es mejor devolver menos que rellenar»: hay que saber cuántas quedaron fuera."""
    _sembrar(db, 3)
    for p in db.query(RetoPregunta).all():
        p.origen = "docente"
    db.commit()
    _runi_variantes(monkeypatch, n_por_tanda=3, omitir=(2,))
    r = rt.variantes(db, CID, "material", "Anatomía")
    assert r["creadas"] == 2 and r["omitidas"] == 1 and r["originales"] == 3


def test_sin_preguntas_del_docente_lo_dice_claro(db, monkeypatch):
    _runi_variantes(monkeypatch)
    with pytest.raises(Exception):
        rt.variantes(db, CID, "material", "Anatomía")


# ── trazabilidad: el acta de intentos y el análisis por pregunta ──────────────────────
# El CEO preguntó si teníamos trazabilidad de lo que responden las estudiantes. El dato estaba en
# la base y no lo veía nadie; y peor, la segunda vuelta SOBREESCRIBÍA el intento anterior, así que
# «falló el martes y acertó el viernes» —justo lo que dice si alguien aprendió— no existía.
from app.models.reto import RetoIntento


def _resp(db, pregunta_id, quien, letra, cuando):
    """Responde anclando la marca de tiempo, como `_responder_dentro`.

    La base estampa la hora REAL; sin anclar, la segunda vuelta se lee como «la misma ventana» y
    el test dependería del día en que se corre.
    """
    from app.models.reto import RetoRespuesta
    r = rt.responder(db, pregunta_id, quien, letra, CID, ahora=cuando)
    for fila in db.query(RetoRespuesta).filter(RetoRespuesta.pseudo_id == quien,
                                               RetoRespuesta.pregunta_id == pregunta_id).all():
        fila.created_at = cuando
    db.commit()
    return r


def test_el_intento_queda_registrado_con_la_letra_que_eligio(db):
    """Saber que falló no sirve; saber que se fue a la C dice QUÉ entendió mal."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "C", CID, ahora=ABIERTA)
    i = db.query(RetoIntento).filter(RetoIntento.pseudo_id == ANA).one()
    assert i.elegida == "C" and not i.correcta and i.vuelta == 1
    assert i.course_id == CID          # desnormalizado: sobrevive al borrado de la pregunta


def test_la_segunda_vuelta_ya_no_borra_la_primera(db):
    """El corazón del asunto: antes se actualizaba la fila y el error se perdía."""
    p = _sembrar(db, 1)[0]
    _resp(db, p.id, ANA, "A", ABIERTA)      # falla
    _resp(db, p.id, ANA, "B", ABIERTA2)     # acierta en el repaso
    actas = db.query(RetoIntento).filter(RetoIntento.pseudo_id == ANA).order_by(
        RetoIntento.vuelta.asc()).all()
    assert [(a.elegida, a.correcta, a.vuelta) for a in actas] == [("A", False, 1), ("B", True, 2)]


def test_repetir_en_la_misma_ventana_no_infla_el_acta(db):
    """Dentro de la ventana no se puede cambiar la respuesta: tampoco debe anotarse un intento."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "A", CID, ahora=ABIERTA)
    rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)
    assert db.query(RetoIntento).count() == 1


def test_el_analisis_muestra_el_distractor_que_mas_arrastra(db):
    p = _sembrar(db, 1)[0]
    for quien, letra in (("stu:1", "C"), ("stu:2", "C"), ("stu:3", "C"), ("stu:4", "B")):
        rt.responder(db, p.id, quien, letra, CID, ahora=ABIERTA)
    q = rt.analisis(db, CID)["preguntas"][0]
    assert q["intentos"] == 4 and q["aciertos"] == 1 and q["acierto_pct"] == 25
    assert q["distractor"]["letra"] == "C" and q["distractor"]["n"] == 3
    assert q["distractor"]["texto"] == "tres"       # el texto, no solo la letra


def test_el_analisis_no_lleva_nombres_ni_pseudonimos(db):
    """Regla del CEO: el profesor solo tiene acceso a chat. Esta vista es agregada, y punto."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "C", CID, ahora=ABIERTA)
    crudo = repr(rt.analisis(db, CID))
    assert ANA not in crudo and "stu:" not in crudo


def test_una_pregunta_con_pocos_datos_no_finge_un_porcentaje(db):
    """3 de 3 no es «100% de acierto»: con dos respuestas un porcentaje es ruido disfrazado."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)
    q = rt.analisis(db, CID)["preguntas"][0]
    assert q["acierto_pct"] is None and not q["suficiente"] and q["intentos"] == 1


def test_una_pregunta_sin_responder_no_encabeza_la_lista_de_lo_fallado(db):
    """Ordenar por «peor primero» pondría arriba lo que nadie tocó: un problema inventado."""
    a, b = _sembrar(db, 2)
    for quien in ("stu:1", "stu:2", "stu:3"):
        rt.responder(db, a.id, quien, "A", CID, ahora=ABIERTA)   # todos fallan la primera
    orden = [q["id"] for q in rt.analisis(db, CID)["preguntas"]]
    assert orden[0] == str(a.id) and orden[-1] == str(b.id)


def test_el_analisis_cuenta_quien_se_corrigio(db):
    """La medida de que el repaso sirve: falló y en la vuelta siguiente acertó."""
    p = _sembrar(db, 1)[0]
    _resp(db, p.id, ANA, "A", ABIERTA); _resp(db, p.id, ANA, "B", ABIERTA2)
    _resp(db, p.id, LUZ, "A", ABIERTA); _resp(db, p.id, LUZ, "C", ABIERTA2)
    r = rt.analisis(db, CID)["resumen"]
    assert r["corregidos"] == 1 and r["reincidentes"] == 1 and r["personas"] == 2


def test_el_analisis_cuenta_los_intentos_y_no_el_ultimo_estado(db):
    """Contando el estado, un error corregido después desaparece y la pregunta parece más fácil."""
    p = _sembrar(db, 1)[0]
    _resp(db, p.id, ANA, "A", ABIERTA)
    _resp(db, p.id, ANA, "B", ABIERTA2)
    q = rt.analisis(db, CID)["preguntas"][0]
    assert q["intentos"] == 2 and q["aciertos"] == 1 and q["personas"] == 1


def test_un_curso_sin_banco_no_revienta(db):
    assert rt.analisis(db, CID) == {"ok": True, "preguntas": [], "resumen": {"intentos": 0, "personas": 0}}


def test_borrar_una_pregunta_no_borra_su_acta(db):
    """El acta es libro de actas: sobrevive a que el docente limpie el banco."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "C", CID, ahora=ABIERTA)
    rt.eliminar(db, p.id)
    assert db.query(RetoIntento).count() == 1


# ── ventanas cada hora, 08 a 19 ───────────────────────────────────────────────────────
def test_las_ventanas_van_de_ocho_a_diecinueve_una_por_hora():
    """Pedido del CEO: 3 preguntas cada hora entre las 08:00 y las 19:00."""
    assert rt.VENTANAS == tuple(range(8, 20))
    assert rt.POR_SESION == 3


def test_ninguna_ventana_cae_de_noche():
    """La última abre a las 19:00 y cierra a las 20:00. Un reto a las 2 AM no se negocia."""
    assert min(rt.VENTANAS) >= 7
    assert max(rt.VENTANAS) + (rt.DURACION_MIN / 60) <= 21


def test_los_avisos_son_cuatro_y_caen_en_ventanas_reales():
    """Doce notificaciones al día hacen que se silencie la app, y con ella los avisos del profesor."""
    assert len(rt.VENTANAS_CON_AVISO) == 4
    assert set(rt.VENTANAS_CON_AVISO) <= set(rt.VENTANAS)


def test_a_las_ocho_de_la_manana_ya_hay_reto(db):
    _sembrar(db, 5)
    ocho = _dtt.datetime(2026, 9, 10, 11, 5)          # 08:05 en Chile (ya con horario de verano)
    assert rt.ventana_de(ocho)["abierta"] and rt.ventana_de(ocho)["hora"] == 8


def test_a_las_nueve_de_la_noche_ya_no(db):
    nueve = _dtt.datetime(2026, 9, 10, 0, 30)         # 21:30 del día anterior en Chile
    assert not rt.ventana_de(nueve)["abierta"]


# ── puntaje, tabla y premios ─────────────────────────────────────────────────────────
def test_la_tabla_nunca_lleva_un_nombre_ni_el_pseudonimo(db):
    """La regla del CEO fue «sin ranking». La tabla existe con una condición que es código, no
    promesa: el alias se DERIVA del pseudónimo, no se lee de ningún campo que alguien rellene."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)
    crudo = repr(rt.tabla(db, CID, ANA))
    assert ANA not in crudo and "stu:" not in crudo


def test_el_alias_es_estable_y_distinto_por_persona(db):
    assert rt.alias_de(ANA) == rt.alias_de(ANA)
    assert rt.alias_de(ANA) != rt.alias_de(LUZ)


def test_gana_quien_mas_acierta(db):
    a, b = _sembrar(db, 2)
    rt.responder(db, a.id, ANA, "B", CID, ahora=ABIERTA)     # acierta
    rt.responder(db, b.id, ANA, "B", CID, ahora=ABIERTA)     # acierta
    rt.responder(db, a.id, LUZ, "C", CID, ahora=ABIERTA)     # falla
    t = rt.tabla(db, CID, LUZ)
    assert t["tabla"][0]["puntos"] == 20 and t["tabla"][0]["alias"] == rt.alias_de(ANA)
    assert t["yo"]["puesto"] == 2 and t["yo"]["yo"] is True


def test_a_igualdad_de_puntos_gana_quien_fallo_menos(db):
    """Si no, insistir rindiera igual que saber, y el premio dejaría de medir lo que dice medir."""
    a, b, c = _sembrar(db, 3)
    rt.responder(db, a.id, ANA, "B", CID, ahora=ABIERTA)     # 1 de 1
    rt.responder(db, b.id, LUZ, "B", CID, ahora=ABIERTA)     # 1 de 2
    rt.responder(db, c.id, LUZ, "A", CID, ahora=ABIERTA)
    t = rt.tabla(db, CID)["tabla"]
    assert t[0]["alias"] == rt.alias_de(ANA) and t[0]["respondidas"] == 1
    assert t[1]["alias"] == rt.alias_de(LUZ)


def test_el_repaso_no_sube_el_puntaje(db):
    """Bastaría con fallar a propósito y volver a acertar para escalar sin límite."""
    p = _sembrar(db, 1)[0]
    _resp(db, p.id, ANA, "A", ABIERTA)      # falla en la primera
    _resp(db, p.id, ANA, "B", ABIERTA2)     # acierta en el repaso
    assert rt.tabla(db, CID, ANA)["yo"]["puntos"] == 0


def test_siempre_se_ve_la_propia_fila_aunque_no_este_en_el_podio(db):
    """Una tabla donde no te encuentras desmotiva justo a quien más necesita verse avanzar."""
    ps = _sembrar(db, 1)[0]
    for i in range(12):
        rt.responder(db, ps.id, "stu:x%d" % i, "B", CID, ahora=ABIERTA)
    otra = _sembrar(db, 1)[0]
    rt.responder(db, otra.id, ANA, "A", CID, ahora=ABIERTA)      # falla: 0 puntos, último
    t = rt.tabla(db, CID, ANA, tope=5)
    assert len(t["tabla"]) == 5 and t["yo"] and t["yo"]["puntos"] == 0


def test_acertar_paga_lumis_una_sola_vez(db):
    from app.services import recompensa_service as rc
    p = _sembrar(db, 1)[0]
    r = rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)
    assert r["lumis"] == rt.LUMIS_ACIERTO and rc.saldo(db, ANA) == rt.LUMIS_ACIERTO
    rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)         # reintento en la misma ventana
    assert rc.saldo(db, ANA) == rt.LUMIS_ACIERTO


def test_fallar_no_paga(db):
    from app.services import recompensa_service as rc
    p = _sembrar(db, 1)[0]
    assert rt.responder(db, p.id, ANA, "C", CID, ahora=ABIERTA)["lumis"] == 0
    assert rc.saldo(db, ANA) == 0


def test_el_repaso_tampoco_paga_lumis(db):
    from app.services import recompensa_service as rc
    p = _sembrar(db, 1)[0]
    _resp(db, p.id, ANA, "A", ABIERTA)
    _resp(db, p.id, ANA, "B", ABIERTA2)
    assert rc.saldo(db, ANA) == 0


def test_el_podio_del_dia_paga_a_las_tres_mejores(db):
    from app.services import recompensa_service as rc
    qs = _sembrar(db, 3)
    rt.responder(db, qs[0].id, ANA, "B", CID, ahora=ABIERTA)
    rt.responder(db, qs[1].id, ANA, "B", CID, ahora=ABIERTA)
    rt.responder(db, qs[0].id, LUZ, "B", CID, ahora=ABIERTA)
    r = rt.cerrar_dia(db, CID, ahora=ABIERTA)
    assert r["premiadas"] == 2 and r["podio"][0]["alias"] == rt.alias_de(ANA)
    assert rc.saldo(db, ANA) == 2 * rt.LUMIS_ACIERTO + rt.LUMIS_PODIO[0]
    assert rc.saldo(db, LUZ) == rt.LUMIS_ACIERTO + rt.LUMIS_PODIO[1]


def test_cerrar_el_dia_dos_veces_no_paga_dos_veces(db):
    """El barrido corre cada diez minutos: sin esto, el podio se cobraría seis veces por hora."""
    from app.services import recompensa_service as rc
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "B", CID, ahora=ABIERTA)
    rt.cerrar_dia(db, CID, ahora=ABIERTA)
    antes = rc.saldo(db, ANA)
    rt.cerrar_dia(db, CID, ahora=ABIERTA)
    assert rc.saldo(db, ANA) == antes


def test_quien_no_sumo_nada_no_entra_al_podio(db):
    """Premiar 0 puntos por ser la única que abrió la app vacía el premio de significado."""
    p = _sembrar(db, 1)[0]
    rt.responder(db, p.id, ANA, "C", CID, ahora=ABIERTA)      # falla
    assert rt.cerrar_dia(db, CID, ahora=ABIERTA)["premiadas"] == 0


def test_un_curso_sin_respuestas_no_revienta_al_cerrar(db):
    _sembrar(db, 2)
    assert rt.cerrar_dia(db, CID, ahora=ABIERTA)["premiadas"] == 0
    assert rt.tabla(db, CID, ANA)["tabla"] == []


# ── ponerle tema a un banco que quedó todo bajo «General» ─────────────────────────────
# Visto en el piloto: la pauta se importó con el campo «tema» vacío, las 56 preguntas quedaron con
# el relleno «General», y la escalera de repaso le pidió a una estudiante «Sin mirar apuntes,
# explica con tus palabras: General». No es cosmético: el reto prioriza por tema, el panel agrupa
# por tema y la consigna del repaso se ARMA con el tema.
def _runi_temas(monkeypatch, mapa):
    """Un Runi de mentira que devuelve el tema que le digamos para cada número."""
    import json
    from app.services import correccion_experta_service as ce
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ce, "_llamar_anthropic", lambda *a, **k: json.dumps(
        {"temas": [{"n": n, "tema": t} for n, t in mapa.items()]}))


def test_general_es_relleno_y_un_tema_de_verdad_no():
    for t in ("General", "  general ", "", "Sin clasificar", "Varios", "tu tema"):
        assert rt.es_tema_relleno(t), t
    for t in ("Pelvis ósea", "Drenaje linfático de la mama", "Periné"):
        assert not rt.es_tema_relleno(t), t


def test_runi_le_pone_tema_a_las_que_quedaron_en_general(db, monkeypatch):
    _sembrar(db, 2, tema="General")
    _runi_temas(monkeypatch, {1: "Pelvis ósea", 2: "Periné"})
    r = rt.clasificar_temas(db, CID, "Material del curso", curso="Anatomía")
    assert r["clasificadas"] == 2
    assert {p.tema for p in db.query(RetoPregunta).all()} == {"Pelvis ósea", "Periné"}


def test_no_se_toca_lo_que_ya_tenia_tema(db, monkeypatch):
    """El profesor pudo haber clasificado a mano: reescribirle eso sería pasarle por encima."""
    _sembrar(db, 1, tema="Pelvis ósea")
    _sembrar(db, 1, tema="General")
    _runi_temas(monkeypatch, {1: "Periné"})
    rt.clasificar_temas(db, CID, "Material", curso="Anatomía")
    assert {p.tema for p in db.query(RetoPregunta).all()} == {"Pelvis ósea", "Periné"}


def test_solo_cambia_el_tema_y_nada_mas(db, monkeypatch):
    """La pregunta que el docente aprobó tiene que seguir siendo exactamente la que aprobó."""
    p = _sembrar(db, 1, tema="General")[0]
    antes = (p.enunciado, dict(p.alternativas), p.correcta, p.estado, p.justificacion)
    _runi_temas(monkeypatch, {1: "Pelvis ósea"})
    rt.clasificar_temas(db, CID, "Material", curso="Anatomía")
    q = db.query(RetoPregunta).one()
    assert (q.enunciado, dict(q.alternativas), q.correcta, q.estado, q.justificacion) == antes
    assert q.tema == "Pelvis ósea"


def test_si_runi_devuelve_otro_relleno_se_descarta(db, monkeypatch):
    """Cambiar «General» por «Varios» y llamar a eso un arreglo sería peor: parecería resuelto."""
    _sembrar(db, 1, tema="General")
    _runi_temas(monkeypatch, {1: "Varios"})
    r = rt.clasificar_temas(db, CID, "Material", curso="Anatomía")
    assert r["clasificadas"] == 0 and r["sin_clasificar"] == 1
    assert db.query(RetoPregunta).one().tema == "General"


def test_se_respetan_los_temas_de_la_tabla_de_especificaciones(db, monkeypatch):
    """Si el docente escribió su lista, el prompt usa ESA: son los temas que él reconoce."""
    _sembrar(db, 1, tema="General")
    capturado = {}
    from app.services import correccion_experta_service as ce
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def espia(system, user, max_tokens=2000):
        capturado["system"] = system
        return '{"temas":[{"n":1,"tema":"Pelvis ósea"}]}'

    monkeypatch.setattr(ce, "_llamar_anthropic", espia)
    rt.clasificar_temas(db, CID, "Material", curso="Anatomía",
                        temas_txt="Pelvis ósea 30%\nPeriné 20%")
    assert "Pelvis ósea" in capturado["system"] and "Periné" in capturado["system"]


def test_si_ya_estan_todas_clasificadas_lo_dice(db, monkeypatch):
    _sembrar(db, 2, tema="Pelvis ósea")
    _runi_temas(monkeypatch, {})
    with pytest.raises(Exception):
        rt.clasificar_temas(db, CID, "Material", curso="Anatomía")


def test_una_tanda_caida_no_arrastra_al_resto(db, monkeypatch):
    """Si el modelo falla, las preguntas quedan como estaban: nunca a medio clasificar."""
    _sembrar(db, 3, tema="General")
    from app.services import correccion_experta_service as ce
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ce, "_llamar_anthropic",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caído")))
    r = rt.clasificar_temas(db, CID, "Material", curso="Anatomía")
    assert r["clasificadas"] == 0 and r["sin_clasificar"] == 3
    assert {p.tema for p in db.query(RetoPregunta).all()} == {"General"}
