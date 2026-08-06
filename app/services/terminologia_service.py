"""
F5 · Servicio de gobernanza terminológica. Importa contratos (schema v3), resuelve conceptId→término
vigente por perfil o por curso, normaliza sinónimos y advierte términos obsoletos. Perfiles publicados
inmutables; una edición nueva SUPERSEDE (no borra) a la anterior → las evidencias históricas nunca se reescriben.
"""
from __future__ import annotations

import re
import unicodedata
import uuid as _uuid

from sqlalchemy.orm import Session

from app.models.terminologia import CourseTermBinding, TermEntry, TermProfile


def _uid() -> str:
    return _uuid.uuid4().hex[:32]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower().strip())


# ── importar un contrato (perfil + términos) ─────────────────────────────────
def importar(db: Session, contrato: dict, quien: str = "") -> dict:
    c = contrato or {}
    req = ["disciplineId", "profileId", "locale", "terms"]
    faltan = [k for k in req if not c.get(k)]
    if faltan:
        return {"ok": False, "error": "faltan campos: " + ", ".join(faltan)}
    pid = str(c["profileId"]).strip()
    ya = db.query(TermProfile).filter(TermProfile.profile_id == pid).first()
    if ya:
        return {"ok": False, "error": "ya existe un perfil con profileId '" + pid + "' (los perfiles son inmutables; usa una edición nueva que lo supersede)"}
    sup = c.get("supersedes")
    prev = db.query(TermProfile).filter(TermProfile.profile_id == sup).first() if sup else None
    version = (prev.version + 1) if prev else 1
    prof = TermProfile(
        id=_uid(), profile_id=pid, discipline_id=str(c["disciplineId"]).strip(), locale=str(c.get("locale") or "es-CL"),
        source_authority=c.get("sourceAuthority"), source_edition=c.get("sourceEdition"), source_uri=c.get("sourceUri"),
        reviewed_by=(c.get("reviewedBy") or quien or None), reviewed_at=c.get("reviewedAt"), valid_from=c.get("validFrom"),
        supersedes=(sup or None), estado="publicado", version=version, n_terms=len(c.get("terms") or []))
    db.add(prof)
    n = 0
    for t in (c.get("terms") or []):
        cid = str(t.get("conceptId") or "").strip()
        pref = str(t.get("preferredTerm") or "").strip()
        if not cid or not pref:
            continue
        syn = [str(x) for x in (t.get("synonyms") or [])]
        dep = [str(x) for x in (t.get("deprecatedTerms") or [])]
        idx = " | ".join(_norm(x) for x in ([pref] + syn + dep))
        db.add(TermEntry(id=_uid(), profile_id=pid, concept_id=cid, preferred_term=pref,
                         synonyms=syn, deprecated_terms=dep, norm_index=idx))
        n += 1
    prof.n_terms = n
    db.commit()
    return {"ok": True, "profile_id": pid, "version": version, "terminos": n, "supersedes": sup or None}


# ── resolución conceptId → término vigente ───────────────────────────────────
def resolver(db: Session, profile_id: str, concept_id: str, fallback: str = "") -> dict:
    e = db.query(TermEntry).filter(TermEntry.profile_id == profile_id, TermEntry.concept_id == concept_id).first()
    if not e:
        return {"ok": True, "term": (fallback or concept_id), "resuelto": False, "concept_id": concept_id}
    return {"ok": True, "term": e.preferred_term, "resuelto": True, "concept_id": concept_id,
            "profile_id": profile_id, "synonyms": e.synonyms or []}


def _binding(db: Session, course_code: str) -> CourseTermBinding | None:
    return db.query(CourseTermBinding).filter(CourseTermBinding.course_code == course_code).first()


def resolver_por_curso(db: Session, course_code: str, concept_id: str, fallback: str = "") -> dict:
    b = _binding(db, course_code)
    if not b:
        return {"ok": True, "term": (fallback or concept_id), "resuelto": False, "concept_id": concept_id, "sin_perfil": True}
    r = resolver(db, b.profile_id, concept_id, fallback)
    r["profile_id"] = b.profile_id
    return r


