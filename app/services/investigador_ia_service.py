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
        "TÍTULO y el TEXTO (abstract o, si lo pegas, el texto completo) de un estudio PROPONES el riesgo de sesgo por sus 5 dominios. Para cada dominio "
        "das: 'juicio' ∈ {bajo, dudas, alto} y 'justificacion' (<=200 caracteres) anclada a lo que el texto "
        "dice o NO dice. Si el texto no aporta información suficiente de un dominio, usa 'dudas' y decláralo. "
        "NUNCA inventes detalles metodológicos que no estén en el texto. Devuelve SOLO JSON con esta forma: "
        '{"D1":{"juicio":"..","justificacion":".."},"D2":{...},"D3":{...},"D4":{...},"D5":{...},'
        '"global":{"juicio":"..","justificacion":".."}}. Regla del juicio global: ALTO si algún dominio es alto '
        "o hay >=2 con dudas; BAJO si los 5 son bajo; en otro caso DUDAS."
    )
    user = "TÍTULO: " + (titulo or "(sin título)") + "\n\nTEXTO (abstract o texto completo del paper): " + ((abstract or "")[:20000] or "(sin texto disponible)")
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
        "Eres extractor de datos para metaanálisis. Del TEXTO (abstract o texto completo del paper) extraes los estadísticos del tamaño de efecto "
        "pedido SOLO si están EXPLÍCITOS o son derivables sin ambigüedad. " + guia + " Si un valor NO está en el "
        "texto, ponlo en null: NO lo inventes ni lo estimes. Devuelve SOLO JSON: " + campos +
        ' y además "confianza" (0 a 1) y "nota" (qué encontraste o por qué falta algún dato).'
    )
    user = "TÍTULO: " + (titulo or "(sin título)") + "\n\nTEXTO (abstract o texto completo del paper): " + ((abstract or "")[:20000] or "(sin texto disponible)")
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=800)
        d = _json_robusto(crudo)
        return {"ok": True, "datos": d, "medida": medida, "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Extracción IA — verifica cada cifra contra el paper antes de calcular (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("extraer_efecto falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


_VAR_CAMPO_DESC = {
    "media": "media (promedio) del desenlace", "de": "desviación estándar (DE)", "n": "tamaño de muestra (n)",
    "media1": "media del grupo 1", "de1": "DE del grupo 1", "n1": "n del grupo 1",
    "media2": "media del grupo 2", "de2": "DE del grupo 2", "n2": "n del grupo 2",
    "eventos": "número de casos con el evento/desenlace", "r": "coeficiente de correlación r",
    "estimador": "estimador de efecto reportado", "ee": "error estándar (EE) del estimador",
}


def extraer_variable(nombre: str, tipo: str, campos: list, titulo: str, texto: str) -> dict:
    """Extrae del TEXTO los valores numéricos de una VARIABLE de interés declarada por el investigador
    (agnóstico a disciplina). Solo lo explícito/derivable sin ambigüedad; ausentes → null (nunca inventa). G1."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    campos = [str(c) for c in (campos or [])]
    if not campos:
        return {"ok": False, "error": "sin campos"}
    esquema = "{" + ",".join('"' + c + '":<' + _VAR_CAMPO_DESC.get(c, c) + " | null>" for c in campos) + "}"
    system = (
        "Eres extractor de datos para metaanálisis. Del TEXTO (abstract o texto completo del paper) extraes, "
        "para la VARIABLE DE INTERÉS indicada, los valores numéricos pedidos SOLO si están EXPLÍCITOS o son "
        "derivables sin ambigüedad. Si un valor NO está en el texto, ponlo en null: NO lo inventes ni lo "
        'estimes. Devuelve SOLO JSON: {"campos":' + esquema + ',"confianza":<0 a 1>,"nota":"qué hallaste o por qué falta"}.'
    )
    user = ("VARIABLE DE INTERÉS: «" + (nombre or "") + "» (tipo: " + (tipo or "") + ")\n\nTÍTULO: "
            + (titulo or "(sin título)") + "\n\nTEXTO (abstract o texto completo):\n"
            + ((texto or "")[:20000] or "(sin texto disponible)"))
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=700)
        d = _json_robusto(crudo)
        src = d.get("campos") if isinstance(d.get("campos"), dict) else d
        out = {}
        for c in campos:
            v = src.get(c)
            try:
                out[c] = None if v in (None, "", "null", "NA", "N/A") else float(v)
            except (TypeError, ValueError):
                out[c] = None
        return {"ok": True, "campos": out, "confianza": d.get("confianza"),
                "nota": str(d.get("nota", ""))[:300], "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Extracción IA — verifica cada cifra contra el paper antes de sintetizar (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("extraer_variable falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


def proponer_appraisal(tool_nombre: str, items: list, titulo: str, texto: str) -> dict:
    """Propone la valoración crítica ítem por ítem para CUALQUIER herramienta (JBI por diseño, o RoB 2),
    desde el título + texto (abstract o texto completo). Respuestas: si/no/poco/na. G1: el investigador valida."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    lista = "\n".join(str(k) + ". " + str(q) for k, q in enumerate(items or []))
    system = (
        "Eres metodólogo experto en valoración crítica de estudios (herramientas JBI / Cochrane). Se te da "
        "el nombre de la herramienta y sus ítems. Para CADA ítem responde 'si', 'no', 'poco' (poco claro / no "
        "reportado) o 'na' (no aplica), según lo que el TEXTO dice o NO dice, con una 'justificacion' breve "
        "(<=160 car.) anclada al texto. NUNCA inventes lo que el texto no reporta (usa 'poco'). Devuelve SOLO "
        'JSON: {"items":[{"i":<índice>,"respuesta":"si|no|poco|na","justificacion":".."}],"global":".."}.'
    )
    user = ("HERRAMIENTA: " + (tool_nombre or "") + "\n\nÍTEMS:\n" + lista
            + "\n\nTÍTULO: " + (titulo or "") + "\n\nTEXTO (abstract o texto completo):\n" + ((texto or "")[:20000] or "(sin texto)"))
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=2200)
        d = _json_robusto(crudo)
        out = []
        for it in (d.get("items") or []):
            r = str(it.get("respuesta", "")).lower()
            r = "si" if r.startswith("s") or r == "yes" else "no" if r == "no" else "na" if r.startswith("na") or "aplic" in r else "poco"
            try:
                idx = int(it.get("i"))
            except (TypeError, ValueError):
                continue
            out.append({"i": idx, "respuesta": r, "justificacion": str(it.get("justificacion", ""))[:220]})
        return {"ok": True, "items": out, "global": str(d.get("global", ""))[:300],
                "motor": "IA (" + ce.MODELO_EXPERTO + ")", "aviso": "Propuesta IA — verifica cada ítem (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("proponer_appraisal falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


def proponer_extraccion(campos: list, titulo: str, texto: str) -> dict:
    """Extrae los campos de un formulario de extracción de datos (estilo Covidence) desde el título +
    texto (abstract o texto completo). Cada campo se rellena SOLO con lo que el texto reporta; lo que no
    aparezca queda vacío (nunca se inventa/estima). G1: el investigador valida. `campos` = [{"k","t"}]."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    lista = "\n".join("- " + str(c.get("k")) + ": " + str(c.get("t", c.get("k"))) for c in (campos or []))
    system = (
        "Eres metodólogo experto en extracción de datos para revisiones sistemáticas (estilo Covidence). Se "
        "te da la lista de CAMPOS a extraer (clave: descripción) y el TEXTO de un estudio. Para CADA campo, "
        "extrae SOLO lo que el texto reporta, conciso (frases o cifras, no párrafos). Si el texto NO reporta "
        "un campo, deja 'valor' como cadena vacía \"\" — NUNCA inventes, estimes ni infieras lo no dicho. "
        "El campo 'diseno' debe ser el tipo de diseño (ECA, cohorte, caso-control, transversal, etc.); "
        "'n_total' solo dígitos. Añade 'confianza' 'alta'|'media'|'baja' por campo. Devuelve SOLO JSON: "
        '{"campos":[{"k":"<clave>","valor":"..","confianza":"alta|media|baja"}]}.'
    )
    user = ("CAMPOS:\n" + lista + "\n\nTÍTULO: " + (titulo or "")
            + "\n\nTEXTO (abstract o texto completo):\n" + ((texto or "")[:20000] or "(sin texto)"))
    validas = {str(c.get("k")) for c in (campos or [])}
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=1800)
        d = _json_robusto(crudo)
        out = []
        for it in (d.get("campos") or []):
            k = str(it.get("k", ""))
            if k not in validas:
                continue
            conf = str(it.get("confianza", "")).lower()
            conf = "alta" if "alt" in conf else "baja" if "baj" in conf else "media"
            out.append({"k": k, "valor": str(it.get("valor", "")).strip()[:600], "confianza": conf})
        return {"ok": True, "campos": out, "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Extracción propuesta por IA — verifica cada campo (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("proponer_extraccion falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}


def sintetizar_resultados(meta: dict, rob: dict | None = None, contexto: str = "") -> dict:
    """Síntesis narrativa de los RESULTADOS de una revisión sistemática + metaanálisis, anclada a las
    cifras dadas, lista para el capítulo 'Resultados' de un Q1. La IA propone; el investigador valida (G1)."""
    if not _disponible():
        return {"ok": False, "disponible": False}
    import json as _json
    from app.services import correccion_experta_service as ce
    system = (
        "Eres autor de revisiones sistemáticas para revistas Q1. A partir del OBJETO JSON con los "
        "resultados del metaanálisis (efecto combinado, IC95%, z, p, heterogeneidad I²/τ²/Q, intervalo de "
        "predicción, sesgo de publicación Egger/trim-and-fill, sensibilidad leave-one-out, subgrupos, "
        "metarregresión, GRADE) y el resumen de riesgo de sesgo, redacta una síntesis de RESULTADOS "
        "rigurosa (180-260 palabras) en estilo APA: (1) magnitud y dirección del efecto combinado con IC95% "
        "y significación; (2) heterogeneidad y su interpretación; (3) robustez (sensibilidad) y sesgo de "
        "publicación; (4) certeza GRADE. Cifras EXACTAS del objeto; NO inventes; NO afirmes causalidad. "
        'Devuelve SOLO JSON: {"sintesis":"..","frase_clave":"..","limitaciones_evidencia":".."}.'
    )
    payload = {"meta": meta, "riesgo_sesgo": rob or {}}
    user = "PREGUNTA/ORIENTACIÓN: " + (contexto or "(no dada)") + "\n\nRESULTADOS:\n" + _json.dumps(payload, ensure_ascii=False)[:9000]
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=1600)
        d = _json_robusto(crudo)
        return {"ok": True, "sintesis": str(d.get("sintesis", "")).strip(),
                "frase_clave": str(d.get("frase_clave", "")).strip(),
                "limitaciones_evidencia": str(d.get("limitaciones_evidencia", "")).strip(),
                "motor": "IA (" + ce.MODELO_EXPERTO + ")", "aviso": "Síntesis propuesta por IA — valídala (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("sintetizar_resultados falló: %s", str(e)[:150])
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
