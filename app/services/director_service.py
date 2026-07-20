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
