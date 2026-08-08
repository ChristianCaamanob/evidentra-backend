"""
Motor de DEFENDIBILIDAD metodológica (Investigator Handoff v2 · el "fondo", no la forma).

Evalúa criterios VERSIONADOS contra el estado REAL del proyecto (`Proyecto.datos`, lo que el taller persiste)
y devuelve: puntaje 0–10, desglose por criterio (completo/parcial/pendiente + detalle + peso + fase), etapa
alcanzada, progreso %, próximo paso (primer criterio no cumplido) y un Libro Mayor liviano (artefactos presentes
con su fase). NO inventa: si un artefacto no existe en `datos`, el criterio queda 'pendiente'. Server-side y versionado
para que "la evidencia decida" y el puntaje sea auditable, no decorativo.
"""
from __future__ import annotations

CRITERIOS_VERSION = "defendibilidad-v1"


def _has(d: dict, *keys) -> bool:
    """True si alguna de las claves existe en datos con contenido real (lista/dict no vacío o texto)."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, (list, dict)):
            if len(v) > 0:
                return True
        elif isinstance(v, str):
            if v.strip():
                return True
        elif v:
            return True
    return False


def _crib_estado(d: dict) -> str:
    """Cribado: 'completo' si hay decisiones Y segundo revisor independiente; 'parcial' si solo un revisor."""
    crib = d.get("cribado") or {}
    crib_b = d.get("cribado_b") or {}
    if crib and crib_b:
        return "completo"
    if crib:
        return "parcial"
    return "pendiente"


def _criterios_revision(d: dict, pregunta: str | None) -> list[dict]:
    return [
        {"id": "pregunta", "fase": "Protocolo", "peso": 1, "label": "Pregunta enmarcada",
         "estado": "completo" if (pregunta and pregunta.strip()) else "pendiente",
         "detalle": "La pregunta de revisión está declarada." if pregunta else "Falta declarar la pregunta (PICO)."},
        {"id": "protocolo", "fase": "Protocolo", "peso": 2, "label": "Protocolo registrado",
         "estado": "completo" if _has(d, "protocolo", "prospero") else "pendiente",
         "detalle": "Protocolo/PROSPERO con contenido." if _has(d, "protocolo", "prospero") else "Registra el protocolo antes de cribar."},
        {"id": "busqueda", "fase": "Búsqueda", "peso": 2, "label": "Búsqueda reproducible",
         "estado": "completo" if _has(d, "estrategia", "searchtable") else "pendiente",
         "detalle": "Estrategia/tabla de búsqueda archivada." if _has(d, "estrategia", "searchtable") else "Documenta la estrategia de búsqueda por base."},
        {"id": "corpus", "fase": "Búsqueda", "peso": 1, "label": "Corpus identificado",
         "estado": "completo" if _has(d, "corpus") else "pendiente",
         "detalle": (str(len(d.get("corpus") or [])) + " registros en el corpus.") if _has(d, "corpus") else "Aún no hay corpus de registros."},
        {"id": "cribado", "fase": "Cribado", "peso": 2, "label": "Cribado independiente",
         "estado": _crib_estado(d),
         "detalle": {"completo": "Cribado con doble revisor.", "parcial": "Solo un revisor; añade el segundo para independencia.", "pendiente": "Aún sin cribado."}[_crib_estado(d)]},
        {"id": "extraccion", "fase": "Extracción", "peso": 1, "label": "Extracción de datos",
         "estado": "completo" if _has(d, "extraccion") else "pendiente",
         "detalle": "Formulario de extracción con datos." if _has(d, "extraccion") else "Extrae los datos de los estudios incluidos."},
        {"id": "rob", "fase": "Sesgo", "peso": 2, "label": "Evaluación de sesgo (ROB-2)",
         "estado": "completo" if _has(d, "rob2") else "pendiente",
         "detalle": "Riesgo de sesgo evaluado." if _has(d, "rob2") else "Evalúa el riesgo de sesgo de los incluidos."},
        {"id": "sintesis", "fase": "Síntesis", "peso": 2, "label": "Síntesis / metaanálisis",
         "estado": "completo" if _has(d, "meta") else "pendiente",
         "detalle": "Metaanálisis calculado." if _has(d, "meta") else "Sintetiza los resultados (meta o narrativa)."},
        {"id": "prisma", "fase": "Reporte", "peso": 1, "label": "Diagrama PRISMA",
         "estado": "completo" if _has(d, "prisma") else "pendiente",
         "detalle": "Flujo PRISMA construido." if _has(d, "prisma") else "Arma el diagrama de flujo PRISMA."},
    ]


def _criterios_datos(d: dict, pregunta: str | None) -> list[dict]:
    return [
        {"id": "pregunta", "fase": "Diseño", "peso": 1, "label": "Pregunta enmarcada",
         "estado": "completo" if (pregunta and pregunta.strip()) else "pendiente",
         "detalle": "Pregunta declarada." if pregunta else "Declara la pregunta de investigación."},
        {"id": "fuente", "fase": "Datos", "peso": 2, "label": "Fuente de datos vinculada",
         "estado": "completo" if _has(d, "course_ids", "assessment_ids") else "pendiente",
         "detalle": "Cursos/evaluaciones vinculados." if _has(d, "course_ids", "assessment_ids") else "Vincula al menos un curso o evaluación."},
        {"id": "grupos", "fase": "Datos", "peso": 1, "label": "Grupos / comparación",
         "estado": "completo" if _has(d, "grupos") else "pendiente",
         "detalle": "Grupos definidos." if _has(d, "grupos") else "Define grupos si tu diseño los compara (opcional)."},
        {"id": "variables", "fase": "Análisis", "peso": 2, "label": "Variables definidas",
         "estado": "completo" if _has(d, "variables") else "pendiente",
         "detalle": "Variables del estudio definidas." if _has(d, "variables") else "Define las variables a analizar."},
        {"id": "analisis", "fase": "Análisis", "peso": 2, "label": "Análisis ejecutado",
         "estado": "completo" if _has(d, "seleccionados", "extraccion") else "pendiente",
         "detalle": "Hay resultados de análisis." if _has(d, "seleccionados", "extraccion") else "Ejecuta el análisis sobre los datos vinculados."},
    ]


def _criterios_experimental(d: dict, pregunta: str | None) -> list[dict]:
    exp = d.get("experimental") or {}
    return [
        {"id": "pregunta", "fase": "Diseño", "peso": 1, "label": "Pregunta / PICO",
         "estado": "completo" if (pregunta and pregunta.strip()) else "pendiente",
         "detalle": "Pregunta declarada." if pregunta else "Declara la pregunta o PICO."},
        {"id": "diseno", "fase": "Diseño", "peso": 2, "label": "Diseño del estudio",
         "estado": "completo" if (isinstance(exp, dict) and exp) else "pendiente",
         "detalle": "Diseño configurado." if exp else "Configura el diseño (experimental/observacional)."},
        {"id": "protocolo", "fase": "Protocolo", "peso": 2, "label": "Protocolo / registro",
         "estado": "completo" if _has(d, "protocolo") else "pendiente",
         "detalle": "Protocolo con contenido." if _has(d, "protocolo") else "Registra el protocolo del estudio."},
        {"id": "variables", "fase": "Medición", "peso": 1, "label": "Variables / instrumentos",
         "estado": "completo" if _has(d, "variables") else "pendiente",
         "detalle": "Variables definidas." if _has(d, "variables") else "Define variables e instrumentos."},
        {"id": "reporte", "fase": "Reporte", "peso": 1, "label": "Reporte (CONSORT/STROBE)",
         "estado": "completo" if _has(d, "manuscrito") else "pendiente",
         "detalle": "Borrador de reporte iniciado." if _has(d, "manuscrito") else "Prepara el borrador con la guía de reporte."},
    ]


_ARTEFACTOS = {  # para el Libro Mayor: clave en datos → etiqueta legible + método/plano
    "protocolo": ("Protocolo", "método"), "estrategia": ("Estrategia de búsqueda", "método"),
    "searchtable": ("Tabla de búsqueda", "método"), "corpus": ("Corpus de registros", "fuente"),
    "cribado": ("Cribado", "método"), "cribado_b": ("Segundo revisor", "método"),
    "extraccion": ("Extracción de datos", "fuente"), "rob2": ("Riesgo de sesgo (ROB-2)", "método"),
    "meta": ("Metaanálisis", "método"), "prisma": ("Diagrama PRISMA", "reporte"),
    "manuscrito": ("Manuscrito", "reporte"), "variables": ("Variables", "método"),
    "experimental": ("Diseño experimental", "método"),
}


# Destino de drill-down: cada CRITERIO → subpestaña real del taller de su tipo (para "abrir el desglose", spec pto.8).
# revisión → rsSub(...) · datos → pjdTab(...) · experimental → expwTab(...)  (el frontend resuelve el prefijo)
_OBJETIVO = {
    "revision": {"pregunta": "protocolo", "protocolo": "protocolo", "busqueda": "corpus", "corpus": "corpus",
                 "cribado": "corpus", "extraccion": "extraccion", "rob": "rob2", "sintesis": "meta", "prisma": "prisma"},
    "datos": {"pregunta": "analisis", "fuente": "analisis", "grupos": "analisis", "variables": "analisis", "analisis": "analisis"},
    "experimental": {"pregunta": "diseno", "diseno": "diseno", "protocolo": "protocolo", "variables": "datos", "reporte": "reporte"},
}
# Chip del Libro Mayor (clave en `datos`) → subpestaña, por tipo de proyecto.
_OBJ_ARTEFACTO = {
    "revision": {"protocolo": "protocolo", "estrategia": "corpus", "searchtable": "corpus", "corpus": "corpus",
                 "cribado": "corpus", "cribado_b": "corpus", "extraccion": "extraccion", "rob2": "rob2",
                 "meta": "meta", "prisma": "prisma", "manuscrito": "manuscrito", "variables": "variables"},
    "datos": {"estrategia": "biblio", "searchtable": "biblio", "corpus": "biblio", "cribado": "biblio", "cribado_b": "biblio",
              "protocolo": "analisis", "extraccion": "analisis", "meta": "analisis", "prisma": "analisis",
              "manuscrito": "analisis", "variables": "analisis"},
    "experimental": {"corpus": "biblio", "estrategia": "biblio", "cribado": "biblio", "cribado_b": "biblio",
                     "protocolo": "protocolo", "experimental": "diseno", "variables": "datos", "extraccion": "datos",
                     "meta": "analisis", "prisma": "analisis", "manuscrito": "manuscrito"},
}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pl(n: int, sing: str, plur: str | None = None) -> str:
    """'1 registro' / '3 registros' — concordancia singular/plural."""
    return str(n) + " " + (sing if n == 1 else (plur or (sing + "s")))


def _kappa(a: dict, b: dict):
    """κ de Cohen sobre las decisiones compartidas de dos revisores (dicts DOI→decisión)."""
    keys = [k for k in a if k in b and a[k] and b[k]]
    n = len(keys)
    if n == 0:
        return None
    cats = set(a[k] for k in keys) | set(b[k] for k in keys)
    po = sum(1 for k in keys if a[k] == b[k]) / n
    pe = sum((sum(1 for k in keys if a[k] == c) / n) * (sum(1 for k in keys if b[k] == c) / n) for c in cats)
    kap = 1.0 if pe >= 1 else (po - pe) / (1 - pe)
    return {"kappa": round(kap, 2), "n": n}


def _metricas_revision(d: dict) -> dict:
    """Números REALES por criterio (no inventa: si el dato no está, no hay métrica)."""
    m = {}
    corpus = d.get("corpus") or []
    if corpus:
        m["corpus"] = _pl(len(corpus), "registro")
    est = d.get("estrategia") or {}
    blocks = est.get("blocks") if isinstance(est, dict) else None
    if isinstance(blocks, list) and blocks:
        m["busqueda"] = _pl(len(blocks), "bloque booleano", "bloques booleanos")
    crib = d.get("cribado") or {}
    crib_b = d.get("cribado_b") or {}
    if crib:
        inc = sum(1 for v in crib.values() if v == "incluir")
        if crib_b:
            k = _kappa(crib, crib_b)
            pre = ("κ=" + str(k["kappa"]) + " (n=" + str(k["n"]) + ") · ") if k else ""
            m["cribado"] = pre + _pl(inc, "incluido") + " de " + str(len(crib))
        else:
            m["cribado"] = _pl(len(crib), "decidido") + " · " + _pl(inc, "incluido") + " · 1 revisor"
    ext = d.get("extraccion") or {}
    if ext:
        m["extraccion"] = _pl(len(ext), "estudio extraído", "estudios extraídos")
    rob = (d.get("rob2") or {}).get("studies") or []
    if rob:
        m["rob"] = _pl(len(rob), "estudio evaluado", "estudios evaluados")
    res = (d.get("meta") or {}).get("resumen") or {}
    if res:
        parts = []
        med = str(res.get("medida") or (d.get("meta") or {}).get("medida") or "").upper()
        if res.get("k") is not None:
            parts.append("k=" + str(res["k"]))
        est_v = _num(res.get("estimador"))
        if est_v is not None:
            parts.append(((med + " ") if med else "") + str(round(est_v, 2)))
        if res.get("I2") is not None:
            parts.append("I²=" + str(res["I2"]) + "%")
        if parts:
            m["sintesis"] = " · ".join(parts)
    prisma = d.get("prisma") or {}
    if prisma:
        ch = prisma.get("checklist") or {}
        modo = prisma.get("modo")
        m["prisma"] = (("modo " + str(modo).upper() + " · ") if modo else "") + _pl(len(ch), "ítem de checklist", "ítems de checklist")
    return m


def _metricas_datos(d: dict) -> dict:
    m = {}
    ci, ai = d.get("course_ids") or [], d.get("assessment_ids") or []
    if ci or ai:
        m["fuente"] = _pl(len(ci), "curso") + " · " + _pl(len(ai), "evaluación", "evaluaciones")
    g = d.get("grupos") or []
    if g:
        m["grupos"] = _pl(len(g), "grupo")
    v = d.get("variables") or {}
    vlist = v.get("list") if isinstance(v, dict) else (v if isinstance(v, list) else None)
    if isinstance(vlist, list) and vlist:
        m["variables"] = _pl(len(vlist), "variable")
    return m


def _metricas_experimental(d: dict) -> dict:
    m = {}
    v = d.get("variables") or {}
    vlist = v.get("list") if isinstance(v, dict) else (v if isinstance(v, list) else None)
    if isinstance(vlist, list) and vlist:
        m["variables"] = _pl(len(vlist), "variable")
    return m


def evaluar(tipo: str, datos: dict | None, pregunta: str | None) -> dict:
    d = datos or {}
    if tipo == "revision":
        crit = _criterios_revision(d, pregunta)
        met = _metricas_revision(d)
    elif tipo == "experimental":
        crit = _criterios_experimental(d, pregunta)
        met = _metricas_experimental(d)
    else:
        crit = _criterios_datos(d, pregunta)
        met = _metricas_datos(d)
    _obj = _OBJETIVO.get(tipo, {})
    for c in crit:
        c["objetivo"] = _obj.get(c["id"])   # None si el taller de ese tipo no tiene subpestaña mapeada
        c["metrica"] = met.get(c["id"])     # número real (κ, I², incluidos…) o None si no aplica
    peso_tot = sum(c["peso"] for c in crit) or 1
    logrado = sum(c["peso"] * (1.0 if c["estado"] == "completo" else (0.5 if c["estado"] == "parcial" else 0.0)) for c in crit)
    puntaje = round(logrado / peso_tot * 10, 1)
    progreso = round(logrado / peso_tot * 100)
    completos = [c for c in crit if c["estado"] == "completo"]
    etapa = completos[-1]["fase"] if completos else "Sin iniciar"
    prox = next((c for c in crit if c["estado"] != "completo"), None)
    proximo_paso = ({"criterio": prox["id"], "label": prox["label"], "detalle": prox["detalle"], "fase": prox["fase"], "objetivo": prox.get("objetivo")}
                    if prox else {"criterio": None, "label": "Estudio defendible en todos los criterios", "detalle": "Prepara el borrador para la revista objetivo.", "fase": "Reporte", "objetivo": ("manuscrito" if tipo == "revision" else None)})
    # Libro Mayor liviano: artefactos presentes en datos (procedencia por fase). Sin hash (no se persiste snapshot aún).
    # `objetivo` = subpestaña del taller para abrir el artefacto (drill-down); `n` = tamaño si es lista/dict.
    def _tam(v):
        return len(v) if isinstance(v, (list, dict)) else None
    _objart = _OBJ_ARTEFACTO.get(tipo, {})
    ledger = [{"clave": k, "label": lab, "plano": plano,
               "objetivo": _objart.get(k),
               "n": _tam(d.get(k))}
              for k, (lab, plano) in _ARTEFACTOS.items() if _has(d, k)]
    return {"version": CRITERIOS_VERSION, "tipo": tipo, "puntaje": puntaje, "progreso": progreso,
            "etapa": etapa, "criterios": crit, "proximo_paso": proximo_paso, "libro_mayor": ledger}
