"""
Motor del modo EN VIVO. Corrige cada respuesta al vuelo contra la pauta (AnswerKey) y,
al cerrar, entrega la matriz binaria participante x item que alimenta la MISMA psicometria
del resto de la plataforma. Sincronizacion por polling (GET estado); WebSockets es una
optimizacion posterior, no cambia el contrato.
"""
from __future__ import annotations

import secrets
import uuid

from app.core.errors import conflict, not_found
from app.models.answer_key import AnswerKey, QUESTION_TYPE_MULTIPLE_CHOICE
from app.models.en_vivo import (
    SesionEnVivo, ParticipanteVivo, RespuestaVivo,
    ESTADO_LOBBY, ESTADO_ACTIVA, ESTADO_PAUSADA, ESTADO_CERRADA,
)
from app.models.scan import Scan

# Prefijo del identificador de los escaneos generados por el modo en vivo. Permite
# reconocerlos (origen trazable) y hace idempotente el cierre (no se duplican).
_SCAN_PREFIX = "envivo:"

# Alfabeto sin caracteres ambiguos (0/O, 1/I) para dictar el codigo en voz alta.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generar_codigo(db, largo: int = 6) -> str:
    for _ in range(30):
        cod = "".join(secrets.choice(_ALFABETO) for _ in range(largo))
        if not db.query(SesionEnVivo).filter(SesionEnVivo.codigo == cod).first():
            return cod
    raise conflict("No se pudo generar un codigo de sala unico.")


def _sesion(db, codigo: str) -> SesionEnVivo:
    s = db.query(SesionEnVivo).filter(SesionEnVivo.codigo == str(codigo).upper()).first()
    if not s:
        raise not_found("Sesion en vivo no encontrada.")
    return s


def _items_mc(db, assessment_id, version: str) -> list:
    """Items de alternativas de la version, ordenados por numero de pregunta.

    El modo en vivo solo corre preguntas de seleccion multiple (las de desarrollo
    necesitan validacion docente y no se auto-corrigen al vuelo).
    """
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak or not ak.is_valid:
        raise conflict("La pauta no esta validada; no se puede iniciar el modo en vivo.")
    items = [it for it in ak.items
             if it.version.upper() == version.upper() and not it.is_annulled
             and it.question_type == QUESTION_TYPE_MULTIPLE_CHOICE]
    items.sort(key=lambda it: it.question_number)
    return items


# ── ciclo de vida (docente) ──────────────────────────────────────────────────────────
def crear_sesion(db, assessment_id, version: str = "A") -> SesionEnVivo:
    items = _items_mc(db, assessment_id, version)
    if not items:
        raise conflict("La evaluacion no tiene preguntas de alternativas para el modo en vivo.")
    s = SesionEnVivo(assessment_id=str(assessment_id), codigo=_generar_codigo(db),
                     estado=ESTADO_LOBBY, pregunta_actual=0, n_preguntas=len(items),
                     version=version.upper())
    db.add(s); db.commit(); db.refresh(s)
    return s


def avanzar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_CERRADA:
        raise conflict("La sesion ya esta cerrada.")
    cierra = s.pregunta_actual >= s.n_preguntas
    if cierra:
        s.estado = ESTADO_CERRADA                 # se acabaron las preguntas -> cierra
    else:
        s.pregunta_actual += 1
        s.estado = ESTADO_ACTIVA
    db.commit(); db.refresh(s)
    if cierra:
        _persistir_scans(db, s)                   # auto-cierre también alimenta la psicometría
    return s


def pausar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_ACTIVA:
        s.estado = ESTADO_PAUSADA
        db.commit(); db.refresh(s)
    return s


def reanudar(db, codigo: str) -> SesionEnVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_PAUSADA:
        s.estado = ESTADO_ACTIVA
        db.commit(); db.refresh(s)
    return s


