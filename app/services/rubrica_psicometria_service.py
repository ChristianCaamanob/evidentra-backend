"""
R - Psicometria de rubricas (+ Teoria de la Generalizabilidad).

Trata la RUBRICA como un instrumento de medicion en si misma: cada criterio es un "item"
y cada estudiante recibe un nivel ordenado (no_logrado=0, parcial=1, logrado=2). Responde
lo que un sistema de evaluacion de desarrollo serio necesita saber de su propia rubrica:

  Por criterio     : dificultad (que tan exigente), discriminacion criterio-resto (cuanto
                     separa a fuertes de debiles), distribucion de niveles.
  De la rubrica     : fiabilidad interna (alpha / omega, reusando I7) y "alpha si se elimina
                     el criterio" -> que criterio revisar.
  Categorias        : ?los niveles funcionan? Se revisa con el orden de los umbrales tau
                     (RSM, reusando I6/MFRM). Umbrales desordenados = un nivel (p. ej.
                     'parcial') que nunca es el mas probable -> categoria mal definida.
  Halo/redundancia  : correlaciones inter-criterio excesivas (el evaluador no diferencia) o
                     pares casi identicos (criterios que sobran).
  G-theory          : componentes de varianza (estudiante x criterio), coeficientes G
                     (relativo) y Phi (absoluto), y ESTUDIO D: cuantos criterios se
                     necesitan para una fiabilidad objetivo.

Validacion teorica: el coeficiente G relativo del diseno estudiante x criterio es
EXACTAMENTE el alpha de Cronbach -> se verifica contra I7 (dimensionalidad_service).

Referencias: Cronbach et al. (1972) Generalizability Theory; Brennan (2001) Generalizability
Theory; Andrich (1978) RSM; Jonsson & Svingby (2007) sobre fiabilidad de rubricas.
"""
from __future__ import annotations

import numpy as np

from app.services import dimensionalidad_service as dz
from app.services import mfrm_service as mf

_NIVEL_COD = {"no_logrado": 0, "parcial": 1, "logrado": 2}


# --- Construccion de la matriz estudiante x criterio ------------------------------------
def matriz_desde_registros(registros: list[dict], usar: str = "nivel_docente") -> tuple:
    """
    De los registros de F3 arma la matriz (estudiante x criterio) con el nivel final (por
    defecto el del docente). Solo conserva estudiantes con TODOS los criterios (diseno
    completo, requisito de la G-theory balanceada).
    """
    alumnos, criterios = [], []
    celdas: dict[tuple, int] = {}
    for r in registros:
        al = r.get("alumno") or str(r.get("respuesta_ref", "?")).split("#")[0]
        cr = r.get("criterio", "?")
        niv = r.get(f"{usar}_canon") or r.get(usar)   # canonico (N niveles) si viene; si no, crudo
        if niv not in _NIVEL_COD:
            continue
        if al not in alumnos:
            alumnos.append(al)
        if cr not in criterios:
            criterios.append(cr)
        celdas[(al, cr)] = _NIVEL_COD[niv]
    completos = [a for a in alumnos if all((a, c) in celdas for c in criterios)]
    X = np.array([[celdas[(a, c)] for c in criterios] for a in completos], dtype=float)
    return X, completos, criterios


# --- Estadigrafos por criterio ----------------------------------------------------------
def estadigrafos_criterios(X: np.ndarray, criterios: list[str], n_cat: int = 3) -> list[dict]:
    """Dificultad, discriminacion criterio-resto y distribucion de niveles por criterio."""
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    maxcat = n_cat - 1
    total_resto = X.sum(1)[:, None] - X            # suma de los OTROS criterios
    out = []
    for j in range(k):
        col = X[:, j]
        if col.std() > 1e-9 and total_resto[:, j].std() > 1e-9:
            disc = float(np.corrcoef(col, total_resto[:, j])[0, 1])
        else:
            disc = 0.0
        dist = {lvl: int((col == code).sum()) for lvl, code in _NIVEL_COD.items() if code <= maxcat}
        out.append({
            "criterio": criterios[j],
            "dificultad_pct": round(float(col.mean() / maxcat * 100), 1),   # % de logro medio
            "media_nivel": round(float(col.mean()), 2),
            "discriminacion": round(disc, 3),
            "discrimina": disc >= 0.3,
            "distribucion": dist,
        })
    return out


