"""
5º módulo · EXAMEN ORAL — motor IA (F2 · 3 capas + síntesis; F3 · evaluación 4 criterios).

Por cada segmento (una pregunta) toma la transcripción LITERAL (Capa 2) y produce:
  • Capa 3 — versión normalizada (solo fonético/orto/gramática con alta confianza) + síntesis
    estructurada + correcciones fonéticas con confianza. PROHIBIDO agregar contenido o convertir
    un error conceptual en acierto.
  • Evaluación por 4 criterios (puntaje 0-1 + justificación + evidencia), con la ponderación de
    la pregunta → nota de la escala. La IA PROPONE; el docente valida y publica (G1).

Sin ANTHROPIC_API_KEY → disponible=False (no rompe). Reusa el cliente de correccion_experta.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")

from app.services import correccion_experta_service as ce
from app.services.result_service import calculate_grade

# Criterios plantilla (editables) si el docente no definió los suyos.
CRITERIOS_DEFECTO = [
    {"nombre": "Exactitud y dominio disciplinar", "peso": 25.0},
    {"nombre": "Razonamiento, fundamentación y aplicación", "peso": 25.0},
    {"nombre": "Organización, coherencia y completitud", "peso": 25.0},
    {"nombre": "Comunicación oral y uso del lenguaje técnico", "peso": 25.0},
]


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


def _json_robusto(crudo: str) -> dict:
    """Extrae el objeto JSON de la respuesta del modelo, tolerando truncación (cierra strings,
    arrays y objetos abiertos y descarta comas colgantes)."""
    t = (crudo or "").strip()
    i = t.find("{")
    if i < 0:
        raise ValueError("La respuesta del modelo no contiene JSON.")
    t = t[i:]
    j = t.rfind("}")
    if j > 0:
        try:
            return json.loads(t[:j + 1])
        except Exception:
            pass
    # Reparación de truncación: pila de cierres (LIFO) para cerrar en el orden correcto.
    stack = []; in_str = False; esc = False
    for ch in t:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack:
                stack.pop()
    s = t
    if in_str:
        s += '"'
    s = s.rstrip()
    if s.endswith(","):
        s = s[:-1]
    s += "".join(reversed(stack))
    return json.loads(s)


def procesar_segmento(literal: str, cfg: dict, criterios: list, llamar=None) -> dict:
    """Devuelve {normalizada, sintesis, correcciones, confianza, evaluaciones[]} para un segmento."""
    literal = (literal or "").strip()
    if not literal:
        return {"vacio": True, "normalizada": "", "sintesis": {}, "correcciones": [],
                "confianza": 0.0, "evaluaciones": []}
    area = cfg.get("area_conocimiento") or "general"
    nat, autoridad = ce._autoridad(area)
    rigor = cfg.get("nivel_rigor") if cfg.get("nivel_rigor") in ce.NIVELES_RIGOR else ce.RIGOR_ESTRICTO
    optima = cfg.get("respuesta_optima") or ""
    conceptos = cfg.get("conceptos_indispensables") or ""
    crit_txt = "\n".join(f"  {i+1}. {c['nombre']} (peso {c.get('peso',25)}%)"
                         for i, c in enumerate(criterios))

    system = (
        "Eres un evaluador oral experto y un editor riguroso. Trabajas sobre la TRANSCRIPCIÓN "
        "LITERAL de la respuesta hablada de un estudiante (seudonimizada). Reglas INVIOLABLES:\n"
        "1) La versión normalizada corrige SOLO errores fonéticos/de transcripción, ortografía y "
        "gramática, y quita muletillas (eh, mmm, o sea, como que). NO agregas contenido, NO "
        "completas ideas, NO conviertes un error conceptual en acierto. Si dijo 'arteria pulmonar' "
        "por 'vena pulmonar', se CONSERVA el error.\n"
        "2) Solo corriges una palabra si hay alta evidencia de error de reconocimiento fonético "
        "(p. ej. 'foramen yugolar'→'yugular'); si hay duda, la dejas y la marcas en 'correcciones' "
        "con confianza baja.\n"
        "3) Evalúas por los criterios dados con el NIVEL DE RIGOR indicado y con evidencia citada "
        "de lo efectivamente dicho. La IA PROPONE; el docente decide la nota.\n"
        "4) FUNDAMENTACIÓN: cada criterio incluye un 'fundamento' que respalda tu juicio con una "
        "referencia disciplinar en cita Vancouver BREVE. Distingue FONDO (texto/manual de "
        "referencia de la disciplina, p. ej. Anatomía → Moore KL, Anatomía con orientación clínica, "
        "última ed.; Fisiología → Guyton & Hall; Derecho → el código/ley pertinente) y FORMA "
        "(nomenclatura/norma, p. ej. Anatomía → Terminologia Anatomica FIPAT/IFAA; Química → IUPAC). "
        "Puedes sugerir 1–2 artículos Q1 de alto impacto que apoyen el juicio, en Vancouver. "
        "HONESTIDAD OBLIGATORIA: si no estás seguro de una cita de artículo (autores/año/DOI), "
        "márcala como 'sugerido, verificar' y NO inventes DOIs ni datos exactos con falsa certeza. "
        "Los manuales/normas canónicos sí puedes citarlos con seguridad.\n"
        "Responde SOLO con un objeto JSON.")

    P = [f"ÁREA: {area}. Autoridad de FORMA (nomenclatura): {autoridad}."]
    P.append("NIVEL DE RIGOR EXIGIDO PARA PUNTUAR:\n" + ce._REGLA_RIGOR.get(rigor, ce._REGLA_RIGOR[ce.RIGOR_ESTRICTO]))
    if cfg.get("enunciado"):
        P.append(f"PREGUNTA: {cfg['enunciado']}")
    if optima:
        P.append(f"RESPUESTA ESPERADA/PAUTA (referencia del docente, NO para completar lo que el "
                 f"estudiante no dijo): {optima}")
    if conceptos:
        P.append(f"CONCEPTOS INDISPENSABLES: {conceptos}")
    P.append("CRITERIOS DE EVALUACIÓN (evalúa cada uno, puntaje 0.0-1.0):\n" + crit_txt)
    P.append(f"TRANSCRIPCIÓN LITERAL DEL ESTUDIANTE:\n\"\"\"\n{literal[:6000]}\n\"\"\"")
    P.append(
        "\nDevuelve SOLO este JSON:\n"
        "{\n"
        '  "normalizada": "<transcripción limpia: fonético/orto/gramática + sin muletillas; MISMO contenido>",\n'
        '  "correcciones": [{"original":"<palabra dicha>","corregido":"<palabra>","confianza":<0-1>}],\n'
        '  "sintesis": {"idea_central":"...","conceptos_correctos":["..."],"argumentos":["..."],'
        '"incompleto":["..."],"errores":["..."],"conceptos_omitidos":["..."],"sintesis_final":"..."},\n'
        '  "confianza": <0-1 confianza global de la transcripción>,\n'
        '  "referencias": {"fondo":"<manual/texto de referencia de la disciplina, Vancouver breve>",'
        '"forma":"<norma/nomenclatura, Vancouver breve>","articulos":["<artículo Q1 Vancouver breve (sugerido, verificar)>"]},\n'
        '  "evaluaciones": [{"criterio":"<nombre exacto>","puntaje":<0-1>,"justificacion":"...",'
        '"evidencia":"<cita breve de lo dicho>","fundamento":"<cita Vancouver breve que respalda ESTE criterio (forma o fondo)>","confianza":<0-1>}]\n'
        "}")
    # El JSON con síntesis + fundamentos + citas Vancouver es grande → tokens holgados para no truncar.
    _call = llamar or (lambda s, u: ce._llamar_anthropic(s, u, max_tokens=6000))
    try:
        crudo = _call(system, "\n\n".join(P))
        d = _json_robusto(crudo)
    except Exception as e:
        logger.warning("Examen oral · procesar_segmento falló: %s", f"{type(e).__name__}: {e}"[:200])
        raise

    sn = d.get("sintesis") or {}
    sintesis = {
        "idea_central": str(sn.get("idea_central", ""))[:800],
        "conceptos_correctos": _lista(sn.get("conceptos_correctos")),
        "argumentos": _lista(sn.get("argumentos")),
        "incompleto": _lista(sn.get("incompleto")),
        "errores": _lista(sn.get("errores")),
        "conceptos_omitidos": _lista(sn.get("conceptos_omitidos")),
        "sintesis_final": str(sn.get("sintesis_final", ""))[:1000],
    }
    # Alinea las evaluaciones a los criterios pedidos (por nombre; si falta, 0 con revisión).
    por_nombre = {}
    for e in (d.get("evaluaciones") or []):
        por_nombre[str(e.get("criterio", "")).strip().lower()] = e
    evals = []
    for c in criterios:
        e = por_nombre.get(c["nombre"].strip().lower(), {})
        evals.append({
            "criterio": c["nombre"], "peso_criterio": float(c.get("peso", 25.0)),
            "puntaje_ia": round(_f(e.get("puntaje"), 0.0), 2),
            "justificacion": str(e.get("justificacion", ""))[:800],
            "evidencia": str(e.get("evidencia", ""))[:500],
            "fundamento": str(e.get("fundamento", ""))[:400],
            "confianza": round(_f(e.get("confianza"), 0.5), 2),
        })
    rf = d.get("referencias") or {}
    referencias = {"fondo": str(rf.get("fondo", ""))[:400],
                   "forma": str(rf.get("forma", ""))[:400],
                   "articulos": _lista(rf.get("articulos"), 3)}
    return {"vacio": False, "normalizada": str(d.get("normalizada", ""))[:6000],
            "correcciones": (d.get("correcciones") or [])[:20],
            "sintesis": sintesis, "referencias": referencias,
            "confianza": round(_f(d.get("confianza"), 0.5), 2),
            "evaluaciones": evals}


def procesar_examen(db, sesion, llamar=None) -> dict:
    """Procesa TODOS los segmentos de la sesión: persiste Capa 3 + evaluaciones y calcula la nota
    ponderada propuesta (la IA propone; el docente valida). Sin API key → disponible=False."""
    from app.models.examen_oral import OralExamSegmento, OralExamEvaluacion, OE_REVISION
    from app.models.answer_key import AnswerKeyItem
    from app.models.assessment import Assessment
    if llamar is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "disponible": False,
                "error": "El motor de examen oral necesita ANTHROPIC_API_KEY configurada."}

    asm = db.get(Assessment, sesion.assessment_id)
    escala = (asm.grading_scale if asm else "chile_1_7") or "chile_1_7"
    exig = (asm.passing_threshold if asm and asm.passing_threshold is not None else 60.0)
    cfg = sesion.config_json or {}
    criterios = cfg.get("criterios") or CRITERIOS_DEFECTO

    num = 0.0; den = 0.0; procesados = 0
    for seg in sorted(sesion.segmentos, key=lambda x: x.pregunta_numero):
        item = db.get(AnswerKeyItem, seg.answer_key_item_id) if seg.answer_key_item_id else None
        peso_preg = float(getattr(item, "weight", 1.0) or 1.0)
        den += peso_preg
        if seg.sin_respuesta or not (seg.transcripcion_literal or "").strip():
            continue
        scfg = {
            "enunciado": getattr(item, "enunciado", "") if item else "",
            "respuesta_optima": (getattr(item, "respuesta_optima", None) or getattr(item, "correct_answer", "")) if item else "",
            "conceptos_indispensables": getattr(item, "conceptos_indispensables", None) if item else "",
            "area_conocimiento": getattr(item, "area_conocimiento", None) or "general",
            "nivel_rigor": getattr(item, "nivel_rigor", None) or "estricto",
        }
        try:
            r = procesar_segmento(seg.transcripcion_literal, scfg, criterios, llamar=llamar)
        except Exception as e:
            return {"ok": False, "disponible": True, "motor": "llm_error",
                    "error": f"{type(e).__name__}: {e}"[:200]}
        seg.version_normalizada = r["normalizada"] or None
        _sint = dict(r["sintesis"]); _sint["referencias"] = r.get("referencias")   # Fondo/Forma/artículos a nivel pregunta
        seg.sintesis_json = _sint
        seg.confianza = r["confianza"]
        seg.correcciones_json = r["correcciones"]
        db.query(OralExamEvaluacion).filter(OralExamEvaluacion.segmento_id == seg.id).delete()
        pj_preg = 0.0; wsum = 0.0
        for e in r["evaluaciones"]:
            db.add(OralExamEvaluacion(
                segmento_id=seg.id, criterio=e["criterio"], peso_criterio=e["peso_criterio"],
                puntaje_ia=e["puntaje_ia"],
                evidencia_json={"evidencia": e["evidencia"], "fundamento": e.get("fundamento", "")},
                justificacion=e["justificacion"], confianza=e["confianza"]))
            pj_preg += e["puntaje_ia"] * e["peso_criterio"]; wsum += e["peso_criterio"]
        frac_preg = (pj_preg / wsum) if wsum else 0.0
        num += frac_preg * peso_preg
        procesados += 1

    pct = round(num / den * 100, 1) if den else 0.0
    nota, etiqueta, aprob = calculate_grade(pct, escala, exig)
    sesion.estado = OE_REVISION
    sesion.logro_pct = pct
    sesion.nota_final = round(nota, 1)   # PROPUESTA; el docente la confirma al publicar (G1)
    db.commit()
    return {"ok": True, "disponible": True, "procesados": procesados,
            "logro_pct": pct, "nota_propuesta": round(nota, 1), "etiqueta": etiqueta,
            "escala": escala}
