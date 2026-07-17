"""
Generador de BRIEFINGS reales (feedback diferenciado) sobre resultados verificados.

Cierra el ciclo evaluación → nota → inteligencia: toma los datos REALES del informe
(`informe_service.build_datos`: nota, brechas y fortalezas por RA, posición en el curso) o
del curso completo, y redacta con el LLM un briefing personalizado, FUNDAMENTADO SOLO en
esos datos. Línea roja: no inventa cifras, RA ni logros; si no hay API key, cae a un
armado determinista con los mismos datos. La nota es del docente (G1); el briefing orienta.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MODELO = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

_SIS_ALUMNO = (
    "Eres un docente que redacta retroalimentación formativa para UN estudiante, en español, "
    "cercana y constructiva. Te doy datos REALES de su evaluación (nota, aciertos/errores, "
    "resultados de aprendizaje logrados y por reforzar, y su posición en el curso). Escribe un "
    "briefing de 2 a 3 párrafos breves: (1) reconoce lo logrado citando los RA/temas concretos "
    "en que le fue bien; (2) señala con precisión qué reforzar (los RA con brecha) y por qué "
    "importa; (3) da 2-3 pasos concretos de estudio. Reglas estrictas: usa SOLO los datos dados; "
    "NO inventes notas, porcentajes, RA ni contenidos que no aparezcan; tono motivador y "
    "respetuoso; sin viñetas rígidas ni encabezados; devuelve solo el texto."
)

_SIS_CURSO = (
    "Eres un asesor pedagógico que redacta un briefing para EL DOCENTE sobre el desempeño del "
    "curso en una evaluación, en español. Te doy datos REALES: distribución de notas, % de "
    "aprobación, ítems más difíciles y resultados de aprendizaje con brecha. Escribe 2 a 3 "
    "párrafos: (1) panorama del curso (dominio general y dispersión); (2) focos de reenseñanza "
    "priorizados por los RA/ítems con más brecha, con justificación; (3) 2-3 acciones concretas "
    "de remediación para la próxima clase. Reglas: usa SOLO los datos dados; NO inventes cifras "
    "ni RA; concreto y accionable; devuelve solo el texto, sin encabezados."
)


def _llm(sistema: str, usuario: str, max_tokens: int = 700) -> str | None:
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
        logger.warning("Briefing cayó a plantilla: %s", str(e)[:150])
    return None


def _nombres_ra(items: list, k: str = "ra") -> list[str]:
    out = []
    for g in items or []:
        n = g.get("nombre") or g.get(k) or g.get("ra") or g.get("titulo")
        if n:
            out.append(str(n))
    return out


def briefing_estudiante(datos: dict) -> dict:
    """Briefing personalizado desde `informe_service.build_datos`."""
    resumen = datos.get("resumen", {}) or {}
    brechas = datos.get("brechas", []) or []
    fortalezas = datos.get("fortalezas", []) or []
    dist = datos.get("distribucion_curso", {}) or {}
    nombre = datos.get("estudiante", {}).get("nombre") if isinstance(datos.get("estudiante"), dict) else None

    usuario = (
        "ESTUDIANTE: " + (nombre or "(seudonimizado)") + "\n"
        "Nota: " + str(resumen.get("nota", "—")) + " · "
        + str(resumen.get("correctas", "?")) + " correctas, "
        + str(resumen.get("incorrectas", "?")) + " incorrectas, "
        + str(resumen.get("omitidas", "?")) + " omitidas.\n"
        "Posición en el curso: percentil " + str(resumen.get("percentil", dist.get("percentil", "—")))
        + " (promedio del curso: " + str(dist.get("promedio", "—")) + "%).\n"
        "RA LOGRADOS (fortalezas): " + (", ".join(_nombres_ra(fortalezas)) or "—") + "\n"
        "RA POR REFORZAR (brechas): " + (", ".join(_nombres_ra(brechas)) or "—") + "\n"
    )
    texto = _llm(_SIS_ALUMNO, usuario)
    if texto:
        return {"briefing": texto, "motor": "IA (" + MODELO + ")"}

    # Respaldo determinista (mismos datos, sin IA).
    fo = _nombres_ra(fortalezas)
    br = _nombres_ra(brechas)
    partes = []
    partes.append("Obtuviste una nota de " + str(resumen.get("nota", "—")) + " con "
                  + str(resumen.get("correctas", "?")) + " respuestas correctas.")
    if fo:
        partes.append("Demostraste dominio en: " + ", ".join(fo[:4]) + ".")
    if br:
        partes.append("Conviene reforzar: " + ", ".join(br[:4])
                      + ". Repasa esos contenidos, resuelve ejercicios similares y consulta tus dudas en la próxima clase.")
    else:
        partes.append("No se detectaron brechas marcadas; mantén el ritmo y profundiza donde te interese.")
    return {"briefing": " ".join(partes), "motor": "plantilla determinista"}


def briefing_curso(distribucion: dict, items_dificiles: list, brechas_ra: list,
                   n_estudiantes: int, aprobacion_pct: float | None = None) -> dict:
    """Briefing para el docente sobre el curso completo."""
    usuario = (
        "CURSO — n=" + str(n_estudiantes) + " estudiantes.\n"
        "Promedio: " + str(distribucion.get("promedio", "—")) + "% · mediana: "
        + str(distribucion.get("mediana", "—")) + "%"
        + (" · aprobación: " + str(aprobacion_pct) + "%" if aprobacion_pct is not None else "") + ".\n"
        "Ítems más difíciles (menor % de acierto): "
        + ("; ".join(str(i) for i in (items_dificiles or [])[:8]) or "—") + "\n"
        "RA con más brecha en el curso: " + (", ".join(brechas_ra or []) or "—") + "\n"
    )
    texto = _llm(_SIS_CURSO, usuario)
    if texto:
        return {"briefing": texto, "motor": "IA (" + MODELO + ")"}

    partes = ["El curso promedió " + str(distribucion.get("promedio", "—")) + "%"
              + (" con " + str(aprobacion_pct) + "% de aprobación" if aprobacion_pct is not None else "") + "."]
    if brechas_ra:
        partes.append("Los focos de reenseñanza prioritarios son: " + ", ".join(brechas_ra[:5]) + ".")
    if items_dificiles:
        partes.append("Revisa especialmente los ítems de menor logro y sus distractores para detectar concepciones erróneas.")
    return {"briefing": " ".join(partes), "motor": "plantilla determinista"}