# --- Fiabilidad de la rubrica (reusa I7) ------------------------------------------------
def fiabilidad_rubrica(X: np.ndarray, criterios: list[str]) -> dict:
    a = dz.alpha_cronbach(X)
    om = dz.omega_mcdonald(dz.matriz_correlacion(X))
    drop = a["alpha_si_elimina"]
    # criterio cuya eliminacion MAS sube el alpha (candidato a revisar)
    peor = None
    if drop:
        j = int(np.argmax(drop))
        if drop[j] > a["alpha"] + 0.01:
            peor = {"criterio": criterios[j], "alpha_sin_el": drop[j]}
    return {"alpha": a["alpha"], "omega": om["omega"], "veredicto": a["veredicto"],
            "alpha_si_elimina": drop, "criterio_a_revisar": peor}


# --- Funcionamiento de las categorias (reusa I6/MFRM) -----------------------------------
def funcionamiento_categorias(X: np.ndarray, criterios: list[str], n_cat: int = 3) -> dict:
    """?Los niveles funcionan? Umbrales tau ordenados (RSM) = categorias bien definidas."""
    obs = []
    n, k = X.shape
    for i in range(n):
        for j in range(k):
            obs.append({"persona": f"p{i}", "item": criterios[j],
                        "evaluador": "final", "categoria": int(X[i, j])})
    modelo = mf.estimar_mfrm(obs, n_cat=n_cat)
    tau = modelo["umbrales_tau"]
    ordenados = all(b > a for a, b in zip(tau, tau[1:])) if len(tau) > 1 else True
    # frecuencia de uso de cada nivel
    uso = {lvl: int((X == code).sum()) for lvl, code in _NIVEL_COD.items() if code < n_cat}
    return {
        "umbrales_tau": tau,
        "ordenados": ordenados,
        "uso_niveles": uso,
        "veredicto": ("Las categorias funcionan: los umbrales estan ordenados; cada nivel es "
                      "el mas probable en algun tramo de logro."
                      if ordenados else
                      "Umbrales DESORDENADOS: algun nivel (p. ej. 'parcial') nunca llega a ser "
                      "el mas probable -> conviene fusionar o redefinir ese nivel."),
    }


# --- Halo y redundancia -----------------------------------------------------------------
def deteccion_halo(X: np.ndarray, criterios: list[str], umbral: float = 0.85) -> dict:
    """Halo = el evaluador no diferencia (correlaciones inter-criterio uniformemente altas).
    Redundancia = pares de criterios casi identicos."""
    R = dz.matriz_correlacion(X)
    k = R.shape[0]
    off = R[~np.eye(k, dtype=bool)]
    media = float(off.mean())
    redundantes = [{"par": [criterios[i], criterios[j]], "r": round(float(R[i, j]), 3)}
                   for i in range(k) for j in range(i + 1, k) if R[i, j] >= umbral]
    return {"correlacion_media_inter_criterio": round(media, 3),
            "halo": bool(media >= umbral),
            "pares_redundantes": redundantes,
            "veredicto": ("Posible efecto HALO: los criterios correlacionan casi perfecto; el "
                          "evaluador podria no estar diferenciandolos." if media >= umbral else
                          "Sin halo evidente: los criterios aportan informacion distinta.")}


