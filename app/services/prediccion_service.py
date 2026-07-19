"""
Parametrización del curso + Ciclos + Pronóstico de aprobación (proactivo, transparente).

Norte del CEO: a medida que se llenan los perfiles, cruzar información por CICLOS (cada
certamen/solemne cierra un ciclo) y PRONOSTICAR la aprobación de la asignatura para actuar
proactivamente. El profesor parametriza OPCIONALMENTE la estructura (componentes con peso %=100,
categorías, asistencia requerida). El pronóstico es una PROYECCIÓN TRANSPARENTE (no caja negra):
weighted grade de lo rendido + escenarios (ritmo actual / optimista / pesimista) + nota necesaria
en lo que resta + compuerta de asistencia. No altera notas (G1); es un plan declarado + proyección.

Modelo de `Course.parametrizacion` (JSON):
{
  "activa": true,
  "componentes": [
     {"id","nombre","categoria","peso_pct","assessment_id"?},   # categoria: certamen|solemne|control|lab_envivo|exposicion|lab_prueba|informe
     ...  # Σ peso_pct == 100
  ],
  "asistencia": {"teorico_pct":75,"teorico_libre":false,"lab_pct":100,"modo":"gate"}
}
"""
from __future__ import annotations

import math

CATEGORIAS = {"certamen", "solemne", "control", "lab_envivo", "exposicion", "lab_prueba", "informe"}
CIERRA_CICLO = {"certamen", "solemne"}      # cada certamen/solemne cierra un ciclo
CONflict_TOL = 0.5


# ────────────────────────────── Parametrización ──────────────────────────────
def obtener_parametrizacion(db, course_id) -> dict:
    from app.models.course import Course
    c = db.get(Course, course_id)
    if not c:
        from app.core.errors import not_found
        raise not_found("Curso no encontrado.")
    return {"course_id": str(c.id), "curso": c.name, "tipo": c.tipo,
            "parametrizacion": c.parametrizacion, "activa": bool(c.parametrizacion and c.parametrizacion.get("activa"))}


def guardar_parametrizacion(db, course_id, payload: dict) -> dict:
    """Valida y persiste. Σ peso_pct debe ser 100 (±0.5). Idempotente."""
    from app.models.course import Course
    from app.core.errors import conflict, not_found
    c = db.get(Course, course_id)
    if not c:
        raise not_found("Curso no encontrado.")
    comps = payload.get("componentes") or []
    total = 0.0
    limpios = []
    for i, comp in enumerate(comps):
        cat = (comp.get("categoria") or "").strip()
        if cat not in CATEGORIAS:
            raise conflict(f"Categoría inválida en el componente {i+1}: '{cat}'.")
        try:
            peso = round(float(comp.get("peso_pct") or 0), 2)
        except (TypeError, ValueError):
            raise conflict(f"Peso inválido en el componente {i+1}.")
        if peso < 0:
            raise conflict("Los pesos no pueden ser negativos.")
        total += peso
        limpios.append({
            "id": comp.get("id") or f"c{i+1}",
            "nombre": (comp.get("nombre") or cat).strip()[:120],
            "categoria": cat,
            "peso_pct": peso,
            "assessment_id": (str(comp.get("assessment_id")) if comp.get("assessment_id") else None),
        })
    if limpios and abs(total - 100.0) > CONflict_TOL:
        raise conflict(f"Los pesos deben sumar 100% (suman {round(total, 1)}%).")

    asis = payload.get("asistencia") or {}
    asistencia = {
        "teorico_pct": _num(asis.get("teorico_pct"), 75),
        "teorico_libre": bool(asis.get("teorico_libre")),
        "lab_pct": _num(asis.get("lab_pct"), 100),
        "modo": ("informativa" if asis.get("modo") == "informativa" else "gate"),
    }
    c.parametrizacion = {"activa": True, "componentes": limpios, "asistencia": asistencia}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(c, "parametrizacion")
    db.commit()
    return {"ok": True, "parametrizacion": c.parametrizacion, "suma_pesos": round(total, 1)}


def _num(v, d):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return d


