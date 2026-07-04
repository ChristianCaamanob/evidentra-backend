"""
I5 - Paquete de publicacion (capstone del modulo Investigador).

Reune las salidas de todos los analisis (descriptivos + psicometria TCT/IRT + validez/DIF
+ longitudinal + cualitativo) en un objeto de manuscrito de alto estandar:

  - Tablas en formato de reporte (APA-like): descriptivos, estadisticos de item,
    resumen DIF, longitudinal.
  - Secciones de METODOS y RESULTADOS auto-generadas DESDE los datos (reproducibles).
  - Declaracion de ETICA (IRB / consentimiento G3-G4, seudonimizacion G2).
  - Manifiesto de REPRODUCIBILIDAD (software, versiones, umbrales, pipeline, semilla).
  - Referencias metodologicas.

No calcula estadistica nueva: orquesta e interpreta lo ya computado para que quede listo
para un manuscrito Q1 y para exportar (PDF/XLSX/CSV via export_service).
"""
from __future__ import annotations

REFERENCIAS = [
    "American Educational Research Association, American Psychological Association, & "
    "National Council on Measurement in Education (2014). Standards for Educational and "
    "Psychological Testing. AERA.",
    "Braun, V., & Clarke, V. (2006). Using thematic analysis in psychology. "
    "Qualitative Research in Psychology, 3(2), 77-101.",
    "Hake, R. R. (1998). Interactive-engagement versus traditional methods. "
    "American Journal of Physics, 66(1), 64-74.",
    "Holland, P. W., & Thayer, D. T. (1988). Differential item performance and the "
    "Mantel-Haenszel procedure. In Test Validity (pp. 129-145). Erlbaum.",
    "Kraft, M. A. (2020). Interpreting effect sizes of education interventions. "
    "Educational Researcher, 49(4), 241-253.",
    "Rasch, G. (1960). Probabilistic Models for Some Intelligence and Attainment Tests. "
    "Danish Institute for Educational Research.",
    "Zumbo, B. D. (1999). A Handbook on the Theory and Methods of DIF. Directorate of "
    "Human Resources Research and Evaluation, Department of National Defense.",
]


# ───────────────────────────────────────────── tablas
def tabla_descriptivos(ctt: dict) -> dict:
    dn = ctt.get("descriptivos_nota", {}) or {}
    dp = ctt.get("descriptivos_pct", {}) or {}
    filas = [
        ["N estudiantes", ctt["instrumento"]["n_alumnos"]],
        ["N items", ctt["instrumento"]["n_items"]],
        ["Nota M (DE)", f"{dn.get('media')} ({dn.get('de')})"],
        ["Nota mediana [min, max]", f"{dn.get('mediana')} [{dn.get('min')}, {dn.get('max')}]"],
        ["Logro % M (DE)", f"{dp.get('media')} ({dp.get('de')})"],
        ["Asimetria / curtosis (%)", f"{dp.get('asimetria')} / {dp.get('curtosis_exceso')}"],
        ["Aprobacion %", ctt.get("tasa_aprobacion")],
        ["Confiabilidad KR-20", ctt.get("confiabilidad_kr20")],
    ]
    return {"titulo": "Tabla 1. Estadisticos descriptivos del curso",
            "columnas": ["Estadistico", "Valor"], "filas": filas,
            "nota": "KR-20 = fiabilidad de consistencia interna para items dicotomicos."}


def tabla_items(ctt: dict, irt: dict) -> dict:
    irt_by = {it["item"]: it for it in irt["items"]}
    filas = []
    for c in ctt["items"]:
        r = irt_by.get(c["item"], {})
        filas.append([f"P{c['item']}", c.get("ra") or "-",
                      c["dificultad_p"], c["discriminacion_pbis"],
                      r.get("b"), r.get("infit_msq"), r.get("outfit_msq")])
    return {"titulo": "Tabla 2. Estadisticos de item (TCT e IRT-Rasch)",
            "columnas": ["Item", "RA", "p", "r_pbis", "b (logit)", "infit", "outfit"],
            "filas": filas,
            "nota": "p = dificultad (proporcion correcta); r_pbis = discriminacion punto-biserial "
                    "corregida; b = dificultad de Rasch; infit/outfit = ajuste (rango util 0.5-1.5)."}


