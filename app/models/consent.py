"""
Consentimiento versionado (dominio IDENTIDAD) — el estudiante acepta explícitamente el uso de datos,
con VERSIÓN del aviso, ámbito, y puede REVOCAR. Guarda además el puntaje del chequeo de comprensión
de privacidad (métrica: comprensión > 90%). Identidad seudonimizada.
"""
from sqlalchemy import String, Integer, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class Consent(UUIDMixin, Base):
    __tablename__ = "consents"

    pseudo_id: Mapped[str] = mapped_column(String(80), index=True, unique=True)
    version: Mapped[str] = mapped_column(String(16), default="v1")     # versión del aviso aceptado
    scope: Mapped[str] = mapped_column(String(120), default="social,analitica")
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    quiz_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # comprensión 0–100
    granted_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
