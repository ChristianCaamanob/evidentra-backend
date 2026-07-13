import uuid

from sqlalchemy import String, Integer, Boolean, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# Modalidad de la evaluacion (Paso 0: el docente la elige al crear y define todo el flujo aguas abajo):
#   alternativas -> seleccion multiple sobre hoja/escaneo. Pauta de grilla + OCR. question_type=multiple_choice.
#   desarrollo   -> respuesta abierta corregida contra rubrica con IA (F2). question_type=open_response.
#   mixta        -> ambas en un mismo instrumento (alternativas + desarrollo).
#   oral         -> rubrica aplicada DIRECTAMENTE a cada estudiante (oral/presentacion/practica).
#                   No hay hoja: el sujeto es el estudiante de la nomina.
# 'escrita' queda como ALIAS LEGADO de 'alternativas' (filas creadas antes del Paso 0).
MODALIDAD_ALTERNATIVAS = "alternativas"
MODALIDAD_DESARROLLO = "desarrollo"
MODALIDAD_MIXTA = "mixta"
MODALIDAD_ORAL = "oral"
MODALIDAD_ESCRITA = "escrita"  # legado -> se interpreta como alternativas
MODALIDADES = (MODALIDAD_ALTERNATIVAS, MODALIDAD_DESARROLLO, MODALIDAD_MIXTA, MODALIDAD_ORAL)


def modalidad_norm(m: str | None) -> str:
    """Normaliza la modalidad: el legado 'escrita' se lee como 'alternativas'."""
    if not m or m == MODALIDAD_ESCRITA:
        return MODALIDAD_ALTERNATIVAS
    return m


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
