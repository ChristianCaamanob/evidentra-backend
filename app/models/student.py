from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.models.base import Base, UUIDMixin, TimestampMixin


class Student(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "students"
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    rut: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    matricula: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)  # nº de matrícula/ID académico (nóminas que no usan RUT)
    apellido_paterno: Mapped[str] = mapped_column(String(100), default="")
    apellido_materno: Mapped[str] = mapped_column(String(100), default="")
    nombres: Mapped[str] = mapped_column(String(100), default="")

    # Variables demograficas para analisis de equidad (DIF / invarianza). ADITIVAS y
    # nullable. Solo se usan si el estudiante CONSINTIO (G4, Ley 21.719) y de forma
    # agregada/seudonimizada (G2). Lista blanca fija en matriz_service.
    sexo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dependencia: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consiente_equidad: Mapped[bool] = mapped_column(Boolean, default=False)

    course = relationship("Course", back_populates="students")
