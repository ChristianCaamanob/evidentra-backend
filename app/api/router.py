from fastapi import APIRouter, Depends

from app.api.deps import req_lectura_datos
from app.core.db import SessionLocal, engine
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
    # Motor de BD activo (sin credenciales): 'postgresql' = persistente; 'sqlite' = efímero.
    return {"status": "ok", "service": "evidentra-backend-mvp", "db": engine.dialect.name}


@api_router.get("/health/ia", tags=["health"])
def healthcheck_ia():
    """¿Está viva la clave de IA? Sin ella, Runi no responde NADA.

    Existe porque una clave inválida se manifestaba como funciones sueltas que fallaban
    (el escáner de horario devolvía un 401 crudo en pantalla) en vez de como lo que era:
    los 17 servicios de IA caídos a la vez. Nunca devuelve la clave ni parte de ella.
    """
    import os
    clave = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not clave:
        return {"ok": False, "estado": "sin_clave",
                "detalle": "ANTHROPIC_API_KEY no está definida en el entorno del servidor."}
    import anthropic
    from app.services import correccion_experta_service as ce
    try:
        anthropic.Anthropic().models.list(limit=1)
    except Exception as e:                               # noqa: BLE001
        msg = str(e)
        invalida = "authentication_error" in msg or "401" in msg
        return {"ok": False, "estado": "clave_invalida" if invalida else "error",
                "detalle": ("La clave existe pero el proveedor la rechaza; hay que rotarla."
                            if invalida else msg[:300])}
    # Listar modelos NO consume créditos ni usa el modelo: con la cuenta sin saldo, o con un id de
    # modelo rechazado, ESTO sigue devolviendo 200 mientras Runi falla en cada respuesta. Pasó en
    # producción y el health decía "ok" durante toda la caída. Por eso ahora se manda un mensaje
    # de verdad, con el mismo modelo que usa Runi.
    try:
        anthropic.Anthropic().messages.create(
            model=ce.MODELO_EXPERTO, max_tokens=4,
            messages=[{"role": "user", "content": "ping"}])
        return {"ok": True, "estado": "ok", "modelo": ce.MODELO_EXPERTO}
    except Exception as e:                               # noqa: BLE001
        msg = str(e)
        b = msg.lower()
        if "credit balance" in b or "billing" in b or "quota" in b:
            estado, detalle = "sin_saldo", "La cuenta de Anthropic no tiene saldo. Hay que recargarla."
        elif "not_found" in b or "model" in b and "does not exist" in b:
            estado, detalle = "modelo_invalido", f"El modelo «{ce.MODELO_EXPERTO}» no está disponible para esta cuenta."
        elif "rate_limit" in b or "429" in b:
            estado, detalle = "limite", "Límite de peticiones alcanzado; se recupera solo."
        elif "overloaded" in b or "529" in b:
            estado, detalle = "sobrecargado", "El proveedor está sobrecargado; se recupera solo."
        else:
            estado, detalle = "error", msg[:300]
        return {"ok": False, "estado": estado, "detalle": detalle, "modelo": ce.MODELO_EXPERTO,
                "crudo": msg[:300]}


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
from app.routes.proyectos import router as proyectos_router
api_router.include_router(proyectos_router)
from app.routes.desarrollo import router as desarrollo_router
api_router.include_router(desarrollo_router)
from app.routes.examen_oral import router as examen_oral_router
api_router.include_router(examen_oral_router)
from app.routes.profesor import router as profesor_router
api_router.include_router(profesor_router)
from app.routes.grupos import router as grupos_router
api_router.include_router(grupos_router)
from app.routes.en_vivo import router as en_vivo_router
api_router.include_router(en_vivo_router)
from app.routes.banco import router as banco_router
api_router.include_router(banco_router)
from app.routes.asistencia import router as asistencia_router
api_router.include_router(asistencia_router)
from app.routes.silabo import router as silabo_router
api_router.include_router(silabo_router)
from app.routes.evidence import router as evidence_router
api_router.include_router(evidence_router)
from app.routes.sala_estudio import router as sala_estudio_router
api_router.include_router(sala_estudio_router)
from app.routes.director import router as director_router
api_router.include_router(director_router)

from app.routes.estructura import router as estructura_router
api_router.include_router(estructura_router)
# Pagos: módulo opcional/incompleto (pagos.py, suscripcion no versionados). Se carga si existe;
# si no, NO debe tumbar toda la app (esto rompía el arranque en Render con status 1).
try:
    from app.routes.pagos import router as pagos_router
    api_router.include_router(pagos_router)
except Exception as _e:  # noqa: BLE001
    import logging
    logging.getLogger("evalys").warning("Router de pagos no disponible, se omite: %s", _e)
from app.routes.auth import router as auth_router
api_router.include_router(auth_router)
from app.routes.export import router as export_router
api_router.include_router(export_router)
from app.routes.admin_consola import router as admin_consola_router
api_router.include_router(admin_consola_router)
from app.routes.analytics import router as analytics_router
api_router.include_router(analytics_router)
from app.routes.runi_break import router as runi_break_router
api_router.include_router(runi_break_router)
from app.routes.ia_eval import router as ia_eval_router
api_router.include_router(ia_eval_router)
from app.routes.logros import router as logros_router
api_router.include_router(logros_router)

from app.routes.recompensas import router as recompensas_router
api_router.include_router(recompensas_router)
from app.routes.terminologia import router as terminologia_router
api_router.include_router(terminologia_router)
from app.routes.pandilla_logros import router as pandilla_logros_router
api_router.include_router(pandilla_logros_router)
from app.routes.experiencia import router as experiencia_router
api_router.include_router(experiencia_router)
from app.routes.research import router as research_router
api_router.include_router(research_router)
from app.routes.runi_prefs import router as runi_prefs_router
api_router.include_router(runi_prefs_router)
