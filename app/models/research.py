"""
Research OS v1 · Fase 1 — fundación de la capa de investigación (separada de analítica operativa y de la
evaluación académica). Identidad SEUDÓNIMA de investigación (`participant_pseudo`), desacoplada de la tabla
institucional; la llave de reidentificación NO vive aquí. Eventos APPEND-ONLY, idempotentes por `event_id`.
"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class ResearchParticipant(Base):
    __tablename__ = "research_participants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchConsent(Base):
    __tablename__ = "research_consents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(16), default="not_asked")   # not_asked|consented|declined|revoked
    version: Mapped[str] = mapped_column(String(16), default="v1")
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResearchEvent(Base):
    __tablename__ = "research_events"

    server_event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)   # idempotencia (cliente)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0.0")
    event_name: Mapped[str] = mapped_column(String(48), index=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[str] = mapped_column(String(48), index=True)
    study_id: Mapped[str] = mapped_column(String(80), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    assignment_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    app_version: Mapped[str] = mapped_column(String(40))
    content_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    occurred_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchAuditLog(Base):
    __tablename__ = "research_audit_log"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor_pseudo_role: Mapped[str] = mapped_column(String(40), default="")   # researcher|auditor|system
    action: Mapped[str] = mapped_column(String(60), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
