"""Pedagogía proactiva — la IA PROPONE acciones docentes a partir del diagnóstico; el docente VALIDA (G1).

proponer_remediacion(tipo, debilidad, contexto):
  A partir de una DEBILIDAD detectada por la analítica (RA con bajo logro, ítem que discrimina poco,
  distractor-trampa) genera una acción pedagógica lista para usar:
    - 'repaso'   : micro-repaso de ~5 min para la próxima clase.
    - 'items'    : ítems de alternativas de refuerzo (enunciado/opciones/correcta/justificación).
    - 'dinamica' : una dinámica/debate/micro-caso para trabajar la brecha en clase.
    - 'mensaje'  : un mensaje cálido al grupo con la brecha y cómo prepararse.
  Nunca inventa cifras: usa solo lo que la debilidad y el contexto reportan. El docente revisa,
  ajusta y libera. Sin ANTHROPIC_API_KEY → {ok:false, disponible:false}.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("evalys")


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


_PROMPTS = {
    "repaso": (
        "Diseña un MICRO-REPASO de ~5 minutos para iniciar la próxima clase y cerrar la brecha. "
        'Devuelve SOLO JSON: {"titulo":"..","objetivo":"..","pasos":[{"minuto":"0-1","actividad":".."}],'
        '"cierre":"..","materiales":".."}. 3-4 pasos, concreto y accionable, en el idioma del contexto.'
    ),
    "items": (
        "Redacta ítems de alternativas de REFUERZO (opción múltiple, 4 opciones A-D, una correcta) que "
        "ataquen exactamente el concepto de la brecha, con un distractor que capture el error típico. "
        'Devuelve SOLO JSON: {"items":[{"enunciado":"..","opciones":[{"letra":"A","texto":".."},'
        '{"letra":"B","texto":".."},{"letra":"C","texto":".."},{"letra":"D","texto":".."}],'
        '"correcta":"A","justificacion":".."}]}. Genera 3 ítems salvo que se pida otro número.'
    ),
    "dinamica": (
        "Diseña UNA dinámica de aula (debate, micro-caso, pregunta socrática o actividad breve) para "
        "trabajar la brecha de forma activa. "
        'Devuelve SOLO JSON: {"titulo":"..","formato":"..","duracion_min":10,"pregunta_disparadora":"..",'
        '"instrucciones":["..",".."],"criterio_exito":".."}.'
    ),
    "mensaje": (
        "Redacta un MENSAJE breve y cálido para el grupo curso: nombra la brecha sin señalar a nadie, "
        "explica por qué importa y da 2-3 acciones concretas para prepararse. Tono cercano y motivador, "
        'no punitivo. Devuelve SOLO JSON: {"asunto":"..","cuerpo":".."}.'
    ),
}


def proponer_remediacion(tipo: str, debilidad: dict, contexto: dict, n_items: int = 3) -> dict:
    tipo = (tipo or "repaso").strip().lower()
    if tipo not in _PROMPTS:
        return {"ok": False, "error": "tipo no válido"}
    if not _disponible():
        return {"ok": False, "disponible": False}
    from app.services import correccion_experta_service as ce
    debilidad = debilidad or {}
    contexto = contexto or {}
    system = (
        "Eres un asesor pedagógico experto que ayuda a un docente universitario a convertir un hallazgo "
        "de la analítica de su evaluación en una acción concreta de aula. Trabajas SOLO con lo que el "
        "docente reporta (la brecha y el contexto): no inventes cifras ni datos que no estén. Escribe en "
        "el idioma del contexto (por defecto español). La IA propone; el docente valida y libera (G1).\n\n"
        + _PROMPTS[tipo]
    )
    partes = ["BRECHA DETECTADA:",
              "- Título: " + str(debilidad.get("titulo", "")),
              "- Detalle: " + str(debilidad.get("detalle", ""))]
    if debilidad.get("ra"):
        partes.append("- Resultado de aprendizaje: " + str(debilidad.get("ra")))
    if debilidad.get("logro") is not None:
        partes.append("- Logro actual: " + str(debilidad.get("logro")) + "%")
    partes += ["", "CONTEXTO DEL CURSO:",
               "- Curso: " + str(contexto.get("curso", "(no dado)")),
               "- Evaluación: " + str(contexto.get("evaluacion", "(no dada)")),
               "- Tema/materia: " + str(contexto.get("tema", contexto.get("curso", "(no dado)")))]
    if tipo == "items" and n_items:
        partes.append("- Nº de ítems a generar: " + str(int(n_items)))
    user = "\n".join(partes)
    try:
        crudo = ce._llamar_anthropic(system, user, max_tokens=2200)
        d = _json_robusto(crudo)
        return {"ok": True, "tipo": tipo, "contenido": d,
                "motor": "IA (" + ce.MODELO_EXPERTO + ")",
                "aviso": "Propuesta pedagógica de la IA — revísala y ajústala antes de usarla (G1)."}
    except Exception as e:  # noqa: BLE001
        logger.warning("proponer_remediacion falló: %s", str(e)[:150])
        return {"ok": False, "error": str(e)[:200]}
