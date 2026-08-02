"""
Identidad de dispositivo (v2.0) — puente para unificar la identidad del alumno entre módulos.

Problema: los mensajes a Runi se guardan por `device_id` (localStorage), pero agenda/avisos/reuniones/
recordatorios se guardan por `owner_key` (`sid:<cuenta>` si inició sesión, `dev:<device>` si no).
Esta tabla mapea cada device_id → owner_key (+ nombre de la cuenta) para que el monitoreo docente
pueda cruzar TODOS los módulos por estudiante. Se actualiza sola cada vez que el alumno actúa.
"""
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class DeviceIdentity(UUIDMixin, Base):
    __tablename__ = "device_identities"

    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)     # sid:<uuid> | dev:<device>
    account_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    nombre: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
