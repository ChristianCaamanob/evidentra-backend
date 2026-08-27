"""
Grupos de la Pandilla — el equipo que los propios ESTUDIANTES forman para trabajar juntos.

No confundir con `Grupo` (app/models/grupo.py), que lo arma el DOCENTE dentro de una
evaluación para poner nota grupal. Este lo crea un alumno, y sus compañeros entran
escaneando un QR con el código de unión: nadie tiene que pasar listas ni correos.

Vive dentro de un curso (`curso` = código del agente de sílabo, como el resto de la capa
social) y el dueño de cada membresía es el `owner_key` que ya usa la Pandilla
(`rut:<rut>` tras identificarse contra la nómina, o `sid:<uuid>` con cuenta).
"""
from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.models.base import Base, UUIDMixin


class PandGrupo(UUIDMixin, Base):
    __tablename__ = "pand_grupos"

    curso: Mapped[str] = mapped_column(String(40), index=True)          # código del sílabo
    codigo: Mapped[str] = mapped_column(String(10), unique=True, index=True)   # el que va en el QR
    nombre: Mapped[str] = mapped_column(String(60), default="Mi grupo")
    creador_owner: Mapped[str] = mapped_column(String(80), index=True)
    emoji: Mapped[str | None] = mapped_column(String(40), nullable=True)
    abierto: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PandGrupoMiembro(UUIDMixin, Base):
    __tablename__ = "pand_grupo_miembros"
    # Un alumno no puede estar dos veces en el mismo grupo (escanear el QR dos veces es
    # normal: se reentra, no se duplica).
    __table_args__ = (UniqueConstraint("grupo_id", "owner_key", name="uq_grupo_owner"),)

    grupo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pand_grupos.id", ondelete="CASCADE"), index=True)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    nombre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    char: Mapped[str | None] = mapped_column(String(40), nullable=True)   # personaje elegido
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
