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


def _dev_validaciones(db, assessment_id, student_id, scan_id=None):
    """Niveles de desarrollo VALIDADOS por el docente (G1) para el estudiante en una evaluación:
    devuelve (individual, grupal). Individual = por seudónimo del escaneo y/o del estudiante;
    grupal = por seudónimo del grupo del estudiante (criterios de ámbito grupal)."""
    from app.models.validacion import RegistroValidacion
    from app.models.grupo import Grupo
    from app.services.matriz_service import _pseudo
    val: dict[str, dict[str, str]] = {}
    for r in db.query(RegistroValidacion).filter(
            RegistroValidacion.assessment_id == str(assessment_id)).all():
        val.setdefault(str(r.respuesta_ref).split("#")[0], {})[r.criterio] = r.nivel_docente
    sv: dict[str, str] = {}
    for p in (([_pseudo(scan_id)] if scan_id else []) + [_pseudo(student_id)]):
        sv.update(val.get(p, {}))
    gp = None
    for g in db.query(Grupo).filter(Grupo.assessment_id == str(assessment_id)).all():
        if any(str(getattr(ig, "student_id", "")) == str(student_id) for ig in g.integrantes):
            gp = _pseudo(g.id); break
    return sv, (val.get(gp, {}) if gp else {})


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
                       origen: str | None = None, assessment_id=None) -> dict:
    """Logro por RA de un estudiante a lo largo del curso + brechas (RA bajo el umbral).
    `assessment_id`: si se indica, acota el cálculo a ESA evaluación (logro por RA de la prueba).

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

    # Tabla de Especificaciones: RA del curso (texto literal preservado, C2). Si el curso aún no
    # tiene Tabla cargada, los RA se DERIVAN del etiquetado de los ítems (C1) más abajo, para que
    # la ficha funcione con la evidencia existente; el texto literal enriquece cuando sí está.
    ras = (db.query(LearningOutcome).filter(LearningOutcome.course_id == course_id)
           .order_by(LearningOutcome.orden).all())
    ra_meta = {r.code: {"code": r.code, "texto": r.text, "unidad": r.unidad, "en_tabla": True}
               for r in ras}

    # Acumuladores por RA (ítems enfrentados / aciertos), con desglose por tipo de prueba.
    acc: dict[str, dict] = {}
    pruebas: list[dict] = []

    from app.services.rubrica_escala_service import fraccion_logro
    from app.services.result_service import calculate_grade
    _escala = (course.grading_scale or "chile_1_7")
    _exig = 60.0 if course.passing_threshold is None else course.passing_threshold
    pendientes_dev = 0
    _q = db.query(Assessment).filter(Assessment.course_id == course_id)
    if assessment_id is not None:
        _q = _q.filter(Assessment.id == assessment_id)
    for a in _q.all():
        ak = answer_key_repo.get_by_assessment_id(db, a.id)
        if not ak or not ak.is_valid:
            continue  # sin pauta validada no hay corrección
        por_version: dict[str, dict[int, object]] = {}
        ra_por_q: dict[int, str] = {}
        for it in ak.items:
            if it.is_annulled:
                continue
            por_version.setdefault(it.version.upper(), {})[it.question_number] = it
            if it.learning_outcome_id:
                ra_por_q[it.question_number] = it.learning_outcome_id  # código del RA (C1)
        # Escaneo del alumno (deduplicado por alumno real; filtrable por origen). En oral/desarrollo
        # directo puede no haber hoja: la evidencia es el nivel de rúbrica VALIDADO por el docente.
        mios = [sc for sc in matriz_service.seleccionar_scans(db, a.id, origen)["scans"]
                if (sc.student_identifier or "").strip() == rut]
        scan = mios[0] if mios else None
        sv, sv_grupo = _dev_validaciones(db, a.id, st.id, scan.id if scan else None)
        if scan is None:
            if origen:                    # el filtro de origen es sobre escaneos: sin hoja no aplica
                continue
            if not (sv or sv_grupo):      # ni hoja ni desarrollo validado: no rindió / no ligado
                continue
        ver = ((scan.detected_version if scan else None) or
               ("A" if "A" in por_version else (next(iter(por_version), "A"))))
        clave = por_version.get(ver.upper())
        if not clave:
            continue
        respuestas = (scan.raw_ocr_payload_json or {}).get("answers", []) if scan else []
        tipo = a.tipo or "otro"
        ev_p = ok_p = 0
        for q, it in clave.items():
            crits = list(it.rubric_criteria)
            if crits:                                    # ── ítem de DESARROLLO (rúbrica, G1) ──
                obt = [(float(c.weight), c.niveles_json,
                        (sv_grupo if getattr(c, "ambito", None) == "grupal" else sv)[c.name])
                       for c in crits
                       if c.name in (sv_grupo if getattr(c, "ambito", None) == "grupal" else sv)]
                if not obt:
                    pendientes_dev += 1
                    continue                             # sin validar: NO cuenta (no es brecha)
                tw = sum(w for w, _, _ in obt) or 1.0
                ok = sum(fraccion_logro(niv, lvl) * w for w, niv, lvl in obt) / tw
            else:                                        # ── ítem de ALTERNATIVAS (vs pauta) ──
                if scan is None:
                    continue                             # sin hoja no hay evidencia de alternativas
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
        if not ev_p:
            continue
        _pct = round(ok_p / ev_p * 100, 1)
        try:
            _nota, _, _ = calculate_grade(_pct, _escala, _exig,
                                          banda_movil=bool(getattr(a, "bandas_moviles", False)))
            _nota = round(_nota, 1)
        except Exception:
            _nota = None
        _fecha = None
        if scan is not None and getattr(scan, "created_at", None):
            try:
                _fecha = scan.created_at.date().isoformat()
            except Exception:
                _fecha = None
        pruebas.append({
            "assessment_id": str(a.id), "nombre": a.name, "tipo": tipo,
            "modalidad": getattr(a, "modalidad", None),
            "origen": matriz_service._origen_de(scan) if scan else "desarrollo",
            "items_evaluados": ev_p,
            "logro_pct": _pct,
            "nota": _nota,
            "fecha": _fecha,
        })

    # RA presentes en la evidencia pero AUSENTES de la Tabla: se incluyen igual (no se ocultan),
    # marcados en_tabla=False. Si el curso no tenía Tabla, así aparecen todos los RA evaluados.
    for code in sorted(acc):
        if code not in ra_meta:
            ra_meta[code] = {"code": code, "texto": None, "unidad": None, "en_tabla": False}

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

    # RA etiquetados en ítems pero AUSENTES de la Tabla formal (trazabilidad honesta del C1).
    fuera_de_tabla = sorted(c for c in acc if not ra_meta.get(c, {}).get("en_tabla"))
    tabla_cargada = any(m.get("en_tabla") for m in ra_meta.values())
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
        "tabla_cargada": tabla_cargada,
        "resumen": {
            "n_ra_programa": sum(1 for m in ra_meta.values() if m.get("en_tabla")),
            "n_ra_evaluados": sum(1 for r in por_ra if r["items_evaluados"]),
            "n_brechas": len(brechas),
            "ra_sin_evaluar": [r["code"] for r in sin_eval],
            "n_pruebas": len(pruebas),
            "pendientes_desarrollo": pendientes_dev,
        },
        "ra_fuera_de_tabla": fuera_de_tabla,
        "gobernanza": "Agrega alternativas (auto-corregidas vs pauta) y desarrollo (nivel de "
                      "rúbrica VALIDADO por el docente, G1), deduplicado por estudiante. El "
                      "desarrollo sin validar no cuenta como brecha (queda pendiente). No altera "
                      "notas (G1); uso pedagógico del docente.",
    }


def _pearson(xs: list, ys: list):
    """Correlación de Pearson; None si n<3 o alguna serie sin varianza (ítem trivial)."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def analisis_evaluacion(db, assessment_id, origen: str | None = None,
                        umbral_brecha: float = 60.0) -> dict:
    """Análisis AGREGADO de una evaluación (Centro de Análisis): KPIs del curso, logro por RA
    (cruce con la Tabla de Especificaciones), distribución de notas y TRAZABILIDAD de la evidencia
    (origen OMR/en vivo, nº de escaneos, duplicados colapsados). Segmenta por prueba; sirve la
    vista por-RA y por-estudiante. Alternativas (auto vs pauta); el desarrollo por-RA agregado
    llega en un corte siguiente."""
    from app.models.assessment import Assessment
    from app.models.course import Course
    from app.models.curriculo import LearningOutcome
    from app.services.result_service import calculate_grade

    ak = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not ak or not ak.is_valid:
        raise conflict("La pauta no está validada; no hay análisis para esta evaluación.")
    asm = db.get(Assessment, assessment_id)
    course = db.get(Course, asm.course_id) if asm else None
    escala = (course.grading_scale if course else None) or "chile_1_7"
    exig = (course.passing_threshold if course else None)
    exig = 60.0 if exig is None else exig

    por_version: dict[str, dict[int, object]] = {}
    ra_por_q: dict[int, str] = {}
    for it in ak.items:
        if it.is_annulled:
            continue
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
        if it.learning_outcome_id:
            ra_por_q[it.question_number] = it.learning_outcome_id
    ra_meta = {r.code: {"code": r.code, "texto": r.text, "en_tabla": True}
               for r in (db.query(LearningOutcome).filter(LearningOutcome.course_id == asm.course_id)
                         .order_by(LearningOutcome.orden).all() if asm else [])}

    sel = matriz_service.seleccionar_scans(db, assessment_id, origen)
    ra_acc: dict[str, dict] = {}
    notas: list[float] = []
    logros: list[float] = []
    filas: list[dict] = []          # por scan: {q: c} de ítems MC + total (para discriminación)
    sesiones: set[str] = set()      # códigos de sesión en vivo (trazabilidad)
    fechas: list = []               # created_at de los escaneos
    opt_acc: dict[str, dict[int, dict[str, int]]] = {}   # [version][q][letra] -> conteo (distractores)
    ver_counts: dict[str, int] = {}                       # nº de scans por versión (para elegir dominante)
    matriz_tmp: list[dict] = []                           # por scan: {nota, ra:{code:pct}} (mapa de calor)
    for scan in sel["scans"]:
        ver = (scan.detected_version or "A").upper()
        clave = por_version.get(ver)
        if not clave:
            continue
        payload = (scan.raw_ocr_payload_json or {})
        respuestas = payload.get("answers", [])
        ses = payload.get("sesion")
        if ses:
            sesiones.add(str(ses))
        if getattr(scan, "created_at", None):
            fechas.append(scan.created_at)
        ev = ok = 0
        fila: dict[int, float] = {}
        fila_ra: dict[str, dict] = {}
        for q, it in clave.items():
            if list(it.rubric_criteria):
                continue  # desarrollo: no entra al agregado por-RA de alternativas
            elegida = respuestas[q - 1] if (q - 1) < len(respuestas) else None
            c = 1.0 if (elegida is not None and str(elegida).upper() == str(it.correct_answer).upper()) else 0.0
            ev += 1; ok += c
            fila[q] = c
            # distractores: conteo de la letra marcada, por versión (no mezcla barajados)
            letra = str(elegida).strip().upper()[:2] if elegida is not None else "∅"
            opt_acc.setdefault(ver, {}).setdefault(q, {}).setdefault(letra, 0)
            opt_acc[ver][q][letra] += 1
            rc = ra_por_q.get(q)
            if rc:
                d = ra_acc.setdefault(rc, {"ev": 0, "ok": 0.0}); d["ev"] += 1; d["ok"] += c
                fr = fila_ra.setdefault(rc, {"ev": 0, "ok": 0.0}); fr["ev"] += 1; fr["ok"] += c
        if not ev:
            continue
        ver_counts[ver] = ver_counts.get(ver, 0) + 1
        pct = round(ok / ev * 100, 1)
        nota, _, _ = calculate_grade(pct, escala, exig, banda_movil=bool(getattr(asm, "bandas_moviles", False)))
        notas.append(round(nota, 1)); logros.append(pct)
        filas.append({"fila": fila, "ok": ok})
        matriz_tmp.append({"nota": round(nota, 1),
                           "ra": {code: round(v["ok"] / v["ev"] * 100) for code, v in fila_ra.items() if v["ev"]}})

    for code in sorted(ra_acc):
        if code not in ra_meta:
            ra_meta[code] = {"code": code, "texto": None, "en_tabla": False}
    por_ra = []
    for code, meta in ra_meta.items():
        d = ra_acc.get(code)
        if d and d["ev"]:
            logro = round(d["ok"] / d["ev"] * 100, 1)
            por_ra.append({**meta, "logro_pct": logro, "nivel": _nivel(logro), "brecha": logro < umbral_brecha})
        else:
            por_ra.append({**meta, "logro_pct": None, "nivel": "sin evaluar", "brecha": None})

    # Discriminación por ítem: correlación ítem–total CORREGIDA (punto-biserial), para alertas de calidad.
    discriminacion = []
    if len(filas) >= 5:
        qs = sorted({q for f in filas for q in f["fila"].keys()})
        for q in qs:
            xs, ts = [], []
            for f in filas:
                if q in f["fila"]:
                    xi = f["fila"][q]
                    xs.append(xi); ts.append(f["ok"] - xi)   # total corregido (excluye el propio ítem)
            r = _pearson(xs, ts)
            if r is not None:
                discriminacion.append({"q": q, "ra": ra_por_q.get(q), "r": round(r, 2)})

    # Dificultad por ítem: % de acierto de cada pregunta (sirve como análisis SIEMPRE, aun sin RA
    # cargados en la Tabla de Especificaciones → el panel nunca queda hueco).
    disc_map = {d["q"]: d["r"] for d in discriminacion}
    por_item = []
    if filas:
        qs_all = sorted({q for f in filas for q in f["fila"].keys()})
        for q in qs_all:
            vals = [f["fila"][q] for f in filas if q in f["fila"]]
            if vals:
                por_item.append({"q": q, "pct": round(sum(vals) / len(vals) * 100, 1),
                                 "ra": ra_por_q.get(q), "discriminacion": disc_map.get(q)})

    # Alertas accionables: RA bajo umbral + ítems de baja/negativa discriminación.
    alertas = []
    for r in por_ra:
        if r.get("brecha"):
            lg = r.get("logro_pct") or 0
            alertas.append({"tipo": "ra_brecha", "severidad": ("critica" if lg < 40 else "media"),
                            "titulo": f'{r["code"]} bajo el umbral ({lg}%)',
                            "detalle": (f'{r.get("texto") or "Resultado de aprendizaje sin descripción"} · umbral {int(umbral_brecha)}%')})
    for d in discriminacion:
        ra_txt = f' · {d["ra"]}' if d["ra"] else ''
        if d["r"] < 0:
            alertas.append({"tipo": "item_discriminacion", "severidad": "critica",
                            "titulo": f'P{d["q"]} discrimina al revés (r={d["r"]})',
                            "detalle": f'Los estudiantes de mejor desempeño tienden a fallarla{ra_txt}. Revisar clave o enunciado.'})
        elif d["r"] < 0.15:
            alertas.append({"tipo": "item_discriminacion", "severidad": "media",
                            "titulo": f'P{d["q"]} discrimina poco (r={d["r"]})',
                            "detalle": f'Distingue mal entre quienes dominan y quienes no{ra_txt}.'})
    _sev = {"critica": 0, "media": 1, "baja": 2}
    alertas.sort(key=lambda a: _sev.get(a["severidad"], 3))

    # Distractores (versión dominante): distribución de la letra marcada por ítem; marca los ítems
    # donde un distractor ATRAE más que la correcta (error conceptual sistemático o redacción ambigua).
    distractores = []
    if ver_counts:
        dom = max(ver_counts, key=ver_counts.get)
        claved = por_version.get(dom, {})
        for q in sorted(opt_acc.get(dom, {})):
            counts = opt_acc[dom][q]
            tot = sum(counts.values())
            if not tot:
                continue
            it = claved.get(q)
            correcta = str(it.correct_answer).strip().upper() if it else ""
            letras = sorted(l for l in counts if l != "∅")
            opciones = [{"letra": l, "n": counts[l], "pct": round(counts[l] / tot * 100),
                         "correcta": (l == correcta)} for l in letras]
            if counts.get("∅"):
                opciones.append({"letra": "∅", "n": counts["∅"], "pct": round(counts["∅"] / tot * 100),
                                 "correcta": False, "omitida": True})
            co = next((o for o in opciones if o.get("correcta")), None)
            pc = co["pct"] if co else 0
            trampa = next((o for o in opciones if not o.get("correcta") and not o.get("omitida") and o["pct"] > pc), None)
            distractores.append({"q": q, "ra": ra_por_q.get(q), "correcta": correcta,
                                 "opciones": opciones, "trampa": (trampa["letra"] if trampa else None)})
        for dd in distractores:
            if dd["trampa"]:
                to = next(o for o in dd["opciones"] if o["letra"] == dd["trampa"])
                co = next((o for o in dd["opciones"] if o.get("correcta")), None)
                alertas.append({"tipo": "distractor", "severidad": "media",
                                "titulo": f'P{dd["q"]}: el distractor {dd["trampa"]} atrae más que la correcta',
                                "detalle": f'{to["pct"]}% marcó {dd["trampa"]} vs {(co["pct"] if co else 0)}% la correcta {dd["correcta"]}. Error conceptual sistemático o redacción ambigua.'})
        alertas.sort(key=lambda a: _sev.get(a["severidad"], 3))

    # Mapa de calor estudiante × RA (seudonimizado G2): ordenado por nota, etiquetas E1..EN.
    ra_codes_mat = [r["code"] for r in por_ra if r.get("logro_pct") is not None]
    matriz_tmp.sort(key=lambda m: m["nota"], reverse=True)
    _LIM = 40
    estudiantes_mat = [{"alias": f"E{i + 1}", "nota": m["nota"],
                        "ra": {c: m["ra"].get(c) for c in ra_codes_mat}}
                       for i, m in enumerate(matriz_tmp[:_LIM])]
    matriz_ra = {"ra_codes": ra_codes_mat, "estudiantes": estudiantes_mat,
                 "n_total": len(matriz_tmp), "truncado": len(matriz_tmp) > _LIM}

    fecha_ult = None
    if fechas:
        try:
            fecha_ult = max(fechas).date().isoformat()
        except Exception:
            fecha_ult = None

    n = len(notas)
    bandas = [("1.0–3.9", 1.0, 3.95), ("4.0–4.9", 3.95, 4.95), ("5.0–5.9", 4.95, 5.95), ("6.0–7.0", 5.95, 7.01)]
    return {
        "assessment_id": str(assessment_id),
        "prueba": (asm.name if asm else ""), "tipo": getattr(asm, "tipo", None),
        "modalidad": getattr(asm, "modalidad", None),
        "ponderacion_semestral": getattr(asm, "ponderacion_semestral", None),
        "curso": (course.name if course else ""), "curso_code": (course.code if course else ""),
        "kpis": {
            "n_estudiantes": n,
            "promedio": round(sum(notas) / n, 1) if n else None,
            "aprobacion_pct": round(sum(1 for x in notas if x >= 4.0) / n * 100) if n else None,
            "logro_pct": round(sum(logros) / len(logros)) if logros else None,
        },
        "por_ra": por_ra,
        "por_item": por_item,
        "distribucion": [{"rango": b[0], "n": sum(1 for x in notas if b[1] <= x < b[2])} for b in bandas],
        "discriminacion": discriminacion,
        "distractores": distractores,
        "matriz_ra": matriz_ra,
        "alertas": alertas,
        "trazabilidad": {
            "origen": sel["origen"], "escaneos_omr": sel["n_omr"], "escaneos_en_vivo": sel["n_en_vivo"],
            "duplicados_colapsados": sel["duplicados_colapsados"], "n_scans": len(sel["scans"]),
            "sesiones": sorted(sesiones), "n_sesiones": len(sesiones), "fecha_ultima": fecha_ult,
        },
        "umbral_brecha": umbral_brecha,
        "tabla_cargada": any(m.get("en_tabla") for m in ra_meta.values()),
    }


