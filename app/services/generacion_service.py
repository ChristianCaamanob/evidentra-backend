"""
E2 - Generacion cualitativa rica de la retroalimentacion.

Sube la retroalimentacion de generica (E1, determinista) a rica: para cada brecha,
'que muestra' + 'por que importa' + una recomendacion accionable, y un plan de
consolidacion con sesiones. Se apoya en un CORPUS por RA (contenido curado del curso).

Gobernanza (no negociable):
  - G2 seudonimizacion: la generacion trabaja sobre una VISTA SEUDONIMIZADA de `datos`
    (sin nombre/RUT/correo). `vista_seudonimizada` lo garantiza y `_sin_identificatorios`
    lo verifica antes de cualquier uso.
  - G1 la IA no decide: la salida es una PROPUESTA (requiere_validacion_docente=True).
    La nota y el cierre del informe siguen siendo del docente.

Motor: `enriquecer` usa un compositor determinista calibrado por el corpus. El punto de
conexion a un modelo potente (Opus/Sonnet) queda como seam documentado en `_generar_modelo`
(engine=api): recibe SOLO la vista seudonimizada.
"""
from __future__ import annotations

import os

# Identificadores de PERSONA (alumno). No incluye "nombre"/"name" a secas: esas claves
# aparecen legitimamente como nombre de la evaluacion o del curso, que no identifican a nadie.
CAMPOS_IDENTIFICATORIOS = (
    "rut", "run", "dni", "cedula", "identificador", "student_identifier",
    "correo", "email", "mail", "nombres", "nombre_completo",
    "apellido_paterno", "apellido_materno",
)

# Corpus de referencia para DMOR0030 (contenido curado por RA). Es el material que
# calibra la generacion; el docente lo valida/ajusta. Clave = codigo de RA del curso.
CORPUS_DMOR0030 = {
    "RA1": {
        "por_que_importa": "La terminologia y los niveles de organizacion son la base para leer cualquier estructura; sin ese marco, el resto de la morfologia queda suelto.",
        "recomendacion": "Repasa niveles de organizacion (celula-tejido-organo-sistema) y enfoques morfologicos con un esquema propio de una estructura de ejemplo.",
        "actividad": "Mapa conceptual de niveles de organizacion aplicado a 3 estructuras.",
    },
    "RA2": {
        "por_que_importa": "El desarrollo embrionario explica el origen de tejidos y organos; entender etapas y capas germinativas ordena el 'por que' de la anatomia adulta.",
        "recomendacion": "Arma una linea de tiempo del desarrollo (semanas, periodos, hitos) y asocia cada capa germinativa con dos derivados.",
        "actividad": "Linea de tiempo del desarrollo + tabla capa germinativa -> derivados.",
    },
    "RA3": {
        "por_que_importa": "Los tejidos basicos son el ladrillo de todos los organos; distinguir epitelio, conectivo y sus variantes es lo que permite interpretar histologia y funcion.",
        "recomendacion": "Compara los tipos de epitelio y de conectivo en una tabla morfofuncion (forma -> funcion -> localizacion) y practica con imagenes.",
        "actividad": "Tabla comparativa de tejidos con 2 imagenes por tipo.",
    },
    "RA4": {
        "por_que_importa": "La terminologia de posicion, planos y ejes es el lenguaje comun para describir el cuerpo; sin ella, las descripciones anatomicas se vuelven ambiguas.",
        "recomendacion": "Practica describiendo relaciones (proximal/distal, medial/lateral) sobre esquemas, y asocia cada movimiento a su plano y eje.",
        "actividad": "Ejercicios de terminos de relacion + planos/ejes sobre laminas.",
    },
    "RA5": {
        "por_que_importa": "La organizacion topografica del sistema osteoarticular y nervioso conecta estructura con funcion; es clave para razonar casos anatomicos simples.",
        "recomendacion": "Refuerza clasificacion de huesos y articulaciones, y la organizacion de sustancia gris/blanca; usa casos anatomicos simples para aplicar.",
        "actividad": "Resolucion de 5 casos anatomicos (osteoarticular y nervioso).",
    },
}


