from fastapi import APIRouter, Depends

from app.api.deps import req_lectura_datos
from app.core.db import SessionLocal
from app.models.assessment import Assessment
from app.models.course import Course
from app.models.scan import Scan
from app.schemas.common import BootstrapOut
from app.routes.answer_keys import router as answer_keys_router
from app.routes.assessments import router as assessments_router
from app.routes.courses import router as courses_router
from app.routes.feedback import router as feedback_router
from app.routes.results import router as results_router
from app.routes.scans import router as scans_router

api_router = APIRouter()


@api_router.get("/health", tags=["health"])
def healthcheck():
    return {"status": "ok", "service": "evidentra-backend-mvp"}


@api_router.get("/bootstrap", response_model=BootstrapOut, tags=["health"])
def bootstrap_ids():
    db = SessionLocal()
    try:
        course = db.query(Course).first()
        assessment = db.query(Assessment).first()
        scan = db.query(Scan).first()
        return {
            "course_id": str(course.id) if course else None,
            "assessment_id": str(assessment.id) if assessment else None,
            "scan_id": str(scan.id) if scan else None,
        }
    finally:
        db.close()


# Todos los routers legados requieren, como minimo, autenticacion + rol con acceso a datos
# (profesor/investigador/director/creador). Asi el director ve/exporta pero, en las rutas de
# ESCRITURA, cada endpoint anade req_profesor para excluirlo (no modifica).
_legado = dict(dependencies=[Depends(req_lectura_datos)])
api_router.include_router(courses_router, **_legado)
api_router.include_router(assessments_router, **_legado)
api_router.include_router(answer_keys_router, **_legado)
api_router.include_router(scans_router, **_legado)
api_router.include_router(results_router, **_legado)
api_router.include_router(feedback_router, **_legado)
from app.routes.investigador import router as investigador_router
api_router.include_router(investigador_router)
from app.routes.desarrollo import router as desarrollo_router
api_router.include_router(desarrollo_router)
from app.routes.profesor import router as profesor_router
api_router.include_router(profesor_router)
from app.routes.auth import router as auth_router
api_router.include_router(auth_router)
