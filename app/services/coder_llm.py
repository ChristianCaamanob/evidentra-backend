"""
Seam LLM de F2: convierte la parametrizacion docente (F1) en una correccion asistida por
un modelo de lenguaje, respetando G1 (la IA PROPONE, el docente decide).

Diseno en tres capas, para ser testeable sin API key y degradar con gracia:

  1. construir_prompt(respuesta, criterio)  -> (system, user)   [PURO, testeable]
       Traduce la rubrica a instrucciones: nivel de exigencia (estricto/tolerante/flexible),
       anclas de calibracion como few-shot, sinonimos, norma terminologica de la disciplina,
       politica ante lo creativo y lo fuera de alcance.
  2. parsear_respuesta(texto)               -> {nivel, confianza, evidencia, justificacion}
       Extrae y valida el JSON del modelo. Si no es parseable, lanza (para caer al fallback).
  3. coder_llm(llamar)                       -> callable compatible con el seam `coder` de F2.
       `llamar(system, user) -> str` se inyecta: por defecto usa el SDK de Anthropic con la
       ANTHROPIC_API_KEY del entorno; en tests se pasa un stub.

coder_llm_seguro envuelve todo y, ante cualquier error (sin key, timeout, JSON invalido),
cae al grader determinista por anclas de F2. coder_por_defecto elige LLM si hay key, si no
None (F2 usa su grader determinista).

Gobernanza: trabaja sobre respuestas seudonimizadas (G2); NO emite la nota (G1). El modelo
solo propone un nivel + evidencia + justificacion que el docente validara (F3).
"""
from __future__ import annotations

import json
import os

from app.models.answer_key import (
    EXIGENCIA_ESTRICTO, EXIGENCIA_TOLERANTE, EXIGENCIA_FLEXIBLE,
    LOGRO_LOGRADO, LOGRO_PARCIAL, LOGRO_NO,
)
from app.services import precalificacion_service

MODELO_DEFECTO = os.environ.get("EVALYS_CODER_MODEL", "claude-sonnet-5")

_REGLA_EXIGENCIA = {
    EXIGENCIA_ESTRICTO: (
        "EXIGENCIA ESTRICTA: exige el concepto correcto Y COMPLETO, con el termino canonico "
        "de la norma disciplinar. Si la idea aparece pero sin el termino de la norma, el nivel "
        "es 'parcial', no 'logrado'. No premies aproximaciones."),
    EXIGENCIA_TOLERANTE: (
        "EXIGENCIA TOLERANTE: premia la idea correcta aunque el fraseo varie; acepta sinonimos "
        "y equivalencias. Penaliza solo si el concepto esta ausente o equivocado."),
    EXIGENCIA_FLEXIBLE: (
        "EXIGENCIA FLEXIBLE: premia la comprension central. Ante un enfoque inesperado pero "
        "potencialmente valido, propone 'parcial' con confianza baja para que el docente lo "
        "revise, en vez de reprobar."),
}


def construir_prompt(respuesta: str, criterio: dict) -> tuple[str, str]:
    """Arma (system, user) desde la parametrizacion F1 del criterio. Funcion pura."""
    exig = criterio.get("nivel_exigencia", EXIGENCIA_TOLERANTE)
    norma = criterio.get("norma_terminologica")
    sinonimos = criterio.get("sinonimos") or []
    anclas = criterio.get("anclas") or []

    system = (
        "Eres un asistente de correccion academica. PROPONES una evaluacion; NO pones la nota "
        "(la decide el docente). Corriges UN criterio de una rubrica sobre una respuesta de "
        "desarrollo seudonimizada. Respondes SOLO con un objeto JSON, sin texto adicional.")

    partes = [
        f"CRITERIO A EVALUAR: {criterio.get('name') or criterio.get('nombre')}",
    ]
    if criterio.get("descriptor"):
        partes.append(f"Descriptor: {criterio['descriptor']}")
    partes.append(_REGLA_EXIGENCIA.get(exig, _REGLA_EXIGENCIA[EXIGENCIA_TOLERANTE]))
    if norma and exig == EXIGENCIA_ESTRICTO:
        partes.append(f"NORMA TERMINOLOGICA VIGENTE: usa como referencia la norma {norma}. "
                      f"El termino correcto es el de esa norma.")
    if sinonimos:
        partes.append("Terminos/equivalencias aceptables: " + ", ".join(sinonimos) + ".")
    if criterio.get("fuera_de_alcance"):
        partes.append(f"NO evalues aqui (fuera de alcance): {criterio['fuera_de_alcance']}.")
    if anclas:
        ejemplos = "\n".join(f"  - Nivel '{a['nivel']}': \"{a['texto']}\"" for a in anclas)
        partes.append("ANCLAS DE CALIBRACION (ejemplos ya corregidos por el docente; usa su "
                      "estandar):\n" + ejemplos)
    partes.append(f"\nRESPUESTA DEL ESTUDIANTE:\n\"{respuesta}\"")
    partes.append(
        '\nDevuelve SOLO este JSON:\n'
        '{"nivel": "logrado|parcial|no_logrado", "confianza": <0.0-1.0>, '
        '"evidencia": "<cita breve de la respuesta que lo sustenta>", '
        '"justificacion": "<por que ese nivel, en una frase>"}')
    return system, "\n".join(partes)