# ── Cortes históricos (snapshots) del Centro de Análisis: congelar el análisis en un instante ──
def crear_snapshot(db, assessment_id, etiqueta: str, origen: str | None = None) -> dict:
    """Congela el análisis actual de una evaluación como corte INMUTABLE (auditoría/serie de tiempo)."""
    from app.models.snapshot import AnalisisSnapshot
    from app.models.assessment import Assessment
    d = analisis_evaluacion(db, assessment_id, origen=origen)
    k = d.get("kpis") or {}
    asm = db.get(Assessment, assessment_id)
    snap = AnalisisSnapshot(
        assessment_id=str(assessment_id),
        course_id=str(asm.course_id) if asm and asm.course_id else None,
        etiqueta=(str(etiqueta or "").strip()[:160] or "Corte"),
        origen=(origen or None),
        n_estudiantes=int(k.get("n_estudiantes") or 0),
        promedio=k.get("promedio"), aprobacion_pct=k.get("aprobacion_pct"), logro_pct=k.get("logro_pct"),
        payload_json=d)
    db.add(snap); db.commit(); db.refresh(snap)
    return {"id": str(snap.id), "etiqueta": snap.etiqueta,
            "tomado_at": snap.tomado_at.isoformat() if snap.tomado_at else None,
            "n_estudiantes": snap.n_estudiantes, "promedio": snap.promedio,
            "aprobacion_pct": snap.aprobacion_pct, "logro_pct": snap.logro_pct}


