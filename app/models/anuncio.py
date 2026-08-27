"""
Anuncios del docente (v2.0) — el profesor publica un aviso al curso y llega en tiempo real
a los estudiantes: notificación push (pantalla bloqueada) + bandeja dentro de la app.

Persistente por curso (a diferencia de la capa social efímera): un anuncio es comunicación
docente→clase, no interacción privada entre pares.
"""
from sqlalchemy import String, DateTime, func, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class Anuncio(UUIDMixin, Base):
    __tablename__ = "anuncios_curso"

    course_id: Mapped[str] = mapped_column(String(64), index=True)
    titulo: Mapped[str] = mapped_column(String(140), default="")
    cuerpo: Mapped[str] = mapped_column(String(1000), default="")
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Adjunto opcional: un ENLACE (Drive/web) o un archivo pequeño guardado en la fila.
    # Un aviso suele venir con algo que mirar (la pauta, el cambio de sala, la lectura).
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    archivo_nombre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    archivo_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    archivo_datos: Mapped[str | None] = mapped_column(Text, nullable=True)   # base64
    tamano: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
