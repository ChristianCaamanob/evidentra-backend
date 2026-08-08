"""RBAC por ámbito — lógica de acceso escalonado (gobernanza).

Reglas:
  · El CREADOR ve/gobierna todo (superadmin).
  · Un usuario con MEMBRESÍAS activas ve/gobierna solo dentro de ellas, con descenso progresivo
    controlado: una membresía de nivel más alto (menor RANGO) puede DESCENDER a niveles más
    granulares dentro de su ámbito — pero nunca automáticamente hasta el dato personal.
  · LEGACY-SAFE: un director/investigador SIN membresías conserva el acceso agregado actual
    (no rompe la experiencia existente hasta que se asignen ámbitos).
El acceso a dato personal exige `registrar_acceso_personal` (finalidad + justificación + registro).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.membresia import Membresia, AccesoPersonalLog, RANGO
from app.models.teacher import ROL_CREADOR


def _ahora():
    return datetime.now(timezone.utc)


def membresias_activas(db: Session, usuario) -> list[Membresia]:
    ahora = _ahora()
    ms = db.query(Membresia).filter(Membresia.teacher_id == usuario.id, Membresia.activa == True).all()  # noqa: E712
    vig = []
    for m in ms:
        vh = m.vigente_hasta
        if vh is not None:
            # normaliza naive→aware para comparar sin romper
            if vh.tzinfo is None:
                vh = vh.replace(tzinfo=timezone.utc)
            if vh < ahora:
                continue
        vig.append(m)
    return vig


def _ambito_cubre(m_ambito: str, obj_ambito: str) -> bool:
    """La membresía cubre el ámbito objetivo si es 'todo el nivel' ("") o coincide/es prefijo."""
    ma = (m_ambito or "").strip()
    if ma == "":
        return True
    oa = (obj_ambito or "").strip()
    return oa == ma or oa.startswith(ma)


def puede_ver(usuario, membresias: list[Membresia], nivel: str, ambito: str = "") -> bool:
    """¿Puede el usuario VER (observar) algo en (nivel, ámbito)? Aplica descenso progresivo."""
    if usuario.rol == ROL_CREADOR:
        return True
    if not membresias:
        return True   # legacy-safe: sin membresías, mantiene el acceso agregado actual
    obj_rango = RANGO.get(nivel, 9)
    for m in membresias:
        # una membresía de rango <= objetivo puede descender hasta ese nivel, dentro de su ámbito
        if RANGO.get(m.nivel, 9) <= obj_rango and _ambito_cubre(m.ambito, ambito):
            return True
    return False


def puede_actuar(usuario, membresias: list[Membresia], nivel: str, ambito: str, accion: str) -> bool:
    """¿Puede EJECUTAR una acción (comentar/solicitar/aprobar/intervenir) en (nivel, ámbito)?
    A diferencia de observar, actuar NO desciende: exige membresía en ese mismo nivel con la acción."""
    if usuario.rol == ROL_CREADOR:
        return True
    if not membresias:
        return usuario.rol in ("director", "investigador")  # legacy-safe acotado
    for m in membresias:
        if m.nivel == nivel and _ambito_cubre(m.ambito, ambito):
            if accion in [a.strip() for a in (m.acciones or "observar").split(",")]:
                return True
    return False


def registrar_acceso_personal(db: Session, usuario, ambito: str, sujeto_ref: str,
                              finalidad: str, justificacion: str, emergencia: bool = False) -> AccesoPersonalLog:
    """Registra (append-only) un acceso a dato personal. Exige finalidad + justificación."""
    if not (finalidad or "").strip() or not (justificacion or "").strip():
        raise ValueError("El acceso a dato personal exige finalidad y justificación.")
    log = AccesoPersonalLog(teacher_id=usuario.id, ambito=(ambito or ""), sujeto_ref=(sujeto_ref or ""),
                            finalidad=finalidad.strip(), justificacion=justificacion.strip(), emergencia=bool(emergencia))
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def dto_membresia(m: Membresia) -> dict:
    return {"id": str(m.id), "teacher_id": str(m.teacher_id), "nivel": m.nivel, "ambito": m.ambito,
            "acciones": [a.strip() for a in (m.acciones or "").split(",") if a.strip()],
            "detalle": m.detalle, "finalidad": m.finalidad,
            "vigente_hasta": m.vigente_hasta.isoformat() if m.vigente_hasta else None,
            "activa": m.activa, "created_at": m.created_at.isoformat() if m.created_at else None}
