"""
El Reto de Runi — banco de preguntas del curso y lo que cada estudiante ya respondió.

Nace de una observación del CEO sobre su propio producto: **Runi espera**. Todo lo que hace —
responder, corregir, celebrar— empieza porque la estudiante entró y escribió. Si no entra, no pasa
nada. Las apps a las que uno vuelve tienen algo nuevo esperando; aquí ese «algo nuevo» tiene que ser
académico y estratégico: preguntas de lo que de verdad entra en la evaluación próxima.

Dos decisiones que gobiernan estas tablas:

1. **Ninguna pregunta llega a una alumna sin que el docente la haya visto** (`estado`). En anatomía
   aplicada una pregunta mal generada no es un bug cosmético: le enseña algo falso a quien la
   responde. La IA propone; la firma es del profesor.

2. **Una pregunta no se repite a quien ya la respondió.** `RetoRespuesta` es única por (persona,
   pregunta): es lo que hace que abrir la app siempre traiga algo nuevo, y no una rueda de lo mismo.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, UUIDMixin

ESTADOS = ("propuesta", "aprobada", "descartada", "reportada")


class RetoPregunta(UUIDMixin, Base):
    __tablename__ = "reto_preguntas"

    course_id: Mapped[str] = mapped_column(String(64), index=True)
    # A qué evaluación pertenece (la tabla de especificaciones del Solemne próximo). Nula = del
    # programa general, para cuando no hay ninguna prueba a la vista.
    eval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    tema: Mapped[str] = mapped_column(String(160), default="", index=True)
    # Cuánto pesa el tema en la tabla de especificaciones: manda en qué se le pregunta más.
    peso: Mapped[int] = mapped_column(Integer, default=1)
    enunciado: Mapped[str] = mapped_column(Text, default="")
    alternativas: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # {"A": "...", "B": "..."}
    correcta: Mapped[str] = mapped_column(String(2), default="A")
    justificacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Borrador escrito por Runi. NO se le muestra a nadie hasta que el docente lo acepta y pasa a
    # `justificacion`: una explicación equivocada de anatomía enseña algo falso, igual que la
    # pregunta. La IA redacta; la firma sigue siendo del profesor.
    justificacion_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    nivel: Mapped[str] = mapped_column(String(16), default="recordar")       # recordar|conectar|aplicar
    estado: Mapped[str] = mapped_column(String(16), default="propuesta", index=True)
    origen: Mapped[str] = mapped_column(String(12), default="ia")            # ia | docente
    veces_servida: Mapped[int] = mapped_column(Integer, default=0)
    aciertos: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetoRespuesta(UUIDMixin, Base):
    """Lo que ESA persona ya contestó. Único por par: una pregunta no vuelve a salirle."""
    __tablename__ = "reto_respuestas"
    __table_args__ = (UniqueConstraint("pseudo_id", "pregunta_id", name="uq_reto_una_vez"),)

    pregunta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reto_preguntas.id", ondelete="CASCADE"), index=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    elegida: Mapped[str] = mapped_column(String(2), default="")
    correcta: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