def listar_snapshots(db, assessment_id) -> dict:
    """Lista los cortes congelados de una evaluación (sin el payload completo), más recientes primero."""
    from app.models.snapshot import AnalisisSnapshot
    q = (db.query(AnalisisSnapshot)
         .filter(AnalisisSnapshot.assessment_id == str(assessment_id))
         .order_by(AnalisisSnapshot.tomado_at.desc()).all())
    return {"assessment_id": str(assessment_id), "n": len(q), "snapshots": [
        {"id": str(s.id), "etiqueta": s.etiqueta, "origen": s.origen or "",
         "tomado_at": s.tomado_at.isoformat() if s.tomado_at else None,
         "n_estudiantes": s.n_estudiantes, "promedio": s.promedio,
         "aprobacion_pct": s.aprobacion_pct, "logro_pct": s.logro_pct} for s in q]}


def obtener_snapshot(db, snapshot_id) -> dict:
    """Devuelve el payload COMPLETO congelado de un corte (para verlo o comparar)."""
    from app.models.snapshot import AnalisisSnapshot
    import uuid as _uuid
    try:
        sid = _uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise not_found("Corte no válido.")
    s = db.get(AnalisisSnapshot, sid)
    if not s:
        raise not_found("Corte no encontrado.")
    d = dict(s.payload_json or {})
    d["_snapshot"] = {"id": str(s.id), "etiqueta": s.etiqueta,
                      "tomado_at": s.tomado_at.isoformat() if s.tomado_at else None, "origen": s.origen or ""}
    return d


