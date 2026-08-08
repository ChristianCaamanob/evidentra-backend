"""
Personalización v4 · persistencia por estudiante (seudónimo). GET/PUT de las preferencias de "Mi espacio".

Sin auth de staff (el alumno no tiene login de staff): la clave es el seudónimo del propio dispositivo/alumno,
igual que /push y /silabo. Se valida el prefijo del seudónimo y se guarda SOLO una lista blanca de campos
(nada de PII ni datos sensibles). No es una nota ni entra a analítica académica.
"""
import json

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.ratelimit import limit
from app.models.runi_pref import RuniPref

router = APIRouter(prefix="/runi", tags=["runi-personalizacion"])

# Lista blanca de campos permitidos (todo lo demás se descarta al guardar).
_ALLOWED = {
    "accent", "customAccent", "ambiente", "surface", "lightMode", "bgIntensity", "motion",
    "presencia", "voz", "font", "fs", "autoVoz", "wake", "rwSound", "rwHaptic", "accessories",
}


def _limpiar(prefs: dict) -> dict:
    out = {}
    if not isinstance(prefs, dict):
        return out
    for k, v in prefs.items():
        if k not in _ALLOWED:
            continue
        if k == "accessories":
            out[k] = [str(x)[:40] for x in (v or [])][:20] if isinstance(v, list) else []
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = (v[:120] if isinstance(v, str) else v)
    return out


def _valido(pseudo: str) -> bool:
    return isinstance(pseudo, str) and pseudo.startswith("stu:") and 4 < len(pseudo) <= 80


@router.get("/prefs")
def runi_prefs_get(participant: str = ""):
    if not _valido(participant):
        return {"ok": False, "reason": "bad_participant"}
    db: Session = SessionLocal()
    try:
        row = db.query(RuniPref).filter(RuniPref.pseudo_id == participant).first()
        if not row:
            return {"ok": True, "prefs": None, "updatedAt": ""}
        try:
            prefs = json.loads(row.prefs_json or "{}")
        except Exception:
            prefs = {}
        return {"ok": True, "prefs": prefs, "updatedAt": row.updated_at_client or "", "schemaVersion": row.schema_version}
    finally:
        db.close()


@router.put("/prefs")
@limit("60/minute")
def runi_prefs_put(request: Request, payload: dict):
    p = payload or {}
    pseudo = p.get("participant", "")
    if not _valido(pseudo):
        return {"ok": False, "reason": "bad_participant"}
    prefs = _limpiar(p.get("prefs") or {})
    updated = str(p.get("updatedAt", ""))[:40]
    db: Session = SessionLocal()
    try:
        row = db.query(RuniPref).filter(RuniPref.pseudo_id == pseudo).first()
        if row:
            # last-write-wins: solo sobrescribe si el cliente trae una marca igual o más nueva.
            if updated and row.updated_at_client and updated < row.updated_at_client:
                return {"ok": True, "stale": True, "updatedAt": row.updated_at_client}
            row.prefs_json = json.dumps(prefs, ensure_ascii=False)
            row.updated_at_client = updated
            row.schema_version = int(p.get("schemaVersion", 1) or 1)
        else:
            row = RuniPref(pseudo_id=pseudo, prefs_json=json.dumps(prefs, ensure_ascii=False),
                           updated_at_client=updated, schema_version=int(p.get("schemaVersion", 1) or 1))
            db.add(row)
        db.commit()
        return {"ok": True, "updatedAt": updated}
    finally:
        db.close()
