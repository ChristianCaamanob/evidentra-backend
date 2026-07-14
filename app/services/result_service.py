from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session
from app.core.errors import conflict, not_found
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository
from app.models.course import Course

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()

# ══════════════════════════════════════════════════════
#  ESCALAS DE CALIFICACIÓN INTERNACIONALES
# ══════════════════════════════════════════════════════

# El registro es la ÚNICA fuente de verdad: cada escala describe su metadata Y su
# regla de conversion ("compute"). El invariante es SIEMPRE el % de logro; la
# exigencia y la escala son solo renderizado (ver conversor "Escala universal").
#
#   compute.kind = "linear"  -> nota interpolada por tramos desde la exigencia.
#       better="high": la nota SUBE con el logro; points = (piso, aprueba, techo).
#       better="low" : la nota BAJA con el logro (Alemania); points = (optimo, aprueba, reprueba).
#   compute.kind = "band"    -> letra por bandas nacionales fijas (referencia).
#   compute.kind = "percentage" -> porcentaje directo.
GRADING_SCALES = {
    # ── Escalas lineales: la aprobacion se mueve con la exigencia ──────────────
    "chile_1_7": {
        "name": "Escala chilena 1.0 – 7.0", "country": "Chile", "region": "CL",
        "type": "numeric", "min": 1.0, "max": 7.0, "passing": 4.0,
        "compute": {"kind": "linear", "better": "high", "points": (1.0, 4.0, 7.0), "decimals": 1},
        "description": "Escala nacional chilena. Nota minima de aprobacion 4.0.",
    },
    "mexico_10": {
        "name": "Escala mexicana 0 – 10", "country": "México", "region": "MX",
        "type": "numeric", "min": 0.0, "max": 10.0, "passing": 6.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 6.0, 10.0), "decimals": 1},
        "description": "Escala 0-10 usada en Mexico. Aprobacion 6.0.",
    },
    "colombia_5": {
        "name": "Escala colombiana 0 – 5", "country": "Colombia", "region": "CO",
        "type": "numeric", "min": 0.0, "max": 5.0, "passing": 3.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 3.0, 5.0), "decimals": 1},
        "description": "Escala 0-5 usada en Colombia. Aprobacion 3.0.",
    },
    "brasil_10": {
        "name": "Escala brasileña 0 – 10", "country": "Brasil", "region": "BR",
        "type": "numeric", "min": 0.0, "max": 10.0, "passing": 6.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 6.0, 10.0), "decimals": 1},
        "description": "Escala 0-10 usada en Brasil. Aprobacion habitual 6.0.",
    },
    "espana_10": {
        "name": "Escala española 0 – 10", "country": "España", "region": "ES",
        "type": "numeric", "min": 0.0, "max": 10.0, "passing": 5.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 5.0, 10.0), "decimals": 1},
        "description": "Escala 0-10 usada en Espana. Aprobacion 5.0.",
    },
    "francia_20": {
        "name": "Escala francesa 0 – 20", "country": "Francia", "region": "FR",
        "type": "numeric", "min": 0.0, "max": 20.0, "passing": 10.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 10.0, 20.0), "decimals": 1},
        "description": "Echelle 0-20 usada en Francia. Aprobacion 10.0.",
    },
    "alemania_5": {
        "name": "Escala alemana 1 – 5 (invertida)", "country": "Alemania", "region": "DE",
        "type": "numeric", "min": 1.0, "max": 5.0, "passing": 4.0,
        # 1,0 es lo optimo; 4,0 es la peor nota que aprueba; 5,0 reprueba.
        "compute": {"kind": "linear", "better": "low", "points": (1.0, 4.0, 5.0), "decimals": 1},
        "description": "Escala 1-5 alemana. 1,0 optimo, 4,0 aprueba, 5,0 reprueba.",
    },
    "europe_10": {
        "name": "Escala europea 0 – 10", "country": "Europa (general)", "region": "EU",
        "type": "numeric", "min": 0.0, "max": 10.0, "passing": 5.0,
        "compute": {"kind": "linear", "better": "high", "points": (0.0, 5.0, 10.0), "decimals": 1},
        "description": "Escala 0-10 generica europea. Aprobacion 5.0.",
    },
    "percentage": {
        "name": "Porcentaje 0 – 100%", "country": "Universal", "region": "UN",
        "type": "numeric", "min": 0.0, "max": 100.0, "passing": 60.0,
        "compute": {"kind": "percentage"},
        "description": "Porcentaje directo sin conversion.",
    },
    # ── Sistemas de letras: bandas nacionales fijas (referencia) ───────────────
    "usa_letter": {
        "name": "Escala estadounidense A–F", "country": "Estados Unidos", "region": "US",
        "type": "letter",
        "compute": {"kind": "band", "bands": [
            (97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
            (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (60, "D"), (0, "F")],
            "passing_cut": 60},
        "description": "A+ A A- B+ B B- C+ C C- D+ D F (bandas fijas).",
    },
    "uk_honours": {
        "name": "Clasificación Honours UK", "country": "Reino Unido", "region": "GB",
        "type": "classification",
        "compute": {"kind": "band", "bands": [
            (70, "First Class"), (60, "Upper Second (2:1)"), (50, "Lower Second (2:2)"),
            (40, "Third Class"), (0, "Fail")],
            "passing_cut": 40},
        "description": "First / 2:1 / 2:2 / Third / Fail (bandas fijas).",
    },
    "ects": {
        "name": "Escala europea ECTS A–F", "country": "Europa (ECTS)", "region": "EU",
        "type": "letter",
        "compute": {"kind": "band", "bands": [
            (90, "A"), (80, "B"), (70, "C"), (60, "D"), (50, "E"), (0, "F")],
            "passing_cut": 50},
        "description": "A B C D E F (bandas de referencia ECTS).",
    },
    "ib_7": {
        "name": "Bachillerato Internacional 1 – 7", "country": "Internacional IB", "region": "IB",
        "type": "letter",
        "compute": {"kind": "band", "bands": [
            (97, "7"), (88, "6"), (78, "5"), (67, "4"), (56, "3"), (44, "2"), (0, "1")],
            "passing_cut": 67},
        "description": "Escala IB por bandas. Aprobacion desde 4.",
    },
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _redondear(v: float, dec: int = 1) -> float:
    """Redondeo estandar medio-arriba (3,95 -> 4,0), no bancario. Predecible en el borde."""
    cuant = Decimal(1).scaleb(-dec)                 # 10^-dec, p.ej. 0.1 con dec=1
    return float(Decimal(str(v)).quantize(cuant, rounding=ROUND_HALF_UP))


def grade_linear(percentage: float, spec: dict, passing_threshold: float):
    """Nota lineal de dos tramos, generalizada desde la exigencia.

    Con better='high' la nota interpola piso->aprueba->techo a medida que sube el
    logro; con better='low' (Alemania) baja optimo<-aprueba<-reprueba. La misma
    formula que usa Chile (piso=1, aprueba=4, techo=7): un unico motor para todas.

    Gradiente continuo redondeado a 1 decimal (config. por escala). La aprobacion
    sigue a la NOTA redondeada (un 4,0 aprueba), nunca al % crudo: asi jamas aparece
    "nota 4,0 pero reprobado". Coincide con la semantica historica de Chile.
    """
    a, passing, b = spec["points"]                 # a=piso/optimo, passing=aprueba, b=techo/reprueba
    dec = spec.get("decimals", 1)
    p = passing_threshold / 100.0
    frac = percentage / 100.0
    en_tramo_superior = percentage >= passing_threshold   # solo elige el tramo de la formula
    top_denom = (1.0 - p) or 1e-9
    bot_denom = p or 1e-9
    if spec.get("better", "high") == "high":
        grade = (passing + (frac - p) / top_denom * (b - passing)) if en_tramo_superior \
            else (a + frac / bot_denom * (passing - a))
        grade = _redondear(_clamp(grade, a, b), dec)
        passed = grade >= passing
    else:  # 'low' (invertida, Alemania): mejor logro -> nota mas baja
        grade = (passing - (frac - p) / top_denom * (passing - a)) if en_tramo_superior \
            else (passing + (1.0 - frac / bot_denom) * (b - passing))
        grade = _redondear(_clamp(grade, a, b), dec)
        passed = grade <= passing                  # invertida: mas bajo es mejor
    return grade, f"{grade:.{dec}f}", passed


def grade_band(percentage: float, spec: dict, passing_threshold: float, movil: bool = False):
    """Letra por bandas nacionales.

    Por defecto las bandas son FIJAS (estandar: una 'A' de EEUU es >=90% siempre) y la
    aprobacion es alcanzar la banda que aprueba (passing_cut). Con `movil=True` (opt-in del
    docente) se aplica la exigencia como en las escalas numericas: el % del alumno se
    re-escala en dos tramos anclados en passing_cut, de modo que la exigencia elegida cae
    justo en la banda de aprobacion y el resto se estira/comprime. Curva la evaluacion.
    """
    p = percentage
    cut = spec.get("passing_cut")
    if movil and cut is not None:
        E = passing_threshold
        if p >= E:
            top = (100.0 - E) or 1e-9
            p = cut + (p - E) / top * (100.0 - cut)
        else:
            bot = E or 1e-9
            p = p / bot * cut
        p = max(0.0, min(100.0, p))
    label = spec["bands"][-1][1]
    for c, lab in spec["bands"]:
        if p >= c:
            label = lab
            break
    # Aprueba si alcanza la banda de aprobacion (passing_cut sobre el % efectivo).
    aprob = (p >= cut) if cut is not None else (percentage >= passing_threshold)
    return percentage, label, aprob


# Exigencia (%) por defecto por escala: el % de logro que cae en la nota de aprobacion,
# segun la convencion mas habitual de cada pais. El docente puede ajustarla por evaluacion.
EXIGENCIA_DEFAULT = {
    "chile_1_7": 60,    # convencion chilena (50-70; 60 lo mas comun)
    "mexico_10": 60,    # aprueba 6/10
    "colombia_5": 60,   # aprueba 3.0/5
    "brasil_10": 60,    # aprueba 6/10 (habitual)
    "espana_10": 50,    # aprobado 5/10
    "francia_20": 50,   # moyenne 10/20
    "alemania_5": 50,   # 4,0 aprueba (escala invertida)
    "europe_10": 50,    # generica europea 5/10
    "ects": 50,         # bandas de referencia ECTS
    "usa_letter": 60,   # D a 60%
    "uk_honours": 40,   # pass a 40%
    "ib_7": 67,         # nivel 4 IB (banda de aprobación real)
    "percentage": 60,   # directo (elige el docente)
}

# Orden de presentacion (los mas representativos primero) para selectores multinacionales.
ESCALAS_ORDEN = [
    "chile_1_7", "mexico_10", "colombia_5", "brasil_10", "espana_10",
    "francia_20", "alemania_5", "europe_10", "ects", "usa_letter",
    "uk_honours", "ib_7", "percentage",
]


def listar_escalas() -> dict:
    """Metadata publica de las escalas (para /assessments y el conversor), con la
    exigencia (%) por defecto de cada pais y un orden de presentacion sugerido."""
    def _meta(k, v):
        d = {kk: vv for kk, vv in v.items() if kk != "compute"}
        d["exigencia_default"] = EXIGENCIA_DEFAULT.get(k, 60)
        d["orden"] = ESCALAS_ORDEN.index(k) if k in ESCALAS_ORDEN else 99
        return d
    return {k: _meta(k, v) for k, v in GRADING_SCALES.items()}


def convertir_multiescala(percentage: float, passing_threshold: float = 60.0,
                          escalas: list | None = None) -> dict:
    """Traduce un MISMO % de logro a varias escalas a la vez (invariante -> renders)."""
    claves = escalas or list(GRADING_SCALES.keys())
    salida = {}
    for k in claves:
        g, label, passed = calculate_grade(percentage, k, passing_threshold)
        salida[k] = {"grade": g, "label": label, "passed": passed}
    return salida


def calculate_grade(percentage: float, scale: str, passing_threshold: float = 60.0,
                    banda_movil: bool = False):
    """Calcula nota segun la escala del registro. Retorna (grade_value, grade_label, passed).

    Un solo motor: el % de logro es el invariante; la escala solo decide como se
    renderiza y la exigencia (passing_threshold) donde cae la linea de aprobacion.
    `banda_movil` (opt-in por evaluacion) solo afecta a las escalas de bandas: mueve los
    cortes con la exigencia en vez de dejarlos fijos.
    """
    spec = GRADING_SCALES.get(scale)
    if spec is None:                                   # fallback: escala chilena
        spec = GRADING_SCALES["chile_1_7"]
    compute = spec["compute"]
    kind = compute["kind"]

    if kind == "linear":
        return grade_linear(percentage, compute, passing_threshold)
    if kind == "band":
        return grade_band(percentage, compute, passing_threshold, movil=banda_movil)
    # percentage
    return percentage, f"{percentage}%", percentage >= passing_threshold


# Mantener compatibilidad con código existente
def _grade_chile(percentage: float, passing_threshold: float = 60.0) -> float:
    grade, _, _ = calculate_grade(percentage, "chile_1_7", passing_threshold)
    return grade


def get_result(db: Session, scan_id):
    scan = scan_repo.get(db, scan_id)
    if not scan:
        raise not_found("Escaneo no encontrado.")
    if scan.requires_review:
        raise conflict("El escaneo aún requiere revisión.")

    answer_key = answer_key_repo.get_by_assessment_id(db, scan.assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no está validada.")

    # Obtener respuestas del alumno desde el OCR payload
    ocr = scan.raw_ocr_payload_json or {}
    student_answers = ocr.get("answers", [])
    version = scan.detected_version or "A"

    # Obtener pauta de la versión detectada
    key_items = {
        item.question_number: item
        for item in answer_key.items
        if item.version.upper() == version.upper()
    }

    if not key_items:
        raise conflict(f"No hay pauta validada para versión {version}.")

    n_total = len(key_items)
    correct = []
    incorrect = []
    annulled = []
    omitted = []

    for q_num, item in sorted(key_items.items()):
        idx = q_num - 1
        student_ans = student_answers[idx] if idx < len(student_answers) else None
        if item.is_annulled:
            annulled.append(q_num)
            continue
        if student_ans is None:
            omitted.append(q_num)
        elif student_ans.upper() == item.correct_answer.upper():
            correct.append(q_num)
        else:
            incorrect.append({"question": q_num, "student": student_ans, "correct": item.correct_answer})

    n_correct = len(correct)
    n_incorrect = len(incorrect)
    n_omitted = len(omitted)
    n_annulled = len(annulled)
    n_effective = n_total - n_annulled

    raw_score = sum(
        item.weight for q_num, item in key_items.items()
        if q_num in correct
    )
    total_weight = sum(item.weight for q_num, item in key_items.items() if q_num not in annulled)
    percentage = round((raw_score / total_weight * 100) if total_weight > 0 else 0, 1)

    # Obtener exigencia del curso
    from app.models.assessment import Assessment
    assessment = db.query(Assessment).filter(Assessment.id == scan.assessment_id).first()
    course = db.query(Course).filter(Course.id == assessment.course_id).first() if assessment else None
    # Prioridad: escala del assessment > escala del curso > default
    grading_scale = getattr(assessment, 'grading_scale', None) or (course.grading_scale if course else None) or 'chile_1_7'
    passing_threshold = getattr(assessment, 'passing_threshold', None) or (course.passing_threshold if course else None) or 60.0

    grade_value, grade_label, passed = calculate_grade(
        percentage, grading_scale, passing_threshold,
        banda_movil=bool(getattr(assessment, "bandas_moviles", False)))
    final_grade = grade_value
    pass_status = "approved" if passed else "failed"

    # Match RUT con nómina
    student_name = None
    student_data = None
    if scan.student_identifier and scan.student_identifier != "desconocido":
        from app.models.student import Student
        student = db.query(Student).filter(
            Student.rut == scan.student_identifier,
            Student.course_id == assessment.course_id if assessment else True
        ).first()
        if student:
            student_name = f"{student.apellido_paterno} {student.apellido_materno} {student.nombres}".strip()
            student_data = {
                "rut": student.rut,
                "apellido_paterno": student.apellido_paterno,
                "apellido_materno": student.apellido_materno,
                "nombres": student.nombres,
            }

    return {
        "scan_id": str(scan.id),
        "student": student_data,
        "student_name": student_name or scan.student_identifier,
        "student_identifier": scan.student_identifier,
        "version": version,
        "n_total": n_total,
        "n_effective": n_effective,
        "n_correct": n_correct,
        "n_incorrect": n_incorrect,
        "n_omitted": n_omitted,
        "n_annulled": n_annulled,
        "raw_score": round(raw_score, 2),
        "percentage": percentage,
        "passing_threshold": passing_threshold,
        "final_grade": final_grade,
        "grade_label": grade_label,
        "grading_scale": grading_scale,
        "pass_status": pass_status,
        "correct_questions": correct,
        "incorrect_questions": incorrect,
        "omitted_questions": omitted,
        "annulled_questions": annulled,
    }


def list_results_for_assessment(db: Session, assessment_id):
    scans = scan_repo.list_by_assessment(db, assessment_id)
    results = []
    skipped = 0
    for scan in scans:
        try:
            results.append(get_result(db, scan.id))
        except Exception:
            skipped += 1
    return {"assessment_id": str(assessment_id), "count": len(results), "skipped": skipped, "results": results}
