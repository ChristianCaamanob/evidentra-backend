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

from app.api.deps import get_db, req_profesor, req_investigador
from app.core.errors import not_found, conflict
from app.models.validacion import RegistroValidacion
from app.models.aprendizaje import RubricaVersion, AjusteCalibracion
from app.services import matriz_service
from app.services import validacion_service
from app.services import precalificacion_service
from app.services import coder_llm
from app.services import mfrm_service
from app.services import rubrica_psicometria_service
from app.services import aprendizaje_service

router = APIRouter(tags=["desarrollo"])
logger = logging.getLogger("evalys")


@router.post("/results/{scan_id}/validar", dependencies=[Depends(req_profesor)])
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


@router.post("/answer-key-items/{item_id}/precalificar", dependencies=[Depends(req_profesor)])
def precalificar(item_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """
    F2 - Pre-califica una respuesta de desarrollo criterio por criterio (la IA propone; la
    nota es del docente, G1). Devuelve el hash de la version de rubrica ACTIVA para que el
    docente lo fije al validar (pinning -> replicabilidad).

    payload = {respuesta}
    """
    try:
        criterios = matriz_service.cargar_criterios_item(db, item_id)
        if not criterios:
            raise conflict("El item no tiene criterios de rubrica definidos.")
        from app.models.answer_key import AnswerKeyItem, AnswerKey
        from app.models.assessment import Assessment
        from app.models.course import Course
        item = db.get(AnswerKeyItem, item_id)

        # Norma terminologica heredada del curso (para el modo estricto del LLM).
        ak = db.get(AnswerKey, item.answer_key_id)
        assessment = db.get(Assessment, ak.assessment_id) if ak else None
        course = db.get(Course, assessment.course_id) if assessment else None
        norma = getattr(course, "norma_terminologica", None) if course else None
        for c in criterios:
            c["norma_terminologica"] = norma

        coder = coder_llm.coder_por_defecto()      # LLM si hay API key; si no, grader determinista
        rep = precalificacion_service.precalificar_respuesta(
            payload.get("respuesta", ""), criterios, coder=coder, norma_terminologica=norma)
        rep["motor"] = "llm" if coder else "deterministico"
        rep["rubrica_version_hash"] = matriz_service.version_activa_hash(
            db, item.answer_key_id, criterios)
        return rep
    except Exception:
        logger.error(f"Error en precalificar {item_id}: {traceback.format_exc()}")
        raise


@router.get("/answer-keys/{ak_id}/rubrica/versiones", dependencies=[Depends(req_profesor)])
def listar_versiones(ak_id: UUID, db: Session = Depends(get_db)):
    """F4 - Historial de versiones de la rubrica (replicabilidad: cada corrida se clava a una)."""
    vers = (db.query(RubricaVersion)
            .filter(RubricaVersion.answer_key_id == str(ak_id))
            .order_by(RubricaVersion.version).all())
    return {"versiones": [{"version": v.version, "hash": v.hash, "parent_hash": v.parent_hash,
                           "estado": v.estado, "resumen": v.resumen, "autor": v.autor}
                          for v in vers]}


@router.post("/answer-keys/{ak_id}/rubrica/versiones/activar", dependencies=[Depends(req_profesor)])
def activar_version(ak_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """
    F4 - Aplica los ajustes APROBADOS por el docente y activa una version NUEVA de la rubrica
    (la anterior queda archivada e inmutable). El docente aprueba la regla (G1 extendido); si
    un ajuste relaja la norma disciplinar, exige justificacion (se rechaza si falta).

    payload = {autor, aprobados:[{criterio, tipo, payload?, recurrencia?, requiere_override?,
               justificacion?, aprobado_por?}]}
    """
    try:
        autor = payload.get("autor", "docente")
        criterios = matriz_service.cargar_criterios_rubrica(db, ak_id)
        actual = (db.query(RubricaVersion)
                  .filter(RubricaVersion.answer_key_id == str(ak_id))
                  .order_by(RubricaVersion.version.desc()).first())
        nueva = aprendizaje_service.aplicar_ajustes(
            criterios, payload.get("aprobados", []),
            version_actual=(actual.version if actual else 1), autor=autor)

        db.query(RubricaVersion).filter(
            RubricaVersion.answer_key_id == str(ak_id),
            RubricaVersion.estado == "activa").update({"estado": "archivada"})
        db.add(RubricaVersion(answer_key_id=str(ak_id), version=nueva["version"],
                              hash=nueva["hash"], parent_hash=nueva["parent_hash"],
                              estado="activa", resumen=nueva["resumen"], autor=autor))
        for ch in nueva["changelog"]:
            db.add(AjusteCalibracion(
                rubrica_version_hash=nueva["hash"], criterio=ch["criterio"], tipo=ch["tipo"],
                direccion=ch.get("direccion") or "sube", descripcion=ch["tipo"],
                recurrencia=ch.get("recurrencia") or 1,
                requiere_override=bool(ch.get("requiere_override")),
                justificacion=ch.get("justificacion"), estado="aprobado",
                aprobado_por=ch.get("aprobado_por") or autor))
        db.commit()
        return {"version": nueva["version"], "hash": nueva["hash"], "estado": "activa",
                "n_cambios": nueva["n_cambios"], "resumen": nueva["resumen"],
                "gobernanza": nueva["gobernanza"]}
    except ValueError as e:                    # relaja la norma sin justificacion (G1)
        raise conflict(str(e))
    except Exception:
        logger.error(f"Error en activar_version {ak_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/mfrm", dependencies=[Depends(req_investigador)])
def rubrica_mfrm(assessment_id: UUID, db: Session = Depends(get_db)):
    """I6 - Severidad del corrector IA vs docente (MFRM) sobre las validaciones persistidas."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return mfrm_service.reporte_severidad_ia(regs)
    except Exception:
        logger.error(f"Error en rubrica_mfrm {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/psicometria", dependencies=[Depends(req_investigador)])
def rubrica_psicometria(assessment_id: UUID, db: Session = Depends(get_db)):
    """R - Psicometria de la rubrica (estadigrafos por criterio, fiabilidad, categorias, G-theory)."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return rubrica_psicometria_service.analizar_rubrica(regs)
    except Exception:
        logger.error(f"Error en rubrica_psicometria {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/rubrica/aprendizaje", dependencies=[Depends(req_profesor)])
def rubrica_aprendizaje(assessment_id: UUID, db: Session = Depends(get_db)):
    """F4 - Propuestas de ajuste aprendidas del docente (solo propone; el docente aprueba, G1)."""
    try:
        regs = matriz_service.cargar_registros_validacion(db, assessment_id)
        return aprendizaje_service.ciclo_aprendizaje(regs)
    except Exception:
        logger.error(f"Error en rubrica_aprendizaje {assessment_id}: {traceback.format_exc()}")
        raise
