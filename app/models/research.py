"""
Research OS v1 · Fase 1 — fundación de la capa de investigación (separada de analítica operativa y de la
evaluación académica). Identidad SEUDÓNIMA de investigación (`participant_pseudo`), desacoplada de la tabla
institucional; la llave de reidentificación NO vive aquí. Eventos APPEND-ONLY, idempotentes por `event_id`.
"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
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


class ResearchAssignment(Base):
    __tablename__ = "research_assignments"
    __table_args__ = (UniqueConstraint("experiment_id", "participant_pseudo", name="uq_asignacion_por_experimento"),)

    assignment_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    study_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    experiment_id: Mapped[str] = mapped_column(String(80), index=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), index=True)
    condition_id: Mapped[str] = mapped_column(String(80))
    stratum_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    seed: Mapped[str] = mapped_column(String(64), default="")
    algorithm_version: Mapped[str] = mapped_column(String(24), default="v1-hash")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchDeviation(Base):
    __tablename__ = "research_deviations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(80), index=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="deviation")   # exclusion | deviation
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchAssessment(Base):
    """Medición longitudinal: una fila por (participante, concepto, ventana). El scheduler la crea al completar la
    intervención; el estudiante la responde cuando vence, con un ÍTEM PARALELO distinto (nunca el mismo)."""
    __tablename__ = "research_assessments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), index=True)
    concept_id: Mapped[str] = mapped_column(String(100), index=True)
    window: Mapped[str] = mapped_column(String(16), index=True)   # baseline|immediate|day_7|day_21|day_45
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, index=True)
    item_id: Mapped[str] = mapped_column(String(100), default="")   # ítem paralelo elegido
    item_set_version: Mapped[str] = mapped_column(String(24), default="items-v1")
    difficulty_band: Mapped[int] = mapped_column(default=3)
    transfer_distance: Mapped[str] = mapped_column(String(16), default="near")   # near|far
    done: Mapped[bool] = mapped_column(default=False)
    score01: Mapped[float | None] = mapped_column(nullable=True)
    confidence01: Mapped[float | None] = mapped_column(nullable=True)
    active_seconds: Mapped[int | None] = mapped_column(nullable=True)
    reminded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ResearchAIReview(Base):
    __tablename__ = "research_ai_reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    participant_pseudo: Mapped[str] = mapped_column(String(80), index=True)
    concept_id: Mapped[str] = mapped_column(String(100), index=True)
    modality: Mapped[str] = mapped_column(String(24), default="teach_runi")
    ai_decision: Mapped[str] = mapped_column(String(24), default="scored")   # scored|abstained|needs_human_review|not_used
    score01: Mapped[float | None] = mapped_column(nullable=True)
    uncertainty01: Mapped[float] = mapped_column(default=0.0)
    criterion_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(24), default="teach-runi-v1")
    model_version: Mapped[str] = mapped_column(String(48), default="")
    prompt_version: Mapped[str] = mapped_column(String(24), default="v1")
    human_review_required: Mapped[bool] = mapped_column(default=False)
    human_verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)   # agree|adjust|reject (docente)
    human_score01: Mapped[float | None] = mapped_column(nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ResearchAuditLog(Base):
    __tablename__ = "research_audit_log"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor_pseudo_role: Mapped[str] = mapped_column(String(40), default="")   # researcher|auditor|system
    action: Mapped[str] = mapped_column(String(60), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
