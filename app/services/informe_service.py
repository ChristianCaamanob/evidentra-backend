"""
E1 - Ensamblado del contrato `datos` para el informe individual (Nivel Evalys).

Arma, de forma DETERMINISTA (sin IA), la estructura `datos` que consume el render del
informe (E3): identidad, desempeno, distribucion de curso, agregacion por RA/Bloom,
mapa pregunta a pregunta, brechas, fortalezas, un plan base y metadata.

Gobernanza:
  - G2 (seudonimizacion): este ensamblado NO llama a la IA. La retroalimentacion rica
    con modelo (E2) recibira una vista seudonimizada; aqui metadata.ia_utilizada=False.
  - G1 (la IA no decide): la nota proviene de la correccion determinista existente
    (result_service). El informe la muestra; no la genera un modelo.
  - G6 (propositiva): el lenguaje describe el logro del estudiante, no juzga el programa.
"""
from __future__ import annotations

from app.services import result_service
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository
from app.models.assessment import Assessment
from app.models.course import Course
from app.models.curriculo import LearningOutcome

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()

CONTRATO_VERSION = "1.0"
# Umbrales para clasificar desempeno por agrupacion (RA / unidad / Bloom).
UMBRAL_BRECHA = 60.0      # < 60% de logro en una agrupacion -> foco de consolidacion
UMBRAL_FORTALEZA = 80.0   # >= 80% -> fortaleza demostrada


def _nivel_evalys(percentage: float) -> str:
    """Etiqueta cualitativa propositiva del nivel de logro global."""
    if percentage >= 85:
        return "consolidado"
    if percentage >= 70:
        return "en_desarrollo_avanzado"
    if percentage >= 55:
        return "en_desarrollo"
    return "inicial"


def _clasifica_preguntas(base: dict) -> dict:
    """Devuelve conjuntos por estado a partir del resultado determinista."""
    incorrectas = {d["question"]: d for d in (base.get("incorrect_questions") or [])}
    return {
        "correctas": set(base.get("correct_questions") or []),
        "incorrectas": incorrectas,
        "omitidas": set(base.get("omitted_questions") or []),
        "anuladas": set(base.get("annulled_questions") or []),
    }


def _agrega(rows: list[dict], key: str) -> list[dict]:
    """Agrupa preguntas efectivas por una clave (ra / bloom / unidad) y calcula logro."""
    grupos: dict[str, dict] = {}
    for r in rows:
        if r["estado"] == "anulada":
            continue
        k = r.get(key) or "sin_clasificar"
        g = grupos.setdefault(k, {"clave": k, "total": 0, "correctas": 0})
        g["total"] += 1
        if r["estado"] == "correcta":
            g["correctas"] += 1
    salida = []
    for g in grupos.values():
        pct = round(g["correctas"] / g["total"] * 100, 1) if g["total"] else 0.0
        salida.append({**g, "porcentaje": pct})
    salida.sort(key=lambda x: (x["porcentaje"], x["clave"]))
    return salida


