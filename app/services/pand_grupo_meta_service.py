"""
Meta compartida del grupo: un objetivo común con el avance de cada integrante.

Reusa `GroupGoal`/`GoalContribution`, que ya existían atados al CURSO o a una sala. El
ámbito del grupo se guarda en el mismo `course_id` con la forma 'g:<codigo>' —igual que
hace el chat—, para no duplicar tablas ni el motor de aportes por una diferencia que es
solo de alcance.

Se respeta el diseño que ya tenían esas tablas: el aporte es una CANTIDAD (entero) y hay
un aporte por persona y meta (restricción única). Así el avance del grupo es la suma de lo
que puso cada uno, y nadie puede inflarlo creando filas.
"""
from __future__ import annotations

import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.pandilla_logros import GroupGoal, GoalContribution

_META_POR_DEFECTO = 5


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


def _scope(codigo: str) -> str:
    return "g:" + str(codigo or "").strip().upper()


def _activa(db: Session, codigo: str) -> GroupGoal | None:
    """La meta vigente del grupo: la más reciente sin completar."""
    return (db.query(GroupGoal)
            .filter(GroupGoal.course_id == _scope(codigo), GroupGoal.completado.is_(False))
            .order_by(GroupGoal.created_at.desc()).first())


def _dict(db: Session, g: GroupGoal | None, owner_key: str | None = None) -> dict:
    if not g:
        return {"ok": True, "meta": None}
    aportes = (db.query(GoalContribution).filter(GoalContribution.goal_id == g.id)
               .order_by(GoalContribution.created_at.asc()).all())
    total = sum(int(a.aporte or 0) for a in aportes)
    meta_n = int(g.meta_n or _META_POR_DEFECTO)
    return {"ok": True, "meta": {
        "id": g.id,
        "titulo": g.titulo or "Meta del grupo",
        "meta_n": meta_n,
        "progreso": total,
        "pct": min(100, round(total * 100 / meta_n)) if meta_n else 0,
        "completado": bool(g.completado) or (meta_n > 0 and total >= meta_n),
        "ya_aporte": bool(owner_key and any(a.pseudo_id == owner_key for a in aportes)),
        "aportes": [{"nombre": (a.nombre or "Compañero/a"),
                     "cantidad": int(a.aporte or 0),
                     "soy_yo": bool(owner_key and a.pseudo_id == owner_key),
                     "fecha": a.created_at.isoformat() if a.created_at else None}
                    for a in aportes],
    }}


def crear(db: Session, codigo: str, owner_key: str, titulo: str, meta_n: int = 0) -> dict:
    t = str(titulo or "").strip()[:160]
    if not t:
        raise unprocessable("Escribe qué quieren lograr.")
    # Una meta activa por grupo: crear otra cierra la anterior en vez de acumular metas
    # a medio terminar que nadie vuelve a mirar.
    prev = _activa(db, codigo)
    if prev:
        prev.completado = True
    try:
        n = int(meta_n or 0)
    except (TypeError, ValueError):
        n = 0
    g = GroupGoal(id=_uid(), course_id=_scope(codigo), titulo=t, created_by=owner_key,
                  meta_n=(n if n > 0 else _META_POR_DEFECTO))
    db.add(g)
    db.commit()
    db.refresh(g)
    return _dict(db, g, owner_key)


def aportar(db: Session, codigo: str, owner_key: str, nombre: str | None, cantidad=1) -> dict:
    g = _activa(db, codigo)
    if not g:
        raise unprocessable("El grupo todavía no tiene una meta. Creen una primero.")
    try:
        n = max(1, min(20, int(cantidad or 1)))
    except (TypeError, ValueError):
        n = 1
    # Un aporte por persona y meta (restricción única): volver a aportar SUMA al propio,
    # no crea una fila nueva.
    mio = db.query(GoalContribution).filter(
        GoalContribution.goal_id == g.id, GoalContribution.pseudo_id == owner_key).first()
    if mio:
        mio.aporte = int(mio.aporte or 0) + n
        if nombre and not mio.nombre:
            mio.nombre = str(nombre)[:80]
    else:
        db.add(GoalContribution(id=_uid(), goal_id=g.id, pseudo_id=owner_key, aporte=n,
                                nombre=(str(nombre or "").strip()[:80] or None)))
    db.flush()
    total = sum(int(a.aporte or 0) for a in
                db.query(GoalContribution).filter(GoalContribution.goal_id == g.id).all())
    g.progreso = total
    db.commit()
    return _dict(db, g, owner_key)


def completar(db: Session, codigo: str, owner_key: str) -> dict:
    g = _activa(db, codigo)
    if not g:
        raise unprocessable("No hay una meta activa.")
    g.completado = True
    db.commit()
    return {"ok": True, "completado": True}


def ver(db: Session, codigo: str, owner_key: str | None = None) -> dict:
    return _dict(db, _activa(db, codigo), owner_key)
