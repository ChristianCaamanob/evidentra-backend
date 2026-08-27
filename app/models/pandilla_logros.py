"""
F7 · Señales de Maestría compartida (Pandilla) para las medallas 10-12.

- PeerSupport: apoyo de un estudiante a otro; SOLO cuenta cuando es VALIDADO (por quien lo recibió o
  un docente). Anti-farming: tope diario 2 validados por quien ayuda; el mismo apoyo no se duplica.
- GroupGoal / GoalContribution: meta grupal de la Pandilla; al completarse, sus aportantes acreditan.
- LongitudinalMastery: el docente/curso marca la maestría longitudinal de un estudiante (medalla 12).

Identidad SEUDONIMIZADA (`pseudo_id`), dominio APRENDIZAJE. Nada de esto castiga; solo suma evidencia real.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PeerSupport(Base):
    __tablename__ = "pandilla_peer_support"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    helper_pseudo: Mapped[str] = mapped_column(String(80), index=True)      # quien ayuda
    beneficiary_pseudo: Mapped[str] = mapped_column(String(80), index=True)  # quien recibe
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="explicacion")     # explicacion|repaso|recurso
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_by: Mapped[str | None] = mapped_column(String(80), nullable=True)  # beneficiario | docente:<email>
    day: Mapped[str] = mapped_column(String(10), index=True, default="")     # YYYY-MM-DD (para el tope diario)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GroupGoal(Base):
    __tablename__ = "pandilla_group_goal"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    sala_code: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    titulo: Mapped[str] = mapped_column(String(160), default="")
    meta_n: Mapped[int] = mapped_column(Integer, default=5)
    progreso: Mapped[int] = mapped_column(Integer, default=0)
    completado: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class GoalContribution(Base):
    __tablename__ = "pandilla_goal_contribution"
    __table_args__ = (UniqueConstraint("goal_id", "pseudo_id", name="uq_aporte_por_meta"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    goal_id: Mapped[str] = mapped_column(String(40), index=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    aporte: Mapped[int] = mapped_column(Integer, default=0)
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)   # quién aportó (un grupo de amigos no lee pseudo_ids)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LongitudinalMastery(Base):
    __tablename__ = "pandilla_longitudinal_mastery"
    __table_args__ = (UniqueConstraint("course_id", "pseudo_id", name="uq_maestria_por_curso"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    granted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)  # docente
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
