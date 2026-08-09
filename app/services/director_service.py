"""
P3 · Panorama del Director: agregado por Departamento/Facultad para decisiones estratégicas.

Cruza el logro por RA de cada estudiante (ficha_service.brechas_estudiante — deduplicado por
alumno, alternativas + desarrollo validado) y lo agrega por curso → departamento → facultad.
Agregado y seudonimizado (G2); orienta decisiones, no altera notas (G1).
"""
from __future__ import annotations

from collections import Counter

# Cohortes de psicometría (grandes, sintéticas): no son docencia real, se excluyen del panorama.
COHORTES_OCULTAS = {"DEMO-Q1", "DEMO-PSICO"}

SIN_FAC = "(sin facultad)"
SIN_DEP = "(sin departamento)"


def _agg(rows: list[dict]) -> dict:
    """Agrega una lista de resúmenes de curso: logro promedio PONDERADO por nº de evaluados,
    totales y las brechas por RA más frecuentes."""
    n_ev = sum(r["n_evaluados"] for r in rows)
    num = sum((r["logro_promedio"] or 0.0) * r["n_evaluados"]
              for r in rows if r["logro_promedio"] is not None)
    rc: Counter = Counter()
    for r in rows:
        rc.update(r["ra_brechas"])
    sem = {"verde": 0, "amarillo": 0, "rojo": 0}
    for r in rows:
        for k in sem:
            sem[k] += (r.get("semaforo") or {}).get(k, 0)
    return {
        "n_cursos": len(rows),
        "n_estudiantes": sum(r["n_estudiantes"] for r in rows),
        "n_evaluados": n_ev,
        "logro_promedio": round(num / n_ev, 1) if n_ev else None,
        "estudiantes_con_brecha": sum(r["estudiantes_con_brecha"] for r in rows),
        "semaforo": sem,
        "top_brechas": [{"code": k, "n": v} for k, v in rc.most_common(6)],
    }


def panorama(db, facultad: str | None = None, departamento: str | None = None,
             umbral_brecha: float = 60.0) -> dict:
    from app.models.course import Course
    from app.models.student import Student
    from app.services import ficha_service

    cursos = [c for c in db.query(Course).all() if c.code not in COHORTES_OCULTAS]
    # Opciones de filtro SIN filtrar (para poblar los selectores del Director aunque haya filtro activo).
    facs_todas = sorted({(c.facultad or SIN_FAC) for c in cursos})
    deps_por_fac: dict[str, set] = {}
    for c in cursos:
        deps_por_fac.setdefault(c.facultad or SIN_FAC, set()).add(c.departamento or SIN_DEP)
    opciones = {"facultades": facs_todas,
                "departamentos": {k: sorted(v) for k, v in deps_por_fac.items()}}
    if facultad:
        cursos = [c for c in cursos if (c.facultad or SIN_FAC) == facultad]
    if departamento:
        cursos = [c for c in cursos if (c.departamento or SIN_DEP) == departamento]

    resumen_cursos = []
    for c in cursos:
        estudiantes = db.query(Student).filter(Student.course_id == c.id).all()
        logros: list[float] = []
        con_brecha = 0
        ra_ct: Counter = Counter()
        sem = {"verde": 0, "amarillo": 0, "rojo": 0}   # semáforo por LOGRO del alumno (≥70/50-69/<50)
        for st in estudiantes:
            try:
                b = ficha_service.brechas_estudiante(db, c.id, st.rut, umbral_brecha=umbral_brecha)
            except Exception:  # noqa: BLE001  (un estudiante sin datos no rompe el panorama)
                continue
            evaluados = [r for r in b["por_ra"] if r["items_evaluados"]]
            if not evaluados:
                continue
            avg = sum(r["logro_pct"] for r in evaluados) / len(evaluados)
            logros.append(avg)
            sem["verde" if avg >= 70 else "amarillo" if avg >= 50 else "rojo"] += 1
            if b["brechas"]:
                con_brecha += 1
            for br in b["brechas"]:
                ra_ct[br["code"]] += 1
        resumen_cursos.append({
            "id": str(c.id), "curso": c.name, "code": c.code, "tipo": c.tipo,
            "facultad": c.facultad or SIN_FAC, "departamento": c.departamento or SIN_DEP,
            "n_estudiantes": len(estudiantes), "n_evaluados": len(logros),
            "logro_promedio": round(sum(logros) / len(logros), 1) if logros else None,
            "estudiantes_con_brecha": con_brecha,
            "semaforo": sem,
            "ra_brechas": dict(ra_ct),
            "top_brechas": [{"code": k, "n": v} for k, v in ra_ct.most_common(3)],
        })

    # Árbol facultad → departamento → cursos, con agregados en cada nivel.
    arbol: dict[str, dict[str, list]] = {}
    for r in resumen_cursos:
        arbol.setdefault(r["facultad"], {}).setdefault(r["departamento"], []).append(r)
    facultades = []
    for fname, deps in sorted(arbol.items()):
        dep_list = []
        for dname, rows in sorted(deps.items()):
            dep_list.append({"departamento": dname, **_agg(rows),
                             "cursos": sorted(rows, key=lambda x: x["curso"])})
        todos = [r for rows in deps.values() for r in rows]
        facultades.append({"facultad": fname, **_agg(todos), "departamentos": dep_list})

    return {
        "facultades": facultades,
        "global": _agg(resumen_cursos),
        "opciones": opciones,
        "filtros": {"facultad": facultad, "departamento": departamento,
                    "umbral_brecha": umbral_brecha},
        "gobernanza": "Agregado y seudonimizado (G2): logro por RA cruzado con la evidencia real, "
                      "deduplicado por estudiante (alternativas + desarrollo validado). Orienta "
                      "decisiones estratégicas; no altera notas (G1).",
    }


