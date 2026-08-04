"""
Consola del Administrador (CEO) — supervisión de gobernanza, SOLO LECTURA, rol 'creador'.

Acceso "fantasma": observa sin participar ni alterar la interacción. Cada lectura de contenido
de estudiantes registra un asiento en `admin_accesos_log` (bitácora que protege al CEO).

Ámbito actual: datos ya almacenados de la capa social (Notas y Momentos). Grabar videollamadas
o retener diálogos indefinidamente es un módulo aparte (captura de datos nuevos) que NO se hace aquí.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.admin_log import AccesoAdminLog
from app.models.pand_nota import PandNota
from app.models.pand_momento import PandMomento


def _log(db: Session, admin_email: str, recurso: str, detalle: str = "") -> None:
    try:
        db.add(AccesoAdminLog(admin_email=admin_email or "?", recurso=recurso, detalle=(detalle or None)))
        db.commit()
    except Exception:
        db.rollback()


def resumen(db: Session, admin_email: str) -> dict:
    """Conteos globales para el tablero (no lee contenido → asiento liviano)."""
    n_notas = db.query(PandNota).count()
    n_moment = db.query(PandMomento).count()
    n_accesos = db.query(AccesoAdminLog).count()
    _log(db, admin_email, "resumen", f"notas={n_notas} momentos={n_moment}")
    return {"ok": True, "resumen": {"notas": n_notas, "momentos": n_moment, "accesos_registrados": n_accesos}}


def social(db: Session, admin_email: str, con_imagen: bool = False) -> dict:
    """Todas las Notas y Momentos de la plataforma (contenido). Registra el acceso."""
    notas = [{"id": str(r.id), "owner_key": r.owner_key, "curso": r.curso, "char": r.char,
              "nombre": r.nombre, "texto": r.texto,
              "created_at": r.created_at.isoformat() if r.created_at else None}
             for r in db.query(PandNota).order_by(PandNota.created_at.desc()).all()]
    momentos = []
    for r in db.query(PandMomento).order_by(PandMomento.created_at.desc()).all():
        d = {"id": str(r.id), "owner_key": r.owner_key, "curso": r.curso, "char": r.char,
             "nombre": r.nombre, "caption": r.caption, "reportes": r.reportes, "oculto": bool(r.oculto),
             "created_at": r.created_at.isoformat() if r.created_at else None}
        if con_imagen:
            d["imagen"] = r.imagen
        momentos.append(d)
    _log(db, admin_email, "social", f"notas={len(notas)} momentos={len(momentos)} imagen={int(con_imagen)}")
    return {"ok": True, "notas": notas, "momentos": momentos}


def accesos(db: Session, admin_email: str, limite: int = 200) -> dict:
    """La bitácora de accesos del propio administrador (transparencia interna)."""
    filas = db.query(AccesoAdminLog).order_by(AccesoAdminLog.created_at.desc()).limit(min(int(limite or 200), 1000)).all()
    return {"ok": True, "accesos": [{"admin": r.admin_email, "recurso": r.recurso, "detalle": r.detalle,
                                     "created_at": r.created_at.isoformat() if r.created_at else None} for r in filas]}
