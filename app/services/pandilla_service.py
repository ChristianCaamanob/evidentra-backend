"""Compuerta passkey → ubicación de la Pandilla (Fase 2).

Reutiliza las passkeys de ASISTENCIA (DispositivoWebAuthn sobre AsistenciaMatricula) como PRUEBA de
identidad antes de compartir/ver ubicación real. El RUT/matrícula IDENTIFICA (nombre + nómina); la
passkey AUTENTICA (posesión de la llave + verificación de usuario). Este servicio NO habilita la
ubicación por sí solo — la ubicación real sigue tras feature flag + revisión legal/DPIA (ver
docs/pandilla-auth-fase2.md). Solo emite un token corto que PRUEBA la identidad del alumno.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unprocessable
from app.models.asistencia import AsistenciaMatricula, DispositivoWebAuthn
from app.services import asistencia_webauthn as awa
from app.services import auth_service
from app.services import silabo_service as sil

_TTL_RETO = 180     # s para completar la ceremonia (get)
_TTL_UBIC = 600     # s de validez del token de ubicación tras probar la passkey
_P_RETO = "pandilla_ubi_reto"
_P_OK = "pandilla_ubi_ok"


def _curso_id(a):
    try:
        return _uuid.UUID(str(a.course_id))
    except Exception:  # noqa: BLE001
        return None


def _matricula_por_valor(db, cid, valor):
    """Encuentra la matrícula (asistencia) del curso por RUT o por identificador/matrícula."""
    nr, nid = sil._norm_rut(valor), sil._norm_id(valor)
    for m in db.query(AsistenciaMatricula).filter(AsistenciaMatricula.course_id == cid).all():
        if (len(nr) >= 7 and sil._norm_rut(m.rut) == nr) or \
           (len(nid) >= 4 and m.identificador and sil._norm_id(m.identificador) == nid):
            return m
    return None


def reto_ubicacion(db: Session, codigo: str, valor: str, origin_header=None) -> dict:
    """Paso 1: opciones de aserción WebAuthn para probar la passkey del alumno.
    {ok:False, motivo:'sin_nomina'|'sin_passkey'} si no aplica (el frontend degrada sin ubicación)."""
    from webauthn import generate_authentication_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement, PublicKeyCredentialDescriptor

    a = sil.agente_por_codigo(db, codigo)
    cid = _curso_id(a)
    if cid is None:
        return {"ok": False, "motivo": "sin_nomina"}
    m = _matricula_por_valor(db, cid, valor)
    if not m:
        return {"ok": False, "motivo": "sin_nomina"}
    activos = [d for d in m.dispositivos if d.activo]
    if not activos:
        return {"ok": False, "motivo": "sin_passkey"}

    rp_id, _n, _o = awa._rp(origin_header)
    challenge = os.urandom(32)
    allow = [PublicKeyCredentialDescriptor(id=awa._b64u_dec(d.credential_id)) for d in activos]
    opts = generate_authentication_options(
        rp_id=rp_id, challenge=challenge, allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED)
    tok = auth_service.create_token({"wa": awa._b64u(challenge), "p": _P_RETO,
                                     "mat": str(m.id), "cid": str(cid),
                                     "exp": int(time.time()) + _TTL_RETO})
    return {"ok": True, "options": json.loads(options_to_json(opts)), "rp_id": rp_id, "reto_token": tok}


def verificar_ubicacion(db: Session, codigo: str, credential, reto_token: str, origin_header=None) -> dict:
    """Paso 2: verifica la aserción contra la passkey enrolada. Si es válida, emite un token corto
    que PRUEBA la identidad (ligado a matrícula+curso). NO comparte ubicación todavía."""
    from webauthn import verify_authentication_response

    payload = auth_service.decode_token(reto_token or "")
    if not payload or payload.get("p") != _P_RETO or not payload.get("wa"):
        raise conflict("La verificación venció o no es válida; vuelve a intentarlo.")
    challenge = awa._b64u_dec(payload["wa"])
    rp_id, _n, origin = awa._rp(origin_header)

    cred = credential if isinstance(credential, dict) else json.loads(credential)
    cred_id = cred.get("id") or cred.get("rawId")
    disp = db.query(DispositivoWebAuthn).filter(
        DispositivoWebAuthn.credential_id == str(cred_id or ""),
        DispositivoWebAuthn.activo.is_(True)).first()
    if not disp:
        raise not_found("Esa passkey no está enrolada.")
    if str(disp.matricula_id) != str(payload.get("mat")):
        raise conflict("La passkey no corresponde a quien inició la verificación.")

    try:
        va = verify_authentication_response(
            credential=json.dumps(cred), expected_challenge=challenge, expected_rp_id=rp_id,
            expected_origin=origin, credential_public_key=base64.b64decode(disp.public_key),
            credential_current_sign_count=disp.sign_count, require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")

    nuevo = int(getattr(va, "new_sign_count", 0) or 0)
    if disp.sign_count and nuevo and nuevo <= disp.sign_count:
        pass  # posible clonación → bandera silenciosa (no rechazo); la ubicación real vendrá con más control
    disp.sign_count = max(nuevo, disp.sign_count or 0)
    db.commit()

    ubic = auth_service.create_token({"p": _P_OK, "mat": payload.get("mat"), "cid": payload.get("cid"),
                                      "exp": int(time.time()) + _TTL_UBIC})
    # La ubicación real permanece BLOQUEADA por flag institucional + DPIA: aquí solo se PRUEBA la identidad.
    return {"ok": True, "ubicacion_token": ubic, "expira_en": _TTL_UBIC, "ubicacion_habilitada": False}
