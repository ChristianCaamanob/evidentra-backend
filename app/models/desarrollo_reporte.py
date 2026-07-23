"""
Persistencia del REPORTE de desarrollo por estudiante (Fase Reportes).

Guarda, por (evaluación × estudiante × pregunta), lo que el alumno respondió y la revisión
que produjo el motor experto (Fase 3), para poder reconstruir el detalle de la corrección en
la ventana de Reportes y en el Centro de Análisis. No reemplaza a RegistroValidacion (que
guarda el nivel VALIDADO por criterio, G1); lo complementa con el TEXTO y la narrativa.

Gobernanza: es una vista docente (identificada); el uso agregado/investigador sigue
seudonimizado (G2). La nota siempre la fija el docente (G1).
"""
import uuid

from sqlalchemy import String, Integer, Float, JSON, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class DesarrolloRespuesta(UUIDMixin, Base):
    __tablename__ = "desarrollo_respuestas"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    student_id: Mapped[str] = mapped_column(String(64), index=True)
    answer_key_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_number: Mapped[int] = mapped_column(Integer, default=0)

    respuesta_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    puntaje: Mapped[float | None] = mapped_column(Float, nullable=True)   # puntos obtenidos
    frac: Mapped[float | None] = mapped_column(Float, nullable=True)      # 0-1 del ítem
    nivel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Narrativa de la revisión: justificación, respuesta modelo, brechas, criterios, transparencia.
    revision_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    docente: Mapped[str] = mapped_column(String(120), default="docente")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
