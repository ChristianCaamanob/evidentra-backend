"""
Transcripción de respuestas MANUSCRITAS con IA de visión (Claude).

Cierra el análogo de ZipGrade para desarrollo: el docente sube una foto/PDF de la respuesta
escrita a mano; el LLM de visión la TRANSCRIBE fielmente (sin corregir ni calificar) y el
texto vuelve al flujo de pre-calificación por rúbrica (G1: la nota la valida el docente).
Línea roja: transcribe tal cual, marca lo ilegible, no inventa ni interpreta.
"""
from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

MODELO = os.environ.get("EVALYS_REPORT_MODEL", "claude-opus-4-8")

_IMG_OK = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_SISTEMA = (
    "Eres un asistente que TRANSCRIBE fielmente respuestas manuscritas de estudiantes. "
    "Devuelve SOLO el texto tal como el estudiante lo escribió: respeta su redacción y "
    "ortografía, NO corrijas, NO completes, NO califiques ni comentes. Marca las partes "
    "que no puedas leer como [ilegible]. Si la imagen no contiene texto manuscrito, responde "
    "exactamente: (sin respuesta legible)."
)


def transcribir(image_bytes: bytes, media_type: str, enunciado: str = "") -> dict:
    media_type = (media_type or "").lower().split(";")[0].strip()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"transcripcion": "", "motor": "sin IA",
                "nota": "La transcripción manuscrita requiere la clave de IA de visión (ANTHROPIC_API_KEY)."}
    es_pdf = media_type == "application/pdf"
    if not es_pdf and media_type not in _IMG_OK:
        return {"transcripcion": "", "motor": "n/a",
                "nota": "Formato no soportado (" + (media_type or "?") + "). Usa JPG, PNG o PDF."}
    try:
        import anthropic
        b64 = base64.standard_b64encode(image_bytes).decode()
        if es_pdf:
            fuente = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        else:
            fuente = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
        instruccion = ("Transcribe la respuesta manuscrita del estudiante"
                       + (" a la pregunta: «" + enunciado.strip() + "»" if enunciado.strip() else "")
                       + ". Devuelve únicamente la transcripción, sin encabezados ni comillas.")
        cliente = anthropic.Anthropic()
        msg = cliente.messages.create(
            model=MODELO, max_tokens=1500,
            system=_SISTEMA,
            messages=[{"role": "user", "content": [fuente, {"type": "text", "text": instruccion}]}])
        texto = ""
        for b in msg.content:
            if getattr(b, "type", None) == "text":
                texto = b.text.strip()
                break
        return {"transcripcion": texto, "motor": "IA visión (" + MODELO + ")"}
    except Exception as e:
        logger.warning("Transcripción falló: %s", str(e)[:200])
        return {"transcripcion": "", "motor": "error",
                "nota": "No se pudo transcribir: " + str(e)[:160]}
