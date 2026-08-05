"""
Analítica de producto (dominio EXPERIENCIA) — eventos con envelope estricto.

El servicio RECHAZA eventos incompletos (schema estricto, ver analytics_service). Aquí solo se
persisten los válidos. Identidad seudonimizada. Separado de aprendizaje/identidad/seguridad.
"""
from sqlalchemy import String, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AnalyticsEvent(UUIDMixin, Base):
    __tablename__ = "analytics_events"

    event: Mapped[str] = mapped_column(String(60), index=True)
    event_version: Mapped[str] = mapped_column(String(8), default="v1")
    domain: Mapped[str] = mapped_column(String(20), index=True)          # producto|aprendizaje|identidad|seguridad
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    segment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    device: Mapped[str | None] = mapped_column(String(16), nullable=True)
    props: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    client_ts: Mapped[str | None] = mapped_column(String(40), nullable=True)  # ts del cliente (ISO)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
