"""Sala de estudio en vivo (Runi · reunión de grupo asistida).

Los estudiantes CREAN sesiones de estudio en vivo sobre un curso (atadas a su agente de sílabo, para que
Runi tenga el contexto). Los compañeros se unen con su nombre de trato (sin cuenta). Runi asiste, responde
lo académico y va PREMIANDO a medida que aprenden; la plataforma da cuenta del progreso grupal e individual.

Doctrina del protocolo: la sala es COMPARTIDA → los temas reservados (salud/denuncia/justificación) NUNCA
aparecen aquí; Runi redirige al espacio personal. Sin datos personales: identidad = nombre de trato + device.
"""
import uuid

from sqlalchemy import String, Boolean, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class SalaEstudio(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "salas_estudio"

    agente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("silabo_agentes.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)     # código de unión
    titulo: Mapped[str] = mapped_column(String(160), default="Sala de estudio")
    creador_alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # {device_id: {alias, puntos, aportes, ultimo_ts}} — presencia + puntaje individual (nombre de trato, sin PII)
    participantes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {puntos_grupo, temas:[...], hitos:[...]} — progreso conjunto
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    mensajes = relationship("SalaMensaje", back_populates="sala", cascade="all, delete-orphan")


class SalaMensaje(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sala_mensajes"

    sala_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("salas_estudio.id"), index=True)
    alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rol: Mapped[str] = mapped_column(String(16), default="alumno")               # alumno | runi | sistema
    texto: Mapped[str] = mapped_column(Text)
    tema: Mapped[str | None] = mapped_column(String(120), nullable=True)          # tema/RA que tocó (trazabilidad)

    sala = relationship("SalaEstudio", back_populates="mensajes")
