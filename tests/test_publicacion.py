"""Test del paquete de publicacion (I5): ensamblado de todo el pipeline."""
from __future__ import annotations

import numpy as np
from scipy.special import expit

from app.services import curso_stats_service as css
from app.services import irt_service as irt
from app.services import longitudinal_service as lg
from app.services import publicacion_service as pub


def _ctt_irt():
    rng = np.random.default_rng(9)
    n, k = 40, 12
    theta = rng.normal(0, 1, n)
    b = np.linspace(-1.2, 1.2, k)
    X = (rng.random((n, k)) < expit(theta[:, None] - b[None, :])).astype(int)
    pauta = {i + 1: "A" for i in range(k)}
    alumnos = [{"student_id": f"S{p:02d}",
                "respuestas": {i + 1: ("A" if X[p, i] else "B") for i in range(k)}}
               for p in range(n)]
    te = {i + 1: {"ra": f"RA{(i % 3) + 1}", "bloom": "Comprension", "unidad": "U1"} for i in range(k)}
    ctt = css.analizar_evaluacion(alumnos, pauta, te_tags=te)
    rasch = irt.estimar_rasch(X)
    return ctt, rasch


def _lng():
    rng = np.random.default_rng(4)
    base = rng.normal(50, 12, 25)
    m = lambda add: np.clip(base + add + rng.normal(0, 5, 25), 5, 100).tolist()
    ids = [f"S{i:02d}" for i in range(25)]
    nota = lambda p: [round(1 + 6 * x / 100, 2) for x in p]
    M = [{"etiqueta": "S1", "pct": m(0), "nota": nota(m(0)), "student_id": ids},
         {"etiqueta": "S2", "pct": m(12), "nota": nota(m(12)), "student_id": ids}]
    return lg.analizar_longitudinal(M, pareado=True)


def test_paquete_completo():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete(
        {"titulo": "Estudio X", "asignatura": "Morfologia", "instrumento": "Solemne 1"},
        ctt, rasch, lng=_lng())
    for k in ("titulo", "resumen", "metodos", "resultados", "tablas", "figuras",
              "limitaciones", "etica", "reproducibilidad", "referencias"):
        assert k in pkg and pkg[k]
    # tablas minimas: descriptivos, items, longitudinal
    titulos = [t["titulo"] for t in pkg["tablas"]]
    assert any("descriptivos" in t.lower() for t in titulos)
    assert any("item" in t.lower() for t in titulos)


def test_metodos_menciona_rasch_y_kr20():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete({"instrumento": "X"}, ctt, rasch)
    assert "Rasch" in pkg["metodos"]
    assert "KR-20" in pkg["metodos"] or "KR-20" in pkg["resultados"]


def test_resultados_incluye_numeros():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete({"instrumento": "X"}, ctt, rasch)
    assert str(ctt["confiabilidad_kr20"]) in pkg["resultados"]


def test_etica_y_reproducibilidad():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete({"instrumento": "X"}, ctt, rasch)
    assert "IRB" in pkg["etica"] or "etica" in pkg["etica"].lower()
    assert "umbrales" in pkg["reproducibilidad"]
    assert "girth" in pkg["reproducibilidad"]["validacion"]


def test_referencias_clave():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete({"instrumento": "X"}, ctt, rasch)
    refs = " ".join(pkg["referencias"])
    for autor in ("Rasch", "Kraft", "Braun", "AERA"):
        assert autor in refs


def test_sin_dif_ni_longitudinal():
    ctt, rasch = _ctt_irt()
    pkg = pub.ensamblar_paquete({"instrumento": "X"}, ctt, rasch)  # sin dif ni lng
    titulos = [t["titulo"] for t in pkg["tablas"]]
    assert not any("DIF" in t for t in titulos)  # tabla DIF ausente
