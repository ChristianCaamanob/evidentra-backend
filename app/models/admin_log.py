"""
Bitácora de accesos del Administrador (CEO) — cada vez que la Consola del Administrador
lee registros de estudiantes queda un asiento inmutable: quién (correo), qué recurso, cuándo.

Es el ESCUDO del CEO: prueba que la fiscalización fue por gobernanza (uso adecuado de la
plataforma) y no invasión arbitraria. Solo el rol 'creador' genera y consulta estos asientos.
"""
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AccesoAdminLog(UUIDMixin, Base):
    __tablename__ = "admin_accesos_log"

    admin_email: Mapped[str] = mapped_column(String(160), index=True)
    recurso: Mapped[str] = mapped_column(String(60))                 # 'social' | 'resumen' | ...
    detalle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