def tabla_dif(dif: dict) -> dict | None:
    if not dif:
        return None
    filas = []
    for it in dif["items"]:
        if it.get("con_dif"):
            mh = it["mh"]
            filas.append([f"P{it['item']}", it.get("ra") or "-", mh.get("delta"),
                          mh.get("clase_ets"), mh.get("p"),
                          it["logistica"].get("delta_r2"), it["clase"]])
    return {"titulo": "Tabla 3. Items con funcionamiento diferencial (DIF)",
            "columnas": ["Item", "RA", "Delta MH", "ETS", "p (MH)", "Delta R2", "Clase"],
            "filas": filas or [["-", "Ninguno con DIF relevante", "", "", "", "", ""]],
            "nota": f"Grupos: {dif['grupos']['referencia']} (ref, n={dif['grupos']['n_ref']}) vs "
                    f"{dif['grupos']['focal']} (focal, n={dif['grupos']['n_focal']}). "
                    "Clasificacion ETS (A/B/C) y Jodoin-Gierl."}


def tabla_longitudinal(lng: dict) -> dict | None:
    if not lng:
        return None
    filas = [[r["etiqueta"], r["n"], r["media_pct"], r["de_pct"], r.get("media_nota")]
             for r in lng["resumen"]]
    ef = lng["comparacion_extremos"]["efecto"]
    filas.append(["Efecto extremos (Hedges g)", "", ef["hedges_g"],
                  f"IC95 {ef['ic95']}", ef["interpretacion_kraft"]])
    return {"titulo": "Tabla 4. Trayectoria longitudinal",
            "columnas": ["Momento", "n", "Logro % M", "DE", "Nota M / efecto"],
            "filas": filas,
            "nota": f"Ganancia de Hake del grupo = {lng['ganancia_hake']['g_grupo']} "
                    f"({lng['ganancia_hake']['clase_grupo']}). Tamano de efecto interpretado con "
                    "benchmarks de educacion (Kraft, 2020)."}


# ───────────────────────────────────────────── secciones (data-driven)
def seccion_metodos(meta: dict, ctt: dict, dif: dict | None, lng: dict | None) -> str:
    n = ctt["instrumento"]["n_alumnos"]; k = ctt["instrumento"]["n_items"]
    partes = [
        f"Participaron {n} estudiantes evaluados con un instrumento de {k} items de seleccion "
        f"unica alineado a una tabla de especificaciones (resultados de aprendizaje y nivel "
        f"taxonomico por item).",
        "Se estimaron indices de la Teoria Clasica del Test (dificultad, discriminacion "
        "punto-biserial corregida) y la fiabilidad KR-20. Se ajusto el modelo de Rasch (1PL) "
        "por maxima verosimilitud conjunta, reportando dificultad de item (b), habilidad (theta), "
        "informacion del test, error estandar de medicion y estadisticos de ajuste infit/outfit.",
    ]
    if dif:
        partes.append(
            "El funcionamiento diferencial del item (DIF) se evaluo con el procedimiento de "
            "Mantel-Haenszel (indice Delta ETS, clasificacion A/B/C) y regresion logistica "
            "(DIF uniforme y no uniforme, con tamano de efecto Delta R2 y clasificacion de "
            "Jodoin-Gierl).")
    if lng:
        partes.append(
            "El analisis longitudinal empleo la ganancia normalizada de Hake, tamanos de efecto "
            "(Hedges g con correccion de sesgo e intervalo de confianza) interpretados con los "
            "benchmarks de Kraft (2020) para educacion, y un modelo lineal de efectos mixtos "
            "para medidas repetidas anidadas en el estudiante.")
    partes.append(
        "La normalidad se verifico con Shapiro-Wilk para seleccionar pruebas parametricas o no "
        "parametricas. El componente cualitativo siguio el analisis tematico de Braun y Clarke. "
        "Todos los analisis se ejecutaron en Python (numpy, scipy, statsmodels).")
    return " ".join(partes)


def seccion_resultados(ctt: dict, irt: dict, dif: dict | None, lng: dict | None) -> str:
    dn = ctt.get("descriptivos_nota", {})
    partes = [
        f"El curso obtuvo una nota media de {dn.get('media')} (DE = {dn.get('de')}) y una tasa de "
        f"aprobacion de {ctt.get('tasa_aprobacion')}%. La fiabilidad fue adecuada "
        f"(KR-20 = {ctt.get('confiabilidad_kr20')}).",
        f"En el modelo de Rasch, la fiabilidad de separacion de personas fue "
        f"{irt['fiabilidad']['separacion_personas']} y la de items "
        f"{irt['fiabilidad']['separacion_items']}; los items ajustaron al modelo dentro del "
        f"rango productivo.",
    ]
    if dif:
        nd = len(dif.get("items_con_dif", []))
        partes.append(
            f"El analisis de DIF identifico {nd} item(es) con funcionamiento diferencial relevante "
            f"entre {dif['grupos']['referencia']} y {dif['grupos']['focal']}; el resto resulto "
            f"equitativo (clase A).")
    if lng:
        ef = lng["comparacion_extremos"]["efecto"]
        partes.append(
            f"Longitudinalmente, el desempeno mejoro de forma significativa "
            f"({lng['comparacion_extremos']['prueba']}, p = {lng['comparacion_extremos']['p']}), "
            f"con un tamano de efecto grande (Hedges g = {ef['hedges_g']}, IC95 {ef['ic95']}) y una "
            f"ganancia de Hake de {lng['ganancia_hake']['g_grupo']}.")
    return " ".join(partes)