def eliminar_snapshot(db, snapshot_id) -> dict:
    from app.models.snapshot import AnalisisSnapshot
    import uuid as _uuid
    try:
        sid = _uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise not_found("Corte no válido.")
    s = db.get(AnalisisSnapshot, sid)
    if not s:
        raise not_found("Corte no encontrado.")
    db.delete(s); db.commit()
    return {"eliminado": True}


def _fortalezas(por_ra: list) -> list:
    return [r for r in por_ra if r.get("nivel") == "Logrado"]


def informe_personalizado(db, course_id, rut: str, umbral_brecha: float = 60.0,
                          origen: str | None = None, assessment_id=None) -> dict:
    """Informe personalizado, EMPÁTICO y PROPOSITIVO, para UN estudiante: reconoce logros,
    constata las brechas por RA (con el texto literal del programa) y propone ESCENARIOS
    ESTRATÉGICOS DE APRENDIZAJE por cada brecha, anclado a los datos reales del alumno.

    Ámbito DINÁMICO: sin assessment_id → consolida TODA la evidencia del curso (todas las
    pruebas rendidas, deduplicadas por RA). Con assessment_id → se acota a ESA evaluación.

    Con clave de IA redacta con el LLM (compuerta docente: es un BORRADOR a revisar); sin clave
    cae a una plantilla determinista con los mismos datos. Línea roja: solo usa los datos dados,
    no inventa notas, %, RA ni contenidos. No altera calificaciones (G1).
    """
    from app.services.briefing_service import _llm, MODELO

    datos = brechas_estudiante(db, course_id, rut, umbral_brecha=umbral_brecha,
                               origen=origen, assessment_id=assessment_id)
    est = datos["estudiante"]
    brechas = sorted(datos["brechas"], key=lambda b: (b.get("logro_pct") if b.get("logro_pct") is not None else 0))
    fortalezas = _fortalezas(datos["por_ra"])
    nombre_pila = (est.get("nombre") or "").split(",")[-1].strip() or "estudiante"

    def _brecha_linea(b):
        pt = b.get("por_tipo") or {}
        det = ("; por tipo: " + ", ".join(f"{k} {v}%" for k, v in pt.items())) if pt else ""
        return f'- {b["code"]} · "{b.get("texto", "")}" — logro {b.get("logro_pct")}%{det}'

    def _fort_linea(r):
        return f'- {r["code"]} · "{r.get("texto", "")}" — logro {r.get("logro_pct")}%'

    sistema = (
        "Eres un docente que escribe un informe formativo PERSONALIZADO para UN estudiante, en "
        "español de Chile, en tono cercano, empático y RESPETUOSO, sin paternalismo. Trato formal: "
        "háblale SIEMPRE de USTED (nunca de tú); conjuga en tercera persona formal. El objetivo "
        "no es la nota sino el aprendizaje: reconoce lo logrado y acompaña en lo que falta. "
        "Estructura en Markdown con estos subtítulos en negrita: "
        "**Lo que ha logrado** (nombra los RA dominados citando su % real); "
        "**Brechas por trabajar** (por cada RA con brecha: constata el vacío con empatía y explica "
        "POR QUÉ ese resultado de aprendizaje importa para lo que viene); "
        "**Escenarios estratégicos de aprendizaje** (por cada brecha, propón UN escenario de "
        "aprendizaje concreto y SITUADO —un caso, un proyecto breve, una simulación, un set de "
        "práctica con progresión— que ayude a cerrar esa brecha específica, describiendo qué haría "
        "el estudiante, con qué y cómo sabría que avanzó); "
        "**Un paso para esta semana** (una sola acción pequeña y realista para empezar). "
        "Reglas estrictas: usa SOLO los datos entregados; NO inventes notas, porcentajes, RA ni "
        "contenidos que no estén; no prometas resultados; 250-400 palabras; trato de USTED en todo."
    )
    usuario = (
        f"ESTUDIANTE: {est.get('nombre', '(seudónimo)')} (diríjase con USTED, usando su nombre «{nombre_pila}»)\n"
        f"CURSO: {datos['curso'].get('nombre', '')}\n"
        f"Evaluaciones rendidas: {datos['resumen']['n_pruebas']}. "
        f"RA del programa: {datos['resumen']['n_ra_programa']}; evaluados: {datos['resumen']['n_ra_evaluados']}.\n"
        "RA LOGRADOS:\n" + ("\n".join(_fort_linea(r) for r in fortalezas) or "- (ninguno destacado aún)") + "\n"
        "RA CON BRECHA (ordenados del más urgente):\n"
        + ("\n".join(_brecha_linea(b) for b in brechas) or "- (sin brechas marcadas)") + "\n"
    )
    texto = _llm(sistema, usuario, max_tokens=1400)
    motor = "IA (" + MODELO + ")" if texto else "plantilla determinista"
    if not texto:
        texto = _plantilla_informe(nombre_pila, datos, fortalezas, brechas)

    # Ámbito del informe: prueba puntual (si se acotó) o consolidado del curso.
    ambito = {"prueba": None, "consolidado": True}
    if assessment_id is not None:
        from app.models.assessment import Assessment
        asm = db.get(Assessment, assessment_id)
        ambito = {"prueba": (asm.name if asm else None),
                  "tipo": getattr(asm, "tipo", None) if asm else None, "consolidado": False}

    return {
        "estudiante": est,
        "curso": datos["curso"],
        "informe": texto,
        "motor": motor,          # sólo para el docente (gobernanza); NO se muestra al estudiante
        "borrador": True,        # compuerta docente: revisar y ajustar antes de compartir
        "ambito": ambito,        # consolidado del curso vs. una prueba específica
        "datos": datos,          # anclaje: los hechos reales que sustentan el texto
        "gobernanza": "Borrador formativo anclado a los datos reales del estudiante. Revíselo y "
                      "ajústelo antes de compartir (compuerta docente). No altera la nota (G1).",
    }