# ────────────────────────────── Ciclos ──────────────────────────────
def ciclos(db, course_id) -> dict:
    """Deriva los CICLOS automáticamente: ordena las evaluaciones por creación; cada
    certamen/solemne CIERRA su ciclo (controles previos + ese certamen = un ciclo)."""
    from app.models.assessment import Assessment
    asms = (db.query(Assessment).filter(Assessment.course_id == course_id)
            .order_by(Assessment.created_at.asc()).all())
    grupos: list[dict] = []
    actual = {"ciclo": 1, "evaluaciones": [], "cierre": None}
    for a in asms:
        tp = (getattr(a, "tipo", None) or "").lower()
        actual["evaluaciones"].append({"assessment_id": str(a.id), "nombre": a.name, "tipo": tp,
                                        "modalidad": getattr(a, "modalidad", None)})
        if tp in CIERRA_CICLO:
            actual["cierre"] = a.name
            grupos.append(actual)
            actual = {"ciclo": len(grupos) + 1, "evaluaciones": [], "cierre": None}
    if actual["evaluaciones"]:
        actual["cierre"] = None   # ciclo en curso (aún sin certamen que lo cierre)
        grupos.append(actual)
    # mapa assessment_id -> ciclo
    mapa = {}
    for g in grupos:
        for e in g["evaluaciones"]:
            mapa[e["assessment_id"]] = g["ciclo"]
    return {"course_id": str(course_id), "n_ciclos": len(grupos), "ciclos": grupos, "mapa": mapa}


# ────────────────────────────── Notas por estudiante ──────────────────────────────
def _nota_en_evaluacion(db, assessment_id, rut, escala, exigencia):
    """Nota (1-7) de UN estudiante en UNA evaluación de alternativas, por RUT. None si no rindió
    o si es una evaluación de desarrollo (sin clave MC). Transparente, no altera notas."""
    from app.repositories import answer_key_repo, scan_repo
    from app.services.result_service import calculate_grade
    ak = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not ak or not ak.is_valid:
        return None
    por_version: dict[str, dict[int, object]] = {}
    for it in ak.items:
        if it.is_annulled or list(it.rubric_criteria):
            continue
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
    if not por_version:
        return None
    cand = [s for s in scan_repo.list_by_assessment(db, assessment_id)
            if s.student_identifier == rut and not getattr(s, "requires_review", False)]
    if not cand:
        return None
    scan = cand[-1]
    clave = por_version.get((scan.detected_version or "A").upper())
    if not clave:
        return None
    respuestas = (scan.raw_ocr_payload_json or {}).get("answers", [])
    ev = ok = 0
    for q, it in clave.items():
        elegida = respuestas[q - 1] if (q - 1) < len(respuestas) else None
        ev += 1
        ok += 1.0 if (elegida is not None and str(elegida).upper() == str(it.correct_answer).upper()) else 0.0
    if not ev:
        return None
    pct = round(ok / ev * 100, 1)
    nota, _, _ = calculate_grade(pct, escala, exigencia)
    return round(nota, 1)


# ────────────────────────────── Asistencia ──────────────────────────────
def asistencia_pct(db, course_id, rut) -> dict:
    """% de asistencia de un estudiante: marcas / sesiones del curso. None si no hay sesiones o
    el estudiante no está en la nómina de asistencia."""
    from app.models.asistencia import AsistenciaMatricula, SesionAsistencia, MarcaAsistencia
    total = db.query(SesionAsistencia).filter(SesionAsistencia.course_id == course_id).count()
    if not total:
        return {"pct": None, "sesiones": 0, "presentes": 0}
    mat = (db.query(AsistenciaMatricula)
           .filter(AsistenciaMatricula.course_id == course_id, AsistenciaMatricula.rut == rut).first())
    if not mat:
        return {"pct": None, "sesiones": total, "presentes": 0, "sin_matricula": True}
    pres = db.query(MarcaAsistencia).filter(MarcaAsistencia.matricula_id == mat.id).count()
    return {"pct": round(pres / total * 100, 1), "sesiones": total, "presentes": pres}


