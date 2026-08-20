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
    for field in ("name", "code", "status", "passing_threshold", "grading_scale", "color", "emoji"):
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
    """Borra el curso y TODO lo que cuelga de él.

    Ojo: 8 tablas referencian courses.id y ninguna declara ON DELETE CASCADE; solo `assessments`
    y `students` tienen cascada ORM. Sin limpiar el resto, Postgres lanza ForeignKeyViolation →
    500 sin cabeceras CORS → el navegador lo reporta como "no se pudo conectar al servidor".
    Por eso se eliminan los dependientes explícitamente, en orden hijo→padre.
    """
    from app.models.asistencia import (
        AsistenciaMatricula, DispositivoWebAuthn, SesionAsistencia, MarcaAsistencia)
    from app.models.curriculo import LearningOutcome
    from app.models.evaluacion_agenda import EvaluacionAgenda
    from app.models.material_curso import MaterialCurso
    from app.models.push import StudentCourseFollow

    course = get_course(db, course_id)
    cid = course.id
    dele = lambda q: q.delete(synchronize_session=False)   # noqa: E731

    mat_ids = [m.id for m in db.query(AsistenciaMatricula.id).filter(AsistenciaMatricula.course_id == cid).all()]
    ses_ids = [s.id for s in db.query(SesionAsistencia.id).filter(SesionAsistencia.course_id == cid).all()]
    if mat_ids or ses_ids:
        cond = []
        if ses_ids:
            cond.append(MarcaAsistencia.sesion_id.in_(ses_ids))
        if mat_ids:
            cond.append(MarcaAsistencia.matricula_id.in_(mat_ids))
        from sqlalchemy import or_
        dele(db.query(MarcaAsistencia).filter(or_(*cond)))
    if mat_ids:
        dele(db.query(DispositivoWebAuthn).filter(DispositivoWebAuthn.matricula_id.in_(mat_ids)))
    dele(db.query(SesionAsistencia).filter(SesionAsistencia.course_id == cid))
    dele(db.query(AsistenciaMatricula).filter(AsistenciaMatricula.course_id == cid))
    dele(db.query(LearningOutcome).filter(LearningOutcome.course_id == cid))
    dele(db.query(EvaluacionAgenda).filter(EvaluacionAgenda.course_id == cid))
    dele(db.query(MaterialCurso).filter(MaterialCurso.course_id == cid))
    dele(db.query(StudentCourseFollow).filter(StudentCourseFollow.course_id == cid))
    db.flush()

    db.delete(course)          # cascada ORM: assessments (→ pauta y escaneos) y students
    db.commit()
    return {"deleted": True, "id": str(course_id)}
