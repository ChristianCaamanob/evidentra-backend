"""La Guarida de Runi · pausa restaurativa del estudiante (persistencia + tiempo de servidor).

Doctrina (handoff v2): el descanso NUNCA se penaliza; se mide RECUPERACIÓN y RETORNO, no tiempo
capturado. La hora de término la calcula/valida el SERVIDOR (no se confía sólo en el temporizador del
cliente): `end_at = started_at + planned_minutes` y se recalcula al extender. Identidad SEUDONIMIZADA
(`pseudo_id`), nunca RUT/nombre. Append-only en la práctica: una pausa se abre, se extiende y se cierra.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

# estado del ciclo: active → (completed | ended_early | returned | finished_day)
ESTADOS = ("active", "completed", "ended_early", "returned", "finished_day")
ZONAS = ("game", "friends", "creative", "calm", "music", "explore")


class RuniBreak(UUIDMixin, Base):
    __tablename__ = "runi_breaks"

    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)         # identidad seudonimizada
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)  # sesión de estudio de origen
    zone: Mapped[str] = mapped_column(String(20), default="calm")
    planned_minutes: Mapped[int] = mapped_column(Integer, default=5)
    extended_count: Mapped[int] = mapped_column(Integer, default=0)
    added_minutes_total: Mapped[int] = mapped_column(Integer, default=0)
    actual_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)   # real al cerrar (servidor)
    estado: Mapped[str] = mapped_column(String(16), default="active", index=True)
    outcome_source: Mapped[str | None] = mapped_column(String(40), nullable=True)  # cómo cerró (header/break_complete…)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))            # término calculado por el servidor
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