# ────────────────────────────── Pronóstico ──────────────────────────────
def _estado_por_necesaria(necesaria, peso_restante):
    if peso_restante <= 0:
        return None
    if necesaria is None:
        return "Encaminado"
    if necesaria <= 4.0:
        return "Encaminado"
    if necesaria <= 5.5:
        return "En riesgo"
    if necesaria <= 7.0:
        return "Crítico"
    return "Muy difícil"


def pronostico_estudiante(db, course_id, rut, escala="chile_1_7", exigencia=60.0) -> dict:
    """Proyección transparente de aprobación para UN estudiante, según la parametrización del curso.
    Devuelve: nota acumulada de lo rendido, escenarios de nota final, nota necesaria en lo que resta,
    estado de asistencia (compuerta) y una probabilidad estimada. No altera notas (G1)."""
    from app.models.course import Course
    from app.models.student import Student
    c = db.get(Course, course_id)
    if not c:
        from app.core.errors import not_found
        raise not_found("Curso no encontrado.")
    param = c.parametrizacion or {}
    comps = (param.get("componentes") or []) if param.get("activa") else []
    est = db.query(Student).filter(Student.course_id == course_id, Student.rut == rut).first()
    nombre = None
    if est:
        nombre = f"{est.apellido_paterno}, {est.nombres}".strip(", ")

    if not comps:
        return {"course_id": str(course_id), "rut": rut, "nombre": nombre,
                "parametrizado": False,
                "mensaje": "El curso aún no tiene parametrización de evaluación; sin ella no se puede "
                           "proyectar la aprobación. Parametriza los pesos (que sumen 100%) para activar el pronóstico."}

    ciclo_map = ciclos(db, course_id)["mapa"]
    detalle = []
    obtenido = 0.0            # Σ (peso/100 * nota) de lo rendido
    peso_rendido = 0.0
    peso_total = 0.0
    for comp in comps:
        peso = float(comp.get("peso_pct") or 0)
        peso_total += peso
        aid = comp.get("assessment_id")
        nota = _nota_en_evaluacion(db, aid, rut, escala, exigencia) if aid else None
        fila = {"nombre": comp.get("nombre"), "categoria": comp.get("categoria"),
                "peso_pct": peso, "assessment_id": aid,
                "ciclo": ciclo_map.get(str(aid)) if aid else None,
                "nota": nota, "rendida": nota is not None}
        if nota is not None:
            obtenido += peso / 100.0 * nota
            peso_rendido += peso
        detalle.append(fila)

    peso_restante = round(peso_total - peso_rendido, 2)
    nota_parcial = round(obtenido / (peso_rendido / 100.0), 2) if peso_rendido > 0 else None

    # Escenarios de nota final (sobre 100% del curso)
    def _proj(nota_resto):
        return round(obtenido + (peso_restante / 100.0) * nota_resto, 2)
    escenarios = None
    if peso_rendido > 0:
        escenarios = {
            "ritmo_actual": _proj(nota_parcial),
            "optimista": _proj(7.0),
            "pesimista": _proj(1.0),
        }
    # Nota necesaria en lo que resta para llegar a 4.0
    necesaria = None
    if peso_restante > 0:
        necesaria = round((4.0 - obtenido) / (peso_restante / 100.0), 2)
        necesaria = max(1.0, necesaria) if necesaria > 1.0 else 1.0  # piso 1.0
    asegura = peso_restante <= 0 or (necesaria is not None and necesaria <= 1.0 and obtenido >= 4.0)

    # Compuerta de asistencia
    asis = asistencia_pct(db, course_id, rut)
    asis_cfg = param.get("asistencia") or {}
    es_lab = (c.tipo or "").lower() in ("laboratorio", "practico")
    requerido = asis_cfg.get("lab_pct", 100) if es_lab else asis_cfg.get("teorico_pct", 75)
    libre = (not es_lab) and asis_cfg.get("teorico_libre")
    modo = asis_cfg.get("modo", "gate")
    reprueba_asistencia = False
    asis_estado = "sin datos"
    if libre:
        asis_estado = "asistencia libre"
    elif asis["pct"] is not None:
        if asis["pct"] + 1e-9 >= requerido:
            asis_estado = "cumple"
        else:
            asis_estado = "bajo el mínimo"
            if modo == "gate":
                reprueba_asistencia = True

    # Estado global + probabilidad
    estado_nota = _estado_por_necesaria(necesaria, peso_restante)
    if peso_restante <= 0:
        estado_nota = "Aprobado proyectado" if (obtenido >= 4.0) else "Reprobado proyectado"
    if reprueba_asistencia:
        estado = "Reprueba por asistencia"
    elif estado_nota:
        estado = estado_nota
    else:
        estado = "Sin evidencia aún"

    # Probabilidad estimada (logística transparente sobre la proyección al ritmo actual)
    prob = None
    if reprueba_asistencia:
        prob = 0
    elif escenarios is not None:
        proj = escenarios["ritmo_actual"]
        prob = round(100.0 / (1.0 + math.exp(-2.4 * (proj - 4.0))))
        prob = max(1, min(99, prob))

    return {
        "course_id": str(course_id), "rut": rut, "nombre": nombre, "parametrizado": True,
        "tipo_curso": c.tipo, "peso_total": round(peso_total, 1),
        "peso_rendido": round(peso_rendido, 1), "peso_restante": peso_restante,
        "nota_acumulada": nota_parcial,          # nota promedio ponderada de lo rendido
        "escenarios": escenarios,                # nota final proyectada
        "nota_necesaria_resto": None if asegura else necesaria,
        "asegura_aprobacion": bool(asegura and obtenido >= 4.0),
        "asistencia": {**asis, "requerido": requerido, "estado": asis_estado,
                       "libre": bool(libre), "modo": modo, "reprueba": reprueba_asistencia},
        "estado": estado,
        "probabilidad_aprobar": prob,
        "detalle": detalle,
    }


