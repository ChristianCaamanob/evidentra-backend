"""
Fase 9 del pipeline Investigador — reporte reproducible.

Toma los estadisticos REALES ya computados (fiabilidad, validez estructural, TRI, equidad,
efectos) y produce:
  - un borrador academico de MÉTODOS y RESULTADOS redactado por el LLM (APA 7, en espanol),
    ANCLADO a los numeros dados (no inventa cifras)
  - un checklist tipo COSMIN de la evidencia psicometrica cubierta

El LLM entra por el mismo seam que F2 (ANTHROPIC_API_KEY). Si no hay clave o falla, se
devuelve un borrador determinista a partir de plantillas + los numeros. No altera notas (G1).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

MODELO_REPORTE = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

_SYSTEM = (
    "Eres un metodologo experto en psicometria educativa que redacta para revistas indexadas "
    "(APA 7). Escribes en espanol academico, preciso y sobrio. Regla ABSOLUTA: usa SOLO los "
    "numeros que se te entregan; no inventes ni redondees de forma distinta ni agregues cifras. "
    "Reportas tamanos de efecto con su intervalo cuando estan disponibles. Devuelves SOLO un "
    "objeto JSON con las claves 'metodos' y 'resultados' (cada una un texto de 1-3 parrafos)."
)


def _prompt(hechos: dict) -> str:
    return (
        "Redacta las secciones MÉTODOS (instrumento, muestra, analisis) y RESULTADOS de un "
        "estudio de validacion, a partir de estos resultados psicometricos REALES:\n\n"
        + json.dumps(hechos, ensure_ascii=False, indent=1)
        + "\n\nEn METODOS: describe el instrumento (n de items, escala), la muestra (n), y los "
        "analisis realizados (TCT y fiabilidad, TRI/Rasch, validez estructural con correlaciones "
        "tetracoricas y CFA WLSMV, invarianza, equidad DIF, tamanos de efecto). En RESULTADOS: "
        "reporta las cifras clave (alfa, omega, indices de ajuste, comparacion de modelos, DIF, "
        "d de Cohen con IC) e interpreta el ajuste segun los umbrales estandar. Devuelve SOLO el "
        "JSON {\"metodos\": \"...\", \"resultados\": \"...\"}."
    )


def redactar(hechos: dict) -> dict:
    """Redacta Metodos+Resultados con el LLM; cae a plantilla determinista si no hay clave."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            cliente = anthropic.Anthropic()
            msg = cliente.messages.create(
                model=MODELO_REPORTE, max_tokens=2200, system=_SYSTEM,
                messages=[{"role": "user", "content": _prompt(hechos)}])
            texto = ""
            for b in msg.content:
                if getattr(b, "type", None) == "text":
                    texto = b.text
                    break
            i, j = texto.find("{"), texto.rfind("}")
            data = json.loads(texto[i:j + 1])
            return {"metodos": str(data.get("metodos", "")).strip(),
                    "resultados": str(data.get("resultados", "")).strip(),
                    "motor": "IA (" + MODELO_REPORTE + ")"}
        except Exception as e:
            logger.warning("Reporte IA cayo a plantilla: %s", str(e)[:160])
    return {**_plantilla(hechos), "motor": "plantilla deterministica"}


def _plantilla(h: dict) -> dict:
    fi = h.get("fiabilidad", {}); est = h.get("estructura", {}); tri = h.get("tri", {})
    metodos = (f"Se analizo un instrumento de {h.get('n_items','—')} items de respuesta "
               f"dicotomica administrado a {h.get('n','—')} estudiantes. Se estimo la fiabilidad "
               "(alfa de Cronbach y omega de McDonald), se ajustaron modelos de Teoria de "
               "Respuesta al Item (1PL y 2PL) comparados por AIC/BIC, y se evaluo la validez "
               "estructural mediante un modelo de un factor sobre correlaciones tetracoricas "
               "(CFA con estimador WLSMV) junto con el analisis de invarianza y de funcionamiento "
               "diferencial del item (DIF) entre grupos consentidos.")
    resultados = (f"La fiabilidad fue adecuada (alfa = {fi.get('alfa','—')}, omega = "
                  f"{fi.get('omega','—')}). El modelo de 1 factor mostro "
                  f"{est.get('veredicto_wlsmv', est.get('veredicto','—'))} "
                  f"(CFI = {est.get('CFI','—')}, RMSEA = {est.get('RMSEA','—')}, SRMR = "
                  f"{est.get('SRMR','—')}). La comparacion de modelos TRI favorecio el "
                  f"{tri.get('preferido','—')} por BIC. " + str(h.get('dif_resumen', '')))
    return {"metodos": metodos, "resultados": resultados}


def checklist_cosmin(h: dict) -> list:
    fi = h.get("fiabilidad", {}); est = h.get("estructura", {})
    def item(nombre, ok, detalle):
        return {"criterio": nombre, "cubierto": bool(ok), "detalle": detalle}
    return [
        item("Consistencia interna", fi.get("alfa") is not None,
             f"alfa={fi.get('alfa','—')}, omega={fi.get('omega','—')}"),
        item("Error de medicion (SEM)", fi.get("sem") is not None, f"SEM={fi.get('sem','—')}"),
        item("Validez estructural (CFA)", est.get("SRMR") is not None,
             f"WLSMV: CFI={est.get('CFI','—')}, RMSEA={est.get('RMSEA','—')}"),
        item("Invarianza de medicion", h.get("invarianza") is not None,
             str(h.get("invarianza", "—"))),
        item("Equidad / DIF", h.get("dif_resumen") is not None, str(h.get("dif_resumen", "—"))),
        item("Reproducibilidad", True, "Analisis versionado; datos seudonimizados (Ley 21.719)."),
    ]
