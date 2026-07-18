"""
Estadística de evaluaciones ORALES (disertación/exposición) para alimentar los informes.

En oral no hay escaneos: la nota sale de la rúbrica aplicada por estudiante (criterios
individuales) y por grupo (criterios grupales), persistida como RegistroValidacion. Este
servicio agrega esos registros para:
  - stats_curso(db, aid): distribución de notas + logro por SECCIÓN de la rúbrica (Contenido,
    Organización, Preguntas finales…) + criterios/secciones más débiles.
  - stats_estudiante(db, aid, student_id): nota + brechas/fortalezas por sección, en forma
    del contrato que consume briefing_service (para el briefing personalizado).

Reusa la misma matemática que el endpoint /oral/estudiantes: fraccion_logro(niveles, nivel)*peso.
"""
from __future__ import annotations

from app.services.rubrica_escala_service import fraccion_logro
from app.services.result_service import calculate_grade
from app.services.matriz_service import _pseudo


def _criterios(db, assessment_id):
    from app.models.answer_key import AnswerKey, AnswerKeyItem, RubricCriterion, QUESTION_TYPE_OPEN_RESPONSE
    crits = []
    ak = db.query(AnswerKey).filter(AnswerKey.assessment_id == assessment_id).first()
    if ak:
        for it in db.query(AnswerKeyItem).filter(
                AnswerKeyItem.answer_key_id == ak.id,
                AnswerKeyItem.question_type == QUESTION_TYPE_OPEN_RESPONSE).all():
            for c in db.query(RubricCriterion).filter(
                    RubricCriterion.answer_key_item_id == it.id).order_by(RubricCriterion.order).all():
                crits.append({"name": c.name, "weight": float(c.weight or 1),
                              "niveles": c.niveles_json, "ambito": c.ambito or "individual",
                              "seccion": c.seccion or "General"})
    return crits


def _validado(db, assessment_id):
    from app.models.validacion import RegistroValidacion
    v: dict = {}
    for r in db.query(RegistroValidacion).filter(
            RegistroValidacion.assessment_id == str(assessment_id)).all():
        p = str(r.respuesta_ref).split("#")[0]
        v.setdefault(p, {})[r.criterio] = r.nivel_docente
    return v


def _grupo_por_est(db, assessment_id):
    from app.models.grupo import Grupo
    m: dict = {}
    for g in db.query(Grupo).filter(Grupo.assessment_id == str(assessment_id)).all():
        gp = _pseudo(g.id)
        for integ in g.integrantes:
            m[str(integ.student_id)] = gp
    return m


def _logro(crits, sv_ind, sv_grp):
    """Devuelve (frac_total, n_resueltos, {seccion: (acc, peso)})."""
    total_w = sum(c["weight"] for c in crits) or 1.0
    acc = 0.0
    resueltos = 0
    por_sec: dict = {}
    for c in crits:
        fuente = sv_grp if c["ambito"] == "grupal" else sv_ind
        if c["name"] in fuente:
            fr = fraccion_logro(c["niveles"], fuente[c["name"]])
            acc += fr * c["weight"]
            resueltos += 1
            s = c["seccion"]
            a, w = por_sec.get(s, (0.0, 0.0))
            por_sec[s] = (a + fr * c["weight"], w + c["weight"])
    return acc / total_w, resueltos, por_sec


def _config(db, assessment_id):
    from app.models.assessment import Assessment
    a = db.get(Assessment, assessment_id)
    escala = (a.grading_scale if a else None) or "chile_1_7"
    exigencia = (a.passing_threshold if a and a.passing_threshold is not None else 60.0)
    banda = bool(getattr(a, "bandas_moviles", False)) if a else False
    return escala, exigencia, banda


def _por_seccion(por_sec):
    return [{"clave": s, "logro_promedio": round((a / w) * 100, 1) if w else 0.0}
            for s, (a, w) in por_sec.items()]


