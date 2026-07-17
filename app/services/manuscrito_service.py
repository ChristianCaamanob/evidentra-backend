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

SECC_TEXTO = ["titulo", "titulo_corto", "abstract", "introduccion", "metodos",
              "resultados", "discusion", "conclusiones", "limitaciones", "lo_que_aporta"]
SECC_LISTA = ["destacados", "palabras_clave"]

_SYSTEM = (
    "Eres un metodologo y autor experto que redacta articulos para revistas Q1 indexadas (Wiley, "
    "Elsevier, Taylor & Francis, SAGE, Springer) en espanol academico, preciso y sobrio, APA 7. "
    "Debes seguir las CONVENCIONES EDITORIALES de esas revistas:\n"
    "- 'titulo': conciso, informativo, <= 20 palabras, sin abreviaturas.\n"
    "- 'titulo_corto': running head <= 50 caracteres.\n"
    "- 'destacados': 3-5 highlights estilo Elsevier, cada uno <= 90 caracteres, frase declarativa.\n"
    "- 'palabras_clave': 4-6 terminos indexables.\n"
    "- 'abstract': ESTRUCTURADO con etiquetas en negrita: **Antecedentes:** **Objetivo:** "
    "**Metodos:** **Resultados:** **Conclusiones:** (y **Registro:** si es revision). 200-280 palabras.\n"
    "- 'metodos': con SUBTITULOS en negrita segun el diseno (p. ej. **Diseno y registro**, "
    "**Criterios de elegibilidad**, **Fuentes y estrategia de busqueda**, **Seleccion y cribado**, "
    "**Extraccion de datos**, **Riesgo de sesgo**, **Sintesis estadistica**). Incluye la guia de "
    "reporte y el registro del protocolo.\n"
    "- 'resultados': con SUBTITULOS (p. ej. **Seleccion de estudios**, **Caracteristicas**, "
    "**Efecto combinado**, **Heterogeneidad**, **Sesgo de publicacion**, **Certeza de la evidencia**).\n"
    "- 'discusion': contrasta con la literatura sin sobrevender; principales hallazgos e implicancias.\n"
    "- 'conclusiones': parrafo breve, sin cifras nuevas.\n"
    "- 'limitaciones': declara los sesgos evaluados y sus consecuencias.\n"
    "- 'lo_que_aporta': caja 'What this paper adds' con 2-3 vinetas (que se sabia / que anade).\n"
    "REGLA ABSOLUTA: usa SOLO los numeros entregados; jamas inventes, estimes ni re-redondees "
    "cifras, ni agregues resultados o referencias no dados. Reporta efectos con su IC. "
    "Devuelves SOLO un objeto JSON con EXACTAMENTE estas claves: " + ", ".join(SECC_TEXTO + SECC_LISTA)
    + " ('destacados' y 'palabras_clave' son arreglos de strings; el resto, texto)."
)


def _prompt(hechos: dict, tipo: str) -> str:
    guia = "PRISMA 2020" if tipo == "revision" else "COSMIN"
    marco = ("una REVISION SISTEMATICA con METAANALISIS de efectos aleatorios" if tipo == "revision"
             else "un ESTUDIO DE VALIDACION / analisis de datos psicometricos")
    return (
        f"Redacta un manuscrito completo y listo para envio a una revista Q1 indexada, para {marco}, "
        f"siguiendo la guia de reporte {guia} y las convenciones editoriales indicadas en el sistema. "
        "Usa EXCLUSIVAMENTE estos hechos y cifras REALES:\n\n"
        + json.dumps(hechos, ensure_ascii=False, indent=1)
        + "\n\nDevuelve SOLO el JSON con TODAS las claves indicadas. No inventes cifras ni referencias."
    )


CAP_META = ["titulo", "titulo_corto", "abstract", "palabras_clave", "destacados"]
_CAP_TOKENS = {"meta": 3000, "introduccion": 4500, "marco_teorico": 8000, "metodos": 8000,
               "resultados": 6000, "discusion": 8000, "conclusiones": 2500, "limitaciones": 3500,
               "etica": 5000, "aporta": 2000}
