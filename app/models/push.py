"""
Web Push (v2.0) — notificaciones a la pantalla bloqueada de la PWA del alumno.

- PushConfig     : singleton con el par de llaves VAPID (auto-generado en el primer arranque; la privada
                   vive SOLO en la BD del cliente, nunca en el código ni en el repo).
- PushSubscription: una suscripción de navegador por dispositivo (endpoint único), ligada al owner_key
                    del alumno (sid:<uuid> | dev:<device>), igual que la agenda.
- StudentCourseFollow: qué cursos sigue el alumno → para saber a quién avisar de cada evaluación.
- PushSent       : dedupe (una evaluación × alumno × hito se envía una sola vez).
"""
import uuid

from sqlalchemy import String, DateTime, Text, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PushConfig(UUIDMixin, Base):
    __tablename__ = "push_config"

    vapid_public: Mapped[str] = mapped_column(Text, default="")     # application server key (base64url, seguro)
    vapid_private: Mapped[str] = mapped_column(Text, default="")    # PEM privada (secreto — solo en esta BD)
    subject: Mapped[str] = mapped_column(String(200), default="mailto:runi@evalys.cl")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(UUIDMixin, Base):
    __tablename__ = "push_subscriptions"

    owner_key: Mapped[str] = mapped_column(String(80), index=True)  # sid:<uuid> | dev:<device>
    endpoint: Mapped[str] = mapped_column(Text)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(Text, default="")
    auth: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudentCourseFollow(UUIDMixin, Base):
    __tablename__ = "student_course_follows"
    __table_args__ = (UniqueConstraint("owner_key", "course_id", name="uq_follow_owner_course"),)

    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), index=True)
    silabo_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushNativeToken(UUIDMixin, Base):
    """Token de push NATIVO (APNs/FCM) del shell Capacitor. Se captura desde ya; el envío nativo se activa
    cuando existan las credenciales (APNs .p8 / FCM) en variables de entorno — hasta entonces se conserva."""
    __tablename__ = "push_native_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_native_token"),)

    owner_key: Mapped[str] = mapped_column(String(80), index=True)   # sid:<uuid> | dev:<device>
    platform: Mapped[str] = mapped_column(String(12), default="")    # "ios" | "android"
    token: Mapped[str] = mapped_column(Text)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSent(UUIDMixin, Base):
    __tablename__ = "push_sent"
    __table_args__ = (UniqueConstraint("eval_id", "owner_key", "hito", name="uq_sent_eval_owner_hito"),)

    eval_id: Mapped[str] = mapped_column(String(60), index=True)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    hito: Mapped[str] = mapped_column(String(20))  # "84" | "7" | "3" | "1" | "0"
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
