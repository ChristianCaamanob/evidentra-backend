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
import re
import traceback
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fastapi import Depends as _Dep
from app.api.deps import get_db, req_investigador, req_lectura_datos
from app.services import exportador_service
from app.services import matriz_service
from app.services import psico_cache
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
from app.services import meta_analisis_service
from app.services import manuscrito_service

# Todo el modulo Investigador exige rol investigador (o creador). El director NO accede a
# este modulo de investigacion; su alcance es ver/exportar datos de estudiante y profesor.
router = APIRouter(prefix="/assessments", tags=["investigador"],
                   dependencies=[_Dep(req_investigador)])
logger = logging.getLogger("evalys")


def _meta(datos: dict, tecnica: str | None = None) -> dict:
    m = {"n_personas": datos["n_personas"], "n_items": datos["n_items"],
         "omitidas_pct": datos["omitidas_pct"],
         "gobernanza": "Analisis agregado y seudonimizado (G2); no altera notas (G1)."}
    # Composición de la evidencia (transparencia: la deduplicación por alumno no es silenciosa).
    if "n_omr" in datos:
        m["composicion"] = {
            "origen": datos.get("origen", "todos"),
            "escaneos_omr": datos.get("n_omr", 0),
            "escaneos_en_vivo": datos.get("n_en_vivo", 0),
            "duplicados_colapsados": datos.get("duplicados_colapsados", 0),
        }
    if tecnica:
        m["poder_muestral"] = poder_muestral_service.evaluar(
            tecnica, datos["n_personas"], datos["n_items"])
    return m


def _origen_ok(origen):
    """Valida el filtro de origen de la evidencia. None/''/'todos' = ambos (deduplicado)."""
    if origen in (None, "", "todos"):
        return None
    if origen not in matriz_service.ORIGENES:
        from app.core.errors import unprocessable
        raise unprocessable("origen inválido (usa 'omr' | 'en_vivo', u omite para ambos).")
    return origen


def _ck(clave: str, origen):
    """Clave de caché que separa por origen (evita servir un origen por otro)."""
    return clave + (":" + origen if origen else "")


@router.get("/{assessment_id}/psicometria/rasch")
def psicometria_rasch(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """I1 - Modelo de Rasch (dificultad, habilidad, ajuste, informacion, fiabilidad).
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id, origen=org)
        rep = irt_service.estimar_rasch(datos["X"])
        for it, num in zip(rep["items"], datos["items"]):
            it["pregunta"] = num                       # numero real de pregunta (no indice)
        rep["_meta"] = _meta(datos, "rasch")
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("rasch", org), _c)
    except Exception:
        logger.error(f"Error en psicometria_rasch {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estadistica/clasica")
def estadistica_clasica(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """Fases 1-2 del pipeline: depuracion de datos (descriptivos, supuestos, perdidos) y
    analisis de items en Teoria Clasica (dificultad, discriminacion, fiabilidad: alfa, omega,
    SEM, Guttman). Numera los items con su pregunta real.
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id, origen=org)
        rep = estadistica_service.reporte_completo(datos["X"])
        nums = datos["items"]
        for bloque in (rep["descriptivos"]["items"], rep["items_tct"]["items"],
                       rep["datos_perdidos"]["por_item"]):
            for it, num in zip(bloque, nums):
                it["pregunta"] = num
        rep["_meta"] = _meta(datos, "clasica")
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("clasica", org), _c)
    except Exception:
        logger.error(f"Error en estadistica_clasica {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/cualitativo")
