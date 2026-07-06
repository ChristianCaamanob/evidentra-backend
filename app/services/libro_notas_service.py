"""
P - Libro de notas UNIFICADO: alternativas + desarrollo en una sola nota.

El profesor no maneja dos modulos separados: una misma evaluacion puede tener items de
seleccion multiple (auto-corregidos vs la pauta) y de desarrollo (evaluados por rubrica y
VALIDADOS por el docente, F3). Este servicio los combina en una nota final por estudiante,
PONDERADA POR ITEM: cada item aporta segun su peso, sin importar su tipo.

    logro_estudiante = sum( logro_item * peso_item ) / sum( peso_item )
    - item MC          -> logro = 1 si la alternativa coincide con la pauta, si no 0.
    - item de desarrollo -> logro = promedio ponderado del nivel VALIDADO de sus criterios.

Si un item de desarrollo aun no fue validado para un estudiante, se marca
'desarrollo_pendiente' (su logro cuenta 0 hasta que el docente lo valide).

Gobernanza: la parte de desarrollo usa el nivel del DOCENTE (G1, indelegable); agregado y
seudonimizado (G2). Un item se considera 'de desarrollo' si tiene criterios de rubrica,
con independencia de la etiqueta question_type (tolera 'open_response'/'desarrollo').
"""
from __future__ import annotations

from app.core.errors import conflict
from app.models.validacion import RegistroValidacion
from app.services.result_service import calculate_grade
from app.services.rubrica_escala_service import fraccion_logro
from app.services.matriz_service import _pseudo, answer_key_repo, scan_repo


def libro_notas(db, assessment_id, escala: str = "chile_1_7", exigencia: float = 60.0) -> dict:
    answer_key = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no esta validada; no hay libro de notas.")

    por_version: dict[str, dict[int, object]] = {}
    items_meta: dict[int, dict] = {}
    dev_criterios: dict[int, list[tuple[str, float]]] = {}
    for it in answer_key.items:
        if it.is_annulled:
            continue
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
        criterios = list(it.rubric_criteria)
        es_desarrollo = bool(criterios)          # robusto: lo define la rubrica, no la etiqueta
        items_meta[it.question_number] = {"desarrollo": es_desarrollo, "weight": float(it.weight)}
        if es_desarrollo:
            dev_criterios[it.question_number] = [
                (c.name, float(c.weight), c.niveles_json, c.ambito) for c in criterios]

    if not items_meta:
        raise conflict("La evaluacion no tiene items validos.")
    total_weight = sum(m["weight"] for m in items_meta.values()) or 1.0

    # Niveles VALIDADOS de desarrollo: por estudiante (seudonimo) -> criterio -> logro.
    validado: dict[str, dict[str, float]] = {}
    for r in db.query(RegistroValidacion).filter(
            RegistroValidacion.assessment_id == str(assessment_id)).all():
        pseudo = str(r.respuesta_ref).split("#")[0]
        validado.setdefault(pseudo, {})[r.criterio] = r.nivel_docente   # nivel crudo (str)

    # Sujetos de evaluacion: en 'oral' es cada estudiante de la nomina (rubrica directa, sin
    # hoja); en 'escrita' es cada escaneo. Ambos comparten el resto del calculo.
    from app.models.assessment import Assessment, MODALIDAD_ORAL
    from app.models.student import Student
    from app.models.grupo import Grupo

    assessment = db.get(Assessment, assessment_id)
    oral = assessment is not None and assessment.modalidad == MODALIDAD_ORAL

    # Grupo de cada estudiante -> seudonimo del grupo (fuente de los criterios grupales).
    grupo_pseudo_por_est: dict[str, str] = {}
    for g in db.query(Grupo).filter(Grupo.assessment_id == str(assessment_id)).all():
        for integ in g.integrantes:
            grupo_pseudo_por_est[integ.student_id] = _pseudo(g.id)

    if oral:
        estudiantes = db.query(Student).filter(Student.course_id == assessment.course_id).all()
        sujetos = [(_pseudo(st.id), None, str(st.id)) for st in estudiantes]
    else:
        rut_a_id = ({st.rut: str(st.id) for st in
                     db.query(Student).filter(Student.course_id == assessment.course_id).all()}
                    if assessment else {})
        sujetos = [(_pseudo(sc.id), sc, rut_a_id.get(sc.student_identifier))
                   for sc in scan_repo.list_by_assessment(db, assessment_id)
                   if not getattr(sc, "requires_review", False)]

    filas = []
    for pseudo, scan, student_id in sujetos:
        clave = por_version.get((scan.detected_version or "A").upper()) if scan else None
        respuestas = (scan.raw_ocr_payload_json or {}).get("answers", []) if scan else []
        sv = validado.get(pseudo, {})                            # registros propios (individual)
        grupo_pseudo = grupo_pseudo_por_est.get(student_id)
        sv_grupo = validado.get(grupo_pseudo, {}) if grupo_pseudo else {}   # registros del grupo
        contrib = 0.0
        pendiente = False
        for q, meta in items_meta.items():
            w = meta["weight"]
            if meta["desarrollo"]:
                crits = dev_criterios.get(q, [])          # [(name, weight, niveles, ambito)]
                obtenidos = []
                for cn, cw, niv, amb in crits:
                    fuente = sv_grupo if amb == "grupal" else sv   # grupal -> registro del grupo
                    if cn in fuente:
                        obtenidos.append((cw, niv, fuente[cn]))
                if obtenidos:
                    tw = sum(cw for cw, _, _ in obtenidos) or 1.0
                    logro = sum(fraccion_logro(niv, lvl) * cw
                                for cw, niv, lvl in obtenidos) / tw
                else:
                    logro = 0.0
                    pendiente = True             # aun sin validar
                contrib += logro * w
            else:
                item = clave.get(q) if clave else None
                if item is None:
                    continue
                elegida = respuestas[q - 1] if (q - 1) < len(respuestas) else None
                ok = 1.0 if (elegida is not None and
                             str(elegida).upper() == str(item.correct_answer).upper()) else 0.0
                contrib += ok * w
        pct = round(contrib / total_weight * 100, 1)
        nota, etiqueta, aprob = calculate_grade(pct, escala, exigencia)
        filas.append({"estudiante": pseudo, "logro_pct": pct, "nota": round(nota, 1),
                      "etiqueta": etiqueta, "aprobado": bool(aprob),
                      "desarrollo_pendiente": pendiente})

    n_mc = sum(1 for m in items_meta.values() if not m["desarrollo"])
    n_dev = sum(1 for m in items_meta.values() if m["desarrollo"])
    notas = [f["nota"] for f in filas]
    return {
        "assessment_id": str(assessment_id),
        "n_estudiantes": len(filas),
        "composicion": {"items_alternativas": n_mc, "items_desarrollo": n_dev,
                        "mixta": n_mc > 0 and n_dev > 0},
        "estudiantes": filas,
        "resumen": {
            "promedio": round(sum(notas) / len(notas), 1) if notas else None,
            "aprobados": sum(1 for f in filas if f["aprobado"]),
            "reprobados": sum(1 for f in filas if not f["aprobado"]),
            "pendientes_desarrollo": sum(1 for f in filas if f["desarrollo_pendiente"]),
        },
        "politica": "Nota unica ponderada por item (alternativas + desarrollo juntos).",
        "gobernanza": "La parte de desarrollo usa el nivel VALIDADO por el docente (G1, "
                      "indelegable). Agregado y seudonimizado (G2).",
    }
