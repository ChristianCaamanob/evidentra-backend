from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.course import ActivateCourseOut, CompleteCourseStructureIn, CourseOut, CourseReadinessOut
from app.services import course_service

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.get_course(db, course_id)


@router.get("/{course_id}/readiness", response_model=CourseReadinessOut)
def get_course_readiness(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.get_course_readiness(db, course_id)


@router.post("/{course_id}/complete-structure", response_model=CourseReadinessOut)
def complete_course_structure(
    course_id: UUID,
    payload: CompleteCourseStructureIn,
    db: Session = Depends(get_db),
):
    return course_service.complete_course_structure(db, course_id, payload.has_learning_structure)


@router.post("/{course_id}/activate", response_model=ActivateCourseOut)
def activate_course(course_id: UUID, db: Session = Depends(get_db)):
    return course_service.activate_course(db, course_id)
