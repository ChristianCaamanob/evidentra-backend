"""
Enrolamiento de passkeys (WebAuthn) para asistencia — AS2.

Ceremonia de registro en dos pasos: (1) el servidor emite opciones con un challenge
aleatorio de un solo uso (guardado transitoriamente en la matrícula); (2) el navegador crea
la passkey y devuelve la credencial, que el servidor verifica con py_webauthn y persiste
SOLO la clave pública + credentialId (nunca biometría). Una credencial activa por matrícula.

Precauciones aplicadas: RP ID = dominio del frontend; origin/type verificados por la
librería; userVerification requerido; attestation "none"; challenge de un solo uso con TTL.
"""
from __future__ import annotations

import base64
import os
import time

from app.core.config import settings
from app.core.errors import conflict, not_found, unprocessable
from app.models.asistencia import (
    AsistenciaMatricula, DispositivoWebAuthn, MAT_VALIDADO, MAT_ACTIVO,
)

_CHALLENGE_TTL = 300   # 5 min para completar el registro


def _rp(origin_header: str | None) -> tuple[str, str, str]:
    """Resuelve (rp_id, rp_name, origin). Config explícita > header Origin de la petición."""
    origin = (settings.webauthn_origin or origin_header or "").strip().rstrip("/")
    rp_id = settings.webauthn_rp_id.strip()
    if not rp_id and origin:
        # host sin esquema ni puerto
        host = origin.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        rp_id = host
    if not (rp_id and origin):
        raise unprocessable("WebAuthn no configurado (RP ID/origin). Define WEBAUTHN_RP_ID y "
                            "WEBAUTHN_ORIGIN, o llama desde el frontend con header Origin.")
    return rp_id, (settings.webauthn_rp_name or "Evalys"), origin


def _matricula_por_token(db, invite_token) -> AsistenciaMatricula:
    m = db.query(AsistenciaMatricula).filter(
        AsistenciaMatricula.invite_token == str(invite_token or "")).first()
    if not m:
        raise not_found("Invitación no válida o vencida.")
    return m


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64u_dec(s: str) -> bytes:
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── registro (enrolamiento) ───────────────────────────────────────────────────────────
def opciones_registro(db, invite_token, origin_header=None) -> dict:
    """Paso 1: opciones de registro (requiere identidad validada presencialmente)."""
    import json
    from webauthn import generate_registration_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, UserVerificationRequirement, ResidentKeyRequirement,
        AuthenticatorAttachment, AttestationConveyancePreference, PublicKeyCredentialDescriptor)

    m = _matricula_por_token(db, invite_token)
    if m.estado not in (MAT_VALIDADO, MAT_ACTIVO):
        raise conflict("Tu identidad aún no ha sido validada presencialmente por el docente.")
    rp_id, rp_name, _origin = _rp(origin_header)

    excluir = [PublicKeyCredentialDescriptor(id=_b64u_dec(d.credential_id))
               for d in m.dispositivos if d.activo]
    challenge = os.urandom(32)
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=rp_name, user_id=m.id.bytes, user_name=m.correo,
        user_display_name=m.nombre, challenge=challenge,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED),
        exclude_credentials=excluir)
    m.webauthn_challenge = _b64u(challenge)
    m.webauthn_challenge_exp = int(time.time()) + _CHALLENGE_TTL
    db.commit()
    return {"options": json.loads(options_to_json(opts)), "rp_id": rp_id}


def verificar_registro(db, invite_token, credential, origin_header=None, verify_fn=None) -> dict:
    """Paso 2: verifica la credencial y registra la passkey (una activa por matrícula)."""
    import json
    m = _matricula_por_token(db, invite_token)
    if not m.webauthn_challenge or (m.webauthn_challenge_exp or 0) < int(time.time()):
        raise conflict("La ceremonia de registro venció; vuelve a intentarlo.")
    rp_id, _rp_name, origin = _rp(origin_header)

    verify = verify_fn
    if verify is None:
        from webauthn import verify_registration_response
        def verify(credential, expected_challenge, expected_rp_id, expected_origin):  # noqa: E306
            cred = credential if isinstance(credential, str) else json.dumps(credential)
            return verify_registration_response(
                credential=cred, expected_challenge=expected_challenge,
                expected_rp_id=expected_rp_id, expected_origin=expected_origin,
                require_user_verification=True)

    try:
        vr = verify(credential=credential, expected_challenge=_b64u_dec(m.webauthn_challenge),
                    expected_rp_id=rp_id, expected_origin=origin)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")

    cred_id = _b64u(vr.credential_id) if isinstance(vr.credential_id, (bytes, bytearray)) else str(vr.credential_id)
    pub = vr.credential_public_key
    pub_b64 = base64.b64encode(pub).decode() if isinstance(pub, (bytes, bytearray)) else str(pub)

    # una credencial activa: revoca las anteriores
    for d in m.dispositivos:
        d.activo = False
    db.add(DispositivoWebAuthn(
        matricula_id=m.id, credential_id=cred_id, public_key=pub_b64,
        sign_count=int(getattr(vr, "sign_count", 0) or 0),
        aaguid=str(getattr(vr, "aaguid", "") or "")[:64] or None,
        transports=None, label="passkey", activo=True))
    m.estado = MAT_ACTIVO
    m.webauthn_challenge = None
    m.webauthn_challenge_exp = None
    db.commit()
    return {"ok": True, "estado": m.estado, "credential_id": cred_id}