def analisis_cualitativo(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db),
                         _: object = _Dep(req_investigador)):
    """I4 - Análisis cualitativo: mapa de concepciones erróneas (puente cuanti->cuali).
    Cada distractor con prevalencia >= umbral revela una concepción errónea específica,
    con severidad y RA afectado. Trabaja sobre respuestas seudonimizadas (G2).
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        datos = matriz_service.cargar_respuestas_letras(db, assessment_id, origen=org)
        resultado = curso_stats_service.analizar_evaluacion(
            datos["respuestas_alumnos"], datos["pauta"], te_tags=datos["te_tags"])
        items_ctt = resultado.get("items", [])
        n_personas = resultado["instrumento"]["n_alumnos"]
        mapa = cualitativo_service.mapa_concepciones(items_ctt, contenido={})
        jd = cualitativo_service.joint_display(mapa.get("concepciones", []), items_ctt, n_personas)
        return {"mapa_concepciones": mapa,
                "joint_display": jd,
                "_meta": {"n_personas": n_personas,
                          "n_items": resultado["instrumento"]["n_items"]}}
    try:
        return psico_cache.memo(db, assessment_id, _ck("cualitativo", org), _c)
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


class RelevanciaPeticion(BaseModel):
    pregunta: str = Field(..., min_length=2)
    titulo: str = Field(..., min_length=2)
    abstract: str = ""
    meta: dict | None = None


@router.post("/investigacion/relevancia")
def relevancia(body: RelevanciaPeticion, _: object = _Dep(req_investigador)):
    """'¿Por qué considerar este artículo?': sugerencia de relevancia fundamentada en el abstract
    real (título + abstract de OpenAlex) frente a la pregunta/línea del estudio. No inventa
    hallazgos; si no conecta, lo dice. Cae a heurística determinista sin clave de IA."""
    from app.services import relevancia_service
    try:
        return relevancia_service.sugerir(body.pregunta, body.titulo, body.abstract, body.meta)
    except Exception:
        logger.error(f"Error en relevancia: {traceback.format_exc()}")
        raise


@router.get("/investigacion/cobertura")
def cobertura(q: str = Query(..., min_length=2), anios: int = Query(0, ge=0, le=50),
              _: object = _Dep(req_investigador)):
    """Embudo de cobertura: cuántos resultados hay para la línea en cada gran fuente ABIERTA
    (OpenAlex · PubMed/MEDLINE · Crossref · DOAJ). Responde '¿son todos los disponibles?'."""
    try:
        return literatura_service.cobertura(q, anios=(anios or None))
    except Exception:
        logger.error(f"Error en cobertura '{q}': {traceback.format_exc()}")
        raise


class MetaEstudio(BaseModel):
    label: str | None = None
    # efecto ya calculado (opcional):
    y: float | None = None
    v: float | None = None
    # o datos crudos según la medida:
    m1: float | None = None; sd1: float | None = None; n1: float | None = None
    m2: float | None = None; sd2: float | None = None; n2: float | None = None
    e1: float | None = None; e2: float | None = None
    r: float | None = None; n: float | None = None
    grupo: str | None = None          # para análisis por subgrupos
    moderador: float | None = None    # para metarregresión


class MetaPeticion(BaseModel):
    medida: str = Field("smd", pattern="^(smd|or|z)$")
    estudios: list[MetaEstudio] = Field(min_length=2, max_length=500)


@router.post("/investigacion/meta-analisis")
def meta_analisis(body: MetaPeticion, _: object = _Dep(req_investigador)):
    """Metaanálisis de efectos aleatorios (DerSimonian-Laird + Hartung-Knapp): efecto combinado,
    heterogeneidad (Q, I², τ², intervalo de predicción), Egger (sesgo de publicación), datos de
    forest/funnel y señales GRADE. `medida`: smd (Hedges g) | or (ln OR) | z (Fisher). Cómputo
    nativo Python; metafor como referencia de contraste. Independiente de los datos del docente."""
    try:
        estudios = [e.model_dump(exclude_none=True) for e in body.estudios]
        return meta_analisis_service.sintetizar(estudios, body.medida)
    except Exception:
        logger.error(f"Error en meta_analisis: {traceback.format_exc()}")
        raise


class AnalizarDatosPeticion(BaseModel):
    matriz: list[list[float]] | None = None          # 0/1 persona×ítem (dataset importado)
    assessment_ids: list[UUID] | None = None         # pooling de evaluaciones del MISMO instrumento
    grupo: list[str] | None = None                   # opcional, para efectos/DIF (solo con matriz)


@router.post("/investigacion/analizar-datos")
def analizar_datos(body: AnalizarDatosPeticion, db: Session = Depends(get_db),
                   _: object = _Dep(req_investigador)):
    """Corre las técnicas psicométricas sobre una matriz de respuestas 0/1, provista de dos
    formas: `assessment_ids` (POOLING de evaluaciones del mismo instrumento — se concatenan las
    filas si el nº de ítems coincide) o `matriz` (dataset EXTERNO importado). Devuelve TCT +
    fiabilidad, dimensionalidad, Rasch, poder muestral, y efectos/DIF si se da `grupo`."""
    from app.core.errors import conflict, unprocessable
    grupo = None
    if body.assessment_ids:
        mats, ncols = [], set()
        for aid in body.assessment_ids:
            d = matriz_service.cargar_matriz_respuestas(db, aid)
            mats.append(d["X"]); ncols.add(int(d["X"].shape[1]))
        if len(ncols) != 1:
            raise conflict(f"No combinables: distinto nº de ítems {sorted(ncols)}. El pooling "
                           "solo agrupa evaluaciones del MISMO instrumento.")
        X = np.vstack(mats)
        fuente = f"pooling de {len(mats)} evaluación(es)"
    elif body.matriz:
        try:
            X = np.array(body.matriz, dtype=float)
        except Exception:
            raise unprocessable("La matriz debe ser numérica (0/1).")
        if X.ndim != 2:
            raise unprocessable("La matriz debe ser 2D (personas × ítems).")
        if X.shape[0] > 5000 or X.shape[1] > 300:
            raise unprocessable("Máximo 5000 personas × 300 ítems.")
        vals = set(np.unique(X[~np.isnan(X)]).tolist())
        if not vals.issubset({0.0, 1.0}):
            raise unprocessable("Solo se admiten valores 0/1 (dicotómicos) o vacíos.")
        grupo = body.grupo if (body.grupo and len(body.grupo) == X.shape[0]) else None
        fuente = "dataset importado"
    else:
        raise unprocessable("Proporciona 'matriz' o 'assessment_ids'.")

    if X.shape[0] < 3 or X.shape[1] < 3:
        raise conflict("Se requieren ≥ 3 personas y ≥ 3 ítems.")
    n, k = int(X.shape[0]), int(X.shape[1])
    out = {
        "fuente": fuente, "n": n, "n_items": k,
        "fiabilidad": {"alfa": estadistica_service.alfa_cronbach(X).get("alfa"),
                       "omega": estadistica_service.omega_mcdonald(X).get("omega"),
                       "sem": estadistica_service.sem(X).get("sem")},
        "dimensionalidad": dimensionalidad_service.analizar_dimensionalidad(X, dicotomico=True),
        "rasch": irt_service.estimar_rasch(X),
        "poder_muestral": {
            "rasch": poder_muestral_service.evaluar("rasch", n, k),
            "dimensionalidad": poder_muestral_service.evaluar("dimensionalidad", n, k),
        },
    }
    if grupo is not None:
        try:
            total = np.nansum(X, axis=1)
            out["efectos"] = efectos_service.comparar_grupos(total, grupo)
            out["dif"] = dif_service.analizar_dif(X, grupo, total)
        except Exception:
            out["efectos_error"] = "No se pudo analizar el grupo (revisa el vector 'grupo')."
    return out


class ManuscritoPeticion(BaseModel):
    tipo: str = Field("revision", pattern="^(revision|datos)$")
    hechos: dict = Field(default_factory=dict)
    capitulo: str | None = None       # si viene, redacta SOLO ese capítulo en profundidad


@router.post("/investigacion/manuscrito")
def manuscrito(body: ManuscritoPeticion, _: object = _Dep(req_investigador)):
    """Genera el manuscrito. Con `capitulo` (meta|introduccion|marco_teorico|metodos|resultados|
    discusion|conclusiones|limitaciones|etica|aporta) redacta SOLO ese capítulo en profundidad
    (artículo largo por capítulos). Sin `capitulo`, devuelve el IMRaD completo en una pasada.
    Anclado a cifras reales; PRISMA 2020 (revisión) o COSMIN (validación)."""
    try:
        if body.capitulo:
            return manuscrito_service.redactar_capitulo(body.hechos, body.tipo, body.capitulo)
        return manuscrito_service.redactar_imrad(body.hechos, body.tipo)
    except Exception:
        logger.error(f"Error en manuscrito: {traceback.format_exc()}")
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


@router.post("/investigacion/proponer-sesgo")
def proponer_sesgo(payload: dict):
    """PROPONE el riesgo de sesgo RoB 2 (5 dominios + global) desde título+abstract. La IA propone;
    el investigador valida y corrige cada dominio (G1)."""
    from app.services import investigador_ia_service as iia
    return iia.proponer_sesgo(payload.get("titulo", ""), payload.get("abstract", ""))


@router.post("/investigacion/extraer-efecto")
def extraer_efecto(payload: dict):
    """EXTRAE del abstract los estadísticos del tamaño de efecto (M/DE/N, eventos/n o r/n) para el
    metaanálisis. Solo lo explícito; ausentes → null. El investigador verifica antes de calcular (G1)."""
    from app.services import investigador_ia_service as iia
    return iia.extraer_efecto(payload.get("titulo", ""), payload.get("abstract", ""),
                              (payload.get("medida") or "smd"))


@router.get("/investigacion/openalex-plan")
def openalex_plan(q: str = Query(..., min_length=2), anios: int = Query(0, ge=0, le=50),
                  limite: int = Query(150, ge=10, le=300)):
    """Devuelve la URL base + parámetros para que el NAVEGADOR consulte OpenAlex directamente (con la
    IP del usuario, presupuesto de créditos propio). Evita el throttling de la IP compartida de Render."""
    import datetime as _dt
    desde = (_dt.date.today().year - anios + 1) if anios else None
    filtros = ["type:article|review|book-chapter"]
    if desde:
        filtros.append(f"from_publication_date:{desde}-01-01")
    return {"base": "https://api.openalex.org/works", "select": literatura_service._OA_SELECT,
            "filter": ",".join(filtros), "per_page": 100, "mailto": literatura_service._MAILTO,
            "desde_anio": desde, "limite": min(max(limite, 10), 300)}


@router.post("/investigacion/corpus-enriquecer")
def corpus_enriquecer(payload: dict):
    """Recibe trabajos CRUDOS de OpenAlex (traídos por el navegador) y los parsea + formatea citas +
    añade cuartil SJR por ISSN, SIN llamar a OpenAlex. Base del corpus con factor de impacto/indexación."""
    try:
        return literatura_service.enriquecer_works(
            payload.get("works") or [], payload.get("query") or "",
            payload.get("desde_anio"), payload.get("total_disponible"))
    except Exception:
        logger.error(f"Error en corpus-enriquecer: {traceback.format_exc()}")
        raise


@router.post("/investigacion/proponer-appraisal")
def proponer_appraisal(payload: dict):
    """Propone la valoración crítica (JBI por diseño o RoB 2) ítem por ítem desde el texto. G1."""
    from app.services import investigador_ia_service as iia
    return iia.proponer_appraisal(payload.get("tool") or "", payload.get("items") or [],
                                  payload.get("titulo") or "", payload.get("texto") or "")


@router.post("/investigacion/sintesis-resultados")
def sintesis_resultados(payload: dict):
    """Síntesis narrativa (IA) del capítulo de Resultados de una RS+meta, anclada a las cifras del
    metaanálisis + riesgo de sesgo. El investigador valida (G1)."""
    from app.services import investigador_ia_service as iia
    return iia.sintetizar_resultados(payload.get("meta") or {}, payload.get("rob"), payload.get("contexto") or "")


@router.post("/investigacion/experimental/analizar")
def experimental_analizar(payload: dict):
    """Arsenal cuantitativo del estudio experimental sobre un dataset {columns, rows}:
    descriptivos | supuestos | comparacion | correlacion | regresion. Estadígrafos + tamaño de efecto
    + reporte APA. El investigador elige el análisis; el motor calcula (no decide)."""
    from app.services import experimental_stats_service as ex
    return ex.analizar(payload)


@router.post("/investigacion/experimental/interpretar")
def experimental_interpretar(payload: dict):
    """Interpretación en prosa (estilo estadígrafo senior) de un resultado de análisis; propone la
    lectura y sus reservas. El investigador valida (G1). Sin clave IA → disponible=False."""
    from app.services import investigador_ia_service as iia
    return iia.interpretar_analisis(payload.get("resultado") or {}, payload.get("contexto") or "")


@router.get("/{assessment_id}/psicometria/dimensionalidad")
def psicometria_dimensionalidad(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """I7 - Dimensionalidad (KMO, Bartlett, analisis paralelo, EFA) + fiabilidad ampliada.
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id, origen=org)
        rep = dimensionalidad_service.analizar_dimensionalidad(datos["X"], dicotomico=True)
        rep["_meta"] = _meta(datos, "dimensionalidad")
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("dimensionalidad", org), _c)
    except Exception:
        logger.error(f"Error en psicometria_dimensionalidad {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dina")
