"""
Material del curso (v2.0) — biblioteca que el DOCENTE comparte con sus estudiantes:
programa, calendarización, apuntes, libros, artículos, enlaces, etc.

Cada material es un ENLACE (url a Drive/web) o un ARCHIVO subido (guardado en la BD como base64,
con tope de tamaño; para libros pesados conviene enlace). El alumno lo lee por el código del agente Runi.
"""
import uuid

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class MaterialCurso(UUIDMixin, Base):
    __tablename__ = "materiales_curso"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200), default="")
    tipo: Mapped[str] = mapped_column(String(30), default="apunte")   # programa/calendario/apunte/libro/articulo/enlace/otro
    descripcion: Mapped[str | None] = mapped_column(String(400), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)       # enlace externo (Drive/web)
    archivo_nombre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    archivo_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    archivo_datos: Mapped[str | None] = mapped_column(Text, nullable=True)   # base64 (solo archivos pequeños)
    tamano: Mapped[int] = mapped_column(Integer, default=0)            # bytes
    orden: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
