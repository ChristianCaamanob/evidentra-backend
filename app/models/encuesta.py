"""
Encuestas de Runi: el docente pregunta, el curso responde, todos ven el resultado.

Trae una LISTA BLANCA de RUT (`solo_ruts`). Nació de un pedido concreto —pilotear la
función en un solo perfil antes de soltarla al curso— pero queda como capacidad general:
cualquier encuesta puede estrenarse con dos o tres personas antes de ser masiva. Vacía o
nula = visible para todo el curso.
"""
import uuid

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class Encuesta(UUIDMixin, Base):
    __tablename__ = "encuestas"

    # Ámbito: el CÓDIGO del agente de sílabo (igual que el resto de lo del alumno), para que
    # el estudiante pueda pedirla sin conocer el id interno del curso.
    silabo: Mapped[str] = mapped_column(String(12), index=True)
    pregunta: Mapped[str] = mapped_column(String(300), default="")
    # ["Sí", "No", "Depende"] — texto libre; el orden que ve el alumno es este.
    opciones: Mapped[list | None] = mapped_column(JSON, nullable=True)
    anonima: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    abierta: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Lista blanca de RUT normalizados. Vacía = todo el curso.
    solo_ruts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # ¿El estudiante ve el recuento del curso? Por defecto NO: en una votación, saber lo
    # que eligieron los demás arrastra el voto propio.
    ver_resultados: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # ¿Puede cambiar su respuesta? Por defecto NO: se responde una vez y queda.
    permite_cambio: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Ventana de la encuesta. Se guardan en UTC; el cliente las pinta en su hora local.
    # Nulas = sin límite por ese lado (abierta desde ya / sin cierre automático).
    abre_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    cierra_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    creada_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EncuestaVoto(UUIDMixin, Base):
    __tablename__ = "encuesta_votos"

    encuesta_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encuestas.id", ondelete="CASCADE"), index=True)
    # Un voto por persona: cambiar de opinión ACTUALIZA el voto, no agrega otro.
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opcion: Mapped[int] = mapped_column(default=0)          # índice dentro de `opciones`
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
