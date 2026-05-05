from uuid import UUID

from sqlalchemy.orm import Session

from app.models.assessment import Assessment


class AssessmentRepository:
    def get(self, db: Session, assessment_id: UUID) -> Assessment | None:
        return db.get(Assessment, assessment_id)

    def first(self, db: Session) -> Assessment | None:
        return db.query(Assessment).first()

    def save(self, db: Session, assessment: Assessment) -> Assessment:
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return assessment
