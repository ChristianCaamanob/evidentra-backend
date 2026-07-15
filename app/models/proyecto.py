"""Proyecto de investigación — contenedor persistente del trabajo del investigador.

Resuelve cuatro necesidades que antes no existían:
  1. Varios proyectos independientes por investigador (antes el análisis era efímero por evaluación).
  2. Tres tipos: 'datos' (análisis de datos propios), 'revision' (RS + meta), 'experimental'.
  3. Selección persistida de cursos/evaluaciones/grupos (proyecto 'datos').
  4. Persistencia del corpus + cribado + protocolo (proyecto 'revision').

`datos` es un JSON flexible cuya forma depende del tipo:
  · datos       → {"course_ids": [...], "assessment_ids": [...], "grupos": [...], "dataset": {...}}
  · revision    → {"protocolo": {...PROSPERO...}, "corpus": [...], "cribado": {doi: decisión}, "meta": {...}}
  · experimental→ {"pico": {...}, "diseno": "...", "protocolo": {...SPIRIT...}}
"""
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

TIPOS = ("datos", "revision", "experimental")
ESTADOS = ("borrador", "activo", "archivado")


class Proyecto(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "proyectos"

    investigador_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))            # datos | revision | experimental
    titulo: Mapped[str] = mapped_column(String(300))
    pregunta: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="borrador")
    datos: Mapped[dict] = mapped_column(JSON, default=dict)  # configuración/estado flexible por tipo

    investigador = relationship("Teacher")
