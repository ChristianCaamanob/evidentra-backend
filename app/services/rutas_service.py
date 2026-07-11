"""
Rutas de investigación CONTEXTUALES para el módulo Investigador.

No son tres tarjetas fijas: cada ruta se despliega en RAMAS cuyo estado depende de lo que el
investigador ya tiene en sus datos. A medida que incorpora información (grupos consentidos,
etiquetado C3, más evaluaciones), nuevas ramas se DESBLOQUEAN. Cada rama trae una "línea"
(consulta) para traer literatura real alineada (Crossref/PubMed).

Estados de rama:
  desbloqueada -> los datos ya lo permiten (con el porqué concreto).
  sugerida     -> falta un insumo puntual; se indica qué agregar para abrirla.
"""
from __future__ import annotations

DESBLOQUEADA = "desbloqueada"
SUGERIDA = "sugerida"


def _rama(nombre, estado, porque, metodo, query, rigor):
    return {"nombre": nombre, "estado": estado, "porque": porque,
            "metodo": metodo, "query": query, "rigor": rigor}


def construir(ctx: dict) -> dict:
    """
    ctx: {n, k, has_grupos, has_c3, n_evaluaciones, topic}
    topic: término en inglés de la línea (para la búsqueda de literatura).
    """
    n = ctx.get("n") or 0
    k = ctx.get("k") or 0
    has_grupos = bool(ctx.get("has_grupos"))
    has_c3 = bool(ctx.get("has_c3"))
    n_eval = ctx.get("n_evaluaciones") or 1
    topic = (ctx.get("topic") or "educational assessment").strip()

    # ── Ruta 1: con tus registros (análisis secundario) — ramas contextuales ──
    r1 = []
    r1.append(_rama(
        "Validación psicométrica del instrumento",
        DESBLOQUEADA if n >= 100 else SUGERIDA,
        (f"Tu cohorte (n={n}) habilita un estudio de validación publicable." if n >= 100
         else f"Con n={n} conviene reunir más casos (≥100) para un estudio de validación robusto."),
        "Rasch · CFA WLSMV · fiabilidad (α, ω)",
        f"{topic} instrument validation psychometrics",
        "preregistro del análisis · reporte COSMIN · muestra suficiente"))
    r1.append(_rama(
        "Estudio de equidad (DIF · invarianza)",
        DESBLOQUEADA if has_grupos else SUGERIDA,
        ("Tienes grupos consentidos (sexo/dependencia): se puede evaluar sesgo e invarianza."
         if has_grupos else "Agrega una variable de grupo consentida (G4) para abrir esta rama."),
        "Mantel-Haenszel · regresión logística · invarianza de medición",
        f"{topic} differential item functioning measurement invariance",
        "consentimiento G4 · umbral ETS · invarianza configural/métrica/escalar"))
    r1.append(_rama(
        "Diagnóstico cognitivo (CDM · DINA)",
        DESBLOQUEADA if has_c3 else SUGERIDA,
        ("Tus ítems están etiquetados (C3 → Q-matrix): puedes estimar perfiles de atributo."
         if has_c3 else "Etiqueta los ítems por resultado de aprendizaje (C3) para abrir esta rama."),
        "DINA · Q-matrix desde el etiquetado",
        f"{topic} cognitive diagnosis DINA Q-matrix",
        "Q-matrix justificada · ajuste del modelo · clasificación de atributos"))
    r1.append(_rama(
        "Estudio longitudinal / de crecimiento",
        DESBLOQUEADA if n_eval >= 2 else SUGERIDA,
        (f"El curso tiene {n_eval} evaluaciones: puedes modelar la trayectoria de aprendizaje."
         if n_eval >= 2 else "Suma otra evaluación al curso para abrir el análisis longitudinal."),
        "modelos de crecimiento · invarianza longitudinal",
        f"{topic} longitudinal growth learning measurement",
        "invarianza longitudinal · manejo de datos faltantes (MCAR/MAR)"))

    # ── Ruta 2: revisión sistemática (independiente o para enmarcar tus datos) ──
    r2 = [
        _rama("Revisión sistemática (PRISMA 2020)", DESBLOQUEADA,
              "Sintetiza la evidencia de tu línea con método reproducible; enmarca tus hallazgos.",
              "PICO/PECO · búsqueda · cribado 2 revisores (κ) · síntesis",
              f"{topic} systematic review",
              "protocolo PROSPERO · PRISMA 2020 · sesgo ROB-2/QUADAS-2"),
        _rama("Meta-análisis", SUGERIDA if n_eval < 2 else DESBLOQUEADA,
              "Cuando reúnas varios estudios/medidas comparables, agrega los tamaños de efecto.",
              "modelo de efectos aleatorios · heterogeneidad (I²)",
              f"{topic} meta-analysis effect size",
              "PRISMA · evaluación de heterogeneidad y sesgo de publicación"),
    ]

    # ── Ruta 3: estudio experimental (independiente, o intervención sobre tu población) ──
    r3 = [
        _rama("Ensayo controlado (RCT / cuasi)", DESBLOQUEADA,
              (f"Con n={n} puedes dimensionar el poder para detectar un efecto." if n
               else "Define hipótesis, diseño y cálculo de potencia."),
              "aleatorización · potencia · ANCOVA/modelos mixtos · tamaño de efecto",
              f"{topic} randomized controlled trial intervention",
              "preregistro OSF · CONSORT · control de confusores"),
        _rama("Estudio de intervención pre-post", DESBLOQUEADA if n_eval >= 2 else SUGERIDA,
              ("Tus mediciones repetidas permiten un diseño pre-post con tu población."
               if n_eval >= 2 else "Con una medición basal y una posterior se abre el diseño pre-post."),
              "pre-post · diferencias-en-diferencias · tamaño de efecto con IC",
              f"{topic} pre-post intervention quasi-experimental",
              "grupo de comparación · control de regresión a la media"),
    ]

    rutas = [
        {"n": "01", "titulo": "Con tus registros", "tipo": "análisis de lo que ya tienes", "ramas": r1},
        {"n": "02", "titulo": "Revisión sistemática", "tipo": "independiente o para enmarcar tus datos", "ramas": r2},
        {"n": "03", "titulo": "Estudio experimental", "tipo": "independiente, o intervención sobre tu población", "ramas": r3},
    ]
    n_desbloq = sum(1 for r in rutas for a in r["ramas"] if a["estado"] == DESBLOQUEADA)
    return {"linea": topic, "rutas": rutas, "n_ramas_desbloqueadas": n_desbloq,
            "contexto": {"n": n, "k": k, "has_grupos": has_grupos, "has_c3": has_c3,
                         "n_evaluaciones": n_eval},
            "nota": "Las ramas se desbloquean con lo que incorporas; cada una trae literatura real alineada."}
