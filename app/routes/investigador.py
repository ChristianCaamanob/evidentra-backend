"""
Router del modulo Investigador (Fase 1 del cableado): expone la psicometria agregada de
una evaluacion. Solo lectura, seudonimizado (G2), no altera notas (G1).

Fase 1 (datos de seleccion multiple, disponibles hoy):
  - GET /assessments/{id}/psicometria/rasch          -> I1 (irt_service)
  - GET /assessments/{id}/psicometria/dimensionalidad -> I7 (dimensionalidad_service)

Los endpoints sobre rubrica (PCM, R, MFRM) y los con grupo (DIF, invarianza) llegan en las
fases 2 y 3, junto con los datos y decisiones que consumen.
"""
import logging
import traceback
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi import Depends as _Dep
from app.api.deps import get_db, req_investigador
from app.services import matriz_service
from app.services import irt_service
from app.services import dimensionalidad_service
from app.services import dina_service
from app.services import dif_service
from app.services import invarianza_service
from app.services import estadistica_service
from app.services import efectos_service
from app.services import cfa_service
from app.services import tri_service
from app.services import poder_muestral_service
from app.services import reporte_service
from app.services import curso_stats_service
from app.services import cualitativo_service
from app.services import rutas_service
from app.services import literatura_service

# Todo el modulo Investigador exige rol investigador (o creador). El director NO accede a
# este modulo de investigacion; su alcance es ver/exportar datos de estudiante y profesor.
router = APIRouter(prefix="/assessments", tags=["investigador"],
                   dependencies=[_Dep(req_investigador)])
logger = logging.getLogger("evalys")


def _meta(datos: dict, tecnica: str | None = None) -> dict:
    m = {"n_personas": datos["n_personas"], "n_items": datos["n_items"],
         "omitidas_pct": datos["omitidas_pct"],
         "gobernanza": "Analisis agregado y seudonimizado (G2); no altera notas (G1)."}
    if tecnica:
        m["poder_muestral"] = poder_muestral_service.evaluar(
            tecnica, datos["n_personas"], datos["n_items"])
    return m


@router.get("/{assessment_id}/psicometria/rasch")
def psicometria_rasch(assessment_id: UUID, db: Session = Depends(get_db)):
    """I1 - Modelo de Rasch (dificultad, habilidad, ajuste, informacion, fiabilidad)."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = irt_service.estimar_rasch(datos["X"])
        for it, num in zip(rep["items"], datos["items"]):
            it["pregunta"] = num                       # numero real de pregunta (no indice)
        rep["_meta"] = _meta(datos, "rasch")
        return rep
    except Exception:
        logger.error(f"Error en psicometria_rasch {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estadistica/clasica")
def estadistica_clasica(assessment_id: UUID, db: Session = Depends(get_db)):
    """Fases 1-2 del pipeline: depuracion de datos (descriptivos, supuestos, perdidos) y
    analisis de items en Teoria Clasica (dificultad, discriminacion, fiabilidad: alfa, omega,
    SEM, Guttman). Numera los items con su pregunta real."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = estadistica_service.reporte_completo(datos["X"])
        nums = datos["items"]
        for bloque in (rep["descriptivos"]["items"], rep["items_tct"]["items"],
                       rep["datos_perdidos"]["por_item"]):
            for it, num in zip(bloque, nums):
                it["pregunta"] = num
        rep["_meta"] = _meta(datos, "clasica")
        return rep
    except Exception:
        logger.error(f"Error en estadistica_clasica {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/cualitativo")
def analisis_cualitativo(assessment_id: UUID, db: Session = Depends(get_db),
                         _: object = _Dep(req_investigador)):
    """I4 - Análisis cualitativo: mapa de concepciones erróneas (puente cuanti->cuali).
    Cada distractor con prevalencia >= umbral revela una concepción errónea específica,
    con severidad y RA afectado. Trabaja sobre respuestas seudonimizadas (G2)."""
    try:
        datos = matriz_service.cargar_respuestas_letras(db, assessment_id)
        resultado = curso_stats_service.analizar_evaluacion(
            datos["respuestas_alumnos"], datos["pauta"], te_tags=datos["te_tags"])
        mapa = cualitativo_service.mapa_concepciones(resultado.get("items", []), contenido={})
        return {"mapa_concepciones": mapa,
                "_meta": {"n_personas": resultado["instrumento"]["n_alumnos"],
                          "n_items": resultado["instrumento"]["n_items"]}}
    except Exception:
        logger.error(f"Error en analisis_cualitativo {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/rutas")
