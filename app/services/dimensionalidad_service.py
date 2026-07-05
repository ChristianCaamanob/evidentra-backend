"""
I7 - Dimensionalidad y fiabilidad ampliada (la base de validez que Q1 exige primero).

Antes de creerle a un modelo de Rasch (I1) o a un tamano de efecto, un revisor Q1 pregunta:
el test, ?mide UN constructo o varios? y ?con que fiabilidad? Este modulo responde eso
sobre la matriz persona x item que ya produce el sistema.

  Factorabilidad   : KMO (Kaiser-Meyer-Olkin) + prueba de esfericidad de Bartlett.
  Cuantos factores : autovalores + analisis paralelo de Horn (el estandar moderno; supera
                     al criterio de Kaiser > 1).
  Estructura       : EFA por factorizacion de ejes principales (PAF, comunalidades
                     iteradas) + rotacion varimax.
  Fiabilidad       : Cronbach alpha (con "alpha si se elimina el item"), McDonald omega
                     (congenerico, desde las cargas), KR-20 e ICC(2,k).
  Veredicto        : si el test es esencialmente unidimensional (y por tanto el Rasch de
                     I1 esta justificado) o no.

Todo con numpy/scipy, implementado desde cero y validado contra resultados conocidos
(sin cajas negras). Para items dicotomicos se usan correlaciones de Pearson (phi); la
tetracorica queda como refinamiento futuro y se declara.

Referencias: Horn (1965) parallel analysis; Kaiser (1974) KMO; McDonald (1999) omega;
Cortina (1993) sobre alpha; Reise et al. (2013) sobre unidimensionalidad esencial.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


# --- Preparacion ------------------------------------------------------------------------
def _limpia(X: np.ndarray) -> np.ndarray:
    """Matriz persona x item a float, con borrado por lista de filas incompletas y sin
    items constantes (varianza 0), que no aportan a la correlacion."""
    X = np.asarray(X, dtype=float)
    X = X[~np.isnan(X).any(axis=1)]
    var = X.var(axis=0)
    return X[:, var > 1e-12]


def matriz_correlacion(X: np.ndarray) -> np.ndarray:
    return np.corrcoef(_limpia(X), rowvar=False)


# --- Factorabilidad ---------------------------------------------------------------------
def kmo(R: np.ndarray) -> dict:
    """Kaiser-Meyer-Olkin global y por item (MSA). >0,8 excelente; >0,6 aceptable; <0,5 malo."""
    Rinv = np.linalg.pinv(R)
    d = np.sqrt(np.outer(np.diag(Rinv), np.diag(Rinv)))
    partial = -Rinv / np.where(d == 0, 1e-12, d)   # correlaciones parciales
    np.fill_diagonal(partial, 0.0)
    R0 = R.copy(); np.fill_diagonal(R0, 0.0)
    r2, p2 = (R0 ** 2), (partial ** 2)
    total = r2.sum() / (r2.sum() + p2.sum())
    msa = r2.sum(0) / (r2.sum(0) + p2.sum(0))
    return {"kmo": round(float(total), 3),
            "msa_items": [round(float(v), 3) for v in msa],
            "veredicto": ("excelente" if total >= 0.8 else "aceptable" if total >= 0.6
                          else "mediocre" if total >= 0.5 else "inadecuado")}


def bartlett_esfericidad(R: np.ndarray, n: int) -> dict:
    """Prueba de esfericidad de Bartlett: H0 = la matriz de correlacion es la identidad
    (no factorable). p<0,05 => factorable."""
    p = R.shape[0]
    signo, logdet = np.linalg.slogdet(R)
    chi2 = -(n - 1 - (2 * p + 5) / 6) * logdet
    df = p * (p - 1) / 2
    pval = float(stats.chi2.sf(chi2, df))
    return {"chi2": round(float(chi2), 2), "df": int(df), "p_value": pval,
            "factorable": bool(pval < 0.05)}


# --- Numero de factores -----------------------------------------------------------------
def analisis_paralelo(X: np.ndarray, n_iter: int = 200, percentil: float = 95,
                      seed: int = 17) -> dict:
    """
    Analisis paralelo de Horn: compara los autovalores reales con los de datos ALEATORIOS
    del mismo tamano. Se retienen los factores cuyo autovalor real supera el percentil de
    los aleatorios (corte en el primer cruce). Determinista dado el seed (reproducibilidad).
    """
    Xc = _limpia(X)
    n, p = Xc.shape
    real = np.sort(np.linalg.eigvalsh(np.corrcoef(Xc, rowvar=False)))[::-1]
    rng = np.random.default_rng(seed)
    rand = np.empty((n_iter, p))
    for i in range(n_iter):
        Z = rng.standard_normal((n, p))
        rand[i] = np.sort(np.linalg.eigvalsh(np.corrcoef(Z, rowvar=False)))[::-1]
    umbral = np.percentile(rand, percentil, axis=0)
    n_fac = 0
    for r, u in zip(real, umbral):
        if r > u:
            n_fac += 1
        else:
            break
    return {"autovalores_reales": [round(float(v), 3) for v in real],
            "autovalores_aleatorios_p95": [round(float(v), 3) for v in umbral],
            "n_factores_sugeridos": int(max(1, n_fac)),
            "ratio_primer_segundo": round(float(real[0] / real[1]), 2) if p > 1 else None}


# --- EFA: factorizacion de ejes principales + varimax -----------------------------------
def _varimax(L: np.ndarray, iters: int = 100, tol: float = 1e-6) -> np.ndarray:
    p, k = L.shape
    if k < 2:
        return L
    R = np.eye(k)
    d = 0.0
    for _ in range(iters):
        Lam = L @ R
        B = L.T @ (Lam ** 3 - (Lam @ np.diag(np.diag(Lam.T @ Lam))) / p)
        u, s, vt = np.linalg.svd(B)
        R = u @ vt
        d_old, d = d, s.sum()
        if d_old != 0 and d / d_old < 1 + tol:
            break
    return L @ R


def efa(R: np.ndarray, n_factores: int, rotar: bool = True,
        max_iter: int = 100, tol: float = 1e-4) -> dict:
    """EFA por PAF con comunalidades iteradas (inicio SMC) y rotacion varimax."""
    p = R.shape[0]
    Rinv = np.linalg.pinv(R)
    comm = np.clip(1 - 1 / np.clip(np.diag(Rinv), 1e-6, None), 0.0, 0.99)  # SMC inicial
    vals_k = np.ones(n_factores)
    L = np.zeros((p, n_factores))
    for _ in range(max_iter):
        Rh = R.copy(); np.fill_diagonal(Rh, comm)
        vals, vecs = np.linalg.eigh(Rh)
        idx = np.argsort(vals)[::-1][:n_factores]
        vals_k = np.clip(vals[idx], 0, None)
        L = vecs[:, idx] * np.sqrt(vals_k)
        nueva = (L ** 2).sum(1)
        if np.max(np.abs(nueva - comm)) < tol:
            comm = nueva
            break
        comm = np.clip(nueva, 0, 0.999)
    if rotar and n_factores > 1:
        L = _varimax(L)
    var_expl = (L ** 2).sum(0) / p
    return {"cargas": np.round(L, 3).tolist(),
            "comunalidades": [round(float(c), 3) for c in comm],
            "varianza_explicada": [round(float(v), 3) for v in var_expl],
            "varianza_total": round(float(var_expl.sum()), 3)}


# --- Fiabilidad -------------------------------------------------------------------------
def alpha_cronbach(X: np.ndarray) -> dict:
    """Alpha de Cronbach + 'alpha si se elimina el item' (para depurar el test)."""
    X = _limpia(X)
    n, k = X.shape
    var_items = X.var(axis=0, ddof=1)
    var_total = X.sum(axis=1).var(ddof=1)
    a = k / (k - 1) * (1 - var_items.sum() / var_total) if var_total > 0 and k > 1 else 0.0
    drop = []
    for j in range(k):
        Xj = np.delete(X, j, axis=1)
        vj = Xj.var(axis=0, ddof=1); vt = Xj.sum(axis=1).var(ddof=1)
        kk = k - 1
        aj = kk / (kk - 1) * (1 - vj.sum() / vt) if vt > 0 and kk > 1 else 0.0
        drop.append(round(float(aj), 3))
    return {"alpha": round(float(a), 3), "alpha_si_elimina": drop,
            "veredicto": ("excelente" if a >= 0.9 else "bueno" if a >= 0.8
                          else "aceptable" if a >= 0.7 else "cuestionable" if a >= 0.6 else "pobre")}


def omega_mcdonald(R: np.ndarray) -> dict:
    """Omega total de McDonald (congenerico) desde una solucion de un factor (PAF)."""
    f = efa(R, 1, rotar=False)
    l = np.array(f["cargas"]).ravel()
    sl = l.sum()
    uniq = np.clip(1 - l ** 2, 0, None).sum()
    omega = sl ** 2 / (sl ** 2 + uniq) if (sl ** 2 + uniq) > 0 else 0.0
    return {"omega": round(float(omega), 3)}


def kr20(X: np.ndarray) -> dict:
    """KR-20 (Kuder-Richardson) para items dicotomicos 0/1."""
    X = _limpia(X)
    n, k = X.shape
    p = X.mean(axis=0); q = 1 - p
    var_total = X.sum(axis=1).var(ddof=1)
    val = k / (k - 1) * (1 - (p * q).sum() / var_total) if var_total > 0 and k > 1 else 0.0
    return {"kr20": round(float(val), 3)}


def icc_2k(X: np.ndarray) -> dict:
    """ICC(2,k) y ICC(2,1), modelo de dos vias aleatorio (personas x items), desde ANOVA."""
    X = _limpia(X)
    n, k = X.shape
    grand = X.mean()
    SSR = k * ((X.mean(1) - grand) ** 2).sum()          # entre personas
    SSC = n * ((X.mean(0) - grand) ** 2).sum()          # entre items
    SST = ((X - grand) ** 2).sum()
    SSE = SST - SSR - SSC
    MSR = SSR / (n - 1); MSC = SSC / (k - 1); MSE = SSE / ((n - 1) * (k - 1))
    icc1 = (MSR - MSE) / (MSR + (k - 1) * MSE + k * (MSC - MSE) / n)
    icck = (MSR - MSE) / (MSR + (MSC - MSE) / n)
    return {"icc_2_1": round(float(icc1), 3), "icc_2_k": round(float(icck), 3)}


# --- Orquestador ------------------------------------------------------------------------
def analizar_dimensionalidad(X: np.ndarray, dicotomico: bool = True) -> dict:
    """
    Reporte completo de dimensionalidad + fiabilidad, con veredicto de unidimensionalidad
    esencial (que justifica o no el modelo de Rasch de I1).
    """
    Xc = _limpia(X)
    n, k = Xc.shape
    if k < 3:
        return {"error": "Se requieren al menos 3 items con varianza para el analisis factorial."}
    R = np.corrcoef(Xc, rowvar=False)

    factorab_kmo = kmo(R)
    bart = bartlett_esfericidad(R, n)
    pa = analisis_paralelo(Xc)
    n_fac = pa["n_factores_sugeridos"]
    estructura = efa(R, n_fac)

    fiab = {"alpha_cronbach": alpha_cronbach(Xc), "omega_mcdonald": omega_mcdonald(R),
            "icc": icc_2k(Xc)}
    if dicotomico:
        fiab["kr20"] = kr20(Xc)

    # Unidimensionalidad esencial: factorable + PA sugiere 1 + primer factor domina.
    var_primer = estructura["varianza_explicada"][0]
    ratio = pa["ratio_primer_segundo"] or 99
    unidim = bool(factorab_kmo["kmo"] >= 0.6 and bart["factorable"]
                  and n_fac == 1 and var_primer >= 0.20 and ratio >= 3.0)
    if unidim:
        verdicto = ("Test esencialmente UNIDIMENSIONAL: el modelo de Rasch (I1) esta "
                    "justificado y los puntajes miden un solo constructo.")
    elif n_fac == 1:
        verdicto = ("Un solo factor por analisis paralelo, pero la evidencia es debil "
                    "(KMO/varianza bajos): interpretar con cautela.")
    else:
        verdicto = (f"Test MULTIDIMENSIONAL ({n_fac} factores): el Rasch unidimensional "
                    "no es apropiado sin subescalas o un modelo multidimensional/bifactor.")

    return {
        "n_personas": int(n), "n_items": int(k),
        "factorabilidad": {"kmo": factorab_kmo, "bartlett": bart},
        "n_factores": pa,
        "estructura_efa": estructura,
        "fiabilidad": fiab,
        "unidimensional": unidim,
        "veredicto": verdicto,
        "nota_metodo": ("Correlaciones de Pearson (phi) para items dicotomicos; la tetracorica "
                        "es un refinamiento futuro." if dicotomico else
                        "Correlaciones de Pearson sobre puntajes politomicos."),
        "gobernanza": "Analisis agregado y seudonimizado (G2); no altera notas (G1).",
    }
