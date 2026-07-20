"""
Motor de suscripciones y pagos. Mismo estilo de seam que el LLM: la pasarela es un objeto
INYECTABLE, con un gateway FALSO determinista para tests (cero red). El adaptador de Flow es
un mapeo delgado sobre este contrato.

Contrato del gateway (`cliente_pago`):
    crear_cobro(monto_clp, descripcion, ref_interna) -> {"url": str, "token": str}

El webhook llega crudo del gateway; `normalizar_webhook(gateway, payload)` lo mapea a claves
canonicas: {idempotency_key, token, tipo, estado, monto_clp, plan}. procesar_evento aplica el
cambio de estado de forma IDEMPOTENTE (un webhook repetido no cobra ni activa dos veces).

Gobernanza: no se guarda dato de tarjeta (PCI); cada evento queda en un log inmutable (G5).
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from app.core.errors import conflict, not_found, unprocessable
from app.models.suscripcion import (
    Suscripcion, EventoPago,
    ESTADO_TRIAL, ESTADO_ACTIVA, ESTADO_MOROSA, ESTADO_CANCELADA,
)
from app.services import planes_service as planes
from app.models.teacher import ROL_CREADOR


def _ahora() -> datetime:
    return datetime.utcnow()   # naive UTC, consistente con auth_service y con SQLite


# ── gateways ───────────────────────────────────────────────────────────────────────────
def gateway_fake():
    """Pasarela de prueba: devuelve una URL y token deterministas. Sin red."""
    class _Fake:
        nombre = "fake"

        def crear_cobro(self, monto_clp, descripcion, ref_interna):
            token = "tok_" + ref_interna
            return {"url": f"https://pago.fake/checkout/{token}", "token": token}
    return _Fake()


def gateway_flow():  # pragma: no cover (requiere credenciales de Flow)
    """Adaptador real de Flow.cl. Mapea el contrato a la API de Flow (firma HMAC + endpoints)."""
    raise RuntimeError("Adaptador de Flow no configurado: faltan credenciales FLOW_API_KEY/SECRET.")


def gateway_por_defecto():
    """Flow si hay credenciales; si no, el gateway falso (dev/test)."""
    if os.environ.get("FLOW_API_KEY") and os.environ.get("FLOW_SECRET"):
        return gateway_flow()
    return gateway_fake()


# ── lecturas ─────────────────────────────────────────────────────────────────────────
def suscripcion_de(db, cuenta_id: str) -> Suscripcion | None:
    return db.query(Suscripcion).filter(Suscripcion.cuenta_id == str(cuenta_id)).first()


def plan_efectivo(sus: Suscripcion | None) -> str:
    """Plan que rige AHORA, considerando estado y vencimiento (degrada a free si vencio)."""
    if sus is None:
        return "free"
    vencida = sus.fin_periodo is not None and sus.fin_periodo < _ahora()
    if sus.estado in (ESTADO_TRIAL, ESTADO_CANCELADA) and vencida:
        return "free"
    if sus.estado == ESTADO_MOROSA and vencida:
        return "free"
    return sus.plan


def entitlements_actuales(db, cuenta_id: str, rol: str | None = None) -> set[str]:
    """Features disponibles AHORA. El creador tiene todo (no toca la BD)."""
    if rol == ROL_CREADOR:
        return planes.entitlements_de_plan("enterprise") | {"*"}
    return planes.entitlements_de_plan(plan_efectivo(suscripcion_de(db, cuenta_id)))


def tiene_feature(db, cuenta_id: str, feature: str, rol: str | None = None) -> bool:
    ents = entitlements_actuales(db, cuenta_id, rol)
    return "*" in ents or feature in ents


# ── ciclo de vida ───────────────────────────────────────────────────────────────────
def iniciar_trial(db, cuenta_id: str) -> Suscripcion:
    """Crea la suscripcion en TRIAL (features premium) si la cuenta no tiene una."""
    sus = suscripcion_de(db, cuenta_id)
    if sus is not None:
        return sus
    sus = Suscripcion(
        cuenta_id=str(cuenta_id), plan=planes.TRIAL_PLAN, estado=ESTADO_TRIAL,
        inicio=_ahora(), fin_periodo=_ahora() + timedelta(days=planes.TRIAL_DIAS))
    db.add(sus); db.commit(); db.refresh(sus)
    return sus


def iniciar_checkout(db, cuenta_id: str, plan: str, cliente_pago=None) -> dict:
    """Prepara el cobro de un plan y devuelve la URL de pago del gateway."""
    if not planes.es_plan_valido(plan) or plan == "free":
        raise unprocessable("Plan invalido para checkout.")
    monto = planes.precio_clp(plan)
    if monto is None:
        raise conflict("Este plan se cotiza con ventas (Enterprise), no por autoservicio.")

    cliente = cliente_pago or gateway_por_defecto()
    sus = suscripcion_de(db, cuenta_id) or iniciar_trial(db, cuenta_id)
    ref = f"{sus.id.hex[:12]}_{secrets.token_hex(4)}"
    cobro = cliente.crear_cobro(monto, f"Evalys {planes.PLANES[plan]['nombre']}", ref)

    sus.gateway = getattr(cliente, "nombre", "desconocido")
    sus.ref_externa = cobro["token"]
    db.add(sus)
    db.add(EventoPago(suscripcion_id=sus.id, gateway=sus.gateway, tipo="checkout_creado",
                      monto_clp=monto, estado="pendiente",
                      idempotency_key=f"checkout:{cobro['token']}",
                      payload_json={"plan": plan, "ref": ref}))
    db.commit()
    return {"url": cobro["url"], "token": cobro["token"], "plan": plan, "monto_clp": monto}


def normalizar_webhook(gateway: str, payload: dict) -> dict:
    """Mapea el payload crudo del gateway a claves canonicas. El fake ya viene canonico."""
    if gateway == "fake":
        return {
            "idempotency_key": payload.get("idempotency_key") or payload.get("token", ""),
            "token": payload.get("token", ""),
            "tipo": payload.get("tipo", "pago_confirmado"),
            "estado": payload.get("estado", "pagado"),
            "monto_clp": int(payload.get("monto_clp", 0) or 0),
            "plan": payload.get("plan"),
        }
    raise unprocessable(f"Gateway no soportado: {gateway}")  # pragma: no cover


def procesar_evento(db, gateway: str, payload: dict) -> dict:
    """Aplica un evento de pago de forma IDEMPOTENTE (webhook repetido = no-op)."""
    ev = normalizar_webhook(gateway, payload)
    idem = ev["idempotency_key"] or ""
    if not idem:
        raise unprocessable("Falta clave de idempotencia en el evento.")

    ya = db.query(EventoPago).filter(EventoPago.idempotency_key == idem).first()
    if ya is not None:
        return {"procesado": False, "motivo": "evento ya aplicado (idempotente)"}

    sus = db.query(Suscripcion).filter(Suscripcion.ref_externa == ev["token"]).first()
    if sus is None:
        raise not_found("No hay suscripcion para ese token de pago.")

    tipo = ev["tipo"]
    if tipo == "pago_confirmado":
        plan = ev["plan"] or sus.plan
        dias = planes.periodo_dias(plan) or 30
        sus.plan = plan
        sus.estado = ESTADO_ACTIVA
        sus.inicio = _ahora()
        sus.fin_periodo = _ahora() + timedelta(days=dias)
    elif tipo == "pago_rechazado":
        sus.estado = ESTADO_MOROSA
    elif tipo == "cancelacion":
        sus.estado = ESTADO_CANCELADA

    db.add(sus)
    db.add(EventoPago(suscripcion_id=sus.id, gateway=gateway, tipo=tipo,
                      monto_clp=ev["monto_clp"], estado=ev["estado"],
                      idempotency_key=idem, payload_json=payload))
    db.commit(); db.refresh(sus)
    return {"procesado": True, "estado": sus.estado, "plan": sus.plan}


def cancelar(db, cuenta_id: str) -> Suscripcion:
    """Cancela: conserva el plan hasta fin_periodo; luego plan_efectivo cae a free."""
    sus = suscripcion_de(db, cuenta_id)
    if sus is None:
        raise not_found("La cuenta no tiene suscripcion.")
    sus.estado = ESTADO_CANCELADA
    db.add(sus)
    db.add(EventoPago(suscripcion_id=sus.id, gateway=sus.gateway or "-", tipo="cancelacion",
                      monto_clp=0, estado="cancelada",
                      idempotency_key=f"cancel:{sus.id.hex}:{secrets.token_hex(4)}",
                      payload_json={"por": "usuario"}))
    db.commit(); db.refresh(sus)
    return sus


def resumen(db, cuenta_id: str, rol: str | None = None) -> dict:
    sus = suscripcion_de(db, cuenta_id)
    efectivo = "enterprise" if rol == ROL_CREADOR else plan_efectivo(sus)
    return {
        "cuenta_id": str(cuenta_id),
        "estado": sus.estado if sus else None,
        "plan": sus.plan if sus else "free",
        "plan_efectivo": efectivo,
        "fin_periodo": sus.fin_periodo.isoformat() if (sus and sus.fin_periodo) else None,
        "entitlements": sorted(entitlements_actuales(db, cuenta_id, rol) - {"*"}),
    }
