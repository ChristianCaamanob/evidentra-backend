"""
Asistencia por curso con QR dinámico + passkeys (WebAuthn).

Modelo autocontenido (no toca la psicometría). Flujo:
  1) El docente/investigador/director importa la nómina oficial (Excel) -> AsistenciaMatricula.
  2) Enrolamiento: invitación por correo + validación presencial -> el alumno registra una
     passkey (DispositivoWebAuthn: SOLO clave pública, nunca biometría).
  3) El docente abre una SesionAsistencia (curso + ventana de fecha/hora) y proyecta un QR
     que rota cada ~4 s (desafío firmado con HMAC del secreto de la sesión).
  4) El alumno aprueba con su passkey sobre el desafío del QR -> MarcaAsistencia.

Gobernanza: se guarda clave pública + credentialId (no huella ni rostro); RUT solo coteja
la nómina, nunca es contraseña. Ley 21.719: minimización + seudonimización en export.
"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin

# Estados de la matrícula (enrolamiento).
MAT_INVITADO = "invitado"     # en la nómina, invitación enviada, aún sin validar
MAT_VALIDADO = "validado"     # identidad validada presencialmente por el docente
MAT_ACTIVO = "activo"         # con passkey registrada -> puede marcar
MAT_ESTADOS = (MAT_INVITADO, MAT_VALIDADO, MAT_ACTIVO)

SES_ABIERTA = "abierta"
SES_CERRADA = "cerrada"

MARCA_PRESENTE = "presente"
MARCA_REVISADO = "revisado"   # marcada pero con anomalía a revisar por el docente
MARCA_AUSENTE = "ausente"     # override manual del docente


class AsistenciaMatricula(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "asistencia_matriculas"
    __table_args__ = (UniqueConstraint("course_id", "correo", name="uq_matricula_curso_correo"),)

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), index=True)
    student_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # coteja con la nómina psicométrica
    nombre: Mapped[str] = mapped_column(String(160))
    correo: Mapped[str] = mapped_column(String(160), index=True)
    identificador: Mapped[str | None] = mapped_column(String(80), nullable=True)  # identificador académico
    rut: Mapped[str | None] = mapped_column(String(20), nullable=True)            # solo cotejo, no contraseña
    carrera: Mapped[str | None] = mapped_column(String(160), nullable=True)
    seccion: Mapped[str | None] = mapped_column(String(80), nullable=True)
    asignatura: Mapped[str | None] = mapped_column(String(160), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default=MAT_INVITADO, server_default=MAT_INVITADO, nullable=False)
    invite_token: Mapped[str | None] = mapped_column(String(48), unique=True, index=True, nullable=True)
    validado_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)

    dispositivos = relationship("DispositivoWebAuthn", back_populates="matricula",
                                cascade="all, delete-orphan")


class DispositivoWebAuthn(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "asistencia_dispositivos"

    matricula_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asistencia_matriculas.id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)  # base64url
    public_key: Mapped[str] = mapped_column(Text)                                     # COSE, base64
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transports: Mapped[list | None] = mapped_column(JSON, nullable=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    matricula = relationship("AsistenciaMatricula", back_populates="dispositivos")


class SesionAsistencia(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "asistencia_sesiones"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), index=True)
    abierta_por: Mapped[str] = mapped_column(String(64))     # id del docente/investigador/director
    titulo: Mapped[str] = mapped_column(String(200), default="Asistencia")
    fecha: Mapped[str] = mapped_column(String(10))           # YYYY-MM-DD (día de la lista)
    inicio: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))   # ventana de marcado
    fin: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))
    estado: Mapped[str] = mapped_column(String(20), default=SES_ABIERTA, server_default=SES_ABIERTA, nullable=False)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    secreto: Mapped[str] = mapped_column(String(64))         # clave HMAC para firmar el desafío del QR
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    marcas = relationship("MarcaAsistencia", back_populates="sesion", cascade="all, delete-orphan")


class MarcaAsistencia(UUIDMixin, Base):
    __tablename__ = "asistencia_marcas"
    # una marca por (sesión, matrícula): no se puede marcar dos veces.
    __table_args__ = (UniqueConstraint("sesion_id", "matricula_id", name="uq_marca_sesion_matricula"),)

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asistencia_sesiones.id"), index=True)
    matricula_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asistencia_matriculas.id"), index=True)
    metodo: Mapped[str] = mapped_column(String(20), default="passkey")
    estado: Mapped[str] = mapped_column(String(20), default=MARCA_PRESENTE, server_default=MARCA_PRESENTE, nullable=False)
    anomalias: Mapped[list | None] = mapped_column(JSON, nullable=True)   # banderas (no rechazos)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    marcada_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionAsistencia", back_populates="marcas")
