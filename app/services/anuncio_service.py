"""
Anuncios del docente — crear (+ push en tiempo real a los suscritos del curso) y listar (bandeja).
"""
from __future__ import annotations

import base64
import re

from sqlalchemy.orm import Session

from app.core.errors import unprocessable, not_found
from app.models.anuncio import Anuncio
from app.services import push_service, silabo_service


_MAX_BYTES = 6 * 1024 * 1024      # el aviso viaja también como push: se acota el adjunto


def _dict(a: Anuncio) -> dict:
    """El archivo NUNCA viaja en el listado: solo su ficha y el enlace para descargarlo.

    Devolver el base64 en cada anuncio inflaría la bandeja del alumno a megas por nada.
    """
    tiene = bool(getattr(a, "archivo_datos", None))
    return {"id": str(a.id), "titulo": a.titulo, "cuerpo": a.cuerpo, "autor": a.autor,
            "url": getattr(a, "url", None),
            "archivo_nombre": getattr(a, "archivo_nombre", None) if tiene else None,
            "archivo_mime": getattr(a, "archivo_mime", None) if tiene else None,
            "tamano": int(getattr(a, "tamano", 0) or 0) if tiene else 0,
            "archivo_url": (f"/api/v1/anuncios/{a.id}/archivo" if tiene else None),
            "created_at": a.created_at.isoformat() if a.created_at else None}


def crear(db: Session, course_id, payload: dict, autor: str = "") -> dict:
    p = payload or {}
    titulo = str(p.get("titulo") or "").strip()[:140]
    cuerpo = str(p.get("cuerpo") or "").strip()[:1000]
    if not titulo and not cuerpo:
        raise unprocessable("El anuncio necesita al menos un título o un mensaje.")
    url = str(p.get("url") or "").strip()[:2000] or None
    b64 = p.get("archivo_datos")
    nombre = str(p.get("archivo_nombre") or "").strip()[:200] or None
    mime = str(p.get("archivo_mime") or "").strip()[:100] or None
    datos, tamano = None, 0
    if b64:
        crudo = re.sub(r"^data:[^;]+;base64,", "", str(b64))
        try:
            tamano = len(base64.b64decode(crudo, validate=False))
        except Exception:  # noqa: BLE001
            tamano = int(len(crudo) * 0.75)
        if tamano > _MAX_BYTES:
            raise unprocessable("El archivo supera 6 MB. Comparte un enlace (Drive/web) en su lugar.")
        datos = crudo

    a = Anuncio(course_id=str(course_id), titulo=titulo or "Anuncio del curso",
                cuerpo=cuerpo, autor=(str(autor or "").strip()[:120] or None),
                url=url, archivo_nombre=nombre, archivo_mime=mime,
                archivo_datos=datos, tamano=tamano)
    db.add(a); db.commit()
    # Push en tiempo real a la pantalla bloqueada de los estudiantes suscritos al curso.
    enviados = 0
    try:
        payload_push = {"title": "📣 " + (a.titulo or "Anuncio del curso"),
                        "body": ((a.cuerpo or "")[:380] or a.titulo) + (" 📎" if (datos or url) else ""),
                        "tag": f"anuncio-{a.id}", "url": "/?avisos=1",
                        "requireInteraction": True, "vibrate": [120, 60, 120, 60, 200],
                        "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}
        enviados = push_service.enviar_a_curso(db, course_id, payload_push)
    except Exception:
        enviados = 0
    return {"ok": True, "anuncio": _dict(a), "enviados": enviados}


def archivo(db: Session, anuncio_id):
    """(bytes, mime, nombre) del adjunto, o None."""
    a = db.query(Anuncio).filter(Anuncio.id == anuncio_id).first()
    if not a or not getattr(a, "archivo_datos", None):
        return None
    try:
        data = base64.b64decode(a.archivo_datos, validate=False)
    except Exception:  # noqa: BLE001
        return None
    return data, (a.archivo_mime or "application/octet-stream"), (a.archivo_nombre or "adjunto")


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
