"""
Test de tamanos de hoja: 20/25/30/40 preguntas. Verifica que el generador produce un PDF
y -clave- que el lector lee EXACTAMENTE N respuestas (25 no se redondea a 26), con columnas
desiguales (13+12) cuando N es impar.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.services.scan_engine import read_answers
from app.services.sheet_service import generate_answer_sheet_pdf

_COL1 = [87, 103, 119, 135, 151]
_COL2 = [210, 226, 242, 258, 274]
_CHOICES = ["A", "B", "C", "D", "E"]
_FACTOR = 2100.0 / 595.27
_Y0 = 184


def _imagen_con_respuestas(n_questions, respuestas):
    """Hoja sintetica (2100x2970) con una burbuja rellena por pregunta, en la MISMA geometria
    (13+12 para 25) que usa el lector."""
    n_col1 = (n_questions + 1) // 2
    n_col2 = n_questions // 2
    row_gap = min(26.0, 498.0 / (n_col1 - 1)) if n_col1 > 1 else 26.0
    r = int(6.5 * _FACTOR)
    img = np.full((2970, 2100), 255, np.uint8)
    for bub_xs, q_start, n_col in [(_COL1, 0, n_col1), (_COL2, n_col1, n_col2)]:
        for q_idx in range(n_col):
            ans = respuestas[q_start + q_idx]
            cx = int(bub_xs[_CHOICES.index(ans)] * _FACTOR)
            cy = int((_Y0 + q_idx * row_gap) * _FACTOR)
            cv2.circle(img, (cx, cy), r, 0, -1)          # burbuja rellena (negra)
    return img


@pytest.mark.parametrize("n", [20, 25, 30, 40])
def test_lee_tamano_exacto(n):
    respuestas = [_CHOICES[i % 5] for i in range(n)]
    img = _imagen_con_respuestas(n, respuestas)
    answers, ambiguous = read_answers(img, n)
    assert len(answers) == n            # EXACTAMENTE n (25 no se convierte en 26)
    assert answers == respuestas        # cada respuesta leida correctamente
    assert ambiguous == []


@pytest.mark.parametrize("n", [20, 25, 30, 40])
def test_genera_pdf(n):
    pdf = generate_answer_sheet_pdf("aid", "cid", "Morfologia", "Solemne 1", n, "A")
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000


def test_impar_reparte_13_12():
    # 25 -> columna 1 con 13, columna 2 con 12 (no 13+13=26).
    respuestas = [_CHOICES[i % 5] for i in range(25)]
    answers, _ = read_answers(_imagen_con_respuestas(25, respuestas), 25)
    assert len(answers) == 25
