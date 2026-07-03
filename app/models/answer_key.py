import uuid

from sqlalchemy import String, Integer, Boolean, Float, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class AnswerKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "answer_keys"

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), unique=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    version_coverage_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    annulled_items_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_weight_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_partial_rule_count: Mapped[int] = mapped_column(Integer, default=0)

    assessment = relationship("Assessment", back_populates="answer_key")
    items = relationship("AnswerKeyItem", back_populates="answer_key", cascade="all, delete-orphan")


class AnswerKeyItem(UUIDMixin, Base):
    __tablename__ = "answer_key_items"

    answer_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("answer_keys.id"))
    question_number: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(10))
    correct_answer: Mapped[str] = mapped_column(String(10))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_annulled: Mapped[bool] = mapped_column(Boolean, default=False)
    partial_credit_rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # C1 - vinculo curricular (RA / Bloom / unidad). OPCIONALES y nullable:
    # el MVP de correccion sigue funcionando sin ellos; solo enriquecen el item
    # cuando el curriculo esta cargado (C2) y etiquetado (C3).
    learning_outcome_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bloom_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(100), nullable=True)

    answer_key = relationship("AnswerKey", back_populates="items")