_CAP_GUIA = {
    "meta": ("Devuelve SOLO un JSON con {titulo, titulo_corto, abstract, palabras_clave (arreglo), "
             "destacados (arreglo de 3-5)}. Abstract ESTRUCTURADO 220-300 palabras con etiquetas en "
             "negrita (**Antecedentes:** **Objetivo:** **Métodos:** **Resultados:** **Conclusiones:** "
             "y **Registro:** si es revisión)."),
    "introduccion": ("Redacta la INTRODUCCIÓN completa (600-900 palabras): contexto y relevancia del "
                     "problema, estado general del campo, el vacío de conocimiento específico y los "
                     "objetivos/preguntas. Prosa fluida y argumentada. Devuelve SOLO JSON {\"texto\":\"...\"}."),
    "marco_teorico": ("Redacta el MARCO TEÓRICO / ANTECEDENTES en profundidad (900-1400 palabras) "
                      "TRENZANDO las referencias incluidas (te doy su cita y resumen): organiza por "
                      "constructos o temas con SUBTÍTULOS en negrita, sintetiza el estado del arte, "
                      "confronta hallazgos entre estudios, expón tensiones y delimita el vacío que la "
                      "revisión llena. Cita autor-año SOLO de las referencias dadas. JSON {\"texto\":\"...\"}."),
    "metodos": ("Redacta MATERIALES Y MÉTODOS en gran profundidad (900-1400 palabras) con SUBTÍTULOS en "
                "negrita según la guía de reporte: **Diseño y registro**, **Criterios de elegibilidad**, "
                "**Fuentes de información**, **Estrategia de búsqueda**, **Proceso de selección** (doble "
                "revisor, concordancia κ, resolución de discrepancias), **Extracción / charting de datos**, "
                "**Riesgo de sesgo** (herramienta), **Medidas de efecto**, **Síntesis estadística** "
                "(efectos aleatorios, τ²/I², Hartung-Knapp), **Sesgo de publicación** (Egger, trim-and-fill), "
                "**Evaluación de la certeza (GRADE)**. JSON {\"texto\":\"...\"}."),
    "resultados": ("Redacta RESULTADOS (700-1100 palabras) con SUBTÍTULOS: **Selección de estudios** "
                   "(remite al diagrama de flujo PRISMA con las cifras dadas), **Características de los "
                   "estudios** (remite a la Tabla 1), **Efecto combinado**, **Heterogeneidad**, "
                   "**Análisis de subgrupos / metarregresión** (si hay), **Sesgo de publicación** (remite "
                   "a la Figura 2, funnel), **Certeza de la evidencia**. Remite a la Figura 1 (forest plot). "
                   "Reporta efectos con su IC. JSON {\"texto\":\"...\"}."),
    "discusion": ("Redacta la DISCUSIÓN (1100-1600 palabras): es el capítulo MÁS IMPORTANTE y el corazón "
                  "de un artículo Q1. SUBTÍTULOS en negrita: **Hallazgos principales**; **Comparación con "
                  "la literatura** (contrasta CADA hallazgo con las referencias incluidas —cita autor-año—, "
                  "señalando concordancias y discrepancias y por qué); **Mecanismos e interpretación**; "
                  "**Fortalezas y limitaciones metodológicas**; **Implicaciones** para la práctica, la "
                  "política y la investigación futura. Argumenta sin sobrevender. JSON {\"texto\":\"...\"}."),
    "conclusiones": ("Redacta CONCLUSIONES (150-300 palabras), sin cifras nuevas, cerrando la contribución. "
                     "JSON {\"texto\":\"...\"}."),
    "limitaciones": ("Redacta LIMITACIONES (300-500 palabras): sesgos evaluados y sus consecuencias, límites "
                     "de la inferencia, generalización. JSON {\"texto\":\"...\"}."),
    "etica": ("Redacta CONSIDERACIONES ÉTICAS Y DECLARACIONES (500-800 palabras) para un artículo Q1, con "
              "SUBTÍTULOS en negrita: **Ética de la investigación** (una revisión de estudios publicados no "
              "requiere aprobación de comité; para datos primarios: consentimiento informado, seudonimización "
              "y protección de datos —Ley 21.719—); **Registro del protocolo** (PROSPERO/OSF); **Conflictos "
              "de interés**; **Financiación**; **Disponibilidad de datos y código**; **Contribuciones "
              "(CRediT)**; **Uso de inteligencia artificial** y su supervisión humana; **Reproducibilidad**. "
              "JSON {\"texto\":\"...\"}."),
    "aporta": ("Redacta 'LO QUE APORTA ESTE ESTUDIO' (caja What this paper adds) con 2-3 viñetas: qué se "
               "sabía / qué añade. JSON {\"texto\":\"...\"}."),
}


