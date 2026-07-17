"""
Caché en memoria de los análisis psicométricos (por evaluación).

Los 14 análisis (Rasch, TRI, CFA, invarianza, DIF, DINA, cualitativo…) son deterministas
para un conjunto fijo de respuestas: solo cambian si entran/editan escaneos o cambia la pauta.
Cacheamos el resultado por (assessment_id, clave) con una HUELLA barata = nº de escaneos +
último `updated_at` + `updated_at` de la pauta. Si la huella coincide, devolvemos el valor
cacheado al instante (mata los ~30 s de recálculo en recargas). La huella cambia sola cuando
se agregan hojas → invalidación automática, sin límite temporal.

Cache por proceso (Render free = pocos workers). Se pierde al reiniciar; se recalcula 1 vez.
"""
from __future__ import annotations

import threading

from sqlalchemy import func

from app.models.scan import Scan

_LOCK = threading.Lock()
_CACHE: dict = {}      # {(assessment_id, clave): (huella, valor)}
_MAX = 512             # tope defensivo de entradas


def huella(db, assessment_id) -> str:
    """Huella barata del estado de datos de la evaluación (O(1) en la BD)."""
    n, ts = 0, ""
    try:
        row = db.query(func.count(Scan.id), func.max(Scan.updated_at)) \
            .filter(Scan.assessment_id == assessment_id).first()
        if row:
            n = row[0] or 0
            ts = row[1].isoformat() if row[1] else ""
    except Exception:
        pass
    ak_ts = ""
    try:
        from app.models.answer_key import AnswerKey
        ak = db.query(func.max(AnswerKey.updated_at)) \
            .filter(AnswerKey.assessment_id == assessment_id).scalar()
        ak_ts = ak.isoformat() if ak else ""
    except Exception:
        pass
    return f"{n}:{ts}:{ak_ts}"


def memo(db, assessment_id, clave: str, compute):
    """Devuelve el valor cacheado si la huella coincide; si no, lo calcula y lo guarda.
    `compute` es una función sin argumentos que hace la carga + el cómputo pesado."""
    aid = str(assessment_id)
    fp = huella(db, assessment_id)
    ck = (aid, clave)
    with _LOCK:
        hit = _CACHE.get(ck)
        if hit and hit[0] == fp:
            return hit[1]
    valor = compute()
    with _LOCK:
        if len(_CACHE) > _MAX:
            _CACHE.clear()
        _CACHE[ck] = (fp, valor)
    return valor


def invalidar(assessment_id=None):
    """Limpia la caché (todo, o de una evaluación)."""
    with _LOCK:
        if assessment_id is None:
            _CACHE.clear()
        else:
            aid = str(assessment_id)
            for k in [k for k in _CACHE if k[0] == aid]:
                _CACHE.pop(k, None)
