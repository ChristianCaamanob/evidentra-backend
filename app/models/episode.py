"""
North Star — Episodio de Aprendizaje Verificado (EAV).

Un episodio cuenta como EAV cuando tiene, registrados: objetivo (RA) → acción/recuperación activa →
respuesta + CONFIANZA → feedback → cierre → comprobación (inmediata o diferida).

Dominio: APRENDIZAJE (evidencia). Identidad SEUDONIMIZADA (`pseudo_id`), nunca RUT/nombre aquí.
Append-only en la práctica: no se modifican históricos salvo el cierre/verificación del propio episodio.
"""
from sqlalchemy import String, Boolean, Integer, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.models.base import Base, UUIDMixin


class Episode(UUIDMixin, Base):
    __tablename__ = "learning_episodes"

    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)      # identidad seudonimizada
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ra: Mapped[str | None] = mapped_column(String(120), nullable=True)  # Resultado de Aprendizaje (objetivo)
    objetivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origen: Mapped[str | None] = mapped_column(String(40), nullable=True)  # silabo|en_vivo|desarrollo|repaso...
    sintesis: Mapped[str | None] = mapped_column(Text, nullable=True)   # cierre
    feedback_given: Mapped[bool] = mapped_column(Boolean, default=False)
    check_immediate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # correcto en comprobación inmediata
    completo: Mapped[bool] = mapped_column(Boolean, default=False)      # objetivo+respuesta+feedback+cierre
    verificado: Mapped[bool] = mapped_column(Boolean, default=False)    # + comprobación (inmediata o diferida)
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)


class ConfidenceObs(UUIDMixin, Base):
    """Observación de confianza por ítem (calibración metacognitiva)."""
    __tablename__ = "learning_confidence_obs"

    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_episodes.id"), index=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ra: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_id: Mapped[str] = mapped_column(String(80))
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # nulo = auto-reporte sin corrección (sílabo)
    confidence: Mapped[int] = mapped_column(Integer, default=0)         # 0–100, ANTES del feedback
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    help_used: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetentionCheck(UUIDMixin, Base):
    """Comprobación diferida (spaced retrieval): distingue aprendizaje real de rendimiento inmediato."""
    __tablename__ = "learning_retention_checks"

    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_episodes.id"), index=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ra: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ventana: Mapped[str] = mapped_column(String(12))                    # 24-48h | 7d | 21-30d
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # null hasta que se responde
    scheduled_for: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))
    done_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
