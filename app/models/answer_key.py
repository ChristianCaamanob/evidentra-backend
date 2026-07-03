import uuid

from sqlalchemy import String, Integer, Boolean, Float, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# F1 - tipos de pregunta soportados por el motor de evaluacion.
# multiple_choice: el MVP actual (respuesta correcta unica, correccion por OCR).
# open_response: respuesta de desarrollo, evaluada contra una rubrica (fase F).
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_OPEN_RESPONSE = "open_response"
QUESTION_TYPES = (QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_OPEN_RESPONSE)


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

    # F1 - tipo de pregunta. Aditivo: el MVP asume multiple_choice, asi que el
    # default preserva el comportamiento de todas las filas y flujos existentes.
    question_type: Mapped[str] = mapped_column(
        String(30), default=QUESTION_TYPE_MULTIPLE_CHOICE,
        server_default=QUESTION_TYPE_MULTIPLE_CHOICE, nullable=False,
    )

    # C1 - vinculo curricular (RA / Bloom / unidad). OPCIONALES y nullable:
    # el MVP de correccion sigue funcionando sin ellos; solo enriquecen el item
    # cuando el curriculo esta cargado (C2) y etiquetado (C3).
    learning_outcome_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bloom_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(100), nullable=True)

    answer_key = relationship("AnswerKey", back_populates="items")
    # F1 - criterios de rubrica (solo relevantes para preguntas open_response).
    rubric_criteria = relationship(
        "RubricCriterion", back_populates="item", cascade="all, delete-orphan",
        order_by="RubricCriterion.order",
    )


class RubricCriterion(UUIDMixin, Base):
    """
    F1 - Criterio de una rubrica de correccion para respuestas de desarrollo.

    Base del motor de evaluacion universal: cada pregunta open_response se corrige
    contra uno o mas criterios (nombre + descriptor + peso). La IA pre-califica
    criterio a criterio (fase F2), pero la nota final es del docente (G1).
    """
    __tablename__ = "rubric_criteria"

    answer_key_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_key_items.id"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255))
    descriptor: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    order: Mapped[int] = mapped_column(Integer, default=0)

    item = relationship("AnswerKeyItem", back_populates="rubric_criteria")
