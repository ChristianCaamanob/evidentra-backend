"""
B11 — Evaluación continua de la IA (Runi): banco experto + regresión por release.

Tres tablas, aditivas y no destructivas:
  · IAEvalCase   — banco experto: casos con comportamiento ESPERADO y criterios de calidad.
  · IAEvalRun    — una corrida por release (resumen agregado + bandera de regresión).
  · IAEvalResult — el veredicto por caso dentro de una corrida (append-only, evidencia).

El comportamiento (responde/abstiene/deriva) se deriva de la autoclasificación de Runi
(`tipo`, `necesita_docente`); la calidad de contenido (cumple criterios, alucina, fundamentado)
la juzga un LLM. Nada de esto toca el flujo del estudiante.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class IAEvalCase(Base):
    __tablename__ = "ia_eval_case"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    esperado: Mapped[str] = mapped_column(String(16), default="responde")  # responde | abstiene | deriva
    curso: Mapped[str | None] = mapped_column(String(160), nullable=True)   # etiqueta del curso (contexto)
    tema: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pregunta: Mapped[str] = mapped_column(Text, default="")
    contexto: Mapped[str | None] = mapped_column(Text, nullable=True)        # material del curso a inyectar (opcional)
    criterios: Mapped[list | None] = mapped_column(JSON, nullable=True)      # lista de exigencias de calidad
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    origen: Mapped[str] = mapped_column(String(24), default="seed")          # seed | manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IAEvalRun(Base):
    __tablename__ = "ia_eval_run"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    release: Mapped[str] = mapped_column(String(48), default="")
    estado: Mapped[str] = mapped_column(String(16), default="corriendo")     # corriendo | ok | error
    n: Mapped[int] = mapped_column(Integer, default=0)
    resumen: Mapped[dict | None] = mapped_column(JSON, nullable=True)         # métricas agregadas
    regresion: Mapped[bool] = mapped_column(Boolean, default=False)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)            # diagnóstico corto vs release anterior
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IAEvalResult(Base):
    __tablename__ = "ia_eval_result"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    esperado: Mapped[str] = mapped_column(String(16), default="responde")
    comportamiento: Mapped[str] = mapped_column(String(16), default="responde")  # lo que Runi hizo
    respuesta: Mapped[str | None] = mapped_column(Text, nullable=True)
    veredicto: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # {cumple, alucina, fundamentado, nota, justificacion}
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
