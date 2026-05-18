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

from fastapi import UploadFile, File, HTTPException
from app.services.scan_engine import scan_sheet
from app.models.scan import Scan

@router.post("/process-image")
async def process_scan_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    image_bytes = await file.read()
    result = scan_sheet(image_bytes)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Error al escanear")

    qr = result.qr
    if not qr or not qr.assessment_id:
        raise HTTPException(status_code=400, detail="QR no detectado")

    # Buscar scan existente o crear uno nuevo
    from app.repositories.scan_repo import ScanRepository
    repo = ScanRepository()
    scan = repo.get(db, qr.assessment_id)

    # Crear nuevo scan con los datos del OCR
    new_scan = Scan(
        assessment_id=qr.assessment_id,
        student_identifier=result.rut or "desconocido",
        status="requires_review" if result.ambiguous else "processed",
        detected_version=qr.version or "A",
        requires_review=bool(result.ambiguous),
        ambiguity_count=len(result.ambiguous or []),
        unresolved_ambiguity_count=len(result.ambiguous or []),
        review_reasons_json=["ambigüedad en respuestas"] if result.ambiguous else [],
        raw_ocr_payload_json={
            "answers": result.answers,
            "ambiguous": result.ambiguous,
            "confidence": result.confidence,
            "provider": "opencv",
        },
    )
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)

    # Calcular resultado automáticamente
    resultado = None
    try:
        from app.services.result_service import get_result
        resultado = get_result(db, new_scan.id)
    except Exception as e:
        resultado = {"error": str(e)}

    return {
        "scan_id": str(new_scan.id),
        "rut": result.rut,
        "version": qr.version,
        "n_questions": len(result.answers or []),
        "answers": result.answers,
        "ambiguous": result.ambiguous,
        "requires_review": new_scan.requires_review,
        "debug_image": result.debug_image,
        "resultado": resultado,
    }
