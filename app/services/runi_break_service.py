"""La Guarida de Runi · lógica de pausa restaurativa con TIEMPO DE SERVIDOR.

El servidor es la fuente de verdad del término (`end_at`) y del tiempo real (`actual_seconds`).
El cliente sólo anima el conteo entre sincronizaciones; al restaurar una pestaña vuelve a preguntar
`active` y recibe el `remaining_ms` recalculado por el servidor. Nunca se penaliza el descanso.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.runi_break import RuniBreak, ZONAS


def _as_uuid(v):
    if isinstance(v, _uuid.UUID):
        return v
    try:
        return _uuid.UUID(str(v))
    except Exception:  # noqa: BLE001
        raise not_found("Pausa no encontrada.")

_MIN_OK = {2, 5, 10, 15}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _dto(b: RuniBreak) -> dict:
    now = _now()
    end = _aware(b.end_at) or now
    remaining = int(max(0, (end - now).total_seconds() * 1000))
    return {
        "break_id": str(b.id), "estado": b.estado, "zone": b.zone,
        "planned_minutes": b.planned_minutes, "extended_count": b.extended_count,
        "added_minutes_total": b.added_minutes_total, "actual_seconds": b.actual_seconds,
        "started_at": _aware(b.started_at).isoformat() if b.started_at else None,
        "end_at": end.isoformat(),
        "server_now": now.isoformat(),
        "remaining_ms": remaining if b.estado == "active" else 0,
        "outcome_source": b.outcome_source,
    }


def start(db: Session, pseudo_id: str, zone: str, planned_minutes: int,
          course_id: str | None = None, source_session_id: str | None = None) -> dict:
    pid = (pseudo_id or "").strip()
    if not pid:
        raise unprocessable("Falta pseudo_id (identidad seudonimizada).")
    z = zone if zone in ZONAS else "calm"
    m = int(planned_minutes or 5)
    if m not in _MIN_OK:
        m = 5
    now = _now()
    b = RuniBreak(pseudo_id=pid[:80], course_id=(str(course_id)[:64] if course_id else None),
                  source_session_id=(str(source_session_id)[:80] if source_session_id else None),
                  zone=z, planned_minutes=m, extended_count=0, added_minutes_total=0,
                  estado="active", started_at=now, end_at=now + timedelta(minutes=m))
    db.add(b)
    db.commit()
    db.refresh(b)
    return _dto(b)


def state(db, break_id, action: str, added_minutes: int = 5, source: str | None = None) -> dict:
    b = db.get(RuniBreak, _as_uuid(break_id))
    if not b:
        raise not_found("Pausa no encontrada.")
    now = _now()
    if action == "extend":
        add = int(added_minutes or 5)
        if add not in _MIN_OK:
            add = 5
        # extender NO reinicia: suma tiempo al término actual (o a 'ahora' si ya venció)
        base = max(_aware(b.end_at) or now, now)
        b.end_at = base + timedelta(minutes=add)
        b.extended_count = (b.extended_count or 0) + 1
        b.added_minutes_total = (b.added_minutes_total or 0) + add
        b.estado = "active"
    elif action in ("complete", "end_early", "return", "finish_day"):
        mapa = {"complete": "completed", "end_early": "ended_early", "return": "returned", "finish_day": "finished_day"}
        b.estado = mapa[action]
        b.closed_at = now
        b.actual_seconds = int(max(0, (now - (_aware(b.started_at) or now)).total_seconds()))
        if source:
            b.outcome_source = str(source)[:40]
    else:
        raise unprocessable("Acción de pausa desconocida.")
    db.commit()
    db.refresh(b)
    return _dto(b)


def active(db: Session, pseudo_id: str) -> dict:
    """La pausa activa más reciente del estudiante (para restaurar al reabrir la pestaña)."""
    pid = (pseudo_id or "").strip()
    if not pid:
        return {"active": None}
    b = (db.query(RuniBreak)
         .filter(RuniBreak.pseudo_id == pid, RuniBreak.estado == "active")
         .order_by(RuniBreak.started_at.desc()).first())
    return {"active": _dto(b) if b else None}


# ── Panel de RECUPERACIÓN Y RETORNO (staff, seudonimizado, agregado) ─────────────────────────────
import math as _math


def _wilson(k: int, n: int, z: float = 1.96):
    """Intervalo de confianza de Wilson para una proporción (reportar efectos con IC, no punto solo)."""
    if n <= 0:
        return {"pct": None, "lo": None, "hi": None, "n": 0}
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = (z * _math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
    return {"pct": round(p * 100, 1), "lo": round(max(0.0, centre - half) * 100, 1),
            "hi": round(min(1.0, centre + half) * 100, 1), "n": n}


def panel(db: Session, course_id: str | None = None, days: int = 30) -> dict:
    """Métricas de descanso RESTAURATIVO. Criterio: la pausa sirve si hay RETORNO EFECTIVO al estudio
    (una acción académica dentro de 2 min de cerrar) + estabilidad del bloque siguiente. NO usa el
    tiempo dentro de la Guarida como éxito. Todo agregado y seudonimizado; efectos con IC de Wilson."""
    from app.models.analytics import AnalyticsEvent

    days = max(1, min(int(days or 30), 180))
    ventana_ini = _now() - timedelta(days=days)
    q = db.query(RuniBreak).filter(RuniBreak.started_at >= ventana_ini)
    if course_id:
        q = q.filter(RuniBreak.course_id == str(course_id))
    breaks = q.order_by(RuniBreak.started_at.desc()).limit(5000).all()

    n = len(breaks)
    estudiantes = len({b.pseudo_id for b in breaks})
    por_duracion = {2: 0, 5: 0, 10: 0, 15: 0}
    por_zona: dict = {}
    por_desenlace = {"completed": 0, "ended_early": 0, "returned": 0, "finished_day": 0, "active": 0}
    cerrados = []
    sin_ext_rep = 0
    adher_ratios = []
    noche_n = 0
    noche_finday = 0
    for b in breaks:
        pm = b.planned_minutes if b.planned_minutes in por_duracion else 5
        por_duracion[pm] = por_duracion.get(pm, 0) + 1
        por_zona[b.zone] = por_zona.get(b.zone, 0) + 1
        por_desenlace[b.estado] = por_desenlace.get(b.estado, 0) + 1
        if (b.extended_count or 0) < 2:
            sin_ext_rep += 1
        st = _aware(b.started_at)
        if st and st.hour >= 21:   # noche (UTC aprox.): abandono nocturno saludable
            noche_n += 1
            if b.estado == "finished_day":
                noche_finday += 1
        if b.closed_at and b.estado in ("completed", "ended_early", "returned"):
            cerrados.append(b)
            if b.actual_seconds is not None and pm > 0:
                adher_ratios.append(min(1.5, b.actual_seconds / (pm * 60.0)))

    # Retorno EFECTIVO: ¿hay una acción académica (dominio aprendizaje) dentro de 2 min de cerrar la pausa?
    retorno_k = 0
    retorno_por_dur = {2: [0, 0], 5: [0, 0], 10: [0, 0], 15: [0, 0]}   # [k, n]
    if cerrados:
        pseudos = list({b.pseudo_id for b in cerrados})
        evs = (db.query(AnalyticsEvent.pseudo_id, AnalyticsEvent.created_at)
               .filter(AnalyticsEvent.domain == "aprendizaje",
                       AnalyticsEvent.created_at >= ventana_ini,
                       AnalyticsEvent.pseudo_id.in_(pseudos)).all())
        by_p: dict = {}
        for pid, ts in evs:
            by_p.setdefault(pid, []).append(_aware(ts))
        for v in by_p.values():
            v.sort()
        for b in cerrados:
            ca = _aware(b.closed_at)
            lst = by_p.get(b.pseudo_id, [])
            hit = any(ca <= t <= ca + timedelta(seconds=120) for t in lst)
            pm = b.planned_minutes if b.planned_minutes in retorno_por_dur else 5
            retorno_por_dur[pm][1] += 1
            if hit:
                retorno_k += 1
                retorno_por_dur[pm][0] += 1

    n_cerr = len(cerrados)
    return {
        "ventana_dias": days, "course_id": course_id or None,
        "n_pausas": n, "n_estudiantes": estudiantes,
        "por_duracion": por_duracion, "por_zona": por_zona, "por_desenlace": por_desenlace,
        "tasa_completadas": _wilson(por_desenlace.get("completed", 0), n) if n else _wilson(0, 0),
        "sin_extension_repetitiva": _wilson(sin_ext_rep, n) if n else _wilson(0, 0),
        "adherencia_media_pct": (round(sum(adher_ratios) / len(adher_ratios) * 100, 1) if adher_ratios else None),
        "retorno_efectivo_2min": _wilson(retorno_k, n_cerr),
        "retorno_por_duracion": {str(k): _wilson(v[0], v[1]) for k, v in retorno_por_dur.items() if v[1] > 0},
        "noche": {"n": noche_n, "finalizaron_dia": noche_finday},
        "criterio": "pausa_restaurativa = retorno_efectivo + estabilidad del siguiente bloque. "
                    "El tiempo dentro de la Guarida NO es KPI. Efectos con IC de Wilson (95%).",
        "pendiente_medicion": "Rendimiento/confianza del bloque siguiente exige enlazar con episodios de "
                              "aprendizaje (EAV); la estratificación usa la duración de la pausa como proxy.",
        "procedencia": {"fuente": "runi_breaks (tiempo de servidor) + eventos de aprendizaje (analytics), seudonimizado",
                        "retorno_efectivo": "acción académica (dominio aprendizaje) dentro de 120 s de cerrar la pausa"},
    }
