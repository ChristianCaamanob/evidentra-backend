"""
Ventana de REPORTES de desarrollo (vista docente identificada).

Tabla por estudiante: curso · prueba · ponderación semestral · RUT · nombre · puntaje · nota,
con detalle por pregunta (respuesta + revisión contra los criterios del docente). Reutiliza el
libro de notas para la NOTA (no recalcula) y DesarrolloRespuesta para el detalle persistido.

Gobernanza: vista docente identificada (G1: la nota la fija el docente). El uso agregado /
investigador sigue seudonimizado (G2) por otras rutas.
"""
from __future__ import annotations

from app.core.errors import not_found
from app.models.assessment import Assessment
from app.models.course import Course
from app.models.student import Student
from app.models.answer_key import AnswerKey, AnswerKeyItem, QUESTION_TYPE_OPEN_RESPONSE
from app.models.desarrollo_reporte import DesarrolloRespuesta
from app.services import libro_notas_service


def _cabecera(db, assessment) -> dict:
    course = db.get(Course, assessment.course_id) if assessment.course_id else None
    return {
        "assessment_id": str(assessment.id),
        "prueba": assessment.name,
        "tipo": assessment.tipo,
        "curso": (course.name if course else None),
        "curso_id": (str(course.id) if course else None),
        "ponderacion_semestral": getattr(assessment, "ponderacion_semestral", None),
        "escala": assessment.grading_scale or "chile_1_7",
        "exigencia": assessment.passing_threshold if assessment.passing_threshold is not None else 60.0,
    }


def _nombre_de(st) -> str | None:
    return ((getattr(st, "apellido_paterno", "") or "") + " "
            + (getattr(st, "apellido_materno", "") or "") + " "
            + (getattr(st, "nombres", "") or "")).replace("  ", " ").strip() or None


def tabla_reportes(db, assessment_id) -> dict:
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    cab = _cabecera(db, asm)
    escala = cab["escala"]; exig = cab["exigencia"]
    libro = libro_notas_service.libro_notas(db, assessment_id, escala=escala, exigencia=exig,
                                            incluir_identidad=True)
    # Resultados del libro indexados por estudiante identificado (ignora hojas sin match a nómina).
    por_sid = {}
    for f in libro.get("estudiantes", []):
        sid = f.get("student_id")
        if sid:
            por_sid[sid] = f
    # estudiantes con detalle de DESARROLLO persistido (para habilitar el click-through)
    con_detalle = {r.student_id for r in db.query(DesarrolloRespuesta.student_id)
                   .filter(DesarrolloRespuesta.assessment_id == str(assessment_id)).all()}

    # La tabla se ancla en la NÓMINA REAL del curso (RUT + nombre); cada alumno muestra su nota
    # si ya está cargado, o queda 'pendiente'. Así no aparecen hojas sueltas "sin nómina".
    roster = (db.query(Student).filter(Student.course_id == asm.course_id).all()
              if asm.course_id else [])
    filas = []
    for st in roster:
        sid = str(st.id)
        f = por_sid.get(sid)
        cargado = f is not None
        filas.append({
            "student_id": sid, "rut": getattr(st, "rut", None), "nombre": _nombre_de(st),
            "puntaje_pct": (f.get("logro_pct") if cargado else None),
            "nota": (f.get("nota") if cargado else None),
            "aprobado": (f.get("aprobado") if cargado else None),
            "etiqueta": (f.get("etiqueta") if cargado else None),
            "pendiente": (f.get("desarrollo_pendiente") if cargado else True),
            "cargado": cargado,
            "tiene_detalle": sid in con_detalle,
        })
    filas.sort(key=lambda x: (not x["cargado"], (x["nombre"] or "").lower()))
    cab["estudiantes"] = filas
    cab["n_cargados"] = sum(1 for x in filas if x["cargado"])
    cab["n_nomina"] = len(filas)
    cab["resumen"] = libro.get("resumen", {})
    cab["composicion"] = libro.get("composicion", {})
    return cab


def detalle_estudiante(db, assessment_id, student_id) -> dict:
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    st = db.get(Student, student_id)
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    enun_por_num = {}
    if ak:
        for it in ak.items:
            if it.question_type == QUESTION_TYPE_OPEN_RESPONSE:
                enun_por_num[it.question_number] = {
                    "enunciado": it.enunciado or "",
                    "respuesta_optima": it.respuesta_optima or it.correct_answer or "",
                    "criterios": [{"name": c.name, "descriptor": c.descriptor}
                                  for c in (it.rubric_criteria or [])]}
    rows = (db.query(DesarrolloRespuesta)
            .filter(DesarrolloRespuesta.assessment_id == str(assessment_id),
                    DesarrolloRespuesta.student_id == str(student_id))
            .order_by(DesarrolloRespuesta.question_number).all())
    preguntas = []
    for r in rows:
        meta = enun_por_num.get(r.question_number, {})
        preguntas.append({
            "numero": r.question_number,
            "enunciado": meta.get("enunciado", ""),
            "respuesta_optima": meta.get("respuesta_optima", ""),
            "criterios": meta.get("criterios", []),
            "respuesta": r.respuesta_texto or "",
            "puntaje": r.puntaje, "frac": r.frac, "nivel": r.nivel,
            "revision": r.revision_json or {},
        })
    nombre = None
    if st:
        nombre = ((getattr(st, "apellido_paterno", "") or "") + " "
                  + (getattr(st, "apellido_materno", "") or "") + " "
                  + (getattr(st, "nombres", "") or "")).replace("  ", " ").strip() or None
    return {"assessment_id": str(assessment_id), "student_id": str(student_id),
            "rut": (getattr(st, "rut", None) if st else None), "nombre": nombre,
            "prueba": asm.name, "n_preguntas": len(preguntas), "preguntas": preguntas}


def guardar_detalle(db, assessment_id, student_id, preguntas: list, docente: str = "docente") -> dict:
    """Upsert POR PREGUNTA (evaluación × estudiante × question_number): reemplaza solo las
    preguntas incluidas en el payload, sin borrar el detalle de otras preguntas ya guardadas
    (el lote corrige una pregunta a la vez)."""
    asm = db.get(Assessment, assessment_id)
    if not asm:
        raise not_found("Evaluación no encontrada.")
    nums = {int(p.get("question_number") or p.get("numero") or 0) for p in (preguntas or [])}
    if nums:
        db.query(DesarrolloRespuesta).filter(
            DesarrolloRespuesta.assessment_id == str(assessment_id),
            DesarrolloRespuesta.student_id == str(student_id),
            DesarrolloRespuesta.question_number.in_(nums)).delete(synchronize_session=False)
    n = 0
    for p in (preguntas or []):
        resp = (p.get("respuesta") or "").strip()
        if not resp and p.get("puntaje") is None:
            continue
        db.add(DesarrolloRespuesta(
            assessment_id=str(assessment_id), student_id=str(student_id),
            answer_key_item_id=(str(p["item_id"]) if p.get("item_id") else None),
            question_number=int(p.get("question_number") or p.get("numero") or 0),
            respuesta_texto=resp or None,
            puntaje=(float(p["puntaje"]) if p.get("puntaje") is not None else None),
            frac=(float(p["frac"]) if p.get("frac") is not None else None),
            nivel=(str(p.get("nivel"))[:20] if p.get("nivel") else None),
            revision_json=(p.get("revision") if isinstance(p.get("revision"), dict) else None),
            docente=docente[:120]))
        n += 1
    db.commit()
    return {"ok": True, "assessment_id": str(assessment_id), "student_id": str(student_id),
            "n_preguntas": n}
