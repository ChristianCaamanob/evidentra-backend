from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.scan import ResolveScanReviewIn, ResolveScanReviewOut, ScanReviewOut
from app.services import scan_service

router = APIRouter(prefix="/scans", tags=["scans"])


@router.get("/{scan_id}/review", response_model=ScanReviewOut)
def get_scan_review(scan_id: UUID, db: Session = Depends(get_db)):
    return scan_service.get_scan_review(db, scan_id)


@router.post("/{scan_id}/resolve-review", response_model=ResolveScanReviewOut)
def resolve_scan_review(
    scan_id: UUID,
    payload: ResolveScanReviewIn,
    db: Session = Depends(get_db),
):
    return scan_service.resolve_scan_review(db, scan_id)