def rutas_investigacion(assessment_id: UUID, db: Session = Depends(get_db),
                        _: object = _Dep(req_investigador)):
    """Rutas de investigación CONTEXTUALES: las ramas se desbloquean según los datos presentes
    (n, grupos consentidos, etiquetado C3, nº de evaluaciones). Flujograma que crece con el trabajo."""
    try:
        from app.models.assessment import Assessment
        from app.models.course import Course
        from app.models.student import Student
        n = k = 0; has_c3 = False
        try:
            datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
            n, k = datos["n_personas"], datos["n_items"]
            has_c3 = any(bool((v or {}).get("ra")) for v in (datos.get("tags") or {}).values())
        except Exception:
            pass
        a = db.get(Assessment, assessment_id)
        course_id = a.course_id if a else None
        n_eval = (db.query(Assessment).filter(Assessment.course_id == course_id).count()
                  if course_id else 1)
        has_grupos = False; topic = "educational assessment"
        if course_id:
            has_grupos = db.query(Student).filter(
                Student.course_id == course_id, Student.consiente_equidad.is_(True),
                Student.sexo.isnot(None)).count() > 0
            c = db.get(Course, course_id)
            nm = (getattr(c, "name", "") or "").lower()
            if "psico" in nm or "medi" in nm or "salud" in nm:
                topic = "educational measurement"
        ctx = {"n": n, "k": k, "has_grupos": has_grupos, "has_c3": has_c3,
               "n_evaluaciones": n_eval, "topic": topic}
        return rutas_service.construir(ctx)
    except Exception:
        logger.error(f"Error en rutas_investigacion {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/investigacion/literatura")
def literatura(q: str = Query(..., min_length=2),
               rows: int = Query(8, ge=1, le=25),
               anios: int = Query(0, ge=0, le=50),
               _: object = _Dep(req_investigador)):
    """Literatura en vivo (OpenAlex + Crossref): artículos reales verificados por DOI, con
    abstract, citas, estado open-access, cita APA 7/Vancouver y export BibTeX/RIS. Nunca inventa
    referencias; deduplica por DOI. `anios`=ventana temporal (5/10/15…; 0=sin límite).
    `q` es la línea de investigación (en inglés rinde mejor)."""
    try:
        return literatura_service.buscar(q, rows=rows, anios=(anios or None))
    except Exception:
        logger.error(f"Error en literatura '{q}': {traceback.format_exc()}")
        raise


@router.get("/investigacion/corpus")
def corpus(q: str = Query(..., min_length=2),
           anios: int = Query(0, ge=0, le=50),
           limite: int = Query(150, ge=10, le=300),
           _: object = _Dep(req_investigador)):
    """Corpus de candidatos para el tablero de cribado (revisión sistemática): pagina OpenAlex
    por cursor hasta `limite` (≤300), deduplica por DOI, con abstract/citas/OA para cribar.
    Base del diagrama PRISMA 2020. `anios`=ventana temporal (0=sin límite)."""
    try:
        return literatura_service.buscar_corpus(q, anios=(anios or None), limite=limite)
    except Exception:
        logger.error(f"Error en corpus '{q}': {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dimensionalidad")
