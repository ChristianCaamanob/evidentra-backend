"""
Pegamento del cableado Investigador: arma, desde la base, la matriz persona x item que
consumen los motores psicometricos (I1 Rasch, I7 dimensionalidad, I2 DIF, I8 invarianza).

Es la unica pieza nueva de datos del cableado: reune los escaneos validados de una
evaluacion y su pauta, y produce una matriz 0/1 SEUDONIMIZADA (G2). La correccion se
calcula por la version detectada de cada escaneo, de modo que items de distintas versiones
se agrupan correctamente por numero de pregunta.
"""
from __future__ import annotations

import hashlib

import numpy as np

from app.core.errors import conflict, not_found, unprocessable
from app.repositories.answer_key_repo import AnswerKeyRepository
from app.repositories.scan_repo import ScanRepository

answer_key_repo = AnswerKeyRepository()
scan_repo = ScanRepository()

# Lista blanca de variables de agrupacion permitidas para equidad (G4). NO se puede
# agrupar por texto libre ni por identificadores: solo estas, y solo con consentimiento.
GRUPOS_PERMITIDOS = ("sexo", "dependencia")


def _pseudo(valor) -> str:
    """Seudonimo estable de un id (G2): sin identidad, reproducible."""
    return "e:" + hashlib.sha256(str(valor).encode("utf-8")).hexdigest()[:10]


ORIGENES = ("omr", "en_vivo")


def _origen_de(scan) -> str:
    """Origen del escaneo. NULL histórico o sin marca = 'omr' (hoja escaneada)."""
    o = getattr(scan, "origen", None)
    if o:
        return str(o)
    return str((scan.raw_ocr_payload_json or {}).get("origen") or "omr")


def _ruts_de_nomina(db, assessment_id) -> set:
    """RUTs reales del curso de la evaluación. Se deduplica SOLO por estos: un identificador
    que no sea un RUT de la nómina ('desconocido', anónimos 'envivo:...') no es una persona
    conocida y no debe colapsarse con otros."""
    from app.models.assessment import Assessment
    from app.models.student import Student
    asm = db.get(Assessment, assessment_id)
    if asm is None:
        return set()
    return {(st.rut or "").strip() for st in
            db.query(Student).filter(Student.course_id == asm.course_id).all() if st.rut}


def _respondidas(scan) -> int:
    ans = (scan.raw_ocr_payload_json or {}).get("answers") or []
    return sum(1 for a in ans if a not in (None, ""))


def _ts(scan) -> float:
    try:
        return scan.created_at.timestamp() if scan.created_at else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def seleccionar_scans(db, assessment_id, origen: str | None = None) -> dict:
    """Escaneos NO en revisión de la evaluación, filtrados por `origen` (omr|en_vivo|None=ambos)
    y DEDUPLICADOS por alumno REAL de la nómina: si un mismo estudiante tiene más de un escaneo
    del mismo assessment (p.ej. OMR + en vivo, o un re-escaneo), se conserva UNO — el más COMPLETO
    (más respuestas; desempate por más reciente) — para no contarlo dos veces en la psicometría.
    Los identificadores que no son un RUT de la nómina NO se colapsan (cada uno es persona
    distinta). Devuelve {scans, n_omr, n_en_vivo, duplicados_colapsados, origen}."""
    crudos = [s for s in scan_repo.list_by_assessment(db, assessment_id)
              if not getattr(s, "requires_review", False)]
    if origen in ORIGENES:
        crudos = [s for s in crudos if _origen_de(s) == origen]
    n_omr = sum(1 for s in crudos if _origen_de(s) == "omr")
    n_vivo = sum(1 for s in crudos if _origen_de(s) == "en_vivo")
    ruts = _ruts_de_nomina(db, assessment_id)
    mejor: dict = {}
    otros: list = []
    colapsados = 0
    for s in crudos:
        sid = (s.student_identifier or "").strip()
        if sid and sid in ruts:                       # alumno identificado → deduplicable
            prev = mejor.get(sid)
            if prev is None:
                mejor[sid] = s
            else:
                colapsados += 1
                if (_respondidas(s), _ts(s)) > (_respondidas(prev), _ts(prev)):
                    mejor[sid] = s                    # se queda el más completo / más reciente
        else:
            otros.append(s)                           # 'desconocido' / anónimo: no colapsar
    elegidos = list(mejor.values()) + otros
    elegidos.sort(key=lambda s: (_ts(s), str(s.id)))  # orden reproducible
    return {"scans": elegidos, "n_omr": n_omr, "n_en_vivo": n_vivo,
            "duplicados_colapsados": colapsados, "origen": origen or "todos"}


