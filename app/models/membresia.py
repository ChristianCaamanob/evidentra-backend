"""RBAC por ÁMBITO (gobernanza escalonada).

Una `Membresia` otorga a un usuario acceso a una SALA (nivel: departamento/carrera/escuela/facultad/
decanatura) sobre un ÁMBITO concreto (una unidad; "" = todo el nivel), con acciones permitidas,
nivel de detalle de datos, FINALIDAD (para auditoría) y VIGENCIA (temporalidad). El acceso a dato
personal NO va por la membresía: exige un registro explícito en `AccesoPersonalLog` (finalidad +
justificación + plazo; emergencia auditada). Doctrina: rol × ámbito × finalidad × detalle × acción ×
temporalidad, con descenso progresivo controlado — nunca automático hasta la persona.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

NIVELES = ("departamento", "carrera", "escuela", "facultad", "decanatura")
ACCIONES = ("observar", "comentar", "solicitar", "aprobar", "intervenir")
DETALLE = ("agregado", "seudonimizado", "identificable")
# Rango jerárquico: menor = más alto/agregado. Un ámbito de rango r puede DESCENDER a rangos mayores.
RANGO = {"decanatura": 0, "facultad": 0, "escuela": 1, "carrera": 2, "departamento": 3}


class Membresia(UUIDMixin, Base):
    __tablename__ = "membresias"

    teacher_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    nivel: Mapped[str] = mapped_column(String(20))                 # departamento|carrera|escuela|facultad|decanatura
    ambito: Mapped[str] = mapped_column(String(160), default="")   # unidad concreta ("" = todo el nivel)
    acciones: Mapped[str] = mapped_column(String(120), default="observar")  # csv de ACCIONES
    detalle: Mapped[str] = mapped_column(String(20), default="agregado")    # agregado|seudonimizado|identificable
    finalidad: Mapped[str] = mapped_column(String(300), default="")
    vigente_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # None = sin vencimiento
    otorgada_por: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccesoPersonalLog(UUIDMixin, Base):
    """Registro APPEND-ONLY de cada acceso a dato personal (descenso hasta la persona)."""
    __tablename__ = "acceso_personal_log"

    teacher_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    ambito: Mapped[str] = mapped_column(String(160), default="")
    sujeto_ref: Mapped[str] = mapped_column(String(160), default="")   # a qué sujeto/dato (seudónimo o id)
    finalidad: Mapped[str] = mapped_column(String(300), default="")
    justificacion: Mapped[str] = mapped_column(Text, default="")
    emergencia: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
