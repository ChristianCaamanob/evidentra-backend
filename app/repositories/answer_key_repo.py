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

    def delete_items_by_version(self, db, answer_key_id, version: str):
        from app.models.answer_key import AnswerKeyItem
        db.query(AnswerKeyItem).filter(
            AnswerKeyItem.answer_key_id == answer_key_id,
            AnswerKeyItem.version == version
        ).delete()
        db.commit()

    def add_items(self, db, items: list):
        db.add_all(items)
        db.commit()

    def get_versions(self, db, answer_key_id) -> list:
        from app.models.answer_key import AnswerKeyItem
        rows = db.query(AnswerKeyItem.version).filter(
            AnswerKeyItem.answer_key_id == answer_key_id
        ).distinct().all()
        return sorted([r[0] for r in rows])
