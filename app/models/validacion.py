"""
F3 - Trazabilidad de la validacion docente.

Registro INMUTABLE (audit log, G5) de cada decision del docente sobre una
pre-calificacion de la IA: guarda la propuesta de la IA (nivel + confianza), la accion
del docente (aprobar / ajustar), el nivel final, quien y cuando. Es lo que hace la nota
defendible ante reclamos y acreditacion, y separa siempre la propuesta de la decision.
"""
import uuid

from sqlalchemy import String, Float, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RegistroValidacion(UUIDMixin, Base):
    __tablename__ = "registros_validacion"

    # A que respuesta/criterio corresponde (seudonimizado: sin nombre/RUT).
    respuesta_ref: Mapped[str] = mapped_column(String(120))     # p. ej. "scan:<id>#item:3"
    criterio: Mapped[str] = mapped_column(String(255))

    # Propuesta de la IA (F2)
    nivel_ia: Mapped[str] = mapped_column(String(20))
    confianza_ia: Mapped[float] = mapped_column(Float)

    # Decision del docente (F3)
    nivel_docente: Mapped[str] = mapped_column(String(20))
    accion: Mapped[str] = mapped_column(String(20))            # aprobado | ajustado
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    docente: Mapped[str] = mapped_column(String(120))

    # Sello temporal inmutable
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
