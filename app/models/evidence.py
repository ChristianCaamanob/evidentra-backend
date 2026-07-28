"""Evalys Evidence Core — override editable de expedientes científicos.

El catálogo base vive en código (evidence_core_service). Esta tabla guarda las EDICIONES que hace el
"responsable de aprobación" desde la app: se fusiona sobre el expediente base (la BD manda). Así el
catálogo es versionable y gobernable sin desplegar código, conservando la fuente curada por defecto.
"""
import uuid

from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class EvidenceExpediente(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_expedientes"

    clave: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSON)                                  # override (dossier completo o parcial)
    version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    responsable: Mapped[str | None] = mapped_column(String(160), nullable=True)
    actualizado_por: Mapped[str | None] = mapped_column(String(160), nullable=True)  # email del editor