def build_datos(db, scan_id) -> dict:
    """Ensambla y devuelve el contrato `datos` completo para un escaneo corregido."""
    base = result_service.get_result(db, scan_id)  # valida estado; puede levantar 409/404

    scan = scan_repo.get(db, scan_id)
    assessment = db.query(Assessment).filter(Assessment.id == scan.assessment_id).first()
    course = (
        db.query(Course).filter(Course.id == assessment.course_id).first()
        if assessment else None
    )
    answer_key = answer_key_repo.get_by_assessment_id(db, scan.assessment_id)
    version = base.get("version") or "A"
    items = {
        it.question_number: it
        for it in (answer_key.items if answer_key else [])
        if (it.version or "").upper() == version.upper()
    }

    # Texto literal del RA (C2), para mostrar el resultado de aprendizaje sin reescribirlo.
    ra_text: dict[str, str] = {}
    if course:
        for lo in db.query(LearningOutcome).filter(LearningOutcome.course_id == course.id).all():
            ra_text[lo.code] = lo.text

    clas = _clasifica_preguntas(base)

    # ── mapa_preguntas: una fila por pregunta con su vinculo curricular ──
    mapa_preguntas: list[dict] = []
    for q in sorted(items):
        it = items[q]
        if q in clas["anuladas"]:
            estado, tu = "anulada", None
        elif q in clas["correctas"]:
            estado, tu = "correcta", it.correct_answer
        elif q in clas["incorrectas"]:
            estado, tu = "incorrecta", clas["incorrectas"][q].get("student")
        else:
            estado, tu = "omitida", None
        mapa_preguntas.append({
            "numero": q,
            "estado": estado,
            "tu_respuesta": tu,
            "respuesta_correcta": it.correct_answer,
            "peso": float(it.weight),
            "ra": it.learning_outcome_id,
            "ra_texto": ra_text.get(it.learning_outcome_id),
            "bloom": it.bloom_level,
            "unidad": it.unidad,
        })

    por_ra = _agrega(mapa_preguntas, "ra")
    por_bloom = _agrega(mapa_preguntas, "bloom")
    por_unidad = _agrega(mapa_preguntas, "unidad")

    # ── brechas / fortalezas: focos de consolidacion y logros demostrados ──
    def _detalle(g: dict, tipo: str) -> dict:
        clave = g["clave"]
        return {
            "ra": clave if clave != "sin_clasificar" else None,
            "ra_texto": ra_text.get(clave),
            "porcentaje": g["porcentaje"],
            "correctas": g["correctas"],
            "total": g["total"],
            "que_muestra": (
                f"Lograste {g['correctas']} de {g['total']} preguntas asociadas a {clave}."
            ),
        }

    brechas = [_detalle(g, "brecha") for g in por_ra if g["porcentaje"] < UMBRAL_BRECHA]
    fortalezas = [_detalle(g, "fortaleza") for g in por_ra if g["porcentaje"] >= UMBRAL_FORTALEZA]

    # ── plan_consolidacion: esqueleto determinista; E2 lo enriquece con IA ──
    plan_consolidacion = {
        "enfoque": [b["ra"] for b in brechas if b["ra"]],
        "detalle": [],  # los pasos ricos (sesiones, bibliografia) llegan en E2
        "nota": "Plan base generado sin IA; se enriquece con la generacion cualitativa (E2).",
    }

    # ── mensaje personalizado: plantilla propositiva, sin IA ──
    nivel = _nivel_evalys(base.get("percentage", 0.0))
    mensaje_personalizado = (
        f"Tu nivel de logro en esta evaluacion es {base.get('percentage', 0.0)}% "
        f"(nivel {nivel}). El informe destaca lo que ya dominas y propone donde seguir "
        f"avanzando, resultado de aprendizaje por resultado de aprendizaje."
    )

    datos = {
        "estudiante": {
            "nombre": base.get("student_name"),
            "identificador": base.get("student_identifier"),
            "curso": course.name if course else None,
        },
        "evaluacion": {
            "nombre": assessment.name if assessment else None,
            "curso": course.name if course else None,
            "codigo_curso": course.code if course else None,
            "version": version,
            "escala": base.get("grading_scale"),
            "n_preguntas": base.get("n_total"),
        },
        "desempeno": {
            "nota": base.get("final_grade"),
            "etiqueta_nota": base.get("grade_label"),
            "porcentaje": base.get("percentage"),
            "nivel": nivel,
            "estado": base.get("pass_status"),
            "correctas": base.get("n_correct"),
            "incorrectas": base.get("n_incorrect"),
            "omitidas": base.get("n_omitted"),
            "anuladas": base.get("n_annulled"),
            "percentil": base.get("percentile"),
        },
        "distribucion_curso": _distribucion_curso(db, scan.assessment_id, base),
        "dimensiones_bloom": por_bloom,
        "mapa_preguntas": mapa_preguntas,
        "brechas": brechas,
        "fortalezas": fortalezas,
        "plan_consolidacion": plan_consolidacion,
        "mensaje_personalizado": mensaje_personalizado,
        "metadata": {
            "contrato_version": CONTRATO_VERSION,
            "generado_por": "informe_service.build_datos",
            "ia_utilizada": False,
            "seudonimizado": True,
            "por_ra": por_ra,
            "por_unidad": por_unidad,
            "nivel_evalys": nivel,
        },
    }
    return datos


def _distribucion_curso(db, assessment_id, base: dict) -> dict:
    """Distribucion del curso y posicion del estudiante (agregado, sin identificadores)."""
    todos = result_service.list_results_for_assessment(db, assessment_id)
    porcentajes = sorted(
        r.get("percentage", 0.0) for r in todos.get("results", [])
        if r.get("percentage") is not None
    )
    n = len(porcentajes)
    promedio = round(sum(porcentajes) / n, 1) if n else None
    mediana = porcentajes[n // 2] if n else None
    mi_pct = base.get("percentage", 0.0)
    # Percentil: proporcion del curso con desempeno <= al del estudiante.
    menores_o_igual = sum(1 for p in porcentajes if p <= mi_pct)
    percentil = round(menores_o_igual / n * 100) if n else None
    return {
        "n_estudiantes": n,
        "promedio": promedio,
        "mediana": mediana,
        "tu_porcentaje": mi_pct,
        "tu_percentil": percentil,
        "histograma": porcentajes,
    }
