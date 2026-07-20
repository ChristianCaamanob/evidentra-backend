"""
Router de suscripciones y pagos.

Autenticado (el usuario de la sesion):
  POST /suscripciones/trial      -> inicia el trial (features premium por N dias)
  POST /suscripciones/checkout   -> {plan} -> URL de pago del gateway (Flow)
  POST /suscripciones/cancelar   -> cancela (conserva plan hasta fin de periodo)
  GET  /suscripciones/mia        -> estado + plan efectivo + entitlements

Publico:
  GET  /planes                   -> catalogo de planes y precios
  POST /pagos/webhook/{gateway}  -> el gateway confirma/rechaza el pago (idempotente)

No se almacena dato de tarjeta (PCI); cada evento queda en un log inmutable (G5).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, usuario_actual
from app.models.teacher import Teacher
from app.services import pagos_service, planes_service

router = APIRouter(tags=["pagos"])


@router.get("/planes")
def catalogo_planes():
    return planes_service.listar_planes()


@router.post("/suscripciones/trial")
def iniciar_trial(usuario: Teacher = Depends(usuario_actual), db: Session = Depends(get_db)):
    sus = pagos_service.iniciar_trial(db, str(usuario.id))
    return pagos_service.resumen(db, str(usuario.id), usuario.rol) | {"estado": sus.estado}


@router.post("/suscripciones/checkout")
def checkout(payload: dict, usuario: Teacher = Depends(usuario_actual),
             db: Session = Depends(get_db)):
    return pagos_service.iniciar_checkout(db, str(usuario.id), payload.get("plan", ""))


@router.post("/suscripciones/cancelar")
def cancelar(usuario: Teacher = Depends(usuario_actual), db: Session = Depends(get_db)):
    pagos_service.cancelar(db, str(usuario.id))
    return pagos_service.resumen(db, str(usuario.id), usuario.rol)


@router.get("/suscripciones/mia")
def mi_suscripcion(usuario: Teacher = Depends(usuario_actual), db: Session = Depends(get_db)):
    return pagos_service.resumen(db, str(usuario.id), usuario.rol)


@router.post("/pagos/webhook/{gateway}")
def webhook(gateway: str, payload: dict, db: Session = Depends(get_db)):
    return pagos_service.procesar_evento(db, gateway, payload)
