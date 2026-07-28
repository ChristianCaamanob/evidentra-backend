"""Escudo de comunicación — lógica del agente de sílabo + bandeja clasificada (Pilar II).

La IA responde SOLO con el contexto del curso que cargó el docente. Si la pregunta no está
cubierta o requiere una decisión humana (cambio de fecha, excepción, nota), la marca para la
bandeja del docente. Todo se persiste clasificado (categoría + urgencia + estado).
"""
from __future__ import annotations

import json
import logging
import re
import secrets

from sqlalchemy.orm import Session

from app.core.errors import not_found, conflict
from app.models.silabo import (
    SilaboAgente, MensajeSilabo, MSG_RESPONDIDA, MSG_PENDIENTE, MSG_RESUELTA,
)

logger = logging.getLogger("evalys")
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CATEGORIAS = ("fechas", "contenido", "evaluación", "logística", "otro")


def _generar_codigo(db: Session) -> str:
    for _ in range(30):
        cod = "".join(secrets.choice(_ALFABETO) for _ in range(6))
        if not db.query(SilaboAgente).filter(SilaboAgente.codigo == cod).first():
            return cod
    return "".join(secrets.choice(_ALFABETO) for _ in range(8))


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


# ── agente (docente) ─────────────────────────────────────────────────────────────────
def agente_de_curso(db: Session, course_id) -> SilaboAgente | None:
    return db.query(SilaboAgente).filter(SilaboAgente.course_id == str(course_id)).first()


def agente_por_codigo(db: Session, codigo: str) -> SilaboAgente:
    a = db.query(SilaboAgente).filter(SilaboAgente.codigo == str(codigo).upper()).first()
    if not a:
        raise not_found("Agente de sílabo no encontrado.")
    return a


def crear_o_actualizar(db: Session, course_id, contexto: str, activo: bool,
                       nombre_curso: str | None = None, config: dict | None = None) -> SilaboAgente:
    a = agente_de_curso(db, course_id)
    if not a:
        a = SilaboAgente(course_id=str(course_id), codigo=_generar_codigo(db),
                         contexto=contexto or "", activo=bool(activo),
                         nombre_curso=nombre_curso, config=config or {})
        db.add(a)
    else:
        a.contexto = contexto if contexto is not None else a.contexto
        a.activo = bool(activo)
        if nombre_curso:
            a.nombre_curso = nombre_curso
        if config is not None:
            a.config = config
    db.commit(); db.refresh(a)
    return a


def join_url(codigo: str, base: str) -> str:
    base = (base or "").rstrip("/")
    return f"{base}/app.html?silabo={codigo}" if base else codigo


# ── Nivel 2 · Ayudante (opcional) ─────────────────────────────────────────────────────
def configurar_ayudante(db: Session, course_id, activo: bool) -> SilaboAgente:
    a = agente_de_curso(db, course_id)
    if not a:
        raise conflict("Primero configure y publique el agente del curso.")
    a.ayudante_activo = bool(activo)
    if activo and not a.ayudante_codigo:
        a.ayudante_codigo = _generar_codigo(db)
    db.commit(); db.refresh(a)
    return a


def ayudante_url(codigo: str, base: str) -> str:
    base = (base or "").rstrip("/")
    return f"{base}/app.html?ayudante={codigo}" if base else codigo


def agente_por_ayudante_codigo(db: Session, codigo: str) -> SilaboAgente:
    a = db.query(SilaboAgente).filter(SilaboAgente.ayudante_codigo == str(codigo).upper()).first()
    if not a:
        raise not_found("Tablero de ayudante no encontrado.")
    return a


def _escalar_vencidos(db: Session, a: SilaboAgente) -> None:
    """Vencimiento automático: los pendientes de NIVEL 2 que pasaron su plazo suben solos al profesor."""
    ahora = _ahora()
    venc = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.estado == MSG_PENDIENTE,
                    MensajeSilabo.nivel == 2).all())
    cambios = 0
    for m in venc:
        if m.vence_ts and m.vence_ts <= ahora:
            m.nivel = 3
            m.vence_ts = ahora + _PLAZO_DOCENTE_H * 3600
            m.motivo_escalamiento = (m.motivo_escalamiento or "Sin respuesta del ayudante en el plazo")
            cambios += 1
    if cambios:
        db.commit()