def psicometria_dimensionalidad(assessment_id: UUID, db: Session = Depends(get_db)):
    """I7 - Dimensionalidad (KMO, Bartlett, analisis paralelo, EFA) + fiabilidad ampliada."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = dimensionalidad_service.analizar_dimensionalidad(datos["X"], dicotomico=True)
        rep["_meta"] = _meta(datos, "dimensionalidad")
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dimensionalidad {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dina")
def psicometria_dina(assessment_id: UUID, base: str = Query("ra", pattern="^(ra|bloom)$"),
                     db: Session = Depends(get_db)):
    """I9 - Diagnostico cognitivo (DINA). La Q-matrix se deriva del etiquetado C3: cada
    item carga en su RA (base=ra) o nivel Bloom (base=bloom)."""
    try:
        d = matriz_service.cargar_dina(db, assessment_id, base=base)
        rep = dina_service.estimar_dina(d["X"], d["Q"], atributos=d["atributos"])
        for it, num in zip(rep["items"], d["items"]):
            it["pregunta"] = num                       # numero real de pregunta
        rep["_meta"] = {"n_personas": d["n_personas"], "n_items": len(d["items"]),
                        "base_atributos": base,
                        "poder_muestral": poder_muestral_service.evaluar(
                            "dina", d["n_personas"], len(d["items"])),
                        "gobernanza": "Diagnostico agregado y seudonimizado (G2); orienta "
                                      "remediacion, no altera notas (G1). Q-matrix derivada de C3."}
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dina {assessment_id}: {traceback.format_exc()}")
        raise


def _meta_equidad(d: dict) -> dict:
    # En análisis por grupo, la potencia la limita el grupo MÁS PEQUEÑO.
    n_grupo_min = None
    grupos = d.get("grupo")
    if grupos is not None:
        try:
            from collections import Counter
            counts = Counter(str(g) for g in grupos if g is not None and str(g) != "")
            if counts:
                n_grupo_min = min(counts.values())
        except Exception:
            pass
    return {"variable": d["variable"], "comparados": d["categorias_comparadas"],
            "categorias_omitidas": d["categorias_omitidas"], "n": d["n"],
            "excluidos_sin_consentimiento": d["excluidos_sin_consentimiento"],
            "poder_muestral": poder_muestral_service.evaluar(
                "dif", d["n"], n_grupo_min=n_grupo_min),
            "gobernanza": "Solo estudiantes que CONSINTIERON el analisis de equidad (G4); "
                          "datos seudonimizados (G2); grupos con minimo para evitar "
                          "reidentificacion. No altera notas (G1)."}


@router.get("/{assessment_id}/reporte")
def reporte_reproducible(assessment_id: UUID, db: Session = Depends(get_db)):
    """Fase 9 - Reporte reproducible: junta los estadisticos reales y redacta Metodos+Resultados
    con IA (o plantilla si no hay clave), mas un checklist COSMIN."""
    try:
        from app.models.assessment import Assessment
        from app.models.course import Course
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        X = datos["X"]
        alfa = estadistica_service.alfa_cronbach(X)
        om = estadistica_service.omega_mcdonald(X)
        sem = estadistica_service.sem(X, alfa.get("alfa"))
        a = db.get(Assessment, assessment_id); c = db.get(Course, a.course_id) if a else None
        cfa = cfa_service.ajuste_cfa(X, incluir_wlsmv_demo=bool(c and getattr(c, "code", None) == "DEMO-PSICO"))
        w = cfa.get("wlsmv") or {}
        hechos = {
            "n": datos["n_personas"], "n_items": datos["n_items"],
            "fiabilidad": {"alfa": alfa.get("alfa"), "omega": om.get("omega"), "sem": sem.get("sem")},
            "estructura": {"SRMR": cfa["ajuste"]["SRMR"], "AVE": cfa["convergente"]["AVE"],
                           "CR": cfa["convergente"]["CR"], "veredicto": cfa["veredicto"],
                           "CFI": w.get("CFI"), "TLI": w.get("TLI"), "RMSEA": w.get("RMSEA"),
                           "veredicto_wlsmv": w.get("veredicto"),
                           "fuente_ajuste": w.get("software")},
        }
        try:
            tri = tri_service.comparar_modelos(X)
            hechos["tri"] = {"preferido": tri["comparacion"]["preferido_BIC"],
                             "delta_BIC": tri["comparacion"]["delta_BIC"], "veredicto": tri["veredicto"]}
        except Exception:
            pass
        try:
            dg = matriz_service.cargar_matriz_con_grupo(db, assessment_id, "sexo")
            Xg = np.asarray(dg["X"], dtype=float); total = np.nansum(Xg, axis=1)
            ef = efectos_service.comparar_grupos(total, dg["grupo"], dg.get("referencia"), dg.get("focal"))
            hechos["efectos"] = {"variable": "sexo", "comparados": ef["comparados"],
                                 "cohen_d": ef["cohen_d"], "d_ic95": ef["d_ic95"], "magnitud": ef["magnitud"]}
            dif = dif_service.analizar_dif(Xg, dg["grupo"], np.nansum(Xg, axis=1), etiqueta_focal=dg["focal"])
            n_dif = int(dif.get("items_con_dif") if isinstance(dif.get("items_con_dif"), int)
                        else len(dif.get("items_con_dif", [])))
            hechos["dif_resumen"] = (f"Sin DIF relevante entre {' y '.join(ef['comparados'])}."
                                     if n_dif == 0 else f"{n_dif} item(es) con DIF entre {' y '.join(ef['comparados'])}.")
            inv = cfa_service.invarianza_configural(Xg, dg["grupo"])
            hechos["invarianza"] = inv.get("veredicto")
        except Exception:
            pass
        red = reporte_service.redactar(hechos)
        return {"hechos": hechos, "metodos": red["metodos"], "resultados": red["resultados"],
                "motor": red["motor"], "checklist": reporte_service.checklist_cosmin(hechos),
                "_meta": _meta(datos, "cfa")}
    except Exception:
        logger.error(f"Error en reporte {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/tri")
def psicometria_tri(assessment_id: UUID, db: Session = Depends(get_db)):
    """Fase 3 - TRI: compara 1PL vs 2PL (AIC/BIC), parametros 2PL (discriminacion/dificultad)
    e independencia local (Q3 de Yen). Estimacion MML con girth."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        rep = tri_service.comparar_modelos(datos["X"])
        for it, num in zip(rep["items_2PL"], datos["items"]):
            it["pregunta"] = num
        rep["_meta"] = _meta(datos, "tri")
        return rep
    except Exception:
        logger.error(f"Error en psicometria_tri {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estructura/cfa")
