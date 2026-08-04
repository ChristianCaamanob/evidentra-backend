"""
Momentos de la Pandilla (v2.0 social) — foto EFÍMERA que el estudiante publica al anillo de su
grupo (inspirado en las Historias de Instagram). Se ve solo el grupo, caduca a las 24 h, revocable.

Un momento activo por estudiante (upsert por owner_key). La imagen se guarda como data-URL base64
ya reescalada en el cliente (~1080px JPEG). Moderación: `reportes` + `oculto` (se oculta al superar
el umbral). Audiencia adulta (universitarios); doctrina: voluntario · temporal · revocable · sin historial.
"""
from sqlalchemy import String, Text, Integer, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PandMomento(UUIDMixin, Base):
    __tablename__ = "pand_momentos"

    owner_key: Mapped[str] = mapped_column(String(80), index=True, unique=True)
    char: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    curso: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)  # código de curso (grupo real)
    imagen: Mapped[str] = mapped_column(Text, default="")          # data-URL base64 (reescalada en cliente)
    caption: Mapped[str | None] = mapped_column(String(140), nullable=True)
    reportes: Mapped[int] = mapped_column(Integer, default=0)
    oculto: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
