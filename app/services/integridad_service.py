"""
Integridad del modo EN VIVO (LV8): agrega la telemetría de ventana/foco de cada participante
en EVIDENCIA OBJETIVA para el docente. No decide: el profesor interpreta y, si corresponde,
cierra selectivamente la prueba a un alumno. Nunca invalida una evaluación automáticamente
(proporcionalidad y debido proceso; Ley 21.719).

Señales fiables en web: Page Visibility (pestaña/app oculta), foco, pantalla completa,
copiar/pegar/menú contextual, latido. NO detecta de forma fiable: screenshot del sistema,
foto con otro teléfono, uso de IA en otro dispositivo (eso se maneja con diseño evaluativo
y verificación oral posterior).
"""
from __future__ import annotations

from datetime import datetime, timezone

# Tipos de evento aceptados desde el cliente (lista blanca; lo demás se ignora).
TIPOS_VALIDOS = {
    "page_hidden", "page_visible", "blur", "focus", "fullscreen_enter", "fullscreen_exit",
    "copy", "paste", "cut", "contextmenu", "heartbeat", "join", "sesion_concurrente",
    "ventana_otra_encima", "window_resize", "posible_captura",
}

# Umbrales del semáforo (interpretación sugerida, NO veredicto).
OCULTO_AVISO_MS = 8000       # una ocultación de ≥8 s ya es un aviso
OCULTO_REVISAR_MS = 30000    # ≥30 s acumulados ocultos → marcar para revisión
SALIDAS_REVISAR = 3          # ≥3 salidas de foco → marcar para revisión


def _ahora_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def registrar_eventos(db, s, p, eventos: list) -> dict:
    """Persiste un lote de eventos (inmutables, hora de servidor). Actualiza el último latido."""
    from app.models.en_vivo import EventoIntegridad
    n = 0
    hubo_latido = False
    for e in (eventos or []):
        tipo = str((e or {}).get("tipo", "")).strip()
        if tipo not in TIPOS_VALIDOS:
            continue
        qn = e.get("question_number")
        dur = e.get("duration_ms")
        seq = e.get("sequence")
        meta = e.get("meta") if isinstance(e.get("meta"), dict) else None
        db.add(EventoIntegridad(
            sesion_id=s.id, participante_id=p.id, tipo=tipo,
            question_number=int(qn) if isinstance(qn, (int, float)) else None,
            duration_ms=int(dur) if isinstance(dur, (int, float)) else None,
            sequence=int(seq) if isinstance(seq, (int, float)) else None,
            meta_json=meta))
        n += 1
        if tipo == "heartbeat":
            hubo_latido = True
    # El último latido (o cualquier evento) marca "visto hace X" con hora de servidor.
    if n:
        p.ultimo_latido_ts = _ahora_epoch()
    db.commit()
    return {"registrados": n, "latido": hubo_latido}


def _resumen_de(eventos: list) -> dict:
    """Agrega la lista de eventos de UN participante → contadores + nivel de semáforo."""
    salidas = 0            # nº de veces que la prueba quedó oculta (cambió de pestaña/app)
    oculto_ms = 0          # tiempo total oculto (de los page_hidden con duración)
    oculto_max_ms = 0      # la ausencia más larga
    pegados = 0
    menus = 0
    salio_fs = 0
    concurrentes = 0
    otra_ventana = 0       # blur sin ocultar = otra ventana/app encima (p.ej. ChatGPT al lado)
    reducciones = 0        # ventana reducida (posible pantalla dividida)
    capturas = 0           # posible captura de pantalla (best-effort, no fiable)
    preguntas_ausencia = set()   # nº de pregunta activa cuando se ausentó
    for e in eventos:
        t = e.tipo
        if t == "page_hidden":
            salidas += 1
            if e.duration_ms:
                oculto_ms += e.duration_ms
                oculto_max_ms = max(oculto_max_ms, e.duration_ms)
            if e.question_number:
                preguntas_ausencia.add(int(e.question_number))
        elif t == "paste":
            pegados += 1
        elif t == "contextmenu":
            menus += 1
        elif t == "fullscreen_exit":
            salio_fs += 1
        elif t == "sesion_concurrente":
            concurrentes += 1
        elif t == "ventana_otra_encima":
            otra_ventana += 1
        elif t == "window_resize":
            if (e.meta_json or {}).get("small"):
                reducciones += 1
        elif t == "posible_captura":
            capturas += 1
    # Nivel (evidencia interpretada, no sentencia): ok / aviso / revisar.
    nivel = "ok"
    if salidas or salio_fs or menus or pegados or otra_ventana or reducciones or capturas:
        nivel = "aviso"
    if (oculto_ms >= OCULTO_REVISAR_MS or salidas >= SALIDAS_REVISAR
            or pegados > 0 or concurrentes > 0 or capturas > 0
            or oculto_max_ms >= OCULTO_AVISO_MS):
        nivel = "revisar"
    return {"salidas_foco": salidas, "oculto_ms": oculto_ms,
            "oculto_s": round(oculto_ms / 1000, 1), "oculto_max_s": round(oculto_max_ms / 1000, 1),
            "pegados": pegados, "menus_contextual": menus, "salidas_pantalla_completa": salio_fs,
            "sesiones_concurrentes": concurrentes, "otra_ventana_encima": otra_ventana,
            "ventana_reducida": reducciones, "posibles_capturas": capturas,
            "preguntas_ausencia": sorted(preguntas_ausencia),
            "ultima_pregunta_oculta": (sorted(preguntas_ausencia)[-1] if preguntas_ausencia else None),
            "nivel": nivel}


