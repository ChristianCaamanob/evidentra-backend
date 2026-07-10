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

from fastapi import APIRouter, Depends, UploadFile, File
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


_persistir_validaciones = validacion_service.persistir_validaciones


@router.post("/results/{scan_id}/validar", dependencies=[Depends(req_profesor)])
def validar_desarrollo(scan_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """
    F3 (escrita) - Valida la respuesta de desarrollo de un ESCANEO. La nota es del docente (G1).

    payload = {docente, rubrica_version_hash?, criterios:[
                 {criterio, nivel_ia?, confianza_ia?, nivel_docente, comentario?}]}
    """
    try:
        scan = matriz_service.scan_repo.get(db, scan_id)
        if not scan:
            raise not_found("Escaneo no encontrado.")
        pseudo = matriz_service._pseudo(scan.id)
        registros, version_hash = _persistir_validaciones(db, pseudo, scan.assessment_id, payload)
        return {
            "sujeto": pseudo, "n_registrados": len(registros),
            "acuerdo": validacion_service.acuerdo_qwk(registros) if registros else {},
            "rubrica_version_hash": version_hash,
            "gobernanza": "Nota fijada por el docente (G1). Trazabilidad inmutable (G5). "
                          "Seudonimizado (G2).",
        }
    except KeyError as e:
        raise not_found(f"Falta el campo {e} en un criterio del payload.")
    except Exception:
        logger.error(f"Error en validar_desarrollo {scan_id}: {traceback.format_exc()}")
        raise


@router.post("/assessments/{assessment_id}/students/{student_id}/rubrica/validar",
             dependencies=[Depends(req_profesor)])
def validar_oral(assessment_id: UUID, student_id: UUID, payload: dict,
                 db: Session = Depends(get_db)):
    """
    F3 (oral) - Aplica la rubrica parametrizada DIRECTAMENTE a un estudiante (oral, presentacion,
    practica): no hay hoja/escaneo, el sujeto es el estudiante de la nomina. Misma trazabilidad
    y gobernanza que la escrita. La IA es opcional (el docente puede puntuar directo).
    """
    try:
        from app.models.student import Student
        from app.models.assessment import Assessment
        st = db.get(Student, student_id)
        if not st:
            raise not_found("Estudiante no encontrado.")
        a = db.get(Assessment, assessment_id)
        if not a:
            raise not_found("Evaluacion no encontrada.")
        if st.course_id != a.course_id:
            raise conflict("El estudiante no pertenece al curso de la evaluacion.")
        pseudo = matriz_service._pseudo(st.id)
        registros, version_hash = _persistir_validaciones(db, pseudo, assessment_id, payload)
        return {
            "sujeto": pseudo, "modalidad": "oral", "n_registrados": len(registros),
            "acuerdo": validacion_service.acuerdo_qwk(registros) if registros else {},
            "rubrica_version_hash": version_hash,
            "gobernanza": "Nota fijada por el docente (G1). Rubrica aplicada directo al estudiante. "
                          "Trazabilidad inmutable (G5). Seudonimizado (G2).",
        }
    except KeyError as e:
        raise not_found(f"Falta el campo {e} en un criterio del payload.")
    except Exception:
        logger.error(f"Error en validar_oral {assessment_id}/{student_id}: {traceback.format_exc()}")
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
        # Motor REAL: 'llm' solo si el modelo respondió; si cayó al determinista lo decimos.
        est = getattr(coder, "estado", None) if coder else None
        if coder is None:
            rep["motor"] = "deterministico"
        elif est and est["llm_ok"] > 0 and est["fallback"] == 0:
            rep["motor"] = "llm"
        elif est and est["llm_ok"] > 0:
            rep["motor"] = "mixto"
        else:
            rep["motor"] = "llm_fallback_deterministico"
            if est and est.get("ultimo_error"):
                rep["motor_detalle"] = est["ultimo_error"]
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


@router.post("/answer-key-items/{item_id}/rubrica/importar", dependencies=[Depends(req_profesor)])
async def importar_rubrica(item_id: UUID, file: UploadFile = File(...), confirmar: bool = False,
                           db: Session = Depends(get_db)):
    """
    Importa una rubrica desde .xlsx a un item. Sin `confirmar` devuelve solo el PREVIEW (no
    escribe); con `confirmar=true` crea los criterios en el item. El parseo es heuristico: el
    docente revisa y confirma (G1).
    """
    try:
        from app.services import rubrica_import_service
        from app.models.answer_key import AnswerKeyItem, RubricCriterion
        preview = rubrica_import_service.parse_rubrica_xlsx(await file.read())
        if not confirmar:
            return {"guardado": False, **preview}
        item = db.get(AnswerKeyItem, item_id)
        if not item:
            raise not_found("Item de pauta no encontrado.")
        for i, c in enumerate(preview["criterios"]):
            db.add(RubricCriterion(
                answer_key_item_id=item_id, name=c["name"][:255], weight=c["weight"],
                order=i, niveles_json=c["niveles"], ambito=c["ambito"],
                seccion=(c["seccion"][:120] if c["seccion"] else None)))
        db.commit()
        return {"guardado": True, "criterios_creados": len(preview["criterios"]), **preview}
    except Exception:
        logger.error(f"Error en importar_rubrica {item_id}: {traceback.format_exc()}")
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
