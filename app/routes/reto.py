"""
El Reto de Runi — rutas.

Docente (`req_profesor`): genera el banco, lo revisa y lo aprueba. **Ninguna pregunta llega a una
estudiante sin pasar por aquí**: en anatomía aplicada una pregunta mal generada le enseña algo falso
a quien la responde.

Alumno (seudonimizado, sin login): pide su sesión de 2–3 preguntas y responde.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.errors import unprocessable
from app.core.ratelimit import limit
from app.services import reto_service as rt
from app.services import silabo_service as sil

router = APIRouter(tags=["reto"])


@router.post("/courses/{course_id}/reto/generar", dependencies=[Depends(req_profesor)])
@limit("6/minute")
def reto_generar(course_id: UUID, request: Request, payload: dict, db: Session = Depends(get_db)):
    """Propone preguntas sobre el material del curso. Quedan SIN publicar hasta que se aprueben."""
    p = payload or {}
    a = sil.agente_de_curso(db, course_id)
    if not a:
        raise unprocessable("Este curso todavía no tiene agente de Runi con material cargado.")
    return rt.generar(db, course_id, p.get("temas", ""), a.contexto or "",
                      curso=(a.nombre_curso or ""), eval_id=p.get("eval_id"),
                      n_por_tema=p.get("n_por_tema", 3))


@router.get("/courses/{course_id}/reto", dependencies=[Depends(req_profesor)])
def reto_listar(course_id: UUID, estado: str = "", db: Session = Depends(get_db)):
    return rt.listar_docente(db, course_id, estado)


@router.post("/reto/{pregunta_id}/revisar", dependencies=[Depends(req_profesor)])
def reto_revisar(pregunta_id: UUID, payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rt.revisar(db, pregunta_id, str(p.get("accion") or "editar"), p.get("cambios"))


@router.post("/courses/{course_id}/reto/manual", dependencies=[Depends(req_profesor)])
def reto_manual(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return rt.crear_manual(db, course_id, payload or {}, (payload or {}).get("eval_id"))


@router.post("/courses/{course_id}/reto/justificar", dependencies=[Depends(req_profesor)])
@limit("4/minute")
def reto_justificar(course_id: UUID, request: Request, payload: dict, db: Session = Depends(get_db)):
    """Runi redacta los porqués que faltan. Quedan como BORRADOR: no los ve ninguna estudiante."""
    a = sil.agente_de_curso(db, course_id)
    if not a:
        raise unprocessable("Este curso todavía no tiene agente de Runi con material cargado.")
    return rt.justificar(db, course_id, a.contexto or "", curso=(a.nombre_curso or ""),
                         rehacer=bool((payload or {}).get("rehacer")))


@router.post("/reto/{pregunta_id}/justificacion", dependencies=[Depends(req_profesor)])
def reto_usar_justificacion(pregunta_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Aceptar (o corregir) el borrador. Recién aquí lo ve la estudiante."""
    p = payload or {}
    if p.get("descartar"):
        return rt.descartar_justificacion(db, pregunta_id)
    return rt.usar_justificacion(db, pregunta_id, p.get("texto"))


@router.post("/courses/{course_id}/reto/justificaciones/usar-todas", dependencies=[Depends(req_profesor)])
def reto_usar_todas_justificaciones(course_id: UUID, db: Session = Depends(get_db)):
    return rt.usar_todas_las_justificaciones(db, course_id)


@router.post("/courses/{course_id}/reto/publicar-todas", dependencies=[Depends(req_profesor)])
def reto_publicar_todas(course_id: UUID, db: Session = Depends(get_db)):
    """Publica el lote por revisar. Lo que no convenza se descarta antes, una por una."""
    return rt.aprobar_todas(db, course_id)


@router.post("/courses/{course_id}/reto/vaciar", dependencies=[Depends(req_profesor)])
def reto_vaciar(course_id: UUID, payload: dict, db: Session = Depends(get_db)):
    return rt.vaciar(db, course_id, str((payload or {}).get("estado") or "descartada"))


@router.post("/courses/{course_id}/reto/importar", dependencies=[Depends(req_profesor)])
@limit("6/minute")
def reto_importar(course_id: UUID, request: Request, payload: dict, db: Session = Depends(get_db)):
    """Importa la pauta del docente (.docx) con la correcta resaltada. Entran APROBADAS: las escribió él."""
    p = payload or {}
    return rt.importar_docx(db, course_id, p.get("archivo_datos", ""),
                            str(p.get("tema") or "General"), p.get("eval_id"))


@router.delete("/reto/{pregunta_id}", dependencies=[Depends(req_profesor)])
def reto_eliminar(pregunta_id: UUID, db: Session = Depends(get_db)):
    return rt.eliminar(db, pregunta_id)


# ── alumno ───────────────────────────────────────────────────────────────────────────
def _curso_de(db: Session, codigo: str):
    return sil.agente_por_codigo(db, codigo).course_id


@router.get("/silabo/{codigo}/reto")
def reto_sesion(codigo: str, pseudo_id: str = "", n: int = rt.POR_SESION,
                db: Session = Depends(get_db)):
    return rt.sesion(db, _curso_de(db, codigo), pseudo_id, n)


@router.get("/silabo/{codigo}/reto/estado")
def reto_mi_estado(codigo: str, pseudo_id: str = "", db: Session = Depends(get_db)):
    return rt.mi_estado(db, _curso_de(db, codigo), pseudo_id)


@router.post("/silabo/{codigo}/reto/{pregunta_id}")
@limit("60/minute")
def reto_responder(codigo: str, pregunta_id: UUID, request: Request, payload: dict,
                   db: Session = Depends(get_db)):
    p = payload or {}
    return rt.responder(db, pregunta_id, str(p.get("pseudo_id") or ""),
                        p.get("elegida", ""), _curso_de(db, codigo))