def stats_curso(db, assessment_id):
    from app.models.assessment import Assessment
    from app.models.student import Student
    crits = _criterios(db, assessment_id)
    val = _validado(db, assessment_id)
    gpe = _grupo_por_est(db, assessment_id)
    escala, exigencia, banda = _config(db, assessment_id)
    a = db.get(Assessment, assessment_id)
    estudiantes = db.query(Student).filter(Student.course_id == a.course_id).all() if a else []
    notas, pcts = [], []
    sec_glob: dict = {}   # seccion -> [suma_frac, n]
    for st in estudiantes:
        sv_ind = val.get(_pseudo(st.id), {})
        gp = gpe.get(str(st.id))
        sv_grp = val.get(gp, {}) if gp else {}
        frac, resueltos, por_sec = _logro(crits, sv_ind, sv_grp)
        if resueltos < len(crits) or not crits:      # solo estudiantes con nota completa
            continue
        pct = round(frac * 100, 1)
        nota, _et, _ap = calculate_grade(pct, escala, exigencia, banda_movil=banda)
        notas.append(round(nota, 1))
        pcts.append(pct)
        for s, (acc, w) in por_sec.items():
            fr_sec = acc / w if w else 0.0
            cur = sec_glob.get(s, [0.0, 0])
            cur[0] += fr_sec
            cur[1] += 1
            sec_glob[s] = cur
    por_seccion = [{"clave": s, "logro_promedio": round((v[0] / v[1]) * 100, 1) if v[1] else 0.0,
                    "items": v[1]} for s, v in sec_glob.items()]
    por_seccion.sort(key=lambda x: x["logro_promedio"])
    return {"n": len(pcts), "notas": notas, "pcts": pcts, "por_seccion": por_seccion,
            "escala": escala, "exigencia": exigencia}


def stats_estudiante(db, assessment_id, student_id):
    from app.models.student import Student
    crits = _criterios(db, assessment_id)
    val = _validado(db, assessment_id)
    gpe = _grupo_por_est(db, assessment_id)
    escala, exigencia, banda = _config(db, assessment_id)
    st = db.get(Student, student_id)
    nombre = (" ".join(x for x in [getattr(st, "nombres", ""), getattr(st, "apellido_paterno", ""),
                                   getattr(st, "apellido_materno", "")] if x).strip()
              if st else "") or (getattr(st, "rut", "") if st else "")
    sv_ind = val.get(_pseudo(student_id), {})
    gp = gpe.get(str(student_id))
    sv_grp = val.get(gp, {}) if gp else {}
    frac, resueltos, por_sec_raw = _logro(crits, sv_ind, sv_grp)
    pct = round(frac * 100, 1)
    nota, etiqueta, aprob = calculate_grade(pct, escala, exigencia, banda_movil=banda)
    secciones = _por_seccion(por_sec_raw)
    brechas = [{"nombre": s["clave"]} for s in sorted(secciones, key=lambda x: x["logro_promedio"])
               if s["logro_promedio"] < 60]
    fortalezas = [{"nombre": s["clave"]} for s in sorted(secciones, key=lambda x: -x["logro_promedio"])
                  if s["logro_promedio"] >= 75]
    # promedio del curso (para posición)
    curso = stats_curso(db, assessment_id)
    prom = round(sum(curso["pcts"]) / len(curso["pcts"]), 1) if curso["pcts"] else None
    menores = sum(1 for p in curso["pcts"] if p <= pct)
    percentil = round(menores / len(curso["pcts"]) * 100) if curso["pcts"] else None
    return {
        "estudiante": {"nombre": nombre},
        "resumen": {"nota": round(nota, 1), "correctas": None, "incorrectas": None,
                    "omitidas": None, "percentil": percentil},
        "brechas": brechas, "fortalezas": fortalezas,
        "distribucion_curso": {"promedio": prom, "percentil": percentil},
        "secciones": secciones, "completo": (resueltos == len(crits) and bool(crits)),
    }
