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
    # ── Recurrencia ──────────────────────────────────────────────────────────────────
    # Un comunicado puede ser de una vez ("el examen se cambió de sala") o repetirse mientras siga
    # vigente ("recuerden traer el delantal cada práctico"). Se repite el AVISO, no el anuncio: la
    # bandeja del alumno conserva una sola entrada, o cada recordatorio la inundaría de duplicados.
    repeticion: Mapped[str] = mapped_column(String(16), default="unica", server_default="unica")
    # Hasta cuándo se repite. OBLIGATORIA en los recurrentes: un aviso que se repite para siempre
    # deja de ser un aviso y pasa a ser ruido que nadie mira.
    repetir_hasta: Mapped[str | None] = mapped_column(String(10), nullable=True)   # "YYYY-MM-DD"
    veces_enviado: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    ultimo_envio: Mapped[str | None] = mapped_column(String(10), nullable=True)    # "YYYY-MM-DD"
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
