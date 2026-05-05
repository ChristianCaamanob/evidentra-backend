from uuid import UUID

from sqlalchemy.orm import Session

from app.models.course import Course


class CourseRepository:
    def get(self, db: Session, course_id: UUID) -> Course | None:
        return db.get(Course, course_id)

    def first(self, db: Session) -> Course | None:
        return db.query(Course).first()

    def save(self, db: Session, course: Course) -> Course:
        db.add(course)
        db.commit()
        db.refresh(course)
        return course
