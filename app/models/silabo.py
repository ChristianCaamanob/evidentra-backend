"""Escudo de comunicación (Pilar II) — agente de sílabo 24/7 + bandeja clasificada.

Doctrina de acceso (igual que Modo en vivo / Asistencia): los alumnos NO tienen cuenta;
acceden al agente por un ENLACE/QR público por curso (`?silabo=CODIGO`). El docente carga
el contexto del curso (sílabo, fechas, reglas), publica el agente, y la IA responde 24/7
SOLO con base en ese contexto. Lo que la IA no puede resolver o que requiere decisión del
docente cae, clasificado, en una bandeja para el docente (no lo satura de repetidas).
"""
import uuid

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin

# Estados de un mensaje de la bandeja.
MSG_RESPONDIDA = "respondida"          # la IA respondió y basta
MSG_PENDIENTE = "pendiente_docente"    # requiere respuesta/decisión del docente
MSG_RESUELTA = "resuelta"              # el docente la respondió/cerró


class SilaboAgente(UUIDMixin, TimestampMixin, Base):
    """Un agente de sílabo por curso. `contexto` es el material sobre el que la IA responde."""
    __tablename__ = "silabo_agentes"

    course_id: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)   # enlace público
    nombre_curso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contexto: Mapped[str] = mapped_column(Text, default="")                    # sílabo/reglas/fechas
    activo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)           # tono, alcance, etc.
    # Nivel 2 · Ayudante (opcional): si está activo, lo que escala pasa PRIMERO por el ayudante.
    ayudante_activo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    ayudante_codigo: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)

    mensajes = relationship("MensajeSilabo", back_populates="agente", cascade="all, delete-orphan")


class MensajeSilabo(UUIDMixin, TimestampMixin, Base):
    """Una pregunta de un alumno + la respuesta de la IA + su clasificación para la bandeja."""
    __tablename__ = "silabo_mensajes"

    agente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("silabo_agentes.id"), index=True)
    alias: Mapped[str | None] = mapped_column(String(80), nullable=True)       # opcional (sin login)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # identidad local del alumno (localStorage)
    pregunta: Mapped[str] = mapped_column(Text)
    respuesta_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Contrato de fuentes: fragmento EXACTO del contexto que sostiene la respuesta (o None).
    cita: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Trazabilidad del profesor: tema/RA al que apunta la consulta + fuente de la respuesta.
    tema: Mapped[str | None] = mapped_column(String(120), nullable=True)     # p.ej. "drenaje linfático de la mama"
    fuente: Mapped[str | None] = mapped_column(String(16), nullable=True)    # corpus | general | ninguna
    confianza: Mapped[str | None] = mapped_column(String(8), nullable=True)  # baja|media|alta (autoevaluación del estudiante, metacognición)
    # Taxonomía de intención (la política/destino se deriva del tipo): administrativa / conceptual /
    # fuera_corpus / evaluativa / riesgo_clinico / personal_salud / extraccion / otro.
    tipo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    categoria: Mapped[str | None] = mapped_column(String(40), nullable=True)   # fechas/contenido/evaluación/logística/otro
    urgencia: Mapped[str | None] = mapped_column(String(10), nullable=True)     # baja/media/alta
    estado: Mapped[str] = mapped_column(String(24), default=MSG_RESPONDIDA,
                                        server_default=MSG_RESPONDIDA, nullable=False)
    necesita_docente: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    nivel: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)   # 2=ayudante, 3=profesor
    respondido_por: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ia | ayudante | docente
    motivo_escalamiento: Mapped[str | None] = mapped_column(String(255), nullable=True)  # por qué el ayudante subió
    vence_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)        # epoch: plazo visible para el alumno
    respuesta_docente: Mapped[str | None] = mapped_column(Text, nullable=True)

    agente = relationship("SilaboAgente", back_populates="mensajes")


class RuniBitacora(UUIDMixin, TimestampMixin, Base):
    """Bitácora de auditoría ENCADENADA POR HASH (append-only, sin datos personales). Cada entrada lleva
    el hash de la anterior: alterar/borrar el pasado rompe la cadena (a prueba de manipulación). Regla dura:
    'sin bitácora no hay respuesta' (se escribe en la MISMA transacción que el mensaje). Protocolo §3.4."""
    __tablename__ = "runi_bitacora"

    agente_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("silabo_agentes.id"), index=True)
    seudonimo: Mapped[str | None] = mapped_column(String(64), nullable=True)       # hash(device), no el nombre
    evento: Mapped[str] = mapped_column(String(32), default="consulta")            # consulta|derivacion|consecuencia|parada
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)                 # tema/tipo/fuente/decision/nivel (sin texto sensible)
    contenido_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sha256 del contenido (prueba, no el texto)
    prev_hash: Mapped[str] = mapped_column(String(80), default="")
    hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    reglas_version: Mapped[str | None] = mapped_column(String(16), nullable=True)  # qué reglas gobernaban
