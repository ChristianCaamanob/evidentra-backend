from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.models.base import Base
from app.models.course import Course
from app.models.scan import Scan
from app.models.student import Student
from app.models.teacher import Teacher
from app.models.password_reset import PasswordResetToken
from app.models.en_vivo import SesionEnVivo, ParticipanteVivo, RespuestaVivo  # noqa: F401
from app.models.suscripcion import Suscripcion, EventoPago  # noqa: F401

# Normaliza el esquema de Render/Heroku: SQLAlchemy 2.0 exige 'postgresql://'.
_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if _db_url.startswith("sqlite") else {}
engine = create_engine(_db_url, future=True, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def _seed_cohorte_showcase(db) -> None:
    """Cohorte SHOWCASE Q1 (DEMO-Q1): grande y bien diseñada para exhibir el módulo Investigador
    a máxima potencia. n=600, 24 ítems, 4 RA, respuestas 2PL (discriminación variable → TRI real),
    DIF UNIFORME plantado en 2 ítems (detectable; el resto limpio), grupos consentidos y
    balanceados (ambos ≥200). Enciende Rasch / TRI-2PL / CFA / DINA / DIF / dimensionalidad /
    efectos / cualitativo en verde y con potencia de publicación. Semilla fija (reproducible)."""
    import math
    import random
    from app.models.answer_key import AnswerKey, AnswerKeyItem
    from app.models.student import Student

    if db.query(Course).filter(Course.code == "DEMO-Q1").first():
        return

    course = Course(name="Demo · Showcase Q1", code="DEMO-Q1", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0, base_score_type="raw_points")
    db.add(course); db.flush()

    k, n, n_ra = 16, 540, 4    # n≥500 potencia DINA/TRI; k=16 mantiene CFA rápida (120 pares)
    assessment = Assessment(course_id=course.id, name="Evaluación integradora (showcase)",
                            status="active", has_versions=False, version_count=1, has_answer_key=True,
                            briefing_level="initial", grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(assessment); db.flush()
    ak = AnswerKey(assessment_id=assessment.id, status="valid", is_valid=True, version_coverage_ok=True,
                   annulled_items_count=0, invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()

    letras = ["A", "B", "C", "D"]
    blooms = ["recordar", "comprender", "aplicar", "analizar"]
    correctas = {}
    for q in range(1, k + 1):
        c = letras[(q * 3) % 4]; correctas[q] = c
        db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                             correct_answer=c, weight=1.0, is_annulled=False,
                             learning_outcome_id=f"RA{((q - 1) % n_ra) + 1}",
                             bloom_level=blooms[(q - 1) % len(blooms)]))
    db.flush()

    rng = random.Random(2026)
    a = [round(rng.uniform(0.9, 2.0), 2) for _ in range(k)]           # discriminacion 2PL variable
    b = [round(-2.0 + 4.0 * (j / (k - 1)), 2) for j in range(k)]      # dificultad bien esparcida
    dif_items = {4, 11}                                               # items 5 y 12: DIF uniforme
    mis = [rng.choice([l for l in letras if l != correctas[j + 1]]) for j in range(k)]
    for i in range(n):
        theta = rng.gauss(0, 1)
        sexo = "F" if i % 2 == 0 else "M"
        dep = "municipal" if (i % 5) < 2 else "particular"           # ~40% municipal (~240), resto ~360
        rut = f"Q1-{i+1:04d}"
        db.add(Student(course_id=course.id, rut=rut, nombres=f"Estudiante {i+1}",
                       apellido_paterno="Demo", sexo=sexo, dependencia=dep, consiente_equidad=True))
        answers = []
        for j in range(k):
            b_eff = b[j] + (0.8 if (j in dif_items and dep == "municipal") else 0.0)  # DIF uniforme
            p = 1.0 / (1.0 + math.exp(-a[j] * (theta - b_eff)))
            if rng.random() < p:
                answers.append(correctas[j + 1])
            elif rng.random() < 0.6:
                answers.append(mis[j])                               # concepcion erronea sistematica
            else:
                otras = [l for l in letras if l != correctas[j + 1] and l != mis[j]]
                answers.append(rng.choice(otras) if otras else mis[j])
        db.add(Scan(assessment_id=assessment.id, student_identifier=rut, status="scored",
                    detected_version="A", requires_review=False,
                    raw_ocr_payload_json={"answers": answers}))
    db.commit()


def _seed_cohorte_psicometria(db) -> None:
    """Cohorte demo para exhibir la psicometria (Rasch/DINA/DIF/dimensionalidad/invarianza)
    con datos reales. Idempotente (marcada por Course.code == 'DEMO-PSICO'). ~40 estudiantes,
    12 items etiquetados C3 (3 RA), respuestas generadas por un modelo IRT logistico con
    semilla fija. Todos los estudiantes consienten el analisis de equidad (demo)."""
    import math
    import random
    from app.models.answer_key import AnswerKey, AnswerKeyItem
    from app.models.student import Student

    if db.query(Course).filter(Course.code == "DEMO-PSICO").first():
        return

    course = Course(name="Demo · Psicometría", code="DEMO-PSICO", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0,
                    base_score_type="raw_points")
    db.add(course); db.flush()

    k, n = 12, 250      # n adecuado para psicometria estable (CFA/DINA/DIF requieren muestra)
    assessment = Assessment(course_id=course.id, name="Ensayo diagnóstico", status="active",
                            assessment_document_url=None, has_versions=False, version_count=1,
                            has_answer_key=True, briefing_level="initial",
                            grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(assessment); db.flush()

    ak = AnswerKey(assessment_id=assessment.id, status="valid", is_valid=True,
                   version_coverage_ok=True, annulled_items_count=0,
                   invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()

    letras = ["A", "B", "C", "D"]
    correctas = {}
    for q in range(1, k + 1):
        c = letras[(q * 3) % 4]
        correctas[q] = c
        db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                             correct_answer=c, weight=1.0, is_annulled=False,
                             partial_credit_rule_json=None,
                             learning_outcome_id=f"RA{(q % 3) + 1}", bloom_level="aplicar"))
    db.flush()

    rng = random.Random(42)
    b = [-1.5 + 3.0 * (j / (k - 1)) for j in range(k)]     # dificultad por item
    # Distractor de "concepcion erronea" por item: quien falla lo elige con prob 0.6 (el resto,
    # otro distractor al azar). Concentra un error sistematico -> el mapa cualitativo es real.
    mis = [rng.choice([l for l in letras if l != correctas[j + 1]]) for j in range(k)]
    for i in range(n):
        theta = rng.gauss(0, 1)                            # habilidad del estudiante
        rut = f"DEMO-{i+1:03d}"
        db.add(Student(course_id=course.id, rut=rut, nombres=f"Estudiante {i+1}",
                       apellido_paterno="Demo", sexo=("F" if i % 2 == 0 else "M"),
                       dependencia=("municipal" if i % 3 == 0 else "particular"),
                       consiente_equidad=True))
        answers = []
        for j in range(k):
            p = 1.0 / (1.0 + math.exp(-(theta - b[j])))
            if rng.random() < p:
                answers.append(correctas[j + 1])
            elif rng.random() < 0.6:
                answers.append(mis[j])                     # concepcion erronea sistematica
            else:
                otras = [l for l in letras if l != correctas[j + 1] and l != mis[j]]
                answers.append(rng.choice(otras) if otras else mis[j])
        db.add(Scan(assessment_id=assessment.id, student_identifier=rut, status="scored",
                    detected_version="A", requires_review=False,
                    raw_ocr_payload_json={"answers": answers}))
    db.commit()


def _seed_desarrollo(db) -> None:
    """Pregunta de desarrollo (open_response) con rúbrica de 2 criterios y anclas, para
    exhibir la pre-calificación con IA (F2) y la validación docente (F3). Idempotente
    (marcada por Course.code == 'DEMO-DESA'). En un curso aparte para no tocar la
    psicometría de alternativas."""
    from app.models.answer_key import (AnswerKey, AnswerKeyItem, RubricCriterion,
                                       RubricAncla, QUESTION_TYPE_OPEN_RESPONSE)

    if db.query(Course).filter(Course.code == "DEMO-DESA").first():
        return

    course = Course(name="Demo · Desarrollo", code="DEMO-DESA", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0,
                    base_score_type="raw_points")
    db.add(course); db.flush()
    a = Assessment(course_id=course.id, name="Ensayo · Sistema linfático", status="active",
                   assessment_document_url=None, has_versions=False, version_count=1,
                   has_answer_key=True, briefing_level="initial",
                   grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(a); db.flush()
    ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True, version_coverage_ok=True,
                   annulled_items_count=0, invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()
    item = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A", correct_answer="",
                         weight=20.0, is_annulled=False, question_type=QUESTION_TYPE_OPEN_RESPONSE,
                         learning_outcome_id="RA1", bloom_level="comprender",
                         enunciado="Explica la función del sistema linfático en la respuesta inmune.")
    db.add(item); db.flush()

    c1 = RubricCriterion(answer_key_item_id=item.id, name="Función de drenaje y transporte de linfa",
                         weight=1.0, order=0, nivel_exigencia="tolerante", umbral_confianza=0.7,
                         sinonimos_json=["líquido intersticial", "drenaje", "transporte"])
    db.add(c1); db.flush()
    for t, n, o in [("El sistema linfático drena el líquido intersticial y lo devuelve a la sangre, transportando linfa.", "logrado", 0),
                    ("Transporta líquido por el cuerpo.", "parcial", 1),
                    ("Bombea sangre al corazón.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c1.id, texto=t, nivel=n, order=o))
    c2 = RubricCriterion(answer_key_item_id=item.id, name="Relación con la respuesta inmune",
                         weight=1.0, order=1, nivel_exigencia="estricto", umbral_confianza=0.7,
                         sinonimos_json=["linfocitos", "ganglios linfáticos", "inmunidad"])
    db.add(c2); db.flush()
    for t, n, o in [("Los ganglios linfáticos filtran patógenos y activan linfocitos, participando en la respuesta inmune.", "logrado", 0),
                    ("Ayuda a defender el cuerpo de enfermedades.", "parcial", 1),
                    ("Solo transporta líquidos.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c2.id, texto=t, nivel=n, order=o))
    db.flush()

    # 2ª pregunta de desarrollo (peso 15 pts) — demuestra el instrumento multi-pregunta.
    item2 = AnswerKeyItem(answer_key_id=ak.id, question_number=2, version="A", correct_answer="",
                          weight=15.0, is_annulled=False, question_type=QUESTION_TYPE_OPEN_RESPONSE,
                          learning_outcome_id="RA2", bloom_level="analizar",
                          enunciado="Compara el sistema linfático con el circulatorio: una semejanza y una diferencia.")
    db.add(item2); db.flush()
    c3 = RubricCriterion(answer_key_item_id=item2.id, name="Semejanza y diferencia correctas",
                         weight=1.0, order=0, nivel_exigencia="tolerante", umbral_confianza=0.7,
                         sinonimos_json=["red de vasos", "transporte", "unidireccional"])
    db.add(c3); db.flush()
    for t, n, o in [("Ambos son redes de vasos; el linfático es unidireccional y drena hacia la sangre.", "logrado", 0),
                    ("Los dos transportan líquidos por el cuerpo.", "parcial", 1),
                    ("Son lo mismo.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c3.id, texto=t, nivel=n, order=o))
    db.flush()

    # ── Validaciones docentes (F3) simuladas: activan R (psicometría de rúbrica), MFRM
    # (severidad IA vs docente) y F4 (aprendizaje). Sin esto, esos análisis quedan inertes. ──
    import hashlib, random, math
    from app.models.validacion import RegistroValidacion
    rngv = random.Random(7)
    niveles = ["no_logrado", "parcial", "logrado"]
    crits = [(c1.name, 0.0), (c2.name, 0.7)]           # (nombre, dificultad; c2 es más estricto)

    def _nivel(theta, dif):
        p = 1.0 / (1.0 + math.exp(-(theta - dif)))
        return "logrado" if p > 0.66 else ("parcial" if p > 0.4 else "no_logrado")

    regs = []
    for s in range(18):
        theta = rngv.gauss(0.3, 1.0)
        href = "e:" + hashlib.sha256(("dev-stu-%d" % s).encode()).hexdigest()[:8]
        for cname, cdif in crits:
            niv_ia = _nivel(theta, cdif)
            conf = round(rngv.uniform(0.55, 0.95), 2)
            if rngv.random() < 0.6:                     # el docente aprueba la propuesta IA
                niv_doc, accion, com = niv_ia, "aprobado", None
            else:                                        # el docente ajusta (sesgo estricto en c2)
                idx = niveles.index(niv_ia)
                delta = -1 if (cdif > 0.3 and rngv.random() < 0.65) else rngv.choice([-1, 1])
                idx2 = max(0, min(2, idx + delta))
                niv_doc = niveles[idx2]
                accion = "ajustado" if idx2 != idx else "aprobado"
                com = ("Falta el término canónico exigido por la norma." if niv_doc != niv_ia else None)
            regs.append(RegistroValidacion(
                respuesta_ref=href + "#" + cname, criterio=cname, assessment_id=str(a.id),
                rubrica_version_hash=None, nivel_ia=niv_ia, confianza_ia=conf,
                nivel_docente=niv_doc, accion=accion, comentario=com, docente="docente@evalys.demo"))
    db.add_all(regs)
    db.commit()


def _init_schema() -> None:
    """Crea/actualiza el esquema. Fuente de verdad = Alembic (upgrade head). Si Alembic no
    está disponible o falla, cae a create_all (idempotente) para no bloquear el arranque."""
    import logging
    log = logging.getLogger("evalys")
    if settings.run_migrations:
        try:
            import os
            from alembic.config import Config
            from alembic import command
            root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # repo root
            cfg = Config(os.path.join(root, "alembic.ini"))
            cfg.set_main_option("script_location", os.path.join(root, "alembic"))  # robusto ante cwd
            command.upgrade(cfg, "head")
            log.info("Esquema al día vía Alembic (upgrade head).")
            return
        except Exception as e:  # noqa: BLE001
            log.warning("Alembic upgrade falló, se usa create_all: %s", e)
    Base.metadata.create_all(bind=engine)


def create_db_and_seed() -> None:
    _init_schema()
    # En producción real (SEED_DEMO=false) el sistema arranca vacío: los usuarios se
    # auto-registran y crean sus cursos. Los datos demo solo para exhibición.
    if not settings.seed_demo:
        return
    db = SessionLocal()
    try:
        # Usuarios demo para el login (idempotentes): permiten mostrar el producto
        # funcionando. 'profesor' es el auto-registro estandar; 'investigador' accede al
        # modulo de psicometria (RBAC).
        from app.services.auth_service import hash_password
        if not db.query(Teacher).filter(Teacher.email == "docente@evalys.demo").first():
            db.add(Teacher(email="docente@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Docente Demo", rol="profesor"))
            db.commit()
        if not db.query(Teacher).filter(Teacher.email == "investigador@evalys.demo").first():
            db.add(Teacher(email="investigador@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Investigadora Demo", rol="investigador"))
            db.commit()

        # Cohortes demo (idempotentes por su propia marca).
        _seed_cohorte_psicometria(db)
        _seed_cohorte_showcase(db)        # DEMO-Q1: showcase grande (n=600) del módulo Investigador
        _seed_desarrollo(db)

        course = db.query(Course).filter(Course.code.notin_(["DEMO-PSICO", "DEMO-DESA"])).first()
        if course:
            return

        course = Course(
            name="Morfología",
            code="DMOR-0030",
            status="draft",
            program_document_url="https://files.example/programa.pdf",
            has_learning_structure=False,
            grading_scale="chile_1_7",
            passing_threshold=60,
            base_score_type="raw_points",
        )
        db.add(course)
        db.flush()

        assessment = Assessment(
            course_id=course.id,
            name="Solemne 1",
            status="draft",
            assessment_document_url=None,
            has_versions=True,
            version_count=2,
            has_answer_key=True,
            briefing_level="initial",
        )
        db.add(assessment)
        db.flush()

        answer_key = AnswerKey(
            assessment_id=assessment.id,
            status="draft",
            is_valid=False,
            version_coverage_ok=True,
            annulled_items_count=1,
            invalid_weight_count=0,
            invalid_partial_rule_count=1,
        )
        db.add(answer_key)
        db.flush()

        db.add_all(
            [
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=1,
                    version="A",
                    correct_answer="B",
                    weight=1.0,
                    is_annulled=False,
                    partial_credit_rule_json=None,
                ),
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=1,
                    version="B",
                    correct_answer="C",
                    weight=1.0,
                    is_annulled=False,
                    partial_credit_rule_json=None,
                ),
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=2,
                    version="A",
                    correct_answer="D",
                    weight=1.0,
                    is_annulled=True,
                    partial_credit_rule_json={"invalid": True},
                ),
            ]
        )

        scan = Scan(
            assessment_id=assessment.id,
            student_identifier="student_001",
            status="requires_review",
            detected_version="B",
            requires_review=True,
            ambiguity_count=1,
            unresolved_ambiguity_count=1,
            review_reasons_json=["corrector con ambigüedad real"],
            sheet_image_url=None,
            raw_ocr_payload_json={"provider": "mock", "confidence": 0.94},
        )
        db.add(scan)
        db.commit()
    finally:
        db.close()
