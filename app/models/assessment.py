import uuid

from sqlalchemy import String, Integer, Boolean, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# Modalidad de la evaluacion:
#   escrita -> sobre hoja/escaneo (alternativas y/o desarrollo escrito). El sujeto es el Scan.
#   oral    -> una rubrica parametrizada aplicada DIRECTAMENTE a cada estudiante (oral,
#              presentacion, practica). No hay hoja: el sujeto es el estudiante de la nomina.
MODALIDAD_ESCRITA = "escrita"
MODALIDAD_ORAL = "oral"
MODALIDADES = (MODALIDAD_ESCRITA, MODALIDAD_ORAL)


class Assessment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assessments"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="draft")
    assessment_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_versions: Mapped[bool] = mapped_column(Boolean, default=False)
    version_count: Mapped[int] = mapped_column(Integer, default=1)
    has_answer_key: Mapped[bool] = mapped_column(Boolean, default=False)
    briefing_level: Mapped[str] = mapped_column(String(50), default="initial")
    n_questions: Mapped[int] = mapped_column(Integer, default=40)
    version: Mapped[str] = mapped_column(String(10), default="A")
    grading_scale: Mapped[str] = mapped_column(String(50), default="chile_1_7")
    passing_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Aditivo: las evaluaciones existentes quedan 'escrita' (server_default), sin cambios.
    modalidad: Mapped[str] = mapped_column(String(20), default=MODALIDAD_ESCRITA,
                                           server_default=MODALIDAD_ESCRITA, nullable=False)

    course = relationship("Course", back_populates="assessments")
    answer_key = relationship("AnswerKey", back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    scans = relationship("Scan", back_populates="assessment", cascade="all, delete-orphan")