def cerrar(db, codigo: str) -> dict:
    """Cierra la sala y VUELCA las respuestas a escaneos (Scan) del mismo assessment.

    Así el modo en vivo deja de ser un silo: los mismos motores psicométricos del módulo
    Profesor/Investigador (que leen `Scan.raw_ocr_payload_json`) ven esta evidencia. No
    escribe notas ni Result (gobernanza G1: en vivo no altera calificaciones); solo aporta
    la matriz de correctitud. Idempotente: si ya se persistió, no duplica.
    """
    s = _sesion(db, codigo)
    s.estado = ESTADO_CERRADA
    db.commit(); db.refresh(s)
    n = _persistir_scans(db, s)
    return {"codigo": s.codigo, "estado": s.estado, "pregunta_actual": s.pregunta_actual,
            "n_preguntas": s.n_preguntas, "scans_incorporados": n}


def _persistir_scans(db, s: SesionEnVivo) -> int:
    """Convierte cada participante que respondió en un Scan (answers por nº de pregunta real).

    Devuelve cuántos escaneos se crearon (0 si ya existían = idempotente, o si nadie jugó).
    """
    ya = db.query(Scan).filter(
        Scan.assessment_id == uuid.UUID(s.assessment_id),
        Scan.student_identifier.like(_SCAN_PREFIX + s.codigo + ":%")).first()
    if ya:
        return 0  # ya se volcó este cierre; no duplicar

    items = _items_mc(db, uuid.UUID(s.assessment_id), s.version)
    if not items:
        return 0
    # ordinal (1..N en vivo) -> nº de pregunta real de la pauta
    ordinal_a_real = {i: it.question_number for i, it in enumerate(items, start=1)}
    max_q = max(ordinal_a_real.values())

    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()
    por_part: dict[uuid.UUID, dict[int, str]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = r.respuesta

    creados = 0
    for p in parts:
        elecciones = por_part.get(p.id)
        if not elecciones:
            continue  # participante que no respondió nada: no aporta fila
        answers: list = [None] * max_q
        for ordinal, letra in elecciones.items():
            real = ordinal_a_real.get(ordinal)
            if real:
                answers[real - 1] = letra
        db.add(Scan(
            assessment_id=uuid.UUID(s.assessment_id),
            student_identifier=(_SCAN_PREFIX + s.codigo + ":" + str(p.id)[:8])[:100],
            status="en_vivo", detected_version=s.version, requires_review=False,
            raw_ocr_payload_json={"answers": answers, "origen": "en_vivo",
                                  "sesion": s.codigo, "alias": p.alias},
        ))
        creados += 1
    db.commit()
    return creados


# ── participantes ────────────────────────────────────────────────────────────────────
def unir(db, codigo: str, alias: str, student_id: str | None = None) -> ParticipanteVivo:
    s = _sesion(db, codigo)
    if s.estado == ESTADO_CERRADA:
        raise conflict("La sesion ya esta cerrada; no admite mas participantes.")
    alias = (alias or "").strip()[:80] or "Anonimo"
    p = ParticipanteVivo(sesion_id=s.id, alias=alias,
                         student_id=str(student_id) if student_id else None,
                         token=secrets.token_urlsafe(24))
    db.add(p); db.commit(); db.refresh(p)
    return p


def responder(db, codigo: str, participante_id, token: str, respuesta: str) -> dict:
    s = _sesion(db, codigo)
    if s.estado != ESTADO_ACTIVA:
        raise conflict("La sesion no esta recibiendo respuestas en este momento.")
    try:
        pid = uuid.UUID(str(participante_id))
    except ValueError:
        raise not_found("Participante no valido.")
    p = db.query(ParticipanteVivo).filter(
        ParticipanteVivo.id == pid, ParticipanteVivo.sesion_id == s.id).first()
    if not p or p.token != token:
        raise not_found("Participante no valido para esta sesion.")

    qn = s.pregunta_actual
    items = _items_mc(db, uuid.UUID(s.assessment_id), s.version)
    if not (1 <= qn <= len(items)):
        raise conflict("No hay una pregunta activa.")
    item = items[qn - 1]

    if db.query(RespuestaVivo).filter(
            RespuestaVivo.participante_id == p.id,
            RespuestaVivo.question_number == qn).first():
        raise conflict("Ya respondiste esta pregunta.")

    elegida = str(respuesta or "").strip().upper()[:10]
    correcta = elegida == str(item.correct_answer).strip().upper()
    db.add(RespuestaVivo(sesion_id=s.id, participante_id=p.id, question_number=qn,
                         respuesta=elegida, correcta=correcta))
    db.commit()
    return {"question_number": qn, "respuesta": elegida, "correcta": correcta}


# ── lecturas (polling) ───────────────────────────────────────────────────────────────
def estado(db, codigo: str) -> dict:
    s = _sesion(db, codigo)
    n_part = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).count()
    n_resp = (db.query(RespuestaVivo).filter(
        RespuestaVivo.sesion_id == s.id,
        RespuestaVivo.question_number == s.pregunta_actual).count()
        if s.pregunta_actual else 0)
    return {"codigo": s.codigo, "estado": s.estado, "pregunta_actual": s.pregunta_actual,
            "n_preguntas": s.n_preguntas, "n_participantes": n_part,
            "respuestas_pregunta_actual": n_resp}