def panorama_export_payload(db, facultad=None, departamento=None, umbral_brecha=60.0) -> dict:
    """Documento exportable (Word/PDF/Excel) del panorama: una tabla resumen por facultad/
    departamento/curso + fila global."""
    p = panorama(db, facultad, departamento, umbral_brecha)

    def _fmt(v):
        return "—" if v is None else v

    filas = []
    for f in p["facultades"]:
        filas.append(["Facultad · " + f["facultad"], f["n_cursos"], f["n_estudiantes"],
                      f["n_evaluados"], _fmt(f["logro_promedio"]), f["estudiantes_con_brecha"],
                      ", ".join(b["code"] for b in f["top_brechas"][:4])])
        for d in f["departamentos"]:
            filas.append(["  Depto · " + d["departamento"], d["n_cursos"], d["n_estudiantes"],
                          d["n_evaluados"], _fmt(d["logro_promedio"]), d["estudiantes_con_brecha"],
                          ", ".join(b["code"] for b in d["top_brechas"][:4])])
            for c in d["cursos"]:
                filas.append(["    " + c["curso"] + " (" + (c["code"] or "") + ")", 1,
                              c["n_estudiantes"], c["n_evaluados"], _fmt(c["logro_promedio"]),
                              c["estudiantes_con_brecha"],
                              ", ".join(b["code"] for b in c["top_brechas"][:4])])
    g = p["global"]
    filas.append(["TOTAL", g["n_cursos"], g["n_estudiantes"], g["n_evaluados"],
                  _fmt(g["logro_promedio"]), g["estudiantes_con_brecha"],
                  ", ".join(b["code"] for b in g["top_brechas"][:4])])

    headers = ["Unidad", "Cursos", "Estudiantes", "Evaluados", "Logro %",
               "Con brecha", "RA con más brechas"]
    tabla = {"titulo": "Panorama por unidad", "headers": headers, "rows": filas}
    doc = {
        "titulo": "Panorama académico · Dirección",
        "secciones": [{"heading": "Resumen para decisiones estratégicas", "nivel": 1,
                       "texto": p["gobernanza"]}],
        "tablas": [tabla],
        "hojas": [{"nombre": "Panorama", "headers": headers, "rows": filas}],
    }
    return {"payload": doc, "panorama": p}


