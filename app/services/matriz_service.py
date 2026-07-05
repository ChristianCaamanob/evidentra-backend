"""
Pegamento del cableado Investigador: arma, desde la base, la matriz persona x item que
consumen los motores psicometricos (I1 Rasch, I7 dimensionalidad, I2 DIF, I8 invarianza).

Es la unica pieza nueva de datos del cableado: reune los escaneos validados de una
evaluacion y su pauta, y produce una matriz 0/1 SEUDONIMIZADA (G2). La correccion se
calcula por la version detectada de cada escaneo, de modo que items de distintas versiones
se agrupan correctamente por numero de pregunta.
"""
from __future__ import annotations

import hashlib

import numpy as np

from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()


def _pseudo(valor) -> str:
    """Seudonimo estable de un id (G2): sin identidad, reproducible."""
    return "e:" + hashlib.sha256(str(valor).encode("utf-8")).hexdigest()[:10]


def cargar_matriz_respuestas(db, assessment_id, min_personas: int = 3,
                             min_items: int = 3) -> dict:
    """
    Devuelve la matriz 0/1 (persona x item) de una evaluacion, mas metadatos:

        {X, personas[seudonimos], items[nums de pregunta], tags{num->{ra,bloom,unidad}},
         n_personas, n_items, n_omitidas_pct}

    Escanea todos los escaneos NO en revision; la correccion usa la version de cada uno.
    Los items anulados se excluyen. Omitidas -> 0 (como en el analisis de curso).
    """
    answer_key = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no esta validada; no hay datos para el analisis.")

    # pauta por version: {version -> {num_pregunta -> item}}
    por_version: dict[str, dict[int, object]] = {}
    tags: dict[int, dict] = {}
    for it in answer_key.items:
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
        tags.setdefault(it.question_number, {
            "ra": it.learning_outcome_id, "bloom": it.bloom_level, "unidad": it.unidad})

    anulados = {it.question_number for it in answer_key.items if it.is_annulled}
    items = sorted({it.question_number for it in answer_key.items} - anulados)
    if not items:
        raise conflict("Todos los items estan anulados; no hay que analizar.")

    scans = scan_repo.list_by_assessment(db, assessment_id)
    filas, personas = [], []
    n_celdas = n_omit = 0
    for scan in scans:
        if getattr(scan, "requires_review", False):
            continue
        ocr = scan.raw_ocr_payload_json or {}
        respuestas = ocr.get("answers", [])
        ver = (scan.detected_version or "A").upper()
        clave = por_version.get(ver)
        if not clave:
            continue
        fila = []
        for q in items:
            item = clave.get(q)
            if item is None or item.is_annulled:
                fila.append(np.nan)
                continue
            idx = q - 1
            elegida = respuestas[idx] if idx < len(respuestas) else None
            n_celdas += 1
            if elegida is None:
                n_omit += 1
                fila.append(0.0)
            else:
                fila.append(1.0 if str(elegida).upper() == str(item.correct_answer).upper() else 0.0)
        filas.append(fila)
        personas.append(_pseudo(scan.id))

    X = np.array(filas, dtype=float) if filas else np.empty((0, len(items)))
    if X.shape[0] < min_personas or X.shape[1] < min_items:
        raise conflict(
            f"Datos insuficientes para el analisis (se requieren >= {min_personas} personas "
            f"y >= {min_items} items; hay {X.shape[0]} personas y {X.shape[1]} items validos).")

    return {
        "X": X, "personas": personas, "items": items, "tags": tags,
        "n_personas": int(X.shape[0]), "n_items": int(X.shape[1]),
        "omitidas_pct": round(n_omit / n_celdas * 100, 1) if n_celdas else 0.0,
    }


def cargar_registros_validacion(db, assessment_id, min_registros: int = 3) -> list[dict]:
    """
    Lee los RegistroValidacion persistidos (F3) de una evaluacion y los devuelve en el
    formato que consumen R, MFRM y F4. El 'alumno' sale seudonimizado del respuesta_ref
    (formato 'e:<hash>#<criterio>'), nunca de un identificador real (G2).
    """
    from app.models.validacion import RegistroValidacion

    filas = (db.query(RegistroValidacion)
             .filter(RegistroValidacion.assessment_id == str(assessment_id))
             .all())
    if len(filas) < min_registros:
        raise conflict(
            f"Aun no hay suficientes validaciones docentes para esta evaluacion "
            f"(hay {len(filas)}; se requieren >= {min_registros}). Corre F3 primero.")
    out = []
    for r in filas:
        alumno = str(r.respuesta_ref).split("#")[0]
        out.append({"alumno": alumno, "criterio": r.criterio,
                    "nivel_ia": r.nivel_ia, "confianza_ia": r.confianza_ia,
                    "nivel_docente": r.nivel_docente, "accion": r.accion,
                    "comentario": r.comentario, "respuesta_ref": r.respuesta_ref})
    return out
