"""
Anuncios del docente (v2.0) — el profesor publica un aviso al curso y llega en tiempo real
a los estudiantes: notificación push (pantalla bloqueada) + bandeja dentro de la app.

Persistente por curso (a diferencia de la capa social efímera): un anuncio es comunicación
docente→clase, no interacción privada entre pares.
"""
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class Anuncio(UUIDMixin, Base):
    __tablename__ = "anuncios_curso"

    course_id: Mapped[str] = mapped_column(String(64), index=True)
    titulo: Mapped[str] = mapped_column(String(140), default="")
    cuerpo: Mapped[str] = mapped_column(String(1000), default="")
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
