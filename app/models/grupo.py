"""
Grupos de trabajo para evaluaciones con puntaje GRUPAL (p. ej. una presentacion).

Diseno para consistencia + trazabilidad: el criterio grupal se valida UNA VEZ por grupo
(sujeto = el grupo), y la nota de cada integrante lo REFERENCIA -no se copia-. Asi dos
integrantes no pueden diferir en un criterio grupal (consistencia) y el audit muestra una
sola decision grupal + la membresia (trazabilidad).

La membresia (GrupoIntegrante) es append-only: fijar el grupo es el 'snapshot' que hace la
nota reproducible aunque despues cambien las conformaciones.
"""
import uuid

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class Grupo(UUIDMixin, Base):
    __tablename__ = "grupos"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    integrantes = relationship("GrupoIntegrante", back_populates="grupo",
                               cascade="all, delete-orphan")


class GrupoIntegrante(UUIDMixin, Base):
    __tablename__ = "grupo_integrantes"

    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos.id"))
    student_id: Mapped[str] = mapped_column(String(64), index=True)   # id del Student (str)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    grupo = relationship("Grupo", back_populates="integrantes")