def departamento_calidad(db, departamento: str, facultad: str | None = None) -> dict:
    """SALA DE DEPARTAMENTO · Calidad de instrumentos agregada por el departamento.

    Recorre las evaluaciones (con pauta validada + evidencia) de los cursos del departamento y
    agrega su calidad psicométrica reutilizando ficha_service.analisis_evaluacion (dificultad,
    discriminación punto-biserial, distractores, alertas). NO altera notas (G1); lectura agregada.
    """
    from app.models.course import Course
    from app.models.assessment import Assessment
    from app.services import ficha_service

    cursos = [c for c in db.query(Course).all() if c.code not in COHORTES_OCULTAS]
    if facultad:
        cursos = [c for c in cursos if (c.facultad or SIN_FAC) == facultad]
    cursos = [c for c in cursos if (c.departamento or SIN_DEP) == departamento]

    difs: list[float] = []
    discrs: list[float] = []
    n_items = 0
    n_prob_disc = 0        # ítems que discriminan poco/al revés (r < 0.2)
    n_prob_dif = 0         # ítems con dificultad extrema (>90% o <25% de acierto)
    n_distractor = 0       # distractores que atraen más que la correcta
    alertas_crit = 0
    ra_cubiertos: set = set()
    evals: list[dict] = []
    cursos_con = set()
    n_scans_total = 0
    for c in cursos:
        asms = db.query(Assessment).filter(Assessment.course_id == c.id).all()
        for a in asms:
            try:
                an = ficha_service.analisis_evaluacion(db, a.id)
            except Exception:  # noqa: BLE001  (sin pauta válida / sin evidencia → no entra)
                continue
            por_item = an.get("por_item") or []
            if not por_item:
                continue
            cursos_con.add(str(c.id))
            e_dif = [it["pct"] for it in por_item if it.get("pct") is not None]
            e_dis = [it["discriminacion"] for it in por_item if it.get("discriminacion") is not None]
            e_prob = sum(1 for it in por_item if it.get("discriminacion") is not None and it["discriminacion"] < 0.2)
            e_probdif = sum(1 for it in por_item if it.get("pct") is not None and (it["pct"] > 90 or it["pct"] < 25))
            e_distr = sum(1 for dd in (an.get("distractores") or []) if dd.get("trampa"))
            e_crit = sum(1 for al in (an.get("alertas") or []) if al.get("severidad") == "critica")
            difs += e_dif
            discrs += e_dis
            n_items += len(por_item)
            n_prob_disc += e_prob
            n_prob_dif += e_probdif
            n_distractor += e_distr
            alertas_crit += e_crit
            for r in (an.get("por_ra") or []):
                if r.get("logro_pct") is not None:
                    ra_cubiertos.add(r.get("code"))
            tz = an.get("trazabilidad") or {}
            n_scans_total += tz.get("n_scans") or 0
            evals.append({
                "assessment_id": str(a.id), "curso": c.name, "curso_code": c.code, "curso_id": str(c.id),
                "prueba": an.get("prueba") or a.name, "n_estudiantes": (an.get("kpis") or {}).get("n_estudiantes"),
                "logro_pct": (an.get("kpis") or {}).get("logro_pct"),
                "dificultad_media": round(sum(e_dif) / len(e_dif), 1) if e_dif else None,
                "discriminacion_media": round(sum(e_dis) / len(e_dis), 2) if e_dis else None,
                "n_items": len(por_item), "items_problematicos": e_prob + e_probdif,
                "distractores_trampa": e_distr, "alertas_criticas": e_crit,
                "origen": tz.get("origen"), "n_scans": tz.get("n_scans"),
            })
    evals.sort(key=lambda e: (e["items_problematicos"] * -1, (e["discriminacion_media"] if e["discriminacion_media"] is not None else 1)))
    resumen = {
        "departamento": departamento, "facultad": facultad,
        "n_cursos": len(cursos), "n_cursos_con_evidencia": len(cursos_con),
        "n_evaluaciones": len(evals), "n_items": n_items,
        "dificultad_media": round(sum(difs) / len(difs), 1) if difs else None,
        "discriminacion_media": round(sum(discrs) / len(discrs), 2) if discrs else None,
        "items_problematicos": n_prob_disc + n_prob_dif,
        "pct_problematicos": round((n_prob_disc + n_prob_dif) / n_items * 100, 1) if n_items else None,
        "distractores_trampa": n_distractor, "alertas_criticas": alertas_crit,
        "ra_cubiertos": len(ra_cubiertos),
        "n_scans": n_scans_total,
    }
    return {"resumen": resumen, "evaluaciones": evals,
            "procedencia": {"fuente": "Centro de Análisis (OMR/en vivo) por evaluación con pauta validada",
                            "calculo": "dificultad = % de acierto; discriminación = punto-biserial ítem–total corregida",
                            "n_scans": n_scans_total, "nota": "Lectura agregada; no altera notas (G1)."}}


