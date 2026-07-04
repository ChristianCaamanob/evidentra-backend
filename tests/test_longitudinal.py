"""Test del motor longitudinal (I3): Hake, tamano de efecto, comparacion y multinivel."""
from __future__ import annotations

import numpy as np

from app.services import longitudinal_service as lg


def _tres_momentos():
    """30 estudiantes, 3 solemnes con mejora sostenida (mismos estudiantes)."""
    rng = np.random.default_rng(5)
    base = rng.normal(50, 12, 30)
    s1 = np.clip(base, 5, 100)
    s2 = np.clip(base + rng.normal(10, 6, 30), 5, 100)
    s3 = np.clip(base + rng.normal(20, 6, 30), 5, 100)
    ids = [f"S{i:03d}" for i in range(30)]
    def nota(p): return np.clip(1 + 6 * p / 100, 1, 7)
    return [
        {"etiqueta": "S1", "pct": s1.tolist(), "nota": nota(s1).tolist(), "student_id": ids},
        {"etiqueta": "S2", "pct": s2.tolist(), "nota": nota(s2).tolist(), "student_id": ids},
        {"etiqueta": "S3", "pct": s3.tolist(), "nota": nota(s3).tolist(), "student_id": ids},
    ]


def test_hake_en_rango():
    m = _tres_momentos()
    h = lg.ganancia_hake(m[0]["pct"], m[-1]["pct"])
    assert h["g_grupo"] is not None and 0 < h["g_grupo"] < 1
    assert h["clase_grupo"] in ("alta", "media", "baja")


def test_hedges_menor_que_cohen():
    m = _tres_momentos()
    ef = lg.tamano_efecto(m[0]["pct"], m[-1]["pct"], pareado=True)
    assert abs(ef["hedges_g"]) < abs(ef["cohen_d"])  # correccion J reduce el sesgo
    assert ef["hedges_g"] > 0                          # hubo mejora
    assert ef["interpretacion_kraft"] in ("pequeno", "mediano (educativamente relevante)", "grande")


def test_comparacion_detecta_mejora():
    m = _tres_momentos()
    c = lg.comparar(m[0]["pct"], m[-1]["pct"], pareado=True)
    assert c["significativo"] is True
    assert c["prueba"] in ("t pareada", "Wilcoxon (signed-rank)")
    assert c["efecto"]["hedges_g"] > 0


def test_multinivel_pendiente_positiva():
    A = lg.analizar_longitudinal(_tres_momentos(), pareado=True)
    ml = A["multinivel"]
    if ml.get("disponible"):
        assert ml["pendiente_por_solemne"] > 0
        assert 0 <= ml["icc_estudiante"] <= 1


def test_orquestador_estructura():
    A = lg.analizar_longitudinal(_tres_momentos(), pareado=True)
    for k in ("momentos", "resumen", "ganancia_hake", "comparacion_extremos", "multinivel", "validez"):
        assert k in A
    assert len(A["resumen"]) == 3
    assert "equating" in A["validez"]


def test_requiere_dos_momentos():
    try:
        lg.analizar_longitudinal([{"etiqueta": "S1", "pct": [50], "nota": [4]}])
        assert False
    except ValueError:
        pass