# ── búsqueda / normalización (para importar contenido y advertir obsoletos) ──
def buscar(db: Session, profile_id: str, texto: str) -> dict:
    n = _norm(texto)
    if not n:
        return {"ok": True, "match": None}
    for e in db.query(TermEntry).filter(TermEntry.profile_id == profile_id).all():
        partes = (e.norm_index or "").split(" | ")
        if n in partes:
            obsoleto = n in [_norm(x) for x in (e.deprecated_terms or [])]
            return {"ok": True, "match": {"concept_id": e.concept_id, "preferred_term": e.preferred_term,
                    "obsoleto": obsoleto, "aviso": ("término obsoleto: usa «" + e.preferred_term + "»") if obsoleto else None}}
    return {"ok": True, "match": None}


# ── perfiles / vínculos ──────────────────────────────────────────────────────
def perfil(db: Session, profile_id: str) -> dict:
    p = db.query(TermProfile).filter(TermProfile.profile_id == profile_id).first()
    if not p:
        return {"ok": False, "error": "perfil no encontrado"}
    terms = db.query(TermEntry).filter(TermEntry.profile_id == profile_id).order_by(TermEntry.concept_id.asc()).all()
    return {"ok": True, "profile": {"profile_id": p.profile_id, "discipline_id": p.discipline_id, "locale": p.locale,
            "source_authority": p.source_authority, "source_edition": p.source_edition, "reviewed_by": p.reviewed_by,
            "reviewed_at": p.reviewed_at, "valid_from": p.valid_from, "supersedes": p.supersedes, "version": p.version,
            "n_terms": p.n_terms},
            "terms": [{"concept_id": t.concept_id, "preferred_term": t.preferred_term, "synonyms": t.synonyms or [],
                       "deprecated_terms": t.deprecated_terms or []} for t in terms]}


def listar_perfiles(db: Session) -> dict:
    ps = db.query(TermProfile).order_by(TermProfile.created_at.desc()).all()
    return {"ok": True, "perfiles": [{"profile_id": p.profile_id, "discipline_id": p.discipline_id, "locale": p.locale,
            "version": p.version, "supersedes": p.supersedes, "n_terms": p.n_terms, "reviewed_by": p.reviewed_by,
            "source_edition": p.source_edition} for p in ps]}


def vincular_curso(db: Session, course_code: str, profile_id: str, quien: str = "") -> dict:
    if not course_code or not profile_id:
        return {"ok": False, "error": "faltan course_code o profile_id"}
    if not db.query(TermProfile).filter(TermProfile.profile_id == profile_id).first():
        return {"ok": False, "error": "el perfil no existe"}
    b = _binding(db, course_code)
    if b:
        b.profile_id = profile_id; b.bound_by = quien or b.bound_by
    else:
        db.add(CourseTermBinding(id=_uid(), course_code=course_code, profile_id=profile_id, bound_by=(quien or None)))
    db.commit()
    return {"ok": True, "course_code": course_code, "profile_id": profile_id}


# ── perfil starter (idempotente) ─────────────────────────────────────────────
_SEED = {
    "disciplineId": "anatomia", "profileId": "anatomia-demo-2026-v1", "locale": "es-CL",
    "sourceAuthority": "Terminologia Anatomica (FIPAT)", "sourceEdition": "2ª ed.",
    "sourceUri": "", "reviewedBy": "(demo — sin firma real)", "reviewedAt": "2026-08-05T00:00:00Z",
    "validFrom": "2026-01-01", "supersedes": None,
    "terms": [
        {"conceptId": "clavicula", "preferredTerm": "Clavícula", "synonyms": ["hueso de la collera"], "deprecatedTerms": ["clavicle"]},
        {"conceptId": "musculo-biceps-braquial", "preferredTerm": "Músculo bíceps braquial", "synonyms": ["bíceps"], "deprecatedTerms": ["biceps del brazo"]},
        {"conceptId": "arteria-aorta", "preferredTerm": "Aorta", "synonyms": ["arteria aorta"], "deprecatedTerms": ["gran arteria"]},
        {"conceptId": "nervio-vago", "preferredTerm": "Nervio vago", "synonyms": ["X par craneal", "nervio neumogástrico"], "deprecatedTerms": ["décimo par"]},
        {"conceptId": "homeostasis", "preferredTerm": "Homeostasis", "synonyms": ["equilibrio del medio interno"], "deprecatedTerms": []},
    ],
}


def sembrar(db: Session) -> dict:
    if db.query(TermProfile).filter(TermProfile.profile_id == _SEED["profileId"]).first():
        return {"ok": True, "sembrados": 0, "ya_existia": True}
    return importar(db, _SEED, quien="seed")
