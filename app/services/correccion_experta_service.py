"""
Fase 3 (módulo F · corrección de desarrollo) — Motor de corrección EXPERTA holística.

A diferencia de F2 (precalificación criterio-a-criterio, que EXIGE rúbrica), este motor
propone una corrección aunque NO haya rúbrica manual: se apoya en la respuesta óptima, el
nivel de rigor y la autoridad del área declarada. Doctrina intacta:

  • G1 — la IA PROPONE; la nota la fija y valida el docente (F3). Nunca es autoridad final.
  • Estándar DECLARADO y transparente — este es el diferenciador vs un chat genérico:
      A) áreas con nomenclatura universal fuerte  → la IA cita el estándar (TA, FDI, IUPAC…).
      B) áreas de unidades/magnitudes             → valida contra SI/ISO-IEC-80000/CODATA…
      C) áreas jurisdiccionales/de consenso       → la IA NO corrige desde su memoria; corrige
         contra la FUENTE que el docente adjunta (`fuente_estandar`) y lo etiqueta. En Derecho
         y normativa técnica esto evita alucinar artículos y no devalúa el producto.

Salida (propuesta editable por el docente):
  {nivel_global, puntaje_sugerido(0-1), justificacion, respuesta_modelo, estandar_citado,
   naturaleza_estandar(A|B|C), transparencia, brechas[], estrategias[],
   requiere_revision(bool), confianza(0-1)}
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

from app.models.answer_key import (
    RIGOR_ESTRICTO, RIGOR_FLEXIBLE, RIGOR_MUY_FLEXIBLE, RIGOR_CRITERIOSO, NIVELES_RIGOR,
)

MODELO_EXPERTO = os.environ.get("EVALYS_EXPERTO_MODEL", "claude-opus-4-8")

# ── Reglas de rigor (N1→N4). Se inyectan tal cual en el prompt. ────────────────────────────
_REGLA_RIGOR = {
    RIGOR_ESTRICTO: (
        "RIGOR N1 · ESTRICTO (superlativo): exige forma Y fondo al máximo. El concepto debe ser "
        "correcto, completo y actualizado, con el TÉRMINO CANÓNICO de la autoridad del área. Un "
        "error conceptual o de nomenclatura baja el nivel. No premies aproximaciones ni sinónimos "
        "coloquiales."),
    RIGOR_FLEXIBLE: (
        "RIGOR N2 · FLEXIBLE: prioriza el fondo; acepta ciertas licencias de forma y sinónimos "
        "equivalentes. Penaliza solo si el concepto está ausente, equivocado o gravemente impreciso."),
    RIGOR_MUY_FLEXIBLE: (
        "RIGOR N3 · MUY FLEXIBLE: premia la comprensión central aunque el fraseo sea informal o "
        "incompleto. Da crédito parcial generoso; reserva 'no logrado' para el error conceptual claro."),
    RIGOR_CRITERIOSO: (
        "RIGOR N4 · CRITERIOSO: evalúa con juicio parámetro por parámetro. Ante un enfoque inesperado "
        "pero potencialmente válido, propón 'parcial' con confianza baja y márcalo para revisión "
        "docente en vez de reprobar. Explicita el juicio aplicado."),
}

# ── Registro de autoridades por área (LEAN). naturaleza: A=nomenclatura universal (cita directa),
#    B=unidades/magnitudes, C=jurisdiccional/consenso (exige fuente declarada + transparencia). ──
_AREAS = {
    "general":        ("A", "consenso académico de la disciplina y la respuesta óptima del docente"),
    "anatomia":       ("A", "Terminologia Anatomica (FIPAT/IFAA)"),
    "odontologia":    ("A", "notación FDI e ISO 3950 (y ADA/universal si el docente la declara)"),
    "medicina":       ("C", "CIE-11/SNOMED-CT y guías clínicas vigentes; ancla a la fuente del docente"),
    "enfermeria":     ("C", "NANDA-I/NIC/NOC y guías vigentes; ancla a la fuente del docente"),
    "kinesiologia":   ("C", "CIF (OMS) y evidencia clínica; ancla a la fuente del docente"),
    "psicologia":     ("C", "DSM-5-TR/CIE-11 y marcos teóricos declarados; ancla a la fuente del docente"),
    "derecho":        ("C", "SOLO la fuente normativa que adjunta el docente; NUNCA cites artículos de memoria"),
    "quimica":        ("A", "nomenclatura IUPAC (y unidades SI)"),
    "biologia":       ("A", "nomenclatura vigente según subárea (ICZN/ICN/ICNP/HGNC) y consenso"),
    "ingenieria":     ("C", "estándar técnico del subámbito y normativa/país que declara el docente (ISO/IEC 80000 para unidades)"),
    "arquitectura":   ("C", "OGUC/NCh u ordenanza jurisdiccional que declara el docente (ISO dibujo técnico)"),
    "educacion":      ("C", "marco curricular y referentes que declara el docente"),
    "economia_admin": ("C", "marco declarado (NIIF/IFRS o US GAAP en contabilidad; frameworks de consenso)"),
}

_ETIQUETA_NAT = {
    "A": "Estándar de nomenclatura universal — la IA lo cita directamente.",
    "B": "Estándar de unidades/magnitudes — la IA valida unidades, símbolos y cifras.",
    "C": ("Área jurisdiccional o de consenso — la IA corrige contra la FUENTE aportada por el "
          "docente, no desde su memoria. Propuesta = borrador para validación experta."),
}


def _autoridad(area: str) -> tuple[str, str]:
    return _AREAS.get((area or "general"), _AREAS["general"])


def construir_prompt(respuesta: str, cfg: dict) -> tuple[str, str]:
    """
    Arma (system, user) para la corrección experta holística. Función pura (testeable).
    cfg = {enunciado, respuesta_optima, nivel_rigor, area_conocimiento, fuente_estandar,
           peso, escala_max, criterios:[{name,descriptor}] (opcional)}
    """
    rigor = cfg.get("nivel_rigor") if cfg.get("nivel_rigor") in NIVELES_RIGOR else RIGOR_ESTRICTO
    area = cfg.get("area_conocimiento") or "general"
    nat, autoridad = _autoridad(area)
    fuente = (cfg.get("fuente_estandar") or "").strip()
    criterios = cfg.get("criterios") or []

    system = (
        "Eres un corrector académico EXPERTO en la disciplina indicada. PROPONES una corrección; "
        "NUNCA pones la nota final (la fija el docente). Trabajas sobre una respuesta seudonimizada. "
        "Reglas inviolables:\n"
        "1) Corrige aplicando el nivel de rigor y la AUTORIDAD del área que se te indica.\n"
        "2) Si el área es jurisdiccional o de consenso (Derecho, normativa técnica, clínica), NO "
        "afirmes números de ley, artículos ni cifras desde tu memoria: usa SOLO la fuente que "
        "adjunta el docente. Si no hay fuente suficiente, dilo en 'transparencia' y baja la confianza.\n"
        "3) Sé empático y propositivo en la retroalimentación. Responde SOLO con un objeto JSON.")

    P = []
    P.append(f"ÁREA: {area}. AUTORIDAD NOMENCLATURAL/NORMATIVA: {autoridad}.")
    P.append(f"NATURALEZA DEL ESTÁNDAR: {nat} — {_ETIQUETA_NAT[nat]}")
    P.append(_REGLA_RIGOR[rigor])
    if fuente:
        P.append("FUENTE DECLARADA POR EL DOCENTE (corrige contra ESTA, cítala como base):\n"
                 f"\"\"\"\n{fuente[:4000]}\n\"\"\"")
    elif nat == "C":
        P.append("AVISO: no hay fuente declarada y el área es jurisdiccional/de consenso. Corrige con "
                 "cautela, NO inventes referencias, y advierte en 'transparencia' que falta la fuente.")
    if cfg.get("enunciado"):
        P.append(f"ENUNCIADO DE LA PREGUNTA:\n{cfg['enunciado']}")
    if cfg.get("respuesta_optima"):
        P.append(f"RESPUESTA ÓPTIMA / DE REFERENCIA DEL DOCENTE:\n{cfg['respuesta_optima']}")
    if criterios:
        crs = "\n".join(f"  - {c.get('name') or c.get('nombre')}: {c.get('descriptor') or ''}"
                        for c in criterios)
        P.append("CRITERIOS DE RÚBRICA (respétalos si existen):\n" + crs)
    else:
        P.append("No hay rúbrica manual: evalúa HOLÍSTICAMENTE contra la respuesta óptima y la "
                 "autoridad del área, y PROPÓN los criterios implícitos que usaste.")
    P.append(f"RESPUESTA DEL ESTUDIANTE:\n\"\"\"\n{(respuesta or '').strip()[:6000]}\n\"\"\"")
    P.append(
        "\nDevuelve SOLO este JSON (sin texto extra):\n"
        "{\n"
        '  "nivel_global": "logrado|parcial|no_logrado",\n'
        '  "puntaje_sugerido": <0.0-1.0 fracción del puntaje de la pregunta>,\n'
        '  "justificacion": "<por qué ese nivel, citando la autoridad/fuente>",\n'
        '  "respuesta_modelo": "<respuesta modelo breve que el docente puede validar/editar>",\n'
        '  "estandar_citado": "<qué autoridad/fuente sustenta la corrección>",\n'
        '  "brechas": ["<vacío conceptual detectado>", "..."],\n'
        '  "estrategias": ["<estrategia de estudio concreta y basada en evidencia>", "..."],\n'
        '  "transparencia": "<nota de transparencia; en Derecho/normativa: \'evaluado según fuente aportada por el docente\'>",\n'
        '  "requiere_revision": <true|false>,\n'
        '  "confianza": <0.0-1.0>\n'
        "}")
    return system, "\n\n".join(P)


_NIVELES = {"logrado": "logrado", "parcial": "parcial", "no_logrado": "no_logrado",
            "no logrado": "no_logrado", "nologrado": "no_logrado"}


def _f(v, d=0.0):
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return d


def _lista(v, n=6):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x)[:400] for x in v if str(x).strip()][:n]


def parsear_respuesta(texto: str, nat: str) -> dict:
    """Extrae/valida el JSON del modelo → propuesta normalizada. Lanza si no es parseable."""
    t = (texto or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1 or j < i:
        raise ValueError("La respuesta del modelo no contiene un objeto JSON.")
    d = json.loads(t[i:j + 1])
    nivel = _NIVELES.get(str(d.get("nivel_global", "")).strip().lower().replace("-", "_"), "parcial")
    # En áreas C, la propuesta es SIEMPRE borrador para validación experta.
    req_rev = bool(d.get("requiere_revision")) or nat == "C"
    return {
        "nivel_global": nivel,
        "puntaje_sugerido": round(_f(d.get("puntaje_sugerido"), 0.0), 2),
        "justificacion": str(d.get("justificacion", ""))[:1500],
        "respuesta_modelo": str(d.get("respuesta_modelo", ""))[:3000],
        "estandar_citado": str(d.get("estandar_citado", ""))[:600],
        "naturaleza_estandar": nat,
        "brechas": _lista(d.get("brechas")),
        "estrategias": _lista(d.get("estrategias")),
        "transparencia": str(d.get("transparencia", ""))[:800],
        "requiere_revision": req_rev,
        "confianza": round(_f(d.get("confianza"), 0.5), 2),
    }


def _llamar_anthropic(system: str, user: str, modelo: str = MODELO_EXPERTO, max_tokens: int = 1800) -> str:
    import anthropic
    cliente = anthropic.Anthropic()          # ANTHROPIC_API_KEY del entorno
    msg = cliente.messages.create(
        model=modelo, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}])
    for bloque in msg.content:
        if getattr(bloque, "type", None) == "text":
            return bloque.text
    return getattr(msg.content[0], "text", "") if msg.content else ""


def _llamar_anthropic_vision(system: str, user: str, imagenes: list, modelo: str = MODELO_EXPERTO,
                             max_tokens: int = 1800) -> str:
    """Igual que _llamar_anthropic pero con IMÁGENES (visión). `imagenes` = [{media_type, data(base64)}].
    Las imágenes van primero y el texto después (recomendación de Anthropic para multi-imagen)."""
    import anthropic
    cliente = anthropic.Anthropic()
    contenido = []
    for im in (imagenes or [])[:6]:                       # tope duro de 6 imágenes por consulta
        data = (im or {}).get("data") or ""
        mt = (im or {}).get("media_type") or "image/jpeg"
        if data:
            contenido.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
    contenido.append({"type": "text", "text": user})
    msg = cliente.messages.create(
        model=modelo, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": contenido}])
    for bloque in msg.content:
        if getattr(bloque, "type", None) == "text":
            return bloque.text
    return getattr(msg.content[0], "text", "") if msg.content else ""


def redactar_texto(texto: str, contexto: str = "", llamar=None) -> dict:
    """
    Limpia un texto DICTADO POR EL DOCENTE (enunciado / respuesta óptima): corrige ortografía,
    gramática y errores de transcripción de voz SIN cambiar el significado, sin agregar
    contenido y sin responder la pregunta. Es el propio texto del docente (no toca G1, que
    aplica a respuestas de alumnos). Sin API key → disponible=False.
    """
    texto = (texto or "").strip()
    if not texto:
        return {"ok": False, "disponible": True, "error": "No hay texto que redactar."}
    if llamar is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "disponible": False,
                "error": "La redacción con IA necesita ANTHROPIC_API_KEY configurada."}
    system = (
        "Eres un editor de textos académicos. Tu ÚNICA tarea es limpiar un texto que un docente "
        "dictó por voz y quedó con errores de transcripción. REGLAS ESTRICTAS: (1) corrige "
        "ortografía, gramática, puntuación y palabras mal transcritas; (2) NO cambies el "
        "significado ni el nivel de detalle; (3) NO agregues información, ejemplos ni respondas "
        "ninguna pregunta; (4) si una parte es ininteligible, deja la mejor reconstrucción fiel y "
        "no inventes datos. Devuelve SOLO el texto corregido, sin comillas ni comentarios.")
    user = ((f"Contexto (no lo incluyas en la salida): {contexto}\n\n" if contexto else "")
            + "Texto dictado a limpiar:\n\"\"\"\n" + texto[:4000] + "\n\"\"\"")
    try:
        crudo = (llamar or _llamar_anthropic)(system, user)
        limpio = (crudo or "").strip().strip('"').strip()
        return {"ok": bool(limpio), "disponible": True, "texto": limpio or texto}
    except Exception as e:
        logger.warning("Redacción falló: %s", f"{type(e).__name__}: {e}"[:200])
        return {"ok": False, "disponible": True, "error": f"{type(e).__name__}: {e}"[:200]}


def corregir(respuesta: str, cfg: dict, llamar=None) -> dict:
    """
    Motor experto. Devuelve {ok, disponible, motor, propuesta|error}.
    `llamar(system, user)->str` inyectable en tests. Sin API key → disponible=False (no rompe).
    """
    nat, _ = _autoridad(cfg.get("area_conocimiento") or "general")
    if llamar is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "disponible": False,
                "error": "El motor de corrección experta necesita ANTHROPIC_API_KEY configurada."}
    system, user = construir_prompt(respuesta, cfg)
    try:
        crudo = (llamar or _llamar_anthropic)(system, user)
        propuesta = parsear_respuesta(crudo, nat)
        return {"ok": True, "disponible": True, "motor": "llm", "propuesta": propuesta}
    except Exception as e:
        logger.warning("Corrección experta falló: %s", f"{type(e).__name__}: {e}"[:200])
        return {"ok": False, "disponible": True, "motor": "llm_error",
                "error": f"{type(e).__name__}: {e}"[:200]}
