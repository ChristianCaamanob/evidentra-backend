"""Ubicación activa de la Pandilla (Fase 2). UNA fila por alumno y curso (upsert) → NO hay historial
de trayectos. Caduca por `expires_ts` (TTL); se purga y se puede revocar al instante (delete).

Solo estudiantes universitarios (mayores de edad). La ubicación es voluntaria, temporal y revocable.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class PandillaUbicacion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "pandilla_ubicaciones"
    # Una ubicación ACTIVA por alumno y curso → el upsert sobrescribe (sin historial).
    __table_args__ = (UniqueConstraint("course_id", "matricula_id", name="uq_pandilla_ubic_curso_mat"),)

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    matricula_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asistencia_matriculas.id"), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float] = mapped_column(Float, default=0.0)        # radio de precisión (m)
    precision: Mapped[str] = mapped_column(String(10), default="aprox")  # 'aprox' | 'preciso'
    char: Mapped[str | None] = mapped_column(String(24), nullable=True)  # personaje de la Pandilla
    alias: Mapped[str | None] = mapped_column(String(120), nullable=True)  # nombre a mostrar (real, nómina)
    estado: Mapped[str | None] = mapped_column(String(20), nullable=True)  # disponibilidad
    capturado_ts: Mapped[int] = mapped_column(Integer, default=0)          # epoch de la última captura
    expires_ts: Mapped[int] = mapped_column(Integer, index=True)           # epoch de caducidad (TTL)
