"""
Router de asistencia por curso (QR dinámico + passkeys).

Gestión (profesor / investigador / director):
  POST /asistencia/{course_id}/nomina        -> importa nómina (xlsx multipart o JSON {filas})
  GET  /asistencia/{course_id}/nomina         -> lista la nómina + estado de enrolamiento
  POST /asistencia/matricula/{id}/validar     -> validación presencial de identidad
  POST /asistencia/{course_id}/sesiones       -> abre una sesión (fecha/hora de la lista)
  POST /asistencia/sesion/{codigo}/cerrar
  GET  /asistencia/sesion/{codigo}/qr          -> desafío firmado vigente (rota 4 s)
  GET  /asistencia/sesion/{codigo}/estado      -> panel: nómina, presentes, anomalías
  POST /asistencia/sesion/{codigo}/override    -> el docente fija presente/ausente manual

Alumno (público; la aserción passkey se valida en AS3):
  POST /asistencia/sesion/{codigo}/marcar      -> registra la marca sobre el desafío del QR
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile, File
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_lectura_datos, usuario_actual
from app.services import asistencia_service as asis
from app.services import asistencia_webauthn as awa
from app.models.asistencia import AsistenciaMatricula

router = APIRouter(tags=["asistencia"])


# ── gestión (P / I / D) ───────────────────────────────────────────────────────────────
@router.post("/asistencia/{course_id}/nomina", dependencies=[Depends(req_lectura_datos)])
async def importar_nomina(course_id: UUID, request: Request,
                          archivo: UploadFile | None = File(default=None),
                          db: Session = Depends(get_db)):
    if archivo is not None:
        filas = asis.parse_nomina_xlsx(await archivo.read())
    else:
        body = await request.json()
        filas = (body or {}).get("filas", [])
    return asis.importar_nomina(db, course_id, filas)


@router.get("/asistencia/{course_id}/nomina", dependencies=[Depends(req_lectura_datos)])
def listar_nomina(course_id: UUID, db: Session = Depends(get_db)):
    return {"matriculas": asis.listar_nomina(db, course_id)}


@router.post("/asistencia/matricula/{matricula_id}/validar", dependencies=[Depends(req_lectura_datos)])
def validar(matricula_id: UUID, db: Session = Depends(get_db)):
    return asis.validar_presencial(db, matricula_id)


@router.post("/asistencia/{course_id}/sesiones", dependencies=[Depends(req_lectura_datos)])
def abrir_sesion(course_id: UUID, payload: dict, db: Session = Depends(get_db),
                 usuario=Depends(usuario_actual)):
    s = asis.abrir_sesion(db, course_id, getattr(usuario, "id", "docente"),
                          payload.get("titulo"), payload.get("fecha"),
                          payload.get("inicio"), payload.get("fin"))
    return {"codigo": s.codigo, "titulo": s.titulo, "fecha": s.fecha, "estado": s.estado}


@router.post("/asistencia/sesion/{codigo}/cerrar", dependencies=[Depends(req_lectura_datos)])
def cerrar_sesion(codigo: str, db: Session = Depends(get_db)):
    return asis.cerrar_sesion(db, codigo)


@router.get("/asistencia/sesion/{codigo}/qr", dependencies=[Depends(req_lectura_datos)])
def qr(codigo: str, db: Session = Depends(get_db)):
    return asis.qr_actual(db, codigo)


@router.get("/asistencia/sesion/{codigo}/estado", dependencies=[Depends(req_lectura_datos)])
def estado(codigo: str, db: Session = Depends(get_db)):
    return asis.estado_sesion(db, codigo)


@router.post("/asistencia/sesion/{codigo}/override", dependencies=[Depends(req_lectura_datos)])
def override(codigo: str, payload: dict, db: Session = Depends(get_db)):
    return asis.override_marca(db, codigo, payload.get("matricula_id"), payload.get("estado"))


# ── enrolamiento del alumno (WebAuthn, público por invite_token) ──────────────────────
@router.get("/asistencia/enrolar/{invite_token}")
def enrolar_info(invite_token: str, db: Session = Depends(get_db)):
    m = db.query(AsistenciaMatricula).filter(AsistenciaMatricula.invite_token == invite_token).first()
    if not m:
        from app.core.errors import not_found
        raise not_found("Invitación no válida.")
    return {"nombre": m.nombre, "correo": m.correo, "estado": m.estado,
            "tiene_passkey": any(d.activo for d in m.dispositivos)}


@router.post("/asistencia/enrolar/opciones")
def enrolar_opciones(payload: dict, request: Request, db: Session = Depends(get_db)):
    return awa.opciones_registro(db, payload.get("invite_token"), request.headers.get("origin"))


@router.post("/asistencia/enrolar/verificar")
def enrolar_verificar(payload: dict, request: Request, db: Session = Depends(get_db)):
    return awa.verificar_registro(db, payload.get("invite_token"), payload.get("credential"),
                                  request.headers.get("origin"))


@router.post("/asistencia/matricula/{matricula_id}/revocar-passkey", dependencies=[Depends(req_lectura_datos)])
def revocar_passkey(matricula_id: UUID, db: Session = Depends(get_db)):
    return awa.revocar_dispositivos(db, matricula_id)


# ── informe / export (docente) ────────────────────────────────────────────────────────
@router.post("/asistencia/sesion/{codigo}/informe/{formato}", dependencies=[Depends(req_lectura_datos)])
def informe(codigo: str, formato: str, db: Session = Depends(get_db)):
    if formato not in ("docx", "pdf", "xlsx"):
        from app.core.errors import unprocessable
        raise unprocessable("Formato no soportado (docx | pdf | xlsx).")
    from fastapi import Response
    import re
    from app.services import exportador_service
    data, media = exportador_service.exportar(formato, asis.informe_payload(db, codigo, formato))
    fn = re.sub(r"[^A-Za-z0-9_\-]", "_", f"asistencia_{codigo}")[:80]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fn}.{formato}"'})


# ── alumno (público) ──────────────────────────────────────────────────────────────────
@router.post("/asistencia/sesion/{codigo}/passkey/opciones")
def passkey_opciones(codigo: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    return awa.opciones_login(db, codigo, payload.get("token"), payload.get("bucket"),
                              request.headers.get("origin"))


@router.post("/asistencia/sesion/{codigo}/passkey/marcar")
def passkey_marcar(codigo: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None
    return awa.marcar_con_passkey(db, codigo, payload.get("bucket"), payload.get("credential"),
                                  request.headers.get("origin"), ip=ip,
                                  ua=request.headers.get("user-agent"))


@router.post("/asistencia/sesion/{codigo}/marcar")
def marcar(codigo: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    """Fallback SIN passkey (seguridad menor): solo desafío del QR + matrícula."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return asis.registrar_marca(db, codigo, payload.get("matricula_id"), payload.get("token"),
                                payload.get("bucket"), ip=ip, ua=ua,
                                metodo=payload.get("metodo", "qr"))
