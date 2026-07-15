"""
I4 - Analisis cualitativo para el modulo Investigador.

Dos capacidades que se potencian:

  1) mapa_concepciones: el PUENTE cuanti->cuali. Cada distractor (alternativa incorrecta)
     que un grupo elige con frecuencia no es ruido: revela una CONCEPCION ERRONEA
     especifica. Combina la prevalencia del distractor (dato) con el significado del
     contenido (que error implica elegir esa alternativa) para producir un mapa de
     concepciones por item, con prevalencia, severidad y RA afectado. Insumo directo para
     la reensenanza y para investigacion de errores frecuentes.

  2) codificacion_tematica: analisis tematico de respuestas de desarrollo siguiendo el
     marco de Braun & Clarke (codigos -> temas), con codebook (deductivo e inductivo),
     frecuencias y una rubrica de calidad. La asignacion de codigos es una tarea de
     modelo (seam LLM); se incluye un asignador por palabras clave como respaldo
     determinista para pruebas y uso sin modelo.

Gobernanza: trabaja sobre respuestas seudonimizadas (G2); el analisis es propositivo
(describe el error para ensenar, no etiqueta al estudiante).
"""
from __future__ import annotations

from collections import Counter

from app.services import consistencia_service


# ───────────────────────────────────────────── mixed-methods: joint display (CUALI ↔ CUANTI)
def _meta_inferencia(prev: float, p, pbis) -> str:
    """Integración: qué significa cruzar la prevalencia de la concepción (cuali) con la
    dificultad y la discriminación del ítem (cuanti)."""
    if p is None or pbis is None:
        return "Sin métricas del ítem para integrar; interpretar solo por prevalencia."
    disc_ok = pbis >= 0.20
    if prev >= 30 and disc_ok:
        return ("Concepción robusta y extendida sobre un ítem que discrimina: separa niveles de "
                "logro — foco prioritario de reenseñanza y buena candidata a variable de estudio.")
    if prev >= 30 and not disc_ok:
        return ("Muy prevalente pero el ítem discrimina poco: la alternativa puede ser ambigua o "
                "el ítem defectuoso — revisar el ítem antes de concluir que es una concepción real.")
    if prev < 30 and disc_ok:
        return ("Prevalencia moderada sobre un ítem que discrimina: concepción localizada pero "
                "informativa del nivel de logro.")
    return ("Prevalencia moderada y baja discriminación: señal débil; confirmar con más evidencia "
            "antes de accionar.")


def joint_display(concepciones: list[dict], items_ctt: list[dict], n_personas: int) -> dict:
    """Tabla de integración mixed-methods (Creswell & Plano Clark, 2018; Fetters et al., 2013):
    cada concepción (CUALI) junto a la dificultad y discriminación del ítem (CUANTI), con IC de
    estabilidad de la prevalencia y una meta-inferencia."""
    idx = {str(it.get("item")): it for it in items_ctt}
    filas = []
    for e in concepciones:
        it = idx.get(str(e.get("item")), {})
        p = it.get("dificultad_p")
        pbis = it.get("discriminacion_pbis")
        prev = e.get("prevalencia_pct", 0.0)
        k = round(prev / 100 * n_personas) if n_personas else 0
        est = consistencia_service.prevalencia_estable(k, n_personas)
        filas.append({
            "item": e.get("item"), "ra": e.get("ra"), "alternativa": e.get("alternativa"),
            "concepcion": e.get("concepcion"),
            "prevalencia_pct": prev, "prevalencia_ic95": est["ic95"],
            "prevalencia_estable": est["estable"],
            "dificultad_p": p, "nivel_dificultad": it.get("nivel_dificultad"),
            "discriminacion_pbis": pbis, "calidad_discriminacion": it.get("calidad_discriminacion"),
            "meta_inferencia": _meta_inferencia(prev, p, pbis),
        })
    n_estables = sum(1 for f in filas if f["prevalencia_estable"])
    return {
        "marco": "Joint display (integración mixed-methods)",
        "filas": filas,
        "n_estables": n_estables, "n_total": len(filas),
        "nota": ("Integra cada concepción (CUALI) con la dificultad y discriminación del ítem "
                 "(CUANTI). El IC95 (Wilson) indica si la prevalencia es estable o ruido muestral."),
        "referencias": ["Creswell & Plano Clark (2018)", "Fetters, Curry & Creswell (2013)",
                        "Guetterman, Fetters & Creswell (2015)"],
    }