def _informe_a_secciones(md: str) -> list[dict]:
    """Convierte el informe (markdown) a secciones del exportador: los encabezados **X** / # X
    pasan a heading; cada otra línea a un párrafo (limpiando negritas y viñetas)."""
    import re
    secs = []
    for raw in str(md or "").split("\n"):
        t = raw.strip()
        if not t:
            continue
        h = None
        if t.startswith("### "):
            h = t[4:]
        elif t.startswith("## "):
            h = t[3:]
        elif t.startswith("# "):
            h = t[2:]
        else:
            m = re.match(r"^\*\*(.+?)\*\*:?$", t)
            if m:
                h = m.group(1)
        if h:
            secs.append({"heading": h.strip(), "nivel": 2, "texto": ""})
        else:
            linea = re.sub(r"^[-*]\s+", "• ", t).replace("**", "")
            secs.append({"heading": None, "nivel": 2, "texto": linea})
    return secs


def informe_export_payload(db, course_id, rut: str, umbral_brecha: float = 60.0,
                           origen: str | None = None, assessment_id=None) -> dict:
    """Documento exportable (Word/PDF) del informe personalizado: portada + informe formativo por
    secciones + tabla de logro por RA. Reutiliza informe_personalizado (con compuerta docente).
    El documento del estudiante NO expone el motor de IA ni notas internas de gobernanza."""
    inf = informe_personalizado(db, course_id, rut, umbral_brecha=umbral_brecha,
                                origen=origen, assessment_id=assessment_id)
    est, datos = inf["estudiante"], inf["datos"]
    tabla = {"titulo": "Logro por Resultado de Aprendizaje",
             "headers": ["RA", "Resultado de aprendizaje", "Logro %", "Nivel", "Brecha"],
             "rows": [[r["code"], r.get("texto") or "—",
                       ("—" if r.get("logro_pct") is None else r["logro_pct"]),
                       r["nivel"], ("Sí" if r.get("brecha") else ("—" if r.get("brecha") is None else "No"))]
                      for r in datos["por_ra"]]}
    ambito = inf.get("ambito") or {}
    sub = ("Evaluación: " + ambito["prueba"]) if ambito.get("prueba") else "Consolidado de todas las evaluaciones del curso"
    cab = {"heading": "Informe formativo personalizado", "nivel": 1,
           "texto": f"Estudiante: {est.get('nombre','')} · Curso: {inf['curso'].get('nombre','')} · {sub}."}
    return {"payload": {"titulo": f"Informe · {est.get('nombre','')}",
                        "secciones": [cab] + _informe_a_secciones(inf["informe"]),
                        "tablas": [tabla]},
            "informe": inf}


