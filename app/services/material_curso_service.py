"""
Material del curso (v2.0) — CRUD docente + lectura pública por código de agente Runi + servir archivo.
"""
from __future__ import annotations

import base64
import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.material_curso import MaterialCurso

_TIPOS = {"programa", "calendario", "apunte", "libro", "articulo", "enlace", "otro"}
_MAX_BYTES = 9 * 1024 * 1024   # 9 MB por archivo (para más grande, usar enlace)


def _tipo(v) -> str:
    t = str(v or "apunte").strip().lower()
    return t if t in _TIPOS else "otro"


def _dict(m: MaterialCurso, incluir_datos: bool = False) -> dict:
    d = {"id": str(m.id), "titulo": m.titulo, "tipo": m.tipo, "descripcion": m.descripcion,
         "url": m.url, "archivo_nombre": m.archivo_nombre, "archivo_mime": m.archivo_mime,
         "tamano": m.tamano, "tiene_archivo": bool(m.archivo_datos)}
    if incluir_datos:
        d["archivo_datos"] = m.archivo_datos
    return d


def crear(db: Session, course_id, payload: dict) -> dict:
    p = payload or {}
    titulo = str(p.get("titulo") or "").strip()[:200]
    if not titulo:
        raise unprocessable("El material necesita un título.")
    url = str(p.get("url") or "").strip()[:2000] or None
    b64 = p.get("archivo_datos")
    nombre = str(p.get("archivo_nombre") or "").strip()[:200] or None
    mime = str(p.get("archivo_mime") or "").strip()[:100] or None
    tamano = 0
    datos = None
    if b64:
        raw = re.sub(r"^data:[^;]+;base64,", "", str(b64))
        try:
            tamano = len(base64.b64decode(raw, validate=False))
        except Exception:  # noqa: BLE001
            tamano = int(len(raw) * 0.75)
        if tamano > _MAX_BYTES:
            raise unprocessable("El archivo supera 9 MB. Para libros pesados, comparte un enlace (Drive/web).")
        datos = raw
    if not url and not datos:
        raise unprocessable("Agrega un enlace o sube un archivo.")
    m = MaterialCurso(
        course_id=course_id, titulo=titulo, tipo=_tipo(p.get("tipo")),
        descripcion=(str(p.get("descripcion") or "").strip()[:400] or None),
        url=url, archivo_nombre=nombre, archivo_mime=mime, archivo_datos=datos, tamano=tamano)
    db.add(m); db.commit()
    return {"ok": True, "material": _dict(m)}


def listar(db: Session, course_id) -> dict:
    filas = (db.query(MaterialCurso).filter(MaterialCurso.course_id == course_id)
             .order_by(MaterialCurso.orden.asc(), MaterialCurso.created_at.asc()).all())
    return {"ok": True, "materiales": [_dict(m) for m in filas]}


def listar_por_silabo(db: Session, codigo: str) -> dict:
    from app.services import silabo_service as sil
    a = sil.agente_por_codigo(db, codigo)
    try:
        cid = _uuid.UUID(str(a.course_id))
    except Exception:  # noqa: BLE001
        return {"ok": True, "materiales": []}
    return listar(db, cid)


def eliminar(db: Session, material_id) -> dict:
    try:
        mid = _uuid.UUID(str(material_id))
    except (ValueError, TypeError):
        raise not_found("Material no válido.")
    m = db.query(MaterialCurso).filter(MaterialCurso.id == mid).first()
    if not m:
        raise not_found("Material no encontrado.")
    db.delete(m); db.commit()
    return {"ok": True}


def archivo(db: Session, material_id):
    """Devuelve (bytes, mime, nombre) del archivo, o None."""
    try:
        mid = _uuid.UUID(str(material_id))
    except (ValueError, TypeError):
        return None
    m = db.query(MaterialCurso).filter(MaterialCurso.id == mid).first()
    if not m or not m.archivo_datos:
        return None
    try:
        data = base64.b64decode(m.archivo_datos, validate=False)
    except Exception:  # noqa: BLE001
        return None
    return data, (m.archivo_mime or "application/octet-stream"), (m.archivo_nombre or "material")
