from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories.course_repo import CourseRepository
from app.services.readiness_service import build_course_readiness

repo = CourseRepository()


def get_course(db: Session, course_id):
    course = repo.get(db, course_id)
    if not course:
        raise not_found("Curso no encontrado.")
    return course


def get_course_readiness(db: Session, course_id):
    course = get_course(db, course_id)
    return build_course_readiness(course)


def complete_course_structure(db: Session, course_id, has_learning_structure: bool = True):
    course = get_course(db, course_id)
    course.has_learning_structure = has_learning_structure
    repo.save(db, course)
    return build_course_readiness(course)


def activate_course(db: Session, course_id):
    course = get_course(db, course_id)
    readiness = build_course_readiness(course)
    if not readiness["is_ready"]:
        raise conflict("El curso no puede activarse porque aún faltan campos obligatorios.")
    course.status = "active"
    repo.save(db, course)
    return {"id": course.id, "status": course.status}


def update_course(db: Session, course_id, payload: dict):
    course = get_course(db, course_id)
    for field in ("name", "code", "status", "passing_threshold", "grading_scale"):
        if field in payload and payload[field] is not None:
            setattr(course, field, payload[field])
    # Tipo de curso: acepta '', None (limpiar) o uno de los válidos; ignora valores desconocidos.
    if "tipo" in payload:
        t = (payload.get("tipo") or "").strip().lower() or None
        if t is None or t in ("teorico", "laboratorio", "practico"):
            course.tipo = t
    repo.save(db, course)
    return course


def delete_course(db: Session, course_id):
    course = get_course(db, course_id)
    db.delete(course)
    db.commit()
    return {"deleted": True, "id": str(course_id)}
