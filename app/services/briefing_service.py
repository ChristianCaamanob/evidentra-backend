"""
Informes/briefings diferenciados sobre resultados verificados (Fase 4).

Cierra el ciclo evaluación → nota → inteligencia con DOS productos:
  1. Briefing por ESTUDIANTE — retroalimentación formativa personalizada, centrada en las
     BRECHAS por resultado de aprendizaje / competencia (no solo la nota), con estrategias.
  2. Informe único del CURSO para el DOCENTE — métricas INTERPRETADAS (no repetidas), brechas
     por RA, ítems críticos, propuestas de mejora y estrategias didácticas para los contenidos
     débiles, de cara al avance del curso.

Ambos se ADAPTAN al tipo (solemne/certamen/…) y a la modalidad (desarrollo/selección/oral).
Línea roja: usan SOLO los datos dados; no inventan cifras, RA ni logros. Sin clave de IA caen
a un armado determinista con los mismos datos. La nota es del docente (G1); el informe orienta.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MODELO = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

_TIPO_TXT = {
    "solemne": "una SOLEMNE (evaluación sumativa de alto impacto en la nota final)",
    "certamen": "un CERTAMEN (evaluación sumativa de alto impacto)",
    "prueba": "una prueba",
    "control": "un control (evaluación breve y focalizada)",
}
_MOD_TXT = {
    "alternativas": ("de SELECCIÓN ÚNICA (ítems de alternativas corregidos contra la pauta)",
                     "tus respuestas marcadas"),
    "desarrollo": ("de DESARROLLO (respuestas abiertas evaluadas con rúbrica por criterios)",
                   "tus respuestas y los criterios de la rúbrica"),
    "mixta": ("MIXTA (alternativas + desarrollo por rúbrica)", "tus respuestas y criterios"),
    "oral": ("de EXPOSICIÓN/DISERTACIÓN ORAL (evaluada con rúbrica de criterios, con parte "
             "grupal e individual)", "tu disertación y los criterios de la rúbrica (grupales e individuales)"),
}


def _contexto(tipo, modalidad):
    tipo = (tipo or "").lower().strip()
    mod = (modalidad or "").lower().strip()
    tt = _TIPO_TXT.get(tipo, "una evaluación")
    mt, voc = _MOD_TXT.get(mod, ("", "tus respuestas"))
    marco = "Es " + tt + (", " + mt if mt else "") + "."
    return marco, voc


def _llm(sistema: str, usuario: str, max_tokens: int = 1100) -> str | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        cliente = anthropic.Anthropic()
        with cliente.messages.stream(model=MODELO, max_tokens=max_tokens, system=sistema,
                                     messages=[{"role": "user", "content": usuario}]) as st:
            final = st.get_final_message()
        for b in final.content:
            if getattr(b, "type", None) == "text" and b.text.strip():
                return b.text.strip()
    except Exception as e:
        logger.warning("Informe cayó a plantilla: %s", str(e)[:150])
    return None


def _nombres_ra(items: list) -> list[str]:
    out = []
    for g in items or []:
        n = g.get("nombre") or g.get("ra") or g.get("titulo") or g.get("clave")
        if n:
            out.append(str(n))
    return out


# ─────────────────────────────── ESTUDIANTE ───────────────────────────────
def briefing_estudiante(datos: dict, tipo: str | None = None, modalidad: str | None = None) -> dict:
    """Briefing personalizado centrado en brechas por RA/competencia, con estrategias."""
    resumen = datos.get("resumen", {}) or {}
    brechas = datos.get("brechas", []) or []
    fortalezas = datos.get("fortalezas", []) or []
    dist = datos.get("distribucion_curso", {}) or {}
    est = datos.get("estudiante") if isinstance(datos.get("estudiante"), dict) else {}
    nombre = (est or {}).get("nombre")
    marco, voc = _contexto(tipo, modalidad)

    sistema = (
        "Eres un docente que redacta retroalimentación formativa para UN estudiante, en español, "
        "cercana y constructiva. " + marco + " Céntrate en las BRECHAS por resultado de "
        "aprendizaje / competencia / habilidad (no solo en la nota). Estructura en 3 bloques con "
        "subtítulos en negrita Markdown: **Lo que lograste** (RA/habilidades dominadas, citando "
        "los datos); **Lo que conviene reforzar** (los RA con brecha, explicando por qué importan "
        "para lo que viene en el curso); **Cómo avanzar** (2-4 estrategias de estudio CONCRETAS y "
        "accionables por cada RA débil: qué hacer, cómo, con qué tipo de recurso o ejercicio). "
        "Habla de " + voc + " según corresponda. Reglas: usa SOLO los datos dados; NO inventes "
        "notas, %, RA ni contenidos; tono respetuoso y motivador; ~200-320 palabras."
    )
    usuario = (
        "ESTUDIANTE: " + (nombre or "(seudonimizado)") + "\n"
        "Nota: " + str(resumen.get("nota", "—")) + " · "
        + str(resumen.get("correctas", "?")) + " correctas, "
        + str(resumen.get("incorrectas", "?")) + " incorrectas, "
        + str(resumen.get("omitidas", "?")) + " omitidas.\n"
        "Posición en el curso: percentil " + str(resumen.get("percentil", dist.get("percentil", "—")))
        + " (promedio del curso: " + str(dist.get("promedio", "—")) + "%).\n"
        "RA/COMPETENCIAS LOGRADAS: " + (", ".join(_nombres_ra(fortalezas)) or "—") + "\n"
        "RA/COMPETENCIAS CON BRECHA (por reforzar): " + (", ".join(_nombres_ra(brechas)) or "—") + "\n"
    )
    texto = _llm(sistema, usuario, max_tokens=900)
    if texto:
        return {"briefing": texto, "motor": "IA (" + MODELO + ")"}

    fo, br = _nombres_ra(fortalezas), _nombres_ra(brechas)
    partes = ["**Lo que lograste.** Obtuviste una nota de " + str(resumen.get("nota", "—")) + " con "
              + str(resumen.get("correctas", "?")) + " respuestas correctas."
              + (" Dominaste: " + ", ".join(fo[:5]) + "." if fo else "")]
    if br:
        partes.append("\n\n**Lo que conviene reforzar.** " + ", ".join(br[:5]) + ".")
        partes.append("\n\n**Cómo avanzar.** Repasa esos resultados de aprendizaje con ejercicios "
                      "similares, identifica dónde te equivocaste y consulta tus dudas antes de la "
                      "próxima unidad, que se apoya en estos contenidos.")
    else:
        partes.append("\n\n**Cómo avanzar.** No se detectaron brechas marcadas; mantén el ritmo y "
                      "profundiza en lo que te interese.")
    return {"briefing": "".join(partes), "motor": "plantilla determinista"}


# ─────────────────────────────── CURSO (DOCENTE) ───────────────────────────────
def briefing_curso(metricas: dict, por_ra: list, items_dificiles: list,
                   tipo: str | None = None, modalidad: str | None = None) -> dict:
    """Informe integral para el docente: métricas interpretadas + brechas + estrategias."""
    marco, _ = _contexto(tipo, modalidad)
    m = metricas or {}
    ra_txt = "; ".join(
        str(g.get("clave", "?")) + ": " + str(g.get("logro_promedio", "?")) + "% ("
        + str(g.get("items", "?")) + " ítems)"
        for g in (por_ra or [])) or "—"

    sistema = (
        "Eres un asesor pedagógico experto en evaluación. Redactas UN informe integral para EL "
        "DOCENTE sobre el desempeño del curso, en español. " + marco + " No te limites a repetir "
        "las cifras: INTERPRÉTALAS (qué significan para el aprendizaje). Estructura con subtítulos "
        "en negrita Markdown:\n"
        "**Panorama del curso** — nivel de logro general, dispersión y forma de la distribución; "
        "qué dice sobre cómo aprendió el grupo (homogéneo/heterogéneo, cola de rezago, techo).\n"
        "**Brechas por resultado de aprendizaje** — qué RA/competencias dominó el curso y cuáles "
        "quedaron débiles, con lectura pedagógica de por qué (prioriza los de menor logro).\n"
        "**Ítems críticos** — los de menor acierto y qué concepción errónea o dificultad sugieren.\n"
        "**Propuestas de mejora** — acciones para el avance de los contenidos del curso, "
        "priorizadas.\n"
        "**Estrategias para los contenidos débiles** — 3-5 estrategias didácticas CONCRETAS "
        "(actividades, secuencia, evaluación formativa, agrupamientos) para abordar los RA débiles.\n"
        "Reglas: usa SOLO los datos dados; NO inventes cifras ni RA; específico y accionable; "
        "~350-550 palabras."
    )
    usuario = (
        "CURSO — n=" + str(m.get("n", "?")) + " estudiantes.\n"
        "Promedio: " + str(m.get("promedio", "—")) + "% · mediana: " + str(m.get("mediana", "—")) + "%"
        + " · desviación: " + str(m.get("desviacion", "—")) + " pts%"
        + " · rango: " + str(m.get("minimo", "—")) + "–" + str(m.get("maximo", "—")) + "%.\n"
        "Aprobación: " + (str(m.get("aprobacion_pct")) + "%" if m.get("aprobacion_pct") is not None else "—")
        + " · forma de la distribución: " + str(m.get("forma", "—")) + ".\n"
        "Logro por resultado de aprendizaje (RA: % logro): " + ra_txt + "\n"
        "Ítems más difíciles (menor acierto): " + ("; ".join(str(i) for i in (items_dificiles or [])[:10]) or "—") + "\n"
    )
    texto = _llm(sistema, usuario, max_tokens=1400)
    if texto:
        return {"briefing": texto, "motor": "IA (" + MODELO + ")"}

    debiles = [g for g in (por_ra or []) if g.get("logro_promedio", 100) < 60]
    partes = ["**Panorama del curso.** El curso promedió " + str(m.get("promedio", "—")) + "% (mediana "
              + str(m.get("mediana", "—")) + "%)"
              + (", con " + str(m.get("aprobacion_pct")) + "% de aprobación" if m.get("aprobacion_pct") is not None else "")
              + ". Dispersión " + str(m.get("desviacion", "—")) + " pts%: distribución " + str(m.get("forma", "—")) + "."]
    if debiles:
        partes.append("\n\n**Brechas por resultado de aprendizaje.** Prioriza: "
                      + ", ".join(str(g.get("clave")) + " (" + str(g.get("logro_promedio")) + "%)" for g in debiles[:6]) + ".")
    if items_dificiles:
        partes.append("\n\n**Ítems críticos.** Revisa " + ", ".join(str(i) for i in items_dificiles[:6])
                      + " y sus distractores para detectar concepciones erróneas.")
    partes.append("\n\n**Estrategias.** Reenseña los contenidos débiles con ejemplos contrastantes, "
                  "trabajo entre pares heterogéneos y un control formativo breve antes de avanzar.")
    return {"briefing": "".join(partes), "motor": "plantilla determinista"}
