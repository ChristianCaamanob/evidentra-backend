"""
Evaluaciones del curso (v2.0) — pruebas/certámenes/entregas con FECHA que el profesor carga y que
aparecen en la agenda del alumno + gatillan recordatorios amables (12 sem / 1 sem / 3 días antes).

Son por CURSO (las carga el docente); el alumno las lee por el código del agente Runi de su curso.
Fecha guardada como texto 'YYYY-MM-DD' (evita líos de zona horaria, igual que la hora de AgendaBloque).
"""
import uuid

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class EvaluacionAgenda(UUIDMixin, Base):
    __tablename__ = "evaluaciones_agenda"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200), default="")
    fecha: Mapped[str] = mapped_column(String(10), default="")          # 'YYYY-MM-DD'
    hora: Mapped[str | None] = mapped_column(String(5), nullable=True)  # 'HH:MM'
    tipo: Mapped[str] = mapped_column(String(40), default="prueba")     # prueba/certamen/examen/entrega/taller
    ponderacion: Mapped[str | None] = mapped_column(String(20), nullable=True)   # "30%"
    detalle: Mapped[str | None] = mapped_column(String(400), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
