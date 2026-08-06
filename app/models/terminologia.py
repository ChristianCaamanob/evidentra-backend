"""
F5 · Gobernanza terminológica — glosario versionado por disciplina (Runi Visual System v3).

Un curso fija un `profile_id` (edición revisada y firmada por un especialista); cada concepto usa un
`concept_id` estable y su etiqueta visible es el `preferred_term` vigente. Cambiar el glosario NO reescribe
evidencias históricas: una edición nueva SUPERSEDE a la anterior (ambas se conservan). Los perfiles publicados
son inmutables; editar = publicar una edición nueva con `supersedes`. Sinónimos y términos obsoletos se
guardan para normalizar importaciones y advertir (nunca sustituir en silencio).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class TermProfile(Base):
    __tablename__ = "term_profile"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)  # ej. "anatomia-udla-2026-v1"
    discipline_id: Mapped[str] = mapped_column(String(60), index=True)            # ej. "anatomia"
    locale: Mapped[str] = mapped_column(String(12), default="es-CL")
    source_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)  # p.ej. Terminologia Anatomica
    source_edition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(String(400), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)   # especialista que firma
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String(80), nullable=True)     # profile_id de la edición anterior
    estado: Mapped[str] = mapped_column(String(16), default="publicado")          # publicado (inmutable)
    version: Mapped[int] = mapped_column(Integer, default=1)
    n_terms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TermEntry(Base):
    __tablename__ = "term_entry"
    __table_args__ = (UniqueConstraint("profile_id", "concept_id", name="uq_concepto_por_perfil"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(80), index=True)
    concept_id: Mapped[str] = mapped_column(String(80), index=True)
    preferred_term: Mapped[str] = mapped_column(String(240), default="")
    synonyms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    deprecated_terms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    norm_index: Mapped[str | None] = mapped_column(Text, nullable=True)   # texto normalizado (preferido+sinónimos+obsoletos) para búsqueda


class CourseTermBinding(Base):
    __tablename__ = "course_term_binding"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)   # código de sílabo
    profile_id: Mapped[str] = mapped_column(String(80), index=True)
    bound_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
