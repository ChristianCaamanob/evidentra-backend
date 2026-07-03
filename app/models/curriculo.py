"""
C2 - Modelo curricular: Resultados de Aprendizaje (RA) de un curso.

Postura propositiva (G6): el programa aprobado se PRESERVA tal cual. La plataforma
no reformula ni reescribe el texto oficial; solo lo almacena de forma literal y lo
vincula a los items de evaluacion (via AnswerKeyItem.learning_outcome_id, C1).
"""
import uuid

from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class LearningOutcome(UUIDMixin, TimestampMixin, Base):
    """Un Resultado de Aprendizaje (RA) de un curso, con su texto literal."""
    __tablename__ = "learning_outcomes"

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True,
    )
    # Codigo del RA tal como aparece en el programa (p. ej. "RA1", "RA2.1").
    code: Mapped[str] = mapped_column(String(50))
    # Texto del RA, PRESERVADO LITERALMENTE desde el programa aprobado. No se edita.
    text: Mapped[str] = mapped_column(Text)
    # Unidad tematica a la que pertenece el RA (opcional).
    unidad: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Orden de aparicion en el programa, para mostrarlos como en el documento original.
    orden: Mapped[int] = mapped_column(Integer, default=0)
    # Procedencia del texto (por defecto: el programa oficial cargado sin cambios).
    source: Mapped[str] = mapped_column(String(100), default="programa_oficial")

    course = relationship("Course")