def psicometria_dina(assessment_id: UUID, base: str = Query("ra", pattern="^(ra|bloom)$"),
                     origen: str | None = None, db: Session = Depends(get_db)):
    """I9 - Diagnostico cognitivo (DINA). La Q-matrix se deriva del etiquetado C3: cada
    item carga en su RA (base=ra) o nivel Bloom (base=bloom).
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        d = matriz_service.cargar_dina(db, assessment_id, base=base, origen=org)
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
    try:
        return psico_cache.memo(db, assessment_id, _ck("dina:" + base, org), _c)
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
        if c and getattr(c, "name", None):
            hechos["titulo"] = f"Evidencia de validez y fiabilidad: {c.name}"
        ms = manuscrito_service.redactar_imrad(hechos, "datos")   # IMRaD completo (COSMIN)
        return {"hechos": hechos, "manuscrito": ms, "motor": ms.get("motor"),
                "checklist": reporte_service.checklist_cosmin(hechos),
                "_meta": _meta(datos, "cfa")}
    except Exception:
        logger.error(f"Error en reporte {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/tri")
def psicometria_tri(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """Fase 3 - TRI: compara 1PL vs 2PL (AIC/BIC), parametros 2PL (discriminacion/dificultad)
    e independencia local (Q3 de Yen). Estimacion MML con girth.
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id, origen=org)
        rep = tri_service.comparar_modelos(datos["X"])
        for it, num in zip(rep["items_2PL"], datos["items"]):
            it["pregunta"] = num
        rep["_meta"] = _meta(datos, "tri")
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("tri", org), _c)
    except Exception:
        logger.error(f"Error en psicometria_tri {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estructura/cfa")
