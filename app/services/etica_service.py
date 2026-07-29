"""Motor de ética ejecutable de Runi (Protocolo · runi-reglas-eticas.yaml).

Tres piezas sobre la bitácora encadenada que ya existe (silabo_service):

  1. ESCALA DE CONSECUENCIAS 0–5 — clasifica cada interacción por su consecuencia potencial. A mayor
     nivel, más estricto el trato (deriva, reserva contenido, prioriza). Hace explícito el juicio.
  2. PUERTA 3 · verificación de SALIDA — antes de entregar, revisa la respuesta ya generada con reglas
     deterministas (no otra llamada al modelo): que la cita exista de verdad en el contexto, que no se
     declare 'sólida' sin respaldo, que no se fabriquen parámetros del curso. Puede DETENER (parada segura).
  3. INFORME A COMITÉ — exporta la trazabilidad agregada (sin datos personales, Ley 21.719) para que un
     comité de ética la audite: distribución de consecuencias, derivaciones, paradas, integridad de la cadena.

etica_service NO importa silabo_service (para evitar ciclos): silabo_service importa esto.
"""
from __future__ import annotations

import re

# ── Escala de consecuencias 0–5 (juicio ético explícito y trazable) ───────────────────
ESCALA_CONSECUENCIAS = {
    0: {"clave": "ninguna", "etiqueta": "Sin consecuencia",
        "descripcion": "Aprendizaje general con respaldo; no hay riesgo ni decisión pendiente.",
        "trato": "Runi responde con normalidad."},
    1: {"clave": "minima", "etiqueta": "Mínima",
        "descripcion": "Orientación conceptual con certeza limitada; conviene contrastarla.",
        "trato": "Runi responde y señala que es orientación general."},
    2: {"clave": "baja", "etiqueta": "Baja",
        "descripcion": "Parámetro del curso no disponible en el material; se deriva sin daño.",
        "trato": "Se marca para el docente; no se inventa el dato."},
    3: {"clave": "media", "etiqueta": "Media",
        "descripcion": "Decisión académica (nota, justificación, excepción) que corresponde al docente.",
        "trato": "No la resuelve la IA; la decide y confirma el docente."},
    4: {"clave": "alta", "etiqueta": "Alta",
        "descripcion": "Situación personal/salud o dato sensible; contenido reservado (Ley 21.719).",
        "trato": "Deriva a Secretaría Académica y Dirección; contenido reservado."},
    5: {"clave": "grave", "etiqueta": "Grave",
        "descripcion": "Riesgo clínico con posible daño real o denuncia; prioridad y canal institucional.",
        "trato": "Prioridad máxima; canal institucional separado; acompañamiento."},
}

# tipo de intención (taxonomía de silabo) → nivel base de consecuencia.
_CONSEC_POR_TIPO = {
    "riesgo_clinico": 5, "denuncia": 5,
    "personal_salud": 4,
    "justificacion": 3, "evaluativa": 3, "solicitud_humana": 3,
    "fuera_corpus": 2, "extraccion": 2,
    "administrativa": 1, "otro": 1,
    "conceptual": 0,
}


def clasificar_consecuencia(tipo: str, fuente: str | None, necesita: bool, certeza: str | None) -> int:
    """Devuelve el nivel 0–5. Parte del tipo y sube si la certeza es floja o si se deriva."""
    nivel = _CONSEC_POR_TIPO.get((tipo or "").lower(), 1)
    if nivel <= 1:
        if (certeza or "") in ("insuficiente",):
            nivel = max(nivel, 1)
        elif (certeza or "") in ("preliminar",):
            nivel = max(nivel, 1)
    # Si algo se deriva al docente pero quedó clasificado como bajo, es al menos consecuencia media 2.
    if necesita and nivel < 2:
        nivel = 2
    return max(0, min(5, nivel))


def consecuencia_dict(nivel: int) -> dict:
    n = max(0, min(5, int(nivel)))
    return {"nivel": n, **ESCALA_CONSECUENCIAS[n]}


# ── Puerta 3 · verificación de salida (determinista) ──────────────────────────────────
# Patrón de "parámetro duro" (fecha/hora/porcentaje/sala): lo que Runi NUNCA debe afirmar de su
# conocimiento propio (fuente 'general'); solo puede venir del material del profesor (fuente 'corpus').
_PARAM_RE = re.compile(
    r"\b(\d{1,2}\s*(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
    r"octubre|noviembre|diciembre))\b|\b\d{1,2}[:h]\d{2}\b|\b\d{1,3}\s?%|\bsala\s+[A-Z0-9-]{1,6}\b",
    re.I)


