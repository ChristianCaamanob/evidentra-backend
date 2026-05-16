from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_db
from app.services.auth_service import register_teacher, login_teacher

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterIn(BaseModel):
    email: str
    password: str
    name: str

class LoginIn(BaseModel):
    email: str
    password: str

@router.post("/register")
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña debe tener al menos 6 caracteres")
    result = register_teacher(db, payload.email, payload.password, payload.name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    result = login_teacher(db, payload.email, payload.password)
    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])
    return result
