"""
Router del modulo Investigador (Fase 1 del cableado): expone la psicometria agregada de
una evaluacion. Solo lectura, seudonimizado (G2), no altera notas (G1).

Fase 1 (datos de seleccion multiple, disponibles hoy):
  - GET /assessments/{id}/psicometria/rasch          -> I1 (irt_service)
  - GET /assessments/{id}/psicometria/dimensionalidad -> I7 (dimensionalidad_service)

Los endpoints sobre rubrica (PCM, R, MFRM) y los con grupo (DIF, invarianza) llegan en las
fases 2 y 3, junto con los datos y decisiones que consumen.
"""
import logging
import traceback
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi import Depends as _Dep
from app.api.deps import get_db, req_investigador
from app.services import matriz_service
from app.services import irt_service
from app.services import dimensionalidad_service
from app.services import dina_service
from app.services import dif_service
from app.services import invarianza_service
from app.services import estadistica_service
from app.services import efectos_service

# Todo el modulo Investigador exige rol investigador (o creador). El director NO accede a
# este modulo de investigacion; su alcance es ver/exportar datos de estudiante y profesor.
router = APIRouter(prefix="/assessments", tags=["investigador"],
                   dependencies=[_Dep(req_investigador)])
logger = logging.getLogger("evalys")


def _meta(datos: dict) -> dict:
    return {"n_personas": datos["n_personas"], "n_items": datos["n_items"],
            "omitidas_pct": datos["omitidas_pct"],
            "gobernanza": "Analisis agregado y seudonimizado (G2); no altera notas (G1)."}


@router.get("/{assessment_id}/psicometria/rasch")
def psicometria_rasch(assessment_id: UUID, db: Session = Depends(get_db)):
    """I1 - Modelo de Rasch (dificultad, habilidad, ajuste, informacion, fiabilidad)."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = irt_service.estimar_rasch(datos["X"])
        for it, num in zip(rep["items"], datos["items"]):
            it["pregunta"] = num                       # numero real de pregunta (no indice)
        rep["_meta"] = _meta(datos)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_rasch {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estadistica/clasica")
def estadistica_clasica(assessment_id: UUID, db: Session = Depends(get_db)):
    """Fases 1-2 del pipeline: depuracion de datos (descriptivos, supuestos, perdidos) y
    analisis de items en Teoria Clasica (dificultad, discriminacion, fiabilidad: alfa, omega,
    SEM, Guttman). Numera los items con su pregunta real."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = estadistica_service.reporte_completo(datos["X"])
        nums = datos["items"]
        for bloque in (rep["descriptivos"]["items"], rep["items_tct"]["items"],
                       rep["datos_perdidos"]["por_item"]):
            for it, num in zip(bloque, nums):
                it["pregunta"] = num
        rep["_meta"] = _meta(datos)
        return rep
    except Exception:
        logger.error(f"Error en estadistica_clasica {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dimensionalidad")
def psicometria_dimensionalidad(assessment_id: UUID, db: Session = Depends(get_db)):
    """I7 - Dimensionalidad (KMO, Bartlett, analisis paralelo, EFA) + fiabilidad ampliada."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = dimensionalidad_service.analizar_dimensionalidad(datos["X"], dicotomico=True)
        rep["_meta"] = _meta(datos)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dimensionalidad {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dina")
def psicometria_dina(assessment_id: UUID, base: str = Query("ra", pattern="^(ra|bloom)$"),
                     db: Session = Depends(get_db)):
    """I9 - Diagnostico cognitivo (DINA). La Q-matrix se deriva del etiquetado C3: cada
    item carga en su RA (base=ra) o nivel Bloom (base=bloom)."""
    try:
        d = matriz_service.cargar_dina(db, assessment_id, base=base)
        rep = dina_service.estimar_dina(d["X"], d["Q"], atributos=d["atributos"])
        for it, num in zip(rep["items"], d["items"]):
            it["pregunta"] = num                       # numero real de pregunta
        rep["_meta"] = {"n_personas": d["n_personas"], "n_items": len(d["items"]),
                        "base_atributos": base,
                        "gobernanza": "Diagnostico agregado y seudonimizado (G2); orienta "
                                      "remediacion, no altera notas (G1). Q-matrix derivada de C3."}
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dina {assessment_id}: {traceback.format_exc()}")
        raise


def _meta_equidad(d: dict) -> dict:
    return {"variable": d["variable"], "comparados": d["categorias_comparadas"],
            "categorias_omitidas": d["categorias_omitidas"], "n": d["n"],
            "excluidos_sin_consentimiento": d["excluidos_sin_consentimiento"],
            "gobernanza": "Solo estudiantes que CONSINTIERON el analisis de equidad (G4); "
                          "datos seudonimizados (G2); grupos con minimo para evitar "
                          "reidentificacion. No altera notas (G1)."}


@router.get("/{assessment_id}/efectos")
def efectos_grupo(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                  db: Session = Depends(get_db)):
    """Fase 7 - Comparacion del puntaje total entre 2 grupos consentidos: t de Welch,
    Mann-Whitney, tamanos de efecto (d de Cohen, g de Hedges) con IC95%, y resumen de
    correlaciones inter-item. Reusa las salvaguardas de equidad (consentimiento, minimo por grupo)."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        X = np.asarray(d["X"], dtype=float)
        total = np.nansum(X, axis=1)
        rep = efectos_service.comparar_grupos(total, d["grupo"], d.get("referencia"), d.get("focal"))
        rep["correlaciones"] = efectos_service.correlaciones_resumen(X)
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en efectos_grupo {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dif")
def psicometria_dif(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                    db: Session = Depends(get_db)):
    """I2 - DIF (Mantel-Haenszel + logistica) entre 2 grupos consentidos. Equidad del item."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        X = np.asarray(d["X"], dtype=float)
        matching = np.nansum(X, axis=1)                # puntaje total como variable de igualacion
        rep = dif_service.analizar_dif(X, d["grupo"], matching, etiqueta_focal=d["focal"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dif {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/invarianza")
def psicometria_invarianza(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                           db: Session = Depends(get_db)):
    """I8b - Invarianza de medicion de Rasch entre 2 grupos consentidos."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        rep = invarianza_service.invarianza_rasch(np.asarray(d["X"], dtype=float), d["grupo"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_invarianza {assessment_id}: {traceback.format_exc()}")
        raise
