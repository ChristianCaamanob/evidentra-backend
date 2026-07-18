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
        },
        "ra_fuera_de_tabla": fuera_de_tabla,
        "gobernanza": "Agrega ítems de alternativas (auto-corregidos vs pauta validada), "
                      "deduplicados por estudiante. No altera notas (G1); uso pedagógico del docente. "
                      "El desarrollo por-RA se integrará en un corte siguiente.",
    }


def _fortalezas(por_ra: list) -> list:
    return [r for r in por_ra if r.get("nivel") == "Logrado"]


def informe_personalizado(db, course_id, rut: str, umbral_brecha: float = 60.0,
                          origen: str | None = None) -> dict:
    """Informe personalizado, EMPÁTICO y PROPOSITIVO, para UN estudiante: reconoce logros,
    constata las brechas por RA (con el texto literal del programa) y propone ESCENARIOS
    ESTRATÉGICOS DE APRENDIZAJE por cada brecha, anclado a los datos reales del alumno.

    Con clave de IA redacta con el LLM (compuerta docente: es un BORRADOR a revisar); sin clave
    cae a una plantilla determinista con los mismos datos. Línea roja: solo usa los datos dados,
    no inventa notas, %, RA ni contenidos. No altera calificaciones (G1).
    """
    from app.services.briefing_service import _llm, MODELO

    datos = brechas_estudiante(db, course_id, rut, umbral_brecha=umbral_brecha, origen=origen)
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
        "español de Chile, en tono cercano, empático y RESPETUOSO, sin paternalismo. El objetivo "
        "no es la nota sino el aprendizaje: reconoce lo logrado y acompaña en lo que falta. "
        "Estructura en Markdown con estos subtítulos en negrita: "
        "**Lo que has logrado** (nombra los RA dominados citando su % real); "
        "**Brechas por trabajar** (por cada RA con brecha: constata el vacío con empatía y explica "
        "POR QUÉ ese resultado de aprendizaje importa para lo que viene); "
        "**Escenarios estratégicos de aprendizaje** (por cada brecha, propón UN escenario de "
        "aprendizaje concreto y SITUADO —un caso, un proyecto breve, una simulación, un set de "
        "práctica con progresión— que ayude a cerrar esa brecha específica, describiendo qué haría "
        "el estudiante, con qué y cómo sabría que avanzó); "
        "**Un paso para esta semana** (una sola acción pequeña y realista para empezar). "
        "Reglas estrictas: usa SOLO los datos entregados; NO inventes notas, porcentajes, RA ni "
        "contenidos que no estén; no prometas resultados; 250-400 palabras; háblale de tú."
    )
    usuario = (
        f"ESTUDIANTE: {est.get('nombre', '(seudónimo)')} (dirígete a él/ella como «{nombre_pila}»)\n"
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

    return {
        "estudiante": est,
        "curso": datos["curso"],
        "informe": texto,
        "motor": motor,
        "borrador": True,   # compuerta docente: revisar y ajustar antes de compartir
        "datos": datos,     # anclaje: los hechos reales que sustentan el texto
        "gobernanza": "Borrador formativo anclado a los datos reales del estudiante. Revísalo y "
                      "ajústalo antes de compartir (compuerta docente). No altera la nota (G1).",
    }


def _plantilla_informe(nombre, datos, fortalezas, brechas) -> str:
    p = [f"**Lo que has logrado.** {nombre}, "]
    if fortalezas:
        p.append("has demostrado dominio en: "
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
            p.append(f'\n- **{b["code"]}**: diseña un escenario situado donde tengas que aplicar '
                     f'«{b.get("texto", "")}» en un caso o problema real del curso; resuélvelo por '
                     "pasos, contrasta tu solución con la pauta y repite con una variante hasta "
                     "resolverla con seguridad.")
        p.append("\n\n**Un paso para esta semana.** Elige la primera brecha de la lista y dedícale "
                 "una sesión corta de práctica enfocada; revisa exactamente dónde se produjo el error.")
    else:
        p.append("\n\n**Brechas por trabajar.** No se detectaron brechas marcadas: mantén el ritmo "
                 "y profundiza en lo que más te interese del curso.")
    return "".join(p)
