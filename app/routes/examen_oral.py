"""
5º módulo · EXAMEN ORAL — router (F1: sesión + segmentos con transcripción literal).

F1 persiste la Capa 2 (transcripción literal por segmento "Respuesta N") y la referencia al
audio local (IndexedDB en el equipo del docente). Las capas 3 (normalización/síntesis) y la
evaluación por 4 criterios llegan en F2–F4. G1: nada se publica sin validación docente.
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor
from app.core.errors import not_found, conflict
from app.models.assessment import Assessment
from app.models.student import Student
from app.models.answer_key import AnswerKey, AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE
from app.models.examen_oral import (
    OralExamSesion, OralExamSegmento, OE_GRABANDO, OE_REVISION, OE_ESTADOS)

logger = logging.getLogger("evalys")
router = APIRouter(prefix="/oral-examen", tags=["examen-oral"])


def _nombre(st) -> str | None:
    return ((getattr(st, "apellido_paterno", "") or "") + " "
            + (getattr(st, "apellido_materno", "") or "") + " "
            + (getattr(st, "nombres", "") or "")).replace("  ", " ").strip() or None


def _preguntas(db, assessment_id) -> list:
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        return []
    items = [it for it in sorted(ak.items, key=lambda x: x.question_number)
             if it.question_type == QUESTION_TYPE_OPEN_RESPONSE]
    return [{"id": str(it.id), "numero": it.question_number, "enunciado": it.enunciado or "",
             "weight": float(it.weight or 1),
             "tiempo_reflexion_seg": getattr(it, "tiempo_reflexion_seg", None),
             "tiempo_max_seg": getattr(it, "tiempo_max_seg", None),
             "respuesta_optima": (it.respuesta_optima or it.correct_answer or ""),
             "conceptos_indispensables": getattr(it, "conceptos_indispensables", None) or "",
             "nivel_rigor": getattr(it, "nivel_rigor", None) or "estricto",
             "area_conocimiento": getattr(it, "area_conocimiento", None) or "general"}
            for it in items]


def _sesion_dict(s, db, incluir_segmentos=False) -> dict:
    st = db.get(Student, s.student_id) if s.student_id else None
    d = {"id": str(s.id), "assessment_id": s.assessment_id, "student_id": s.student_id,
         "rut": (getattr(st, "rut", None) if st else None), "nombre": _nombre(st) if st else None,
         "estado": s.estado, "evaluador": s.evaluador, "duracion_seg": s.duracion_seg,
         "nota_final": s.nota_final, "logro_pct": s.logro_pct,
         "observaciones": (s.config_json or {}).get("observaciones", "") if isinstance(s.config_json, dict) else "",
         "n_segmentos": len(s.segmentos)}
    if incluir_segmentos:
        d["segmentos"] = [{
            "id": str(g.id), "pregunta_numero": g.pregunta_numero,
            "answer_key_item_id": g.answer_key_item_id,
            "t_inicio_ms": g.t_inicio_ms, "t_fin_ms": g.t_fin_ms,
            "transcripcion_literal": g.transcripcion_literal or "",
            "version_normalizada": g.version_normalizada or "",
            "sintesis_json": g.sintesis_json, "confianza": g.confianza,
            "correcciones_json": g.correcciones_json or [],
            "sin_respuesta": g.sin_respuesta,
            "evaluaciones": [{
                "id": str(e.id), "criterio": e.criterio, "peso_criterio": e.peso_criterio,
                "puntaje_ia": e.puntaje_ia, "puntaje_docente": e.puntaje_docente,
                "justificacion": e.justificacion or "",
                "evidencia": (e.evidencia_json or {}).get("evidencia", "") if isinstance(e.evidencia_json, dict) else "",
                "fundamento": (e.evidencia_json or {}).get("fundamento", "") if isinstance(e.evidencia_json, dict) else "",
                "accion": e.accion, "confianza": e.confianza}
                for e in g.evaluaciones]}
            for g in sorted(s.segmentos, key=lambda x: x.pregunta_numero)]
    return d


@router.get("/assessments/{assessment_id}/preguntas", dependencies=[Depends(req_profesor)])
def preguntas_oral(assessment_id: UUID, db: Session = Depends(get_db)):
    """Preguntas de la evaluación oral (reusa AnswerKeyItem open_response) + nómina del curso."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    roster = (db.query(Student).filter(Student.course_id == asm.course_id).all()
              if asm.course_id else [])
    return {"assessment_id": str(assessment_id), "prueba": asm.name,
            "escala": asm.grading_scale or "chile_1_7",
            "exigencia": asm.passing_threshold if asm.passing_threshold is not None else 60.0,
            "preguntas": _preguntas(db, assessment_id),
            "nomina": [{"student_id": str(st.id), "rut": st.rut, "nombre": _nombre(st)}
                       for st in roster]}


