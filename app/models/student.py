from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.models.base import Base, UUIDMixin, TimestampMixin


class Student(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "students"
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    rut: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    apellido_paterno: Mapped[str] = mapped_column(String(100), default="")
    apellido_materno: Mapped[str] = mapped_column(String(100), default="")
    nombres: Mapped[str] = mapped_column(String(100), default="")

    course = relationship("Course", back_populates="students")
