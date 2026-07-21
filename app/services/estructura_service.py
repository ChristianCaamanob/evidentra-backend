"""
Estructura institucional (config 'Lego'): Facultades / Departamentos / Profesores como bloques
que se ensamblan sobre los cursos reales. Persistencia en un único registro JSON (scope='global').

Al guardar, sincroniza los NOMBRES de facultad/departamento sobre cada curso asignado, para que
el Panorama del Director (que agrega por course.facultad/departamento) refleje la estructura.
No altera notas (G1); es metadata organizativa.
"""
from __future__ import annotations

import uuid as _uuid

from app.models.estructura import EstructuraInstitucional
from app.models.course import Course
from app.models.student import Student

SCOPE = "global"
_VACIA = {"facultades": [], "departamentos": [], "profesores": [], "cursos": {}}


def _registro(db):
    return db.query(EstructuraInstitucional).filter(EstructuraInstitucional.scope == SCOPE).first()


def obtener_payload(db) -> dict:
    reg = _registro(db)
    p = dict((reg.payload if reg and reg.payload else {}) or {})
    for k, v in _VACIA.items():
        if k not in p or p[k] is None:
            p[k] = {} if isinstance(v, dict) else []
    return p


def bloques_cursos(db) -> list[dict]:
    """Los cursos REALES disponibles para ensamblar (con su nómina y su facultad/depto actual)."""
    out = []
    for c in db.query(Course).all():
        n = db.query(Student).filter(Student.course_id == c.id).count()
        out.append({"id": str(c.id), "name": c.name, "code": c.code, "tipo": c.tipo,
                    "facultad": c.facultad, "departamento": c.departamento, "n_estudiantes": n})
    out.sort(key=lambda x: (x["name"] or "").lower())
    return out


def estado(db) -> dict:
    return {"payload": obtener_payload(db), "cursos": bloques_cursos(db)}


def _index(lst, key="id"):
    return {x.get(key): x for x in (lst or []) if isinstance(x, dict) and x.get(key)}


def guardar(db, payload: dict) -> dict:
    payload = dict(payload or {})
    for k, v in _VACIA.items():
        if k not in payload or payload[k] is None:
            payload[k] = {} if isinstance(v, dict) else []

    reg = _registro(db)
    if not reg:
        reg = EstructuraInstitucional(scope=SCOPE, payload=payload)
        db.add(reg)
    else:
        reg.payload = payload
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(reg, "payload")

    # ── Sincroniza nombres de facultad/departamento sobre los cursos asignados ──
    facs = _index(payload.get("facultades"))
    deps = _index(payload.get("departamentos"))
    asign = payload.get("cursos") or {}
    for cid, meta in asign.items():
        if not isinstance(meta, dict):
            continue
        try:
            curso = db.query(Course).filter(Course.id == _uuid.UUID(str(cid))).first()
        except (ValueError, TypeError):
            curso = None
        if not curso:
            continue
        dep = deps.get(meta.get("departamento_id"))
        if dep:
            if dep.get("nombre"):
                curso.departamento = dep["nombre"]
            fac = facs.get(dep.get("facultad_id"))
            if fac and fac.get("nombre"):
                curso.facultad = fac["nombre"]

    db.commit()
    return estado(db)
