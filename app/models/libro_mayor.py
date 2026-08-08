"""Libro Mayor de la evidencia — registro APPEND-ONLY, con hash encadenado y procedencia.

Cada vez que un ARTEFACTO metodológico del proyecto (corpus, cribado, protocolo, meta, PRISMA…)
cambia de contenido, se añade UNA entrada inmutable con:
  · `hash`      = SHA-256 del contenido canónico del artefacto en ese instante,
  · `hash_prev` = hash de la entrada anterior del MISMO artefacto (cadena tipo bitácora → a prueba de manipulación),
  · `n`         = tamaño (nº de registros/decisiones/ítems) para procedencia rápida,
  · `plano`     = método | fuente | reporte (a qué plano de la evidencia pertenece),
  · `actor_id`  = investigador que provocó el cambio (procedencia),
  · `created_at`= hora de servidor (cuándo se registró).

NO se actualiza ni se borra: es la "procedencia completa" que pedía el Handoff v2. La verdad del
esquema es Alembic; en BD nueva la crea create_all (tabla nueva) con estas columnas ya incluidas.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class LibroMayorEntrada(UUIDMixin, Base):
    __tablename__ = "libro_mayor"

    proyecto_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proyectos.id", ondelete="CASCADE"), index=True)
    clave: Mapped[str] = mapped_column(String(40), index=True)      # artefacto: corpus, cribado, meta, prisma…
    hash: Mapped[str] = mapped_column(String(64))                   # SHA-256 hex del contenido canónico
    hash_prev: Mapped[str | None] = mapped_column(String(64), nullable=True)  # cadena por artefacto
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)   # tamaño (registros/decisiones/ítems)
    plano: Mapped[str] = mapped_column(String(20), default="método")  # método | fuente | reporte
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # investigador (procedencia)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