def _plantilla_informe(nombre, datos, fortalezas, brechas) -> str:
    p = [f"**Lo que ha logrado.** {nombre}, "]
    if fortalezas:
        p.append("ha demostrado dominio en: "
                 + ", ".join(f'{r["code"]} ({r.get("logro_pct")}%)' for r in fortalezas[:5]) + ". "
                 "Es una base sólida sobre la que seguir construyendo.")
    else:
        p.append("aún no hay un RA plenamente consolidado, y eso es completamente trabajable: "
                 "lo importante es dónde poner el foco ahora.")
    if brechas:
        p.append("\n\n**Brechas por trabajar.** Conviene reforzar:")
        for b in brechas[:6]:
            p.append(f'\n- **{b["code"]}** — «{b.get("texto", "")}» (logro {b.get("logro_pct")}%). '
                     "Este resultado de aprendizaje sostiene los contenidos que vienen, por eso "
                     "vale la pena afianzarlo ahora.")
        p.append("\n\n**Escenarios estratégicos de aprendizaje.** Para cada brecha:")
        for b in brechas[:6]:
            p.append(f'\n- **{b["code"]}**: diseñe un escenario situado donde tenga que aplicar '
                     f'«{b.get("texto", "")}» en un caso o problema real del curso; resuélvalo por '
                     "pasos, contraste su solución con la pauta y repita con una variante hasta "
                     "resolverla con seguridad.")
        p.append("\n\n**Un paso para esta semana.** Elija la primera brecha de la lista y dedíquele "
                 "una sesión corta de práctica enfocada; revise exactamente dónde se produjo el error.")
    else:
        p.append("\n\n**Brechas por trabajar.** No se detectaron brechas marcadas: mantenga el ritmo "
                 "y profundice en lo que más le interese del curso.")
    return "".join(p)
