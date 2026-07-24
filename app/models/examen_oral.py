"""
5º módulo · EXAMEN ORAL — modelo de datos (F1 fundación).

Tres capas de integridad evaluativa (doctrina CEO):
  Capa 1 · audio original  → vive en el equipo del profesor (IndexedDB); aquí solo su referencia.
  Capa 2 · transcripción literal → conserva errores conceptuales, nunca se sobrescribe.
  Capa 3 · versión normalizada + síntesis → corrige solo fonético/orto/gramática; no agrega nada.

Gobernanza: la IA PROPONE (puntaje_ia); el docente FIJA y valida (puntaje_docente), con sello
temporal — misma doctrina que RegistroValidacion (G1). Nunca publica sin validación docente.
"""
import uuid

from sqlalchemy import String, Integer, Float, JSON, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

# Estados de la sesión (mapa de color en la UI): gris/azul/rojo/amarillo/verde/morado.
OE_NO_INICIADA = "no_iniciada"   # gris
OE_REFLEXION = "reflexion"       # azul
OE_GRABANDO = "grabando"         # rojo
OE_REVISION = "revision"         # amarillo
OE_REVISADA = "revisada"         # verde
OE_PUBLICADA = "publicada"       # morado
OE_ESTADOS = (OE_NO_INICIADA, OE_REFLEXION, OE_GRABANDO, OE_REVISION, OE_REVISADA, OE_PUBLICADA)


class OralExamSesion(UUIDMixin, Base):
    __tablename__ = "oral_exam_sesiones"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    student_id: Mapped[str] = mapped_column(String(64), index=True)
    evaluador: Mapped[str] = mapped_column(String(120), default="docente")
    estado: Mapped[str] = mapped_column(String(20), default=OE_NO_INICIADA,
                                        server_default=OE_NO_INICIADA, nullable=False)
    # Config congelada de la sesión: criterios+pesos, ponderación de preguntas, tiempos, escala.
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audio_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # clave IndexedDB local
    # Modo A (QR): token público del canal en vivo (el celular del estudiante lee/postea con él).
    vivo_token: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    duracion_seg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nota final (validada por el docente) + % logro. Nullable hasta publicar.
    nota_final: Mapped[float | None] = mapped_column(Float, nullable=True)
    logro_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    iniciada_en: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizada_en: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    segmentos = relationship("OralExamSegmento", back_populates="sesion",
                             cascade="all, delete-orphan", order_by="OralExamSegmento.pregunta_numero")


class OralExamSegmento(UUIDMixin, Base):
    __tablename__ = "oral_exam_segmentos"

    sesion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oral_exam_sesiones.id"), nullable=False)
    pregunta_numero: Mapped[int] = mapped_column(Integer, default=0)
    answer_key_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    t_inicio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_fin_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Capa 2 — literal (nunca se sobrescribe). Capa 3 — normalizada + síntesis.
    transcripcion_literal: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_normalizada: Mapped[str | None] = mapped_column(Text, nullable=True)
    sintesis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    correcciones_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # historial fonético
    sin_respuesta: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("OralExamSesion", back_populates="segmentos")
    evaluaciones = relationship("OralExamEvaluacion", back_populates="segmento",
                                cascade="all, delete-orphan")


class OralExamEvaluacion(UUIDMixin, Base):
    __tablename__ = "oral_exam_evaluaciones"

    segmento_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oral_exam_segmentos.id"), nullable=False)
    criterio: Mapped[str] = mapped_column(String(255))
    peso_criterio: Mapped[float] = mapped_column(Float, default=25.0)   # % del criterio
    puntaje_ia: Mapped[float | None] = mapped_column(Float, nullable=True)      # 0-1 propuesto
    puntaje_docente: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-1 validado (G1)
    evidencia_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # fragmento + marca temporal
    justificacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    accion: Mapped[str | None] = mapped_column(String(20), nullable=True)      # aprobado | ajustado
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    segmento = relationship("OralExamSegmento", back_populates="evaluaciones")
