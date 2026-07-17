from uuid import UUID

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.schemas.course import ActivateCourseOut, CompleteCourseStructureIn, CourseOut, CourseReadinessOut
from app.services import course_service

router = APIRouter(prefix="/courses", tags=["courses"])


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
def list_courses(db: Session = Depends(get_db)):
    from app.models.course import Course
    courses = db.query(Course).order_by(Course.created_at.desc()).all()
    return [{"id": str(c.id), "name": c.name, "code": c.code,
             "status": c.status, "grading_scale": c.grading_scale,
             "passing_threshold": c.passing_threshold} for c in courses]

class CourseIn(BaseModel):
    name: str
    code: str
    grading_scale: str = "chile_1_7"
    passing_threshold: float = 60.0

@router.post("/", dependencies=[Depends(req_profesor)])
def create_course(payload: CourseIn, db: Session = Depends(get_db)):
    from app.models.course import Course
    existing = db.query(Course).filter(Course.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un curso con ese código")
    course = Course(
        name=payload.name,
        code=payload.code,
        status="active",
        grading_scale=payload.grading_scale,
        passing_threshold=payload.passing_threshold,
        has_learning_structure=False,
        base_score_type="raw_points",
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return {"id": str(course.id), "name": course.name, "code": course.code,
            "status": course.status, "grading_scale": course.grading_scale,
            "passing_threshold": course.passing_threshold}