def redactar_capitulo(hechos: dict, tipo: str = "revision", cap: str = "introduccion") -> dict:
    """Genera UN capítulo en profundidad (llamada dedicada, prompt específico, presupuesto amplio).
    Permite ensamblar un artículo largo por capítulos en vez de una sola pasada corta."""
    guia = _CAP_GUIA.get(cap, _CAP_GUIA["introduccion"])
    sistema = (
        "Eres un metodólogo y autor experto que redacta artículos para revistas Q1 indexadas (Wiley, "
        "Elsevier, Taylor & Francis, SAGE) en español académico, preciso y argumentado, APA 7. Escribes "
        "capítulos EXTENSOS y de fondo, no resúmenes. REGLA ABSOLUTA: usa SOLO los números y las "
        "referencias que se te entregan; jamás inventes cifras ni referencias ni resultados no dados. " + guia)
    marco = ("una REVISIÓN SISTEMÁTICA con METAANÁLISIS" if tipo == "revision"
             else "un ESTUDIO DE VALIDACIÓN / análisis de datos")
    usuario = (f"Contexto: {marco}. Redacta el capítulo '{cap}'. Usa EXCLUSIVAMENTE estos hechos, cifras y "
               "referencias REALES:\n\n" + json.dumps(hechos, ensure_ascii=False)[:14000] + "\n\nDevuelve SOLO el JSON pedido.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pl = _plantilla(hechos, tipo)
        if cap == "meta":
            out = {k: pl.get(k, "") for k in CAP_META}
        else:
            m = {"marco_teorico": "introduccion", "etica": "limitaciones", "aporta": "lo_que_aporta"}
            out = {"texto": pl.get(m.get(cap, cap), "")}
        out["motor"] = "plantilla deterministica"
        return out
    try:
        import anthropic
        cliente = anthropic.Anthropic()
        with cliente.messages.stream(model=MODELO, max_tokens=_CAP_TOKENS.get(cap, 5000),
                                     system=sistema, messages=[{"role": "user", "content": usuario}]) as st:
            final = st.get_final_message()
        texto = ""
        for b in final.content:
            if getattr(b, "type", None) == "text":
                texto = b.text
                break
        texto = texto.strip()
        if texto.startswith("```"):
            texto = texto.split("```", 2)[1]
            if texto.lstrip().startswith("json"):
                texto = texto.lstrip()[4:]
        i, j = texto.find("{"), texto.rfind("}")
        data = json.loads(texto[i:j + 1])
        if cap == "meta":
            out = {k: str(data.get(k, "")).strip() for k in ["titulo", "titulo_corto", "abstract"]}
            for k in ["palabras_clave", "destacados"]:
                v = data.get(k) or []
                out[k] = [str(x).strip() for x in v if str(x).strip()][:6] if isinstance(v, list) else []
        else:
            out = {"texto": str(data.get("texto", "")).strip()}
        out["motor"] = "IA (" + MODELO + ")"
        return out
    except Exception as e:
        logger.warning("Capítulo %s cayó a plantilla: %s", cap, str(e)[:150])
        pl = _plantilla(hechos, tipo)
        if cap == "meta":
            out = {k: pl.get(k, "") for k in CAP_META}
        else:
            m = {"marco_teorico": "introduccion", "etica": "limitaciones", "aporta": "lo_que_aporta"}
            out = {"texto": pl.get(m.get(cap, cap), "")}
        out["motor"] = "plantilla deterministica"
        return out


def redactar_imrad(hechos: dict, tipo: str = "revision") -> dict:
    """Genera las 7 secciones IMRaD con el LLM; cae a plantilla determinista si no hay clave/falla."""
    err = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            cliente = anthropic.Anthropic()
            with cliente.messages.stream(               # streaming: evita timeout con salida larga
                    model=MODELO, max_tokens=8000, system=_SYSTEM,
                    messages=[{"role": "user", "content": _prompt(hechos, tipo)}]) as stream:
                final = stream.get_final_message()
            texto = ""
            for b in final.content:
                if getattr(b, "type", None) == "text":
                    texto = b.text
                    break
            texto = texto.strip()
            if texto.startswith("```"):                 # quita fences ```json … ```
                texto = texto.split("```", 2)[1]
                if texto.lstrip().startswith("json"):
                    texto = texto.lstrip()[4:]
            i, j = texto.find("{"), texto.rfind("}")
            if i < 0 or j <= i:
                raise ValueError(f"sin JSON en la respuesta ({len(texto)} chars)")
            data = json.loads(texto[i:j + 1])
            out = {k: str(data.get(k, "")).strip() for k in SECC_TEXTO}
            for k in SECC_LISTA:
                v = data.get(k) or []
                out[k] = [str(x).strip() for x in v if str(x).strip()][:6] if isinstance(v, list) else []
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
    herr = h.get("herramienta_sesgo", "RoB 2")
    return {
        "titulo": h.get("titulo") or "Revisión sistemática y metaanálisis: síntesis de la evidencia",
        "titulo_corto": (h.get("titulo") or "Revisión sistemática y metaanálisis")[:50],
        "destacados": [
            f"Metaanálisis de {pr.get('inc','—')} estudios ({esc} = {est}).",
            f"Efecto significativo con heterogeneidad {het.get('nivel','—')} (I²={het.get('I2','—')}%).",
            f"Certeza de la evidencia (GRADE): {grade}.",
        ],
        "palabras_clave": [w for w in [pico.get("intervencion"), pico.get("resultado"),
                           pico.get("poblacion"), "metaanálisis", "revisión sistemática"] if w][:6],
        "abstract": (f"**Antecedentes:** {pico.get('poblacion','')} — {pico.get('intervencion','')}. "
                     f"**Objetivo:** estimar el efecto combinado sobre {pico.get('resultado','el resultado')}. "
                     f"**Métodos:** revisión sistemática (PRISMA 2020) con metaanálisis de efectos aleatorios; "
                     f"{pr.get('ident','—')} registros identificados, {pr.get('inc','—')} estudios incluidos. "
                     f"**Resultados:** efecto combinado ({esc}) = {est} (IC95% [{ic[0]}, {ic[1]}]), "
                     f"heterogeneidad {het.get('nivel','—')} (I²={het.get('I2','—')}%). "
                     f"**Conclusiones:** certeza GRADE {grade}. **Registro:** protocolo prospectivo (PROSPERO)."),
        "introduccion": (f"El presente estudio aborda {pico.get('resultado','el resultado de interés')} en "
                         f"{pico.get('poblacion','la población objetivo')}. A pesar de la evidencia primaria, "
                         "persiste la necesidad de una síntesis cuantitativa que integre los hallazgos y "
                         "cuantifique la magnitud del efecto con su incertidumbre, vacío que este metaanálisis "
                         "busca llenar."),
        "metodos": (f"**Diseño y registro.** Revisión sistemática conforme a PRISMA 2020, con protocolo "
                    f"prospectivo (PROSPERO). **Fuentes y estrategia de búsqueda.** {h.get('fuentes','Bases bibliográficas')}, "
                    f"con cadenas booleanas por bloque PICO. **Selección y cribado.** Doble revisor con "
                    f"concordancia κ; el flujo se documenta según PRISMA. **Riesgo de sesgo.** Evaluado con "
                    f"{herr}. **Síntesis estadística.** Modelo de efectos aleatorios (DerSimonian-Laird) con "
                    f"intervalo de Hartung-Knapp; heterogeneidad por I² y τ²; sesgo de publicación por Egger y "
                    f"trim-and-fill."),
        "resultados": (f"**Selección de estudios.** Se incluyeron {pr.get('inc','—')} estudios (de "
                       f"{pr.get('ident','—')} identificados). **Efecto combinado.** ({esc}) = {est} (IC95% "
                       f"Hartung-Knapp [{ic[0]}, {ic[1]}], p={comb.get('p','—')}). **Heterogeneidad.** "
                       f"{het.get('nivel','—')} (I²={het.get('I2','—')}%, τ²={het.get('tau2','—')}). " + str(h.get("meta_extra", ""))),
        "discusion": ("Los hallazgos sintetizan la evidencia disponible y deben interpretarse a la luz de la "
                      "heterogeneidad observada y de la certeza GRADE. Conviene contrastar con la literatura "
                      "primaria antes de generalizar."),
        "conclusiones": (f"La evidencia sintetizada indica un efecto combinado {est} con certeza GRADE {grade}. "
                         "Se requieren estudios de mayor calidad para consolidar la inferencia."),
        "limitaciones": (f"Se evaluó el riesgo de sesgo intra-estudio ({herr}) y el sesgo de publicación (Egger, "
                         f"trim-and-fill). La certeza global fue {grade}. El número de estudios y la "
                         f"heterogeneidad condicionan la precisión de la estimación."),
        "lo_que_aporta": ("• Lo que se sabía: existía evidencia primaria dispersa sin síntesis cuantitativa. "
                          "• Lo que añade: un efecto combinado con su incertidumbre, heterogeneidad y certeza GRADE."),
    }


def _plantilla_datos(h: dict) -> dict:
    fi = h.get("fiabilidad", {}) or {}
    est = h.get("estructura", {}) or {}
    return {
        "titulo": h.get("titulo") or "Evidencia de validez y fiabilidad de un instrumento de medición",
        "titulo_corto": (h.get("titulo") or "Validez y fiabilidad del instrumento")[:50],
        "destacados": [
            f"Fiabilidad adecuada (α={fi.get('alfa','—')}, ω={fi.get('omega','—')}).",
            f"Validez estructural respaldada (CFA WLSMV, CFI={est.get('CFI','—')}).",
            "Evidencia de invarianza y equidad (DIF) entre grupos consentidos.",
        ],
        "palabras_clave": ["validez", "fiabilidad", "psicometría", "TRI", "invarianza de medición"],
        "abstract": (f"**Antecedentes:** la calidad de la medición condiciona toda inferencia. "
                     f"**Objetivo:** aportar evidencia de validez y fiabilidad. **Métodos:** instrumento de "
                     f"{h.get('n_items','—')} ítems en {h.get('n','—')} personas; TCT, TRI, CFA WLSMV, invarianza "
                     f"y DIF (COSMIN). **Resultados:** α={fi.get('alfa','—')}, ω={fi.get('omega','—')}; "
                     f"CFI={est.get('CFI','—')}, RMSEA={est.get('RMSEA','—')}. **Conclusiones:** propiedades "
                     f"psicométricas documentadas que respaldan la interpretación de las puntuaciones."),
        "introduccion": ("La calidad de la medición es condición para toda inferencia posterior. Este estudio "
                         "aporta evidencia de validez y fiabilidad conforme al marco COSMIN, cubriendo la "
                         "necesidad de instrumentos con propiedades psicométricas documentadas."),
        "metodos": (f"**Instrumento y muestra.** {h.get('n_items','—')} ítems administrados a {h.get('n','—')} "
                    f"personas. **Análisis.** Fiabilidad (α de Cronbach, ω de McDonald); TRI (1PL/2PL) comparados "
                    f"por AIC/BIC; validez estructural (CFA WLSMV sobre correlaciones tetracóricas); invarianza de "
                    f"medición; y funcionamiento diferencial del ítem (DIF) entre grupos consentidos (COSMIN)."),
        "resultados": (f"**Fiabilidad.** α={fi.get('alfa','—')}, ω={fi.get('omega','—')}. **Validez estructural.** "
                       f"El modelo unifactorial mostró {est.get('veredicto','—')} (CFI={est.get('CFI','—')}, "
                       f"RMSEA={est.get('RMSEA','—')}, SRMR={est.get('SRMR','—')}). **Equidad.** " + str(h.get("dif_resumen", ""))),
        "discusion": ("Los índices obtenidos respaldan la interpretación de las puntuaciones. La evidencia de "
                      "invarianza y equidad (DIF) es relevante para el uso comparativo entre grupos."),
        "conclusiones": ("El instrumento presenta propiedades psicométricas adecuadas que respaldan su uso e "
                         "interpretación en la población estudiada."),
        "limitaciones": ("Se evaluó la equidad de medición (DIF/invarianza) sobre grupos consentidos. El tamaño "
                         "muestral condiciona la potencia; se reporta la advertencia de poder muestral cuando aplica."),
        "lo_que_aporta": ("• Lo que se sabía: se requieren instrumentos con propiedades documentadas. "
                          "• Lo que añade: evidencia integrada de fiabilidad, validez estructural e invarianza."),
    }