# ── taxonomía de intención (Antesala) · política y destino por tipo ───────────────────
# Tipos que la IA NUNCA responde con contenido: se arman para el profesor.
_TIPOS_A_DOCENTE = ("fuera_corpus", "evaluativa", "riesgo_clinico")
# Tipos que SIEMPRE se derivan a Secretaría Académica + Dirección (no los trata la Antesala ni el
# docente por este canal): salud, justificaciones y denuncias/ética/acoso.
_TIPOS_DERIVACION = ("personal_salud", "justificacion", "denuncia")
_PLAZO_DOCENTE_H = 48   # horas visibles del reloj para el alumno (Fase 3: horas hábiles + auto-subida)
_PLAZO_AYUDANTE_H = 24  # nivel 2: si el ayudante no responde en 24 h, sube solo al profesor


def _derivacion_texto(a: SilaboAgente) -> str:
    cfg = a.config or {}
    sec = str(cfg.get("contacto_secretaria") or "").strip()
    dire = str(cfg.get("contacto_direccion") or "").strip()
    partes = ["Esto no lo resuelve la Antesala. Por su naturaleza —salud, justificaciones o denuncias/"
              "situaciones personales— debe dirigirlo SIEMPRE a la Secretaría Académica y a la Dirección "
              "de su carrera, que son las instancias que corresponden."]
    if sec:
        partes.append("Secretaría Académica: " + sec + ".")
    if dire:
        partes.append("Dirección: " + dire + ".")
    partes.append("Si es urgente o afecta su salud, acuda de forma presencial. No está solo/a.")
    return " ".join(partes)


def _ahora() -> int:
    import time
    return int(time.time())


# ── similitud semántica ligera (sin embeddings): Jaccard de tokens normalizados ───────
import unicodedata as _ud

_STOP = {"a", "al", "ante", "aqui", "asi", "el", "la", "los", "las", "un", "una", "unos", "unas",
         "de", "del", "en", "y", "o", "u", "que", "cual", "cuales", "cuanto", "cuanta", "cuantos",
         "cuantas", "como", "para", "por", "con", "sin", "se", "su", "sus", "mi", "mis", "es", "son",
         "hay", "tiene", "tienen", "cuando", "donde", "quien", "cuál", "qué", "cómo", "sobre", "esta",
         "este", "esto", "estas", "estos", "me", "te", "lo", "le", "les", "yo", "tu", "si", "no", "mas",
         "muy", "ya", "he", "ha", "va", "vale"}


def _tokens(texto: str) -> set:
    t = _ud.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not _ud.combining(c))       # sin tildes
    t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOP}


_UMBRAL_SIM = 0.5   # ≥ 0.5 de Jaccard Y ≥ 2 palabras-tema en común = equivalente


def _jaccard(a: set, b: set) -> float:
    """Similitud PRECISION-FIRST: exige ≥ 2 palabras de contenido en común (evita fusionar dos
    preguntas por un solo término compartido). Nota: es LÉXICO — capta redacciones parecidas, no
    sinónimos profundos (eso requiere embeddings, mejora futura)."""
    if not a or not b or len(a & b) < 2:
        return 0.0
    return len(a & b) / len(a | b)


def _es_equivalente(t_a: set, texto_b: str) -> bool:
    return _jaccard(t_a, _tokens(texto_b)) >= _UMBRAL_SIM


def _buscar_cache(db: Session, a: SilaboAgente, pregunta: str):
    """Consistencia + economía: si una pregunta equivalente YA fue respondida y sigue vigente,
    devuelve la MISMA respuesta (prefiere la del docente). Invalida si el contexto se editó
    después (a.updated_at) o si la respuesta venció."""
    t_q = _tokens(pregunta)
    if not t_q:
        return None
    corte = getattr(a, "updated_at", None)
    ahora = _ahora()
    recientes = (db.query(MensajeSilabo)
                 .filter(MensajeSilabo.agente_id == a.id)
                 .order_by(MensajeSilabo.created_at.desc()).limit(300).all())
    mejor, mejor_sim = None, 0.0
    for m in recientes:
        # AUTO-CACHE seguro: solo reusa la respuesta CANÓNICA del DOCENTE (no auto-reusa la de la IA,
        # que en léxico podría confundir "cuándo/dónde"). Es la consistencia que pide el diseño.
        if not (m.respuesta_docente or "").strip():
            continue
        if corte and getattr(m, "created_at", None) and m.created_at < corte:
            continue                                        # contexto cambió después
        if getattr(m, "vence_ts", None) and m.vence_ts and m.vence_ts <= ahora:
            continue                                        # respuesta vencida
        sim = _jaccard(t_q, _tokens(m.pregunta))
        if sim > mejor_sim and sim >= _UMBRAL_SIM:
            mejor, mejor_sim = m, sim
    if not mejor:
        return None
    return {"respuesta": mejor.respuesta_docente,
            "tipo": getattr(mejor, "tipo", "conceptual") or "conceptual",
            "categoria": mejor.categoria or "otro", "por_docente": True,
            "cita": getattr(mejor, "cita", None)}


