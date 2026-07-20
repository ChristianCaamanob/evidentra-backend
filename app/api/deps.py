from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.teacher import (
    Teacher, ROL_PROFESOR, ROL_INVESTIGADOR, ROL_DIRECTOR, ROL_CREADOR,
)
from app.services import auth_service

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def usuario_actual(cred: HTTPAuthorizationCredentials = Depends(_bearer),
                   db: Session = Depends(get_db)) -> Teacher:
    """Usuario autenticado a partir del Bearer JWT. 401 si falta o es invalido."""
    if cred is None or not cred.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Falta el token de autenticacion.")
    usuario = auth_service.usuario_desde_token(db, cred.credentials)
    if usuario is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido o expirado.")
    return usuario


def requiere_rol(*roles: str):
    """Dependencia-guarda: pasa si el rol del usuario esta en `roles`. El creador SIEMPRE
    pasa (superadmin). Devuelve una dependencia para usar con Depends()."""
    permitidos = set(roles) | {ROL_CREADOR}

    def _guarda(usuario: Teacher = Depends(usuario_actual)) -> Teacher:
        if usuario.rol not in permitidos:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Tu rol ('{usuario.rol}') no tiene acceso a este recurso.")
        return usuario

    return _guarda


# Guardas por modulo (el creador queda incluido en todas):
#   profesor      -> profesor, investigador
#   investigador  -> investigador
#   lectura_datos -> profesor, investigador, director (ver/exportar datos estudiante+profesor)
#   creador       -> solo creador (estructural, licencias)
req_profesor = requiere_rol(ROL_PROFESOR, ROL_INVESTIGADOR)
req_investigador = requiere_rol(ROL_INVESTIGADOR)
req_lectura_datos = requiere_rol(ROL_PROFESOR, ROL_INVESTIGADOR, ROL_DIRECTOR)
req_creador = requiere_rol()


def requiere_plan(feature: str):
    """Dependencia-guarda por ENTITLEMENT: pasa si el plan de la cuenta incluye `feature`.

    Ortogonal a requiere_rol (rol = quien eres; plan = que pagaste). El creador pasa
    siempre. 402 Payment Required cuando el plan no alcanza (se necesita upgrade)."""
    def _guarda(usuario: Teacher = Depends(usuario_actual),
                db: Session = Depends(get_db)) -> Teacher:
        from app.services import pagos_service
        if not pagos_service.tiene_feature(db, str(usuario.id), feature, usuario.rol):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"Tu plan no incluye '{feature}'. Actualiza tu suscripcion para acceder.")
        return usuario

    return _guarda
