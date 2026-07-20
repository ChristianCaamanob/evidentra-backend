from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.models.teacher import Teacher
import os

SECRET_KEY = os.getenv("SECRET_KEY", "evalys-secret-2026-uss")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_token(data):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(days=7)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def usuario_desde_token(db, token: str):
    """Devuelve el Teacher del JWT (o None). El rol se relee de la BD, no del token,
    para que un cambio de rol tenga efecto inmediato."""
    import uuid as _uuid
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        return None
    try:
        uid = _uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        return None
    return db.query(Teacher).filter(Teacher.id == uid).first()

def _token_payload(teacher):
    return {"sub": str(teacher.id), "email": teacher.email, "rol": teacher.rol}

def get_teacher_by_email(db, email):
    return db.query(Teacher).filter(Teacher.email == email.lower()).first()

def _teacher_dict(teacher):
    return {"id": str(teacher.id), "email": teacher.email, "name": teacher.name,
            "rol": teacher.rol, "email_verificado": bool(getattr(teacher, "email_verificado", True))}

def _verify_email_token(teacher):
    from datetime import datetime as _dt, timedelta as _td
    return jwt.encode({"sub": str(teacher.id), "p": "verify_email",
                       "exp": _dt.utcnow() + _td(days=2)}, SECRET_KEY, algorithm=ALGORITHM)

def enviar_verificacion(db, teacher) -> bool:
    """Envía (o reenvía) el correo de verificación. Devuelve True si se envió."""
    from app.services.email_service import send_verification_email
    try:
        send_verification_email(teacher.email, _verify_email_token(teacher), teacher.name)
        print(f"[VERIFY OK] enviado a {teacher.email}", flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[VERIFY ERROR] {teacher.email}: {e}", flush=True)
        return False

def verificar_email(db, token: str):
    payload = decode_token(token or "")
    if not payload or payload.get("p") != "verify_email" or not payload.get("sub"):
        return {"error": "Enlace de verificación inválido o expirado"}
    import uuid as _uuid
    try:
        uid = _uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        return {"error": "Enlace inválido"}
    teacher = db.query(Teacher).filter(Teacher.id == uid).first()
    if not teacher:
        return {"error": "Cuenta no encontrada"}
    teacher.email_verificado = True
    db.commit()
    return {"ok": True, "email": teacher.email}

def reenviar_verificacion(db, email: str):
    teacher = get_teacher_by_email(db, (email or "").lower().strip())
    if teacher and not getattr(teacher, "email_verificado", True):
        enviar_verificacion(db, teacher)
    return {"ok": True}   # no revela si el correo existe

def register_teacher(db, email, password, name):
    email = email.lower().strip()
    if get_teacher_by_email(db, email):
        return {"error": "Este correo ya está registrado"}
    # El auto-registro SIEMPRE crea 'profesor'. Elevar a investigador/director/creador es
    # una accion del creador (no se puede autoasignar un rol privilegiado).
    # Cuenta NUEVA nace SIN verificar: debe confirmar el enlace del correo antes de ingresar.
    teacher = Teacher(email=email, hashed_password=hash_password(password), name=name,
                      email_verificado=False)
    db.add(teacher); db.commit(); db.refresh(teacher)
    enviado = enviar_verificacion(db, teacher)
    return {"pendiente_verificacion": True, "email": teacher.email, "correo_enviado": enviado}

def login_teacher(db, email, password):
    teacher = get_teacher_by_email(db, email)
    if not teacher: return {"error": "Correo no registrado"}
    if not verify_password(password, teacher.hashed_password): return {"error": "Contraseña incorrecta"}
    if not getattr(teacher, "email_verificado", True):
        return {"error": "Verifica tu correo antes de ingresar. Te enviamos un enlace.",
                "email_no_verificado": True, "email": teacher.email}
    return {"token": create_token(_token_payload(teacher)), "teacher": _teacher_dict(teacher)}

import secrets
from app.models.password_reset import PasswordResetToken
from app.services.email_service import send_reset_email

def create_reset_token(db, email: str):
    import logging
    logger = logging.getLogger(__name__)
    teacher = get_teacher_by_email(db, email)
    if not teacher:
        logger.warning(f"forgot-password: email no encontrado {email}")
        return {"ok": True}
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=15)
    db.add(PasswordResetToken(teacher_id=str(teacher.id), token=token, expires_at=expires))
    db.commit()
    try:
        send_reset_email(teacher.email, token, teacher.name)
        print(f"[SMTP OK] email enviado a {teacher.email}", flush=True)
    except Exception as e:
        print(f"[SMTP ERROR] {teacher.email}: {e}", flush=True)
    return {"ok": True}

def cambiar_password(db, teacher, actual: str, nueva: str):
    """Cambio de contraseña del usuario AUTENTICADO (verifica la actual)."""
    if not verify_password(actual or "", teacher.hashed_password):
        return {"error": "La contraseña actual no es correcta"}
    if len(nueva or "") < 6:
        return {"error": "La nueva contraseña debe tener al menos 6 caracteres"}
    teacher.hashed_password = hash_password(nueva)
    db.commit()
    return {"ok": True}

def perfil(teacher):
    return {"id": str(teacher.id), "email": teacher.email, "name": teacher.name,
            "rol": teacher.rol, "email_verificado": bool(getattr(teacher, "email_verificado", True)),
            "institution": getattr(teacher, "institution", None),
            "created_at": teacher.created_at.isoformat() if getattr(teacher, "created_at", None) else None}

def reset_password(db, token: str, new_password: str):
    record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    if not record:
        return {"error": "Token inválido o expirado"}
    teacher = db.query(Teacher).filter(Teacher.id == record.teacher_id).first()
    teacher.hashed_password = hash_password(new_password)
    record.used = True
    db.commit()
    return {"ok": True}
