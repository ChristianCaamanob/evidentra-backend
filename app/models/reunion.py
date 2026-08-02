"""
Reuniones / reservas nativas (v2.0 · estilo Bookings, keyless).

- Disponibilidad: alguien (alumno anfitrión, ayudante) publica ventanas horarias semanales con un código
  público; genera un enlace para compartir. La videollamada es keyless (sala Jitsi determinista).
- Reserva: el invitado elige un hueco libre → se crea la cita con enlace de video + queda en la agenda.

Fechas/horas como texto (evita líos de zona horaria, igual que AgendaBloque / EvaluacionAgenda).
"""
from sqlalchemy import String, Integer, Boolean, JSON, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin
import uuid


class Disponibilidad(UUIDMixin, Base):
    __tablename__ = "reunion_disponibilidades"

    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)     # sid:<uuid> | dev:<device>
    anfitrion: Mapped[str] = mapped_column(String(120), default="")    # nombre visible del anfitrión
    titulo: Mapped[str] = mapped_column(String(160), default="Reunión")
    duracion: Mapped[int] = mapped_column(Integer, default=30)          # minutos
    ventanas: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{dia:0-6, inicio:"HH:MM", fin:"HH:MM"}]
    vigencia_dias: Mapped[int] = mapped_column(Integer, default=21)     # cuántos días hacia adelante ofrecer
    video: Mapped[bool] = mapped_column(Boolean, default=True)          # ¿crear sala de video?
    lugar: Mapped[str | None] = mapped_column(String(160), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reserva(UUIDMixin, Base):
    __tablename__ = "reunion_reservas"

    disponibilidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reunion_disponibilidades.id"), index=True)
    fecha: Mapped[str] = mapped_column(String(10), default="")          # 'YYYY-MM-DD'
    inicio: Mapped[str] = mapped_column(String(5), default="")          # 'HH:MM'
    fin: Mapped[str] = mapped_column(String(5), default="")
    invitado: Mapped[str] = mapped_column(String(120), default="")
    invitado_contacto: Mapped[str | None] = mapped_column(String(160), nullable=True)
    invitado_owner_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    nota: Mapped[str | None] = mapped_column(String(300), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="confirmada")   # confirmada | cancelada
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
