"""
v4 · Servicio del motor de experiencia universal. `resolver()` es PURO y DETERMINISTA y sigue la
precedencia de `adaptation-policy`: seguridad/evaluación → accesibilidad → elección explícita → tarea
actual → contexto del curso → preferencia reciente → default. Fallback seguro = Core + pack `general` +
compañero, sin bloquear la tarea. Devuelve `resolutionReasons` (nunca contenido privado). Los catálogos se
cachean por versión, no por estudiante; los cambios de catálogo NO tocan recibos históricos.
"""
from __future__ import annotations

import json
import os
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.experiencia import CourseFacultyBinding, StudentRelationship

_CAT = None
_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "runi_v4")

# lo que ESTA fase entrega (feature flags independientes de la migración v4)
_FLAGS = {"runiRelationshipV4": True, "facultyPacksV4": True, "rewardDimensionsV4": False}


def _load(name: str) -> dict:
    with open(os.path.join(_DIR, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _cat() -> dict:
    global _CAT
    if _CAT is None:
        rel = _load("relationship-modes.json")
        fac = _load("faculty-packs.json")
        ops = _load("learning-operations.json")
        dim = _load("universal-reward-dimensions.json")
        pol = _load("adaptation-policy.json")
        packs = fac.get("packs") or fac.get("faculties") or []
        _CAT = {
            "relationship": rel, "faculty": fac, "operations": ops, "dimensions": dim, "policy": pol,
            "rel_by": {m["id"]: m for m in rel.get("modes", [])},
            "pack_by": {p["id"]: p for p in packs},
            "op_ids": {o["id"] for o in ops.get("operations", [])},
        }
    return _CAT


def catalogos(db: Session | None = None) -> dict:
    c = _cat()
    return {"ok": True, "flags": _FLAGS,
            "relationship_modes": c["relationship"].get("modes", []),
            "relationship_default": c["relationship"].get("default", "companion"),
            "faculty_packs": list(c["pack_by"].values()),
            "faculty_fallback": c["faculty"].get("fallback", "general"),
            "learning_operations": c["operations"].get("operations", []),
            "reward_dimensions": c["dimensions"].get("dimensions", []),
            "dimensions_display": c["dimensions"].get("display", {}),
            "versions": {"relationship": c["relationship"].get("version"), "faculty": c["faculty"].get("version"),
                         "operations": c["operations"].get("version"), "dimensions": c["dimensions"].get("version"),
                         "policy": c["policy"].get("version")}}


def _pack(pack_id: str) -> dict:
    c = _cat()
    return c["pack_by"].get(pack_id) or c["pack_by"].get("general") or {"id": "general", "accent": "#34e5a8", "world": "studio"}


def _faculty_de_curso(db: Session | None, course_code: str) -> str | None:
    if not (db and course_code):
        return None
    b = db.query(CourseFacultyBinding).filter(CourseFacultyBinding.course_code == course_code).first()
    return b.faculty_pack_id if b else None


def _assessment_safe(student: dict) -> dict:
    acc = (student or {}).get("accessibility") or {}
    reduced = bool(acc.get("reducedMotion"))
    return {"ok": True, "assessmentSafe": True, "relationshipMode": "quiet", "facultyPackId": "general",
            "operation": "understand", "accent": "#7785a3", "world": "studio",
            "motionTier": "none" if reduced else "spark", "soundEnabled": False, "hapticsEnabled": False,
            "proactiveInterventionAllowed": False, "hideAcademicChat": True, "denyUploads": True,
            "denyCamera": True, "denyAnswerGeneration": True,
            "resolutionReasons": ["safety_and_assessment_mode"]}


# ── resolución determinista ──────────────────────────────────────────────────
def resolver(db: Session | None, student: dict, relation: dict, ctx: dict) -> dict:
    c = _cat()
    student = student or {}; relation = relation or {}; ctx = ctx or {}
    reasons: list[str] = []
    # 1) seguridad / modo evaluación primero
    if ctx.get("assessmentMode"):
        return _assessment_safe(student)
    # 5) facultad: ctx → binding del curso → perfil del estudiante → general
    fac = ctx.get("facultyPackId")
    if fac and fac in c["pack_by"]:
        reasons.append("explicit_faculty")
    else:
        fac = _faculty_de_curso(db, ctx.get("course_code") or "")
        if fac and fac in c["pack_by"]:
            reasons.append("course_pack")
        else:
            fac = student.get("facultyPackId")
            if fac and fac in c["pack_by"]:
                reasons.append("profile_pack")
            else:
                fac = "general"; reasons.append("default_pack")
    pack = _pack(fac)
    # 4) operación de aprendizaje de la tarea
    op = ctx.get("operation") or ((student.get("preferredOperations") or [None])[0]) or "understand"
    if op not in c["op_ids"]:
        op = "understand"
    else:
        reasons.append("task_operation")
    # 3) elección explícita del vínculo (override temporal solo durante la tarea)
    mode = relation.get("temporaryMode") or relation.get("primaryMode") or c["relationship"].get("default", "companion")
    if mode not in c["rel_by"]:
        mode = "companion"
    if relation.get("temporaryMode"):
        reasons.append("temporary_relationship")
    elif relation.get("primaryMode"):
        reasons.append("explicit_relationship")
    else:
        reasons.append("default_relationship")
    # 2) accesibilidad
    acc = student.get("accessibility") or {}
    reduced = bool(acc.get("reducedMotion"))
    if reduced:
        reasons.append("accessibility_reduced_motion")
    proactivity = relation.get("proactivity") or "medium"
    proactive_ok = (mode != "quiet") and (proactivity != "low")
    return {"ok": True, "assessmentSafe": False,
            "relationshipMode": mode, "facultyPackId": fac, "operation": op,
            "accent": pack.get("accent", "#34e5a8"), "world": pack.get("world", "studio"),
            "metaphors": pack.get("metaphors", []),
            "motionTier": "none" if reduced else "spark",
            "soundEnabled": (acc.get("sound") != "off"), "hapticsEnabled": bool(acc.get("haptics", True)),
            "proactiveInterventionAllowed": proactive_ok,
            "maxUnsolicited": c["policy"].get("constraints", {}).get("maxUnsolicitedInterventionsPerSession", 2),
            "cooldownMinutes": c["policy"].get("constraints", {}).get("cooldownMinutes", 15),
            "resolutionReasons": reasons}


# ── vínculos (persistencia mínima) ───────────────────────────────────────────
def vincular_facultad(db: Session, course_code: str, faculty_pack_id: str, quien: str = "") -> dict:
    if faculty_pack_id not in _cat()["pack_by"]:
        return {"ok": False, "error": "facultad desconocida"}
    b = db.query(CourseFacultyBinding).filter(CourseFacultyBinding.course_code == course_code).first()
    if b:
        b.faculty_pack_id = faculty_pack_id; b.bound_by = quien or b.bound_by
    else:
        db.add(CourseFacultyBinding(id=_uuid.uuid4().hex[:32], course_code=course_code, faculty_pack_id=faculty_pack_id, bound_by=(quien or None)))
    db.commit()
    return {"ok": True, "course_code": course_code, "faculty_pack_id": faculty_pack_id}


def tono_de_modo(db: Session | None, pseudo_id: str) -> dict:
    """v4-F2 · Devuelve el modo de vínculo del estudiante (con tono/desafío/iniciativa del catálogo) para
    inyectarlo al prompt de Runi. Default 'companion'. Nunca falla: cae a compañero."""
    mode_id = "companion"
    try:
        if db is not None and pseudo_id:
            r = db.query(StudentRelationship).filter(StudentRelationship.pseudo_id == pseudo_id).first()
            if r and r.primary_mode:
                mode_id = r.primary_mode
    except Exception:  # noqa: BLE001
        mode_id = "companion"
    c = _cat()
    return c["rel_by"].get(mode_id) or c["rel_by"].get("companion") or {"id": "companion", "label": "Compañero",
            "tone": "cálido, horizontal y breve", "challenge": "low", "initiative": "medium"}


def relacion_get(db: Session, pseudo_id: str) -> dict:
    r = db.query(StudentRelationship).filter(StudentRelationship.pseudo_id == pseudo_id).first()
    return {"ok": True, "primary_mode": (r.primary_mode if r else "companion"), "proactivity": (r.proactivity if r else "medium")}


def relacion_set(db: Session, pseudo_id: str, primary_mode: str, proactivity: str = "medium") -> dict:
    if not pseudo_id:
        return {"ok": False, "error": "falta pseudo_id"}
    if primary_mode not in _cat()["rel_by"]:
        return {"ok": False, "error": "modo desconocido"}
    if proactivity not in ("low", "medium", "high"):
        proactivity = "medium"
    r = db.query(StudentRelationship).filter(StudentRelationship.pseudo_id == pseudo_id).first()
    if r:
        r.primary_mode = primary_mode; r.proactivity = proactivity
    else:
        db.add(StudentRelationship(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, primary_mode=primary_mode, proactivity=proactivity))
    db.commit()
    return {"ok": True, "primary_mode": primary_mode, "proactivity": proactivity}
