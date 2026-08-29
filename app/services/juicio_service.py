"""
Runi lee lo que la estudiante escribió y emite un juicio.

Esto cierra el hueco que dejaba el repaso: pedía «¿cómo se aplica esto? da un ejemplo», ella escribía
la respuesta… y el texto se descartaba. Lo único que quedaba era si se había puesto «Lo supe». Con
eso se puede medir constancia, pero no si conectó dos ideas ni si supo aplicar algo a un caso nuevo,
que es justo lo que piden las medallas 4, 5 y 7.

Cuatro tipos de consigna, de menor a mayor exigencia:
  recordar → recuperar de memoria
  conectar → relacionar el tema de hoy con OTRO que ya estudió (linkedConcepts)
  aplicar  → resolver un caso que no estaba en el material (novelTransferCases)
  integrar → explicar cómo encajan varios conceptos en un resultado (conceptsIntegrated)

**El juicio del modelo no manda solo.** Una evidencia cuenta para una puerta únicamente si el
autorreporte de la estudiante y el juicio de Runi COINCIDEN. Si discrepan se guarda igual y se le
muestra la diferencia —que es información valiosa sobre su calibración—, pero no abre ninguna puerta.
Un modelo se equivoca; que su error cueste una medalla sería injusto y difícil de explicar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.juicio import TIPOS, EpisodeJuicio

_LOG = logging.getLogger("evalys")
_MAX_RESP = 4000


def _huella(tipo: str, ra: str, texto: str, ra_b: str | None = None) -> str:
    """Identifica una evidencia para que repetirla no vuelva a contar (antiFarming del spec v3).

    En «conectar» la evidencia es el PAR, no un tema suelto: el par va en la huella y ordenado, para
    que conectar A con B y B con A sean la misma conexión aunque se redacten distinto.
    """
    norm = re.sub(r"\s+", " ", (texto or "").strip().lower())
    par = "|".join(sorted(x for x in ((ra or "").lower(), (ra_b or "").lower()) if x))
    return hashlib.sha256(f"{tipo}|{par}|{norm}".encode()).hexdigest()[:64]


_CONSIGNAS = {
    "recordar": "Sin mirar apuntes, explica con tus palabras: {a}.",
    "conectar": "¿Cómo se relaciona «{a}» con «{b}»? Explica la conexión, no cada una por separado.",
    "aplicar": "Aplica «{a}» a una situación nueva: describe un caso concreto y cómo lo resolverías.",
    "integrar": "Explica cómo encajan al menos tres conceptos del curso en un mismo resultado, usando «{a}» como eje.",
}


def consigna(tipo: str, ra: str, ra_b: str | None = None) -> str:
    t = _CONSIGNAS.get(tipo, _CONSIGNAS["recordar"])
    return t.format(a=(ra or "tu tema"), b=(ra_b or "otro tema que ya estudiaste"))


def _prompt(tipo: str, ra: str, ra_b: str | None, contexto: str) -> tuple:
    base = (
        "Eres Runi, copiloto de aprendizaje. Vas a leer la respuesta escrita de una estudiante y decir "
        "si demuestra lo que se le pidió. NO eres un examinador que busca errores: eres quien reconoce "
        "cuando alguien entendió, aunque lo diga con sus palabras y de forma incompleta.\n"
        "Criterio general: acepta la respuesta si el NÚCLEO conceptual es correcto, aunque falte "
        "detalle, haya faltas de ortografía o el orden sea distinto al del material. Recházala solo si "
        "hay un error conceptual real, si no responde lo que se preguntó, o si está vacía o es evasiva "
        "('no sé', 'lo vi pero no me acuerdo').\n"
    )
    especifico = {
        "recordar": "Se le pidió RECORDAR. Basta con que recupere las ideas centrales del tema.\n",
        "conectar": ("Se le pidió CONECTAR dos temas. Acepta SOLO si explica una relación real entre "
                     "AMBOS (causa, dependencia, contraste, secuencia, parte-todo). Describir cada tema "
                     "por separado, sin vínculo, NO es conectar.\n"),
        "aplicar": ("Se le pidió APLICAR a una situación NUEVA. Acepta SOLO si describe un caso concreto "
                    "y cómo el concepto opera ahí. Repetir la definición, o un ejemplo textual del "
                    "material, NO es aplicar.\n"),
        "integrar": ("Se le pidió INTEGRAR al menos tres conceptos en un mismo resultado. Acepta SOLO si "
                     "articula tres o más conceptos del curso de forma que dependan entre sí. Enumerar "
                     "conceptos sueltos NO es integrar. Lista en 'conceptos' los que realmente integró.\n"),
    }[tipo]
    system = base + especifico + (
        "Devuelve SOLO JSON: {\"correcto\": true|false, \"conceptos\": [\"…\"], "
        "\"razon\": \"una frase corta, en segunda persona y sin condescendencia, diciendo qué reconociste "
        "o qué faltó\"}. La razón la va a leer ella: que sea útil, no un veredicto."
    )
    user = ""
    if contexto:
        user += "MATERIAL DEL CURSO (referencia, puede no cubrirlo todo):\n" + contexto[:6000] + "\n\n"
    user += "TEMA: " + (ra or "—") + "\n"
    if ra_b:
        user += "SEGUNDO TEMA: " + ra_b + "\n"
    return system, user


def _juzgar_con_ia(tipo: str, ra: str, ra_b: str | None, respuesta: str, contexto: str) -> dict | None:
    """Devuelve {correcto, conceptos, razon} o None si el motor no está disponible.

    None NO es 'incorrecto': es 'no se pudo juzgar'. La diferencia importa — dar por mala una
    respuesta porque el servicio de IA está caído sería exactamente el tipo de injusticia que este
    módulo existe para evitar.
    """
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    system, user = _prompt(tipo, ra, ra_b, contexto)
    user += "\nRESPUESTA DE LA ESTUDIANTE:\n" + (respuesta or "")[:_MAX_RESP]
    try:
        from app.services import correccion_experta_service as ce
        crudo = ce._llamar_anthropic(system, user, max_tokens=500)
        m = re.search(r"\{.*\}", crudo or "", re.S)
        d = json.loads(m.group(0)) if m else None
        if not isinstance(d, dict) or "correcto" not in d:
            return None
        return {"correcto": bool(d.get("correcto")),
                "conceptos": [str(x)[:80] for x in (d.get("conceptos") or [])][:8],
                "razon": str(d.get("razon") or "")[:400]}
    except Exception as e:  # noqa: BLE001
        _LOG.warning("juicio: no se pudo juzgar (%s): %s", tipo, str(e)[:120])
        return None


def _contexto_del_curso(db: Session, course_id) -> str:
    """El material del docente, si el episodio viene de un curso con agente de sílabo."""
    if not course_id:
        return ""
    try:
        from app.models.silabo import SilaboAgente
        a = (db.query(SilaboAgente).filter(SilaboAgente.codigo == str(course_id)).first()
             or db.query(SilaboAgente).filter(SilaboAgente.course_id == course_id).first())
        return (a.contexto or "") if a else ""
    except Exception:  # noqa: BLE001
        return ""


def juzgar(db: Session, pseudo_id: str, tipo: str, ra: str, respuesta: str,
           auto_reporte: bool | None = None, episode_id=None, course_id=None,
           ra_b: str | None = None, confianza: int = 0) -> dict:
    """Guarda la respuesta escrita y el juicio de Runi. Siempre guarda, juzgue o no."""
    tipo = (tipo or "recordar").strip().lower()
    if tipo not in TIPOS:
        raise unprocessable("Tipo de consigna no válido.")
    if not (pseudo_id or "").strip():
        raise unprocessable("Falta la identidad del estudiante.")
    texto = (respuesta or "").strip()[:_MAX_RESP]

    veredicto = _juzgar_con_ia(tipo, ra, ra_b, texto, _contexto_del_curso(db, course_id)) if texto else None
    juicio = veredicto["correcto"] if veredicto else None
    # Concordancia: solo cuando AMBOS dicen que sí. Es lo que abre las puertas de las medallas.
    concordancia = bool(veredicto and juicio and auto_reporte)

    eid = None
    if episode_id:
        try:
            eid = _uuid.UUID(str(episode_id))
        except (ValueError, TypeError):
            eid = None

    j = EpisodeJuicio(
        episode_id=eid, pseudo_id=str(pseudo_id)[:80],
        course_id=(str(course_id)[:64] if course_id else None), tipo=tipo,
        ra=(str(ra)[:120] if ra else None), ra_b=(str(ra_b)[:120] if ra_b else None),
        consigna=consigna(tipo, ra, ra_b), respuesta=texto, huella=_huella(tipo, ra, texto, ra_b),
        auto_reporte=(None if auto_reporte is None else bool(auto_reporte)),
        juicio=juicio, concordancia=concordancia,
        conceptos=(veredicto or {}).get("conceptos"), razon=(veredicto or {}).get("razon"),
        confianza=max(0, min(100, int(confianza or 0))))
    db.add(j); db.commit(); db.refresh(j)

    # Qué se le muestra. Cuando discrepan, se nombra la diferencia sin decidir por ella.
    if veredicto is None:
        mensaje = "No pude revisarlo ahora mismo. Tu respuesta quedó guardada igual."
    elif concordancia:
        mensaje = veredicto["razon"] or "Coincidimos: lo tienes."
    elif juicio and auto_reporte is False:
        mensaje = "Yo sí lo veo bien: " + (veredicto["razon"] or "está correcto.") + " Fuiste dura contigo."
    elif juicio is False and auto_reporte:
        mensaje = "Aquí no coincidimos: " + (veredicto["razon"] or "le falta algo.") + " Vale la pena volver sobre esto."
    else:
        mensaje = veredicto["razon"] or "Lo revisamos juntos."
    return {"ok": True, "id": str(j.id), "tipo": tipo, "juicio": juicio,
            "auto_reporte": auto_reporte, "concordancia": concordancia,
            "conceptos": j.conceptos or [], "mensaje": mensaje,
            "sin_juicio": veredicto is None}


# ── Señales para el motor de logros ───────────────────────────────────────────────────
def senales(db: Session, pseudo_id: str) -> dict:
    """Traduce los juicios en las señales que piden las puertas de las medallas 4, 5 y 7.

    Solo cuenta lo CONCORDANTE, y cada evidencia una sola vez: la misma respuesta repetida comparte
    huella y no vuelve a sumar (antiFarming del spec v3).
    """
    filas = (db.query(EpisodeJuicio)
             .filter(EpisodeJuicio.pseudo_id == pseudo_id, EpisodeJuicio.concordancia.is_(True)).all())
    vistas, pares, transfer, integraciones, max_conceptos = set(), set(), 0, 0, 0
    for j in filas:
        if j.huella in vistas:
            continue
        vistas.add(j.huella)
        if j.tipo == "conectar" and j.ra and j.ra_b:
            # El par es simétrico: conectar A con B es la misma conexión que B con A.
            pares.add(tuple(sorted((j.ra.lower(), j.ra_b.lower()))))
        elif j.tipo == "aplicar":
            transfer += 1
        elif j.tipo == "integrar":
            n = len(j.conceptos or [])
            max_conceptos = max(max_conceptos, n)
            if n >= 3:
                integraciones += 1
    return {"linkedConcepts": len(pares), "novelTransferCases": transfer,
            "conceptsIntegrated": max_conceptos, "integratedOutcomes": integraciones}


def mis_juicios(db: Session, pseudo_id: str, limite: int = 20) -> dict:
    filas = (db.query(EpisodeJuicio).filter(EpisodeJuicio.pseudo_id == pseudo_id)
             .order_by(EpisodeJuicio.created_at.desc()).limit(min(int(limite or 20), 100)).all())
    return {"ok": True, "juicios": [
        {"tipo": j.tipo, "ra": j.ra, "ra_b": j.ra_b, "auto_reporte": j.auto_reporte,
         "juicio": j.juicio, "concordancia": j.concordancia, "razon": j.razon,
         "conceptos": j.conceptos or [],
         "fecha": j.created_at.isoformat() if j.created_at else None} for j in filas]}
