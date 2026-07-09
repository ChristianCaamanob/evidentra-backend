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


def create_db_and_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Usuario demo para el login (idempotente): permite mostrar el producto
        # funcionando sin datos reales. Rol 'profesor' (el auto-registro estandar).
        from app.services.auth_service import hash_password
        if not db.query(Teacher).filter(Teacher.email == "docente@evalys.demo").first():
            db.add(Teacher(email="docente@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Docente Demo", rol="profesor"))
            db.commit()

        course = db.query(Course).first()
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
