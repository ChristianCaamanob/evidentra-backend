"""
P3 · Ficha del estudiante: BRECHAS por Resultado de Aprendizaje (RA), a través del curso.

Cruza la evidencia real del estudiante (sus escaneos/pruebas, ya ligados a su ficha por RUT —
ver en_vivo _persistir_scans + matriz_service.seleccionar_scans) contra la Tabla de
Especificaciones del curso (LearningOutcome, C2), agregando el logro por RA a lo largo de
TODAS las evaluaciones y diferenciándolo por tipo de prueba. Es la capa consultable que el
profesor necesita para constatar brechas de conocimiento (norte del producto).

Gobernanza: por ahora agrega los ítems de ALTERNATIVAS (auto-corregidos vs pauta validada).
Los ítems de desarrollo (rúbrica) usan el nivel VALIDADO por el docente (G1) y se integrarán
por-RA en un corte siguiente; aquí se declara la cobertura de forma honesta. No altera notas
(G1); agregado por estudiante para uso pedagógico del docente.
"""
from __future__ import annotations

from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.services import matriz_service

answer_key_repo = AnswerKeyRepository()


def _nivel(logro_pct: float) -> str:
    if logro_pct >= 70:
        return "Logrado"
    if logro_pct >= 50:
        return "En desarrollo"
    return "Inicial"


def _nombre(st) -> str:
    ap = " ".join(x for x in (st.apellido_paterno, st.apellido_materno) if x).strip()
    n = (st.nombres or "").strip()
    return (ap + (", " + n if n else "")).strip() or (st.rut or "Estudiante")


def brechas_estudiante(db, course_id, rut: str, umbral_brecha: float = 60.0,
                       origen: str | None = None) -> dict:
    """Logro por RA de un estudiante a lo largo del curso + brechas (RA bajo el umbral).

    `origen`: None = toda la evidencia (deduplicada por alumno); 'omr' | 'en_vivo' para acotar
    a un tipo de instrumento. `umbral_brecha`: % de logro bajo el cual el RA se marca como brecha.
    """
    from app.models.course import Course
    from app.models.student import Student
    from app.models.assessment import Assessment
    from app.models.curriculo import LearningOutcome

    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Curso no encontrado.")
    rut = (rut or "").strip()
    st = (db.query(Student)
          .filter(Student.course_id == course_id, Student.rut == rut).first())
    if st is None:
        raise not_found("Estudiante no encontrado en el curso.")

    # Tabla de Especificaciones: RA del curso (texto literal preservado, C2).
    ras = (db.query(LearningOutcome).filter(LearningOutcome.course_id == course_id)
           .order_by(LearningOutcome.orden).all())
    ra_meta = {r.code: {"code": r.code, "texto": r.text, "unidad": r.unidad} for r in ras}

    # Acumuladores por RA (ítems enfrentados / aciertos), con desglose por tipo de prueba.
    acc: dict[str, dict] = {}
    pruebas: list[dict] = []

    for a in db.query(Assessment).filter(Assessment.course_id == course_id).all():
        ak = answer_key_repo.get_by_assessment_id(db, a.id)
        if not ak or not ak.is_valid:
            continue  # sin pauta validada no hay corrección de alternativas
        por_version: dict[str, dict[int, object]] = {}
        ra_por_q: dict[int, str] = {}
        for it in ak.items:
            if it.is_annulled:
                continue
            por_version.setdefault(it.version.upper(), {})[it.question_number] = it
            if it.learning_outcome_id:
                ra_por_q[it.question_number] = it.learning_outcome_id  # código del RA (C1)
        # Escaneo del alumno para esta evaluación (deduplicado por alumno real; filtrable por origen).
        mios = [sc for sc in matriz_service.seleccionar_scans(db, a.id, origen)["scans"]
                if (sc.student_identifier or "").strip() == rut]
        if not mios:
            continue  # el estudiante no rindió (o no está ligado) esta evaluación
        scan = mios[0]
        clave = por_version.get((scan.detected_version or "A").upper())
        if not clave:
            continue
        respuestas = (scan.raw_ocr_payload_json or {}).get("answers", [])
        tipo = a.tipo or "otro"
        ev_p = ok_p = 0
        for q, it in clave.items():
            elegida = respuestas[q - 1] if (q - 1) < len(respuestas) else None
            ok = 1.0 if (elegida is not None and
                         str(elegida).upper() == str(it.correct_answer).upper()) else 0.0
            ev_p += 1; ok_p += ok
            racode = ra_por_q.get(q)
            if racode:
                d = acc.setdefault(racode, {"ev": 0, "ok": 0.0, "por_tipo": {}})
                d["ev"] += 1; d["ok"] += ok
                t = d["por_tipo"].setdefault(tipo, {"ev": 0, "ok": 0.0})
                t["ev"] += 1; t["ok"] += ok
        pruebas.append({
            "assessment_id": str(a.id), "nombre": a.name, "tipo": tipo,
            "modalidad": getattr(a, "modalidad", None),
            "origen": matriz_service._origen_de(scan),
            "items_evaluados": ev_p,
            "logro_pct": round(ok_p / ev_p * 100, 1) if ev_p else None,
        })

    # Cruce con la Tabla de Especificaciones: un renglón por RA del programa (evaluado o no).
    por_ra = []
    for code, meta in ra_meta.items():
        d = acc.get(code)
        if d and d["ev"]:
            logro = round(d["ok"] / d["ev"] * 100, 1)
            por_tipo = {t: round(v["ok"] / v["ev"] * 100, 1)
                        for t, v in d["por_tipo"].items() if v["ev"]}
            por_ra.append({**meta, "items_evaluados": d["ev"], "logro_pct": logro,
                           "nivel": _nivel(logro), "brecha": logro < umbral_brecha,
                           "por_tipo": por_tipo})
        else:
            por_ra.append({**meta, "items_evaluados": 0, "logro_pct": None,
                           "nivel": "sin evaluar", "brecha": None, "por_tipo": {}})

    # RA etiquetados en ítems pero AUSENTES de la Tabla (trazabilidad honesta del etiquetado C1).
    fuera_de_tabla = sorted(c for c in acc if c not in ra_meta)
    brechas = [r for r in por_ra if r["brecha"]]
    sin_eval = [r for r in por_ra if r["items_evaluados"] == 0]

    return {
        "estudiante": {"rut": st.rut, "nombre": _nombre(st)},
        "curso": {"id": str(course.id), "nombre": course.name, "codigo": course.code},
        "umbral_brecha": umbral_brecha,
        "origen": origen or "todos",
        "por_ra": por_ra,
        "pruebas": pruebas,
        "brechas": [{"code": r["code"], "texto": r["texto"], "logro_pct": r["logro_pct"],
                     "por_tipo": r["por_tipo"]} for r in brechas],
        "resumen": {
            "n_ra_programa": len(ra_meta),
            "n_ra_evaluados": sum(1 for r in por_ra if r["items_evaluados"]),
            "n_brechas": len(brechas),
            "ra_sin_evaluar": [r["code"] for r in sin_eval],
            "n_pruebas": len(pruebas),
        },
        "ra_fuera_de_tabla": fuera_de_tabla,
        "gobernanza": "Agrega ítems de alternativas (auto-corregidos vs pauta validada), "
                      "deduplicados por estudiante. No altera notas (G1); uso pedagógico del docente. "
                      "El desarrollo por-RA se integrará en un corte siguiente.",
    }