def _matriz_cruda(db, assessment_id, origen: str | None = None) -> dict:
    """
    Armado comun: pauta por version + una fila de correctitud (0/1, NaN si anulada en esa
    version) por cada escaneo NO en revision, conservando el objeto scan (para el vinculo
    con el estudiante en el analisis por grupo). Omitidas -> 0.
    """
    answer_key = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no esta validada; no hay datos para el analisis.")

    por_version: dict[str, dict[int, object]] = {}
    tags: dict[int, dict] = {}
    for it in answer_key.items:
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
        tags.setdefault(it.question_number, {
            "ra": it.learning_outcome_id, "bloom": it.bloom_level, "unidad": it.unidad})

    anulados = {it.question_number for it in answer_key.items if it.is_annulled}
    items = sorted({it.question_number for it in answer_key.items} - anulados)
    if not items:
        raise conflict("Todos los items estan anulados; no hay que analizar.")

    sel = seleccionar_scans(db, assessment_id, origen)
    filas_scan = []
    for scan in sel["scans"]:
        respuestas = (scan.raw_ocr_payload_json or {}).get("answers", [])
        clave = por_version.get((scan.detected_version or "A").upper())
        if not clave:
            continue
        fila = []; celdas = omit = 0
        for q in items:
            item = clave.get(q)
            if item is None or item.is_annulled:
                fila.append(np.nan)
                continue
            elegida = respuestas[q - 1] if (q - 1) < len(respuestas) else None
            celdas += 1
            if elegida is None:
                omit += 1
                fila.append(0.0)
            else:
                fila.append(1.0 if str(elegida).upper() == str(item.correct_answer).upper() else 0.0)
        filas_scan.append({"scan": scan, "fila": fila, "celdas": celdas, "omit": omit})

    return {"items": items, "tags": tags, "filas_scan": filas_scan,
            "n_omr": sel["n_omr"], "n_en_vivo": sel["n_en_vivo"],
            "duplicados_colapsados": sel["duplicados_colapsados"], "origen": sel["origen"]}


def cargar_respuestas_letras(db, assessment_id, origen: str | None = None) -> dict:
    """
    Respuestas a NIVEL DE LETRA (seudonimizadas) para el análisis de distractores / cualitativo.
    Devuelve el insumo de curso_stats_service.analizar_evaluacion:
      {respuestas_alumnos: [{student_id, respuestas:{q->letra|None}}], pauta:{q->letra}, te_tags}.
    Deduplicado por alumno real y filtrable por `origen` (ver seleccionar_scans).
    """
    answer_key = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if not answer_key or not answer_key.is_valid:
        raise conflict("La pauta no esta validada; no hay datos para el analisis.")
    por_version, tags, pauta = {}, {}, {}
    for it in answer_key.items:
        por_version.setdefault(it.version.upper(), {})[it.question_number] = it
    anulados = {it.question_number for it in answer_key.items if it.is_annulled}
    items = sorted({it.question_number for it in answer_key.items} - anulados)
    base_ver = "A" if "A" in por_version else (next(iter(por_version)) if por_version else "A")
    clave_base = por_version.get(base_ver, {})
    for q in items:
        it = clave_base.get(q)
        if it is not None:
            pauta[q] = str(it.correct_answer).upper()
            tags[q] = {"ra": it.learning_outcome_id, "bloom": it.bloom_level, "unidad": it.unidad}
    respuestas_alumnos = []
    for scan in seleccionar_scans(db, assessment_id, origen)["scans"]:
        resp_raw = (scan.raw_ocr_payload_json or {}).get("answers", [])
        clave = por_version.get((scan.detected_version or "A").upper())
        if not clave:
            continue
        respuestas = {}
        for q in items:
            it = clave.get(q)
            if it is None or it.is_annulled:
                continue
            elegida = resp_raw[q - 1] if (q - 1) < len(resp_raw) else None
            respuestas[q] = str(elegida).upper() if elegida else None
        respuestas_alumnos.append({"student_id": _pseudo(scan.id), "respuestas": respuestas})
    return {"respuestas_alumnos": respuestas_alumnos, "pauta": pauta, "te_tags": tags}


