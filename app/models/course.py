from sqlalchemy import String, Float, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Course(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    program_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_learning_structure: Mapped[bool] = mapped_column(Boolean, default=False)
    grading_scale: Mapped[str | None] = mapped_column(String(100), nullable=True)
    passing_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_score_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Naturaleza del curso: 'teorico' (máx. 110) o 'laboratorio'/'practico' (máx. 33). Etiqueta
    # para la UI y el tope de nómina; no altera notas. Nullable → cursos previos sin tipo.
    tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Identidad visual del curso (la elige el docente): color de acento y emoji de portada.
    # Aditivas y nullable; puramente cosméticas (no alteran notas ni permisos).
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Unidad organizativa para el agregado del Director (decisiones por Departamento/Facultad).
    # Nullable/aditivas; no alteran notas ni la vista del docente.
    departamento: Mapped[str | None] = mapped_column(String(160), nullable=True)
    facultad: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # F1 (blueprint) - norma terminologica vigente de la disciplina, fijada una vez y
    # heredada por las rubricas. La IA la usa como autoridad (p. ej. "TA2 (IFAA)").
    norma_terminologica: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Parametrización de la estructura de evaluación (componentes con peso %=100, ciclos y reglas
    # de asistencia). La define el profesor OPCIONALMENTE; habilita el pronóstico de aprobación.
    # No altera notas (G1); es un plan de ponderación declarado.
    parametrizacion: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    assessments = relationship("Assessment", back_populates="course", cascade="all, delete-orphan")
    students = relationship("Student", back_populates="course", cascade="all, delete-orphan")
