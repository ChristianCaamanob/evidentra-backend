from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin
from datetime import datetime

class PasswordResetToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "password_reset_tokens"
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("teachers.id"), nullable=False)
    token: Mapped[str]      = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool]      = mapped_column(Boolean, default=False)
