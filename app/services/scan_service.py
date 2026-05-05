from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories.scan_repo import ScanRepository

repo = ScanRepository()


def get_scan_review(db: Session, scan_id):
    scan = repo.get(db, scan_id)
    if not scan:
        raise not_found("Escaneo no encontrado.")
    return {
        "id": scan.id,
        "status": scan.status,
        "detected_version": scan.detected_version,
        "requires_review": scan.requires_review,
        "ambiguity_count": scan.ambiguity_count,
        "unresolved_ambiguity_count": scan.unresolved_ambiguity_count,
        "review_reasons": scan.review_reasons_json or [],
    }


def resolve_scan_review(db: Session, scan_id):
    scan = repo.get(db, scan_id)
    if not scan:
        raise not_found("Escaneo no encontrado.")
    if not scan.requires_review:
        raise conflict("El escaneo ya no requiere revisión.")

    scan.status = "reviewed"
    scan.requires_review = False
    scan.unresolved_ambiguity_count = 0
    scan.review_reasons_json = []
    repo.save(db, scan)
    return {
        "id": scan.id,
        "status": scan.status,
        "requires_review": scan.requires_review,
        "unresolved_ambiguity_count": scan.unresolved_ambiguity_count,
    }