def _ak_de(db, assessment_id):
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if not ak:
        ak = AnswerKey(assessment_id=assessment_id, status="draft", is_valid=False)
        db.add(ak); db.flush()
    return ak


@router.post("/assessments/{assessment_id}/preguntas-ia", dependencies=[Depends(req_profesor)])
def preguntas_ia(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Genera preguntas orales con IA (NO persiste; devuelve preview). modo='plantilla' (desde
    tema/unidad/RA/cantidad) o 'extraer' (estructura texto pegado de un PDF/DOCX/apunte)."""
    import os, json as _json
    from app.services import correccion_experta_service as ce
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "disponible": False, "error": "Falta ANTHROPIC_API_KEY."}
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    modo = payload.get("modo") or "plantilla"
    n = max(1, min(int(payload.get("cantidad") or 5), 30))
    system = ("Eres un experto en evaluación por competencias que redacta preguntas para un EXAMEN "
              "ORAL. Devuelve SOLO un JSON {\"preguntas\":[{\"enunciado\":\"...\",\"respuesta_esperada\":"
              "\"...\",\"conceptos_indispensables\":\"c1, c2\",\"dificultad\":\"baja|media|alta\"}]}. "
              "Preguntas claras, de respuesta hablada, sin numerar en el enunciado.")
    if modo == "extraer":
        texto = (payload.get("texto") or "").strip()
        if not texto:
            raise conflict("Pega el texto del que extraer preguntas.")
        user = ("Extrae y estructura como preguntas de examen oral el siguiente material "
                "(respeta las preguntas existentes; no inventes de más):\n\"\"\"\n" + texto[:8000] + "\n\"\"\"")
    else:
        ctx = {k: payload.get(k) for k in ("tema", "unidad", "ra", "nivel", "dificultad") if payload.get(k)}
        user = (f"Genera {n} preguntas de examen oral. Contexto: {_json.dumps(ctx, ensure_ascii=False)}. "
                f"Asignatura: {asm.name}.")
    try:
        crudo = ce._llamar_anthropic(system, user)
        t = crudo.strip(); i, j = t.find("{"), t.rfind("}")
        d = _json.loads(t[i:j + 1])
        pregs = []
        for p in (d.get("preguntas") or [])[:30]:
            en = str(p.get("enunciado", "")).strip()
            if en:
                pregs.append({"enunciado": en[:2000],
                              "respuesta_optima": str(p.get("respuesta_esperada", ""))[:3000],
                              "conceptos_indispensables": str(p.get("conceptos_indispensables", ""))[:1000],
                              "dificultad": str(p.get("dificultad", ""))[:20]})
        return {"ok": True, "disponible": True, "preguntas": pregs}
    except Exception as e:
        logger.warning("preguntas_ia falló: %s", f"{type(e).__name__}: {e}"[:200])
        return {"ok": False, "disponible": True, "error": f"{type(e).__name__}: {e}"[:200]}


@router.post("/assessments/{assessment_id}/importar", dependencies=[Depends(req_profesor)])
def importar_preguntas(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Crea preguntas orales (open_response) desde una lista. payload = {preguntas:[{enunciado,
    respuesta_optima?, conceptos_indispensables?, weight?, tiempo_reflexion_seg?}], reemplazar?}."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    pregs = payload.get("preguntas") or []
    if not isinstance(pregs, list) or not pregs:
        raise conflict("Envía al menos una pregunta.")
    ak = _ak_de(db, str(assessment_id))
    if payload.get("reemplazar"):
        for it in list(ak.items):
            if it.question_type == QUESTION_TYPE_OPEN_RESPONSE:
                db.delete(it)
        db.flush()
    base_num = max([it.question_number for it in ak.items] or [0])
    n = 0
    for p in pregs:
        en = (p.get("enunciado") or "").strip()
        if not en:
            continue
        base_num += 1
        try:
            w = float(p.get("weight") or 10)
        except (TypeError, ValueError):
            w = 10.0
        db.add(AnswerKeyItem(
            answer_key_id=ak.id, question_number=base_num, version="A", correct_answer="",
            question_type=QUESTION_TYPE_OPEN_RESPONSE, enunciado=en[:2000], weight=max(0.1, w),
            respuesta_optima=((p.get("respuesta_optima") or "").strip() or None),
            conceptos_indispensables=((p.get("conceptos_indispensables") or "").strip() or None),
            tiempo_reflexion_seg=(int(p["tiempo_reflexion_seg"]) if p.get("tiempo_reflexion_seg") else None)))
        n += 1
    ak.is_valid = True
    db.commit()
    return {"ok": True, "creadas": n, "preguntas": _preguntas(db, assessment_id)}


@router.post("/assessments/{assessment_id}/sesion", dependencies=[Depends(req_profesor)])
def crear_o_abrir_sesion(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Crea (o reabre) la sesión de examen oral de un estudiante. payload = {student_id, evaluador?,
    config?}."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    sid = str(payload.get("student_id") or "").strip()
    if not sid:
        raise conflict("Falta el estudiante.")
    s = (db.query(OralExamSesion)
         .filter(OralExamSesion.assessment_id == str(assessment_id),
                 OralExamSesion.student_id == sid).first())
    if not s:
        s = OralExamSesion(assessment_id=str(assessment_id), student_id=sid,
                           evaluador=(payload.get("evaluador") or "docente")[:120],
                           config_json=payload.get("config"))
        db.add(s)
    else:
        if payload.get("config") is not None:
            s.config_json = payload.get("config")
    db.commit(); db.refresh(s)
    return {"sesion": _sesion_dict(s, db, incluir_segmentos=True),
            "preguntas": _preguntas(db, assessment_id)}


@router.post("/sesion/{sesion_id}/segmentos", dependencies=[Depends(req_profesor)])
def guardar_segmentos(sesion_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Persiste (upsert por pregunta) los segmentos con la TRANSCRIPCIÓN LITERAL (Capa 2) y sus
    marcas de tiempo. payload = {estado?, duracion_seg?, audio_ref?, segmentos:[{pregunta_numero,
    item_id?, t_inicio_ms?, t_fin_ms?, transcripcion_literal, sin_respuesta?}]}."""
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    if payload.get("estado") in OE_ESTADOS:
        s.estado = payload["estado"]
    if payload.get("duracion_seg") is not None:
        try:
            s.duracion_seg = float(payload["duracion_seg"])
        except (TypeError, ValueError):
            pass
    if payload.get("audio_ref"):
        s.audio_ref = str(payload["audio_ref"])[:255]
    segs = payload.get("segmentos") or []
    nums = {int(x.get("pregunta_numero") or 0) for x in segs}
    if nums:
        db.query(OralExamSegmento).filter(
            OralExamSegmento.sesion_id == str(sesion_id),
            OralExamSegmento.pregunta_numero.in_(nums)).delete(synchronize_session=False)
    n = 0
    for x in segs:
        db.add(OralExamSegmento(
            sesion_id=s.id, pregunta_numero=int(x.get("pregunta_numero") or 0),
            answer_key_item_id=(str(x["item_id"]) if x.get("item_id") else None),
            t_inicio_ms=(int(x["t_inicio_ms"]) if x.get("t_inicio_ms") is not None else None),
            t_fin_ms=(int(x["t_fin_ms"]) if x.get("t_fin_ms") is not None else None),
            transcripcion_literal=((x.get("transcripcion_literal") or "").strip() or None),
            sin_respuesta=bool(x.get("sin_respuesta"))))
        n += 1
    db.commit(); db.refresh(s)
    return {"ok": True, "n_segmentos": n, "sesion": _sesion_dict(s, db, incluir_segmentos=True)}


@router.post("/sesion/{sesion_id}/procesar", dependencies=[Depends(req_profesor)])
def procesar_sesion(sesion_id: UUID, db: Session = Depends(get_db)):
    """F2+F3 · Procesa con IA: por cada segmento genera Capa 3 (normalizada + síntesis +
    correcciones fonéticas) y evalúa por 4 criterios con evidencia, y calcula la nota ponderada
    PROPUESTA. La IA propone; el docente valida y publica (G1). Sin API key → disponible=False."""
    from app.models.examen_oral import OralExamSesion
    from app.services import examen_oral_ia_service
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    try:
        res = examen_oral_ia_service.procesar_examen(db, s)
        if res.get("ok"):
            res["sesion"] = _sesion_dict(s, db, incluir_segmentos=True)
        return res
    except Exception:
        logger.error(f"Error en procesar_sesion {sesion_id}: {traceback.format_exc()}")
        raise


def _recompute_nota(db, sesion):
    """Nota ponderada usando el puntaje del DOCENTE si existe, si no el de la IA (G1)."""
    from app.services.result_service import calculate_grade
    asm = db.get(Assessment, sesion.assessment_id)
    escala = (asm.grading_scale if asm else "chile_1_7") or "chile_1_7"
    exig = (asm.passing_threshold if asm and asm.passing_threshold is not None else 60.0)
    num = 0.0; den = 0.0
    for seg in sesion.segmentos:
        item = db.get(AnswerKeyItem, seg.answer_key_item_id) if seg.answer_key_item_id else None
        wp = float(getattr(item, "weight", 1.0) or 1.0); den += wp
        evs = list(seg.evaluaciones)
        if not evs:
            continue
        pj = 0.0; ws = 0.0
        for e in evs:
            p = e.puntaje_docente if e.puntaje_docente is not None else (e.puntaje_ia or 0.0)
            pj += (p or 0.0) * (e.peso_criterio or 0.0); ws += (e.peso_criterio or 0.0)
        num += (pj / ws if ws else 0.0) * wp
    pct = round(num / den * 100, 1) if den else 0.0
    nota, etiqueta, aprob = calculate_grade(pct, escala, exig)
    return pct, round(nota, 1), etiqueta


@router.post("/sesion/{sesion_id}/validar", dependencies=[Depends(req_profesor)])
def validar_sesion(sesion_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """F4 · El docente ajusta puntajes por criterio (G1) y opcionalmente publica. payload =
    {evaluaciones:[{id, puntaje_docente(0-1)}], observaciones?, publicar?(bool)}. Recalcula la
    nota con los puntajes del docente. No borra la evidencia original."""
    from app.models.examen_oral import OralExamSesion, OralExamEvaluacion, OE_REVISADA, OE_PUBLICADA
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    for ev in (payload.get("evaluaciones") or []):
        e = db.get(OralExamEvaluacion, ev.get("id"))
        if not e:
            continue
        if ev.get("puntaje_docente") is not None:
            try:
                e.puntaje_docente = min(1.0, max(0.0, float(ev["puntaje_docente"])))
                e.accion = "ajustado" if (e.puntaje_ia is None or abs(e.puntaje_docente - e.puntaje_ia) > 1e-6) else "aprobado"
            except (TypeError, ValueError):
                pass
    if payload.get("observaciones") is not None:
        cfg = dict(s.config_json or {}); cfg["observaciones"] = str(payload["observaciones"])[:4000]
        s.config_json = cfg
    db.flush()
    pct, nota, etiqueta = _recompute_nota(db, s)
    s.logro_pct = pct; s.nota_final = nota
    s.estado = OE_PUBLICADA if payload.get("publicar") else OE_REVISADA
    db.commit(); db.refresh(s)
    return {"ok": True, "logro_pct": pct, "nota_final": nota, "etiqueta": etiqueta,
            "estado": s.estado, "sesion": _sesion_dict(s, db, incluir_segmentos=True)}


@router.get("/assessments/{assessment_id}/sesiones", dependencies=[Depends(req_profesor)])
def listar_sesiones(assessment_id: UUID, db: Session = Depends(get_db)):
    ses = (db.query(OralExamSesion)
           .filter(OralExamSesion.assessment_id == str(assessment_id)).all())
    return {"assessment_id": str(assessment_id),
            "sesiones": [_sesion_dict(s, db) for s in ses]}


@router.get("/sesion/{sesion_id}", dependencies=[Depends(req_profesor)])
def obtener_sesion(sesion_id: UUID, db: Session = Depends(get_db)):
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    return _sesion_dict(s, db, incluir_segmentos=True)


# ══════════════════════════════════════════════════════════════════════════
#  MODO A · canal en vivo QR (el celular del estudiante graba; el docente controla)
#  El docente abre el canal (genera token + QR); el teléfono lee la pregunta activa
#  y postea su transcripción; el docente avanza y ve el progreso develado. Doctrina:
#  el celular NO ve su transcripción ni descargas; el informe/nota es solo del docente.
# ══════════════════════════════════════════════════════════════════════════
def _vivo(s) -> dict:
    v = (s.config_json or {}).get("vivo") if isinstance(s.config_json, dict) else None
    return dict(v) if isinstance(v, dict) else {}


def _set_vivo(s, patch: dict):
    cfg = dict(s.config_json or {})
    v = dict(cfg.get("vivo") or {})
    v.update(patch)
    cfg["vivo"] = v
    s.config_json = cfg
    return v


@router.post("/sesion/{sesion_id}/vivo/abrir", dependencies=[Depends(req_profesor)])
def vivo_abrir(sesion_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """Abre (o reabre) el canal QR de una sesión. Devuelve token + URL de unión + QR (data URL).
    payload = {base?} (origen absoluto del front, p.ej. https://evalys-web.vercel.app)."""
    import secrets
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    if not s.vivo_token:
        s.vivo_token = secrets.token_urlsafe(9)
    _set_vivo(s, {"active_idx": 0, "estado": "esperando", "unido": False})
    s.estado = OE_GRABANDO
    db.commit(); db.refresh(s)
    base = (payload.get("base") or "").rstrip("/")
    join = (base + "/app.html?oral=" + s.vivo_token) if base else ("/app.html?oral=" + s.vivo_token)
    qr = None
    try:
        from app.services import en_vivo_service as _ev
        qr = _ev.qr_data_url(join)
    except Exception:
        qr = None
    return {"ok": True, "token": s.vivo_token, "join_url": join, "qr": qr}


@router.post("/sesion/{sesion_id}/vivo/control", dependencies=[Depends(req_profesor)])
def vivo_control(sesion_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """El docente controla el canal: cambia la pregunta activa o el estado
    (esperando|grabando|pausa|fin). payload = {active_idx?, estado?}."""
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    patch = {}
    if payload.get("active_idx") is not None:
        try:
            patch["active_idx"] = max(0, int(payload["active_idx"]))
        except (TypeError, ValueError):
            pass
    if payload.get("estado"):
        patch["estado"] = str(payload["estado"])[:20]
    v = _set_vivo(s, patch)
    db.commit()
    return {"ok": True, "vivo": v}


@router.get("/sesion/{sesion_id}/vivo", dependencies=[Depends(req_profesor)])
def vivo_estado_docente(sesion_id: UUID, db: Session = Depends(get_db)):
    """Polling del docente: estado del canal + progreso (nº de caracteres transcritos por pregunta)."""
    s = db.get(OralExamSesion, sesion_id)
    if not s:
        raise not_found("Sesión no encontrada.")
    prog = {g.pregunta_numero: len((g.transcripcion_literal or "")) for g in s.segmentos}
    return {"ok": True, "token": s.vivo_token, "vivo": _vivo(s),
            "progreso": prog, "n_segmentos": len(s.segmentos)}


def _sesion_por_token(db, token: str):
    return (db.query(OralExamSesion)
            .filter(OralExamSesion.vivo_token == token).first()) if token else None


@router.get("/vivo/{token}")
def vivo_publico_estado(token: str, db: Session = Depends(get_db)):
    """PÚBLICO (sin login) · el celular del estudiante lee la pregunta activa y el estado.
    NO expone transcripción ni notas."""
    s = _sesion_por_token(db, token)
    if not s:
        raise not_found("La sesión no existe o el examen ya se cerró.")
    v = _vivo(s)
    if not v.get("unido"):
        v = _set_vivo(s, {"unido": True}); db.commit()
    try:
        aid = UUID(s.assessment_id) if isinstance(s.assessment_id, str) else s.assessment_id
    except Exception:
        aid = s.assessment_id
    pregs = _preguntas(db, aid)
    asm = db.get(Assessment, aid)
    st = db.get(Student, s.student_id) if s.student_id else None
    idx = int(v.get("active_idx") or 0)
    activa = pregs[idx] if 0 <= idx < len(pregs) else None
    return {"nombre": (_nombre(st) if st else None), "prueba": (asm.name if asm else ""),
            "estado": v.get("estado", "esperando"), "active_idx": idx, "n": len(pregs),
            "pregunta": ({"numero": activa["numero"], "enunciado": activa["enunciado"],
                          "tiempo_max_seg": activa.get("tiempo_max_seg"),
                          "tiempo_reflexion_seg": activa.get("tiempo_reflexion_seg")} if activa else None)}


@router.post("/vivo/{token}/segmento")
def vivo_publico_segmento(token: str, payload: dict, db: Session = Depends(get_db)):
    """PÚBLICO · el celular postea la transcripción literal (completa) de la pregunta que responde.
    Upsert por pregunta; reemplaza el texto acumulado. payload = {pregunta_numero, transcripcion_literal}."""
    s = _sesion_por_token(db, token)
    if not s:
        raise not_found("La sesión no existe o el examen ya se cerró.")
    try:
        num = int(payload.get("pregunta_numero") or 0)
    except (TypeError, ValueError):
        num = 0
    if num <= 0:
        return {"ok": False}
    lit = (payload.get("transcripcion_literal") or "").strip()
    seg = (db.query(OralExamSegmento)
           .filter(OralExamSegmento.sesion_id == str(s.id),
                   OralExamSegmento.pregunta_numero == num).first())
    if not seg:
        seg = OralExamSegmento(sesion_id=s.id, pregunta_numero=num)
        db.add(seg)
    seg.transcripcion_literal = (lit or None)
    seg.sin_respuesta = (not lit)
    db.commit()
    return {"ok": True}
