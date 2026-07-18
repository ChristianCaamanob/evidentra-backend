import uuid

from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Scan(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "scans"

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    student_identifier: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    detected_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    ambiguity_count: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_ambiguity_count: Mapped[int] = mapped_column(Integer, default=0)
    review_reasons_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sheet_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_ocr_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Origen de la evidencia: "omr" (hoja escaneada) | "en_vivo" (sala sincrónica). NULL = omr
    # (histórico). Permite filtrar la psicometría por tipo de instrumento y deduplicar por alumno
    # sin mezclar orígenes en silencio (norte: consultar por tipo de prueba).
    origen: Mapped[str | None] = mapped_column(String(20), nullable=True)

    assessment = relationship("Assessment", back_populates="scans")
