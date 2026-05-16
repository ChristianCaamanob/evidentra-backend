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

def get_teacher_by_email(db, email):
    return db.query(Teacher).filter(Teacher.email == email.lower()).first()

def register_teacher(db, email, password, name):
    email = email.lower().strip()
    if get_teacher_by_email(db, email):
        return {"error": "Este correo ya está registrado"}
    teacher = Teacher(email=email, hashed_password=hash_password(password), name=name)
    db.add(teacher); db.commit(); db.refresh(teacher)
    return {"token": create_token({"sub": str(teacher.id), "email": teacher.email}),
            "teacher": {"id": str(teacher.id), "email": teacher.email, "name": teacher.name}}

def login_teacher(db, email, password):
    teacher = get_teacher_by_email(db, email)
    if not teacher: return {"error": "Correo no registrado"}
    if not verify_password(password, teacher.hashed_password): return {"error": "Contraseña incorrecta"}
    return {"token": create_token({"sub": str(teacher.id), "email": teacher.email}),
            "teacher": {"id": str(teacher.id), "email": teacher.email, "name": teacher.name}}
