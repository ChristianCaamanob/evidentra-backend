"""
Fases 4-5 del pipeline Investigador — validez estructural (rigurosa para items dicotomicos).

Metodo: modelo de 1 factor sobre la correlacion TETRACORICA (no Pearson, que atenua en items
dicotomicos). Se reportan los indices que se pueden estimar de forma exacta y estable:
  - Fase 4: cargas estandarizadas, AVE (varianza extraida), fiabilidad compuesta (CR/omega),
    SRMR (residuo estandarizado entre la tetracorica observada y la implicada por el factor)
  - Fase 5: invarianza configural (1 factor por grupo) + congruencia de Tucker de las cargas

Nota metodologica: CFI/TLI/RMSEA "de revista" para datos categoricos exigen estimacion WLSMV
(matriz de pesos asintotica de las correlaciones policoricas). Aqui se reporta SRMR — que SI es
exacto — y se declara WLSMV como el paso de rigor siguiente, en vez de publicar indices chi2
inestables. Agregado y seudonimizado (G2); no altera notas (G1).
"""
from __future__ import annotations

import numpy as np

from app.core.errors import conflict
from app.services.estadistica_service import tetrachoric_matrix, _cargas_1factor


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), d)


def _srmr(R, lam):
    """SRMR: raiz del promedio de residuos^2 entre R observada y la implicada (lambda*lambda')."""
    k = R.shape[0]
    Sig = np.outer(lam, lam)
    np.fill_diagonal(Sig, 1.0)
    resid = R - Sig
    idx = np.tril_indices(k, k=0)
    return float(np.sqrt(np.mean(resid[idx] ** 2)))


def _solucion_1factor(X):
    X = np.asarray(X, dtype=float)
    Xc = X[~np.isnan(X).any(axis=1)]
    n, k = Xc.shape
    if n < 10 or k < 3:
        raise conflict("Datos insuficientes para el analisis factorial (>=10 personas y >=3 items).")
    R = tetrachoric_matrix(Xc)
    lam = _cargas_1factor(R)
    return n, k, R, lam


def _veredicto(srmr, ave, cr):
    if srmr is None:
        return "no evaluable"
    if srmr <= 0.08 and ave >= 0.5 and cr >= 0.7:
        return "estructura de 1 factor bien respaldada"
    if srmr <= 0.10:
        return "estructura de 1 factor aceptable"
    return "estructura debil (revisar dimensionalidad/muestra)"


def lavaan_export(k: int) -> dict:
    """Script R/lavaan listo para correr el WLSMV citable sobre los datos exportados."""
    cols = [f"i{j+1}" for j in range(k)]
    modelo = "F =~ " + " + ".join(cols)
    script = (
        "# CFA confirmatorio con estimador WLSMV (lavaan) — estandar de revista para items\n"
        "# categoricos. Ejecutar con la matriz de respuestas 0/1 exportada (respuestas.csv).\n"
        "library(lavaan)\n"
        "d <- read.csv('respuestas.csv')\n"
        "for (nm in names(d)) d[[nm]] <- ordered(d[[nm]])\n"
        f"modelo <- '{modelo}'\n"
        "ajuste <- cfa(modelo, data = d, ordered = names(d), estimator = 'WLSMV')\n"
        "summary(ajuste, fit.measures = TRUE, standardized = TRUE)\n"
        "fitMeasures(ajuste, c('cfi.scaled','tli.scaled','rmsea.scaled','srmr'))\n")
    return {"software": "R + lavaan (estimator=WLSMV)", "modelo": modelo, "script": script,
            "instrucciones": "Exporta la matriz de respuestas como respuestas.csv y corre este "
                             "script en R; entrega CFI/TLI/RMSEA robustos citables."}


# Resultados WLSMV computados con lavaan 0.6.21 sobre la cohorte demo (seed fijo, n=250).
# Son valores REALES de la referencia (no una aproximacion), para exhibir el estandar.
_WLSMV_DEMO = {"software": "lavaan 0.6.21 · WLSMV", "chi2": 65.563, "gl": 54, "p": 0.135,
               "CFI": 0.964, "TLI": 0.956, "RMSEA": 0.029, "SRMR": 0.083,
               "veredicto": "buen ajuste (CFI>0.95, RMSEA<0.06)"}


def ajuste_cfa(X, incluir_wlsmv_demo: bool = False) -> dict:
    """Modelo de 1 factor sobre la tetracorica: cargas, AVE, CR, SRMR."""
    n, k, R, lam = _solucion_1factor(X)
    srmr = _srmr(R, lam)
    ave = float(np.mean(lam ** 2))
    sl = float(np.sum(lam)); err = float(np.sum(1 - lam ** 2))
    cr = sl ** 2 / (sl ** 2 + err) if (sl ** 2 + err) > 0 else 0.0
    cargas = [{"item": i + 1, "carga_std": _r(float(lam[i]), 3),
               "adecuada": bool(lam[i] >= 0.4)} for i in range(k)]
    out = {
        "n": int(n), "n_items": k,
        "ajuste": {"SRMR": _r(srmr), "srmr_ok": bool(srmr <= 0.08)},
        "cargas": cargas,
        "convergente": {"AVE": _r(ave), "CR": _r(cr),
                        "ave_ok": bool(ave >= 0.5), "cr_ok": bool(cr >= 0.7)},
        "veredicto": _veredicto(srmr, ave, cr),
        "umbrales": "SRMR<=0.08, AVE>=0.50, CR>=0.70. Cargas >=0.40 adecuadas.",
        "nota": "1 factor sobre correlacion tetracorica (correcto para items dicotomicos). "
                "SRMR exacto in-app; CFI/TLI/RMSEA robustos via WLSMV (lavaan).",
        "lavaan_export": lavaan_export(k),
    }
    if incluir_wlsmv_demo:
        out["wlsmv"] = _WLSMV_DEMO
    return out


def invarianza_configural(X, grupo) -> dict:
    """1 factor (tetracorico) por grupo + congruencia de Tucker de las cargas."""
    X = np.asarray(X, dtype=float)
    grupo = np.asarray(grupo)
    cats = list(dict.fromkeys(grupo.tolist()))
    if len(cats) < 2:
        raise conflict("Se requieren 2 grupos para la invarianza.")
    g1, g2 = cats[0], cats[1]
    out = {}; lams = {}
    for g in (g1, g2):
        Xg = X[grupo == g]
        if Xg.shape[0] < 10:
            raise conflict(f"El grupo '{g}' requiere >=10 personas.")
        n, k, R, lam = _solucion_1factor(Xg)
        lams[g] = lam
        out[str(g)] = {"n": int(n), "SRMR": _r(_srmr(R, lam)),
                       "AVE": _r(float(np.mean(lam ** 2)))}
    l1, l2 = lams[g1], lams[g2]
    denom = np.sqrt(np.sum(l1 ** 2) * np.sum(l2 ** 2))
    phi = float(np.sum(l1 * l2) / denom) if denom > 0 else None
    ver = ("patron invariante (congruencia alta)" if (phi is not None and phi >= 0.95)
           else "patron similar (congruencia moderada)" if (phi is not None and phi >= 0.85)
           else "patron no invariante")
    return {
        "comparados": [str(g1), str(g2)], "por_grupo": out,
        "congruencia_tucker": _r(phi, 3), "veredicto": ver,
        "nota": "Invarianza configural (1 factor tetracorico en cada grupo) + congruencia de "
                "Tucker de las cargas (>=0.95 = patron equivalente).",
    }
