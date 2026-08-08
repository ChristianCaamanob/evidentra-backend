"""Gobernanza · Decisiones trazables + planes de mejora (memoria institucional).

Cada decisión/plan de mejora registra el ciclo completo que pide la doctrina de gobernanza:
problema → evidencia → alternativas → decisión → responsable → plazo → indicador → resultado →
revisión (mantener/ajustar/detener). Lleva una **bitácora append-only** (lista de eventos con
autor y fecha) para construir memoria institucional auditable — la decisión evoluciona, pero su
historia no se borra. `ambito`/`nivel` son texto por ahora (departamento/carrera/escuela/decanatura);
cuando aterrice el RBAC por ámbito, el acceso se restringe por ese eje.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

TIPOS = ("decision", "plan_mejora")
NIVELES = ("departamento", "carrera", "escuela", "decanatura")
ESTADOS = ("abierta", "en_curso", "cerrada")
REVISIONES = ("mantener", "ajustar", "detener")


class DecisionGov(UUIDMixin, Base):
    __tablename__ = "decisiones_gov"

    autor_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    ambito: Mapped[str] = mapped_column(String(160), default="", index=True)   # p.ej. "Departamento: Anatomía"
    nivel: Mapped[str] = mapped_column(String(20), default="departamento")     # departamento|carrera|escuela|decanatura
    tipo: Mapped[str] = mapped_column(String(20), default="decision")          # decision|plan_mejora
    titulo: Mapped[str] = mapped_column(String(300), default="")
    problema: Mapped[str] = mapped_column(Text, default="")                    # problema identificado
    evidencia: Mapped[str] = mapped_column(Text, default="")                   # evidencia examinada (+ enlace)
    alternativas: Mapped[str] = mapped_column(Text, default="")                # alternativas consideradas
    decision: Mapped[str] = mapped_column(Text, default="")                    # decisión / objetivo del plan
    responsable: Mapped[str] = mapped_column(String(200), default="")
    plazo: Mapped[str] = mapped_column(String(40), default="")                 # fecha ISO (texto libre por ahora)
    indicador: Mapped[str] = mapped_column(Text, default="")                   # indicador de logro / evidencia esperada
    estado: Mapped[str] = mapped_column(String(20), default="abierta")
    resultado: Mapped[str] = mapped_column(Text, default="")                   # resultado obtenido
    revision: Mapped[str] = mapped_column(String(20), default="")              # mantener|ajustar|detener
    bitacora: Mapped[list] = mapped_column(JSON, default=list)                 # [{ts, actor, evento}] append-only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
