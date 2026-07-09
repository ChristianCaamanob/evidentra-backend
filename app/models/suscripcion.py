"""
Suscripcion de una cuenta a un plan, y el log INMUTABLE de eventos de pago (trazabilidad
tipo G5). No se almacena NINGUN dato de tarjeta: eso vive en la pasarela (PCI). Aca solo
guardamos referencias/tokens y el estado.

Estados de la suscripcion:
    trial     -> periodo de prueba con features premium; vence en fin_periodo.
    activa    -> pago vigente.
    morosa    -> intento de cobro fallido; ventana de gracia antes de degradar.
    cancelada -> el usuario cancelo; conserva el plan hasta fin_periodo, luego cae a free.
"""
import uuid

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

ESTADO_TRIAL = "trial"
ESTADO_ACTIVA = "activa"
ESTADO_MOROSA = "morosa"
ESTADO_CANCELADA = "cancelada"
ESTADOS = (ESTADO_TRIAL, ESTADO_ACTIVA, ESTADO_MOROSA, ESTADO_CANCELADA)


class Suscripcion(UUIDMixin, Base):
    __tablename__ = "suscripciones"

    # Una suscripcion por cuenta (id del Teacher, como str).
    cuenta_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(30), default="free")
    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_TRIAL)
    inicio: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Fin del periodo vigente (fin del trial o del ciclo pagado). None = no expira (free).
    fin_periodo: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ref_externa: Mapped[str | None] = mapped_column(String(160), nullable=True)  # token/suscripcion del gateway
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    eventos = relationship("EventoPago", back_populates="suscripcion",
                           cascade="all, delete-orphan")


class EventoPago(UUIDMixin, Base):
    """Registro append-only de cada evento de pago (checkout, confirmacion, rechazo...)."""
    __tablename__ = "eventos_pago"

    suscripcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suscripciones.id"), index=True)
    gateway: Mapped[str] = mapped_column(String(20))
    tipo: Mapped[str] = mapped_column(String(40))          # checkout_creado | pago_confirmado | pago_rechazado | cancelacion
    monto_clp: Mapped[int] = mapped_column(Integer, default=0)
    estado: Mapped[str] = mapped_column(String(20), default="")
    # Clave de idempotencia: un webhook repetido no se procesa dos veces.
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suscripcion = relationship("Suscripcion", back_populates="eventos")
