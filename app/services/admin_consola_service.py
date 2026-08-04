"""
Consola del Administrador (CEO) — supervisión de gobernanza, SOLO LECTURA, rol 'creador'.

Acceso "fantasma": observa sin participar ni alterar la interacción. Cada lectura de contenido
de estudiantes registra un asiento en `admin_accesos_log` (bitácora que protege al CEO).

Ámbito actual: datos ya almacenados de la capa social (Notas y Momentos). Grabar videollamadas
o retener diálogos indefinidamente es un módulo aparte (captura de datos nuevos) que NO se hace aquí.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy.orm import Session

from app.models.admin_log import AccesoAdminLog
from app.models.pand_nota import PandNota
from app.models.pand_momento import PandMomento
from app.models.reunion import Disponibilidad, Reserva
from app.models.silabo import MensajeSilabo, SilaboAgente


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


def reuniones(db: Session, admin_email: str) -> dict:
    """Reuniones/reservas EN VIVO: disponibilidades activas + próximas citas confirmadas."""
    disp_activas = db.query(Disponibilidad).filter(Disponibilidad.activo == True).count()  # noqa: E712
    hoy = _dt.date.today().isoformat()
    filas = (db.query(Reserva).filter(Reserva.estado == "confirmada", Reserva.fecha >= hoy)
             .order_by(Reserva.fecha.asc(), Reserva.inicio.asc()).limit(80).all())
    disp_ids = {r.disponibilidad_id for r in filas}
    disp = {d.id: d for d in db.query(Disponibilidad).filter(Disponibilidad.id.in_(disp_ids)).all()} if disp_ids else {}
    reservas = []
    for r in filas:
        d = disp.get(r.disponibilidad_id)
        reservas.append({"id": str(r.id), "fecha": r.fecha, "inicio": r.inicio, "fin": r.fin,
                         "invitado": r.invitado, "anfitrion": (d.anfitrion if d else ""),
                         "titulo": (d.titulo if d else "Reunión"), "video": bool(r.video_url),
                         "nota": r.nota})
    _log(db, admin_email, "reuniones", f"activas={disp_activas} reservas={len(reservas)}")
    return {"ok": True, "disponibilidades_activas": disp_activas, "reservas": reservas}


def dialogos(db: Session, admin_email: str, limite: int = 60) -> dict:
    """Diálogos con Runi EN VIVO: las consultas más recientes de los estudiantes (pulso, no archivo)."""
    filas = db.query(MensajeSilabo).order_by(MensajeSilabo.created_at.desc()).limit(min(int(limite or 60), 200)).all()
    ag_ids = {f.agente_id for f in filas}
    agentes = {a.id: a for a in db.query(SilaboAgente).filter(SilaboAgente.id.in_(ag_ids)).all()} if ag_ids else {}
    out = []
    for f in filas:
        a = agentes.get(f.agente_id)
        curso = (a.nombre_curso if a and a.nombre_curso else (a.codigo if a else None)) or "—"
        out.append({"id": str(f.id), "curso": curso, "alias": f.alias, "pregunta": f.pregunta,
                    "respuesta": (f.respuesta_ia or "")[:400], "tema": f.tema, "categoria": f.categoria,
                    "confianza": f.confianza, "estado": f.estado,
                    "created_at": f.created_at.isoformat() if f.created_at else None})
    _log(db, admin_email, "dialogos", f"n={len(out)}")
    return {"ok": True, "dialogos": out}


def accesos(db: Session, admin_email: str, limite: int = 200) -> dict:
    """La bitácora de accesos del propio administrador (transparencia interna)."""
    filas = db.query(AccesoAdminLog).order_by(AccesoAdminLog.created_at.desc()).limit(min(int(limite or 200), 1000)).all()
    return {"ok": True, "accesos": [{"admin": r.admin_email, "recurso": r.recurso, "detalle": r.detalle,
                                     "created_at": r.created_at.isoformat() if r.created_at else None} for r in filas]}
