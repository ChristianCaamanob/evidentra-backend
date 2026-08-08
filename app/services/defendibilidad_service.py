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


def evaluar(tipo: str, datos: dict | None, pregunta: str | None) -> dict:
    d = datos or {}
    if tipo == "revision":
        crit = _criterios_revision(d, pregunta)
    elif tipo == "experimental":
        crit = _criterios_experimental(d, pregunta)
    else:
        crit = _criterios_datos(d, pregunta)
    peso_tot = sum(c["peso"] for c in crit) or 1
    logrado = sum(c["peso"] * (1.0 if c["estado"] == "completo" else (0.5 if c["estado"] == "parcial" else 0.0)) for c in crit)
    puntaje = round(logrado / peso_tot * 10, 1)
    progreso = round(logrado / peso_tot * 100)
    completos = [c for c in crit if c["estado"] == "completo"]
    etapa = completos[-1]["fase"] if completos else "Sin iniciar"
    prox = next((c for c in crit if c["estado"] != "completo"), None)
    proximo_paso = ({"criterio": prox["id"], "label": prox["label"], "detalle": prox["detalle"], "fase": prox["fase"]}
                    if prox else {"criterio": None, "label": "Estudio defendible en todos los criterios", "detalle": "Prepara el borrador para la revista objetivo.", "fase": "Reporte"})
    # Libro Mayor liviano: artefactos presentes en datos (procedencia por fase). Sin hash (no se persiste snapshot aún).
    ledger = [{"clave": k, "label": lab, "plano": plano}
              for k, (lab, plano) in _ARTEFACTOS.items() if _has(d, k)]
    return {"version": CRITERIOS_VERSION, "tipo": tipo, "puntaje": puntaje, "progreso": progreso,
            "etapa": etapa, "criterios": crit, "proximo_paso": proximo_paso, "libro_mayor": ledger}
