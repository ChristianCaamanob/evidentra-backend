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
