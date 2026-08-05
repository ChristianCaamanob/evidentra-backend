"""
Motor del Episodio de Aprendizaje Verificado (North Star).

Ciclo: start → observe(confianza) → feedback → close(+comprobación inmediata) → [comprobación diferida].
`completo` = objetivo + respuesta + feedback + cierre.  `verificado` = completo + comprobación.
Métricas: EAV/WAU, %≥3 EAV, Brier, calibración, sobreconfianza, errores de alta confianza, retención diferida.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.episode import Episode, ConfidenceObs, RetentionCheck

_VENTANAS = {"24-48h": _dt.timedelta(hours=36), "7d": _dt.timedelta(days=7), "21-30d": _dt.timedelta(days=25)}
_CONF_MAP = {"baja": 30, "media": 60, "alta": 90}   # etiqueta metacognitiva → confianza 0–100


def _ep(db, eid) -> Episode:
    try:
        u = _uuid.UUID(str(eid))
    except (ValueError, TypeError):
        raise not_found("Episodio no válido.")
    e = db.query(Episode).filter(Episode.id == u).first()
    if not e:
        raise not_found("Episodio no encontrado.")
    return e


def start(db: Session, pseudo_id: str, course_id: str, ra: str, objetivo: str = "", origen: str = "") -> dict:
    if not (pseudo_id or "").strip():
        raise unprocessable("Falta pseudo_id.")
    e = Episode(pseudo_id=str(pseudo_id)[:80], course_id=(str(course_id)[:64] if course_id else None),
                ra=(str(ra)[:120] if ra else None), objetivo=(str(objetivo)[:255] or None),
                origen=(str(origen)[:40] or None))
    db.add(e); db.commit()
    return {"ok": True, "episode_id": str(e.id)}


def observe(db: Session, episode_id, obs: dict) -> dict:
    e = _ep(db, episode_id)
    o = obs or {}
    if o.get("item_id") is None or o.get("confidence") is None:
        raise unprocessable("La observación necesita item_id y confidence.")
    conf = max(0, min(100, int(o.get("confidence") or 0)))
    corr = o.get("correct")
    corr = (bool(corr) if corr is not None else None)   # None = auto-reporte sin corrección
    db.add(ConfidenceObs(episode_id=e.id, pseudo_id=e.pseudo_id, course_id=e.course_id, ra=(o.get("ra") or e.ra),
                         item_id=str(o.get("item_id"))[:80], correct=corr, confidence=conf,
                         response_time_ms=o.get("response_time_ms"), help_used=bool(o.get("help_used")),
                         attempt=int(o.get("attempt") or 1)))
    db.commit()
    return {"ok": True}


def registrar_silabo(db: Session, pseudo_id: str, course_id, tema: str, confianza_label: str,
                     sintesis: str = "") -> dict:
    """Cable sílabo→Episodio: una consulta con confianza auto-reportada = Episodio COMPLETO
    (objetivo=tema, feedback dado por Runi, cierre=síntesis) + comprobación diferida 7d programada.
    Se vuelve VERIFICADO cuando el estudiante responde esa comprobación."""
    ra = (str(tema or "consulta"))[:120]
    e = Episode(pseudo_id=str(pseudo_id)[:80], course_id=(str(course_id)[:64] if course_id else None),
                ra=ra, objetivo=("Comprender: " + ra)[:255], origen="silabo", feedback_given=True,
                sintesis=((str(sintesis)[:2000]) or "Consulta resuelta con Runi."),
                closed_at=_dt.datetime.utcnow(), completo=True, verificado=False)
    db.add(e); db.flush()
    conf = _CONF_MAP.get((confianza_label or "").lower(), 60)
    db.add(ConfidenceObs(episode_id=e.id, pseudo_id=e.pseudo_id, course_id=e.course_id, ra=ra,
                         item_id="silabo", correct=None, confidence=conf, attempt=1))
    db.add(RetentionCheck(episode_id=e.id, pseudo_id=e.pseudo_id, course_id=e.course_id, ra=ra,
                          ventana="7d", scheduled_for=_dt.datetime.utcnow() + _VENTANAS["7d"]))
    db.commit()
    return {"ok": True, "episode_id": str(e.id), "completo": True}


def feedback(db: Session, episode_id) -> dict:
    e = _ep(db, episode_id); e.feedback_given = True; db.commit()
    return {"ok": True}


def close(db: Session, episode_id, sintesis: str = "", check_immediate=None, programar_diferida: str = "7d") -> dict:
    e = _ep(db, episode_id)
    e.sintesis = (str(sintesis)[:2000] or None)
    e.closed_at = _dt.datetime.utcnow()
    if check_immediate is not None:
        e.check_immediate = bool(check_immediate)
    n_obs = db.query(ConfidenceObs).filter(ConfidenceObs.episode_id == e.id).count()
    e.completo = bool(e.ra and n_obs > 0 and e.feedback_given and e.sintesis)
    e.verificado = bool(e.completo and (e.check_immediate is not None))
    # Programar comprobación diferida (spaced retrieval) — se responde luego y puede verificar el episodio.
    dif = None
    if e.completo and programar_diferida in _VENTANAS:
        dif = RetentionCheck(episode_id=e.id, pseudo_id=e.pseudo_id, course_id=e.course_id, ra=e.ra,
                             ventana=programar_diferida, scheduled_for=_dt.datetime.utcnow() + _VENTANAS[programar_diferida])
        db.add(dif)
    db.commit()
    return {"ok": True, "completo": e.completo, "verificado": e.verificado,
            "diferida_programada": (dif is not None), "ventana": (programar_diferida if dif else None)}


def responder_diferida(db: Session, check_id, correct: bool) -> dict:
    try:
        u = _uuid.UUID(str(check_id))
    except (ValueError, TypeError):
        raise not_found("Comprobación no válida.")
    c = db.query(RetentionCheck).filter(RetentionCheck.id == u).first()
    if not c:
        raise not_found("Comprobación no encontrada.")
    c.correct = bool(correct); c.done_at = _dt.datetime.utcnow(); db.commit()
    e = db.query(Episode).filter(Episode.id == c.episode_id).first()
    if e and e.completo and not e.verificado:
        e.verificado = True; db.commit()   # una comprobación diferida respondida verifica el episodio
    return {"ok": True, "verificado": bool(e and e.verificado)}


def pendientes_diferidas(db: Session, pseudo_id: str) -> dict:
    ahora = _dt.datetime.utcnow()
    filas = (db.query(RetentionCheck)
             .filter(RetentionCheck.pseudo_id == str(pseudo_id), RetentionCheck.done_at.is_(None),
                     RetentionCheck.scheduled_for <= ahora).all())
    return {"ok": True, "pendientes": [{"id": str(c.id), "ra": c.ra, "ventana": c.ventana,
                                        "course_id": c.course_id} for c in filas]}


def mi_progreso(db: Session, pseudo_id: str) -> dict:
    """Progreso REAL del estudiante para su home: dominio por RA, episodios, errores de alta
    confianza y repasos pendientes. Dominio = % correcto sobre observaciones graduadas; si un RA
    solo tiene auto-reporte (sílabo), se usa la confianza como proxy (marcado `graduado:false`)."""
    pid = str(pseudo_id or "")
    if not pid:
        return {"ok": True, "episodios": 0, "verificados": 0, "por_ra": [], "errores_alta_confianza": 0, "repasos_hoy": 0}
    eps = db.query(Episode).filter(Episode.pseudo_id == pid).all()
    obs = db.query(ConfidenceObs).filter(ConfidenceObs.pseudo_id == pid).all()
    ras: dict[str, dict] = {}
    for o in obs:
        r = o.ra or "General"
        d = ras.setdefault(r, {"ok": 0, "ng": 0, "conf": 0, "n": 0})
        d["n"] += 1; d["conf"] += (o.confidence or 0)
        if o.correct is not None:
            d["ng"] += 1; d["ok"] += (1 if o.correct else 0)
    por_ra = []
    for r, d in ras.items():
        dominio = round(d["ok"] / d["ng"] * 100) if d["ng"] else round(d["conf"] / max(1, d["n"]))
        por_ra.append({"ra": r, "dominio": dominio, "n": d["n"], "graduado": d["ng"] > 0})
    por_ra.sort(key=lambda x: x["dominio"])   # lo más débil primero (para intervención)
    ahora = _dt.datetime.utcnow()
    repasos = (db.query(RetentionCheck)
               .filter(RetentionCheck.pseudo_id == pid, RetentionCheck.done_at.is_(None),
                       RetentionCheck.scheduled_for <= ahora).count())
    return {"ok": True, "episodios": len(eps), "verificados": sum(1 for e in eps if e.verificado),
            "por_ra": por_ra[:6], "errores_alta_confianza": sum(1 for o in obs if o.correct is False and (o.confidence or 0) >= 80),
            "repasos_hoy": repasos}


def resumen_docente(db: Session, course: str, dias: int = 14) -> dict:
    """B8 · Dashboard docente de DECISIONES (no gráficos): pulso del curso + RA con mayor dificultad
    (dominio + errores de alta confianza) + alertas pedagógicas accionables."""
    m = metricas(db, course or None, dias)
    desde = _dt.datetime.utcnow() - _dt.timedelta(days=max(1, int(dias or 14)))
    q = db.query(ConfidenceObs).filter(ConfidenceObs.created_at >= desde)
    if course:
        q = q.filter(ConfidenceObs.course_id == course)
    obs = q.all()
    ras: dict[str, dict] = {}
    for o in obs:
        r = o.ra or "General"
        d = ras.setdefault(r, {"ok": 0, "ng": 0, "conf": 0, "n": 0, "alta_mal": 0})
        d["n"] += 1; d["conf"] += (o.confidence or 0)
        if o.correct is not None:
            d["ng"] += 1; d["ok"] += (1 if o.correct else 0)
            if o.correct is False and (o.confidence or 0) >= 80:
                d["alta_mal"] += 1
    por_ra = [{"ra": r, "dominio": (round(d["ok"] / d["ng"] * 100) if d["ng"] else round(d["conf"] / max(1, d["n"]))),
               "n": d["n"], "graduado": d["ng"] > 0, "errores_alta_confianza": d["alta_mal"]} for r, d in ras.items()]
    por_ra.sort(key=lambda x: (x["dominio"], -x["errores_alta_confianza"]))   # más difícil primero
    alertas = []
    for r in por_ra:
        if r["errores_alta_confianza"] >= 2:
            alertas.append({"tipo": "alta_confianza", "ra": r["ra"],
                            "texto": r["ra"] + ": varios errores con ALTA confianza → conviene una aclaración colectiva."})
        elif r["graduado"] and r["dominio"] < 45:
            alertas.append({"tipo": "dominio_bajo", "ra": r["ra"],
                            "texto": r["ra"] + ": dominio bajo (" + str(r["dominio"]) + "%) → reforzar en clase."})
    return {"ok": True, "pulso": m, "por_ra": por_ra[:8], "alertas": alertas[:6]}


def metricas(db: Session, course_id: str | None = None, dias: int = 7) -> dict:
    """North Star + calibración en ventana de `dias`. Para dashboards (no califica estudiantes)."""
    desde = _dt.datetime.utcnow() - _dt.timedelta(days=max(1, int(dias or 7)))

    def _ep_q():
        q = db.query(Episode).filter(Episode.started_at >= desde)
        return q.filter(Episode.course_id == course_id) if course_id else q

    def _obs_q():
        q = db.query(ConfidenceObs).filter(ConfidenceObs.created_at >= desde)
        return q.filter(ConfidenceObs.course_id == course_id) if course_id else q

    eps = _ep_q().all()
    obs = _obs_q().all()
    wau = len(set([e.pseudo_id for e in eps] + [o.pseudo_id for o in obs]))
    eav = [e for e in eps if e.verificado]
    n_eav = len(eav)
    # %≥3 EAV por estudiante activo
    por_est = {}
    for e in eav:
        por_est[e.pseudo_id] = por_est.get(e.pseudo_id, 0) + 1
    con_3 = sum(1 for v in por_est.values() if v >= 3)
    # calibración — SOLO sobre observaciones graduadas (correct != None). El auto-reporte del
    # sílabo (correct=None) alimenta la distribución de confianza, no el Brier.
    grad = [o for o in obs if o.correct is not None]
    ng = len(grad)
    brier = round(sum(((o.confidence / 100.0) - (1 if o.correct else 0)) ** 2 for o in grad) / ng, 4) if ng else None
    cal_err = round(sum(abs((o.confidence / 100.0) - (1 if o.correct else 0)) for o in grad) / ng, 4) if ng else None
    conf_media_g = (sum(o.confidence for o in grad) / ng / 100.0) if ng else None
    exac_media = (sum(1 for o in grad if o.correct) / ng) if ng else None
    sobreconf = round(conf_media_g - exac_media, 4) if ng else None
    err_alta_conf = sum(1 for o in grad if o.confidence >= 80 and not o.correct)
    conf_autoreporte = round(sum(o.confidence for o in obs if o.correct is None) / max(1, sum(1 for o in obs if o.correct is None)), 1) if any(o.correct is None for o in obs) else None
    # retención diferida (checks respondidos en ventana)
    rq = db.query(RetentionCheck).filter(RetentionCheck.done_at.isnot(None), RetentionCheck.done_at >= desde)
    if course_id:
        rq = rq.filter(RetentionCheck.course_id == course_id)
    rchecks = rq.all()
    ret_dif = round(sum(1 for c in rchecks if c.correct) / len(rchecks), 4) if rchecks else None
    return {"ok": True, "ventana_dias": dias, "wau": wau, "eav": n_eav,
            "eav_por_wau": round(n_eav / wau, 3) if wau else 0,
            "pct_3eav": round(con_3 / wau, 3) if wau else 0,
            "brier": brier, "error_calibracion": cal_err, "sobreconfianza": sobreconf,
            "errores_alta_confianza": err_alta_conf, "retencion_diferida": ret_dif,
            "observaciones": len(obs), "observaciones_graduadas": ng,
            "confianza_autoreporte": conf_autoreporte}
