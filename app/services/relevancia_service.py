"""
Sugerencia de relevancia: "¿por qué considerar este artículo en el estudio?".

Toma la línea/pregunta de investigación + el artículo (título + abstract reales de OpenAlex)
y devuelve 2–3 frases FUNDAMENTADAS EN EL ABSTRACT sobre el aporte potencial del artículo al
estudio. Línea roja: NO inventa hallazgos, cifras ni conclusiones; si el abstract no conecta
con la pregunta, lo dice con honestidad. Cae a una razón heurística determinista si no hay
clave de API o el modelo falla.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MODELO = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

_SISTEMA = (
    "Eres un metodólogo que asiste a un investigador en la selección de literatura. "
    "Dada la PREGUNTA/línea de investigación y un ARTÍCULO (título + abstract reales), explica "
    "en 2 o 3 frases, en español, por qué convendría (o no) considerar este artículo en el "
    "estudio. Reglas estrictas: (1) básate ÚNICAMENTE en lo que dice el abstract y el título; "
    "(2) NO inventes hallazgos, cifras, muestras ni conclusiones que no estén en el texto; "
    "(3) señala el vínculo concreto (constructo, población, método, instrumento o marco) con la "
    "pregunta; (4) si el abstract NO se relaciona claramente con la pregunta, dilo con franqueza "
    "y sugiere descartarlo. Sé específico y conciso; no uses viñetas ni encabezados; devuelve "
    "solo el párrafo, sin comillas."
)


def _heuristica(pregunta: str, titulo: str, abstract: str) -> str:
    """Razón determinista por solapamiento de términos, sin LLM."""
    import re

    def _toks(s: str) -> set[str]:
        return {w for w in re.findall(r"[a-záéíóúñ]{4,}", (s or "").lower())}

    stop = {"para", "sobre", "entre", "como", "esta", "este", "with", "from", "that",
            "this", "which", "study", "based", "using", "hacia", "según", "cuyo"}
    pq = _toks(pregunta) - stop
    comunes = sorted((pq & (_toks(titulo) | _toks(abstract))) - stop)[:6]
    if comunes:
        return ("Coincide con tu línea en: " + ", ".join(comunes) + ". Revisa el abstract para "
                "confirmar que el constructo, la población y el método sean compatibles con tu "
                "pregunta antes de incluirlo.")
    return ("No se detecta solapamiento léxico evidente con tu pregunta. Lee el abstract con "
            "atención: podría aportar por su marco o método, o convenir descartarlo si el tema "
            "no coincide.")


def sugerir(pregunta: str, titulo: str, abstract: str = "", meta: dict | None = None) -> dict:
    pregunta = (pregunta or "").strip()
    titulo = (titulo or "").strip()
    abstract = (abstract or "").strip()
    if not pregunta or not titulo:
        return {"sugerencia": "Falta la pregunta de investigación o el título del artículo.",
                "motor": "n/a"}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"sugerencia": _heuristica(pregunta, titulo, abstract),
                "motor": "heurística (sin IA)"}
    try:
        import anthropic

        ctx = ""
        if meta:
            piezas = []
            if meta.get("cuartil"):
                piezas.append("cuartil SJR " + str(meta["cuartil"]))
            if meta.get("anio"):
                piezas.append("año " + str(meta["anio"]))
            if meta.get("citas") is not None:
                piezas.append(str(meta["citas"]) + " citas")
            if piezas:
                ctx = " (Señales bibliométricas: " + "; ".join(piezas) + ".)"
        usuario = (
            "PREGUNTA/línea de investigación:\n" + pregunta + "\n\n"
            "ARTÍCULO\nTítulo: " + titulo + "\n"
            "Abstract: " + (abstract[:4000] if abstract else "(no disponible)") + ctx
        )
        cliente = anthropic.Anthropic()
        with cliente.messages.stream(model=MODELO, max_tokens=400, system=_SISTEMA,
                                     messages=[{"role": "user", "content": usuario}]) as st:
            final = st.get_final_message()
        texto = ""
        for b in final.content:
            if getattr(b, "type", None) == "text":
                texto = b.text.strip()
                break
        texto = texto.strip().strip('"').strip()
        if not texto:
            raise ValueError("respuesta vacía")
        return {"sugerencia": texto, "motor": "IA (" + MODELO + ")"}
    except Exception as e:
        logger.warning("Relevancia cayó a heurística: %s", str(e)[:150])
        return {"sugerencia": _heuristica(pregunta, titulo, abstract),
                "motor": "heurística (respaldo)"}
