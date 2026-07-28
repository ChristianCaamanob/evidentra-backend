"""Evalys Evidence Core — expediente científico VERSIONADO por procedimiento.

Doctrina (CEO, jul-28): Evalys no es "una plataforma que usa IA para educar", sino una
INFRAESTRUCTURA DE EVALUACIÓN cuyos procedimientos se pueden defender científica, psicométrica,
normativa y éticamente. Cada función medible lleva un EXPEDIENTE con: constructo → fundamento →
procedimiento/fórmula → evidencia científica (con DOI/diseño/hallazgo/riesgo de sesgo/aplicabilidad)
→ norma/estándar → limitaciones/población validada → versión/fecha → validación interna →
responsable de aprobación. El distintivo "Respaldado por Evalys Evidence" lo hace VISIBLE por módulo.

Precisión del CEO: publicar Q1/Q2 NO garantiza evidencia sólida — hay que evaluar diseño, riesgo de
sesgo, tamaño de efecto, población, replicación y CERTEZA. Por eso cada estudio del expediente
declara su `rob` (riesgo de sesgo / nivel de evidencia) y su `aplicabilidad`.

Este catálogo es CONOCIMIENTO DE PRODUCTO curado (no dato de usuario): vive en código, versionado.
Fase futura: superponer resultados de validación interna continua desde la base de datos.
"""
from __future__ import annotations

# Jerarquía de certeza espejo de la de Runi (silabo_service): un único lenguaje de certeza en todo Evalys.
NIVELES_CERTEZA = ("solida", "moderada", "preliminar", "insuficiente")

