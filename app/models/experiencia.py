"""
v4 · Motor de experiencia universal de Runi. Vínculo del curso con una facultad + el modo de vínculo
elegido por el estudiante (persistido solo con su elección). Runi es siempre el mismo; cambia la forma
de relacionarse y el mundo disciplinar, nunca su identidad ni la capacidad atribuida.
"""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CourseFacultyBinding(Base):
    __tablename__ = "exp_course_faculty"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    faculty_pack_id: Mapped[str] = mapped_column(String(40), default="general")
    bound_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudentRelationship(Base):
    __tablename__ = "exp_student_relationship"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    primary_mode: Mapped[str] = mapped_column(String(24), default="companion")
    proactivity: Mapped[str] = mapped_column(String(12), default="medium")  # low|medium|high
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
