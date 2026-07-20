from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.api.deps import get_db, usuario_actual
from app.core.ratelimit import limit
from app.services.auth_service import register_teacher, login_teacher

router = APIRouter(prefix="/auth", tags=["auth"])


def _origin(request: Request) -> str | None:
    return request.headers.get("origin") or request.headers.get("Origin")

class RegisterIn(BaseModel):
    email: str
    password: str
    name: str

class LoginIn(BaseModel):
    email: str
    password: str

@router.post("/register")
@limit("4/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)):
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña debe tener al menos 6 caracteres")
    result = register_teacher(db, payload.email, payload.password, payload.name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/login")
@limit("8/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)):
    result = login_teacher(db, payload.email, payload.password)
    if result.get("email_no_verificado"):
        # No es un error de credenciales: el frontend muestra "verifica tu correo" + reenviar.
        return {"email_no_verificado": True, "email": result.get("email"), "detail": result["error"]}
    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])
    return result


from app.services.auth_service import verificar_email as _verificar_email, reenviar_verificacion as _reenviar_verif

class VerifyIn(BaseModel):
    token: str

class ResendVerifyIn(BaseModel):
    email: str

@router.post("/verify-email")
@limit("10/minute")
def verify_email(request: Request, payload: VerifyIn, db: Session = Depends(get_db)):
    result = _verificar_email(db, payload.token)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/resend-verification")
@limit("4/minute")
def resend_verification(request: Request, payload: ResendVerifyIn, db: Session = Depends(get_db)):
    return _reenviar_verif(db, payload.email)

from app.services.auth_service import create_reset_token, reset_password

class ForgotIn(BaseModel):
    email: str

class ResetIn(BaseModel):
    token: str
    password: str

@router.post("/forgot-password")
@limit("4/minute")
def forgot_password(request: Request, payload: ForgotIn, db: Session = Depends(get_db)):
    return create_reset_token(db, payload.email.lower().strip())

@router.post("/reset-password")
@limit("6/minute")
def reset_pwd(request: Request, payload: ResetIn, db: Session = Depends(get_db)):
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña debe tener al menos 6 caracteres")
    result = reset_password(db, payload.token, payload.password)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Passkeys (WebAuthn) del staff: entrar con huella / rostro ──────────────────────────
from app.services import teacher_webauthn as _twa   # noqa: E402


@router.post("/passkey/register/options")
def passkey_reg_options(request: Request, db: Session = Depends(get_db),
                        teacher=Depends(usuario_actual)):
    return _twa.opciones_registro(db, teacher, _origin(request))


@router.post("/passkey/register/verify")
def passkey_reg_verify(request: Request, payload: dict, db: Session = Depends(get_db),
                       teacher=Depends(usuario_actual)):
    return _twa.verificar_registro(db, teacher, payload.get("credential"),
                                   payload.get("challenge_token"), _origin(request),
                                   label=payload.get("label"))


@router.post("/passkey/login/options")
@limit("20/minute")
def passkey_login_options(request: Request, db: Session = Depends(get_db)):
    return _twa.opciones_login(db, _origin(request))


@router.post("/passkey/login/verify")
@limit("12/minute")
def passkey_login_verify(request: Request, payload: dict, db: Session = Depends(get_db)):
    return _twa.verificar_login(db, payload.get("credential"),
                                payload.get("challenge_token"), _origin(request))


@router.get("/passkey/list")
def passkey_list(db: Session = Depends(get_db), teacher=Depends(usuario_actual)):
    return _twa.listar(db, teacher)


@router.delete("/passkey/{passkey_id}")
def passkey_del(passkey_id: str, db: Session = Depends(get_db), teacher=Depends(usuario_actual)):
    return _twa.revocar(db, teacher, passkey_id)