def pronostico_curso(db, course_id, escala="chile_1_7", exigencia=60.0) -> dict:
    """Agregado del pronóstico para TODO el curso: por estudiante + conteos por estado. Base del
    tablero proactivo del profesor y del agregado del Director."""
    from app.models.course import Course
    from app.models.student import Student
    c = db.get(Course, course_id)
    if not c:
        from app.core.errors import not_found
        raise not_found("Curso no encontrado.")
    param = c.parametrizacion or {}
    if not (param.get("activa") and param.get("componentes")):
        return {"course_id": str(course_id), "curso": c.name, "parametrizado": False,
                "mensaje": "Parametriza el curso para activar el pronóstico agregado."}
    ests = db.query(Student).filter(Student.course_id == course_id).order_by(Student.apellido_paterno).all()
    filas = []
    conteo = {}
    probs = []
    for st in ests:
        p = pronostico_estudiante(db, course_id, st.rut, escala, exigencia)
        estado = p.get("estado", "Sin evidencia aún")
        conteo[estado] = conteo.get(estado, 0) + 1
        if p.get("probabilidad_aprobar") is not None:
            probs.append(p["probabilidad_aprobar"])
        filas.append({"rut": st.rut, "nombre": p.get("nombre"), "estado": estado,
                      "probabilidad": p.get("probabilidad_aprobar"),
                      "nota_acumulada": p.get("nota_acumulada"),
                      "proyeccion": (p.get("escenarios") or {}).get("ritmo_actual"),
                      "necesita": p.get("nota_necesaria_resto"),
                      "asistencia_pct": p["asistencia"].get("pct"),
                      "reprueba_asistencia": p["asistencia"].get("reprueba")})
    en_riesgo = sum(v for k, v in conteo.items() if k in ("En riesgo", "Crítico", "Muy difícil",
                                                          "Reprueba por asistencia", "Reprobado proyectado"))
    return {"course_id": str(course_id), "curso": c.name, "tipo": c.tipo, "parametrizado": True,
            "n_estudiantes": len(ests), "conteo_estados": conteo,
            "prob_promedio": round(sum(probs) / len(probs)) if probs else None,
            "en_riesgo": en_riesgo, "estudiantes": filas}
