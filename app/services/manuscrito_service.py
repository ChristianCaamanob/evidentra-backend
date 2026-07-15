"""Fase E — generador de manuscrito Q1 (IMRaD completo).

Extiende reporte_service (que redactaba solo Métodos+Resultados) a un artículo IMRaD completo:
Título, Abstract, Introducción, Métodos, Resultados, Discusión y Limitaciones. Sirve a dos
tipos de estudio:
  · 'datos'    → estudio de validación / análisis de datos propios (psicometría + cualitativo).
  · 'revision' → revisión sistemática + metaanálisis (PRISMA, efecto combinado, GRADE, ROB-2).

Reglas de integridad (líneas rojas):
  · El LLM redacta la PROSA; las CIFRAS vienen dadas y NO se inventan ni se re-redondean.
  · Guía de reporte según diseño: PRISMA 2020 (revisión) / COSMIN (validación).
  · Sin clave o si falla el LLM → borrador determinista por plantilla (siempre responde).

Mismo seam que reporte_service (ANTHROPIC_API_KEY). No altera notas (G1); datos seudonimizados (G2).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

MODELO = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

SECCIONES = ["titulo", "abstract", "introduccion", "metodos", "resultados", "discusion", "limitaciones"]

_SYSTEM = (
    "Eres un metodologo experto que redacta articulos para revistas Q1 (JCR/Scopus) en espanol "
    "academico, preciso y sobrio, formato APA 7. REGLA ABSOLUTA: usa SOLO los numeros que se te "
    "entregan; jamas inventes, estimes ni re-redondees cifras, y no agregues resultados no dados. "
    "Reporta tamanos de efecto con su intervalo de confianza. Sigue la guia de reporte indicada "
    "(PRISMA 2020 para revisiones; COSMIN para validacion). La Introduccion debe enmarcar el vacio "
    "de conocimiento; la Discusion debe contrastar con literatura sin sobrevender; las Limitaciones "
    "deben declarar los sesgos evaluados. Devuelves SOLO un objeto JSON con EXACTAMENTE estas claves "
    "(cada una texto plano): titulo, abstract, introduccion, metodos, resultados, discusion, "
    "limitaciones. 'titulo' es una linea; 'abstract' 150-250 palabras estructurado; el resto, 1-3 "
    "parrafos cada uno."
)


def _prompt(hechos: dict, tipo: str) -> str:
    guia = "PRISMA 2020" if tipo == "revision" else "COSMIN"
    marco = ("una REVISION SISTEMATICA con METAANALISIS (efectos aleatorios)" if tipo == "revision"
             else "un ESTUDIO DE VALIDACION / analisis de datos psicometricos")
    return (
        f"Redacta un manuscrito IMRaD completo para {marco}, siguiendo la guia de reporte {guia}. "
        "Usa EXCLUSIVAMENTE estos hechos y cifras REALES:\n\n"
        + json.dumps(hechos, ensure_ascii=False, indent=1)
        + "\n\nDevuelve SOLO el JSON con las 7 claves indicadas. No inventes cifras ni referencias."
    )


def redactar_imrad(hechos: dict, tipo: str = "revision") -> dict:
    """Genera las 7 secciones IMRaD con el LLM; cae a plantilla determinista si no hay clave/falla."""
    err = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            cliente = anthropic.Anthropic()
            msg = cliente.messages.create(
                model=MODELO, max_tokens=4096, system=_SYSTEM,
                messages=[{"role": "user", "content": _prompt(hechos, tipo)}])
            texto = ""
            for b in msg.content:
                if getattr(b, "type", None) == "text":
                    texto = b.text
                    break
            i, j = texto.find("{"), texto.rfind("}")
            data = json.loads(texto[i:j + 1])
            out = {k: str(data.get(k, "")).strip() for k in SECCIONES}
            out["motor"] = "IA (" + MODELO + ")"
            return out
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:200]
            logger.warning("Manuscrito IA cayo a plantilla: %s", err)
    else:
        err = "sin ANTHROPIC_API_KEY en el entorno"
    out = _plantilla(hechos, tipo)
    out["motor"] = "plantilla deterministica"
    if err:
        out["motor_detalle"] = err
    return out


# ───────────────────────────── plantilla determinista (respaldo sin LLM)
def _plantilla(h: dict, tipo: str) -> dict:
    if tipo == "revision":
        return _plantilla_revision(h)
    return _plantilla_datos(h)


def _plantilla_revision(h: dict) -> dict:
    m = h.get("meta", {}) or {}
    comb = m.get("combinado", {}) or {}
    het = m.get("heterogeneidad", {}) or {}
    pr = h.get("prisma", {}) or {}
    pico = h.get("pico", {}) or {}
    esc = m.get("efecto_escala", "el tamaño de efecto")
    est = comb.get("estimador", "—")
    ic = comb.get("ic95_hksj", ["—", "—"])
    grade = (m.get("grade", {}) or {}).get("certeza", "—")
    return {
        "titulo": h.get("titulo") or "Revisión sistemática y metaanálisis: síntesis de la evidencia",
        "abstract": (f"Antecedentes: {pico.get('poblacion','')} {pico.get('intervencion','')}. "
                     f"Métodos: revisión sistemática (PRISMA 2020) con metaanálisis de efectos aleatorios; "
                     f"se identificaron {pr.get('ident','—')} registros y se incluyeron {pr.get('inc','—')} "
                     f"estudios. Resultados: el efecto combinado ({esc}) fue {est} (IC95% [{ic[0]}, {ic[1]}]), "
                     f"con heterogeneidad {het.get('nivel','—')} (I²={het.get('I2','—')}%). "
                     f"Conclusión: certeza de la evidencia (GRADE) {grade}."),
        "introduccion": (f"El presente estudio aborda {pico.get('resultado','el resultado de interés')} en "
                         f"{pico.get('poblacion','la población objetivo')}. A pesar de la evidencia primaria "
                         "disponible, persiste la necesidad de una síntesis cuantitativa que integre los "
                         "hallazgos y cuantifique la magnitud del efecto con su incertidumbre, cubriendo el "
                         "vacío que este metaanálisis busca llenar."),
        "metodos": (f"Se condujo una revisión sistemática conforme a PRISMA 2020, con protocolo prospectivo. "
                    f"La búsqueda se realizó en {h.get('fuentes','bases bibliográficas')}; el cribado fue por "
                    f"doble revisor (concordancia κ reportada) y la selección se documentó en el diagrama de "
                    f"flujo PRISMA. El riesgo de sesgo se evaluó con {h.get('herramienta_sesgo','RoB 2')}. La "
                    f"síntesis empleó un modelo de efectos aleatorios (DerSimonian-Laird) con intervalo de "
                    f"Hartung-Knapp; la heterogeneidad se cuantificó con I² y τ², y el sesgo de publicación con "
                    f"la prueba de Egger y trim-and-fill."),
        "resultados": (f"Se incluyeron {pr.get('inc','—')} estudios (de {pr.get('ident','—')} identificados). "
                       f"El efecto combinado ({esc}) fue {est} (IC95% Hartung-Knapp [{ic[0]}, {ic[1]}], "
                       f"p={comb.get('p','—')}), con heterogeneidad {het.get('nivel','—')} "
                       f"(I²={het.get('I2','—')}%, τ²={het.get('tau2','—')}). " + str(h.get("meta_extra", ""))),
        "discusion": ("Los hallazgos sintetizan la evidencia disponible y deben interpretarse a la luz de la "
                      "heterogeneidad observada y de la certeza GRADE. El intervalo de predicción delimita el "
                      "rango esperable del efecto en nuevos contextos; conviene contrastar estos resultados con "
                      "la literatura primaria antes de generalizar."),
        "limitaciones": (f"Se evaluó el riesgo de sesgo intra-estudio ({h.get('herramienta_sesgo','RoB 2')}) y el "
                         f"sesgo de publicación (Egger, trim-and-fill). La certeza global de la evidencia fue "
                         f"{grade}. El número de estudios y la heterogeneidad condicionan la precisión de la "
                         f"estimación combinada."),
    }


def _plantilla_datos(h: dict) -> dict:
    fi = h.get("fiabilidad", {}) or {}
    est = h.get("estructura", {}) or {}
    return {
        "titulo": h.get("titulo") or "Evidencia de validez y fiabilidad de un instrumento de medición",
        "abstract": (f"Se analizó un instrumento de {h.get('n_items','—')} ítems administrado a "
                     f"{h.get('n','—')} personas. La fiabilidad fue α={fi.get('alfa','—')}, ω={fi.get('omega','—')}; "
                     f"la validez estructural (CFA WLSMV) mostró CFI={est.get('CFI','—')}, "
                     f"RMSEA={est.get('RMSEA','—')}. Se evaluaron invarianza, DIF y tamaños de efecto."),
        "introduccion": ("La calidad de la medición es condición para toda inferencia posterior. Este estudio "
                         "aporta evidencia de validez y fiabilidad del instrumento conforme al marco COSMIN, "
                         "cubriendo la necesidad de instrumentos con propiedades psicométricas documentadas."),
        "metodos": (f"Se administró un instrumento de {h.get('n_items','—')} ítems a {h.get('n','—')} personas. "
                    "Se estimó la fiabilidad (α de Cronbach, ω de McDonald), se ajustaron modelos de TRI (1PL/2PL) "
                    "comparados por AIC/BIC, y se evaluó la validez estructural (CFA WLSMV sobre correlaciones "
                    "tetracóricas), la invarianza de medición y el funcionamiento diferencial del ítem (DIF) entre "
                    "grupos consentidos."),
        "resultados": (f"La fiabilidad fue adecuada (α={fi.get('alfa','—')}, ω={fi.get('omega','—')}). El modelo "
                       f"unifactorial mostró {est.get('veredicto','—')} (CFI={est.get('CFI','—')}, "
                       f"RMSEA={est.get('RMSEA','—')}, SRMR={est.get('SRMR','—')}). " + str(h.get("dif_resumen", ""))),
        "discusion": ("Los índices obtenidos respaldan la interpretación de las puntuaciones. La evidencia de "
                      "invarianza y equidad (DIF) es relevante para el uso comparativo del instrumento entre grupos."),
        "limitaciones": ("Se evaluó la equidad de medición (DIF/invarianza) sobre grupos consentidos. El tamaño "
                         "muestral condiciona la potencia de las técnicas empleadas; se reporta la advertencia de "
                         "poder muestral cuando corresponde."),
    }
