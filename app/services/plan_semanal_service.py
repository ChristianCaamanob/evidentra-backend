"""
El plan de la semana que se pone la estudiante.

La medalla «Rumbo propio» pide cumplir tu propio plan, y no existía ningún lugar donde ese plan
existiera: la agenda solo guarda el horario de clases extraído de la foto, que no es un plan sino un
calendario impuesto. Aquí ella declara cuántos episodios quiere cerrar esta semana.

Dos decisiones:
- **El plan lo pone ella**, no el sistema. Un objetivo asignado no es rumbo propio.
- **Se mide contra episodios VERIFICADOS**, no contra sesiones abiertas ni minutos en la app. Abrir
  la app no es estudiar, y esa es la regla de toda la progresión.

No se castiga la semana incumplida: no resta nada, solo no suma.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.episode import Episode
from app.models.juicio import PlanSemanal

_MIN, _MAX = 1, 20
UMBRAL = 0.8            # ≥80% del propio plan, como pide la puerta de la medalla 8


def _hoy() -> _dt.date:
    """Siempre en UTC. Los episodios se guardan con `utcnow()`, así que mezclar la fecha LOCAL con
    marcas de tiempo UTC parte la semana en dos: un domingo por la tarde en Chile ya es lunes en UTC
    y los episodios de ese día dejaban de contar para el plan. Cazado por un test que empezó a
    fallar al cruzar la medianoche UTC."""
    return _dt.datetime.utcnow().date()


def semana_de(d: _dt.date | None = None) -> str:
    d = d or _hoy()
    a, s, _ = d.isocalendar()
    return f"{a}-W{s:02d}"


def _rango(semana: str) -> tuple:
    """Lunes 00:00 y domingo 23:59:59 de esa semana ISO."""
    a, s = int(semana[:4]), int(semana[6:])
    lunes = _dt.date.fromisocalendar(a, s, 1)
    return (_dt.datetime.combine(lunes, _dt.time.min),
            _dt.datetime.combine(lunes + _dt.timedelta(days=6), _dt.time.max))


def fijar(db: Session, pseudo_id: str, meta: int, nota: str = "", semana: str | None = None) -> dict:
    """Pone (o cambia) el plan de la semana. Uno por semana: cambiarlo lo reemplaza."""
    if not (pseudo_id or "").strip():
        raise unprocessable("Falta la identidad del estudiante.")
    try:
        meta = int(meta)
    except (TypeError, ValueError):
        raise unprocessable("La meta tiene que ser un número de episodios.")
    if not (_MIN <= meta <= _MAX):
        raise unprocessable(f"Ponte una meta entre {_MIN} y {_MAX} episodios.")
    sem = semana or semana_de()
    p = (db.query(PlanSemanal).filter(PlanSemanal.pseudo_id == pseudo_id,
                                      PlanSemanal.semana == sem).first())
    if p:
        p.meta_episodios = meta
        p.nota = (str(nota or "").strip()[:200] or None)
    else:
        db.add(PlanSemanal(id=_uuid.uuid4().hex[:32], pseudo_id=str(pseudo_id)[:80], semana=sem,
                           meta_episodios=meta, nota=(str(nota or "").strip()[:200] or None)))
    db.commit()
    return estado(db, pseudo_id, sem)


def _hechos(db: Session, pseudo_id: str, semana: str) -> int:
    ini, fin = _rango(semana)
    return (db.query(Episode)
            .filter(Episode.pseudo_id == pseudo_id, Episode.verificado.is_(True),
                    Episode.started_at >= ini, Episode.started_at <= fin).count())


def estado(db: Session, pseudo_id: str, semana: str | None = None) -> dict:
    sem = semana or semana_de()
    p = (db.query(PlanSemanal).filter(PlanSemanal.pseudo_id == pseudo_id,
                                      PlanSemanal.semana == sem).first())
    hechos = _hechos(db, pseudo_id, sem)
    meta = p.meta_episodios if p else 0
    pct = round(min(1.0, hechos / meta) * 100) if meta else 0
    return {"ok": True, "semana": sem, "hay_plan": bool(p), "meta": meta, "nota": (p.nota if p else None),
            "hechos": hechos, "pct": pct, "cumplida": bool(meta and (hechos / meta) >= UMBRAL),
            "sugerencia": _sugerencia(db, pseudo_id) if not p else None}


def _sugerencia(db: Session, pseudo_id: str) -> int:
    """Qué meta proponerle: lo que logró la semana pasada, +1. Nunca menos de 2 ni más de 6.

    Proponer un número alto a quien recién empieza no motiva, lo desmoraliza; y proponerle siempre
    3 a quien ya hace 8 lo vuelve irrelevante.
    """
    prev = semana_de(_hoy() - _dt.timedelta(days=7))
    return max(2, min(6, _hechos(db, pseudo_id, prev) + 1))


def semanas_cumplidas(db: Session, pseudo_id: str) -> int:
    """Cuántas semanas cumplió su propio plan (la señal de la medalla «Rumbo propio»).

    Solo cuentan semanas CERRADAS: la actual todavía puede completarse y contarla ahora sería
    adelantar un logro que aún no ocurre.
    """
    actual = semana_de()
    planes = db.query(PlanSemanal).filter(PlanSemanal.pseudo_id == pseudo_id).all()
    n = 0
    for p in planes:
        if p.semana >= actual or not p.meta_episodios:
            continue
        if (_hechos(db, pseudo_id, p.semana) / p.meta_episodios) >= UMBRAL:
            n += 1
    return n