def resumen_participantes(db, s) -> dict:
    """Panel de supervisión: una fila por participante con contadores y semáforo, ordenado por
    riesgo (revisar → aviso → ok). Sirve para el informe EN VIVO y el FINAL."""
    from app.models.en_vivo import ParticipanteVivo, EventoIntegridad, RespuestaVivo
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    evs = db.query(EventoIntegridad).filter(EventoIntegridad.sesion_id == s.id).all()
    por_part: dict = {}
    for e in evs:
        por_part.setdefault(e.participante_id, []).append(e)
    # Respuestas por participante (para correlacionar la ausencia con la pregunta respondida).
    resp_por_part: dict = {}
    for rv in db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all():
        resp_por_part.setdefault(rv.participante_id, {})[int(rv.question_number)] = bool(rv.correcta)
    ahora = _ahora_epoch()
    orden = {"revisar": 0, "aviso": 1, "ok": 2}
    filas = []
    for p in parts:
        r = _resumen_de(por_part.get(p.id, []))
        sin_latido = (ahora - p.ultimo_latido_ts) if p.ultimo_latido_ts else None
        # Correlación clave: preguntas durante las cuales se ausentó Y respondió (¿acertó al volver?).
        resp = resp_por_part.get(p.id, {})
        respondidas_tras_ausencia = [{"pregunta": q, "correcta": resp[q]}
                                     for q in r["preguntas_ausencia"] if q in resp]
        filas.append({
            "participante_id": str(p.id), "alias": p.alias, "student_id": p.student_id,
            "progreso": p.progreso, "bloqueado": bool(p.bloqueado),
            "bloqueado_motivo": p.bloqueado_motivo,
            "sin_latido_s": sin_latido,
            "conectado": (sin_latido is not None and sin_latido <= 25),
            "respondidas_tras_ausencia": respondidas_tras_ausencia,
            **r,
        })
    filas.sort(key=lambda f: (orden.get(f["nivel"], 3), -(f["oculto_ms"] or 0)))
    return {"codigo": s.codigo, "n": len(filas),
            "n_revisar": sum(1 for f in filas if f["nivel"] == "revisar"),
            "n_aviso": sum(1 for f in filas if f["nivel"] == "aviso"),
            "participantes": filas}


def timeline_participante(db, s, participante_id) -> dict:
    """Línea temporal de incidencias de UN participante (evidencia detallada para decidir)."""
    import uuid as _uuid
    from app.models.en_vivo import ParticipanteVivo, EventoIntegridad
    try:
        pid = _uuid.UUID(str(participante_id))
    except ValueError:
        return {"eventos": []}
    p = db.query(ParticipanteVivo).filter(
        ParticipanteVivo.id == pid, ParticipanteVivo.sesion_id == s.id).first()
    if not p:
        return {"eventos": []}
    evs = (db.query(EventoIntegridad)
           .filter(EventoIntegridad.participante_id == pid)
           .order_by(EventoIntegridad.server_time).all())
    # Solo eventos "de interés" en la línea (el latido se resume aparte).
    interes = {"page_hidden", "page_visible", "blur", "focus", "fullscreen_exit",
               "fullscreen_enter", "paste", "copy", "cut", "contextmenu", "sesion_concurrente"}
    linea = [{
        "tipo": e.tipo, "question_number": e.question_number,
        "duration_ms": e.duration_ms,
        "server_time": e.server_time.isoformat() if e.server_time else None,
    } for e in evs if e.tipo in interes]
    return {"participante_id": str(p.id), "alias": p.alias,
            "resumen": _resumen_de(evs), "eventos": linea}


def bloquear(db, s, participante_id, bloquear_: bool, motivo: str | None = None) -> dict:
    """El docente CIERRA (o reabre) la prueba para un alumno. Decisión humana, registrada."""
    import uuid as _uuid
    from app.models.en_vivo import ParticipanteVivo
    from app.core.errors import not_found
    try:
        pid = _uuid.UUID(str(participante_id))
    except ValueError:
        raise not_found("Participante no válido.")
    p = db.query(ParticipanteVivo).filter(
        ParticipanteVivo.id == pid, ParticipanteVivo.sesion_id == s.id).first()
    if not p:
        raise not_found("Participante no encontrado en esta sesión.")
    p.bloqueado = bool(bloquear_)
    p.bloqueado_motivo = (str(motivo)[:255] if (bloquear_ and motivo) else None)
    db.commit()
    return {"participante_id": str(p.id), "alias": p.alias,
            "bloqueado": p.bloqueado, "motivo": p.bloqueado_motivo}
