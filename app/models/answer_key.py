import uuid

from sqlalchemy import String, Integer, Boolean, Float, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# F1 - tipos de pregunta soportados por el motor de evaluacion.
# multiple_choice: el MVP actual (respuesta correcta unica, correccion por OCR).
# open_response: respuesta de desarrollo, evaluada contra una rubrica (fase F).
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_OPEN_RESPONSE = "open_response"
QUESTION_TYPES = (QUESTION_TYPE_MULTIPLE_CHOICE, QUESTION_TYPE_OPEN_RESPONSE)

# F1 (blueprint modulo F) - nivel de exigencia con que la IA corrige un criterio.
# estricto : concepto correcto y completo; errores conceptuales O formales penalizan.
# tolerante: acepta la idea aunque este incompleta/imprecisa; separa forma de contenido (default).
# flexible : premia la comprension central; lo inesperado-valido se marca para el docente.
EXIGENCIA_ESTRICTO = "estricto"
EXIGENCIA_TOLERANTE = "tolerante"
EXIGENCIA_FLEXIBLE = "flexible"
NIVELES_EXIGENCIA = (EXIGENCIA_ESTRICTO, EXIGENCIA_TOLERANTE, EXIGENCIA_FLEXIBLE)

# Fase 1 (corrección desarrollo) — nivel de RIGOR de la revisión IA POR pregunta. La IA propone;
# el docente valida (G1). N1 estricto (forma+fondo superlativo, autoridad nomenclatural estricta) →
# N4 criterioso (más juicio/licencias por parámetro).
RIGOR_ESTRICTO = "estricto"        # N1 · superlativo, forma y fondo, autoridad estricta
RIGOR_FLEXIBLE = "flexible"        # N2 · permite ciertas licencias
RIGOR_MUY_FLEXIBLE = "muy_flexible"  # N3 · más licencias
RIGOR_CRITERIOSO = "criterioso"    # N4 · mayor criterio/juicio por parámetro
NIVELES_RIGOR = (RIGOR_ESTRICTO, RIGOR_FLEXIBLE, RIGOR_MUY_FLEXIBLE, RIGOR_CRITERIOSO)
# Área de conocimiento → fija la autoridad nomenclatural que la IA debe aplicar (Fase 3).
AREAS_CONOCIMIENTO = ("general", "anatomia", "odontologia", "medicina", "enfermeria", "kinesiologia",
                      "derecho", "ingenieria", "arquitectura", "quimica", "biologia", "psicologia",
                      "educacion", "economia_admin")

# Niveles de logro que asigna la pre-calificacion (F2) y las anclas de calibracion.
LOGRO_LOGRADO = "logrado"
LOGRO_PARCIAL = "parcial"
LOGRO_NO = "no_logrado"
NIVELES_LOGRO = (LOGRO_LOGRADO, LOGRO_PARCIAL, LOGRO_NO)


class AnswerKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "answer_keys"

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assessments.id"), unique=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    version_coverage_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    annulled_items_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_weight_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_partial_rule_count: Mapped[int] = mapped_column(Integer, default=0)

    assessment = relationship("Assessment", back_populates="answer_key")
    items = relationship("AnswerKeyItem", back_populates="answer_key", cascade="all, delete-orphan")


