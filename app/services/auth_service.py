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

def register_teacher(db, email, password, name):
    email = email.lower().strip()
    if get_teacher_by_email(db, email):
        return {"error": "Este correo ya está registrado"}
    # El auto-registro SIEMPRE crea 'profesor'. Elevar a investigador/director/creador es
    # una accion del creador (no se puede autoasignar un rol privilegiado).
    teacher = Teacher(email=email, hashed_password=hash_password(password), name=name)
    db.add(teacher); db.commit(); db.refresh(teacher)
    return {"token": create_token(_token_payload(teacher)),
            "teacher": {"id": str(teacher.id), "email": teacher.email, "name": teacher.name,
                        "rol": teacher.rol}}

def login_teacher(db, email, password):
    teacher = get_teacher_by_email(db, email)
    if not teacher: return {"error": "Correo no registrado"}
    if not verify_password(password, teacher.hashed_password): return {"error": "Contraseña incorrecta"}
    return {"token": create_token(_token_payload(teacher)),
            "teacher": {"id": str(teacher.id), "email": teacher.email, "name": teacher.name,
                        "rol": teacher.rol}}

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