def cargar_matriz_respuestas(db, assessment_id, min_personas: int = 3,
                             min_items: int = 3, origen: str | None = None) -> dict:
    """Matriz 0/1 (persona x item) SEUDONIMIZADA (G2) de una evaluacion, mas metadatos.
    `origen`: None = ambos orígenes deduplicados por alumno; 'omr' | 'en_vivo' = solo ese."""
    cruda = _matriz_cruda(db, assessment_id, origen)
    items = cruda["items"]
    filas = [fs["fila"] for fs in cruda["filas_scan"]]
    personas = [_pseudo(fs["scan"].id) for fs in cruda["filas_scan"]]
    n_celdas = sum(fs["celdas"] for fs in cruda["filas_scan"])
    n_omit = sum(fs["omit"] for fs in cruda["filas_scan"])

    X = np.array(filas, dtype=float) if filas else np.empty((0, len(items)))
    if X.shape[0] < min_personas or X.shape[1] < min_items:
        raise conflict(
            f"Datos insuficientes para el analisis (se requieren >= {min_personas} personas "
            f"y >= {min_items} items; hay {X.shape[0]} personas y {X.shape[1]} items validos).")

    return {
        "X": X, "personas": personas, "items": items, "tags": cruda["tags"],
        "n_personas": int(X.shape[0]), "n_items": int(X.shape[1]),
        "omitidas_pct": round(n_omit / n_celdas * 100, 1) if n_celdas else 0.0,
        "n_omr": cruda["n_omr"], "n_en_vivo": cruda["n_en_vivo"],
        "duplicados_colapsados": cruda["duplicados_colapsados"], "origen": cruda["origen"],
    }