# ── marcado con passkey (aserción sobre el desafío del QR) ────────────────────────────
def opciones_login(db, codigo, token, bucket, origin_header=None) -> dict:
    """Opciones de autenticación cuyo challenge = el desafío del QR vigente. Así la aserción
    de la passkey queda ATADA a ese QR fresco (prueba presencia-en-el-QR + posesión de la llave)."""
    import json
    from app.services import asistencia_service as asis
    from webauthn import generate_authentication_options
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement

    s = asis._sesion(db, codigo)
    challenge = asis.desafio_vigente(s, token, bucket)
    if challenge is None:
        raise conflict("El código QR venció o no es válido; escanea el que está en pantalla.")
    rp_id, _rp_name, _origin = _rp(origin_header)
    opts = generate_authentication_options(
        rp_id=rp_id, challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED)   # allow_credentials vacío = passkey descubrible
    return {"options": json.loads(options_to_json(opts)), "rp_id": rp_id}


def marcar_con_passkey(db, codigo, bucket, credential, origin_header=None,
                       ip=None, ua=None, verify_fn=None) -> dict:
    """Verifica la aserción WebAuthn sobre el desafío del QR y registra la asistencia.
    Identifica al alumno por la credencial (userHandle = matrícula); verifica signCount."""
    import json
    from app.services import asistencia_service as asis
    s = asis._sesion(db, codigo)
    # el challenge debe ser el del bucket que firmó, aún vigente (ventana + tolerancia)
    if not asis.ceremonia_vigente(bucket):
        raise conflict("El código QR venció; vuelve a escanear el que está en pantalla.")
    challenge = asis._digest(s.secreto, str(s.id), int(bucket))
    rp_id, _rp_name, origin = _rp(origin_header)

    cred = credential if isinstance(credential, dict) else json.loads(credential)
    cred_id = cred.get("id") or cred.get("rawId")
    disp = db.query(DispositivoWebAuthn).filter(
        DispositivoWebAuthn.credential_id == str(cred_id or ""), DispositivoWebAuthn.activo.is_(True)).first()
    if not disp:
        raise not_found("Este dispositivo no está enrolado para asistencia.")

    verify = verify_fn
    if verify is None:
        from webauthn import verify_authentication_response
        def verify(credential, expected_challenge, expected_rp_id, expected_origin,  # noqa: E306
                   credential_public_key, credential_current_sign_count):
            c = credential if isinstance(credential, str) else json.dumps(credential)
            return verify_authentication_response(
                credential=c, expected_challenge=expected_challenge, expected_rp_id=expected_rp_id,
                expected_origin=expected_origin, credential_public_key=credential_public_key,
                credential_current_sign_count=credential_current_sign_count,
                require_user_verification=True)

    try:
        va = verify(credential=cred, expected_challenge=challenge, expected_rp_id=rp_id,
                    expected_origin=origin, credential_public_key=base64.b64decode(disp.public_key),
                    credential_current_sign_count=disp.sign_count)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No se pudo verificar la passkey: {e}")

    flags = []
    nuevo = int(getattr(va, "new_sign_count", 0) or 0)
    if disp.sign_count and nuevo and nuevo <= disp.sign_count:
        flags.append("sign_count_no_aumento")   # posible clonación del autenticador (bandera, no rechazo)
    disp.sign_count = max(nuevo, disp.sign_count or 0)

    m = disp.matricula
    if str(m.course_id) != str(s.course_id):
        raise conflict("La passkey no corresponde a este curso.")
    return asis.marcar_verificado(db, s, m, ip=ip, ua=ua, metodo="passkey", flags_extra=flags)


def revocar_dispositivos(db, matricula_id) -> dict:
    """Recuperación (cambio/pérdida de teléfono): revoca las passkeys activas y devuelve la
    matrícula a 'validado' para re-enrolar. Lo ejecuta el docente/admin tras verificar."""
    import uuid
    try:
        mid = uuid.UUID(str(matricula_id))
    except (ValueError, TypeError):
        raise not_found("Matrícula no válida.")
    m = db.query(AsistenciaMatricula).filter(AsistenciaMatricula.id == mid).first()
    if not m:
        raise not_found("Matrícula no encontrada.")
    n = 0
    for d in m.dispositivos:
        if d.activo:
            d.activo = False
            n += 1
    if m.estado == MAT_ACTIVO:
        m.estado = MAT_VALIDADO
    db.commit()
    return {"revocados": n, "estado": m.estado}
