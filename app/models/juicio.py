"""
Evidencia JUZGADA: lo que la estudiante escribió y qué dijo Runi al leerlo.

Hasta ahora el repaso era autocalificado de punta a punta —ella escribía su respuesta en un cuadro
de texto que **nunca se enviaba a ninguna parte**, y lo único que se guardaba era si se había puesto
«Lo supe»—. Eso alcanzaba para medir constancia, pero no para saber si conectó dos ideas o si supo
aplicar algo a un caso que no había visto.

Regla que sostiene todo: **una medalla exige que el autorreporte y el juicio de Runi COINCIDAN**
(`concordancia`). Un modelo se equivoca; el estudiante también. Cuando discrepan no se castiga a
nadie: se muestra la diferencia y esa evidencia simplemente no cuenta para la puerta. Así una
medalla nunca se gana ni se pierde por un error del modelo.

Se guarda el texto de la respuesta porque es la evidencia; dominio APRENDIZAJE, identidad
seudonimizada (`pseudo_id`), nunca RUT ni nombre.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, UUIDMixin

# recordar = recuperación simple · conectar = relacionar dos temas · aplicar = caso nuevo
# integrar = explicar cómo encajan varios conceptos en un resultado
TIPOS = ("recordar", "conectar", "aplicar", "integrar")


class EpisodeJuicio(UUIDMixin, Base):
    __tablename__ = "learning_juicios"

    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("learning_episodes.id"), index=True, nullable=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    course_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    tipo: Mapped[str] = mapped_column(String(16), default="recordar", index=True)
    ra: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ra_b: Mapped[str | None] = mapped_column(String(120), nullable=True)   # el otro tema, en 'conectar'
    consigna: Mapped[str | None] = mapped_column(Text, nullable=True)      # lo que se le pidió
    respuesta: Mapped[str | None] = mapped_column(Text, nullable=True)     # lo que escribió
    # Huella del texto: la misma respuesta repetida no vuelve a contar (antiFarming del spec v3).
    huella: Mapped[str] = mapped_column(String(64), default="", index=True)
    auto_reporte: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # lo que ella dijo
    juicio: Mapped[bool | None] = mapped_column(Boolean, nullable=True)         # lo que dijo Runi
    concordancia: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    conceptos: Mapped[list | None] = mapped_column(JSON, nullable=True)    # los que Runi reconoció
    razon: Mapped[str | None] = mapped_column(Text, nullable=True)         # por qué, para mostrárselo
    confianza: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PlanSemanal(Base):
    """El plan que la estudiante se pone para la semana. Lo pone ella, no el sistema.

    Existe porque la medalla «Rumbo propio» pide cumplir tu propio plan, y no había ningún lugar
    donde ese plan existiera: la agenda solo guarda el horario de clases extraído de la foto.
    Se mide contra episodios verificados de esa misma semana, no contra sesiones abiertas.
    """
    __tablename__ = "learning_plan_semanal"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    semana: Mapped[str] = mapped_column(String(10), index=True)      # "2026-W35" (ISO)
    meta_episodios: Mapped[int] = mapped_column(Integer, default=3)
    nota: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creado_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
