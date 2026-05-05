import uuid

from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Assessment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assessments"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="draft")
    assessment_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_versions: Mapped[bool] = mapped_column(Boolean, default=False)
    version_count: Mapped[int] = mapped_column(Integer, default=1)
    has_answer_key: Mapped[bool] = mapped_column(Boolean, default=False)
    briefing_level: Mapped[str] = mapped_column(String(50), default="initial")

    course = relationship("Course", back_populates="assessments")
    answer_key = relationship("AnswerKey", back_populates="assessment", uselist=False, cascade="all, delete-orphan")
    scans = relationship("Scan", back_populates="assessment", cascade="all, delete-orphan")