def estructura_cfa(assessment_id: UUID, origen: str | None = None, db: Session = Depends(get_db)):
    """Fase 4 - CFA de 1 factor: indices de ajuste (chi2/gl, CFI, TLI, RMSEA, SRMR),
    cargas estandarizadas, AVE y fiabilidad compuesta.
    origen: omr | en_vivo | (omitir = ambos, deduplicado por alumno)."""
    org = _origen_ok(origen)
    def _c():
        from app.models.assessment import Assessment
        from app.models.course import Course
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id, origen=org)
        a = db.get(Assessment, assessment_id)
        c = db.get(Course, a.course_id) if a else None
        es_demo = bool(c and getattr(c, "code", None) == "DEMO-PSICO")
        rep = cfa_service.ajuste_cfa(datos["X"], incluir_wlsmv_demo=es_demo)
        for it, num in zip(rep["cargas"], datos["items"]):
            it["pregunta"] = num
        rep["_meta"] = _meta(datos, "cfa")
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("cfa", org), _c)
    except Exception:
        logger.error(f"Error en estructura_cfa {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/estructura/invarianza-cfa")
def estructura_invarianza_cfa(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                              origen: str | None = None, db: Session = Depends(get_db)):
    """Fase 5 - Invarianza configural entre 2 grupos consentidos: CFA por grupo + congruencia
    de Tucker de las cargas. origen: omr | en_vivo | (omitir = ambos)."""
    org = _origen_ok(origen)
    def _c():
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo, origen=org)
        rep = cfa_service.invarianza_configural(np.asarray(d["X"], dtype=float), d["grupo"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("invcfa:" + grupo, org), _c)
    except Exception:
        logger.error(f"Error en estructura_invarianza_cfa {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/efectos")
def efectos_grupo(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                  origen: str | None = None, db: Session = Depends(get_db)):
    """Fase 7 - Comparacion del puntaje total entre 2 grupos consentidos: t de Welch,
    Mann-Whitney, tamanos de efecto (d de Cohen, g de Hedges) con IC95%, y resumen de
    correlaciones inter-item. Reusa las salvaguardas de equidad (consentimiento, minimo por grupo).
    origen: omr | en_vivo | (omitir = ambos)."""
    org = _origen_ok(origen)
    def _c():
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo, origen=org)
        X = np.asarray(d["X"], dtype=float)
        total = np.nansum(X, axis=1)
        rep = efectos_service.comparar_grupos(total, d["grupo"], d.get("referencia"), d.get("focal"))
        rep["correlaciones"] = efectos_service.correlaciones_resumen(X)
        rep["_meta"] = _meta_equidad(d)
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("efectos:" + grupo, org), _c)
    except Exception:
        logger.error(f"Error en efectos_grupo {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/dif")