# --- G-theory: componentes de varianza + estudios G y D ---------------------------------
def g_theory(X: np.ndarray) -> dict:
    """
    Diseno estudiante (p) x criterio (i), aleatorio de dos vias. Descompone la varianza y
    entrega G (relativo) y Phi (absoluto). G relativo == alpha de Cronbach (se valida).
    """
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    grand = X.mean()
    MSp = k * ((X.mean(1) - grand) ** 2).sum() / (n - 1)
    MSi = n * ((X.mean(0) - grand) ** 2).sum() / (k - 1)
    SSt = ((X - grand) ** 2).sum()
    SSp = k * ((X.mean(1) - grand) ** 2).sum()
    SSi = n * ((X.mean(0) - grand) ** 2).sum()
    MSpi = (SSt - SSp - SSi) / ((n - 1) * (k - 1))

    var_p = max((MSp - MSpi) / k, 0.0)             # varianza de puntaje universo (senal)
    var_i = max((MSi - MSpi) / n, 0.0)             # severidad diferencial de criterios
    var_pi = max(MSpi, 0.0)                         # interaccion + error (ruido)

    g_rel = var_p / (var_p + var_pi / k) if (var_p + var_pi / k) > 0 else 0.0
    phi = var_p / (var_p + (var_i + var_pi) / k) if (var_p + (var_i + var_pi) / k) > 0 else 0.0
    return {
        "n_estudiantes": int(n), "n_criterios": int(k),
        "componentes_varianza": {"estudiante": round(var_p, 4), "criterio": round(var_i, 4),
                                 "residual_pi": round(var_pi, 4)},
        "coef_g_relativo": round(float(g_rel), 3),
        "coef_phi_absoluto": round(float(phi), 3),
        "nota": "G relativo (para decisiones normativas) == alpha de Cronbach; Phi (para "
                "decisiones de criterio/corte) es mas exigente porque incluye la severidad "
                "diferencial de los criterios.",
    }


def estudio_d(X: np.ndarray, objetivo: float = 0.8, max_criterios: int = 12) -> dict:
    """
    Estudio D: proyecta G (relativo) para distintos numeros de criterios y calcula cuantos
    se necesitan para alcanzar la fiabilidad objetivo (Spearman-Brown sobre la G-theory).
    """
    g = g_theory(X)
    var_p = g["componentes_varianza"]["estudiante"]
    var_pi = g["componentes_varianza"]["residual_pi"]
    if var_p <= 0:
        return {"disponible": False, "motivo": "Sin varianza entre estudiantes."}

    def G(nc):
        return var_p / (var_p + var_pi / nc)

    proyeccion = [{"n_criterios": nc, "G": round(float(G(nc)), 3)}
                  for nc in range(1, max_criterios + 1)]
    # n necesario: G = vp/(vp+vpi/n) -> n = (vpi/vp) * Gt/(1-Gt)
    if objetivo < 1.0:
        n_nec = int(np.ceil((var_pi / var_p) * (objetivo / (1 - objetivo))))
        n_nec = max(1, n_nec)
    else:
        n_nec = None
    return {"disponible": True, "objetivo": objetivo, "n_criterios_actual": int(X.shape[1]),
            "n_criterios_necesarios": n_nec, "proyeccion": proyeccion,
            "nota": f"Para G={objetivo:g} se necesitan ~{n_nec} criterios equivalentes "
                    f"(hoy hay {X.shape[1]})."}


# --- Orquestador ------------------------------------------------------------------------
def analizar_rubrica(registros: list[dict], usar: str = "nivel_docente",
                     n_cat: int = 3, objetivo_g: float = 0.8) -> dict:
    """Reporte completo de psicometria de la rubrica a partir de los registros validados."""
    X, alumnos, criterios = matriz_desde_registros(registros, usar=usar)
    if X.shape[0] < 3 or X.shape[1] < 2:
        return {"error": "Se requieren >=3 estudiantes con diseno completo y >=2 criterios."}
    return {
        "n_estudiantes": X.shape[0], "n_criterios": X.shape[1], "criterios": criterios,
        "por_criterio": estadigrafos_criterios(X, criterios, n_cat),
        "fiabilidad": fiabilidad_rubrica(X, criterios),
        "categorias": funcionamiento_categorias(X, criterios, n_cat),
        "halo": deteccion_halo(X, criterios),
        "g_theory": g_theory(X),
        "estudio_d": estudio_d(X, objetivo=objetivo_g),
        "gobernanza": "Analisis agregado y seudonimizado (G2); diagnostico de la rubrica, no "
                      "altera notas (G1). Apoya la revision de la rubrica antes de re-versionar (F4).",
    }
