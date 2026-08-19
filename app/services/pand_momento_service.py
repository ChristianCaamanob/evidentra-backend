"""
Momentos de la Pandilla — servicio CRUD efímero (24 h) + moderación.

Un momento activo por estudiante (upsert por owner_key). `feed` devuelve el propio momento sólo si
sigue vigente (< 24 h) y no está oculto. `reportar` incrementa reportes y oculta al superar el umbral.
Sin historial: al vencer, borrar o superar reportes, desaparece del feed.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.pand_momento import PandMomento

_TTL = _dt.timedelta(hours=24)
_MAX_B64 = 8 * 1024 * 1024          # ~8 MB de data-URL (media ya reescalada/comprimida en cliente)
_REPORT_HIDE = 3                    # se oculta al alcanzar N reportes
_MAX_POR_ALUMNO = 20               # tope rodante de momentos activos por alumno (Historia)


def _es_media(s: str) -> bool:
    s = s or ""
    return s.startswith("data:image/") or s.startswith("data:video/")


def _vigente(r: PandMomento) -> bool:
    try:
        ca = r.created_at
        if ca is None:
            return True
        if ca.tzinfo is not None:
            ca = ca.replace(tzinfo=None)
        return (_dt.datetime.utcnow() - ca) < _TTL
    except Exception:
        return True


def _dict(r: PandMomento, con_imagen: bool = True) -> dict:
    d = {"id": str(r.id), "char": r.char, "nombre": r.nombre, "caption": r.caption,
         "created_at": r.created_at.isoformat() if r.created_at else None}
    if con_imagen:
        d["imagen"] = r.imagen
    return d


def publicar(db: Session, owner_key: str, curso: str, nombre: str, payload: dict) -> dict:
    """Inserta UN momento nuevo (Historia). owner_key/curso/nombre vienen del TOKEN verificado."""
    p = payload or {}
    img = str(p.get("imagen") or "").strip()
    if not _es_media(img):
        raise unprocessable("Necesito una foto o un video válido para tu momento.")
    if len(img) > _MAX_B64:
        raise unprocessable("El archivo es muy pesado. Prueba con un clip más corto o una foto más liviana.")
    r = PandMomento(owner_key=owner_key)
    db.add(r)
    r.imagen = img
    r.caption = (str(p.get("caption") or "").strip()[:140] or None)
    r.char = (str(p.get("char") or "").strip()[:40] or None)
    r.nombre = (str(nombre or "").strip()[:80] or (str(p.get("nombre") or "").strip()[:80] or None))
    r.curso = (str(curso or "").strip()[:40] or None)
    r.reportes = 0
    r.oculto = False
    r.created_at = _dt.datetime.utcnow()
    db.commit()
    # tope rodante: si supera el máximo activo, borra los más antiguos del alumno
    activos = (db.query(PandMomento).filter(PandMomento.owner_key == owner_key)
               .order_by(PandMomento.created_at.desc()).all())
    if len(activos) > _MAX_POR_ALUMNO:
        for viejo in activos[_MAX_POR_ALUMNO:]:
            db.delete(viejo)
        db.commit()
    return {"ok": True, "momento": _dict(r, con_imagen=False)}


def _mis_vigentes(db: Session, owner_key: str):
    filas = db.query(PandMomento).filter(PandMomento.owner_key == owner_key).all()
    vis = [x for x in filas if (not x.oculto) and _vigente(x) and _es_media(x.imagen or "")]
    vis.sort(key=lambda x: x.created_at or _dt.datetime.min)   # cronológico (viejo→nuevo) para la Historia
    return vis


def feed(db: Session, owner_key: str, curso: str = "") -> dict:
    """Historias: metadatos SIN media (la media se pide por momento al abrir, para no inflar el feed
    con videos). Devuelve `mios` (mi Historia) y `grupos` (una Historia por compañero del mismo curso)."""
    mios = [_dict(x, con_imagen=False) for x in _mis_vigentes(db, owner_key)]
    grupos = []
    cur = str(curso or "").strip()[:40]
    if cur:
        filas = db.query(PandMomento).filter(PandMomento.curso == cur,
                                             PandMomento.owner_key != owner_key).all()
        vis = [x for x in filas if (not x.oculto) and _vigente(x) and _es_media(x.imagen or "")]
        por: dict = {}
        for x in vis:
            por.setdefault(x.owner_key, []).append(x)
        personas = []
        for _ok, lst in por.items():
            lst.sort(key=lambda x: x.created_at or _dt.datetime.min)   # cronológico
            personas.append((lst[-1].created_at or _dt.datetime.min, lst))
        personas.sort(key=lambda t: t[0], reverse=True)   # persona con lo más nuevo primero
        for _u, lst in personas:
            cab = lst[-1]
            grupos.append({"char": cab.char, "nombre": cab.nombre,
                           "momentos": [_dict(x, con_imagen=False) for x in lst]})
    # compat con el frontend anterior (un momento por persona)
    mio = (_mis_vigentes(db, owner_key) or [None])
    mio = _dict(mio[-1], con_imagen=True) if mio and mio[-1] is not None else None
    companeros = []
    for g in grupos:
        m = g["momentos"][-1]
        companeros.append(m)
    return {"ok": True, "mios": mios, "grupos": grupos, "mio": mio, "companeros": companeros}


def media(db: Session, cid: str, momento_id) -> dict:
    """Devuelve la media completa de UN momento (carga perezosa), solo si es del mismo curso."""
    try:
        u = _uuid.UUID(str(momento_id))
    except (ValueError, TypeError):
        raise not_found("Momento no válido.")
    r = db.query(PandMomento).filter(PandMomento.id == u).first()
    if r is None or r.oculto or not _vigente(r):
        raise not_found("Ese momento ya no está disponible.")
    if str(r.curso or "") != str(cid or ""):
        raise not_found("Ese momento no es de tu grupo.")
    return {"ok": True, "id": str(r.id), "imagen": r.imagen, "caption": r.caption,
            "char": r.char, "nombre": r.nombre, "created_at": r.created_at.isoformat() if r.created_at else None}


def eliminar(db: Session, owner_key: str, momento_id=None) -> dict:
    if momento_id:
        try:
            u = _uuid.UUID(str(momento_id))
        except (ValueError, TypeError):
            raise not_found("Momento no válido.")
        r = db.query(PandMomento).filter(PandMomento.id == u,
                                         PandMomento.owner_key == owner_key).first()
        if r is not None:
            db.delete(r); db.commit()
        return {"ok": True, "id": str(momento_id)}
    filas = db.query(PandMomento).filter(PandMomento.owner_key == owner_key).all()   # sin id: quita todos
    for r in filas:
        db.delete(r)
    db.commit()
    return {"ok": True, "mio": None}


def reportar(db: Session, mid) -> dict:
    try:
        u = _uuid.UUID(str(mid))
    except (ValueError, TypeError):
        raise not_found("Momento no válido.")
    r = db.query(PandMomento).filter(PandMomento.id == u).first()
    if r is None:
        raise not_found("Ese momento ya no existe.")
    r.reportes = int(r.reportes or 0) + 1
    if r.reportes >= _REPORT_HIDE:
        r.oculto = True
    db.commit()
    return {"ok": True, "oculto": bool(r.oculto), "reportes": r.reportes}