def cargar_matriz_con_grupo(db, assessment_id, grupo: str, min_por_grupo: int = 10,
                            origen: str | None = None) -> dict:
    """
    Prepara la matriz 0/1 + la variable de grupo para DIF / invarianza (equidad), aplicando
    las tres salvaguardas de la Ley 21.719:
      - LISTA BLANCA : grupo debe estar en GRUPOS_PERMITIDOS (si no, 422).
      - CONSENTIMIENTO: solo se incluyen estudiantes con consiente_equidad = True (G4).
      - ANTI-REIDENTIFICACION: cada grupo comparado exige >= min_por_grupo estudiantes.
    Si la variable tiene >2 categorias, compara las 2 mayores y declara las omitidas.
    """
    if grupo not in GRUPOS_PERMITIDOS:
        raise unprocessable(
            f"Variable de agrupacion '{grupo}' no permitida. Permitidas (consentidas): "
            f"{', '.join(GRUPOS_PERMITIDOS)}.")

    from app.models.assessment import Assessment
    from app.models.student import Student

    cruda = _matriz_cruda(db, assessment_id, origen)
    assessment = db.get(Assessment, assessment_id)
    por_rut = {}
    if assessment is not None:
        for st in db.query(Student).filter(Student.course_id == assessment.course_id).all():
            por_rut[st.rut] = st

    filas, valores = [], []
    sin_consent = sin_dato = 0
    for fs in cruda["filas_scan"]:
        st = por_rut.get(fs["scan"].student_identifier)
        if st is None or getattr(st, grupo, None) in (None, ""):
            sin_dato += 1
            continue
        if not getattr(st, "consiente_equidad", False):
            sin_consent += 1
            continue
        filas.append(fs["fila"]); valores.append(str(getattr(st, grupo)))

    if not filas:
        raise conflict(
            f"No hay estudiantes con consentimiento y con '{grupo}' registrado para esta evaluacion.")

    X = np.array(filas, dtype=float)
    valores = np.array(valores)
    cats, counts = np.unique(valores, return_counts=True)
    orden = np.argsort(counts)[::-1]
    cats, counts = cats[orden], counts[orden]
    if len(cats) < 2:
        raise conflict(f"Se requieren al menos 2 categorias de '{grupo}' con datos (hay {len(cats)}).")
    if counts[0] < min_por_grupo or counts[1] < min_por_grupo:
        raise conflict(
            f"Cada grupo requiere >= {min_por_grupo} estudiantes para proteger contra "
            f"reidentificacion. Tamanos: {dict(zip(cats.tolist(), counts.tolist()))}.")

    top2 = cats[:2]
    mask = np.isin(valores, top2)
    return {
        "X": X[mask], "grupo": valores[mask].tolist(),
        "referencia": str(top2[0]), "focal": str(top2[1]),
        "variable": grupo, "n": int(mask.sum()),
        "categorias_comparadas": [str(top2[0]), str(top2[1])],
        "categorias_omitidas": [str(c) for c in cats[2:]],
        "excluidos_sin_consentimiento": int(sin_consent),
        "excluidos_sin_dato": int(sin_dato),
    }


def cargar_dina(db, assessment_id, base: str = "ra", min_personas: int = 10,
                origen: str | None = None) -> dict:
    """
    Prepara los insumos de DINA (I9) derivando la Q-matrix del etiquetado C3: cada item
    'carga' en su RA (o nivel Bloom). base in {'ra','bloom'}. Requiere que los items esten
    etiquetados (C3) y al menos 2 atributos distintos.
    """
    datos = cargar_matriz_respuestas(db, assessment_id, origen=origen)
    X, items, tags = datos["X"], datos["items"], datos["tags"]
    etiqueta = {q: (tags.get(q) or {}).get(base) for q in items}
    usados = [i for i, q in enumerate(items) if etiqueta[q]]
    if len(usados) < 3:
        raise conflict(
            f"Faltan etiquetas C3 ({base.upper()}) en los items; DINA las necesita para la "
            f"Q-matrix (hay {len(usados)} items etiquetados). Etiqueta el instrumento en C3.")
    atributos = sorted({etiqueta[items[i]] for i in usados})
    if len(atributos) < 2:
        raise conflict("Se requieren al menos 2 atributos (RA/Bloom distintos) para el diagnostico.")

    Xr = X[:, usados]
    fila_ok = ~np.isnan(Xr).any(axis=1)          # DINA requiere respuestas completas
    Xr = Xr[fila_ok]
    if Xr.shape[0] < min_personas:
        raise conflict(f"Datos insuficientes para DINA (se requieren >= {min_personas} "
                       f"estudiantes con respuestas completas; hay {Xr.shape[0]}).")

    idx_attr = {a: k for k, a in enumerate(atributos)}
    Q = np.zeros((len(usados), len(atributos)))
    for r, i in enumerate(usados):
        Q[r, idx_attr[etiqueta[items[i]]]] = 1.0

    return {"X": Xr, "Q": Q, "atributos": atributos,
            "items": [items[i] for i in usados], "n_personas": int(Xr.shape[0]),
            "base": base}