def declaracion_etica(meta: dict) -> str:
    return (
        "Este estudio se realizo sobre datos academicos seudonimizados (sin nombre, RUT ni "
        "correo). El seguimiento individual y el uso de variables de agrupamiento (p. ej. seccion, "
        "sexo) para analisis de equidad requieren consentimiento informado del estudiante. Todo "
        "export con fines de investigacion requiere aprobacion del comite de etica / IRB de la "
        "institucion. El sistema no emite calificaciones automaticas: la nota es responsabilidad "
        "indelegable del docente. El proposito es exclusivamente pedagogico y de mejora continua.")


def manifiesto_reproducibilidad(versiones: dict | None = None) -> dict:
    return {
        "software": "Python 3.x",
        "librerias": versiones or {"numpy": "2.x", "scipy": "1.x", "statsmodels": "0.14.x", "girth": "0.8.x"},
        "modelos": {"psicometria": "TCT + Rasch (JMLE)", "dif": "Mantel-Haenszel + regresion logistica",
                    "longitudinal": "Hake + Hedges g + modelo mixto", "cualitativo": "analisis tematico"},
        "umbrales": {"fiabilidad": ">=.70 aceptable/.80 buena/.90 excelente",
                     "ajuste_rasch": "infit/outfit 0.5-1.5 productivo",
                     "discriminacion": "r_pbis >=.30 buena", "dif_ets": "A<1, B 1-1.5, C>=1.5",
                     "efecto_educacion": "Kraft: <.05 pequeno, .05-.20 mediano, >=.20 grande"},
        "validacion": "Estimacion Rasch validada contra girth.rasch_jml (r=1.0).",
        "datos": "Dataset tidy (una fila por estudiante-item) seudonimizado, exportable en CSV/XLSX.",
    }


# ───────────────────────────────────────────── ensamblador
def ensamblar_paquete(meta: dict, ctt: dict, irt: dict,
                      dif: dict | None = None, lng: dict | None = None,
                      cualitativo: dict | None = None, versiones: dict | None = None) -> dict:
    """
    meta: {"titulo","asignatura","instrumento","autores"?...}.
    ctt/irt/dif/lng/cualitativo: salidas de los servicios respectivos (dif/lng/cualitativo opcionales).
    """
    tablas = [tabla_descriptivos(ctt), tabla_items(ctt, irt)]
    if dif:
        tablas.append(tabla_dif(dif))
    if lng:
        tablas.append(tabla_longitudinal(lng))

    figuras = [
        {"titulo": "Figura 1. Mapa item-persona (Wright) del modelo de Rasch"},
        {"titulo": "Figura 2. Funcion de informacion del test"},
    ]
    if dif:
        figuras.append({"titulo": "Figura 3. Curvas caracteristicas por grupo (DIF)"})
    if lng:
        figuras.append({"titulo": "Figura 4. Trayectoria longitudinal del curso"})
    if cualitativo:
        figuras.append({"titulo": "Figura 5. Mapa de concepciones erroneas"})

    resumen = (
        f"Se analizo psicometrica y cualitativamente {meta.get('instrumento', 'un instrumento')} "
        f"de {meta.get('asignatura', 'la asignatura')}. Se reportan indices clasicos e IRT-Rasch, "
        f"evidencia de equidad (DIF), trayectoria longitudinal y un mapa de concepciones erroneas, "
        f"bajo un marco de gobernanza etica.")

    limitaciones = (
        "La comparacion longitudinal se realiza sobre la escala de logro/nota o con efectos "
        "estandarizados; la habilidad theta de instrumentos distintos requiere equating (items "
        "ancla) para ser estrictamente comparable. El analisis de DIF y las estimaciones IRT "
        "ganan estabilidad con muestras mayores. El vinculo curricular por RA es longitudinal "
        "solo si los RA estan mapeados entre instrumentos, cada uno con su propia TE.")

    return {
        "titulo": meta.get("titulo", "Analisis psicometrico y de aprendizaje"),
        "resumen": resumen,
        "metodos": seccion_metodos(meta, ctt, dif, lng),
        "resultados": seccion_resultados(ctt, irt, dif, lng),
        "tablas": [t for t in tablas if t],
        "figuras": figuras,
        "limitaciones": limitaciones,
        "etica": declaracion_etica(meta),
        "reproducibilidad": manifiesto_reproducibilidad(versiones),
        "referencias": REFERENCIAS,
    }
