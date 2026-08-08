"""
Personalización v4 — persistencia POR ESTUDIANTE (no por dispositivo) del "Mi espacio con Runi".

- Se guarda por `pseudo_id` seudónimo del alumno (`stu:<device-uuid>`), desacoplado de la identidad
  institucional (mismo criterio que push/silabo/research). NUNCA es una puntuación académica: son solo
  preferencias de interfaz (ambiente, acento, superficie, luz, intensidad, movimiento, presencia).
- El cliente aplica primero su copia local (sin destello) y reconcilia con el servidor por `updated_at_client`
  (last-write-wins). El servidor conserva la preferencia del usuario para que sobreviva a limpiar caché o
  reinstalar la PWA, y para seguir al alumno si más adelante tiene cuenta.
"""
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RuniPref(UUIDMixin, Base):
    __tablename__ = "runi_prefs"

    pseudo_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)   # stu:<uuid>
    prefs_json: Mapped[str] = mapped_column(Text, default="{}")                   # whitelist de preferencias (JSON)
    schema_version: Mapped[int] = mapped_column(default=1)
    updated_at_client: Mapped[str] = mapped_column(String(40), default="")        # ISO del cliente (reconciliación)
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
