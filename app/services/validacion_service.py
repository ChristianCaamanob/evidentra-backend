"""
F3 - Validacion graduada del docente (cierre del modulo de desarrollo).

La IA pre-califico (F2); aqui el docente VALIDA con el esfuerzo que elija:

  - Auditoria LIGERA  : revisa solo lo que la IA marco (baja confianza / creativo).
  - Auditoria MEDIA   : lo marcado + una muestra de control de los de alta confianza.
  - Auditoria PROFUNDA: revisa todo.
  - Modo MASIVO       : aprueba en bloque lo de confianza >= umbral (p. ej. 90%),
                        dejando el resto para revisar.

Cada decision se registra (trazabilidad inmutable, G5). La nota final la fija el docente
(G1). El acuerdo IA<->docente se mide con QWK como metrica de calidad viva que alimenta al
modulo Investigador (MFRM, G-theory).
"""
from __future__ import annotations

from app.services.precalificacion_service import qwk, _PUNTAJE
from app.services.result_service import calculate_grade

MODO_LIGERA = "ligera"
MODO_MEDIA = "media"
MODO_PROFUNDA = "profunda"
MODOS = (MODO_LIGERA, MODO_MEDIA, MODO_PROFUNDA)


def plan_auditoria(precalifs: list[dict], modo: str = MODO_LIGERA, muestra_cada: int = 5) -> dict:
    """
    precalifs: [{ref, criterio, nivel_ia, confianza, requiere_revision, peso?}].
    Devuelve que se revisa y que se auto-aprueba segun el modo. La muestra de la auditoria
    media es DETERMINISTA (cada N no marcados) para reproducibilidad.
    """
    a_revisar, auto = [], []
    contador_no_marcado = 0
    for p in precalifs:
        marcado = p.get("requiere_revision", False)
        if modo == MODO_PROFUNDA:
            a_revisar.append(p)
        elif modo == MODO_LIGERA:
            (a_revisar if marcado else auto).append(p)
        else:  # media
            if marcado:
                a_revisar.append(p)
            else:
                contador_no_marcado += 1
                (a_revisar if (contador_no_marcado % muestra_cada == 0) else auto).append(p)
    n = len(precalifs)
    return {
        "modo": modo, "total": n,
        "a_revisar": a_revisar, "auto_aprobados": auto,
        "n_revisar": len(a_revisar), "n_auto": len(auto),
        "esfuerzo_pct": round(len(a_revisar) / n * 100, 1) if n else 0.0,
        "nota": ("El docente revisa solo lo marcado." if modo == MODO_LIGERA else
                 "El docente revisa lo marcado + una muestra de control." if modo == MODO_MEDIA else
                 "El docente revisa todas las respuestas."),
    }


def modo_masivo_aprobar(precalifs: list[dict], umbral_conf: float = 0.9) -> dict:
    """Aprueba en bloque lo de confianza >= umbral y no marcado; el resto queda pendiente."""
    auto = [p for p in precalifs if p.get("confianza", 0) >= umbral_conf and not p.get("requiere_revision")]
    pendientes = [p for p in precalifs if p not in auto]
    return {"umbral": umbral_conf, "auto_aprobados": auto, "pendientes": pendientes,
            "n_auto": len(auto), "n_pendientes": len(pendientes)}


def registrar_validacion(ref: str, criterio: str, nivel_ia: str, confianza: float,
                         nivel_docente: str, docente: str, comentario: str | None = None,
                         timestamp: str | None = None) -> dict:
    """Construye el registro de trazabilidad (pre-eval IA + accion docente)."""
    accion = "aprobado" if nivel_docente == nivel_ia else "ajustado"
    reg = {"respuesta_ref": ref, "criterio": criterio,
           "nivel_ia": nivel_ia, "confianza_ia": round(float(confianza), 2),
           "nivel_docente": nivel_docente, "accion": accion,
           "comentario": comentario, "docente": docente}
    if timestamp:
        reg["created_at"] = timestamp
    return reg


def acuerdo_qwk(registros: list[dict]) -> dict:
    """QWK entre el nivel de la IA y el nivel final del docente (metrica de calidad viva)."""
    ia = [r["nivel_ia"] for r in registros]
    doc = [r["nivel_docente"] for r in registros]
    val = qwk(ia, doc)
    n_ajustados = sum(1 for r in registros if r["accion"] == "ajustado")
    return {"qwk": val, "n": len(registros), "ajustados": n_ajustados,
            "tasa_ajuste_pct": round(n_ajustados / len(registros) * 100, 1) if registros else 0.0,
            "calidad": ("operativa" if val >= 0.8 else "aceptable" if val >= 0.7 else "revisar calibracion"),
            "nota": "QWK >= 0.70 aceptable, >= 0.80 operativo (estandar de acuerdo IA<->humano)."}


def nota_final(criterios_validados: list[dict], escala: str = "chile_1_7",
               exigencia: float = 60.0) -> dict:
    """
    criterios_validados: [{nivel_docente, peso}]. Calcula el % de logro ponderado y la nota
    en la escala. Es la nota del DOCENTE (los niveles ya son su decision final).
    """
    total = sum(c.get("peso", 1.0) for c in criterios_validados) or 1.0
    logro = sum(_PUNTAJE.get(c["nivel_docente"], 0.0) * c.get("peso", 1.0)
                for c in criterios_validados) / total
    pct = round(logro * 100, 1)
    nota, etiqueta, aprob = calculate_grade(pct, escala, exigencia)
    return {"logro_pct": pct, "nota": round(nota, 1), "etiqueta": etiqueta,
            "aprobado": bool(aprob), "responsable": "docente",
            "gobernanza": "Nota fijada por el docente (G1, indelegable); la IA solo propuso."}
