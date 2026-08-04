"""
Notas de la Pandilla (v2.0 social) — nota corta y EFÍMERA que el estudiante publica y que
aparece como burbuja sobre su avatar para su grupo (inspirado en las "Notes" de Instagram).

Personal por alumno (owner_key = sid:<uuid> | dev:<device>). Una nota activa por estudiante
(se sobreescribe). Efímera: caduca a las 24 h; se filtra por created_at en el servicio.
Doctrina de privacidad: voluntario · temporal · revocable · sin historial.
"""
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PandNota(UUIDMixin, Base):
    __tablename__ = "pand_notas"

    owner_key: Mapped[str] = mapped_column(String(80), index=True, unique=True)
    texto: Mapped[str] = mapped_column(String(90), default="")
    char: Mapped[str | None] = mapped_column(String(40), nullable=True)     # personaje/avatar
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)   # nombre visible
    curso: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)  # código de curso (grupo real)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
