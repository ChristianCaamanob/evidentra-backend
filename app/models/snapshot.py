"""
Cortes históricos del Centro de Análisis (persistencia de series de tiempo).

Un `AnalisisSnapshot` CONGELA el resultado de `ficha_service.analisis_evaluacion` de una
evaluación en un instante (hora de servidor), con una etiqueta. A diferencia del análisis que
se recomputa al vuelo, un snapshot es INMUTABLE: sirve para auditoría (qué se veía al cierre de
tal sesión/fecha) y para comparar la evolución sin depender de que la evidencia posterior cambie.
"""
import uuid

from sqlalchemy import String, Integer, Float, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AnalisisSnapshot(UUIDMixin, Base):
    __tablename__ = "analisis_snapshots"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    etiqueta: Mapped[str] = mapped_column(String(160))
    origen: Mapped[str | None] = mapped_column(String(20), nullable=True)   # '' | 'omr' | 'en_vivo'
    # KPIs extraídos para listar sin abrir el payload completo.
    n_estudiantes: Mapped[int] = mapped_column(Integer, default=0)
    promedio: Mapped[float | None] = mapped_column(Float, nullable=True)
    aprobacion_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logro_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # El análisis completo congelado (mismo shape que analisis_evaluacion).
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tomado_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
