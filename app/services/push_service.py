"""
Web Push (v2.0) — servicio de notificaciones a la pantalla bloqueada de la PWA.

Llaves VAPID: se generan una sola vez y se guardan en la BD (la privada nunca sale de aquí).
Recordatorios amables de evaluaciones: hitos a 12 semanas / 1 semana / 3 días / mañana / hoy,
idempotentes (una evaluación × alumno × hito se envía una única vez).
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.models.push import PushConfig, PushSubscription, StudentCourseFollow, PushSent, PushNativeToken
from app.models.evaluacion_agenda import EvaluacionAgenda

_log = logging.getLogger("push")

# hito (días antes) → etiqueta amable
_HITOS = {84: "en 12 semanas", 7: "en 1 semana", 3: "en 3 días", 1: "mañana", 0: "hoy"}
_TIPO_LABEL = {"prueba": "Prueba", "certamen": "Certamen", "examen": "Examen",
               "entrega": "Entrega", "taller": "Taller", "control": "Control"}


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _ensure_config(db: Session) -> PushConfig | None:
    cfg = db.query(PushConfig).first()
    if cfg and cfg.vapid_public and cfg.vapid_private:
        return cfg
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        priv = ec.generate_private_key(ec.SECP256R1())
        priv_pem = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        raw_pub = priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        app_key = _b64u(raw_pub)
    except Exception:  # noqa: BLE001
        _log.exception("No se pudieron generar llaves VAPID")
        return None
    if not cfg:
        cfg = PushConfig()
        db.add(cfg)
    cfg.vapid_public = app_key
    cfg.vapid_private = priv_pem
    if not cfg.subject:
        cfg.subject = "mailto:runi@evalys.cl"
    db.commit()
    return cfg


def vapid_public(db: Session) -> dict:
    cfg = _ensure_config(db)
    return {"ok": bool(cfg), "publicKey": cfg.vapid_public if cfg else ""}


def guardar_sub(db: Session, owner_key: str, sub: dict) -> dict:
    s = sub or {}
    endpoint = str(s.get("endpoint") or "").strip()
    keys = s.get("keys") or {}
    if not endpoint:
        return {"ok": False, "error": "sin endpoint"}
    eh = hashlib.sha256(endpoint.encode()).hexdigest()
    row = db.query(PushSubscription).filter(PushSubscription.endpoint_hash == eh).first()
    if not row:
        row = PushSubscription(endpoint=endpoint, endpoint_hash=eh)
        db.add(row)
    row.owner_key = owner_key
    row.p256dh = str(keys.get("p256dh") or "")
    row.auth = str(keys.get("auth") or "")
    db.commit()
    return {"ok": True}


def guardar_native(db: Session, owner_key: str, platform: str, token: str) -> dict:
    """Registra el token de push nativo (Capacitor/APNs/FCM) del alumno. Idempotente por token.
    El ENVÍO nativo se activa cuando existan credenciales APNs/FCM en env; por ahora solo se conserva."""
    token = str(token or "").strip()
    if not token:
        return {"ok": False, "error": "sin token"}
    platform = str(platform or "").strip().lower()[:12]
    row = db.query(PushNativeToken).filter(PushNativeToken.token == token).first()
    if not row:
        row = PushNativeToken(token=token)
        db.add(row)
    row.owner_key = owner_key
    row.platform = platform
    db.commit()
    return {"ok": True}


def seguir_curso(db: Session, owner_key: str, course_id, silabo_code: str = "") -> dict:
    if not course_id:
        return {"ok": False}
    existe = db.query(StudentCourseFollow).filter(
        StudentCourseFollow.owner_key == owner_key,
        StudentCourseFollow.course_id == course_id).first()
    if not existe:
        db.add(StudentCourseFollow(owner_key=owner_key, course_id=course_id,
                                   silabo_code=(silabo_code or None)))
        db.commit()
    elif silabo_code and existe.silabo_code != silabo_code:
        existe.silabo_code = silabo_code
        db.commit()
    return {"ok": True}


def _enviar_a_sub(cfg: PushConfig, row: PushSubscription, payload: dict) -> str:
    """Devuelve 'ok' | 'gone' | 'err'."""
    try:
        from pywebpush import webpush, WebPushException
        from py_vapid import Vapid01
    except Exception:  # noqa: BLE001
        return "err"
    sub_info = {"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}}
    try:
        vp = Vapid01.from_pem(cfg.vapid_private.encode())
        webpush(subscription_info=sub_info, data=json.dumps(payload),
                vapid_private_key=vp, vapid_claims={"sub": cfg.subject},
                ttl=60 * 60 * 24)
        return "ok"
    except WebPushException as e:  # noqa: PERF203
        code = getattr(getattr(e, "response", None), "status_code", 0)
        return "gone" if code in (404, 410) else "err"
    except Exception:  # noqa: BLE001
        return "err"


def enviar_a_owner(db: Session, owner_key: str, payload: dict) -> int:
    cfg = _ensure_config(db)
    if not cfg:
        return 0
    subs = db.query(PushSubscription).filter(PushSubscription.owner_key == owner_key).all()
    enviados = 0
    for row in subs:
        r = _enviar_a_sub(cfg, row, payload)
        if r == "ok":
            enviados += 1
        elif r == "gone":
            db.delete(row)
    db.commit()
    return enviados


def enviar_a_curso(db: Session, course_id, payload: dict) -> int:
    """Envía la notificación a TODOS los estudiantes suscritos que siguen el curso (tiempo real)."""
    cfg = _ensure_config(db)
    if not cfg:
        return 0
    seguidores = db.query(StudentCourseFollow).filter(
        StudentCourseFollow.course_id == str(course_id)).all()
    enviados = 0
    for f in seguidores:
        subs = db.query(PushSubscription).filter(PushSubscription.owner_key == f.owner_key).all()
        for row in subs:
            r = _enviar_a_sub(cfg, row, payload)
            if r == "ok":
                enviados += 1
            elif r == "gone":
                db.delete(row)
    db.commit()
    return enviados


def _payload_eval(e: EvaluacionAgenda, dias: int) -> dict:
    tipo = _TIPO_LABEL.get((e.tipo or "").lower(), (e.tipo or "Evaluación").capitalize())
    cuando = _HITOS.get(dias, f"en {dias} días")
    if dias == 0:
        cuerpo = f"Hoy es tu {tipo.lower()}: {e.titulo}. ¡Tú puedes! 🦊"
    elif dias == 1:
        cuerpo = f"Mañana: {tipo.lower()} «{e.titulo}». Repasa con calma, vas bien."
    else:
        cuerpo = f"{tipo} «{e.titulo}» {cuando}. Empecemos a prepararnos sin apuro 🦊"
    if e.ponderacion:
        cuerpo += f" ({e.ponderacion})"
    return {"title": "Runi · recordatorio amable", "body": cuerpo,
            "tag": f"eval-{e.id}-{dias}", "url": "/?agenda=1",
            "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}


def tick(db: Session) -> dict:
    """Barrido idempotente: envía los recordatorios que corresponden hoy. Seguro de llamar muchas veces."""
    cfg = _ensure_config(db)
    if not cfg:
        return {"ok": False, "error": "sin config"}
    hoy = _dt.date.today()
    evals = db.query(EvaluacionAgenda).all()
    enviados = 0
    for e in evals:
        try:
            fecha = _dt.date.fromisoformat((e.fecha or "")[:10])
        except (ValueError, TypeError):
            continue
        dias = (fecha - hoy).days
        if dias not in _HITOS:
            continue
        seguidores = db.query(StudentCourseFollow).filter(
            StudentCourseFollow.course_id == e.course_id).all()
        for f in seguidores:
            ya = db.query(PushSent).filter(
                PushSent.eval_id == str(e.id), PushSent.owner_key == f.owner_key,
                PushSent.hito == str(dias)).first()
            if ya:
                continue
            n = enviar_a_owner(db, f.owner_key, _payload_eval(e, dias))
            db.add(PushSent(eval_id=str(e.id), owner_key=f.owner_key, hito=str(dias)))
            db.commit()
            enviados += n
    # Comunicados recurrentes del docente ("recuerden traer el delantal cada práctico").
    recurrentes = {}
    try:
        from app.services import anuncio_service as _an
        recurrentes = _an.tick(db)
    except Exception:  # noqa: BLE001 — aditivo: nunca puede tumbar los recordatorios de evaluación
        recurrentes = {}

    # Alarmas de recordatorios personales del alumno (fecha/hora que él mismo puso).
    personales = 0
    try:
        from app.services import recordatorio_service as rs
        personales = rs.tick(db)
    except Exception:  # noqa: BLE001
        _log.exception("tick recordatorios personales")
    # B4 · repasos diferidos vencidos (comprobación espaciada del Episodio de Aprendizaje).
    repasos = 0
    try:
        from app.services import episode_service as eps
        repasos = eps.tick_repasos(db)
    except Exception:  # noqa: BLE001
        _log.exception("tick repasos diferidos")
    return {"ok": True, "enviados": enviados, "personales": personales, "repasos": repasos,
            "comunicados": (recurrentes or {}).get("recurrentes_reenviados", 0)}
