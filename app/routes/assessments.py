from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.api.deps import get_db, req_profesor
from app.schemas.assessment import (
    ActivateAssessmentOut,
    AssessmentOut,
    AssessmentReadinessOut,
    AttachAssessmentDocumentIn,
)
from app.services import assessment_service
from app.services import result_service
from app.services import briefing_service
from app.services import curso_stats_service
from app.services import matriz_service
from app.services.sheet_service import generate_answer_sheet_pdf

router = APIRouter(prefix="/assessments", tags=["assessments"])


@router.get("/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment(db, assessment_id)


@router.get("/{assessment_id}/readiness", response_model=AssessmentReadinessOut)
def get_assessment_readiness(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.get_assessment_readiness(db, assessment_id)


@router.post("/{assessment_id}/attach-document", response_model=AssessmentReadinessOut,
             dependencies=[Depends(req_profesor)])
def attach_document(
    assessment_id: UUID,
    payload: AttachAssessmentDocumentIn,
    db: Session = Depends(get_db),
):
    return assessment_service.attach_document(db, assessment_id, payload.assessment_document_url)


@router.post("/{assessment_id}/activate", response_model=ActivateAssessmentOut,
             dependencies=[Depends(req_profesor)])
def activate_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    return assessment_service.activate_assessment(db, assessment_id)


@router.get("/{assessment_id}/generate-sheet")
def generate_sheet(
    assessment_id: UUID,
    version: str = Query(default="A", description="Versión de la hoja: A o B"),
    n_questions: int = Query(default=0, description="N° de preguntas. 0 = usar el configurado en la evaluación"),
    db: Session = Depends(get_db),
):
    """
    Genera y devuelve la hoja de respuesta PDF para una evaluación.
    El docente puede elegir la versión (A o B) y el número de preguntas.
    """
    assessment = assessment_service.get_assessment(db, assessment_id)
    course = assessment.course

    # Usar el n_questions del query param si viene, sino el del modelo
    nq = n_questions if n_questions > 0 else getattr(assessment, 'n_questions', 40)
    # Asegurar que sea par para las dos columnas
    if nq % 2 != 0:
        nq += 1

    pdf_bytes = generate_answer_sheet_pdf(
        assessment_id=str(assessment_id),
        course_id=str(assessment.course_id),
        course_name=course.name,
        assessment_name=assessment.name,
        n_questions=nq,
        version=version.upper(),
        date="2026",
        scale_min=1.0,
        scale_max=7.0,
        passing=4.0,
        threshold_pct=getattr(course, 'passing_threshold', 60),
    )

    filename = f"Evidentra_{assessment.name.replace(' ', '_')}_Ver{version.upper()}_{nq}P.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



from pydantic import BaseModel as _BaseModel

class AssessmentIn(_BaseModel):
    name: str
    course_id: str
    n_questions: int = 40
    versions: str = "A"
    grading_scale: str = "chile_1_7"
    passing_threshold: float = 60.0
    # Paso 0: modalidad elegida al crear (alternativas | desarrollo | mixta | oral).
    modalidad: str = "alternativas"
    # Solo desarrollo/mixta: cuántas preguntas de desarrollo sembrar (peso por puntaje).
    n_desarrollo: int = 0
    # Opt-in: en escalas de bandas, mover los cortes con la exigencia (curva la evaluación).
    bandas_moviles: bool = False

@router.get("/by-course/{course_id}")
def list_assessments(course_id: UUID, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment, modalidad_norm
    from app.models.answer_key import AnswerKey
    assessments = db.query(Assessment).filter(Assessment.course_id == course_id).order_by(Assessment.created_at.desc()).all()
    result = []
    for a in assessments:
        ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == a.id).first()
        result.append({
            "id": str(a.id),
            "name": a.name,
            "status": a.status,
            "n_questions": a.version_count or 40,
            "has_answer_key": ak is not None,
            "answer_key_valid": ak.is_valid if ak else False,
            "modalidad": modalidad_norm(a.modalidad),
            "created_at": str(a.created_at)[:10] if a.created_at else None,
        })
    return result

@router.post("/", dependencies=[Depends(req_profesor)])
def create_assessment(payload: AssessmentIn, db: Session = Depends(get_db)):
    import uuid as _uuid
    from app.models.assessment import Assessment, MODALIDADES, MODALIDAD_ALTERNATIVAS, modalidad_norm
    from app.models.answer_key import (
        AnswerKey, AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE,
    )
    modalidad = modalidad_norm(payload.modalidad)
    if modalidad not in MODALIDADES:
        modalidad = MODALIDAD_ALTERNATIVAS
    # Modalidades que corrigen por RÚBRICA (ítems open_response): desarrollo, mixta y oral.
    es_desarrollo = modalidad in ("desarrollo", "mixta", "oral")
    # En desarrollo puro, n_questions describe las preguntas de desarrollo (no la grilla OCR).
    a = Assessment(
        course_id=_uuid.UUID(payload.course_id),
        name=payload.name,
        status="draft",
        modalidad=modalidad,
        bandas_moviles=bool(payload.bandas_moviles),
        has_versions=len(payload.versions) > 1,
        version_count=payload.n_questions,
        n_questions=payload.n_questions,
        has_answer_key=False,
        briefing_level="initial",
        grading_scale=payload.grading_scale,
        passing_threshold=payload.passing_threshold,
    )
    db.add(a)
    db.flush()
    ak = AnswerKey(
        assessment_id=a.id,
        status="draft",
        is_valid=False,
        version_coverage_ok=True,
        annulled_items_count=0,
        invalid_weight_count=0,
        invalid_partial_rule_count=0,
    )
    db.add(ak)
    db.flush()
    # Desarrollo/mixta: sembrar preguntas abiertas iniciales para que el gestor no arranque vacío
    # y para que el flujo (inferencia por question_type) reconozca la modalidad de inmediato.
    n_seed = 0
    if es_desarrollo:
        if modalidad == "oral":
            n_seed = 1                       # una tarea oral; sus criterios se definen en la rúbrica
        elif payload.n_desarrollo > 0:
            n_seed = payload.n_desarrollo
        else:
            n_seed = payload.n_questions if modalidad == "desarrollo" else 1
        n_seed = max(1, min(n_seed, 40))
        for i in range(1, n_seed + 1):
            db.add(AnswerKeyItem(
                answer_key_id=ak.id, question_number=i, version="A",
                correct_answer="", weight=10.0, is_annulled=False,
                question_type=QUESTION_TYPE_OPEN_RESPONSE, enunciado=None,
            ))
    db.commit()
    db.refresh(a)
    return {"id": str(a.id), "name": a.name, "course_id": str(a.course_id),
            "status": a.status, "n_questions": payload.n_questions,
            "modalidad": a.modalidad, "n_desarrollo": n_seed}


@router.delete("/{assessment_id}", dependencies=[Depends(req_profesor)])
def delete_assessment(assessment_id: UUID, db: Session = Depends(get_db)):
    """Elimina una evaluación y todo lo que cuelga de ella (pauta, ítems, escaneos,
    grupos, sesiones en vivo, registros de validación). Acción del docente (G1)."""
    from app.models.assessment import Assessment
    a = db.get(Assessment, assessment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    aid_str = str(assessment_id)
    # Dependencias que no están en una cascada ORM: se borran defensivamente por si el
    # modelo no existe en algún entorno (additivo/tolerante).
    def _wipe(import_path, model_name, *filters):
        try:
            mod = __import__(import_path, fromlist=[model_name])
            Model = getattr(mod, model_name)
            q = db.query(Model)
            for f in filters:
                q = q.filter(f(Model))
            q.delete(synchronize_session=False)
        except Exception as _e:  # noqa: BLE001
            import logging
            logging.getLogger("evalys").warning("delete_assessment: no se pudo limpiar %s: %s", model_name, _e)
    _wipe("app.models.validacion", "RegistroValidacion", lambda M: M.assessment_id == aid_str)
    _wipe("app.models.scan", "Scan", lambda M: M.assessment_id == assessment_id)
    _wipe("app.models.en_vivo", "SesionEnVivo", lambda M: M.assessment_id == aid_str)
    _wipe("app.models.grupo", "Grupo", lambda M: M.assessment_id == aid_str)
    # answer_key + items + criterios + anclas caen por cascada ORM al borrar el assessment
    db.delete(a)
    db.commit()
    return {"deleted": True, "id": aid_str}


@router.get("/{assessment_id}/oral/estudiantes")
def oral_estudiantes(assessment_id: UUID, db: Session = Depends(get_db)):
    """Progreso de una evaluación ORAL: cada estudiante de la nómina con su estado
    (calificado o no) y su nota, calculada directo desde sus registros de validación
    y la rúbrica (independiente del libro de notas, robusto sobre nóminas grandes)."""
    from app.models.assessment import Assessment, modalidad_norm
    from app.models.student import Student
    from app.models.validacion import RegistroValidacion
    from app.models.answer_key import AnswerKey, AnswerKeyItem, RubricCriterion, QUESTION_TYPE_OPEN_RESPONSE
    from app.models.grupo import Grupo
    from app.services import matriz_service
    from app.services.rubrica_escala_service import fraccion_logro
    from app.services.result_service import calculate_grade
    a = db.get(Assessment, assessment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    escala = a.grading_scale or "chile_1_7"
    exigencia = a.passing_threshold if a.passing_threshold is not None else 60.0
    # Criterios de la rúbrica oral (nombre, peso, niveles_json, ámbito) desde los ítems abiertos.
    criterios = []
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if ak:
        for it in db.query(AnswerKeyItem).filter(
                AnswerKeyItem.answer_key_id == ak.id,
                AnswerKeyItem.question_type == QUESTION_TYPE_OPEN_RESPONSE).all():
            for c in db.query(RubricCriterion).filter(RubricCriterion.answer_key_item_id == it.id).all():
                criterios.append((c.name, c.weight or 1.0, c.niveles_json, c.ambito or "individual"))
    peso_total = sum(w for _, w, _, _ in criterios) or 1.0
    hay_grupal = any(amb == "grupal" for _, _, _, amb in criterios)
    # Registros por seudónimo (incluye seudónimos de estudiante Y de grupo).
    por_pseudo: dict[str, dict] = {}
    for r in db.query(RegistroValidacion).filter(
            RegistroValidacion.assessment_id == str(assessment_id)).all():
        pseudo = str(r.respuesta_ref).split("#")[0]
        por_pseudo.setdefault(pseudo, {})[r.criterio] = r.nivel_docente
    # Grupo de cada estudiante -> seudónimo del grupo (fuente de los criterios grupales).
    grupo_por_est: dict[str, tuple] = {}   # student_id -> (grupo_pseudo, grupo_nombre)
    for g in db.query(Grupo).filter(Grupo.assessment_id == str(assessment_id)).all():
        gp = matriz_service._pseudo(g.id)
        for integ in g.integrantes:
            grupo_por_est[integ.student_id] = (gp, g.nombre)
    students = db.query(Student).filter(Student.course_id == a.course_id).all()
    filas = []
    for st in students:
        p = matriz_service._pseudo(st.id)
        sv_ind = por_pseudo.get(p, {})
        gp_info = grupo_por_est.get(str(st.id))
        sv_grp = por_pseudo.get(gp_info[0], {}) if gp_info else {}
        nombre = (" ".join(x for x in [st.nombres, st.apellido_paterno, st.apellido_materno] if x)).strip() or st.rut
        acc = 0.0
        resueltos = 0
        for cn, w, niv, amb in criterios:
            fuente = sv_grp if amb == "grupal" else sv_ind
            if cn in fuente:
                acc += fraccion_logro(niv, fuente[cn]) * w
                resueltos += 1
        completo = (len(criterios) > 0 and resueltos == len(criterios))
        nota = logro_pct = etiqueta = aprobado = None
        if resueltos > 0:
            logro_pct = round(acc / peso_total * 100, 1)   # criterios sin resolver cuentan 0
            nota, etiqueta, aprobado = calculate_grade(
                logro_pct, escala, exigencia, banda_movil=bool(getattr(a, "bandas_moviles", False)))
            nota = round(nota, 1)
        filas.append({
            "student_id": str(st.id), "nombre": nombre, "rut": st.rut,
            "calificado": completo, "parcial": (resueltos > 0 and not completo),
            "grupo": gp_info[1] if gp_info else None,
            "nota": nota if completo else None, "etiqueta": etiqueta if completo else None,
            "aprobado": aprobado if completo else None,
            "logro_pct": logro_pct if completo else None,
        })
    return {"modalidad": modalidad_norm(a.modalidad), "n": len(filas),
            "n_calificados": sum(1 for f in filas if f["calificado"]),
            "hay_grupal": hay_grupal,
            "criterios": [{"name": cn, "weight": w, "ambito": amb} for cn, w, niv, amb in criterios],
            "estudiantes": filas}


@router.get("/{assessment_id}/config")
def get_assessment_config(assessment_id: UUID, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment, modalidad_norm
    from app.services.result_service import listar_escalas
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    return {
        "id": str(a.id),
        "name": a.name,
        "n_questions": a.n_questions or a.version_count or 40,
        "grading_scale": a.grading_scale or "chile_1_7",
        "passing_threshold": a.passing_threshold or 60.0,
        "status": a.status,
        "modalidad": modalidad_norm(a.modalidad),
        "bandas_moviles": bool(getattr(a, "bandas_moviles", False)),
        "course_id": str(a.course_id),
        "available_scales": listar_escalas(),
    }

@router.patch("/{assessment_id}/config", dependencies=[Depends(req_profesor)])
def update_assessment_config(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    from app.models.assessment import Assessment
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada")
    if "grading_scale" in payload:
        a.grading_scale = payload["grading_scale"]
    if "passing_threshold" in payload:
        a.passing_threshold = float(payload["passing_threshold"])
    if "name" in payload:
        a.name = payload["name"]
    if "n_questions" in payload:
        a.n_questions = int(payload["n_questions"])
        a.version_count = int(payload["n_questions"])
    if "bandas_moviles" in payload:
        a.bandas_moviles = bool(payload["bandas_moviles"])
    db.commit()
    db.refresh(a)
    return {"id": str(a.id), "name": a.name, "grading_scale": a.grading_scale,
            "passing_threshold": a.passing_threshold,
            "bandas_moviles": bool(getattr(a, "bandas_moviles", False))}


@router.get("/grading-scales/list")
def list_grading_scales():
    from app.services.result_service import listar_escalas
    return listar_escalas()


@router.get("/{assessment_id}/results")
def list_assessment_results(assessment_id: UUID, db: Session = Depends(get_db)):
    return result_service.list_results_for_assessment(db, assessment_id)


@router.get("/{assessment_id}/briefing")
def briefing_del_curso(assessment_id: UUID, db: Session = Depends(get_db)):
    """Briefing del CURSO para el docente (IA sobre resultados REALES): panorama, focos de
    reenseñanza priorizados por RA/ítems con brecha y acciones. No inventa cifras."""
    import traceback, logging
    logger = logging.getLogger("evalys")
    try:
        res = result_service.list_results_for_assessment(db, assessment_id)
        rows = res.get("results", [])
        pcts = sorted(r["percentage"] for r in rows if r.get("percentage") is not None)
        n = len(pcts)
        promedio = round(sum(pcts) / n, 1) if n else None
        mediana = pcts[n // 2] if n else None
        aprob = sum(1 for r in rows if r.get("pass_status") == "approved")
        aprob_pct = round(aprob / len(rows) * 100, 1) if rows else None
        items_dificiles, brechas_ra = [], []
        try:
            d = matriz_service.cargar_respuestas_letras(db, assessment_id)
            ia = curso_stats_service.analizar_evaluacion(
                d["respuestas_alumnos"], d["pauta"], te_tags=d.get("te_tags"))
            items = sorted(ia.get("items", []), key=lambda x: x.get("dificultad_p", 1))
            for it in items[:8]:
                items_dificiles.append("P" + str(it["item"]) + " ("
                                       + str(round(it.get("dificultad_p", 0) * 100)) + "% acierto)")
            for g in (ia.get("por_ra") or []):
                if g.get("clave") and g["clave"] != "sin_clasificar" and g.get("logro_promedio", 100) < 60:
                    brechas_ra.append(str(g["clave"]) + " (" + str(g["logro_promedio"]) + "%)")
        except Exception:
            pass
        rep = briefing_service.briefing_curso(
            {"promedio": promedio, "mediana": mediana}, items_dificiles, brechas_ra,
            len(rows), aprob_pct)
        rep["resumen"] = {"n": len(rows), "promedio_pct": promedio, "mediana_pct": mediana,
                          "aprobacion_pct": aprob_pct, "items_dificiles": items_dificiles,
                          "brechas_ra": brechas_ra}
        return rep
    except Exception:
        logger.error(f"Error en briefing_del_curso {assessment_id}: {traceback.format_exc()}")
        raise
