from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.answer_key import AnswerKey


class AnswerKeyRepository:
    def get_by_assessment_id(self, db: Session, assessment_id: UUID) -> AnswerKey | None:
        return (
            db.query(AnswerKey)
            .options(selectinload(AnswerKey.items))
            .filter(AnswerKey.assessment_id == assessment_id)
            .first()
        )

    def save(self, db: Session, answer_key: AnswerKey) -> AnswerKey:
        db.add(answer_key)
        db.commit()
        db.refresh(answer_key)
        return answer_key