# ── pregunta del alumno (público) ────────────────────────────────────────────────────
def preguntar(db: Session, codigo: str, pregunta: str, alias: str | None = None,
              device_id: str | None = None, escalar: bool = False) -> dict:
    a = agente_por_codigo(db, codigo)
    if not a.activo:
        raise conflict("El agente del curso no está activo en este momento.")
    pregunta = (pregunta or "").strip()
    if len(pregunta) < 3:
        raise conflict("Escriba su pregunta.")
    if len(pregunta) > 1000:
        pregunta = pregunta[:1000]

    cache_hit, cita, tema, fuente = False, None, None, None
    if escalar:
        # Botón "quiero preguntar a una persona": salta la IA y arma para el docente.
        tipo, respuesta, categoria, urgencia, necesita = (
            "solicitud_humana",
            "Listo: le llevé tu consulta a tu docente. Puedes seguir su estado y su respuesta aquí.",
            "otro", "media", True)
        fuente = "ninguna"
    else:
        cache = _buscar_cache(db, a, pregunta)
        if cache:
            # Consistencia: una pregunta equivalente ya respondida → la MISMA respuesta, sin re-inferir.
            tipo, respuesta, categoria, urgencia, necesita = (
                cache["tipo"], cache["respuesta"], cache["categoria"], "baja", False)
            cita = cache.get("cita"); tema = cache.get("tema"); fuente = cache.get("fuente"); cache_hit = True
        else:
            intentos = _intentos_equivalentes(db, a, pregunta, device_id)
            tipo, respuesta, categoria, urgencia, necesita, cita, tema, fuente = _clasificar_y_responder(a, pregunta, intentos)

    estado = MSG_PENDIENTE if necesita else MSG_RESPONDIDA
    # Nivel de escalamiento: si hay ayudante activo, lo pendiente pasa PRIMERO por el ayudante (nivel 2, 24 h);
    # si no, va directo al profesor (nivel 3, 48 h). Lo ya respondido no escala.
    if necesita:
        nivel = 2 if a.ayudante_activo else 3
        vence = _ahora() + (_PLAZO_AYUDANTE_H if nivel == 2 else _PLAZO_DOCENTE_H) * 3600
        respondido_por = None
    else:
        nivel = 1
        vence = None
        respondido_por = "docente" if cache_hit else "ia"
    m = MensajeSilabo(agente_id=a.id, alias=(alias or None), device_id=(device_id or None),
                      pregunta=pregunta, respuesta_ia=respuesta, tipo=tipo, categoria=categoria, cita=cita,
                      tema=tema, fuente=fuente,
                      urgencia=urgencia, necesita_docente=bool(necesita), estado=estado, vence_ts=vence,
                      nivel=nivel, respondido_por=respondido_por)
    db.add(m); db.commit(); db.refresh(m)
    return {"respuesta": respuesta, "necesita_docente": bool(necesita), "tipo": tipo, "cache": cache_hit,
            "cita": cita, "categoria": categoria, "urgencia": urgencia, "mensaje_id": str(m.id), "vence_ts": vence}


def _intentos_equivalentes(db: Session, a: SilaboAgente, pregunta: str, device_id: str | None) -> int:
    """Cuántas veces ESTE dispositivo ya preguntó algo equivalente (regla de rendición)."""
    if not device_id:
        return 0
    t = _tokens(pregunta)
    if not t:
        return 0
    prev = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
            .order_by(MensajeSilabo.created_at.desc()).limit(40).all())
    return sum(1 for m in prev if _es_equivalente(t, m.pregunta))


