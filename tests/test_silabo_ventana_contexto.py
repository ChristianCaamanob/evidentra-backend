"""
La ventana de contexto de Runi.

El caso que originó estos tests: una estudiante preguntó por las ponderaciones de sus pruebas
teniendo el programa cargado, y Runi respondió que no lo tenía escrito. En un sílabo la sección de
evaluación va casi siempre al final, y el contexto se recortaba a los primeros 20 000 caracteres:
el dato existía y Runi nunca lo veía.
"""
from app.services import silabo_service as sil

# Un sílabo largo y realista: la sección de evaluación al FINAL, como en un programa de verdad.
_RELLENO = "\n\n".join(
    f"UNIDAD {i}. Contenidos de anatomía de la unidad {i}: descripción, irrigación e inervación "
    "de las estructuras revisadas en clases teóricas y prácticas de laboratorio." for i in range(1, 400))
_EVALUACION = (
    "EVALUACIÓN DE LA ASIGNATURA\n"
    "Solemne 1: ponderación 30%\n"
    "Solemne 2: ponderación 30%\n"
    "Examen final: ponderación 40%\n"
    "Nota de aprobación: 4.0 con 75% de asistencia.")
_SILABO = "ANATOMÍA APLICADA A LA GINECOOBSTETRICIA\n\n" + _RELLENO + "\n\n" + _EVALUACION


def test_contexto_corto_pasa_entero():
    corto = "Curso breve.\n\nSolemne 1: 40%."
    assert sil._ventana_contexto(corto, "¿ponderaciones?") == corto


def test_ponderaciones_del_final_llegan_al_modelo():
    """El corazón del asunto: el dato está en el último tramo de un sílabo que no cabe entero."""
    assert len(_SILABO) > sil._TOPE_CONTEXTO          # el caso solo existe si de verdad no cabe
    v = sil._ventana_contexto(_SILABO, "¿Cuáles son las ponderaciones de mis pruebas?")
    assert "ponderación 30%" in v and "Examen final: ponderación 40%" in v
    assert len(v) <= sil._TOPE_CONTEXTO


def test_el_encabezado_nunca_se_pierde():
    """Sin el encabezado el modelo deja de saber de qué curso habla."""
    v = sil._ventana_contexto(_SILABO, "¿Cuáles son las ponderaciones?")
    assert "ANATOMÍA APLICADA A LA GINECOOBSTETRICIA" in v


def test_se_avisa_que_es_una_seleccion():
    """Los saltos van marcados: el modelo debe saber que ve un extracto, no el documento entero."""
    assert "[…]" in sil._ventana_contexto(_SILABO, "¿Cuáles son las ponderaciones?")


def test_una_pregunta_de_contenido_trae_su_unidad():
    largo = "PROGRAMA\n\n" + _RELLENO + "\n\nUNIDAD ESPECIAL. El drenaje linfático de la mama sigue la cadena axilar.\n\n" + _RELLENO
    v = sil._ventana_contexto(largo, "¿Cómo es el drenaje linfático de la mama?")
    assert "drenaje linfático de la mama" in v


def test_los_trozos_respetan_las_lineas():
    """Una tabla OCR viene como un párrafo gigante: se parte por líneas, no a mitad de palabra."""
    tabla = "\n".join(f"Fila {i} con datos de la tabla de especificaciones" for i in range(300))
    for t in sil._trozos(tabla, largo=500):
        assert t.strip()
        assert not t.startswith(" ")


# ── qué se le dice al estudiante cuando el motor falla ───────────────────────────────
def test_una_caida_del_motor_nunca_se_le_cobra_al_estudiante():
    """Visto en producción: la cuenta sin saldo devolvía «reformula tu pregunta».

    Eso manda a la estudiante a repetir para siempre una pregunta que estaba bien, y le ensucia al
    docente el mapa de vacíos con temas que Runi nunca llegó a intentar. Ninguna de estas fallas es
    de la pregunta.
    """
    fallas = [
        "Your credit balance is too low to access the Anthropic API",
        "billing error: payment required",
        "model claude-x does not exist",
        "not_found_error: model",
        "invalid_request_error",
        "sin respuesta del modelo",
        "502 Bad Gateway",
        "rate_limit_error", "overloaded_error", "connection reset", "timeout",
    ]
    for f in fallas:
        assert sil._es_falla_de_servicio(Exception(f)), f


def test_una_pregunta_fuera_del_silabo_sigue_siendo_del_silabo():
    """Al revés: ensanchar las señales no puede convertir cualquier error en «servicio caído»."""
    for f in ("KeyError: 'tema'", "list index out of range", ""):
        assert not sil._es_falla_de_servicio(Exception(f)), f


# ── el rescate: una duda de CONTENIDO no se deriva al docente ────────────────────────
def test_una_duda_de_anatomia_no_es_un_parametro_del_curso():
    """Visto en el piloto: preguntas de contenido puro acabaron en la bandeja del docente.

    `fuera_corpus` existe para un dato administrativo que el profesor no escribió (una fecha, una
    ponderación). Derivar una duda de anatomía le roba tiempo al profesor, deja a la estudiante
    esperando por algo que se sabe, y le ensucia el mapa de vacíos.
    """
    contenido = [
        "el nervio frenico nace desde el plexo cervical, de que se encarga un 75% la vértebra C4?",
        "Drenaje linfático de la mama nombra los linfos que existen",
        "Drenaje linfático de la mama tipos de linfonodos",
        "Que debo saber de la región axilar",
        "Seno pericárdicoTrans",
        "¿Qué músculo deprime los cartílagos costales?",
    ]
    for q in contenido:
        assert not sil._pide_un_parametro(q), q


def test_un_parametro_del_curso_si_se_reconoce():
    """Y al revés: lo administrativo tiene que seguir yendo al docente cuando no está escrito."""
    parametros = [
        "¿Cuáles son las ponderaciones de mis pruebas?",
        "¿Cuándo es el solemne?",
        "¿En qué sala rendimos?",
        "¿Hasta dónde entra en el certamen?",
        "¿Qué pasa con mi asistencia si falto?",
        "¿Cuánto vale la nota del taller?",
        "¿Cuál es la fecha de entrega?",
        "¿Cómo se evalúa el informe?",
    ]
    for q in parametros:
        assert sil._pide_un_parametro(q), q
