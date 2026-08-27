"""
Transcribir un sílabo ESCANEADO (PDF de imagen o foto) a texto, con visión.

Un PDF escaneado no tiene texto que extraer: el extractor del navegador (pdf.js/mammoth)
devuelve vacío y el docente se queda mirando un cuadro en blanco. Aquí las páginas llegan
ya rasterizadas desde el cliente y un modelo con visión las transcribe.

Es TRANSCRIPCIÓN, no interpretación: se pide el texto tal como está, sin resumir ni
inventar, porque este contenido es luego la única fuente sobre la que Runi responde a los
estudiantes. Un sílabo resumido produciría respuestas con fechas y ponderaciones inventadas.
"""
from __future__ import annotations

import logging

from app.core.errors import unprocessable

_LOG = logging.getLogger("evalys")
_MAX_PAGINAS = 6            # tope duro de imágenes por consulta (igual que el resto de visión)

_SYSTEM = (
    "Eres un transcriptor de documentos académicos. Devuelves EXACTAMENTE el texto que ves, "
    "respetando títulos, tablas, fechas, porcentajes y numeraciones. No resumes, no "
    "interpretas, no completas lo que falta y no agregas comentarios propios. Si una parte "
    "es ilegible, escribe [ilegible] en su lugar."
)
_USER = (
    "Transcribe el contenido de estas páginas de un sílabo o programa de curso.\n"
    "- Mantén el orden de lectura y la estructura (unidades, fechas, ponderaciones, reglas).\n"
    "- Las tablas conviértelas en líneas legibles, una fila por línea, separando con ' · '.\n"
    "- No agregues encabezados que no estén en el documento.\n"
    "Devuelve solo el texto transcrito."
)


def transcribir(imagenes: list, llamar=None) -> dict:
    """`imagenes` = [{media_type, data(base64)}] — páginas ya rasterizadas en el cliente."""
    ims = [im for im in (imagenes or [])
           if isinstance(im, dict) and im.get("data")][:_MAX_PAGINAS]
    if not ims:
        raise unprocessable("No recibí ninguna página que transcribir.")

    if llamar is None:
        from app.services.correccion_experta_service import _llamar_anthropic_vision as llamar

    try:
        texto = llamar(_SYSTEM, _USER, ims, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        # No volcar el error del proveedor en la pantalla del docente; distinguir "el
        # servicio está caído" de "tu documento no se entiende" es lo único accionable.
        _LOG.error("silabo OCR: falló la transcripción: %s", e)
        msg = str(e)
        if "authentication_error" in msg or "401" in msg or "api key" in msg.lower():
            raise unprocessable(
                "El lector de documentos escaneados no está disponible ahora mismo. "
                "No es tu archivo: es la conexión con el servicio de IA.")
        raise unprocessable("No pude leer el documento esta vez. Prueba con un escaneo más nítido.")

    texto = (texto or "").strip()
    if not texto:
        raise unprocessable(
            "No encontré texto legible en esas páginas. Prueba con un escaneo más nítido "
            "y derecho, o pega el sílabo como texto.")
    return {"ok": True, "texto": texto, "paginas": len(ims)}
