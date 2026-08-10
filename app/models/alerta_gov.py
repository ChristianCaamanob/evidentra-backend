"""Gobernanza · Alertas escalonadas (motor de escalamiento controlado).

Doctrina del CEO: las alertas **no ascienden solas**. La clasificación automática (verde/amarillo/rojo
del panorama) es sólo la DETECCIÓN; convertir una señal en una alerta con ciclo de vida — registrarla,
escalarla, darle seguimiento y cerrarla — es siempre un acto HUMANO, justificado y auditable.

Escalera de niveles (orden fijo, `NIVELES_ALERTA`):
    informativa → observacion → revision → intervencion → critica
Subir o bajar de nivel exige justificación y queda en la **bitácora append-only** (memoria auditable).
Nunca se etiqueta a la persona: `sujeto_ref` guarda el seudónimo (E-XXXXXX) o una referencia de
curso/RA — abrir el dato personal exige el registro de acceso personal (0A, `AccesoPersonalLog`).
El acceso por lectura respeta el RBAC por ámbito (`gobernanza_ambito_service.puede_ver`).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

NIVELES = ("departamento", "carrera", "escuela", "decanatura")
# escalera de escalamiento, en orden ascendente
NIVELES_ALERTA = ("informativa", "observacion", "revision", "intervencion", "critica")
ESTADOS = ("abierta", "en_seguimiento", "resuelta", "descartada")
CERTEZAS = ("baja", "media", "alta")


class AlertaGov(UUIDMixin, Base):
    __tablename__ = "alertas_gov"

    autor_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    ambito: Mapped[str] = mapped_column(String(160), default="", index=True)   # p.ej. "Carrera: Medicina · Histología"
    nivel: Mapped[str] = mapped_column(String(20), default="carrera")          # departamento|carrera|escuela|decanatura
    titulo: Mapped[str] = mapped_column(String(300), default="")
    sujeto_ref: Mapped[str] = mapped_column(String(200), default="")           # seudónimo E-XXXXXX o ref curso/RA (NUNCA nombre)
    origen: Mapped[str] = mapped_column(String(40), default="manual")          # manual|carrera_sede|departamento|escuela
    fundamento: Mapped[str] = mapped_column(Text, default="")                  # por qué se levanta (RA/logro/evidencia)
    certeza: Mapped[str] = mapped_column(String(10), default="media")          # baja|media|alta
    nivel_alerta: Mapped[str] = mapped_column(String(20), default="informativa")
    estado: Mapped[str] = mapped_column(String(20), default="abierta")
    responsable: Mapped[str] = mapped_column(String(200), default="")
    decision_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=True)  # decisión 0B derivada (cierra el ciclo)
    bitacora: Mapped[list] = mapped_column(JSON, default=list)                 # [{ts, actor, evento, de, a}] append-only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