def puerta3_verificar(respuesta: str, contexto: str, tipo: str, cita: str | None,
                      fuente: str | None, certeza: str | None, necesita: bool) -> dict:
    """Revisa la SALIDA ya generada. Devuelve {veredicto, observaciones, checks}.
    veredicto ∈ {ok, observado, detenido}. 'detenido' = parada segura (no entregar tal cual)."""
    obs, checks = [], {}
    resp = respuesta or ""
    ctx = contexto or ""

    # 1) Cita real: si dice apoyarse en el corpus, la cita debe existir LITERAL en el contexto.
    if fuente == "corpus":
        ok = bool(cita and cita.strip() and cita.strip() in ctx)
        checks["cita_en_contexto"] = ok
        if not ok:
            obs.append("La respuesta se declara respaldada por el material, pero la cita no aparece "
                       "literal en el contexto (posible fabricación).")
    else:
        checks["cita_en_contexto"] = None

    # 2) Coherencia de certeza: 'sólida' exige respaldo del corpus con cita.
    coh = not (certeza == "solida" and not (fuente == "corpus" and cita))
    checks["certeza_coherente"] = coh
    if not coh:
        obs.append("Se declara certeza 'sólida' sin respaldo del material del curso.")

    # 3) Sin fabricación de parámetros: si NO se apoya en el corpus, no debe afirmar fechas/horas/%/salas.
    if fuente != "corpus" and not necesita:
        fab = _PARAM_RE.search(resp)
        checks["sin_parametro_fabricado"] = not bool(fab)
        if fab:
            obs.append("La respuesta afirma un parámetro del curso (fecha/hora/%/sala) sin respaldo del "
                       "material: «" + fab.group(0) + "».")
    else:
        checks["sin_parametro_fabricado"] = True

    # 4) Respuesta presente para lo que Runi sí debe responder.
    pres = bool(resp.strip()) or necesita
    checks["respuesta_presente"] = pres
    if not pres:
        obs.append("Respuesta vacía para una consulta que Runi debía responder.")

    # Veredicto: se DETIENE SOLO ante fabricación de un PARÁMETRO del curso (fecha/hora/%/sala sin respaldo) —
    # eso es lo que puede engañar al estudiante. Una cita ausente o una certeza incoherente se OBSERVAN
    # (no se detiene una respuesta de aprendizaje válida por eso; la fuente ya se degradó a 'general' aguas arriba).
    detener = (checks.get("sin_parametro_fabricado") is False)
    veredicto = "detenido" if detener else ("observado" if obs else "ok")
    return {"veredicto": veredicto, "observaciones": obs, "checks": checks}


# ── Informe para comité de ética (agregado, sin datos personales) ─────────────────────
def informe_comite(db, course_id) -> dict:
    """Exporta la trazabilidad agregada para auditoría de un comité de ética. No expone texto ni
    identidades: solo conteos, distribución de consecuencias, derivaciones e integridad de la cadena."""
    from app.services import silabo_service as sil          # import local: evita ciclo al cargar el módulo
    from app.models.silabo import RuniBitacora

    a = sil.agente_de_curso(db, course_id)
    if not a:
        return {"agente": None, "total": 0}
    entradas = (db.query(RuniBitacora).filter(RuniBitacora.agente_id == a.id)
                .order_by(RuniBitacora.created_at.asc()).all())
    dist = {str(n): 0 for n in range(6)}
    eventos, puertas = {}, {"ok": 0, "observado": 0, "detenido": 0}
    derivaciones = 0
    primera = ultima = None
    for b in entradas:
        m = b.meta or {}
        c = m.get("consecuencia")
        if isinstance(c, int) and 0 <= c <= 5:
            dist[str(c)] += 1
        ev = b.evento or "consulta"
        eventos[ev] = eventos.get(ev, 0) + 1
        p = m.get("puerta3")
        if p in puertas:
            puertas[p] += 1
        if m.get("decision") == "derivado" or ev == "derivacion":
            derivaciones += 1
        ts = b.created_at.isoformat() if getattr(b, "created_at", None) else None
        if ts:
            primera = primera or ts
            ultima = ts
    return {
        "agente": {"nombre_curso": a.nombre_curso, "codigo": a.codigo},
        "total": len(entradas),
        "ventana": {"desde": primera, "hasta": ultima},
        "consecuencias": {"distribucion": dist, "escala": {str(k): v["etiqueta"] for k, v in ESCALA_CONSECUENCIAS.items()}},
        "eventos": eventos,
        "puerta3": puertas,
        "derivaciones": derivaciones,
        "integridad_cadena": sil.verificar_bitacora(db, a.id),
        "reglas_version": sil.reglas_version(),
        "nota": "Informe agregado y seudonimizado (Ley 21.719): no contiene texto de consultas ni identidades.",
    }