def cargar_registros_validacion(db, assessment_id, min_registros: int = 3) -> list[dict]:
    """
    Lee los RegistroValidacion persistidos (F3) de una evaluacion y los devuelve en el
    formato que consumen R, MFRM y F4. El 'alumno' sale seudonimizado del respuesta_ref
    (formato 'e:<hash>#<criterio>'), nunca de un identificador real (G2).
    """
    from app.models.validacion import RegistroValidacion
    from app.services.rubrica_escala_service import nivel_canonico

    filas = (db.query(RegistroValidacion)
             .filter(RegistroValidacion.assessment_id == str(assessment_id))
             .all())
    if len(filas) < min_registros:
        raise conflict(
            f"Aun no hay suficientes validaciones docentes para esta evaluacion "
            f"(hay {len(filas)}; se requieren >= {min_registros}). Corre F3 primero.")

    # Escala propia de cada criterio -> para normalizar niveles arbitrarios (p. ej.
    # Excelente/Bueno/Regular/Deficiente) a la escala canonica de 3 que consumen R y MFRM.
    niveles_por_crit = {}
    ak = answer_key_repo.get_by_assessment_id(db, assessment_id)
    if ak:
        for it in ak.items:
            for c in it.rubric_criteria:
                niveles_por_crit.setdefault(c.name, c.niveles_json)

    out = []
    for r in filas:
        alumno = str(r.respuesta_ref).split("#")[0]
        niv = niveles_por_crit.get(r.criterio)
        out.append({"alumno": alumno, "criterio": r.criterio,
                    "nivel_ia": r.nivel_ia, "confianza_ia": r.confianza_ia,
                    "nivel_docente": r.nivel_docente, "accion": r.accion,
                    # canonicos (3 niveles) para la psicometria; los crudos quedan para F4.
                    "nivel_ia_canon": nivel_canonico(niv, r.nivel_ia),
                    "nivel_docente_canon": nivel_canonico(niv, r.nivel_docente),
                    "comentario": r.comentario, "respuesta_ref": r.respuesta_ref})
    return out


def cargar_criterios_item(db, answer_key_item_id) -> list[dict]:
    """
    Carga los criterios de rubrica (con sus anclas) de un item, en el formato que consume
    F2 (precalificacion_service) y F4 (aprendizaje_service). Incluye 'name' y 'nombre' por
    compatibilidad con ambos motores.
    """
    from app.models.answer_key import AnswerKeyItem

    item = db.get(AnswerKeyItem, answer_key_item_id)
    if not item:
        raise not_found("Item de pauta no encontrado.")
    criterios = []
    for c in sorted(item.rubric_criteria, key=lambda x: x.order):
        anclas = [{"texto": a.texto, "nivel": a.nivel}
                  for a in sorted(c.anclas, key=lambda x: x.order)]
        criterios.append({
            "name": c.name, "nombre": c.name, "weight": float(c.weight),
            "nivel_exigencia": c.nivel_exigencia, "sinonimos": c.sinonimos_json or [],
            "umbral_confianza": float(c.umbral_confianza), "anclas": anclas,
        })
    return criterios


def cargar_criterios_rubrica(db, answer_key_id) -> list[dict]:
    """Todos los criterios de la rubrica de una pauta (a lo largo de sus items), para versionar."""
    from app.models.answer_key import AnswerKey

    ak = db.get(AnswerKey, answer_key_id)
    if not ak:
        raise not_found("Pauta no encontrada.")
    criterios = []
    for item in ak.items:
        criterios.extend(cargar_criterios_item(db, item.id))
    return criterios


def version_activa_hash(db, answer_key_id, criterios: list[dict]) -> str:
    """Hash de la version de rubrica ACTIVA (pinning). Si no hay versiones, el hash del
    contenido actual (v1 implicita)."""
    from app.models.aprendizaje import RubricaVersion
    from app.services.aprendizaje_service import hash_criterios

    activa = (db.query(RubricaVersion)
              .filter(RubricaVersion.answer_key_id == str(answer_key_id),
                      RubricaVersion.estado == "activa")
              .order_by(RubricaVersion.version.desc()).first())
    return activa.hash if activa else hash_criterios(criterios)
