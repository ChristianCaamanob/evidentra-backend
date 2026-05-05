from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()


def get_result(db: Session, scan_id):
    scan = scan_repo.get(db, scan_id)
    if not scan:
        raise not_found("Escaneo no encontrado.")
    if scan.requires_review:
        raise conflict("No puede generarse el resultado porque el escaneo aún requiere revisión.")

    answer_key = answer_key_repo.get_by_assessment_id(db, scan.assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("No puede generarse el resultado porque la pauta no está validada.")

    return {
        "scan_id": scan.id,
        "raw_score": 31.0,
        "percentage": 77.5,
        "final_grade": 5.6,
        "pass_status": "approved",
        "percentile": 68,
    }
