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

from typing import Optional
from fastapi import UploadFile, File, Form, HTTPException
from app.services.scan_engine import scan_sheet
from app.models.scan import Scan

@router.post("/process-image")
async def process_scan_image(
    file: UploadFile = File(...),
    assessment_id: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    n_questions: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    image_bytes = await file.read()
    result = scan_sheet(image_bytes, n_questions_override=n_questions or 0)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Error al escanear")

    qr = result.qr
    # assessment_id puede venir del parametro (hoja v6 sin QR) o del QR (hojas viejas)
    final_aid = assessment_id or (qr.assessment_id if qr else None)
    final_version = result.detected_version or version or (qr.version if qr else None) or "A"
    if not final_aid:
        raise HTTPException(status_code=400, detail="No se pudo identificar la evaluacion (sin QR ni assessment_id)")

    # Crear nuevo scan con los datos del OCR
    new_scan = Scan(
        assessment_id=final_aid,
        student_identifier=result.rut or "desconocido",
        status="requires_review" if result.ambiguous else "processed",
        detected_version=final_version,
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
        "version": final_version,
        "detected_version": final_version,
        "n_questions": len(result.answers or []),
        "answers": result.answers,
        "ambiguous": result.ambiguous,
        "requires_review": new_scan.requires_review,
        "debug_image": result.debug_image,
        "resultado": resultado,
    }

@router.post("/process-pdf")
async def process_scan_pdf(
    file: UploadFile = File(...),
    assessment_id: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    n_questions: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    import fitz
    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
    image_bytes = pix.tobytes("jpeg")
    result = scan_sheet(image_bytes, n_questions_override=n_questions or 0)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Error al escanear")
    qr = result.qr
    final_aid = assessment_id or (qr.assessment_id if qr else None)
    final_version = result.detected_version or version or (qr.version if qr else None) or "A"
    if not final_aid:
        raise HTTPException(status_code=400, detail="No se pudo identificar la evaluacion (sin QR ni assessment_id)")
    new_scan = Scan(
        assessment_id=final_aid,
        student_identifier=result.rut or "desconocido",
        status="requires_review" if result.ambiguous else "processed",
        detected_version=final_version,
        requires_review=bool(result.ambiguous),
        ambiguity_count=len(result.ambiguous or []),
        unresolved_ambiguity_count=len(result.ambiguous or []),
        review_reasons_json=["ambigüedad en respuestas"] if result.ambiguous else [],
        raw_ocr_payload_json={"answers": result.answers, "ambiguous": result.ambiguous, "confidence": result.confidence, "provider": "opencv"},
    )
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    resultado = None
    try:
        from app.services.result_service import get_result
        resultado = get_result(db, new_scan.id)
    except Exception as e:
        resultado = {"error": str(e)}
    return {"scan_id": str(new_scan.id), "rut": result.rut, "version": final_version, "detected_version": final_version,
            "n_questions": len(result.answers or []), "answers": result.answers,
            "ambiguous": result.ambiguous, "requires_review": new_scan.requires_review,
            "debug_image": result.debug_image, "resultado": resultado}


# --- borrado de escaneo (limpieza de registros) ---
from app.repositories.scan_repo import ScanRepository as _ScanRepoDel
from app.core.errors import not_found as _not_found_scan

_scan_repo_del = _ScanRepoDel()


@router.delete("/{scan_id}")
def delete_scan(scan_id: UUID, db: Session = Depends(get_db)):
    deleted = _scan_repo_del.delete(db, scan_id)
    if not deleted:
        raise _not_found_scan("Escaneo no encontrado.")
    return {"deleted": True, "scan_id": str(scan_id)}
