"""
Test de R - Psicometria de rubricas (+ G-theory).

Validaciones contra resultados conocidos:
  - G relativo == alpha de Cronbach (identidad teorica del diseno p x i) -> se cruza con I7.
  - el estudio D es monotono creciente y proyecta mas criterios para subir la fiabilidad.
  - la discriminacion criterio-resto separa un criterio informativo de uno ruidoso.
  - categorias desordenadas se detectan; halo se detecta cuando el evaluador no diferencia.
"""
from __future__ import annotations

import numpy as np

from app.services import rubrica_psicometria_service as rp
from app.services import dimensionalidad_service as dz


def _rubrica_correlacionada(seed=1, n=80, k=5, carga=0.7):
    """Estudiantes con habilidad latente; niveles 0/1/2 por umbrales -> criterios coherentes."""
    rng = np.random.default_rng(seed)
    hab = rng.normal(0, 1, n)
    X = np.empty((n, k))
    for j in range(k):
        lat = carga * hab + np.sqrt(1 - carga ** 2) * rng.normal(0, 1, n)
        X[:, j] = np.digitize(lat, [-0.5, 0.5])   # -> 0,1,2
    return X


def _registros_desde_matriz(X, criterios=None):
    cod = {0: "no_logrado", 1: "parcial", 2: "logrado"}
    criterios = criterios or [f"C{j}" for j in range(X.shape[1])]
    regs = []
    for i in range(X.shape[0]):
        for j in range(X.shape[1]):
            regs.append({"alumno": f"al{i}", "criterio": criterios[j],
                         "nivel_docente": cod[int(X[i, j])]})
    return regs


def test_g_relativo_igual_a_alpha():
    X = _rubrica_correlacionada()
    g = rp.g_theory(X)["coef_g_relativo"]
    a = dz.alpha_cronbach(X)["alpha"]
    assert abs(g - a) < 1e-3          # identidad teorica: G relativo == alpha


def test_estudio_d_monotono_y_proyecta():
    X = _rubrica_correlacionada(k=4)
    d = rp.estudio_d(X, objetivo=0.9)
    Gs = [p["G"] for p in d["proyeccion"]]
    assert all(b >= a for a, b in zip(Gs, Gs[1:]))       # monotono creciente
    assert d["n_criterios_necesarios"] >= d["n_criterios_actual"]  # para G=0,9 hacen falta mas


def test_discriminacion_distingue_criterio_ruidoso():
    rng = np.random.default_rng(5)
    X = _rubrica_correlacionada(seed=5, n=100, k=4)
    # anexar un criterio de PURO RUIDO (independiente de los demas)
    ruido = rng.integers(0, 3, size=(100, 1)).astype(float)
    Xr = np.hstack([X, ruido])
    criterios = [f"C{j}" for j in range(4)] + ["ruido"]
    ests = rp.estadigrafos_criterios(Xr, criterios)
    disc = {e["criterio"]: e["discriminacion"] for e in ests}
    assert disc["ruido"] < 0.3                            # el ruidoso no discrimina
    assert np.mean([disc[f"C{j}"] for j in range(4)]) > disc["ruido"]


def test_categorias_ordenadas_en_rubrica_coherente():
    X = _rubrica_correlacionada(n=120, k=5)
    fc = rp.funcionamiento_categorias(X, [f"C{j}" for j in range(5)])
    assert fc["ordenados"] is True
    assert "funcionan" in fc["veredicto"].lower()


def test_halo_se_detecta_cuando_no_hay_diferenciacion():
    # Todos los criterios identicos -> correlacion ~1 -> halo.
    rng = np.random.default_rng(9)
    base = rng.integers(0, 3, size=(60, 1)).astype(float)
    X = np.repeat(base, 4, axis=1)
    h = rp.deteccion_halo(X, [f"C{j}" for j in range(4)])
    assert h["halo"] is True
    assert len(h["pares_redundantes"]) > 0


def test_sin_halo_en_criterios_diversos():
    X = _rubrica_correlacionada(carga=0.55)
    h = rp.deteccion_halo(X, [f"C{j}" for j in range(X.shape[1])])
    assert h["halo"] is False


def test_orquestador_completo_desde_registros():
    X = _rubrica_correlacionada(n=60, k=4)
    regs = _registros_desde_matriz(X)
    rep = rp.analizar_rubrica(regs)
    assert rep["n_estudiantes"] == 60 and rep["n_criterios"] == 4
    assert "coef_g_relativo" in rep["g_theory"]
    assert rep["estudio_d"]["disponible"] is True
    assert len(rep["por_criterio"]) == 4
    # coherencia interna: G del reporte == alpha del reporte
    assert abs(rep["g_theory"]["coef_g_relativo"] - rep["fiabilidad"]["alpha"]) < 1e-3


def test_phi_no_supera_a_g():
    # Phi (absoluto) es siempre <= G (relativo): incluye mas fuentes de error.
    X = _rubrica_correlacionada()
    g = rp.g_theory(X)
    assert g["coef_phi_absoluto"] <= g["coef_g_relativo"] + 1e-9
