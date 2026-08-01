"""
Cuenta global del alumno (app Runi): registro e inicio de sesión con passkey (WebAuthn).

Registro (2 pasos): (1) opciones con RUT + nombre + apellido → crea/ubica la cuenta y emite un
reg_token JWT con el challenge; (2) verifica la credencial y guarda la passkey → sesión.
Login (2 pasos): (1) opciones (passkey descubrible, sin escribir RUT) con login_token; (2) verifica
la aserción contra la passkey enrolada → sesión. Solo se guarda la clave pública; nunca la biometría.

Seguridad: una cuenta con passkey ACTIVA no puede re-registrarse a ciegas (evita apropiación de un
RUT ajeno); en ese caso el frontend debe pedir iniciar sesión. El challenge viaja firmado (JWT),
userVerification requerido, attestation "none", credencial descubrible (resident key).
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unprocessable
from app.models.student_account import StudentAccount, StudentPasskey
from app.services import asistencia_webauthn as awa
from app.services import auth_service
from app.services import silabo_service as sil

_TTL_CEREMONIA = 300     # s para completar registro/login
_P_REG = "stu_reg"
_P_LOGIN = "stu_login"
_P_SESS = "stu_sess"


def _limpia(s, n=120):
    return str(s or "").strip()[:n]


def _dv_ok(rut_norm: str) -> bool:
    """Valida el dígito verificador del RUT chileno (norm = cuerpo+dv, sin puntos ni guion; k minúscula)."""
    if len(rut_norm) < 2:
        return False
    cuerpo, dv = rut_norm[:-1], rut_norm[-1].upper()
    if not cuerpo.isdigit():
        return False
    s, m = 0, 2
    for c in reversed(cuerpo):
        s += int(c) * m
        m = 2 if m == 7 else m + 1
    r = 11 - (s % 11)
    esperado = "0" if r == 11 else "K" if r == 10 else str(r)
    return dv == esperado


def _cuenta_dict(c: StudentAccount) -> dict:
    nom = sil._nombre_amable(c.nombres, c.apellido_paterno) or c.nombres or "Alumno"
    return {"sid": str(c.id), "rut": c.rut, "nombres": c.nombres,
            "apellido_paterno": c.apellido_paterno, "apellido_materno": c.apellido_materno,
            "nombre": nom}


def _sesion_token(c: StudentAccount) -> str:
    # 7 días (create_token) — al vencer, un toque biométrico vuelve a iniciar sesión.
    return auth_service.create_token({"p": _P_SESS, "sid": str(c.id), "rut": c.rut,
                                      "nombre": _cuenta_dict(c)["nombre"]})


def sesion_desde_token(db: Session, token: str) -> dict | None:
    """Valida un token de sesión de alumno y devuelve su identidad (o None)."""
    p = auth_service.decode_token(token or "")
    if not p or p.get("p") != _P_SESS or not p.get("sid"):
        return None
    try:
        c = db.query(StudentAccount).filter(StudentAccount.id == _uuid.UUID(str(p["sid"]))).first()
    except Exception:  # noqa: BLE001
        return None
    return _cuenta_dict(c) if c else None


# ── registro ─────────────────────────────────────────────────────────────────
def registrar_opciones(db, rut, nombres, ap_paterno, ap_materno="", origin_header=None) -> dict:
    """Paso 1: valida RUT+nombre, crea/ubica la cuenta y devuelve las opciones de creación de passkey."""
    from webauthn import generate_registration_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, UserVerificationRequirement, ResidentKeyRequirement,
        AttestationConveyancePreference, PublicKeyCredentialDescriptor)

    rn = sil._norm_rut(rut)
    if not _dv_ok(rn):
        raise unprocessable("El RUT no es válido; revísalo (incluye el dígito verificador).")
    nombres = _limpia(nombres)
    ap_paterno = _limpia(ap_paterno)
    ap_materno = _limpia(ap_materno)
    if not nombres or not ap_paterno:
        raise unprocessable("Escribe tu nombre y tu apellido.")

    c = db.query(StudentAccount).filter(StudentAccount.rut == rn).first()
    if c and any(d.activo for d in c.passkeys):
        # El RUT ya tiene passkey activa → no re-registrar a ciegas; que inicie sesión.
        return {"ok": False, "motivo": "ya_registrado"}
    if not c:
        c = StudentAccount(rut=rn, nombres=nombres, apellido_paterno=ap_paterno, apellido_materno=ap_materno)
        db.add(c)
        db.flush()
    else:
        c.nombres = nombres or c.nombres
        c.apellido_paterno = ap_paterno or c.apellido_paterno
        c.apellido_materno = ap_materno or c.apellido_materno

    rp_id, rp_name, _o = awa._rp(origin_header)
    excluir = [PublicKeyCredentialDescriptor(id=awa._b64u_dec(d.credential_id)) for d in c.passkeys if d.activo]
    challenge = os.urandom(32)
    dd = _cuenta_dict(c)
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=rp_name, user_id=c.id.bytes, user_name=c.rut,
        user_display_name=dd["nombre"], challenge=challenge,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.REQUIRED),   # passkey descubrible → login sin escribir RUT
        exclude_credentials=excluir)
    db.commit()
    tok = auth_service.create_token({"p": _P_REG, "sid": str(c.id),
                                     "wa": awa._b64u(challenge), "exp": int(time.time()) + _TTL_CEREMONIA})
    return {"ok": True, "options": json.loads(options_to_json(opts)), "rp_id": rp_id, "reg_token": tok}


def registrar_verificar(db, reg_token, credential, origin_header=None) -> dict:
    """Paso 2: verifica la credencial recién creada y persiste la passkey → sesión."""
    from webauthn import verify_registration_response

    p = auth_service.decode_token(reg_token or "")
    if not p or p.get("p") != _P_REG or not p.get("wa") or not p.get("sid"):
        raise conflict("El registro venció; vuelve a intentarlo.")
    try:
        c = db.query(StudentAccount).filter(StudentAccount.id == _uuid.UUID(str(p["sid"]))).first()
    except Exception:  # noqa: BLE001
        c = None
    if not c:
        raise not_found("Cuenta no encontrada.")
    rp_id, _n, origin = awa._rp(origin_header)
    cred = credential if isinstance(credential, str) else json.dumps(credential)
    try:
        vr = verify_registration_response(
            credential=cred, expected_challenge=awa._b64u_dec(p["wa"]),
            expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo registrar la passkey: {e}")

    cred_id = awa._b64u(vr.credential_id) if isinstance(vr.credential_id, (bytes, bytearray)) else str(vr.credential_id)
    pub = vr.credential_public_key
    pub_b64 = base64.b64encode(pub).decode() if isinstance(pub, (bytes, bytearray)) else str(pub)
    if db.query(StudentPasskey).filter(StudentPasskey.credential_id == cred_id).first():
        raise conflict("Esa passkey ya está registrada.")
    db.add(StudentPasskey(account_id=c.id, credential_id=cred_id, public_key=pub_b64,
                          sign_count=int(getattr(vr, "sign_count", 0) or 0),
                          aaguid=str(getattr(vr, "aaguid", "") or "")[:64] or None,
                          label="passkey", activo=True))
    db.commit()
    return {"ok": True, "sesion": _sesion_token(c), "alumno": _cuenta_dict(c)}


# ── login ─────────────────────────────────────────────────────────────────────
def login_opciones(db, origin_header=None) -> dict:
    """Paso 1: opciones de aserción para una passkey DESCUBRIBLE (el sistema ofrece la cuenta correcta)."""
    from webauthn import generate_authentication_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement

    rp_id, _n, _o = awa._rp(origin_header)
    challenge = os.urandom(32)
    opts = generate_authentication_options(
        rp_id=rp_id, challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED)   # allow vacío → passkey descubrible
    tok = auth_service.create_token({"p": _P_LOGIN, "wa": awa._b64u(challenge),
                                     "exp": int(time.time()) + _TTL_CEREMONIA})
    return {"ok": True, "options": json.loads(options_to_json(opts)), "rp_id": rp_id, "login_token": tok}


def login_verificar(db, login_token, credential, origin_header=None) -> dict:
    """Paso 2: verifica la aserción contra la passkey enrolada e inicia sesión."""
    from webauthn import verify_authentication_response

    p = auth_service.decode_token(login_token or "")
    if not p or p.get("p") != _P_LOGIN or not p.get("wa"):
        raise conflict("El inicio de sesión venció; vuelve a intentarlo.")
    rp_id, _n, origin = awa._rp(origin_header)
    cred = credential if isinstance(credential, dict) else json.loads(credential)
    cred_id = cred.get("id") or cred.get("rawId")
    disp = db.query(StudentPasskey).filter(
        StudentPasskey.credential_id == str(cred_id or ""), StudentPasskey.activo.is_(True)).first()
    if not disp:
        raise not_found("Esta passkey no está registrada. Primero crea tu cuenta.")
    try:
        va = verify_authentication_response(
            credential=json.dumps(cred), expected_challenge=awa._b64u_dec(p["wa"]),
            expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=base64.b64decode(disp.public_key),
            credential_current_sign_count=disp.sign_count, require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")
    nuevo = int(getattr(va, "new_sign_count", 0) or 0)
    disp.sign_count = max(nuevo, disp.sign_count or 0)
    db.commit()
    c = disp.cuenta
    if not c:
        raise not_found("Cuenta no encontrada.")
    return {"ok": True, "sesion": _sesion_token(c), "alumno": _cuenta_dict(c)}
