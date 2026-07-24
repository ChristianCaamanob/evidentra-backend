"""Propuestas IA para el módulo Investigador — doctrina G1: la IA PROPONE, el investigador VALIDA.

- proponer_sesgo(titulo, abstract): Cochrane RoB 2 por 5 dominios + juicio global, con justificación
  anclada al texto. Nunca decide: el investigador corrige cada dominio.
- extraer_efecto(titulo, abstract, medida): tamaños de efecto (M/DE/N, eventos/n o r/n) SOLO si están
  explícitos en el abstract; los valores ausentes van a null (jamás se inventan/estiman).

Sin ANTHROPIC_API_KEY → {ok:false, disponible:false} (la UI muestra el aviso y sigue manual).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

_DOMINIOS = [
    ("D1", "Proceso de aleatorización"),
    ("D2", "Desviaciones de la intervención prevista"),
    ("D3", "Datos de resultado faltantes"),
    ("D4", "Medición del resultado"),
    ("D5", "Selección del resultado reportado"),
]


def _disponible() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _json_robusto(crudo: str) -> dict:
    t = (crudo or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("sin objeto JSON")
    return json.loads(t[i:j + 1])


def _norm_juicio(v: str, defecto: str = "dudas") -> str:
    s = str(v or "").lower()
    if "alto" in s or "high" in s:
        return "alto"
    if "bajo" in s or "low" in s:
        return "bajo"
    if "dud" in s or "some" in s or "concern" in s:
        return "dudas"
    return defecto


def proponer_sesgo(titulo: str, abstract: str) -> dict:
    """Propone RoB 2 (5 dominios + global) desde título+abstract. G1: el investigador valida."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    system = (
        "Eres metodólogo experto en la herramienta Cochrane RoB 2 (Sterne et al., 2019). A partir del "
        "TÍTULO y ABSTRACT de un estudio PROPONES el riesgo de sesgo por sus 5 dominios. Para cada dominio "
        "das: 'juicio' ∈ {bajo, dudas, alto} y 'justificacion' (<=200 caracteres) anclada a lo que el texto "
        "dice o NO dice. Si el abstract no aporta información suficiente de un dominio, usa 'dudas' y decláralo. "
        "NUNCA inventes detalles metodológicos que no estén en el texto. Devuelve SOLO JSON con esta forma: "
        '{"D1":{"juicio":"..","justificacion":".."},"D2":{...},"D3":{...},"D4":{...},"D5":{...},'
        '"global":{"juicio":"..","justificacion":".."}}. Regla del juicio global: ALTO si algún dominio es alto '
        "o hay >=2 con dudas; BAJO si los 5 son bajo; en otro caso DUDAS."
    )
    user = "TÍTULO: " + (titulo or "(sin título)") + "\n\nABSTRACT: " + ((abstract or "")[:6000] or "(sin abstract disponible)")
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=1500)
        d = _json_robusto(crudo)
        out = {}
        for k, _lab in _DOMINIOS:
            dd = d.get(k) or {}
            out[k] = {"juicio": _norm_juicio(dd.get("juicio")),
                      "justificacion": str(dd.get("justificacion", ""))[:300]}
        g = d.get("global") or {}
        out["global"] = {"juicio": _norm_juicio(g.get("juicio")),
                         "justificacion": str(g.get("justificacion", ""))[:300]}
        return {"ok": True, "propuesta": out, "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Propuesta IA — verifica y corrige cada dominio (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("proponer_sesgo falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


def extraer_efecto(titulo: str, abstract: str, medida: str = "smd") -> dict:
    """Extrae del abstract los estadísticos del tamaño de efecto pedido. Valores ausentes → null."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    if medida == "or":
        campos = '{"e1":<eventos grupo intervención>,"n1":<n grupo1>,"e2":<eventos control>,"n2":<n grupo2>}'
        guia = "Para Odds Ratio necesitas eventos y n por grupo (2x2)."
    elif medida == "z":
        campos = '{"r":<coeficiente de correlación r>,"n":<n total>}'
        guia = "Para correlación (Fisher z) necesitas r y n."
    else:
        campos = ('{"m1":<media grupo1>,"de1":<DE grupo1>,"n1":<n grupo1>,'
                  '"m2":<media grupo2>,"de2":<DE grupo2>,"n2":<n grupo2>}')
        guia = "Para diferencia de medias (Hedges g) necesitas media, DE y n por grupo."
    system = (
        "Eres extractor de datos para metaanálisis. Del ABSTRACT extraes los estadísticos del tamaño de efecto "
        "pedido SOLO si están EXPLÍCITOS o son derivables sin ambigüedad. " + guia + " Si un valor NO está en el "
        "texto, ponlo en null: NO lo inventes ni lo estimes. Devuelve SOLO JSON: " + campos +
        ' y además "confianza" (0 a 1) y "nota" (qué encontraste o por qué falta algún dato).'
    )
    user = "TÍTULO: " + (titulo or "(sin título)") + "\n\nABSTRACT: " + ((abstract or "")[:6000] or "(sin abstract disponible)")
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=800)
        d = _json_robusto(crudo)
        return {"ok": True, "datos": d, "medida": medida, "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Extracción IA — verifica cada cifra contra el paper antes de calcular (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("extraer_efecto falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


def interpretar_analisis(resultado: dict, contexto: str = "") -> dict:
    """Interpreta un resultado estadístico (t/ANOVA/correlación/regresión…) como lo haría un
    estadígrafo senior para un artículo Q1: lectura del hallazgo, tamaño de efecto, supuestos y
    reservas. La IA propone; el investigador valida (G1)."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    import json as _json
    from app.services import correccion_experta_service as ce
    system = (
        "Eres un estadígrafo senior que redacta la lectura de un resultado para un artículo indexado Q1. "
        "A partir del OBJETO JSON con el resultado del análisis, escribe una interpretación rigurosa y "
        "sobria (120-180 palabras): (1) qué muestra el estadístico y su p-valor; (2) el TAMAÑO DE EFECTO y "
        "su magnitud sustantiva (no solo la significación); (3) supuestos/limitaciones relevantes; (4) una "
        "frase lista para 'Resultados' en estilo APA. NO exageres, NO afirmes causalidad si el diseño no la "
        "soporta, NO inventes cifras que no estén en el objeto. Devuelve SOLO JSON: "
        '{"interpretacion":"..","frase_apa":"..","reservas":".."}.'
    )
    user = "CONTEXTO: " + (contexto or "(no dado)") + "\n\nRESULTADO:\n" + _json.dumps(resultado, ensure_ascii=False)[:6000]
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=1200)
        d = _json_robusto(crudo)
        return {"ok": True, "interpretacion": str(d.get("interpretacion", "")).strip(),
                "frase_apa": str(d.get("frase_apa", "")).strip(),
                "reservas": str(d.get("reservas", "")).strip(),
                "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Lectura propuesta por IA — valídala (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("interpretar_analisis falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}
