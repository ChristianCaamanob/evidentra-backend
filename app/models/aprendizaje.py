"""
F4 - Aprendizaje de calibracion: versionado inmutable de la rubrica.

Dos registros complementarios que hacen que "la IA aprenda" sin romper la
replicabilidad:

  - RubricaVersion: una FOTO inmutable del conjunto de criterios, con hash de
    contenido. Cada evaluacion queda clavada a una version; corregir la regla
    crea una version NUEVA y deja la anterior congelada (el pasado sigue
    reproducible).

  - AjusteCalibracion: cada refinamiento aprendido (una entrada del changelog),
    con su evidencia seudonimizada, recurrencia, si relaja la norma disciplinar
    (requiere override docente) y quien lo aprobo. Es la trazabilidad del
    aprendizaje (G5) y la compuerta etica (G1: el docente aprueba la regla, no
    solo la nota).
"""
from sqlalchemy import String, Float, Integer, Boolean, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RubricaVersion(UUIDMixin, Base):
    __tablename__ = "rubrica_versiones"

    answer_key_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[int] = mapped_column(Integer)                       # 1, 2, 3...
    hash: Mapped[str] = mapped_column(String(64))                       # hash de contenido (replicabilidad)
    parent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="propuesta")  # propuesta|activa|archivada
    resumen: Mapped[str | None] = mapped_column(Text, nullable=True)
    autor: Mapped[str] = mapped_column(String(120))
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AjusteCalibracion(UUIDMixin, Base):
    __tablename__ = "ajustes_calibracion"

    rubrica_version_hash: Mapped[str] = mapped_column(String(64))       # a que version pertenece
    criterio: Mapped[str] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(40))                       # sinonimo_aceptado, ancla_nueva...
    direccion: Mapped[str] = mapped_column(String(10))                  # sube | baja
    descripcion: Mapped[str] = mapped_column(Text)
    recurrencia: Mapped[int] = mapped_column(Integer, default=1)
    confianza: Mapped[float] = mapped_column(Float, default=0.0)
    evidencia_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # refs seudonimizadas (G2)
    requiere_override: Mapped[bool] = mapped_column(Boolean, default=False)  # relaja la norma disciplinar
    justificacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="propuesto")     # propuesto|aprobado|rechazado
    aprobado_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
