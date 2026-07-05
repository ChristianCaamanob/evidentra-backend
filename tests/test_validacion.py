"""Test de la validacion graduada del docente (F3): auditoria, masivo, trazabilidad, QWK, nota."""
from __future__ import annotations
import uuid

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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.validacion import RegistroValidacion
from app.services import validacion_service as vs


def _precalifs():
    # 10 criterios: 3 marcados (baja confianza), 7 de alta confianza.
    out = []
    for i in range(10):
        marcado = i < 3
        out.append({"ref": f"r{i}", "criterio": f"C{i}",
                    "nivel_ia": "parcial" if marcado else "logrado",
                    "confianza": 0.5 if marcado else 0.95,
                    "requiere_revision": marcado, "peso": 1.0})
    return out


def test_auditoria_ligera_solo_marcados():
    p = vs.plan_auditoria(_precalifs(), vs.MODO_LIGERA)
    assert p["n_revisar"] == 3 and p["n_auto"] == 7
    assert all(x["requiere_revision"] for x in p["a_revisar"])


def test_auditoria_profunda_revisa_todo():
    p = vs.plan_auditoria(_precalifs(), vs.MODO_PROFUNDA)
    assert p["n_revisar"] == 10 and p["n_auto"] == 0
    assert p["esfuerzo_pct"] == 100.0


def test_auditoria_media_marcados_mas_muestra():
    p = vs.plan_auditoria(_precalifs(), vs.MODO_MEDIA, muestra_cada=5)
    # 3 marcados + 1 de muestra (cada 5 de los 7 no marcados)
    assert p["n_revisar"] == 4
    assert p["n_auto"] == 6


def test_modo_masivo_aprobar():
    m = vs.modo_masivo_aprobar(_precalifs(), umbral_conf=0.9)
    assert m["n_auto"] == 7        # los de conf 0.95 no marcados
    assert m["n_pendientes"] == 3


def test_registro_aprobado_vs_ajustado():
    r1 = vs.registrar_validacion("r1", "C1", "logrado", 0.9, "logrado", "prof.caamano")
    r2 = vs.registrar_validacion("r2", "C2", "parcial", 0.6, "logrado", "prof.caamano",
                                 comentario="La analogía era válida")
    assert r1["accion"] == "aprobado"
    assert r2["accion"] == "ajustado" and r2["comentario"]


def test_acuerdo_qwk():
    regs = [
        {"nivel_ia": "logrado", "nivel_docente": "logrado", "accion": "aprobado"},
        {"nivel_ia": "parcial", "nivel_docente": "logrado", "accion": "ajustado"},
        {"nivel_ia": "no_logrado", "nivel_docente": "no_logrado", "accion": "aprobado"},
        {"nivel_ia": "logrado", "nivel_docente": "logrado", "accion": "aprobado"},
    ]
    a = vs.acuerdo_qwk(regs)
    assert 0.0 <= a["qwk"] <= 1.0
    assert a["ajustados"] == 1
    assert a["tasa_ajuste_pct"] == 25.0


def test_nota_final_del_docente():
    crit = [{"nivel_docente": "logrado", "peso": 0.4},
            {"nivel_docente": "logrado", "peso": 0.4},
            {"nivel_docente": "parcial", "peso": 0.2}]
    nf = vs.nota_final(crit, escala="chile_1_7", exigencia=60)
    # logro = 0.4 + 0.4 + 0.1 = 0.9 -> 90%
    assert nf["logro_pct"] == 90.0
    assert nf["aprobado"] is True and nf["responsable"] == "docente"


def test_trazabilidad_persistente():
    e = create_engine("sqlite://"); Base.metadata.create_all(e)
    with Session(e) as s:
        reg = RegistroValidacion(respuesta_ref="scan:x#item:3", criterio="Distensibilidad",
                                 nivel_ia="parcial", confianza_ia=0.6, nivel_docente="logrado",
                                 accion="ajustado", docente="prof.caamano")
        s.add(reg); s.commit(); s.refresh(reg)
        assert reg.created_at is not None       # sello temporal inmutable
        assert reg.accion == "ajustado"
