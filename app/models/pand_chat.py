"""
Chat de la Pandilla — mensajes de grupo por curso (solo miembros verificados del MISMO curso).
Retención corta rolling (7 días): conversación viva, sin historial permanente. Audiencia adulta.
"""
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PandChat(UUIDMixin, Base):
    __tablename__ = "pand_chat"

    curso: Mapped[str] = mapped_column(String(40), index=True)          # course_id (grupo real)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    char: Mapped[str | None] = mapped_column(String(40), nullable=True)
    texto: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
