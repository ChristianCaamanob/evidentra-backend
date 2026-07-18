from uuid import UUID

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
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
    if "error" in result and result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])
    # Eliminar nómina anterior del curso
    db.query(Student).filter(Student.course_id == course_id).delete()
    db.commit()
    # Insertar nuevos estudiantes
    for s in result["students"]:
        db.add(Student(
            course_id=course_id,
            rut=s["rut"],
            apellido_paterno=s["apellido_paterno"],
            apellido_materno=s["apellido_materno"],
            nombres=s["nombres"],
        ))
    db.commit()
    return {
        "imported": result["valid_count"],
        "errors": result["error_count"],
        "error_details": result["errors"],
    }

@router.get("/{course_id}/students")
def get_students(course_id: UUID, db: Session = Depends(get_db)):
    students = db.query(Student).filter(Student.course_id == course_id).all()
    return [{"id": str(s.id), "rut": s.rut, "apellido_paterno": s.apellido_paterno,
             "apellido_materno": s.apellido_materno, "nombres": s.nombres} for s in students]


@router.get("/{course_id}/estudiante/{rut}/brechas", dependencies=[Depends(req_profesor)])
def brechas_estudiante(course_id: UUID, rut: str, umbral: float = 60.0,
                       origen: str | None = None, db: Session = Depends(get_db)):
    """P3 · Brechas de aprendizaje del estudiante: logro por RA a lo largo del curso (cruce con la
    Tabla de Especificaciones), diferenciado por tipo de prueba. `umbral`=% bajo el cual el RA es
    brecha; `origen`=omr|en_vivo|(omitir=toda la evidencia)."""
    if origen not in (None, "", "omr", "en_vivo"):
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service
    return ficha_service.brechas_estudiante(db, course_id, rut, umbral_brecha=umbral,
                                            origen=(origen or None))


@router.get("/{course_id}/estudiante/{rut}/informe", dependencies=[Depends(req_profesor)])
def informe_estudiante(course_id: UUID, rut: str, umbral: float = 60.0,
                       origen: str | None = None, db: Session = Depends(get_db)):
    """P3 · Informe personalizado, empático y propositivo, del estudiante: reconoce logros,
    constata brechas por RA y propone escenarios estratégicos de aprendizaje (BORRADOR con
    compuerta docente; IA anclada a datos reales o plantilla determinista sin clave)."""
    if origen not in (None, "", "omr", "en_vivo"):
        raise HTTPException(status_code=422, detail="origen inválido (omr | en_vivo | omitir).")
    from app.services import ficha_service
    return ficha_service.informe_personalizado(db, course_id, rut, umbral_brecha=umbral,
                                               origen=(origen or None))


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
    from app.models.teacher import ROL_INVESTIGADOR, ROL_CREADOR
    # Conteo de estudiantes por curso en una sola consulta.
    counts = dict(db.query(Student.course_id, func.count(Student.id))
                  .group_by(Student.course_id).all())
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
                       "n_students": int(counts.get(c.id, 0))})
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