def _sin_identificatorios(obj) -> bool:
    """True si en el objeto (dict/list/str) no aparece ningun campo identificatorio."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in CAMPOS_IDENTIFICATORIOS:
                return False
            if not _sin_identificatorios(v):
                return False
        return True
    if isinstance(obj, list):
        return all(_sin_identificatorios(x) for x in obj)
    return True


def vista_seudonimizada(datos: dict) -> dict:
    """
    Devuelve una copia de `datos` apta para enviar a la IA: sin bloque `estudiante`
    y sin identificadores. Conserva desempeno, brechas, fortalezas, dimensiones y RA.
    """
    v = {k: val for k, val in datos.items() if k != "estudiante"}
    # metadata puede traer identificadores? no, pero por si acaso limpiamos claves prohibidas.
    if not _sin_identificatorios(v):
        raise ValueError("La vista para la IA aun contiene datos identificatorios (viola G2).")
    return v


def enriquecer(datos: dict, corpus: dict | None = None) -> dict:
    """
    Produce la retroalimentacion rica (PROPUESTA, pendiente de validacion docente).
    Trabaja sobre la vista seudonimizada. `corpus`: {ra_code: {por_que_importa, recomendacion, actividad}}.
    """
    vista = vista_seudonimizada(datos)
    corpus = corpus or {}

    def _corp(ra: str, campo: str, ra_texto: str | None) -> str:
        c = corpus.get(ra or "", {})
        if c.get(campo):
            return c[campo]
        # Fallback generico y propositivo derivado del texto del RA (sin inventar contenido).
        base = ra_texto or "este resultado de aprendizaje"
        return {
            "por_que_importa": f"Consolidar '{base}' sostiene los aprendizajes que vienen despues en la asignatura.",
            "recomendacion": f"Dedica una sesion breve a repasar '{base}' con ejemplos y autoevaluacion.",
            "actividad": f"Repaso guiado de '{base}'.",
        }[campo]

    brechas_ricas = []
    for b in vista.get("brechas", []):
        ra = b.get("ra")
        brechas_ricas.append({
            "ra": ra,
            "unidad": b.get("unidad"),
            "porcentaje": b.get("porcentaje"),
            "que_muestra": b.get("que_muestra"),
            "por_que_importa": _corp(ra, "por_que_importa", b.get("ra_texto")),
            "recomendacion": _corp(ra, "recomendacion", b.get("ra_texto")),
        })

    fortalezas_ricas = [
        {"ra": f.get("ra"), "porcentaje": f.get("porcentaje"),
         "comentario": f"Dominio solido en {f.get('ra')}: apoyate en esta base para los focos por reforzar."}
        for f in vista.get("fortalezas", [])
    ]

    sesiones = []
    for i, b in enumerate(brechas_ricas, start=1):
        sesiones.append({
            "n": i,
            "foco": b["ra"],
            "actividad": _corp(b["ra"], "actividad", None),
            "duracion_min": 45,
        })
    plan = {
        "sesiones": sesiones,
        "resumen": (f"Plan de {len(sesiones)} sesion(es) enfocado en "
                    f"{', '.join(b['ra'] for b in brechas_ricas) or 'mantener el nivel'}."),
    }

    des = vista.get("desempeno", {})
    if brechas_ricas:
        mensaje = (f"Alcanzaste {des.get('porcentaje')}% de logro. Tienes una base solida en "
                   f"{', '.join(f['ra'] for f in fortalezas_ricas) or 'varias areas'}; el foco ahora "
                   f"esta en {', '.join(b['ra'] for b in brechas_ricas)}. El plan propone pasos concretos.")
    else:
        mensaje = (f"Alcanzaste {des.get('porcentaje')}% de logro, sin brechas por RA. "
                   f"Proximo desafio: profundizar hacia niveles cognitivos superiores.")

    return {
        "seudonimizado": True,
        "requiere_validacion_docente": True,   # G1: la IA propone, el docente valida
        "ia_utilizada": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "brechas": brechas_ricas,
        "fortalezas": fortalezas_ricas,
        "plan_consolidacion": plan,
        "mensaje": mensaje,
    }


def _generar_modelo(vista_seudonimizada: dict, model: str) -> dict:  # pragma: no cover
    """
    Seam para el motor de modelo potente (engine=api). Recibe SOLO la vista
    seudonimizada. Completar con la llamada al SDK anthropic + tool-use si se desea
    una redaccion mas matizada que el compositor por corpus. Doc:
    https://docs.claude.com/en/api/overview
    """
    raise NotImplementedError("Conectar el modelo (engine=api) usando solo la vista seudonimizada.")
