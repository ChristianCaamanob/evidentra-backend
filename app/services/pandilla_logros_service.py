"""
F7 · Servicio de Maestría compartida (Pandilla). Instrumenta las señales de las medallas 10-12 con
anti-farming: apoyo entre pares SOLO cuenta validado (tope diario 2 por quien ayuda, sin duplicados),
metas grupales acreditan a sus aportantes al completarse, y la maestría longitudinal la otorga el docente.
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.pandilla_logros import (GoalContribution, GroupGoal, LongitudinalMastery, PeerSupport)

_CAP_DIARIO = 2   # validados por quien ayuda, por día (progression-rules.antiFarming.peerSupportDailyCap)


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


def _hoy() -> str:
    return _dt.date.today().isoformat()


# ── apoyo entre pares ─────────────────────────────────────────────────────────
def registrar_apoyo(db: Session, helper: str, beneficiary: str, course_id: str = "", kind: str = "explicacion", nota: str = "") -> dict:
    helper = (helper or "").strip(); beneficiary = (beneficiary or "").strip()
    if not helper or not beneficiary:
        return {"ok": False, "error": "faltan helper/beneficiary"}
    if helper == beneficiary:
        return {"ok": False, "error": "no puedes registrarte apoyo a ti mismo"}
    day = _hoy()
    # anti-duplicado: mismo par + curso + tipo + día → devuelve el existente
    dup = (db.query(PeerSupport)
           .filter(PeerSupport.helper_pseudo == helper, PeerSupport.beneficiary_pseudo == beneficiary,
                   PeerSupport.course_id == (course_id or None), PeerSupport.kind == kind, PeerSupport.day == day)
           .first())
    if dup:
        return {"ok": True, "id": dup.id, "validated": dup.validated, "duplicado": True}
    ps = PeerSupport(id=_uid(), helper_pseudo=helper, beneficiary_pseudo=beneficiary,
                     course_id=(course_id or None), kind=kind, nota=(nota or None)[:500] if nota else None, day=day)
    db.add(ps); db.commit()
    return {"ok": True, "id": ps.id, "validated": False}


def validar_apoyo(db: Session, support_id: str, validador: str) -> dict:
    ps = db.query(PeerSupport).filter(PeerSupport.id == support_id).first()
    if not ps:
        return {"ok": False, "error": "apoyo no encontrado"}
    if ps.validated:
        return {"ok": True, "already": True}
    # solo lo valida quien lo recibió o un docente (validador con prefijo 'docente:')
    es_docente = str(validador or "").startswith("docente:")
    if not es_docente and validador != ps.beneficiary_pseudo:
        return {"ok": False, "error": "solo el beneficiario o un docente pueden validar el apoyo"}
    # tope diario del que AYUDA
    ya_hoy = (db.query(PeerSupport)
              .filter(PeerSupport.helper_pseudo == ps.helper_pseudo, PeerSupport.day == ps.day,
                      PeerSupport.validated == True)  # noqa: E712
              .count())
    if ya_hoy >= _CAP_DIARIO:
        return {"ok": False, "error": "tope diario de apoyos validados alcanzado (" + str(_CAP_DIARIO) + ")", "cap": True}
    ps.validated = True; ps.validated_by = validador; ps.validated_at = _dt.datetime.utcnow()
    db.commit()
    return {"ok": True, "validated": True}


def apoyos_de(db: Session, pseudo: str) -> dict:
    dados = db.query(PeerSupport).filter(PeerSupport.helper_pseudo == pseudo).all()
    recibidos = db.query(PeerSupport).filter(PeerSupport.beneficiary_pseudo == pseudo).all()
    def _row(p):
        return {"id": p.id, "kind": p.kind, "validated": p.validated, "beneficiary": p.beneficiary_pseudo,
                "helper": p.helper_pseudo, "nota": p.nota, "day": p.day}
    return {"ok": True, "dados": [_row(p) for p in dados], "recibidos": [_row(p) for p in recibidos],
            "validados_dados": sum(1 for p in dados if p.validated),
            "pendientes_por_validar": [_row(p) for p in recibidos if not p.validated]}


# ── metas grupales ────────────────────────────────────────────────────────────
def meta_crear(db: Session, course_id: str, sala_code: str, titulo: str, meta_n: int, creador: str = "") -> dict:
    g = GroupGoal(id=_uid(), course_id=(course_id or None), sala_code=(sala_code or None),
                  titulo=(titulo or "Meta de la Pandilla")[:160], meta_n=max(1, int(meta_n or 5)), created_by=(creador or None))
    db.add(g); db.commit()
    return {"ok": True, "id": g.id, "meta_n": g.meta_n}


def meta_aportar(db: Session, goal_id: str, pseudo: str, n: int = 1) -> dict:
    g = db.query(GroupGoal).filter(GroupGoal.id == goal_id).first()
    if not g:
        return {"ok": False, "error": "meta no encontrada"}
    n = max(1, int(n or 1))
    c = db.query(GoalContribution).filter(GoalContribution.goal_id == goal_id, GoalContribution.pseudo_id == pseudo).first()
    if c:
        c.aporte += n
    else:
        db.add(GoalContribution(id=_uid(), goal_id=goal_id, pseudo_id=pseudo, aporte=n))
    g.progreso = (g.progreso or 0) + n
    recien = False
    if not g.completado and g.progreso >= g.meta_n:
        g.completado = True; g.completed_at = _dt.datetime.utcnow(); recien = True
    db.commit()
    return {"ok": True, "progreso": g.progreso, "meta_n": g.meta_n, "completado": g.completado, "recien_completada": recien}


def metas_de_curso(db: Session, course_id: str) -> dict:
    gs = db.query(GroupGoal).filter(GroupGoal.course_id == course_id).order_by(GroupGoal.created_at.desc()).all()
    return {"ok": True, "metas": [{"id": g.id, "titulo": g.titulo, "meta_n": g.meta_n, "progreso": g.progreso,
            "completado": g.completado, "sala_code": g.sala_code} for g in gs]}


# ── maestría longitudinal (docente) ──────────────────────────────────────────
def otorgar_maestria(db: Session, course_id: str, pseudo: str, docente: str = "", nota: str = "") -> dict:
    if not course_id or not pseudo:
        return {"ok": False, "error": "faltan course_id/pseudo"}
    ya = db.query(LongitudinalMastery).filter(LongitudinalMastery.course_id == course_id, LongitudinalMastery.pseudo_id == pseudo).first()
    if ya:
        return {"ok": True, "already": True}
    db.add(LongitudinalMastery(id=_uid(), course_id=course_id, pseudo_id=pseudo, granted_by=(docente or None), nota=(nota or None)))
    db.commit()
    return {"ok": True, "otorgada": True}


# ── señales para el motor de logros (medallas 10-12) ─────────────────────────
def senales(db: Session, pseudo: str) -> dict:
    validated_peer = db.query(PeerSupport).filter(PeerSupport.helper_pseudo == pseudo, PeerSupport.validated == True).count()  # noqa: E712
    goal_ids = [c.goal_id for c in db.query(GoalContribution).filter(GoalContribution.pseudo_id == pseudo).all()]
    shared_goals = 0
    if goal_ids:
        shared_goals = db.query(GroupGoal).filter(GroupGoal.id.in_(goal_ids), GroupGoal.completado == True).count()  # noqa: E712
    mastery = db.query(LongitudinalMastery).filter(LongitudinalMastery.pseudo_id == pseudo).count() > 0
    return {"validatedPeerSupports": validated_peer, "sharedGroupGoalsCompleted": shared_goals,
            "courseDefinedLongitudinalMastery": mastery}
