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

_TTL_RETO = 180      # s para completar la ceremonia (get)
_TTL_UBIC = 7200     # s de validez del token de ubicación (cubre una sesión de compartir de hasta 2 h)
_P_RETO = "pandilla_ubi_reto"
_P_OK = "pandilla_ubi_ok"
_MAX_MIN = 120       # duración máxima de compartir (min)
_APROX_RADIO_M = 160.0   # radio de privacidad del modo "zona aproximada" (m)
_APROX_DEC = 3           # redondeo de coords en modo aproximado (~110 m)
_PRESENCIA_S = 300       # una ubicación de más de 5 min sin renovar se considera vieja


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
    return {"ok": True, "ubicacion_token": ubic, "expira_en": _TTL_UBIC, "ubicacion_habilitada": True}


# ── Compartir / ver / revocar ubicación real (Fase 2 · adultos, voluntario, temporal, sin historial) ──
def _tok_ok(token):
    """Valida el token de ubicación (emitido tras la passkey) y devuelve (matricula_id, course_id)."""
    p = auth_service.decode_token(token or "")
    if not p or p.get("p") != _P_OK or not p.get("mat") or not p.get("cid"):
        raise conflict("Tu verificación de ubicación venció; vuelve a probar tu passkey.")
    return str(p["mat"]), str(p["cid"])


def _nombre_matricula(db, mat_id):
    m = db.query(AsistenciaMatricula).filter(AsistenciaMatricula.id == _uuid.UUID(str(mat_id))).first()
    return (sil._nombre_amable(m.nombre) if m and m.nombre else None), (m if m else None)


def compartir_ubicacion(db: Session, codigo: str, token: str, lat, lng, accuracy=None,
                        precision="aprox", char=None, estado=None, duracion_min=30, origin_header=None) -> dict:
    """Guarda/actualiza la ÚNICA ubicación activa del alumno (upsert → sin historial). En modo 'aprox'
    reduce la precisión (redondeo + radio de privacidad). Caduca por TTL según la duración elegida."""
    from app.models.pandilla import PandillaUbicacion
    mat_id, cid = _tok_ok(token)
    a = sil.agente_por_codigo(db, codigo)
    if str(_curso_id(a)) != cid:
        raise conflict("La verificación no corresponde a este curso.")
    try:
        lat = float(lat); lng = float(lng)
    except Exception:  # noqa: BLE001
        raise unprocessable("Coordenadas inválidas.")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise unprocessable("Coordenadas fuera de rango.")
    preciso = (str(precision) == "preciso")
    if not preciso:
        lat = round(lat, _APROX_DEC); lng = round(lng, _APROX_DEC)
        acc = _APROX_RADIO_M
    else:
        try:
            acc = float(accuracy) if accuracy is not None else 10.0
        except Exception:  # noqa: BLE001
            acc = 10.0
        acc = max(3.0, min(acc, 80.0))
    try:
        dur = int(duracion_min)
    except Exception:  # noqa: BLE001
        dur = 30
    dur = max(5, min(dur, _MAX_MIN))
    ahora = int(time.time())
    nombre, _m = _nombre_matricula(db, mat_id)
    cid_u, mat_u = _uuid.UUID(cid), _uuid.UUID(mat_id)
    row = db.query(PandillaUbicacion).filter(
        PandillaUbicacion.course_id == cid_u, PandillaUbicacion.matricula_id == mat_u).first()
    if not row:
        row = PandillaUbicacion(course_id=cid_u, matricula_id=mat_u)
        db.add(row)
    row.lat = lat; row.lng = lng; row.accuracy_m = acc
    row.precision = "preciso" if preciso else "aprox"
    row.char = (str(char)[:24] if char else row.char)
    row.alias = nombre or row.alias
    row.estado = (str(estado)[:20] if estado else None)
    row.capturado_ts = ahora
    row.expires_ts = ahora + dur * 60
    db.commit()
    return {"ok": True, "expira_ts": row.expires_ts, "precision": row.precision}


def ubicaciones_grupo(db: Session, codigo: str, token: str) -> dict:
    """Ubicaciones ACTIVAS (no caducadas) del MISMO curso de quien está verificado. Purga las vencidas."""
    from app.models.pandilla import PandillaUbicacion
    mat_id, cid = _tok_ok(token)
    a = sil.agente_por_codigo(db, codigo)
    if str(_curso_id(a)) != cid:
        raise conflict("La verificación no corresponde a este curso.")
    ahora = int(time.time())
    cid_u = _uuid.UUID(cid)
    # purga oportunista de las caducadas (sin historial)
    db.query(PandillaUbicacion).filter(
        PandillaUbicacion.course_id == cid_u, PandillaUbicacion.expires_ts < ahora).delete()
    db.commit()
    filas = db.query(PandillaUbicacion).filter(
        PandillaUbicacion.course_id == cid_u, PandillaUbicacion.expires_ts >= ahora).all()
    out = []
    for r in filas:
        out.append({
            "yo": str(r.matricula_id) == mat_id,
            "char": r.char, "alias": r.alias, "estado": r.estado,
            "lat": r.lat, "lng": r.lng, "accuracy_m": r.accuracy_m, "precision": r.precision,
            "edad_seg": max(0, ahora - int(r.capturado_ts or ahora)),
            "vieja": (ahora - int(r.capturado_ts or ahora)) > _PRESENCIA_S,
        })
    return {"ok": True, "ubicaciones": out, "servidor_ts": ahora}


def dejar_ubicacion(db: Session, codigo: str, token: str) -> dict:
    """Revocación inmediata: elimina la ubicación activa del alumno."""
    from app.models.pandilla import PandillaUbicacion
    mat_id, cid = _tok_ok(token)
    db.query(PandillaUbicacion).filter(
        PandillaUbicacion.course_id == _uuid.UUID(cid),
        PandillaUbicacion.matricula_id == _uuid.UUID(mat_id)).delete()
    db.commit()
    return {"ok": True}