def resultados(db, codigo: str) -> dict:
    s = _sesion(db, codigo)
    items = _items_mc(db, uuid.UUID(s.assessment_id), s.version)
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()

    por_pregunta = []
    for i, item in enumerate(items, start=1):
        rs = [r for r in resp if r.question_number == i]
        dist: dict[str, int] = {}
        for r in rs:
            dist[r.respuesta] = dist.get(r.respuesta, 0) + 1
        n = len(rs)
        n_ok = sum(1 for r in rs if r.correcta)
        por_pregunta.append({
            "pregunta": i, "correcta": item.correct_answer,
            "n_respuestas": n, "n_correctas": n_ok,
            "pct_correcta": round(n_ok / n * 100, 1) if n else 0.0,
            "distribucion": dist,
        })

    ranking = []
    for p in parts:
        rs = [r for r in resp if r.participante_id == p.id]
        aciertos = sum(1 for r in rs if r.correcta)
        ranking.append({"participante": p.alias, "aciertos": aciertos,
                        "respondidas": len(rs)})
    ranking.sort(key=lambda x: (-x["aciertos"], x["respondidas"]))

    return {"codigo": s.codigo, "estado": s.estado, "n_participantes": len(parts),
            "n_preguntas": s.n_preguntas, "por_pregunta": por_pregunta, "ranking": ranking}


def matriz_binaria(db, codigo: str) -> dict:
    """Matriz participante x item (0/1) para alimentar la psicometria (Rasch, KR-20...).

    El modo en vivo entra a los mismos motores del modulo Investigador sin persistir
    escaneos: es otra fuente de la misma evidencia.
    """
    s = _sesion(db, codigo)
    n = s.n_preguntas
    parts = db.query(ParticipanteVivo).filter(ParticipanteVivo.sesion_id == s.id).all()
    resp = db.query(RespuestaVivo).filter(RespuestaVivo.sesion_id == s.id).all()
    por_part: dict[uuid.UUID, dict[int, int]] = {}
    for r in resp:
        por_part.setdefault(r.participante_id, {})[r.question_number] = 1 if r.correcta else 0

    filas, aliases = [], []
    for p in parts:
        celdas = por_part.get(p.id, {})
        filas.append([celdas.get(i, 0) for i in range(1, n + 1)])
        aliases.append(p.alias)
    return {"codigo": s.codigo, "participantes": aliases,
            "items": list(range(1, n + 1)), "matriz": filas}


def join_url(codigo: str, base: str | None = None) -> str:
    """Enlace de unión que codifica el QR. Absoluto si hay base (ideal para escanear con
    el teléfono); relativo si no, para que el frontend lo complete con su propio origen."""
    ruta = "/app.html?sala=" + str(codigo).upper()
    b = (base or "").strip().rstrip("/")
    return (b + ruta) if b else ruta


def qr_data_url(payload: str) -> str | None:
    """PNG en base64 (data URL) para el QR de union. None si la libreria no esta."""
    try:
        import base64
        import io
        import qrcode
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None
