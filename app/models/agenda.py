"""
Agenda del alumno (v2.0 · Horario mágico) — bloques de clase/actividad extraídos de la foto del horario.

Personal por alumno: owner_key = 'sid:<student_account_id>' (si inició sesión) o 'dev:<device_id>'.
Una fila por bloque recurrente semanal. No guarda historial de cambios (upsert por reemplazo del owner).
"""
import uuid

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AgendaBloque(UUIDMixin, Base):
    __tablename__ = "agenda_bloques"

    owner_key: Mapped[str] = mapped_column(String(80), index=True)     # sid:<uuid> | dev:<device>
    asignatura: Mapped[str] = mapped_column(String(160), default="")
    dia: Mapped[int] = mapped_column(Integer, default=0)                # 0=Lunes … 6=Domingo
    inicio: Mapped[str] = mapped_column(String(5), default="")          # "HH:MM" 24h
    fin: Mapped[str] = mapped_column(String(5), default="")             # "HH:MM" 24h
    sala: Mapped[str | None] = mapped_column(String(80), nullable=True)
    docente: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo: Mapped[str | None] = mapped_column(String(30), nullable=True)          # clase/lab/ayudantia/otro
    recurrencia: Mapped[str] = mapped_column(String(20), default="semanal")
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
