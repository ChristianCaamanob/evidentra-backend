"""
Anuncios del docente — crear (+ push en tiempo real a los suscritos del curso) y listar (bandeja).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import unprocessable, not_found
from app.models.anuncio import Anuncio
from app.services import push_service, silabo_service


def _dict(a: Anuncio) -> dict:
    return {"id": str(a.id), "titulo": a.titulo, "cuerpo": a.cuerpo, "autor": a.autor,
            "created_at": a.created_at.isoformat() if a.created_at else None}


def crear(db: Session, course_id, payload: dict, autor: str = "") -> dict:
    p = payload or {}
    titulo = str(p.get("titulo") or "").strip()[:140]
    cuerpo = str(p.get("cuerpo") or "").strip()[:1000]
    if not titulo and not cuerpo:
        raise unprocessable("El anuncio necesita al menos un título o un mensaje.")
    a = Anuncio(course_id=str(course_id), titulo=titulo or "Anuncio del curso",
                cuerpo=cuerpo, autor=(str(autor or "").strip()[:120] or None))
    db.add(a); db.commit()
    # Push en tiempo real a la pantalla bloqueada de los estudiantes suscritos al curso.
    enviados = 0
    try:
        payload_push = {"title": "📣 " + (a.titulo or "Anuncio del curso"),
                        "body": (a.cuerpo or "")[:180] or a.titulo,
                        "tag": f"anuncio-{a.id}", "url": "/?avisos=1",
                        "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}
        enviados = push_service.enviar_a_curso(db, course_id, payload_push)
    except Exception:
        enviados = 0
    return {"ok": True, "anuncio": _dict(a), "enviados": enviados}


def listar_por_course(db: Session, course_id, limite: int = 30) -> dict:
    filas = (db.query(Anuncio).filter(Anuncio.course_id == str(course_id))
             .order_by(Anuncio.created_at.desc()).limit(min(int(limite or 30), 100)).all())
    return {"ok": True, "anuncios": [_dict(a) for a in filas]}


def listar_por_codigo(db: Session, codigo: str, limite: int = 30) -> dict:
    try:
        a = silabo_service.agente_por_codigo(db, codigo)
    except Exception:
        return {"ok": True, "anuncios": []}
    return listar_por_course(db, a.course_id, limite)
