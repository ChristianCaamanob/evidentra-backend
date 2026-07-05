"""
Router del motor de desarrollo (Fase 2 del cableado): validacion docente (F3) que persiste
la trazabilidad, y los analisis de rubrica que la consumen (R, MFRM) mas las propuestas de
aprendizaje (F4).

  POST /results/{scan_id}/validar                 -> F3: persiste RegistroValidacion (G1, G5)
  GET  /assessments/{id}/rubrica/mfrm             -> I6: severidad IA vs docente
  GET  /assessments/{id}/rubrica/psicometria      -> R:  psicometria de la rubrica + G-theory
  GET  /assessments/{id}/rubrica/aprendizaje      -> F4: propuestas de ajuste (solo propone)

La nota final es del docente (G1); cada decision queda con sello temporal inmutable (G5);
los datos se agregan seudonimizados (G2).
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import not_found
from app.models.validacion import RegistroValidacion
from app.services import matriz_service
from app.services import validacion_service
from app.services import mfrm_service
from app.services import rubrica_psicometria_service
from app.services import aprendizaje_service

router = APIRouter(tags=["desarrollo"])
logger = logging.getLogger("evalys")


@router.post("/results/{scan_id}/validar")
def validar_desarrollo(scan_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """
    F3 - Registra la validacion docente de una respuesta de desarrollo. Persiste un
    RegistroValidacion por criterio (trazabilidad inmutable, G5). La nota es del docente (G1).

    payload = {docente, rubrica_version_hash?, criterios:[
                 {criterio, nivel_ia, confianza_ia, nivel_docente, comentario?}]}
    """
    try:
        scan = matriz_service.scan_repo.get(db, scan_id)
        if not scan:
            raise not_found("Escaneo no encontrado.")
        docente = payload.get("docente") or "docente"
        version_hash = payload.get("rubrica_version_hash")
        pseudo = matriz_service._pseudo(scan.id)
        registros = []
        for c in payload.get("criterios", []):
            reg = validacion_service.registrar_validacion(
                ref=f"{pseudo}#{c['criterio']}", criterio=c["criterio"],
                nivel_ia=c["nivel_ia"], confianza=c.get("confianza_ia", 0.0),
                nivel_docente=c["nivel_docente"], docente=docente,
                comentario=c.get("comentario"))
            db.add(RegistroValidacion(
                respuesta_ref=reg["respuesta_ref"], criterio=reg["criterio"],
                nivel_ia=reg["nivel_ia"], confianza_ia=reg["confianza_ia"],
                nivel_docente=reg["nivel_docente"], accion=reg["accion"],
                comentario=reg["comentario"], docente=reg["docente"],
                assessment_id=str(scan.assessment_id), rubrica_version_hash=version_hash))
            registros.append(reg)
        db.commit()
        return {
            "scan": pseudo, "n_registrados": len(registros),
            "acuerdo": validacion_service.acuerdo_qwk(registros) if registros else {},
            "rubrica_version_hash": version_hash,
            "gobernanza": "Nota fijada por el docente (G1, indelegable). Trazabilidad "
                          "inmutable con sello temporal (G5). Seudonimizado (G2).",
        }
    except KeyError as e:
        raise not_found(f"Falta el campo {e} en un criterio del payload.")
    except Exception:
        logger.error(f"Error en validar_desarrollo {scan_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/mfrm")
def rubrica_mfrm(assessment_id: UUID, db: Session = Depends(get_db)):
    """I6 - Severidad del corrector IA vs docente (MFRM) sobre las validaciones persistidas."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return mfrm_service.reporte_severidad_ia(regs)
    except Exception:
        logger.error(f"Error en rubrica_mfrm {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/psicometria")
def rubrica_psicometria(assessment_id: UUID, db: Session = Depends(get_db)):
    """R - Psicometria de la rubrica (estadigrafos por criterio, fiabilidad, categorias, G-theory)."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return rubrica_psicometria_service.analizar_rubrica(regs)
    except Exception:
        logger.error(f"Error en rubrica_psicometria {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/aprendizaje")
def rubrica_aprendizaje(assessment_id: UUID, db: Session = Depends(get_db)):
    """F4 - Propuestas de ajuste aprendidas del docente (solo propone; el docente aprueba, G1)."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return aprendizaje_service.ciclo_aprendizaje(regs)
    except Exception:
        logger.error(f"Error en rubrica_aprendizaje {assessment_id}: {traceback.format_exc()}")
        raise
