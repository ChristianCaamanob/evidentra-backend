"""
Passkeys (WebAuthn) para el STAFF: registrar y entrar con huella / rostro (biometría del equipo).

Solo se persiste la clave pública + credentialId (nunca la biometría). El challenge de cada
ceremonia NO se guarda en BD: viaja firmado en un JWT corto (stateless, sirve con varios workers).
Reutiliza la misma librería py_webauthn y la resolución de RP del módulo de asistencia.
"""
from __future__ import annotations

import base64
import json
import os
import time

from app.core.config import settings
from app.core.errors import conflict, not_found, unprocessable
from app.models.teacher import Teacher
from app.models.teacher_passkey import TeacherPasskey
from app.services import auth_service

_CHALLENGE_TTL = 300   # 5 min


def _rp(origin_header: str | None):
    origin = (settings.webauthn_origin or origin_header or "").strip().rstrip("/")
    rp_id = (settings.webauthn_rp_id or "").strip()
    if not rp_id and origin:
        rp_id = origin.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if not (rp_id and origin):
        raise unprocessable("WebAuthn no configurado (define WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN o "
                            "llama desde el frontend con header Origin).")
    return rp_id, (settings.webauthn_rp_name or "Evalys"), origin


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64u_dec(s: str) -> bytes:
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _challenge_token(challenge: bytes, proposito: str) -> str:
    """Empaqueta el challenge en un JWT corto (no se guarda en BD)."""
    return auth_service.create_token({"wa": _b64u(challenge), "p": proposito,
                                      "exp": int(time.time()) + _CHALLENGE_TTL})


def _challenge_de_token(token: str, proposito: str) -> bytes:
    payload = auth_service.decode_token(token or "")
    if not payload or payload.get("p") != proposito or not payload.get("wa"):
        raise conflict("La ceremonia venció o no es válida; vuelve a intentarlo.")
    return _b64u_dec(payload["wa"])


# ── registro de una passkey (staff autenticado) ──────────────────────────────────────
def opciones_registro(db, teacher: Teacher, origin_header=None) -> dict:
    from webauthn import generate_registration_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, UserVerificationRequirement, ResidentKeyRequirement,
        AttestationConveyancePreference, PublicKeyCredentialDescriptor)
    rp_id, rp_name, _ = _rp(origin_header)
    existentes = db.query(TeacherPasskey).filter(
        TeacherPasskey.teacher_id == teacher.id, TeacherPasskey.activo.is_(True)).all()
    excluir = [PublicKeyCredentialDescriptor(id=_b64u_dec(d.credential_id)) for d in existentes]
    challenge = os.urandom(32)
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=rp_name, user_id=teacher.id.bytes,
        user_name=teacher.email, user_display_name=(teacher.name or teacher.email),
        challenge=challenge, attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.REQUIRED),   # passkey descubrible (login sin escribir correo)
        exclude_credentials=excluir)
    return {"options": json.loads(options_to_json(opts)), "rp_id": rp_id,
            "challenge_token": _challenge_token(challenge, "reg")}


def verificar_registro(db, teacher: Teacher, credential, challenge_token, origin_header=None, label=None) -> dict:
    from webauthn import verify_registration_response
    rp_id, _rp_name, origin = _rp(origin_header)
    esperado = _challenge_de_token(challenge_token, "reg")
    cred = credential if isinstance(credential, str) else json.dumps(credential)
    try:
        vr = verify_registration_response(
            credential=cred, expected_challenge=esperado, expected_rp_id=rp_id,
            expected_origin=origin, require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")
    cred_id = _b64u(vr.credential_id) if isinstance(vr.credential_id, (bytes, bytearray)) else str(vr.credential_id)
    if db.query(TeacherPasskey).filter(TeacherPasskey.credential_id == cred_id).first():
        raise conflict("Esta passkey ya está registrada.")
    pub = vr.credential_public_key
    pub_b64 = base64.b64encode(pub).decode() if isinstance(pub, (bytes, bytearray)) else str(pub)
    pk = TeacherPasskey(
        teacher_id=teacher.id, credential_id=cred_id, public_key=pub_b64,
        sign_count=int(getattr(vr, "sign_count", 0) or 0),
        aaguid=str(getattr(vr, "aaguid", "") or "")[:64] or None,
        label=(str(label or "").strip()[:80] or "passkey"), activo=True)
    db.add(pk); db.commit(); db.refresh(pk)
    return {"ok": True, "id": str(pk.id), "label": pk.label, "credential_id": cred_id}


# ── login con passkey (sin escribir correo/clave) ────────────────────────────────────
def opciones_login(db, origin_header=None) -> dict:
    from webauthn import generate_authentication_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    rp_id, _rp_name, _ = _rp(origin_header)
    challenge = os.urandom(32)
    opts = generate_authentication_options(
        rp_id=rp_id, challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED)   # allow_credentials vacío = passkey descubrible
    return {"options": json.loads(options_to_json(opts)), "rp_id": rp_id,
            "challenge_token": _challenge_token(challenge, "login")}


def verificar_login(db, credential, challenge_token, origin_header=None) -> dict:
    from webauthn import verify_authentication_response
    rp_id, _rp_name, origin = _rp(origin_header)
    esperado = _challenge_de_token(challenge_token, "login")
    cred = credential if isinstance(credential, dict) else json.loads(credential)
    cred_id = cred.get("id") or cred.get("rawId")
    pk = db.query(TeacherPasskey).filter(
        TeacherPasskey.credential_id == str(cred_id or ""), TeacherPasskey.activo.is_(True)).first()
    if not pk:
        raise not_found("Esta passkey no está registrada. Inicia sesión con tu contraseña.")
    try:
        va = verify_authentication_response(
            credential=(cred if isinstance(cred, str) else json.dumps(cred)),
            expected_challenge=esperado, expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=base64.b64decode(pk.public_key),
            credential_current_sign_count=pk.sign_count, require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")
    nuevo = int(getattr(va, "new_sign_count", 0) or 0)
    pk.sign_count = max(nuevo, pk.sign_count or 0)
    db.commit()
    teacher = db.get(Teacher, pk.teacher_id)
    if not teacher:
        raise not_found("Cuenta no encontrada.")
    # Misma forma que /auth/login para reutilizar el mismo cierre de sesión en el frontend.
    return {"token": auth_service.create_token(auth_service._token_payload(teacher)),
            "teacher": {"id": str(teacher.id), "email": teacher.email,
                        "name": teacher.name, "rol": teacher.rol},
            "metodo": "passkey"}


def listar(db, teacher: Teacher) -> dict:
    pks = (db.query(TeacherPasskey).filter(TeacherPasskey.teacher_id == teacher.id)
           .order_by(TeacherPasskey.created_at.desc()).all())
    return {"passkeys": [{"id": str(p.id), "label": p.label, "activo": p.activo,
                          "created_at": p.created_at.isoformat() if p.created_at else None} for p in pks]}


def revocar(db, teacher: Teacher, passkey_id) -> dict:
    import uuid as _uuid
    try:
        pid = _uuid.UUID(str(passkey_id))
    except (ValueError, TypeError):
        raise not_found("Passkey no válida.")
    p = db.query(TeacherPasskey).filter(
        TeacherPasskey.id == pid, TeacherPasskey.teacher_id == teacher.id).first()
    if not p:
        raise not_found("Passkey no encontrada.")
    db.delete(p); db.commit()
    return {"eliminado": True}