def psicometria_dif(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                    origen: str | None = None, db: Session = Depends(get_db)):
    """I2 - DIF (Mantel-Haenszel + logistica) entre 2 grupos consentidos. Equidad del item.
    origen: omr | en_vivo | (omitir = ambos)."""
    org = _origen_ok(origen)
    def _c():
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo, origen=org)
        X = np.asarray(d["X"], dtype=float)
        matching = np.nansum(X, axis=1)                # puntaje total como variable de igualacion
        rep = dif_service.analizar_dif(X, d["grupo"], matching, etiqueta_focal=d["focal"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    try:
        return psico_cache.memo(db, assessment_id, _ck("dif:" + grupo, org), _c)
    except Exception:
        logger.error(f"Error en psicometria_dif {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/{assessment_id}/psicometria/invarianza")
def psicometria_invarianza(assessment_id: UUID, grupo: str = Query(..., pattern="^(sexo|dependencia)$"),
                           origen: str | None = None, db: Session = Depends(get_db)):
    """I8b - Invarianza de medicion de Rasch entre 2 grupos consentidos.
    origen: omr | en_vivo | (omitir = ambos)."""
    org = _origen_ok(origen)
    try:
        d = matriz_service.cargar_matriz_con_grupo(db, assessment_id, grupo, origen=org)
        rep = invarianza_service.invarianza_rasch(np.asarray(d["X"], dtype=float), d["grupo"])
        rep["_meta"] = _meta_equidad(d)
        return rep
    except Exception:
        logger.error(f"Error en psicometria_invarianza {assessment_id}: {traceback.format_exc()}")
        raise
