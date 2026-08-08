"""Libro Mayor de la evidencia — servicio (procedencia + hash encadenado, APPEND-ONLY).

Filosofía (Handoff v2, "el fondo"): la evidencia debe ser AUDITABLE y a prueba de manipulación.
Cada artefacto metodológico (corpus, cribado, protocolo, meta, PRISMA…) deja una entrada inmutable
cada vez que cambia de contenido; la entrada guarda el SHA-256 del contenido, el hash de la entrada
anterior del mismo artefacto (cadena tipo bitácora) y el tamaño. Así "el Libro Mayor abre la
procedencia completa" y se puede verificar integridad (recalcular el hash del estado actual y
compararlo con el último registrado). NO inventa: solo registra artefactos con contenido real.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.models.libro_mayor import LibroMayorEntrada
# Reutilizamos el catálogo de artefactos del motor de defendibilidad (misma verdad).
from app.services.defendibilidad_service import _ARTEFACTOS, _has

# Artefactos que el Libro Mayor rastrea (los que tienen etiqueta+plano en el catálogo).
_CLAVES = list(_ARTEFACTOS.keys())


def _canon(contenido) -> str:
    return json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _hash(contenido) -> str:
    return hashlib.sha256(_canon(contenido).encode("utf-8")).hexdigest()


def _tam(v):
    return len(v) if isinstance(v, (list, dict)) else None


def _ultima(db: Session, proyecto_id, clave: str) -> LibroMayorEntrada | None:
    return (db.query(LibroMayorEntrada)
            .filter(LibroMayorEntrada.proyecto_id == proyecto_id, LibroMayorEntrada.clave == clave)
            .order_by(LibroMayorEntrada.created_at.desc(), LibroMayorEntrada.id.desc())
            .first())


def registrar_cambios(db: Session, proyecto, datos: dict | None, actor_id=None) -> int:
    """Añade una entrada por cada artefacto CON CONTENIDO cuyo hash difiera del último registrado.
    NO hace commit (lo hace quien llama, dentro de su transacción). Devuelve el nº de entradas nuevas."""
    d = datos or {}
    nuevas = 0
    for clave in _CLAVES:
        cont = d.get(clave)
        if not _has(d, clave):
            continue
        h = _hash(cont)
        ult = _ultima(db, proyecto.id, clave)
        if ult and ult.hash == h:
            continue  # sin cambios reales → no se registra ruido
        _lbl, plano = _ARTEFACTOS[clave]
        db.add(LibroMayorEntrada(
            proyecto_id=proyecto.id, clave=clave, hash=h,
            hash_prev=(ult.hash if ult else None), n=_tam(cont),
            plano=plano, actor_id=actor_id))
        nuevas += 1
    return nuevas


def libro_mayor(db: Session, proyecto) -> dict:
    """Vista del Libro Mayor: por artefacto, estado actual + integridad + historial (procedencia).
    Si el proyecto no tiene NINGUNA entrada aún (proyectos previos), siembra una línea base idempotente."""
    d = proyecto.datos or {}
    # Semilla de línea base (una sola vez): registra el estado actual como primer commit por artefacto.
    hay = db.query(LibroMayorEntrada.id).filter(LibroMayorEntrada.proyecto_id == proyecto.id).first()
    if not hay:
        if registrar_cambios(db, proyecto, d, actor_id=getattr(proyecto, "investigador_id", None)):
            db.commit()

    filas = (db.query(LibroMayorEntrada)
             .filter(LibroMayorEntrada.proyecto_id == proyecto.id)
             .order_by(LibroMayorEntrada.created_at.asc(), LibroMayorEntrada.id.asc())
             .all())
    por_clave: dict[str, list[LibroMayorEntrada]] = {}
    for f in filas:
        por_clave.setdefault(f.clave, []).append(f)

    artefactos = []
    total_commits = 0
    intactos = 0
    for clave in _CLAVES:
        hist = por_clave.get(clave) or []
        if not hist:
            continue
        lbl, plano = _ARTEFACTOS[clave]
        ult = hist[-1]
        # integridad: el hash del contenido actual coincide con el último registrado
        actual_hash = _hash(d.get(clave)) if _has(d, clave) else None
        integ = "intacto" if (actual_hash and actual_hash == ult.hash) else ("modificado" if actual_hash else "ausente")
        if integ == "intacto":
            intactos += 1
        # cadena: cada entrada apunta al hash de la anterior
        cadena_ok = all((hist[i].hash_prev == hist[i - 1].hash) for i in range(1, len(hist)))
        total_commits += len(hist)
        artefactos.append({
            "clave": clave, "label": lbl, "plano": plano,
            "commits": len(hist), "integridad": integ, "cadena_ok": cadena_ok,
            "actual": {"hash": ult.hash, "hash_corto": ult.hash[:12], "n": ult.n,
                       "fecha": ult.created_at.isoformat() if ult.created_at else None},
            "historial": [{"hash_corto": e.hash[:12], "hash": e.hash,
                           "hash_prev_corto": (e.hash_prev[:12] if e.hash_prev else None),
                           "n": e.n, "fecha": e.created_at.isoformat() if e.created_at else None}
                          for e in reversed(hist)],  # más reciente primero
        })

    return {
        "proyecto_id": str(proyecto.id),
        "artefactos": artefactos,
        "resumen": {"artefactos": len(artefactos), "commits": total_commits,
                    "intactos": intactos, "algoritmo": "SHA-256", "cadena": "por artefacto"},
    }
