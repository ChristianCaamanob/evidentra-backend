"""
B9/B10 · Runi Visual System v3 — motor de logros (gratificación atada al EAV).

`MedalUnlock` es el **recibo de desbloqueo INMUTABLE** (unlockReceipt del spec): guarda la versión de
regla, el XP al momento y la evidencia (conteos de señales) que justificó la medalla. Nunca se recalcula
retroactivamente con reglas nuevas. Identidad SEUDONIMIZADA (`pseudo_id`), dominio APRENDIZAJE.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class MedalUnlock(Base):
    __tablename__ = "logros_medal_unlock"
    __table_args__ = (UniqueConstraint("pseudo_id", "medal_id", name="uq_medal_por_alumno"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    medal_id: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(48), default="")
    rule_version: Mapped[str] = mapped_column(String(16), default="")
    xp_at_unlock: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # snapshot de señales al desbloquear
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
