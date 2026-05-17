from sqlalchemy import String, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Course(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    program_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_learning_structure: Mapped[bool] = mapped_column(Boolean, default=False)
    grading_scale: Mapped[str | None] = mapped_column(String(100), nullable=True)
    passing_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_score_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    assessments = relationship("Assessment", back_populates="course", cascade="all, delete-orphan")
    students = relationship("Student", back_populates="course", cascade="all, delete-orphan")