# Meta-estudio: cómo estudiar/prepararse. Runi SIEMPRE puede responderlo (capa C), aunque el LLM falle.
_META_ESTUDIO_RE = re.compile(
    r"c[oó]mo\s+(estudi|prepar|repas|memoriz|aprend|organiz)|"
    r"\b(estudiar|estudio|repasar|repaso|prepararme|preparar|memorizar|mnemot|"
    r"plan de estudio|estrategi|t[eé]cnica|priorizar|organizar (mi|el) (tiempo|estudio)|"
    r"por d[oó]nde (empiezo|parto|comienzo)|c[oó]mo me organiz)", re.I)
def _es_meta_estudio(pregunta: str) -> bool:
    return bool(_META_ESTUDIO_RE.search(pregunta or ""))
_FALLBACK_ESTUDIO = (
    "¡Con gusto! Un buen plan es: 1) divide el temario por unidades y prioriza según la ponderación de "
    "cada evaluación; 2) estudia con la bibliografía obligatoria y practica con casos o ejercicios; y "
    "3) haz repaso espaciado y autoevaluación (explícate el tema en voz alta). ¿Por qué unidad o tema "
    "quieres partir? Te armo un plan más específico."
)


def _clasificar_y_responder(a: SilaboAgente, pregunta: str, intentos: int = 0):
    """Runi, copiloto de APRENDIZAJE. DOS ámbitos: (1) APRENDIZAJE en general → LIBRE, usa el conocimiento
    de la IA como apoyo estratégico para cerrar brechas, anclado al programa y sin contradecir al profesor;
    (2) PARÁMETROS de la asignatura (fechas/ponderaciones/reglas/alcance/ventana) → ESTRICTO: solo el corpus,
    nunca inventar ni contradecir. Clasifica cada consulta (tipo, tema/RA, fuente) para la trazabilidad del
    profesor. Devuelve (tipo, respuesta, categoria, urgencia, necesita_docente, cita, tema, fuente)."""
    import os
    curso = a.nombre_curso or "el curso"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if _es_meta_estudio(pregunta):
            return ("conceptual", _FALLBACK_ESTUDIO, "contenido", "baja", False, None, "estrategia de estudio", "general")
        return ("fuera_corpus", "Tu consulta necesita a tu docente; se la llevé y verás aquí su respuesta.",
                "otro", "media", True, None, None, "ninguna")
    # Modo pedagógico (config del docente): guiado | mixto | directo | cerrado.
    modo = str((a.config or {}).get("modo_pedagogico") or "directo").lower()
    if modo not in ("guiado", "mixto", "directo", "cerrado"):
        modo = "directo"
    # Regla de rendición: si el estudiante ya intentó ≥2 veces algo equivalente, se responde DIRECTO.
    rendido = intentos >= 2
    modo_efectivo = "directo" if (rendido and modo in ("guiado", "mixto")) else modo
    politica_modo = {
        "guiado": "Solo para contenido EVALUABLE cercano a una prueba: NO des la respuesta completa; da UNA pista mínima y devuelve la pregunta. El aprendizaje general (conceptos, técnicas, temas del ámbito) respóndelo normal.",
        "mixto": "En contenido evaluable cercano a una prueba: primero una pista; si insiste o se frustra, resuelve completo. El aprendizaje general respóndelo normal.",
        "directo": "Responde completo, claro y con razonamiento.",
        "cerrado": "VENTANA DE EVALUACIÓN ABIERTA: responde SOLO parámetros/logística (fechas, salas, reglas). NO resuelvas contenido evaluable; ofrece ayudar a estudiar después.",
    }[modo_efectivo]
    rendicion = (" El estudiante ya insistió; ENTREGA la respuesta completa con el razonamiento (regla de rendición)."
                 if rendido else " Si muestra frustración clara, entrega la respuesta completa.")
    try:
        from app.services import correccion_experta_service as ce
        system = (
            f"Eres Runi, copiloto de APRENDIZAJE del curso {curso}. Tu misión es ayudar a APRENDER en todo el "
            "ámbito de la asignatura y su aprendizaje. Tienes DOS ámbitos con reglas DISTINTAS:\n"
            "  (1) PARÁMETROS DE LA ASIGNATURA — fechas, plazos, ponderaciones, reglas, salas, requisitos, alcance "
            "del temario y ventana de evaluación. Aquí eres ESTRICTO: usa SOLO el CONTEXTO DEL CURSO; JAMÁS inventes "
            "ni estimes un parámetro que no esté escrito, y NO contradigas el material del profesor. Si un parámetro "
            "no está en el contexto, dilo con honestidad y márcalo para el docente (fuera_corpus).\n"
            "  (2) APRENDIZAJE EN GENERAL — explicar conceptos, resolver dudas de contenido, dar contexto, técnicas "
            "de estudio, temas relacionados del ámbito. Aquí tienes LIBERTAD para responder con TU CONOCIMIENTO como "
            "apoyo estratégico para cerrar brechas: claro, riguroso y propositivo, ANCLADO al programa del curso y "
            "SIN CONTRADECIR el material del profesor. Esto NO necesita al docente.\n"
            "LÍMITES que SIEMPRE se respetan:\n"
            "- NO entregues respuestas de una evaluación EN CURSO (extraccion): ofrece ayudar a estudiar el tema.\n"
            f"- MODO PEDAGÓGICO = {modo_efectivo}. {politica_modo}{rendicion}\n"
            "- Nota, recorrección o reclamo (evaluativa) → NO respondas; necesita_docente=true.\n"
            "- Salud/afectivo (personal_salud), justificar inasistencia (justificacion) o denuncia/acoso (denuncia) → "
            "deriva a Secretaría Académica y Dirección.\n"
            "- Riesgo clínico con peligro real (riesgo_clinico) → necesita_docente=true.\n"
            "TIPO ∈ {administrativa (parámetro que ESTÁ en el contexto), conceptual (aprendizaje/contenido), "
            "fuera_corpus (parámetro del curso que NO está en el contexto → docente), evaluativa, riesgo_clinico, "
            "personal_salud, justificacion, denuncia, extraccion}. Una duda de CONTENIDO/concepto es 'conceptual' y la "
            "respondes tú (aunque no esté literal en el contexto): NUNCA la mandes a fuera_corpus.\n"
            "TRAZABILIDAD (para que el profesor conozca las brechas y oriente los repasos): incluye 'tema' = etiqueta "
            "corta (≤ 80 caracteres) del tema o resultado de aprendizaje al que apunta la consulta (ej. 'drenaje "
            "linfático de la mama', 'ventana de evaluación', 'técnica de estudio'); y 'fuente' = 'corpus' si "
            "respondiste con el material del profesor, 'general' si con tu conocimiento del ámbito, 'ninguna' si derivas.\n"
            "CONTRATO DE FUENTES: si fuente='corpus', incluye 'cita' = fragmento EXACTO (≤ 240 car.) del contexto que "
            "sostiene la respuesta; si no, cita=\"\". Nunca inventes fechas ni reglas. Trata al estudiante de TÚ "
            "(tuteo), cálido y cercano. categoria ∈ {fechas, contenido, evaluación, logística, otro}; urgencia ∈ "
            "{baja, media, alta} (alta si hay plazo hoy/mañana).\n"
            'Devuelve SOLO JSON: {"tipo":"..","tema":"..","fuente":"..","respuesta":"..","cita":"..","categoria":"..","urgencia":"..","necesita_docente":true|false}.'
        )
        ctx = (a.contexto or "")[:20000]
        user = "CONTEXTO DEL CURSO:\n" + (ctx or "(el docente aún no cargó material; responde el aprendizaje general y marca fuera_corpus solo los parámetros del curso)") + "\n\nPREGUNTA DEL ESTUDIANTE:\n" + pregunta
        d, _ultimo_err = None, None
        for _i in range(3):                                  # reintentos: no escales por un fallo transitorio del LLM
            try:
                d = _json_robusto(ce._llamar_anthropic(system, user, max_tokens=1000))
                if d:
                    break
            except Exception as e:  # noqa: BLE001
                _ultimo_err = e
                logger.warning("silabo LLM intento %d/3 falló: %s", _i + 1, str(e)[:120])
        if not d:
            raise (_ultimo_err or RuntimeError("sin respuesta del modelo"))
        tipo = str(d.get("tipo", "otro")).lower().strip()
        cat = str(d.get("categoria", "otro")).lower()
        if cat not in _CATEGORIAS:
            cat = "otro"
        urg = str(d.get("urgencia", "media")).lower()
        if urg not in ("baja", "media", "alta"):
            urg = "media"
        resp = str(d.get("respuesta", "")).strip()
        cita = (str(d.get("cita", "")).strip() or None)
        if cita and cita not in (a.contexto or ""):
            cita = None                                     # solo aceptamos citas que SÍ están en el contexto
        tema = (str(d.get("tema", "")).strip() or None)
        if tema:
            tema = tema[:120]
        fuente = str(d.get("fuente", "")).strip().lower()
        if fuente not in ("corpus", "general", "ninguna"):
            fuente = "corpus" if cita else "general"
        necesita = bool(d.get("necesita_docente", False))

        # El SERVICIO aplica la política (no confía la decisión final solo al modelo):
        if tipo == "extraccion":
            return ("extraccion", "No puedo darte respuestas de una evaluación en curso. Pero con gusto te ayudo "
                    "a estudiar el tema si quieres.", "evaluación", "media", False, None, tema, "ninguna")
        if tipo in _TIPOS_DERIVACION:
            return (tipo, _derivacion_texto(a), "logística", "alta", False, None, tema, "ninguna")
        if tipo in _TIPOS_A_DOCENTE:
            if not resp:
                resp = ("Esto necesita a tu docente; se lo llevé y verás aquí su respuesta.")
            return (tipo, resp, cat, urg, True, None, tema, "ninguna")
        # administrativa / conceptual / otro: Runi responde
        return (tipo or "conceptual", resp or "Déjame reintentar; reformula tu pregunta con un poco más de detalle.",
                cat, urg, necesita, cita, tema, fuente)
    except Exception as e:  # noqa: BLE001
        logger.warning("silabo _clasificar_y_responder falló: %s", str(e)[:150])
        # Fallback INTELIGENTE: meta-estudio se responde igual (nunca se escala por un fallo del modelo);
        # solo lo genuinamente no resoluble cae al docente.
        if _es_meta_estudio(pregunta):
            return ("conceptual", _FALLBACK_ESTUDIO, "contenido", "baja", False, None, "estrategia de estudio", "general")
        return ("fuera_corpus", "No pude resolver tu duda ahora mismo; reintento y, si sigue, la lleva tu docente. "
                "Mientras tanto, ¿puedes reformularla o darme un poco más de detalle?",
                "otro", "media", False, None, None, "ninguna")