_NIVELES = {
    "logrado": LOGRO_LOGRADO, "parcial": LOGRO_PARCIAL,
    "no_logrado": LOGRO_NO, "no logrado": LOGRO_NO, "nologrado": LOGRO_NO,
}


def _norm_nivel(valor) -> str:
    clave = str(valor or "").strip().lower().replace("-", "_")
    if clave not in _NIVELES:
        raise ValueError(f"Nivel no reconocido del modelo: {valor!r}")
    return _NIVELES[clave]


def parsear_respuesta(texto: str) -> dict:
    """Extrae y valida el JSON del modelo -> {nivel, confianza, evidencia, justificacion}."""
    t = (texto or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1 or j < i:
        raise ValueError("La respuesta del modelo no contiene un objeto JSON.")
    data = json.loads(t[i:j + 1])
    nivel = _norm_nivel(data.get("nivel"))
    try:
        conf = float(data.get("confianza", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = min(1.0, max(0.0, conf))
    return {"nivel": nivel, "confianza": round(conf, 2),
            "evidencia": str(data.get("evidencia", ""))[:300],
            "justificacion": str(data.get("justificacion", ""))[:500]}


def _llamar_anthropic(modelo: str = MODELO_DEFECTO):
    """Factory de la funcion de llamada real (SDK de Anthropic). Se evalua perezosamente."""
    def _llamar(system: str, user: str) -> str:
        import anthropic
        cliente = anthropic.Anthropic()          # lee ANTHROPIC_API_KEY del entorno
        msg = cliente.messages.create(
            model=modelo, max_tokens=400, system=system,
            messages=[{"role": "user", "content": user}])
        # Toma el primer bloque de texto (robusto: no asume que content[0] sea texto).
        for bloque in msg.content:
            if getattr(bloque, "type", None) == "text":
                return bloque.text
        return getattr(msg.content[0], "text", "") if msg.content else ""
    return _llamar


def coder_llm(llamar=None, modelo: str = MODELO_DEFECTO):
    """Devuelve un `coder` compatible con el seam de F2. `llamar` inyectable (tests)."""
    llamar = llamar or _llamar_anthropic(modelo)

    def _coder(respuesta: str, criterio: dict) -> dict:
        system, user = construir_prompt(respuesta, criterio)
        return parsear_respuesta(llamar(system, user))

    return _coder


def coder_llm_seguro(llamar=None, modelo: str = MODELO_DEFECTO):
    """coder_llm con red de seguridad: ante cualquier error cae al grader por anclas (F2)."""
    base = coder_llm(llamar, modelo)

    def _coder(respuesta: str, criterio: dict) -> dict:
        try:
            return base(respuesta, criterio)
        except Exception:
            return precalificacion_service._grade_por_anclas(respuesta, criterio)

    return _coder


def coder_por_defecto():
    """LLM (seguro) si hay ANTHROPIC_API_KEY; si no, None -> F2 usa su grader determinista."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return coder_llm_seguro()
    return None
