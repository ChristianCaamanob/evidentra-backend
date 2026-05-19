from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.result import ImmediateResultOut
from app.services import result_service

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/{scan_id}", response_model=ImmediateResultOut)
def get_result(scan_id: UUID, db: Session = Depends(get_db)):
    import traceback, logging
    logger = logging.getLogger("evalys")
    try:
        return result_service.get_result(db, scan_id)
    except Exception as e:
        logger.error(f"Error en get_result {scan_id}: {traceback.format_exc()}")
        raise
