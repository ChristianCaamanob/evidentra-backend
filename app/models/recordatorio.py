"""
Recordatorios personales del alumno (v2.0) — el estudiante crea sus propios avisos con fecha/hora
y Runi se los recuerda con una notificación (alarma) a la pantalla bloqueada cuando llega el momento.

Personal por alumno (owner_key = sid:<uuid> | dev:<device>). Fecha/hora como texto (sin líos de zona).
"""
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RecordatorioPersonal(UUIDMixin, Base):
    __tablename__ = "recordatorios_personales"

    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    titulo: Mapped[str] = mapped_column(String(160), default="")
    fecha: Mapped[str] = mapped_column(String(10), default="")          # 'YYYY-MM-DD'
    hora: Mapped[str] = mapped_column(String(5), default="")            # 'HH:MM'
    nota: Mapped[str | None] = mapped_column(String(300), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avisado: Mapped[bool] = mapped_column(Boolean, default=False)       # ya se envió la alarma push
    hecho: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
