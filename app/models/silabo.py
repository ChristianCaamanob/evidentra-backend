"""Escudo de comunicación (Pilar II) — agente de sílabo 24/7 + bandeja clasificada.

Doctrina de acceso (igual que Modo en vivo / Asistencia): los alumnos NO tienen cuenta;
acceden al agente por un ENLACE/QR público por curso (`?silabo=CODIGO`). El docente carga
el contexto del curso (sílabo, fechas, reglas), publica el agente, y la IA responde 24/7
SOLO con base en ese contexto. Lo que la IA no puede resolver o que requiere decisión del
docente cae, clasificado, en una bandeja para el docente (no lo satura de repetidas).
"""
import uuid

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin

# Estados de un mensaje de la bandeja.
MSG_RESPONDIDA = "respondida"          # la IA respondió y basta
MSG_PENDIENTE = "pendiente_docente"    # requiere respuesta/decisión del docente
MSG_RESUELTA = "resuelta"              # el docente la respondió/cerró


class SilaboAgente(UUIDMixin, TimestampMixin, Base):
    """Un agente de sílabo por curso. `contexto` es el material sobre el que la IA responde."""
    __tablename__ = "silabo_agentes"

    course_id: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)   # enlace público
    nombre_curso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contexto: Mapped[str] = mapped_column(Text, default="")                    # sílabo/reglas/fechas
    activo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)           # tono, alcance, etc.

    mensajes = relationship("MensajeSilabo", back_populates="agente", cascade="all, delete-orphan")


class MensajeSilabo(UUIDMixin, TimestampMixin, Base):
    """Una pregunta de un alumno + la respuesta de la IA + su clasificación para la bandeja."""
    __tablename__ = "silabo_mensajes"

    agente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("silabo_agentes.id"), index=True)
    alias: Mapped[str | None] = mapped_column(String(80), nullable=True)       # opcional (sin login)
    pregunta: Mapped[str] = mapped_column(Text)
    respuesta_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoria: Mapped[str | None] = mapped_column(String(40), nullable=True)   # fechas/contenido/evaluación/logística/otro
    urgencia: Mapped[str | None] = mapped_column(String(10), nullable=True)     # baja/media/alta
    estado: Mapped[str] = mapped_column(String(24), default=MSG_RESPONDIDA,
                                        server_default=MSG_RESPONDIDA, nullable=False)
    necesita_docente: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    respuesta_docente: Mapped[str | None] = mapped_column(Text, nullable=True)

    agente = relationship("SilaboAgente", back_populates="mensajes")
