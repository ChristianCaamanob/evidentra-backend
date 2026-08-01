"""
Cuenta GLOBAL del alumno (app Runi) — identidad propia con passkey.

A diferencia de Student (ligado a un curso) y de AsistenciaMatricula (nómina por curso),
StudentAccount es UNA cuenta del estudiante, independiente del curso: se registra una vez
(RUT + nombre + apellido + passkey) y con ella entra a cualquier curso al que lo inviten.

Solo se guarda la CLAVE PÚBLICA + credentialId de la passkey; nunca la biometría (esa vive
en el dispositivo). Un alumno puede tener varias passkeys (varios equipos). El challenge de
cada ceremonia NO se persiste: viaja en un token JWT corto (stateless, sirve multi-worker).
"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class StudentAccount(UUIDMixin, Base):
    __tablename__ = "student_accounts"

    rut: Mapped[str] = mapped_column(String(20), unique=True, index=True)   # RUT normalizado (cuerpo+dv, sin puntos ni guion)
    nombres: Mapped[str] = mapped_column(String(120), default="")
    apellido_paterno: Mapped[str] = mapped_column(String(120), default="")
    apellido_materno: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    passkeys = relationship("StudentPasskey", back_populates="cuenta", cascade="all, delete-orphan")


class StudentPasskey(UUIDMixin, Base):
    __tablename__ = "student_passkeys"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("student_accounts.id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(String(1024))     # base64 de la clave pública COSE
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(80), default="passkey")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cuenta = relationship("StudentAccount", back_populates="passkeys")
