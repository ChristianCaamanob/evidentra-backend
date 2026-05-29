from uuid import UUID

from sqlalchemy.orm import Session

from app.models.scan import Scan


class ScanRepository:
    def get(self, db: Session, scan_id: UUID) -> Scan | None:
        return db.get(Scan, scan_id)

    def first(self, db: Session) -> Scan | None:
        return db.query(Scan).first()

    def save(self, db: Session, scan: Scan) -> Scan:
        db.add(scan)
        db.commit()
        db.refresh(scan)
        return scan

    def list_by_assessment(self, db: Session, assessment_id):
        return (
            db.query(Scan)
            .filter(Scan.assessment_id == assessment_id)
            .order_by(Scan.created_at.asc())
            .all()
        )
