"""
Runi Reward System v1 — inventario, equipamiento, cofres y libro mayor de Lumis.

Tres decisiones que sostienen todo lo demás:

1. **El saldo de Lumis NO es un número guardado.** Es la suma de un libro mayor de movimientos, cada
   uno con una `ref` única. Un contador editable se desincroniza entre dos teléfonos y no deja
   explicar de dónde salió un saldo; un libro mayor con `ref` única hace que reintentar una petición
   acredite una sola vez y que cada Lumin tenga procedencia.

2. **Las tres opciones de un cofre se guardan al abrirlo.** La directiva del paquete lo exige y tiene
   razón: si se sortearan al pintar la pantalla, recargar daría tres opciones distintas y la elección
   dejaría de ser una elección.

3. **Identidad seudonimizada** (`pseudo_id`), igual que el motor de medallas. Aquí no entra el RUT.

Nada de esto toca notas, respuestas ni evaluaciones: es una capa cosmética.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class RecompensaItem(Base):
    """Una recompensa que ESTA persona posee. La unicidad impide duplicados por doble clic."""
    __tablename__ = "recompensa_item"
    __table_args__ = (UniqueConstraint("pseudo_id", "item_id", name="uq_recompensa_por_alumno"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    item_id: Mapped[str] = mapped_column(String(64), index=True)
    categoria: Mapped[str] = mapped_column(String(24), default="")
    rareza: Mapped[str] = mapped_column(String(16), default="common")
    origen: Mapped[str] = mapped_column(String(24), default="cofre")     # cofre · tienda · hito
    ref: Mapped[str | None] = mapped_column(String(80), nullable=True)   # cofre o compra que lo originó
    obtenido_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecompensaEquipo(Base):
    """Lo que la persona lleva puesto. Una fila por ranura: equipar reemplaza, nunca acumula."""
    __tablename__ = "recompensa_equipo"
    __table_args__ = (UniqueConstraint("pseudo_id", "slot", name="uq_ranura_por_alumno"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    slot: Mapped[str] = mapped_column(String(24), default="")
    item_id: Mapped[str] = mapped_column(String(64), default="")
    actualizado_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LuminMovimiento(Base):
    """Libro mayor de Lumis. El saldo es la SUMA de estas filas; nunca un campo que se sobrescribe.

    `ref` identifica el hecho que lo causó (una medalla, un día, una compra). Es única por persona:
    reintentar la misma petición no vuelve a acreditar.
    """
    __tablename__ = "recompensa_lumin"
    __table_args__ = (UniqueConstraint("pseudo_id", "ref", name="uq_lumin_ref"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    delta: Mapped[int] = mapped_column(Integer, default=0)               # + gana · − gasta
    motivo: Mapped[str] = mapped_column(String(48), default="")
    detalle: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ref: Mapped[str] = mapped_column(String(80), default="")
    creado_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RecompensaPendiente(Base):
    """Un cofre ganado y todavía sin abrir (o abierto y sin elegir).

    `origen_ref` es el hecho verificado que lo produjo —el recibo de una medalla—, y es único: un
    mismo desbloqueo no puede generar dos cofres aunque la pantalla se recargue diez veces.
    """
    __tablename__ = "recompensa_pendiente"
    __table_args__ = (UniqueConstraint("pseudo_id", "origen_ref", name="uq_cofre_por_origen"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(80), index=True)
    origen_ref: Mapped[str] = mapped_column(String(80), default="")
    origen_texto: Mapped[str | None] = mapped_column(String(200), nullable=True)  # "Tramo 4 · Puente de los Desafíos"
    cofre_id: Mapped[str] = mapped_column(String(32), default="cofre-expedicion")
    opciones: Mapped[list | None] = mapped_column(JSON, nullable=True)    # las 3, fijadas al crearse
    elegido: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creado_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    reclamado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