def mis_consultas(db: Session, codigo: str, device_id: str) -> dict:
    """El estudiante ve SUS consultas con estado, reloj y la respuesta del docente cuando llega."""
    a = agente_por_codigo(db, codigo)
    if not device_id:
        return {"nombre_curso": a.nombre_curso, "consultas": []}
    q = (db.query(MensajeSilabo)
         .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.device_id == str(device_id))
         .order_by(MensajeSilabo.created_at.desc()).limit(60).all())
    ahora = _ahora()
    out = []
    for m in q:
        restante = None
        if m.estado == MSG_PENDIENTE and m.vence_ts:
            restante = max(0, int(m.vence_ts) - ahora)
        out.append({"id": str(m.id), "pregunta": m.pregunta, "respuesta_ia": m.respuesta_ia,
                    "respuesta_docente": m.respuesta_docente, "estado": m.estado, "tipo": m.tipo,
                    "cita": getattr(m, "cita", None),
                    "respondido_por": getattr(m, "respondido_por", None),
                    "necesita_docente": m.necesita_docente, "segundos_restantes": restante,
                    "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None})
    return {"nombre_curso": a.nombre_curso, "consultas": out}


# ── bandeja (docente) ────────────────────────────────────────────────────────────────
def _derivada_dict(m: MensajeSilabo) -> dict:
    """Registro de trazabilidad de una derivación institucional. Muestra el HECHO (tipo + fecha),
    pero el CONTENIDO queda RESERVADO para salud y denuncia (Ley 21.719 · minimización; la denuncia
    puede ser sobre el propio docente → canal institucional separado). Justificación sí se muestra."""
    reservado = getattr(m, "tipo", None) in ("personal_salud", "denuncia")
    return {"id": str(m.id), "tipo": getattr(m, "tipo", None), "alias": m.alias,
            "contenido": (None if reservado else m.pregunta), "reservado": reservado,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}


def bandeja(db: Session, course_id, solo_pendientes: bool = False) -> dict:
    a = agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "mensajes": [], "conteos": {}, "derivadas": [], "derivadas_conteo": {}}
    _escalar_vencidos(db, a)                             # nivel-2 vencidos suben solos al profesor
    q = db.query(MensajeSilabo).filter(MensajeSilabo.agente_id == a.id)
    msgs = q.order_by(MensajeSilabo.created_at.desc()).limit(400).all()
    conteos = {"total": 0, "pendientes": 0, "por_categoria": {}, "con_ayudante": 0}
    salida, derivadas, der_conteo = [], [], {}
    for m in msgs:
        if getattr(m, "tipo", None) in _TIPOS_DERIVACION:
            derivadas.append(_derivada_dict(m))
            der_conteo[m.tipo] = der_conteo.get(m.tipo, 0) + 1
            continue                                    # no entran a la bandeja normal
        conteos["total"] += 1
        if m.estado == MSG_PENDIENTE:
            conteos["pendientes"] += 1
            if getattr(m, "nivel", 3) == 2:
                conteos["con_ayudante"] += 1
        conteos["por_categoria"][m.categoria or "otro"] = conteos["por_categoria"].get(m.categoria or "otro", 0) + 1
        if solo_pendientes and m.estado != MSG_PENDIENTE:
            continue
        salida.append(_msg_dict(m))
    # Agrupar equivalentes ENTRE LOS PENDIENTES: se muestra un representante por grupo con el nº de
    # equivalentes (para "un clic responde a los N"). Los ya resueltos/respondidos pasan sin agrupar.
    pend = [d for d in salida if d["estado"] == MSG_PENDIENTE]
    otros = [d for d in salida if d["estado"] != MSG_PENDIENTE]
    reps, usados = [], set()
    for d in pend:
        if d["id"] in usados:
            continue
        t = _tokens(d["pregunta"])
        grupo = [d]
        for e in pend:
            if e["id"] != d["id"] and e["id"] not in usados and _es_equivalente(t, e["pregunta"]):
                grupo.append(e); usados.add(e["id"])
        usados.add(d["id"])
        d["equivalentes"] = len(grupo)
        d["equivalentes_alias"] = [g.get("alias") for g in grupo if g.get("alias")]
        reps.append(d)
    return {"agente": _agente_dict(a), "mensajes": reps + otros, "conteos": conteos,
            "derivadas": derivadas, "derivadas_conteo": der_conteo}


def responder_docente(db: Session, mensaje_id, respuesta: str, quien: str = "docente") -> dict:
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    resp = (respuesta or "").strip()
    m.respuesta_docente = resp
    m.estado = MSG_RESUELTA
    m.respondido_por = quien
    # "Un clic responde a los N": aplica la MISMA respuesta a todos los pendientes equivalentes.
    t = _tokens(m.pregunta)
    n = 1
    if t:
        otros = (db.query(MensajeSilabo)
                 .filter(MensajeSilabo.agente_id == m.agente_id, MensajeSilabo.estado == MSG_PENDIENTE,
                         MensajeSilabo.id != m.id).limit(400).all())
        for o in otros:
            if _es_equivalente(t, o.pregunta):
                o.respuesta_docente = resp
                o.estado = MSG_RESUELTA
                o.respondido_por = quien
                n += 1
    db.commit(); db.refresh(m)
    d = _msg_dict(m); d["respondidos"] = n
    return d


def subir_al_profesor(db: Session, mensaje_id, motivo: str) -> dict:
    """El ayudante sube una consulta al profesor (nivel 2 → 3) con un motivo obligatorio."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise conflict("Indique en una línea por qué la sube al profesor.")
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    m.nivel = 3
    m.motivo_escalamiento = motivo[:255]
    m.vence_ts = _ahora() + _PLAZO_DOCENTE_H * 3600
    db.commit(); db.refresh(m)
    return _msg_dict(m)


def tablero_ayudante(db: Session, codigo: str) -> dict:
    """Cola del ayudante (nivel 2): pendientes agrupados. Sube solos los vencidos antes de listar."""
    a = agente_por_ayudante_codigo(db, codigo)
    if not a.ayudante_activo:
        raise conflict("El tablero de ayudante no está activo.")
    _escalar_vencidos(db, a)
    pend = (db.query(MensajeSilabo)
            .filter(MensajeSilabo.agente_id == a.id, MensajeSilabo.estado == MSG_PENDIENTE,
                    MensajeSilabo.nivel == 2)
            .order_by(MensajeSilabo.created_at.asc()).limit(200).all())
    dicts = [_msg_dict(m) for m in pend]
    # agrupa equivalentes (mismo "1 clic responde a los N")
    reps, usados = [], set()
    for d in dicts:
        if d["id"] in usados:
            continue
        t = _tokens(d["pregunta"])
        n = 1
        for e in dicts:
            if e["id"] != d["id"] and e["id"] not in usados and _es_equivalente(t, e["pregunta"]):
                n += 1; usados.add(e["id"])
        usados.add(d["id"]); d["equivalentes"] = n
        reps.append(d)
    return {"nombre_curso": a.nombre_curso, "consultas": reps}


_FAQ_HEADER = "# Preguntas ya resueltas por el docente (fuente canónica)"


def agregar_al_contexto(db: Session, mensaje_id) -> dict:
    """El corpus crece por uso: promueve una consulta ya respondida a FUENTE del contexto, para que
    la IA responda futuras preguntas parecidas por sí sola (y las cite). Cerrar el círculo (doc #11)."""
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    a = db.query(SilaboAgente).filter(SilaboAgente.id == m.agente_id).first()
    if not a:
        raise not_found("Agente no encontrado.")
    resp = (m.respuesta_docente or m.respuesta_ia or "").strip()
    preg = (m.pregunta or "").strip()
    if not resp or not preg:
        raise conflict("La consulta aún no tiene respuesta para agregar.")
    ctx = a.contexto or ""
    if preg and preg in ctx:
        return {"ok": True, "ya": True}                     # ya estaba
    if _FAQ_HEADER not in ctx:
        ctx = ctx.rstrip() + "\n\n" + _FAQ_HEADER + "\n"
    a.contexto = ctx.rstrip() + "\n\nP: " + preg + "\nR: " + resp
    db.commit(); db.refresh(a)
    return {"ok": True, "agregado": True}


def marcar_estado(db: Session, mensaje_id, estado: str) -> dict:
    if estado not in (MSG_RESPONDIDA, MSG_PENDIENTE, MSG_RESUELTA):
        raise conflict("Estado no válido.")
    m = db.query(MensajeSilabo).filter(MensajeSilabo.id == _uuid(mensaje_id)).first()
    if not m:
        raise not_found("Mensaje no encontrado.")
    m.estado = estado
    db.commit(); db.refresh(m)
    return _msg_dict(m)


# ── serialización ────────────────────────────────────────────────────────────────────
def _uuid(x):
    import uuid as _u
    try:
        return x if isinstance(x, _u.UUID) else _u.UUID(str(x))
    except (ValueError, TypeError):
        raise not_found("Identificador no válido.")


def _agente_dict(a: SilaboAgente) -> dict:
    return {"id": str(a.id), "codigo": a.codigo, "activo": a.activo,
            "nombre_curso": a.nombre_curso, "tiene_contexto": bool((a.contexto or "").strip()),
            "contexto": a.contexto or "", "config": a.config or {},
            "ayudante_activo": bool(getattr(a, "ayudante_activo", False)),
            "ayudante_codigo": getattr(a, "ayudante_codigo", None)}


def _msg_dict(m: MensajeSilabo) -> dict:
    restante = None
    if m.estado == MSG_PENDIENTE and getattr(m, "vence_ts", None):
        restante = int(m.vence_ts) - _ahora()
    return {"id": str(m.id), "alias": m.alias, "pregunta": m.pregunta,
            "respuesta_ia": m.respuesta_ia, "tipo": getattr(m, "tipo", None),
            "cita": getattr(m, "cita", None), "tema": getattr(m, "tema", None), "fuente": getattr(m, "fuente", None),
            "categoria": m.categoria, "urgencia": m.urgencia,
            "estado": m.estado, "necesita_docente": m.necesita_docente,
            "nivel": getattr(m, "nivel", 3), "respondido_por": getattr(m, "respondido_por", None),
            "motivo_escalamiento": getattr(m, "motivo_escalamiento", None),
            "respuesta_docente": m.respuesta_docente, "segundos_restantes": restante,
            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}
