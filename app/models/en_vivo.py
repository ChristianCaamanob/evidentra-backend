"""
Modo EN VIVO: quiz sincronico estilo Socrative sobre la misma infraestructura.

El docente abre una sesion desde una evaluacion existente (reusa su AnswerKey de
alternativas). Los estudiantes se unen con un codigo corto (o QR), el docente avanza
pregunta a pregunta, y las respuestas se corrigen al vuelo contra la pauta. Al cerrar,
la matriz binaria participante x item alimenta la misma psicometria del modulo Profesor
e Investigador (Rasch, KR-20, etc.): el modo en vivo NO es un silo, es otra forma de
aplicar una evaluacion.

Estados de la sesion:
    lobby   -> creada, estudiantes uniendose, aun sin pregunta activa (pregunta_actual=0)
    activa  -> hay una pregunta en pantalla; los participantes pueden responder
    pausada -> el docente congelo la sesion; no se aceptan respuestas
    cerrada -> terminada; se consolidan resultados (no admite mas cambios)
"""
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

ESTADO_LOBBY = "lobby"
ESTADO_ACTIVA = "activa"
ESTADO_PAUSADA = "pausada"
ESTADO_CERRADA = "cerrada"
ESTADOS = (ESTADO_LOBBY, ESTADO_ACTIVA, ESTADO_PAUSADA, ESTADO_CERRADA)

# Ritmo de avance: 'docente' = el profesor avanza a toda la clase (una pregunta global);
# 'alumno' = cada estudiante avanza solo (self-paced, requerido si se barajan preguntas).
RITMO_DOCENTE = "docente"
RITMO_ALUMNO = "alumno"


class SesionEnVivo(UUIDMixin, Base):
    __tablename__ = "sesiones_en_vivo"

    assessment_id: Mapped[str] = mapped_column(String(64), index=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_LOBBY,
                                        server_default=ESTADO_LOBBY, nullable=False)
    # 0 = lobby (sin pregunta); 1..N = numero de pregunta en pantalla.
    pregunta_actual: Mapped[int] = mapped_column(Integer, default=0)
    n_preguntas: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(String(10), default="A")   # el quiz en vivo usa una version
    # Retroalimentación al alumno (config del docente antes de abrir la sala):
    retro_alumno: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    revelar_correccion: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Reveal motivacional del "huillín" al alumno antes de mostrar el puntaje (según su % de logro).
    mascota_motivacional: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Temporizador (LV11): duración total en minutos (0 = sin límite). timer_inicio_ts = epoch en
    # que arrancó la cuenta (se estampa al pasar lobby→activa la primera vez). El plazo de cada
    # alumno = timer_inicio_ts + duracion_min*60 + su tiempo_extra_seg (extensión selectiva).
    duracion_min: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    timer_inicio_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modo_ritmo: Mapped[str] = mapped_column(String(20), default=RITMO_DOCENTE,
                                            server_default=RITMO_DOCENTE, nullable=False)
    shuffle_preguntas: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    shuffle_opciones: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # LV9 · Bloqueo real con Safe Exam Browser (alto impacto). requiere_seb: exige entrar desde SEB;
    # seb_config_key: hash de la config .seb generada (para verificar que la petición viene de SEB).
    requiere_seb: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    seb_config_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Atención por cámara (consentida, en-dispositivo, solo eventos — nunca video). OFF por defecto.
    atencion_camara: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Modo Auditorio: si NO es NULL, la sala corrige contra ESTA lista de preguntas (ad-hoc de las
    # diapositivas marcadas) en vez de la pauta del assessment. Cada ítem ya viene con la forma de
    # _items_contenido (ordinal/correcta/letras/opciones/…). NULL = sala normal de Modo en vivo (intacta).
    auditorio_items_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    participantes = relationship("ParticipanteVivo", back_populates="sesion",
                                 cascade="all, delete-orphan")
    respuestas = relationship("RespuestaVivo", back_populates="sesion",
                              cascade="all, delete-orphan")


class ParticipanteVivo(UUIDMixin, Base):
    __tablename__ = "participantes_vivo"

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones_en_vivo.id"), index=True)
    alias: Mapped[str] = mapped_column(String(80))
    student_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # si es un alumno de la nomina
    token: Mapped[str] = mapped_column(String(48))     # autoriza a responder sin login
    # Vinculo al dispositivo (LV10): huella estable del navegador guardada al unirse. Un dispositivo
    # que ya tiene participante en la sala NO puede crear otro (evita rendir por un companero / doble
    # registro). Es un candado honesto: corta el abuso casual, no el determinado (incognito/otro equipo).
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Distribución personal del quiz (barajado por-alumno): {"q_order":[...], "opt_map":{"1":["C","A",...]}}.
    # q_order = orden de los ordinales de pregunta; opt_map[qn][posición_mostrada] = letra canónica.
    layout_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progreso: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # nº de preguntas respondidas (self-paced)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Integridad (LV8): el docente puede CERRAR selectivamente la prueba a este alumno (decisión
    # humana ante evidencia). ultimo_latido_ts = epoch del último heartbeat (para "tiempo sin actividad").
    bloqueado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    bloqueado_motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ultimo_latido_ts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Extensión selectiva de tiempo (LV11): segundos EXTRA que el docente concede a ESTE alumno
    # (llegó tarde / reabierto). Se suma a su plazo. 0 = sin extensión.
    tiempo_extra_seg: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    sesion = relationship("SesionEnVivo", back_populates="participantes")


class EventoIntegridad(UUIDMixin, Base):
    """Telemetría de integridad del modo en vivo (LV8): un registro INMUTABLE por evento de
    ventana/foco del alumno, con hora de SERVIDOR. Es evidencia objetiva — la interpretación es
    humana y nunca invalida la evaluación por sí sola (proporcionalidad, Ley 21.719).

    tipo: page_hidden | page_visible | blur | focus | fullscreen_enter | fullscreen_exit |
          copy | paste | cut | contextmenu | heartbeat | join | sesion_concurrente
    """
    __tablename__ = "eventos_integridad"

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones_en_vivo.id"), index=True)
    participante_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("participantes_vivo.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30), index=True)
    question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)   # p.ej. tiempo oculto
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)      # orden en el cliente
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # p.ej. {"pegado_len":42,"screens":2}
    server_time: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RespuestaVivo(UUIDMixin, Base):
    __tablename__ = "respuestas_vivo"
    # una sola respuesta por participante y pregunta (no se puede responder dos veces).
    __table_args__ = (UniqueConstraint("participante_id", "question_number", name="uq_resp_vivo"),)

    sesion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones_en_vivo.id"), index=True)
    participante_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("participantes_vivo.id"), index=True)
    question_number: Mapped[int] = mapped_column(Integer)
    respuesta: Mapped[str] = mapped_column(String(10))
    correcta: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sesion = relationship("SesionEnVivo", back_populates="respuestas")
