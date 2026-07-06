"""
Modo EN VIVO: quiz sincronico estilo Socrative sobre la misma infraestructura.

El docente abre una sesion desde una evaluacion existente (reusa su AnswerKey de
alternativas). Los estudiantes se unen con un codigo corto (o QR), el docente avanza
pregunta a pregunta, y las respuestas se corrigen al vuelo contra la pauta. Al cerrar,
la matriz binaria participante x item alimenta la misma psicometria del modulo Profesor
e Investigador (Rasch, KR-20, etc.): el modo en vivo NO es un silo, es otra forma de
aplicar una evaluacion.

Estados de la sesion:
    lobby   -> creada, estudiantes uniendose, aun sin pregunta activa (pregunta_actual=0)
    activa  -> hay una pregunta en pantalla; los participantes pueden responder
    pausada -> el docente congelo la sesion; no se aceptan respuestas
    cerrada -> terminada; se consolidan resultados (no admite mas cambios)
"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

ESTADO_LOBBY = "lobby"
ESTADO_ACTIVA = "activa"
ESTADO_PAUSADA = "pausada"
ESTADO_CERRADA = "cerrada"
ESTADOS = (ESTADO_LOBBY, ESTADO_ACTIVA, ESTADO_PAUSADA, ESTADO_CERRADA)


class SesionEnVivo(UUIDMixin, Base):
    __tablename__ = "sesiones_en_vivo"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_LOBBY,
                                        server_default=ESTADO_LOBBY, nullable=False)
    # 0 = lobby (sin pregunta); 1..N = numero de pregunta en pantalla.
    pregunta_actual: Mapped[int] = mapped_column(Integer, default=0)
    n_preguntas: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(String(10), default="A")   # el quiz en vivo usa una version
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    participantes = relationship("ParticipanteVivo", back_populates="sesion",
                                 cascade="all, delete-orphan")
    respuestas = relationship("RespuestaVivo", back_populates="sesion",
                              cascade="all, delete-orphan")


class ParticipanteVivo(UUIDMixin, Base):
    __tablename__ = "participantes_vivo"

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones_en_vivo.id"), index=True)
    alias: Mapped[str] = mapped_column(String(80))
    student_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # si es un alumno de la nomina
    token: Mapped[str] = mapped_column(String(48))     # autoriza a responder sin login
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionEnVivo", back_populates="participantes")


class RespuestaVivo(UUIDMixin, Base):
    __tablename__ = "respuestas_vivo"
    # una sola respuesta por participante y pregunta (no se puede responder dos veces).
    __table_args__ = (UniqueConstraint("participante_id", "question_number", name="uq_resp_vivo"),)

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones_en_vivo.id"), index=True)
    participante_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("participantes_vivo.id"), index=True)
    question_number: Mapped[int] = mapped_column(Integer)
    respuesta: Mapped[str] = mapped_column(String(10))
    correcta: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionEnVivo", back_populates="respuestas")
