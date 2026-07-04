"""Test del motor cualitativo (I4): concepciones desde distractores + codificacion tematica."""
from __future__ import annotations

from app.services import cualitativo_service as cq


def _items_ctt():
    return [
        {"item": 9, "ra": "RA3", "distractores": {
            "A": {"pct": 10, "correcta": False}, "B": {"pct": 6, "correcta": False},
            "C": {"pct": 22, "correcta": False}, "D": {"pct": 62, "correcta": True}}},
        {"item": 7, "ra": "RA3", "distractores": {
            "A": {"pct": 35, "correcta": False}, "B": {"pct": 8, "correcta": False},
            "C": {"pct": 12, "correcta": False}, "D": {"pct": 45, "correcta": True}}},
    ]


def _contenido():
    return {
        9: {"enunciado": "Función del urotelio", "correcta": "D",
            "concepciones": {"C": "Confunde el urotelio con un epitelio de protección mecánica."}},
        7: {"enunciado": "Identificar epitelio en imagen", "correcta": "D",
            "concepciones": {"A": "Lee un plano estratificado como epitelio simple."}},
    }


def test_mapa_concepciones_filtra_y_ordena():
    R = cq.mapa_concepciones(_items_ctt(), _contenido(), umbral_pct=15)
    # distractores >=15%: item7 A(35), item9 C(22). El correcto (D) nunca entra.
    items = [(e["item"], e["alternativa"]) for e in R["concepciones"]]
    assert (7, "A") in items and (9, "C") in items
    assert all(e["alternativa"] != "D" for e in R["concepciones"])
    # ordenado por prevalencia desc
    assert R["concepciones"][0]["prevalencia_pct"] >= R["concepciones"][-1]["prevalencia_pct"]
    # severidad
    top = R["concepciones"][0]
    assert top["item"] == 7 and top["severidad"] == "alta"
    assert "plano estratificado" in top["concepcion"]


def test_mapa_concepciones_umbral():
    R = cq.mapa_concepciones(_items_ctt(), _contenido(), umbral_pct=40)
    # solo item7 A (35) NO pasa; nada >=40 salvo... ninguno
    assert R["n_concepciones"] == 0


def test_resumen_por_ra():
    R = cq.mapa_concepciones(_items_ctt(), _contenido(), umbral_pct=15)
    assert R["por_ra"][0]["ra"] == "RA3"


def test_codificacion_tematica_palabras_clave():
    codebook = [
        {"codigo": "confunde_justif_excul", "tema": "Antijuridicidad", "tipo": "deductivo",
         "definicion": "...", "palabras_clave": ["justificación", "exculpación"]},
        {"codigo": "error_prohibicion", "tema": "Culpabilidad", "tipo": "deductivo",
         "definicion": "...", "palabras_clave": ["error de prohibición", "prohibición"]},
    ]
    resp = [
        {"student_id": "S1", "texto": "El estudiante confunde justificación con exculpación."},
        {"student_id": "S2", "texto": "Trata el error de prohibición como error de tipo."},
        {"student_id": "S3", "texto": "Respuesta sin relación."},
    ]
    R = cq.codificacion_tematica(resp, codebook)
    assert R["n_respuestas"] == 3
    cods = {c["codigo"] for c in R["codigos"]}
    assert "confunde_justif_excul" in cods and "error_prohibicion" in cods
    # calidad: 2 de 3 cubiertas
    assert R["calidad"]["cobertura_pct"] == round(2 / 3 * 100, 1)
    temas = {t["tema"] for t in R["temas"]}
    assert "Antijuridicidad" in temas and "Culpabilidad" in temas


def test_seam_coder_personalizado():
    codebook = [{"codigo": "X", "tema": "T", "palabras_clave": []}]
    resp = [{"student_id": "S1", "texto": "cualquier cosa"}]
    R = cq.codificacion_tematica(resp, codebook, coder=lambda t: ["X"])
    assert R["codificacion"][0]["codigos"] == ["X"]