# ───────────────────────────────────────────── 1) concepciones desde distractores
def mapa_concepciones(items_ctt: list[dict], contenido: dict, umbral_pct: float = 15.0) -> dict:
    """
    items_ctt: [{item, ra, distractores:{A:{pct, correcta}, ...}}]  (de curso_stats).
    contenido: {item: {"enunciado":..., "correcta":"X",
                       "concepciones": {"A":"que error implica elegir A", ...}}}.
    Devuelve, por cada distractor con prevalencia >= umbral, la concepcion erronea asociada.
    """
    entradas = []
    for it in items_ctt:
        cont = contenido.get(it["item"]) or contenido.get(str(it["item"])) or {}
        concs = cont.get("concepciones", {})
        for alt, d in it["distractores"].items():
            if d.get("correcta"):
                continue
            pct = d.get("pct", 0)
            if pct < umbral_pct:
                continue
            sev = "alta" if pct >= 30 else "media" if pct >= 20 else "baja"
            entradas.append({
                "item": it["item"], "ra": it.get("ra"),
                "alternativa": alt, "prevalencia_pct": pct, "severidad": sev,
                "concepcion": concs.get(alt) or f"Error asociado a elegir la alternativa {alt}.",
                "enunciado": cont.get("enunciado"),
            })
    entradas.sort(key=lambda e: -e["prevalencia_pct"])
    # agregacion por RA: cuantas concepciones y prevalencia media
    por_ra: dict[str, list] = {}
    for e in entradas:
        por_ra.setdefault(e["ra"] or "sin_ra", []).append(e["prevalencia_pct"])
    resumen_ra = [{"ra": ra, "concepciones": len(v),
                   "prevalencia_media": round(sum(v) / len(v), 1)} for ra, v in por_ra.items()]
    resumen_ra.sort(key=lambda x: -x["prevalencia_media"])
    texto = _interpretar_concepciones(entradas)
    return {"concepciones": entradas, "por_ra": resumen_ra,
            "n_concepciones": len(entradas), "interpretacion": texto,
            "gobernanza": "Describe el error para ensenar; no etiqueta al estudiante (postura propositiva)."}


def _interpretar_concepciones(entradas: list[dict]) -> str:
    if not entradas:
        return ("Ningun distractor supera el umbral de prevalencia: no hay concepciones "
                "erroneas extendidas detectables en este instrumento.")
    top = entradas[0]
    n_alta = sum(1 for e in entradas if e["severidad"] == "alta")
    return (f"Se identifican {len(entradas)} concepciones erroneas con prevalencia relevante "
            f"({n_alta} de severidad alta). La mas extendida esta en P{top['item']} "
            f"(alternativa {top['alternativa']}, {top['prevalencia_pct']}%): "
            f"{top['concepcion']} Conviene abordarla explicitamente en clase.")


# ───────────────────────────────────────────── 2) codificacion tematica (Braun & Clarke)
def _asignador_palabras_clave(codebook: list[dict]):
    """Respaldo determinista: asigna un codigo si aparece alguna de sus palabras clave."""
    def coder(texto: str) -> list[str]:
        t = (texto or "").lower()
        return [c["codigo"] for c in codebook
                if any(k.lower() in t for k in c.get("palabras_clave", []))]
    return coder


def codificacion_tematica(respuestas: list[dict], codebook: list[dict], coder=None) -> dict:
    """
    respuestas: [{"student_id":..., "texto":...}]. codebook: [{"codigo","definicion",
    "tipo":"deductivo"|"inductivo","tema","palabras_clave":[...]}].
    coder: callable(texto)->[codigos] (seam LLM). Por defecto usa palabras clave.
    """
    coder = coder or _asignador_palabras_clave(codebook)
    tema_de = {c["codigo"]: c.get("tema", "sin_tema") for c in codebook}
    codificadas = []
    conteo_cod: Counter = Counter()
    for r in respuestas:
        cods = coder(r.get("texto", ""))
        conteo_cod.update(cods)
        codificadas.append({"student_id": r.get("student_id"),
                            "codigos": cods, "temas": sorted({tema_de.get(c, "sin_tema") for c in cods})})
    # temas: frecuencia y codigos que los componen
    temas: dict[str, dict] = {}
    for c in codebook:
        tm = c.get("tema", "sin_tema")
        temas.setdefault(tm, {"tema": tm, "codigos": [], "frecuencia": 0})
        temas[tm]["codigos"].append(c["codigo"])
    for cod, n in conteo_cod.items():
        temas.setdefault(tema_de.get(cod, "sin_tema"), {"tema": tema_de.get(cod, "sin_tema"),
                                                          "codigos": [], "frecuencia": 0})
        temas[tema_de.get(cod, "sin_tema")]["frecuencia"] += n
    temas_l = sorted(temas.values(), key=lambda x: -x["frecuencia"])
    calidad = _rubrica_calidad(respuestas, codificadas, codebook, conteo_cod)
    return {"marco": "Braun & Clarke (analisis tematico)",
            "n_respuestas": len(respuestas),
            "codigos": [{"codigo": k, "frecuencia": v} for k, v in conteo_cod.most_common()],
            "temas": temas_l, "codificacion": codificadas, "calidad": calidad}


def _rubrica_calidad(respuestas, codificadas, codebook, conteo_cod) -> dict:
    n = len(respuestas)
    cubiertas = sum(1 for c in codificadas if c["codigos"])
    cobertura = round(cubiertas / n * 100, 1) if n else 0.0
    cod_usados = len(conteo_cod)
    cod_total = len(codebook)
    return {
        "cobertura_pct": cobertura,               # % de respuestas con al menos un codigo
        "codigos_usados": cod_usados, "codigos_totales": cod_total,
        "densidad": round(sum(conteo_cod.values()) / n, 2) if n else 0.0,
        "observacion": ("Cobertura suficiente." if cobertura >= 80
                        else "Cobertura baja: revisar el codebook o codificar mas inductivamente."),
    }
