"""
Passkeys (WebAuthn) del STAFF — inicio de sesión con huella / rostro (biometría del dispositivo).

Solo se guarda la CLAVE PÚBLICA + credentialId; nunca la biometría (esa vive en el dispositivo).
Un docente/investigador/director/admin puede tener varias passkeys (varios equipos). El challenge
de cada ceremonia NO se persiste: viaja en un token JWT corto (stateless, sirve multi-worker).
"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class TeacherPasskey(UUIDMixin, Base):
    __tablename__ = "teacher_passkeys"

    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(String(1024))     # base64 de la clave pública COSE
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(80), default="passkey")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