def estructura_cfa(assessment_id: UUID, db: Session = Depends(get_db)):
    """Fase 4 - CFA de 1 factor: indices de ajuste (chi2/gl, CFI, TLI, RMSEA, SRMR),
    cargas estandarizadas, AVE y fiabilidad compuesta."""
    try:
        from app.models.assessment import Assessment
        from app.models.course import Course
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        a = db.get(Assessment, assessment_id)
        c = db.get(Course, a.course_id) if a else None
        es_demo = bool(c and getattr(c, "code", None) == "DEMO-PSICO")
        rep = cfa_service.ajuste_cfa(datos["X"], incluir_wlsmv_demo=es_demo)
        for it, num in zip(rep["cargas"], datos["items"]):
            it["pregunta"] = num
        rep["_meta"] = _meta(datos, "cfa")
        return rep
    except Exception:
        logger.error(f"Error en estructura_cfa {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estructura/invarianza-cfa")
def estructura_invarianza_cfa(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                              db: Session = Depends(get_db)):
    """Fase 5 - Invarianza configural entre 2 grupos consentidos: CFA por grupo + congruencia
    de Tucker de las cargas."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        rep = cfa_service.invarianza_configural(np.asarray(d["X"], dtype=float), d["grupo"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en estructura_invarianza_cfa {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/efectos")
def efectos_grupo(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                  db: Session = Depends(get_db)):
    """Fase 7 - Comparacion del puntaje total entre 2 grupos consentidos: t de Welch,
    Mann-Whitney, tamanos de efecto (d de Cohen, g de Hedges) con IC95%, y resumen de
    correlaciones inter-item. Reusa las salvaguardas de equidad (consentimiento, minimo por grupo)."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        X = np.asarray(d["X"], dtype=float)
        total = np.nansum(X, axis=1)
        rep = efectos_service.comparar_grupos(total, d["grupo"], d.get("referencia"), d.get("focal"))
        rep["correlaciones"] = efectos_service.correlaciones_resumen(X)
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en efectos_grupo {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dif")
def psicometria_dif(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                    db: Session = Depends(get_db)):
    """I2 - DIF (Mantel-Haenszel + logistica) entre 2 grupos consentidos. Equidad del item."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        X = np.asarray(d["X"], dtype=float)
        matching = np.nansum(X, axis=1)                # puntaje total como variable de igualacion
        rep = dif_service.analizar_dif(X, d["grupo"], matching, etiqueta_focal=d["focal"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_dif {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/invarianza")
def psicometria_invarianza(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                           db: Session = Depends(get_db)):
    """I8b - Invarianza de medicion de Rasch entre 2 grupos consentidos."""
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo)
        rep = invarianza_service.invarianza_rasch(np.asarray(d["X"], dtype=float), d["grupo"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_invarianza {assessment_id}: {traceback.format_exc()}")
        raise