# Cada expediente: clave → dict con todos los campos defendibles. `evidencia` es una lista de estudios
# con su riesgo de sesgo (rob) y aplicabilidad (la clave que pidió el CEO: Q1 no basta por sí solo).
_EXPEDIENTES: dict[str, dict] = {
    "certeza_runi": {
        "titulo": "Jerarquía de certeza de Runi",
        "modulo": "Escudo de comunicación · Runi",
        "certeza_global": "solida",
        "constructo": "Comunicación honesta y calibrada de la incertidumbre de una respuesta de IA, "
                      "separando hecho, inferencia, recomendación y decisión docente.",
        "fundamento": "La calibración (que la confianza declarada coincida con la exactitud real) es un "
                      "requisito de una IA educativa responsable; sobre-declarar certeza induce dependencia "
                      "y errores de alta confianza. Se adopta un lenguaje de certeza graduado con pisos que "
                      "impiden a la IA presentar su conocimiento propio como evidencia dura del curso.",
        "procedimiento": "Piso por fuente: derivación→'revisión docente'; respaldado por el material del "
                         "curso (con cita)→puede ser 'sólida'; conocimiento propio de la IA→tope 'moderada'; "
                         "sin respaldo→'insuficiente'. La certeza y la separación de planos se registran en "
                         "una bitácora encadenada por hash (append-only).",
        "evidencia": [
            {"referencia": "Guo et al. (2017), On Calibration of Modern Neural Networks",
             "doi": "10.48550/arXiv.1706.04599", "diseno": "Estudio empírico de calibración",
             "hallazgo": "Los modelos modernos están mal calibrados por defecto: la confianza no refleja la "
                         "exactitud; se requiere calibración explícita.",
             "rob": "Moderado · dominio ML, no educativo", "aplicabilidad": "Justifica no confiar en la "
             "confianza cruda del modelo y fijar pisos externos."},
            {"referencia": "AERA, APA & NCME (2014), Standards for Educational and Psychological Testing",
             "doi": "", "diseno": "Estándar profesional",
             "hallazgo": "Toda interpretación derivada de una medición debe declarar su fundamento de validez "
                         "y sus límites; no se presentan inferencias como hechos.",
             "rob": "Referencia normativa (no estudio empírico)", "aplicabilidad": "Alta · gobierna la "
             "separación hecho/inferencia."},
        ],
        "normas": ["AERA/APA/NCME Standards (2014)", "Ley 21.719 (protección de datos, Chile)"],
        "limitaciones": "El piso es conservador por diseño; puede subestimar la certeza de una inferencia "
                        "correcta. La calibración fina por dominio aún no se mide en vivo.",
        "poblacion_validada": "Consultas de estudiantes de educación superior en español (piloto interno).",
        "validacion_interna": "Auditoría de la cadena de bitácora (verificación de integridad por hash) en "
                              "cada lectura. Pendiente: estudio de calibración confianza-vs-exactitud en vivo.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Dirección de Producto · Evalys",
    },
    "fiabilidad_alfa_omega": {
        "titulo": "Fiabilidad · α de Cronbach y ω de McDonald",
        "modulo": "Investigador · Psicometría",
        "certeza_global": "solida",
        "constructo": "Consistencia interna de un puntaje total como estimación de su fiabilidad.",
        "fundamento": "α asume tau-equivalencia (cargas iguales) y suele subestimar o sobreestimar la "
                      "fiabilidad cuando ese supuesto no se cumple; ω de McDonald, basado en el modelo "
                      "factorial, es el estimador recomendado. Evalys reporta AMBOS con su supuesto.",
        "procedimiento": "α = (k/(k-1))·(1 − Σσ²ᵢ/σ²ₜ). ω = (Σλᵢ)² / [(Σλᵢ)² + Σψᵢ] a partir de las cargas "
                         "λ de un modelo factorial de un factor. Se acompañan de su intervalo de confianza.",
        "evidencia": [
            {"referencia": "McDonald (1999), Test Theory: A Unified Treatment", "doi": "10.4324/9781410601087",
             "diseno": "Tratado teórico", "hallazgo": "Define ω como estimador de fiabilidad basado en el "
             "modelo factorial, superior a α bajo cargas desiguales.",
             "rob": "Bajo · fundamento canónico", "aplicabilidad": "Alta."},
            {"referencia": "Flora (2020), Your Coefficient Alpha Is Probably Wrong…",
             "doi": "10.1177/2515245920951747", "diseno": "Revisión metodológica",
             "hallazgo": "α es frecuentemente inadecuado; recomienda reportar ω y verificar la dimensionalidad.",
             "rob": "Bajo · revisión metodológica reciente", "aplicabilidad": "Alta · guía la práctica de Evalys."},
        ],
        "normas": ["COSMIN (fiabilidad de instrumentos)", "AERA/APA/NCME Standards (2014)"],
        "limitaciones": "ω requiere un modelo factorial razonable (unidimensionalidad aproximada). Con muestras "
                        "pequeñas los intervalos son amplios.",
        "poblacion_validada": "Ítems dicotómicos y politómicos; muestras n≥200 en cohortes de demostración.",
        "validacion_interna": "Contrastado contra valores de referencia en cohortes simuladas con fiabilidad "
                              "conocida (semilla fija).",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "rasch_tri": {
        "titulo": "Modelo de Rasch / TRI (1PL–2PL)",
        "modulo": "Investigador · Psicometría",
        "certeza_global": "solida",
        "constructo": "Medición de la habilidad latente del estudiante y la dificultad del ítem en una escala "
                      "de intervalo común (logits).",
        "fundamento": "La Teoría de Respuesta al Ítem modela la probabilidad de acierto en función de la "
                      "habilidad (θ) y parámetros del ítem; Rasch (1PL) impone medición conjunta invariante. "
                      "Permite propiedades que el puntaje bruto no garantiza (invarianza, error por nivel).",
        "procedimiento": "1PL: P(Xᵢ=1|θ) = 1/(1+e^{−(θ−bᵢ)}). 2PL añade discriminación aᵢ: "
                         "P = 1/(1+e^{−aᵢ(θ−bᵢ)}). Estimación por máxima verosimilitud marginal.",
        "evidencia": [
            {"referencia": "Rasch (1960/1980), Probabilistic Models for Some Intelligence and Attainment Tests",
             "doi": "", "diseno": "Fundamento teórico", "hallazgo": "Define la medición conjunta específicamente "
             "objetiva de personas e ítems.", "rob": "Bajo · fundamento canónico", "aplicabilidad": "Alta."},
            {"referencia": "Embretson & Reise (2000), Item Response Theory for Psychologists",
             "doi": "10.4324/9781410605269", "diseno": "Tratado de referencia",
             "hallazgo": "Sistematiza TRI 1PL/2PL/3PL, supuestos (unidimensionalidad, independencia local) y ajuste.",
             "rob": "Bajo", "aplicabilidad": "Alta · define supuestos que Evalys verifica antes de aplicar."},
        ],
        "normas": ["AERA/APA/NCME Standards (2014)", "COSMIN"],
        "limitaciones": "Exige unidimensionalidad e independencia local; sensible al tamaño muestral (2PL/3PL "
                        "requieren n grande). Evalys verifica dimensionalidad antes de justificar el modelo.",
        "poblacion_validada": "Evaluaciones de alternativas, k=12–24 ítems, n≥250 (cohortes de demostración).",
        "validacion_interna": "Recuperación de parámetros en datos simulados 2PL con parámetros conocidos.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "dif_equidad": {
        "titulo": "Funcionamiento Diferencial del Ítem (DIF) · equidad",
        "modulo": "Investigador · Equidad",
        "certeza_global": "moderada",
        "constructo": "Detección de ítems que funcionan distinto entre grupos (p. ej. dependencia, sexo) a "
                      "igual nivel de habilidad — una amenaza a la validez y a la equidad.",
        "fundamento": "Un ítem con DIF favorece o perjudica a un grupo controlando la habilidad; su presencia "
                      "cuestiona la comparabilidad de puntajes. El análisis es CONSENTIDO (Ley 21.719).",
        "procedimiento": "Mantel-Haenszel (DIF uniforme) y regresión logística (uniforme + no uniforme), "
                         "estratificando por el puntaje total. Se reporta magnitud y clasificación (A/B/C ETS).",
        "evidencia": [
            {"referencia": "Holland & Wainer (1993), Differential Item Functioning",
             "doi": "10.4324/9780203357811", "diseno": "Obra de referencia",
             "hallazgo": "Establece los métodos MH y de regresión logística para DIF y su interpretación.",
             "rob": "Bajo", "aplicabilidad": "Alta."},
            {"referencia": "Zumbo (1999), A Handbook on the Theory and Methods of DIF", "doi": "",
             "diseno": "Manual metodológico", "hallazgo": "Detalla la regresión logística para DIF uniforme y "
             "no uniforme con tamaños de efecto.", "rob": "Bajo", "aplicabilidad": "Alta."},
        ],
        "normas": ["Standards (2014) · equidad en el testing", "Ley 21.719 (consentimiento y datos sensibles)"],
        "limitaciones": "Requiere n suficiente POR GRUPO (idealmente ≥200 c/u); el DIF señala una alerta, no una "
                        "causa — la interpretación sustantiva es del experto. Solo con consentimiento.",
        "poblacion_validada": "Grupos balanceados y consentidos; DIF uniforme plantado y recuperado en demo.",
        "validacion_interna": "Detección verificada en cohorte con DIF uniforme inyectado en ítems conocidos.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "cfa_dimensionalidad": {
        "titulo": "Dimensionalidad · AFC e índices de ajuste (CFI/TLI/RMSEA)",
        "modulo": "Investigador · Validez estructural",
        "certeza_global": "solida",
        "constructo": "Evidencia de validez estructural: que sumar el puntaje total es legítimo porque los "
                      "ítems miden un constructo común.",
        "fundamento": "El Análisis Factorial Confirmatorio contrasta un modelo de medición; los índices de "
                      "ajuste cuantifican qué tan bien reproduce la estructura de covarianzas. Con ítems "
                      "categóricos se usa el estimador WLSMV.",
        "procedimiento": "AFC con WLSMV sobre correlaciones policóricas. Se reportan CFI, TLI, RMSEA y cargas "
                         "estandarizadas; unidimensionalidad como respaldo del puntaje total.",
        "evidencia": [
            {"referencia": "Hu & Bentler (1999), Cutoff criteria for fit indexes…",
             "doi": "10.1080/10705519909540118", "diseno": "Estudio de simulación",
             "hallazgo": "Propone puntos de corte (CFI≥.95, RMSEA≤.06) para el ajuste del modelo.",
             "rob": "Moderado · cortes que se han matizado luego (no aplicar de forma mecánica)",
             "aplicabilidad": "Alta, con la advertencia de no tratarlos como umbrales rígidos."},
            {"referencia": "Flora & Curran (2004), An empirical evaluation of alternative methods… categorical data",
             "doi": "10.1037/1082-989X.9.4.466", "diseno": "Estudio de simulación",
             "hallazgo": "Justifica WLSMV para indicadores categóricos.", "rob": "Bajo",
             "aplicabilidad": "Alta · define el estimador que usa Evalys."},
        ],
        "normas": ["COSMIN (validez estructural)", "AERA/APA/NCME Standards (2014)"],
        "limitaciones": "Los puntos de corte NO son leyes universales; sensibles al tamaño y a la complejidad "
                        "del modelo. Requiere n adecuado para estabilidad de WLSMV.",
        "poblacion_validada": "Instrumentos de 12–16 ítems; k=16 mantiene el AFC estable en demo.",
        "validacion_interna": "Ajuste evaluado en estructura unidimensional simulada conocida.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "grade_certeza": {
        "titulo": "Certeza de la evidencia · GRADE",
        "modulo": "Investigador · Síntesis / Metaanálisis",
        "certeza_global": "solida",
        "constructo": "Calificación de la certeza (confianza) en la estimación de un efecto sintetizado.",
        "fundamento": "GRADE gradúa la certeza en alta/moderada/baja/muy baja considerando riesgo de sesgo, "
                      "inconsistencia, imprecisión, evidencia indirecta y sesgo de publicación — precisamente "
                      "la advertencia del CEO: 'Q1/Q2 no basta; hay que evaluar diseño, sesgo, efecto, certeza'.",
        "procedimiento": "Se parte del diseño (ECA=alta) y se baja/sube por los dominios GRADE; el veredicto "
                         "se reporta por desenlace con las razones explícitas de cada descenso.",
        "evidencia": [
            {"referencia": "Guyatt et al. (2008), GRADE: an emerging consensus…",
             "doi": "10.1136/bmj.39489.470347.AD", "diseno": "Consenso metodológico (BMJ)",
             "hallazgo": "Define el sistema GRADE y sus dominios.", "rob": "Bajo · consenso ampliamente adoptado",
             "aplicabilidad": "Alta."},
            {"referencia": "Balshem et al. (2011), GRADE guidelines: 3. Rating the quality of evidence",
             "doi": "10.1016/j.jclinepi.2010.07.015", "diseno": "Guía metodológica",
             "hallazgo": "Operacionaliza la calificación de certeza por desenlace.", "rob": "Bajo",
             "aplicabilidad": "Alta."},
        ],
        "normas": ["GRADE Working Group", "PRISMA 2020 (reporte de síntesis)"],
        "limitaciones": "GRADE incluye juicio experto en cada dominio; distintos revisores pueden diferir. Evalys "
                        "hace explícitas las razones para trazabilidad.",
        "poblacion_validada": "Síntesis de estudios cargados por el investigador en el módulo de metaanálisis.",
        "validacion_interna": "Coherencia del descenso por dominio verificada sobre casos de prueba.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "prisma_2020": {
        "titulo": "Reporte de revisiones sistemáticas · PRISMA 2020",
        "modulo": "Investigador · Revisión sistemática",
        "certeza_global": "solida",
        "constructo": "Transparencia y completitud del reporte de una revisión sistemática (no es una medida de "
                      "calidad del estudio, sino del REPORTE).",
        "fundamento": "PRISMA 2020 estandariza qué debe informar una revisión (búsqueda, cribado, inclusión, "
                      "sesgos, síntesis) y su diagrama de flujo de doble vía, para que sea replicable y auditable.",
        "procedimiento": "Checklist de 27 ítems + diagrama de flujo (identificación→cribado→incluidos), con "
                         "cadenas de búsqueda por base y literatura gris. Evalys genera ambos.",
        "evidencia": [
            {"referencia": "Page et al. (2021), The PRISMA 2020 statement",
             "doi": "10.1136/bmj.n71", "diseno": "Guía de reporte (consenso)",
             "hallazgo": "Actualiza PRISMA con 27 ítems y el diagrama de doble vía.",
             "rob": "Bajo · estándar internacional", "aplicabilidad": "Alta."},
        ],
        "normas": ["PRISMA 2020", "PRISMA-ScR (scoping)", "MOOSE (observacionales)"],
        "limitaciones": "Buen reporte ≠ buena evidencia: PRISMA no evalúa el riesgo de sesgo de los estudios "
                        "(eso lo hacen RoB 2 / Newcastle-Ottawa, también en Evalys).",
        "poblacion_validada": "Revisiones sistemáticas y de alcance en el módulo Proyectos.",
        "validacion_interna": "Contraste del checklist y del flujo contra las plantillas oficiales.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
    "item_clasico": {
        "titulo": "Análisis clásico de ítems · dificultad y discriminación",
        "modulo": "Psicometría · Teoría clásica",
        "certeza_global": "solida",
        "constructo": "Calidad de cada ítem: qué tan difícil es y qué tan bien separa a quienes dominan de "
                      "quienes no.",
        "fundamento": "La dificultad (p) y la discriminación (correlación ítem-total corregida / índice D) son "
                      "los indicadores clásicos para depurar un instrumento y detectar distractores fallidos.",
        "procedimiento": "p = proporción de aciertos; discriminación = correlación punto-biserial corregida "
                         "(ítem vs total sin el ítem). Análisis de distractores por opción.",
        "evidencia": [
            {"referencia": "Crocker & Algina (1986), Introduction to Classical and Modern Test Theory",
             "doi": "", "diseno": "Tratado de referencia",
             "hallazgo": "Define los índices clásicos de ítem y sus criterios de interpretación.",
             "rob": "Bajo · canónico", "aplicabilidad": "Alta."},
        ],
        "normas": ["AERA/APA/NCME Standards (2014)"],
        "limitaciones": "Los índices clásicos dependen de la muestra (no invariantes como TRI). La discriminación "
                        "baja con muy alta/baja dificultad.",
        "poblacion_validada": "Ítems de alternativas en todas las cohortes de demostración.",
        "validacion_interna": "Índices contrastados contra cálculo de referencia en datos conocidos.",
        "version": "1.0.0", "fecha": "2026-07-28", "responsable": "Módulo Investigador · Evalys",
    },
}

# Alias amables → clave canónica (para que los módulos puedan pedir el expediente por un nombre cercano).
_ALIAS = {
    "certeza": "certeza_runi", "runi": "certeza_runi",
    "alfa": "fiabilidad_alfa_omega", "omega": "fiabilidad_alfa_omega", "fiabilidad": "fiabilidad_alfa_omega",
    "rasch": "rasch_tri", "tri": "rasch_tri", "irt": "rasch_tri",
    "dif": "dif_equidad", "equidad": "dif_equidad",
    "cfa": "cfa_dimensionalidad", "afc": "cfa_dimensionalidad", "dimensionalidad": "cfa_dimensionalidad",
    "grade": "grade_certeza",
    "prisma": "prisma_2020",
    "item": "item_clasico", "discriminacion": "item_clasico", "dificultad": "item_clasico",
}


def _clave(clave: str) -> str | None:
    c = (clave or "").strip().lower()
    if c in _EXPEDIENTES:
        return c
    return _ALIAS.get(c)


def obtener(clave: str) -> dict | None:
    """Devuelve el expediente completo (con su clave) o None si no existe."""
    c = _clave(clave)
    if not c:
        return None
    return {"clave": c, **_EXPEDIENTES[c]}


def listar() -> list[dict]:
    """Resumen de todos los expedientes (para el índice del distintivo)."""
    return [{"clave": k, "titulo": v["titulo"], "modulo": v["modulo"],
             "certeza_global": v["certeza_global"], "n_estudios": len(v["evidencia"]),
             "normas": v["normas"], "version": v["version"], "fecha": v["fecha"]}
            for k, v in _EXPEDIENTES.items()]
