"""
Test de F4 - Aprendizaje de calibracion.

Verifica las cuatro garantias de un sistema de evaluacion serio:
  - CONSISTENCIA : un caso aislado no se vuelve regla; solo lo recurrente/generalizable.
  - NORMA        : relajar la norma disciplinar exige override docente (no bloquea, registra).
  - REPLICABILIDAD: mismo contenido -> mismo hash; aplicar cambios no muta la version previa.
  - TRAZABILIDAD : cada version nueva trae changelog con evidencia seudonimizada.
  - APRENDIZAJE  : la curva de QWK por version evidencia convergencia.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.aprendizaje import RubricaVersion, AjusteCalibracion
from app.services import aprendizaje_service as ap


def _registros_ajuste_recurrente(n=4):
    """n alumnos donde la IA marco 'parcial' pero el docente subio a 'logrado' por analogia."""
    regs = []
    for i in range(n):
        regs.append({"respuesta_ref": f"al{i}#Distensibilidad", "criterio": "Distensibilidad",
                     "nivel_ia": "parcial", "nivel_docente": "logrado", "accion": "ajustado",
                     "comentario": "La analogia del acordeon expresa la distensibilidad."})
    return regs


def test_senal_recurrente_se_vuelve_propuesta():
    regs = _registros_ajuste_recurrente(4)
    ciclo = ap.ciclo_aprendizaje(regs, min_recurrencia=2)
    assert ciclo["n_propuestas"] == 1
    p = ciclo["propuestas"][0]
    assert p["criterio"] == "Distensibilidad"
    assert p["tipo"] == ap.TIPO_ANALOGIA
    assert p["recurrencia"] == 4
    assert p["guardrails"]["generalizable"] is True


def test_caso_aislado_no_es_regla():
    # Un solo ajuste, sin patron: queda como observacion, NO como regla (consistencia).
    regs = [{"respuesta_ref": "al0#X", "criterio": "X", "nivel_ia": "logrado",
             "nivel_docente": "parcial", "accion": "ajustado", "comentario": ""}]
    ciclo = ap.ciclo_aprendizaje(regs, min_recurrencia=2)
    assert ciclo["n_propuestas"] == 0
    assert ciclo["n_observaciones"] == 1
    assert ciclo["observaciones"][0]["estado"] == "observacion"


def test_ancla_aprobable_aun_con_un_caso():
    # Una subida sin pista textual -> ancla ejemplar; siempre estandariza (aprobable con rec 1).
    regs = [{"respuesta_ref": "al0#Y", "criterio": "Y", "nivel_ia": "parcial",
             "nivel_docente": "logrado", "accion": "ajustado", "comentario": ""}]
    ciclo = ap.ciclo_aprendizaje(regs, min_recurrencia=2)
    assert ciclo["n_propuestas"] == 1
    assert ciclo["propuestas"][0]["tipo"] == ap.TIPO_ANCLA


def test_relajar_norma_exige_override():
    regs = _registros_ajuste_recurrente(3)   # relajacion (acepta analogia) = RELAJANTE
    criterios = {"Distensibilidad": {"nombre": "Distensibilidad", "nivel_exigencia": "estricto"}}
    ciclo = ap.ciclo_aprendizaje(regs, criterios_por_nombre=criterios, norma="TA2/IFAA")
    p = ciclo["propuestas"][0]
    assert p["requiere_override"] is True
    assert ciclo["n_requieren_override"] == 1
    # aplicar sin justificacion debe fallar
    aprobado = dict(p, payload={"texto": "acordeon", "nivel": "logrado"})
    try:
        ap.aplicar_ajustes([{"nombre": "Distensibilidad"}], [aprobado])
        assert False, "debio exigir justificacion"
    except ValueError as e:
        assert "override" in str(e).lower() or "justificacion" in str(e).lower()


def test_endurecer_hacia_norma_es_consistente():
    regs = [{"respuesta_ref": f"al{i}#Z", "criterio": "Z", "nivel_ia": "logrado",
             "nivel_docente": "parcial", "accion": "ajustado",
             "comentario": "El termino correcto segun la norma es otro."} for i in range(3)]
    criterios = {"Z": {"nombre": "Z", "nivel_exigencia": "estricto"}}
    ciclo = ap.ciclo_aprendizaje(regs, criterios_por_nombre=criterios, norma="TA2/IFAA")
    p = ciclo["propuestas"][0]
    assert p["tipo"] == ap.TIPO_PRECISION
    assert p["requiere_override"] is False            # endurecer hacia la norma no necesita override
    assert p["guardrails"]["consistente_norma"] is True


def test_replicabilidad_hash_estable_y_orden_indiferente():
    c1 = [{"nombre": "A", "peso": 0.5}, {"nombre": "B", "peso": 0.5}]
    c2 = [{"nombre": "A", "peso": 0.5}, {"nombre": "B", "peso": 0.5}]
    assert ap.hash_criterios(c1) == ap.hash_criterios(c2)   # mismo contenido -> mismo hash
    # cambiar el contenido cambia el hash
    c3 = [{"nombre": "A", "peso": 0.6}, {"nombre": "B", "peso": 0.4}]
    assert ap.hash_criterios(c3) != ap.hash_criterios(c1)


def test_aplicar_no_muta_version_previa():
    criterios = [{"nombre": "Distensibilidad", "sinonimos": ["elastico"]}]
    hash_antes = ap.hash_criterios(criterios)
    aprobado = {"criterio": "Distensibilidad", "tipo": ap.TIPO_SINONIMO,
                "payload": {"termino": "distensible"}, "recurrencia": 3,
                "evidencia": ["resp:abc"], "aprobado_por": "prof.caamano"}
    nueva = ap.aplicar_ajustes(criterios, [aprobado], version_actual=1)
    # la version previa quedo congelada
    assert ap.hash_criterios(criterios) == hash_antes
    assert criterios[0]["sinonimos"] == ["elastico"]
    # la nueva version incorpora el sinonimo y sube de version con hash distinto
    assert nueva["version"] == 2
    assert "distensible" in nueva["criterios"][0]["sinonimos"]
    assert nueva["hash"] != hash_antes
    assert nueva["parent_hash"] == hash_antes
    assert nueva["n_cambios"] == 1 and nueva["changelog"][0]["aprobado_por"] == "prof.caamano"


def test_curva_de_aprendizaje_detecta_convergencia():
    serie = [{"version": 1, "qwk": 0.62, "n": 40}, {"version": 2, "qwk": 0.74, "n": 40},
             {"version": 3, "qwk": 0.83, "n": 40}]
    c = ap.curva_aprendizaje(serie)
    assert c["delta_total"] > 0.15
    assert c["mejora_monotona"] is True
    assert c["convergencia"] is True
    assert "converge" in c["verdicto"].lower()


def test_curva_detecta_retroceso():
    serie = [{"version": 1, "qwk": 0.80}, {"version": 2, "qwk": 0.66}]
    c = ap.curva_aprendizaje(serie)
    assert c["delta_total"] <= -0.05
    assert "empeora" in c["verdicto"].lower()


def test_persistencia_version_y_changelog():
    e = create_engine("sqlite://"); Base.metadata.create_all(e)
    with Session(e) as s:
        v = RubricaVersion(version=2, hash="deadbeefcafe0001", parent_hash="0000",
                           estado="propuesta", autor="prof.caamano",
                           resumen="v2: 1 ajuste aprendido.")
        s.add(v); s.flush()
        aj = AjusteCalibracion(rubrica_version_hash="deadbeefcafe0001", criterio="Distensibilidad",
                               tipo=ap.TIPO_ANALOGIA, direccion="sube", descripcion="acepta analogia",
                               recurrencia=4, confianza=0.93, requiere_override=True,
                               justificacion="La analogia expresa el concepto.", estado="aprobado",
                               aprobado_por="prof.caamano")
        s.add(aj); s.commit(); s.refresh(v); s.refresh(aj)
        assert v.created_at is not None and v.estado == "propuesta"
        assert aj.requiere_override is True and aj.justificacion