class AnswerKeyItem(UUIDMixin, Base):
    __tablename__ = "answer_key_items"

    answer_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("answer_keys.id"))
    question_number: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(10))
    correct_answer: Mapped[str] = mapped_column(String(10))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_annulled: Mapped[bool] = mapped_column(Boolean, default=False)
    partial_credit_rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # F1 - tipo de pregunta. Aditivo: el MVP asume multiple_choice, asi que el
    # default preserva el comportamiento de todas las filas y flujos existentes.
    question_type: Mapped[str] = mapped_column(
        String(30), default=QUESTION_TYPE_MULTIPLE_CHOICE,
        server_default=QUESTION_TYPE_MULTIPLE_CHOICE, nullable=False,
    )

    # C1 - vinculo curricular (RA / Bloom / unidad). OPCIONALES y nullable:
    # el MVP de correccion sigue funcionando sin ellos; solo enriquecen el item
    # cuando el curriculo esta cargado (C2) y etiquetado (C3).
    learning_outcome_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bloom_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # F1 (desarrollo multi-pregunta) - enunciado de la pregunta abierta. Aditivo/nullable:
    # solo aplica a open_response; las de alternativas no lo usan. El peso (score) es 'weight'.
    # LV (modo en vivo): el enunciado también se reutiliza para mostrar la pregunta de
    # alternativas en el teléfono del alumno (banco de ítems), cuando está cargado.
    enunciado: Mapped[str | None] = mapped_column(Text, nullable=True)
    # F-desarrollo: respuesta óptima/de referencia (texto largo — antes se truncaba en correct_answer).
    respuesta_optima: Mapped[str | None] = mapped_column(Text, nullable=True)
    # F-desarrollo: rigor de la revisión IA + área (autoridad nomenclatural). Default sensato.
    nivel_rigor: Mapped[str] = mapped_column(String(20), default="estricto", server_default="estricto", nullable=False)
    area_conocimiento: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # LV (banco de ítems) - contenido opcional para el modo en vivo digital. Aditivo/nullable:
    # opciones_json = textos de las alternativas ([{"letra":"A","texto":"..."}, ...]);
    # justificacion = por qué la correcta es correcta (retroalimentación real al alumno).
    # Si están vacíos, el modo en vivo cae al modo genérico (solo letras A-D), sin romper nada.
    opciones_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    justificacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LV12 - imagen del enunciado (muy usada en pruebas de laboratorio: "a partir de la imagen…").
    # Data URI (base64) para no depender de almacenamiento de archivos. Aditivo/nullable.
    enunciado_imagen: Mapped[str | None] = mapped_column(Text, nullable=True)

    answer_key = relationship("AnswerKey", back_populates="items")
    # F1 - criterios de rubrica (solo relevantes para preguntas open_response).
    rubric_criteria = relationship(
        "RubricCriterion", back_populates="item", cascade="all, delete-orphan",
        order_by="RubricCriterion.order",
    )


class RubricCriterion(UUIDMixin, Base):
    """
    F1 - Criterio de una rubrica de correccion para respuestas de desarrollo.

    Base del motor de evaluacion universal: cada pregunta open_response se corrige
    contra uno o mas criterios (nombre + descriptor + peso). La IA pre-califica
    criterio a criterio (fase F2), pero la nota final es del docente (G1).
    """
    __tablename__ = "rubric_criteria"

    answer_key_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_key_items.id"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255))
    descriptor: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    order: Mapped[int] = mapped_column(Integer, default=0)

    # F1 (blueprint) - parametrizacion docente de la revision IA. Todo con default
    # sensato: configurar es opcional, no engorroso.
    nivel_exigencia: Mapped[str] = mapped_column(
        String(20), default=EXIGENCIA_TOLERANTE, server_default=EXIGENCIA_TOLERANTE, nullable=False)
    penaliza_forma: Mapped[bool] = mapped_column(Boolean, default=False)   # ortografia/termino inexacto
    sinonimos_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # equivalencias aceptadas
    umbral_confianza: Mapped[float] = mapped_column(Float, default=0.7)    # < umbral -> revision docente
    politica_creativo: Mapped[str] = mapped_column(String(20), default="marcar")  # marcar | penalizar
    fuera_de_alcance: Mapped[str | None] = mapped_column(Text, nullable=True)     # que NO evaluar aqui

    # Robustecimiento para rubricas analiticas reales (aditivo, nullable):
    #  - niveles_json: escala PROPIA del criterio [{nivel, puntos, descriptor}], mejor->peor
    #    (p. ej. Excelente=3 / Bueno=2 / Regular=1 / Deficiente=0). Si es None, se usa la
    #    escala de 3 niveles por defecto (logrado/parcial/no_logrado). `weight` = factor de
    #    multiplicacion.
    #  - seccion: dimension que agrupa criterios (Contenido, Organizacion, Preguntas finales).
    #  - ambito: 'grupal' (mismo puntaje a todo el grupo) o 'individual' (por estudiante).
    niveles_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    seccion: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ambito: Mapped[str] = mapped_column(String(20), default="individual",
                                        server_default="individual", nullable=False)

    item = relationship("AnswerKeyItem", back_populates="rubric_criteria")
    # Anclas de calibracion (few-shot): respuestas ya corregidas por el docente que
    # fijan el estandar de este criterio. Es la forma NO engorrosa de configurar.
    anclas = relationship("RubricAncla", back_populates="criterio",
                          cascade="all, delete-orphan", order_by="RubricAncla.order")


class RubricAncla(UUIDMixin, Base):
    """
    F1 - Ancla de calibracion: una respuesta de ejemplo con su nivel de logro asignado
    por el docente. El few-shot que calibra a la IA (F2) sin escribir reglas.
    """
    __tablename__ = "rubric_anclas"

    rubric_criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rubric_criteria.id"), nullable=False)
    texto: Mapped[str] = mapped_column(Text)
    nivel: Mapped[str] = mapped_column(String(20))   # logrado | parcial | no_logrado
    order: Mapped[int] = mapped_column(Integer, default=0)

    criterio = relationship("RubricCriterion", back_populates="anclas")