def departamento_profundo(db, departamento: str, facultad: str | None = None) -> dict:
    """Sala de Departamento (profundizar): BANCO de preguntas con calidad + MAPA de errores conceptuales.

    · Banco: cada ítem del departamento etiquetado por calidad (gold / a revisar / dificultad extrema / ok),
      reutilizando dificultad (pct) y discriminación (punto-biserial).
    · Errores: ítems donde un distractor ATRAE MÁS que la correcta = confusión conceptual sistemática.
    NO altera notas (G1); lectura agregada.
    """
    from app.models.course import Course
    from app.models.assessment import Assessment
    from app.services import ficha_service

    cursos = [c for c in db.query(Course).all() if c.code not in COHORTES_OCULTAS]
    if facultad:
        cursos = [c for c in cursos if (c.facultad or SIN_FAC) == facultad]
    cursos = [c for c in cursos if (c.departamento or SIN_DEP) == departamento]

    banco: list[dict] = []
    errores: list[dict] = []
    n_items = 0
    cont = {"gold": 0, "revisar": 0, "extremo": 0, "ok": 0}
    for c in cursos:
        for a in db.query(Assessment).filter(Assessment.course_id == c.id).all():
            try:
                an = ficha_service.analisis_evaluacion(db, a.id)
            except Exception:  # noqa: BLE001
                continue
            prueba = an.get("prueba") or a.name
            for it in (an.get("por_item") or []):
                pct = it.get("pct")
                dis = it.get("discriminacion")
                n_items += 1
                if dis is not None and dis >= 0.3 and pct is not None and 40 <= pct <= 75:
                    cal = "gold"
                elif dis is not None and dis < 0.2:
                    cal = "revisar"
                elif pct is not None and (pct > 90 or pct < 25):
                    cal = "extremo"
                else:
                    cal = "ok"
                cont[cal] += 1
                if len(banco) < 150:
                    banco.append({"curso": c.name, "curso_code": c.code, "curso_id": str(c.id),
                                  "prueba": prueba, "q": it.get("q"), "pct": pct,
                                  "discriminacion": dis, "calidad": cal})
            for dd in (an.get("distractores") or []):
                if not dd.get("trampa"):
                    continue
                ops = dd.get("opciones") or []
                to = next((o for o in ops if o.get("letra") == dd["trampa"]), None)
                co = next((o for o in ops if o.get("correcta")), None)
                if len(errores) < 150:
                    errores.append({"curso": c.name, "curso_code": c.code, "curso_id": str(c.id),
                                    "prueba": prueba, "q": dd.get("q"), "correcta": dd.get("correcta"),
                                    "trampa": dd.get("trampa"),
                                    "trampa_pct": (to["pct"] if to else None),
                                    "correcta_pct": (co["pct"] if co else None)})
    orden = {"revisar": 0, "extremo": 1, "gold": 2, "ok": 3}
    banco.sort(key=lambda x: (orden.get(x["calidad"], 9), (x["discriminacion"] if x["discriminacion"] is not None else 1)))
    errores.sort(key=lambda e: ((e["trampa_pct"] or 0) - (e["correcta_pct"] or 0)) * -1)
    return {
        "departamento": departamento,
        "banco": {"n_items": n_items, **cont, "items": banco},
        "errores": {"n": len(errores), "items": errores},
        "procedencia": {"fuente": "Centro de Análisis por evaluación con pauta validada",
                        "banco": "calidad = discriminación (punto-biserial) + dificultad (% acierto)",
                        "errores": "un distractor atrae MÁS que la correcta → confusión conceptual sistemática",
                        "nota": "Lectura agregada; no altera notas (G1)."},
    }
