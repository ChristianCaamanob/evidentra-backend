"""
Fases 4-5 del pipeline Investigador — validez estructural confirmatoria.

Fase 4 · Analisis Factorial Confirmatorio (CFA) de 1 factor:
  - indices de ajuste que exige toda revista: chi2/gl, CFI, TLI, RMSEA, SRMR
  - cargas estandarizadas, AVE (varianza extraida) y fiabilidad compuesta (CR/omega)
Fase 5 · Evidencia de invarianza entre 2 grupos consentidos:
  - CFA por grupo (invarianza configural: la estructura de 1 factor se sostiene en ambos)
  - congruencia de Tucker entre las cargas de los 2 grupos (invarianza del patron)

Estimacion por maxima verosimilitud (ML). Para items estrictamente dicotomicos, WLSMV con
correlaciones policoricas es el ideal metodologico; ML sobre 0/1 es una aproximacion habitual
y se declara como tal. Agregado y seudonimizado (G2); no altera notas (G1).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from app.core.errors import conflict

warnings.filterwarnings("ignore")


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), d)


def _cargas_std(model):
    ins = model.inspect(std_est=True)
    car = ins[(ins["op"] == "~") & (ins["rval"] == "F")]
    return car["Est. Std"].to_numpy(dtype=float), car["lval"].tolist()


def _srmr(R_obs, lam):
    """SRMR desde la correlacion observada y la implicada por 1 factor (lambda*lambda')."""
    k = R_obs.shape[0]
    Sig = np.outer(lam, lam)
    np.fill_diagonal(Sig, 1.0)
    resid = R_obs - Sig
    idx = np.tril_indices(k, k=0)
    return float(np.sqrt(np.mean(resid[idx] ** 2)))


def _veredicto_ajuste(cfi, rmsea):
    if cfi is None or rmsea is None:
        return "no evaluable"
    if cfi >= 0.95 and rmsea <= 0.06:
        return "buen ajuste"
    if cfi >= 0.90 and rmsea <= 0.08:
        return "ajuste aceptable"
    return "ajuste pobre (revisar modelo/muestra)"


def _fit_1factor(X):
    import semopy
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    if n < 10 or k < 3:
        raise conflict("Datos insuficientes para CFA (>=10 personas y >=3 items).")
    cols = [f"i{j+1}" for j in range(k)]
    df = pd.DataFrame(X, columns=cols).dropna()
    desc = "F =~ " + " + ".join(cols)
    m = semopy.Model(desc)
    m.fit(df)
    st = semopy.calc_stats(m).iloc[0]
    lam, _ = _cargas_std(m)
    R = np.corrcoef(df.to_numpy(), rowvar=False)
    return m, st, lam, R, k


def ajuste_cfa(X) -> dict:
    """CFA de 1 factor: indices de ajuste + cargas + AVE + fiabilidad compuesta."""
    m, st, lam, R, k = _fit_1factor(X)
    cfi = float(st.get("CFI", np.nan)); rmsea = float(st.get("RMSEA", np.nan))
    tli = float(st.get("TLI", np.nan)); chi2 = float(st.get("chi2", np.nan))
    dof = float(st.get("DoF", np.nan)); pval = float(st.get("chi2 p-value", np.nan))
    srmr = _srmr(R, lam)
    ave = float(np.mean(lam ** 2))
    sl = float(np.sum(lam)); err = float(np.sum(1 - lam ** 2))
    cr = sl ** 2 / (sl ** 2 + err) if (sl ** 2 + err) > 0 else None
    cargas = [{"item": i + 1, "carga_std": _r(float(lam[i]), 3),
               "adecuada": bool(lam[i] >= 0.4)} for i in range(k)]
    return {
        "n_items": k,
        "ajuste": {
            "chi2": _r(chi2, 2), "gl": int(dof) if not np.isnan(dof) else None,
            "chi2_gl": _r(chi2 / dof, 2) if dof else None, "p": _r(pval, 4),
            "CFI": _r(cfi), "TLI": _r(tli), "RMSEA": _r(rmsea), "SRMR": _r(srmr),
        },
        "cargas": cargas,
        "convergente": {"AVE": _r(ave), "CR": _r(cr),
                        "ave_ok": bool(ave >= 0.5), "cr_ok": bool(cr is not None and cr >= 0.7)},
        "veredicto": _veredicto_ajuste(cfi, rmsea),
        "umbrales": "Buen ajuste: CFI>=0.95, RMSEA<=0.06, SRMR<=0.08. AVE>=0.50, CR>=0.70.",
        "nota": "Estimacion ML; en items dicotomicos, WLSMV con policoricas es el ideal.",
    }


def invarianza_configural(X, grupo) -> dict:
    """CFA de 1 factor por grupo (configural) + congruencia de Tucker entre las cargas."""
    X = np.asarray(X, dtype=float)
    grupo = np.asarray(grupo)
    cats = list(dict.fromkeys(grupo.tolist()))
    if len(cats) < 2:
        raise conflict("Se requieren 2 grupos para la invarianza.")
    g1, g2 = cats[0], cats[1]
    out = {}
    lams = {}
    for g in (g1, g2):
        Xg = X[grupo == g]
        if Xg.shape[0] < 10:
            raise conflict(f"El grupo '{g}' requiere >=10 personas para el CFA por grupo.")
        _, st, lam, _, _ = _fit_1factor(Xg)
        lams[g] = lam
        out[str(g)] = {"n": int(Xg.shape[0]), "CFI": _r(float(st.get("CFI", np.nan))),
                       "RMSEA": _r(float(st.get("RMSEA", np.nan)))}
    l1, l2 = lams[g1], lams[g2]
    denom = np.sqrt(np.sum(l1 ** 2) * np.sum(l2 ** 2))
    phi = float(np.sum(l1 * l2) / denom) if denom > 0 else None
    ver = ("patron invariante (congruencia alta)" if (phi is not None and phi >= 0.95)
           else "patron similar (congruencia moderada)" if (phi is not None and phi >= 0.85)
           else "patron no invariante")
    return {
        "comparados": [str(g1), str(g2)],
        "por_grupo": out,
        "congruencia_tucker": _r(phi, 3),
        "veredicto": ver,
        "nota": "Invarianza configural (la estructura de 1 factor se sostiene en ambos grupos) + "
                "congruencia de Tucker de las cargas (>=0.95 = patron equivalente).",
    }
