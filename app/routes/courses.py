from uuid import UUID

import re

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.schemas.course import ActivateCourseOut, CompleteCourseStructureIn, CourseOut, CourseReadinessOut
from app.services import course_service

router = APIRouter(prefix="/courses", tags=["courses"])

# Tope de nómina por naturaleza del curso (aviso, no bloqueo): teórico grande, laboratorio chico.
MAX_POR_TIPO = {"teorico": 110, "laboratorio": 33, "practico": 33}
CURSOS_SOLO_INVESTIGACION = {"DEMO-Q1", "DEMO-PSICO"}   # cohortes grandes de psicometría


def _max_estudiantes(tipo):
    return MAX_POR_TIPO.get((tipo or "").lower())


_bearer_opt = HTTPBearer(auto_error=False)


def _rol_opcional(cred: HTTPAuthorizationCredentials = Depends(_bearer_opt),
                  db: Session = Depends(get_db)):
    """Rol del usuario si viene token válido; None si no. No exige auth (lista pública tolerante)."""
    if cred is None or not cred.credentials:
        return None
    try:
        from app.services import auth_service
        u = auth_service.usuario_desde_token(db, cred.credentials)
        return u.rol if u else None
    except Exception:
        return None


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.get_course(db, course_id)


@router.get("/{course_id}/readiness", response_model=CourseReadinessOut)
def get_course_readiness(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.get_course_readiness(db, course_id)


@router.post("/{course_id}/complete-structure", response_model=CourseReadinessOut,
             dependencies=[Depends(req_profesor)])
def complete_course_structure(
    course_id: UUID,
    payload: CompleteCourseStructureIn,
    db: Session = Depends(get_db),
):
    return course_service.complete_course_structure(db, course_id, payload.has_learning_structure)


@router.post("/{course_id}/activate", response_model=ActivateCourseOut,
             dependencies=[Depends(req_profesor)])
def activate_course(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.activate_course(db, course_id)


@router.patch("/{course_id}", response_model=CourseOut, dependencies=[Depends(req_profesor)])
def update_course(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return course_service.update_course(db, course_id, payload)


@router.delete("/{course_id}", dependencies=[Depends(req_profesor)])
def delete_course(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.delete_course(db, course_id)

from fastapi import UploadFile, File
from app.services.nomina_service import parse_nomina_excel
from app.models.student import Student

@router.post("/{course_id}/upload-nomina", dependencies=[Depends(req_profesor)])
async def upload_nomina(course_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_bytes = await file.read()
    result = parse_nomina_excel(file_bytes)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    # NO borrar la nómina existente si el Excel no aportó estudiantes válidos (evita vaciar el curso).
    if not result["students"]:
        muestra = "; ".join((e.get("error") or "") for e in (result.get("errors") or [])[:3])
        raise HTTPException(status_code=400, detail=(
            "No se importó ningún estudiante: el Excel no tiene RUT válidos ni números de matrícula."
            + (" Ejemplos: " + muestra if muestra else "")))
    # Reemplazar la nómina: eliminar la anterior e insertar la nueva.
    db.query(Student).filter(Student.course_id == course_id).delete()
    db.commit()
    for s in result["students"]:
        db.add(Student(
            course_id=course_id,
            rut=s["rut"],                       # RUT si lo hay; si no, la matrícula (identificador)
            matricula=s.get("matricula"),
            apellido_paterno=s["apellido_paterno"],
            apellido_materno=s["apellido_materno"],
            nombres=s["nombres"],
        ))
    db.commit()
    return {
        "imported": result["valid_count"],
        "errors": result["error_count"],
        "dv_advertencias": result.get("dv_advertencias", 0),
        "sin_rut": result.get("sin_rut", 0),
        "error_details": result["errors"][:20],
    }

@router.get("/{course_id}/students")
def get_students(course_id: UUID, db: Session = Depends(get_db)):
    students = db.query(Student).filter(Student.course_id == course_id).all()
    return [{"id": str(s.id), "rut": s.rut, "matricula": s.matricula,
             "apellido_paterno": s.apellido_paterno,
             "apellido_materno": s.apellido_materno, "nombres": s.nombres} for s in students]


@router.get("/{course_id}/curriculo")
def get_curriculo(course_id: UUID, db: Session = Depends(get_db)):
    """Tabla de Especificaciones del curso: los RA (LearningOutcome) con su texto literal (C2)."""
    from app.models.curriculo import LearningOutcome
    ras = (db.query(LearningOutcome).filter(LearningOutcome.course_id == course_id)
           .order_by(LearningOutcome.orden).all())
    return {"ras": [{"code": r.code, "text": r.text, "unidad": r.unidad, "orden": r.orden}
                    for r in ras], "n": len(ras)}


@router.post("/{course_id}/curriculo", dependencies=[Depends(req_profesor)])
def set_curriculo(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Carga/actualiza la Tabla de Especificaciones (RA) del curso, preservando el texto literal
    del programa. payload={"ras":[{"code","text","unidad"?}]}. Idempotente por (curso, code)."""
    from app.services import curriculo_service
    limpio = []
    for r in (payload.get("ras") or []):
        code = str(r.get("code", "")).strip()
        text = str(r.get("text", "")).strip()
        if code and text:
            limpio.append({"code": code, "text": text,
                           "unidad": (str(r.get("unidad")).strip() or None) if r.get("unidad") else None})
    if not limpio:
        raise HTTPException(status_code=422, detail="Envía al menos un RA con 'code' y 'text'.")
    out = curriculo_service.import_curriculo(db, course_id, limpio)
    return {"ras": [{"code": r.code, "text": r.text, "unidad": r.unidad, "orden": r.orden}
                    for r in out], "n": len(out)}


@router.get("/{course_id}/estudiante/{rut}/brechas", dependencies=[Depends(req_profesor)])
def brechas_estudiante(course_id: UUID, rut: str, umbral: float = 60.0,
                       origen: str | None = None, assessment_id: UUID | None = None,
                       db: Session = Depends(get_db)):
    """P3 · Brechas de aprendizaje del estudiante: logro por RA a lo largo del curso (cruce con la
    Tabla de Especificaciones), diferenciado por tipo de prueba. `umbral`=% bajo el cual el RA es
    brecha; `origen`=omr|en_vivo|(omitir=toda la evidencia); `assessment_id`=acota a una prueba."""
    if origen not in (None, "", "omr", "en_vivo"):
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service
    return ficha_service.brechas_estudiante(db, course_id, rut, umbral_brecha=umbral,
                                            origen=(origen or None), assessment_id=assessment_id)


@router.get("/{course_id}/estudiante/{rut}/informe", dependencies=[Depends(req_profesor)])
def informe_estudiante(course_id: UUID, rut: str, umbral: float = 60.0,
                       origen: str | None = None, assessment_id: UUID | None = None,
                       db: Session = Depends(get_db)):
    """P3 · Informe personalizado, empático y propositivo, del estudiante: reconoce logros,
    constata brechas por RA y propone escenarios estratégicos de aprendizaje (BORRADOR con
    compuerta docente; IA anclada a datos reales o plantilla determinista sin clave).
    assessment_id opcional → informe DINÁMICO acotado a esa prueba; omitir → consolidado del curso."""
    if origen not in (None, "", "omr", "en_vivo"):
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service
    return ficha_service.informe_personalizado(db, course_id, rut, umbral_brecha=umbral,
                                               origen=(origen or None), assessment_id=assessment_id)


@router.post("/{course_id}/estudiante/{rut}/informe/{formato}", dependencies=[Depends(req_profesor)])
def informe_estudiante_export(course_id: UUID, rut: str, formato: str, umbral: float = 60.0,
                              origen: str | None = None, assessment_id: UUID | None = None,
                              db: Session = Depends(get_db)):
    """Descarga el informe personalizado del estudiante en Word/PDF (borrador, compuerta docente).
    assessment_id opcional → acota a una prueba; omitir → consolidado del curso."""
    if formato not in ("docx", "pdf"):
        raise HTTPException(status_code=422, detail="Formato no soportado (docx | pdf).")
    if origen not in (None, "", "omr", "en_vivo"):
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service, exportador_service
    out = ficha_service.informe_export_payload(db, course_id, rut, umbral_brecha=umbral,
                                               origen=(origen or None), assessment_id=assessment_id)
    data, media = exportador_service.exportar(formato, out["payload"])
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", f"informe_{rut}")[:80]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.{formato}"'})


# ── Parametrización del curso + Ciclos + Pronóstico de aprobación (proactivo) ──
@router.get("/{course_id}/parametrizacion", dependencies=[Depends(req_profesor)])
def get_parametrizacion(course_id: UUID, db: Session = Depends(get_db)):
    from app.services import prediccion_service
    return prediccion_service.obtener_parametrizacion(db, course_id)


@router.put("/{course_id}/parametrizacion", dependencies=[Depends(req_profesor)])
def put_parametrizacion(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Guarda la estructura de evaluación del curso (componentes con peso %=100 + asistencia).
    Habilita el pronóstico. No altera notas (G1)."""
    from app.services import prediccion_service
    return prediccion_service.guardar_parametrizacion(db, course_id, payload)


@router.get("/{course_id}/ciclos", dependencies=[Depends(req_profesor)])
def get_ciclos(course_id: UUID, db: Session = Depends(get_db)):
    """Ciclos automáticos: cada certamen/solemne cierra un ciclo (controles previos + ese certamen)."""
    from app.services import prediccion_service
    return prediccion_service.ciclos(db, course_id)


@router.get("/{course_id}/estudiante/{rut}/pronostico", dependencies=[Depends(req_profesor)])
def get_pronostico_estudiante(course_id: UUID, rut: str, db: Session = Depends(get_db)):
    """Proyección de aprobación del estudiante (escenarios + nota necesaria + compuerta de asistencia)."""
    from app.services import prediccion_service
    from app.models.course import Course
    c = db.get(Course, course_id)
    escala = (c.grading_scale if c else None) or "chile_1_7"
    exig = (c.passing_threshold if c else None) or 60.0
    return prediccion_service.pronostico_estudiante(db, course_id, rut, escala=escala, exigencia=exig)


@router.get("/{course_id}/pronostico", dependencies=[Depends(req_profesor)])
def get_pronostico_curso(course_id: UUID, db: Session = Depends(get_db)):
    """Pronóstico agregado del curso: por estudiante + conteo por estado (tablero proactivo)."""
    from app.services import prediccion_service
    from app.models.course import Course
    c = db.get(Course, course_id)
    escala = (c.grading_scale if c else None) or "chile_1_7"
    exig = (c.passing_threshold if c else None) or 60.0
    return prediccion_service.pronostico_curso(db, course_id, escala=escala, exigencia=exig)


@router.post("/{course_id}/pronostico/{formato}", dependencies=[Depends(req_profesor)])
def export_pronostico_curso(course_id: UUID, formato: str, db: Session = Depends(get_db)):
    """Descarga el pronóstico del curso en Word/PDF/Excel (semáforo + tabla por estudiante)."""
    if formato not in ("docx", "pdf", "xlsx"):
        raise HTTPException(status_code=422, detail="Formato no soportado (docx | pdf | xlsx).")
    from app.services import prediccion_service, exportador_service
    from app.models.course import Course
    c = db.get(Course, course_id)
    escala = (c.grading_scale if c else None) or "chile_1_7"
    exig = (c.passing_threshold if c else None) or 60.0
    out = prediccion_service.pronostico_export_payload(db, course_id, escala=escala, exigencia=exig)
    data, media = exportador_service.exportar(formato, out["payload"])
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", f"pronostico_{(c.code if c else '')}")[:80] or "pronostico"
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.{formato}"'})


class StudentIn(BaseModel):
    rut: str
    apellido_paterno: str
    apellido_materno: str = ""
    nombres: str

@router.post("/{course_id}/students", dependencies=[Depends(req_profesor)])
def add_student(course_id: UUID, payload: StudentIn, db: Session = Depends(get_db)):
    from app.models.student import Student
    # Verificar RUT duplicado
    existing = db.query(Student).filter(Student.rut == payload.rut, Student.course_id == course_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un estudiante con ese RUT en este curso")
    student = Student(
        course_id=course_id,
        rut=payload.rut,
        apellido_paterno=payload.apellido_paterno,
        apellido_materno=payload.apellido_materno,
        nombres=payload.nombres,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"rut": student.rut, "apellido_paterno": student.apellido_paterno,
            "apellido_materno": student.apellido_materno, "nombres": student.nombres}


@router.get("/", response_model=list)
def list_courses(rol=Depends(_rol_opcional), db: Session = Depends(get_db)):
    from sqlalchemy import func
    from app.models.course import Course
    from app.models.student import Student
    from app.models.assessment import Assessment
    from app.models.teacher import ROL_INVESTIGADOR, ROL_CREADOR
    # Conteo de estudiantes y de evaluaciones por curso, cada uno en una sola consulta.
    counts = dict(db.query(Student.course_id, func.count(Student.id))
                  .group_by(Student.course_id).all())
    asm_counts = dict(db.query(Assessment.course_id, func.count(Assessment.id))
                      .group_by(Assessment.course_id).all())
    # Señal para el tablero: cuántas evaluaciones ya tienen PAUTA VALIDADA (lo que habilita
    # corregir/abrir sala). La diferencia con n_assessments es lo que le falta al docente.
    from app.models.answer_key import AnswerKey
    pautas_ok = dict(db.query(Assessment.course_id, func.count(func.distinct(Assessment.id)))
                     .join(AnswerKey, AnswerKey.assessment_id == Assessment.id)
                     .filter(AnswerKey.is_valid.is_(True))
                     .group_by(Assessment.course_id).all())
    ve_investigacion = rol in (ROL_INVESTIGADOR, ROL_CREADOR)
    salida = []
    for c in db.query(Course).order_by(Course.created_at.desc()).all():
        # Las cohortes grandes de psicometría solo las ve el Investigador (o el creador).
        if c.code in CURSOS_SOLO_INVESTIGACION and not ve_investigacion:
            continue
        salida.append({"id": str(c.id), "name": c.name, "code": c.code,
                       "status": c.status, "grading_scale": c.grading_scale,
                       "passing_threshold": c.passing_threshold,
                       "tipo": c.tipo, "max_estudiantes": _max_estudiantes(c.tipo),
                       "n_students": int(counts.get(c.id, 0)),
                       "n_assessments": int(asm_counts.get(c.id, 0)),
                       "n_pautas_ok": int(pautas_ok.get(c.id, 0)),
                       "color": c.color, "emoji": c.emoji,
                       "departamento": c.departamento, "facultad": c.facultad})
    return salida

class CourseIn(BaseModel):
    name: str
    code: str
    grading_scale: str = "chile_1_7"
    passing_threshold: float = 60.0
    tipo: str | None = None      # 'teorico' | 'laboratorio' | 'practico'

@router.post("/", dependencies=[Depends(req_profesor)])
def create_course(payload: CourseIn, db: Session = Depends(get_db)):
    from app.models.course import Course
    existing = db.query(Course).filter(Course.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un curso con ese código")
    tipo = (payload.tipo or "").lower() or None
    if tipo and tipo not in MAX_POR_TIPO:
        tipo = None
    course = Course(
        name=payload.name,
        code=payload.code,
        status="active",
        grading_scale=payload.grading_scale,
        passing_threshold=payload.passing_threshold,
        has_learning_structure=False,
        base_score_type="raw_points",
        tipo=tipo,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"id": str(course.id), "name": course.name, "code": course.code,
            "status": course.status, "grading_scale": course.grading_scale,
            "passing_threshold": course.passing_threshold,
            "tipo": course.tipo, "max_estudiantes": _max_estudiantes(course.tipo),
            "n_students": 0}
