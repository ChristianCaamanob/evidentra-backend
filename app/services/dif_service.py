"""
I2 - Validez y equidad: Funcionamiento Diferencial del Item (DIF).

Detecta items que funcionan distinto entre dos grupos (p. ej. seccion, sexo) para
estudiantes de IGUAL habilidad. Es la evidencia de equidad/validez que exigen los
Standards (AERA/APA/NCME) y que usan de rutina PISA y TIMSS.

Dos metodos complementarios:
  - Mantel-Haenszel (numpy puro): DIF UNIFORME. Entrega chi-cuadrado MH, razon de
    momios comun (alpha), el indice ETS Delta = -2.35*ln(alpha) y su clasificacion
    A (despreciable) / B (moderado) / C (grande).
  - Regresion logistica (statsmodels): DIF uniforme Y no uniforme (termino de
    interaccion habilidad x grupo), con pruebas de razon de verosimilitud y tamano de
    efecto Delta R2 de Nagelkerke, clasificado por Jodoin-Gierl.

GOBERNANZA: el DIF requiere una variable de grupo sensible (sexo, seccion...). Solo debe
usarse con consentimiento del estudiante (G4) y sobre datos seudonimizados (G2). El grupo
se pasa explicito: la responsabilidad del consentimiento es de quien invoca.
"""
from __future__ import annotations

import numpy as np
from scipy import stats as _stats

try:
    import statsmodels.api as _sm
except Exception:  # pragma: no cover
    _sm = None


def _clasifica_ets(delta: float, sig: bool) -> str:
    a = abs(delta)
    if not sig or a < 1.0:
        return "A"          # despreciable
    if a < 1.5:
        return "B"          # moderado
    return "C"              # grande


def _clasifica_jodoin_gierl(dr2: float) -> str:
    if dr2 < 0.035:
        return "A"
    if dr2 < 0.070:
        return "B"
    return "C"


def mantel_haenszel(y: np.ndarray, grupo_focal: np.ndarray, matching: np.ndarray,
                    n_estratos: int = 6) -> dict:
    """
    y: 0/1 respuesta al item. grupo_focal: 1 = focal, 0 = referencia.
    matching: puntaje de emparejamiento (habilidad o puntaje total).
    Estratifica el matching en cuantiles y calcula MH.
    """
    y = np.asarray(y, float); g = np.asarray(grupo_focal, int); m = np.asarray(matching, float)
    ok = ~np.isnan(y) & ~np.isnan(m)
    y, g, m = y[ok], g[ok], m[ok]
    # estratos por cuantiles del matching (colapsa si hay pocos)
    qs = np.quantile(m, np.linspace(0, 1, n_estratos + 1))
    qs = np.unique(qs)
    estr = np.clip(np.digitize(m, qs[1:-1]), 0, len(qs) - 2)

    num = den = 0.0
    sa = sea = sva = 0.0
    for k in np.unique(estr):
        s = estr == k
        a = float(((g == 1) & (y == 1) & s).sum())  # focal correcto
        b = float(((g == 1) & (y == 0) & s).sum())  # focal incorrecto
        c = float(((g == 0) & (y == 1) & s).sum())  # ref correcto
        d = float(((g == 0) & (y == 0) & s).sum())  # ref incorrecto
        nk = a + b + c + d
        if nk < 2 or (a + b) == 0 or (c + d) == 0 or (a + c) == 0 or (b + d) == 0:
            continue
        num += a * d / nk
        den += b * c / nk
        sa += a
        sea += (a + b) * (a + c) / nk
        sva += (a + b) * (c + d) * (a + c) * (b + d) / (nk * nk * (nk - 1))
    if den <= 0 or sva <= 0:
        return {"alpha": None, "delta": None, "chi2": None, "p": None,
                "clase_ets": "A", "favorece": None, "significativo": False}
    alpha = num / den
    delta = -2.35 * float(np.log(alpha)) if alpha > 0 else None
    chi2 = (abs(sa - sea) - 0.5) ** 2 / sva
    p = float(_stats.chi2.sf(chi2, 1))
    sig = p < 0.05
    favorece = None
    if delta is not None and sig:
        favorece = "focal" if alpha > 1 else "referencia"
    return {"alpha": round(alpha, 3), "delta": round(delta, 3) if delta is not None else None,
            "chi2": round(float(chi2), 3), "p": round(p, 4),
            "clase_ets": _clasifica_ets(delta if delta is not None else 0.0, sig),
            "favorece": favorece, "significativo": sig}


def _nagelkerke(ll_model, ll_null, n):
    cox = 1 - np.exp((2 / n) * (ll_null - ll_model))
    denom = 1 - np.exp((2 / n) * ll_null)
    return float(cox / denom) if denom > 0 else 0.0


def logistica_dif(y: np.ndarray, grupo_focal: np.ndarray, matching: np.ndarray) -> dict:
    """DIF uniforme y no uniforme por regresion logistica (Swaminathan-Rogers / Zumbo)."""
    if _sm is None:
        return {"disponible": False}
    y = np.asarray(y, float); g = np.asarray(grupo_focal, float); z = np.asarray(matching, float)
    ok = ~np.isnan(y) & ~np.isnan(z)
    y, g, z = y[ok], g[ok], z[ok]
    z = (z - z.mean()) / (z.std() + 1e-9)
    n = len(y)
    try:
        X1 = _sm.add_constant(np.column_stack([z]))
        X2 = _sm.add_constant(np.column_stack([z, g]))
        X3 = _sm.add_constant(np.column_stack([z, g, z * g]))
        m1 = _sm.Logit(y, X1).fit(disp=0)
        m2 = _sm.Logit(y, X2).fit(disp=0)
        m3 = _sm.Logit(y, X3).fit(disp=0)
    except Exception:
        return {"disponible": False}
    lr_unif = 2 * (m2.llf - m1.llf)
    lr_noun = 2 * (m3.llf - m2.llf)
    p_unif = float(_stats.chi2.sf(lr_unif, 1))
    p_noun = float(_stats.chi2.sf(lr_noun, 1))
    dr2 = _nagelkerke(m3.llf, m1.llf, n)   # efecto total (M1 -> M3)
    return {"disponible": True,
            "p_uniforme": round(p_unif, 4), "p_no_uniforme": round(p_noun, 4),
            "delta_r2": round(dr2, 4), "clase_jodoin_gierl": _clasifica_jodoin_gierl(dr2),
            "tipo": ("no_uniforme" if p_noun < 0.05 else "uniforme" if p_unif < 0.05 else "sin_dif")}


def analizar_dif(X, grupo, matching, items_meta: list | None = None,
                 etiqueta_focal=None) -> dict:
    """
    X: matriz persona x item (0/1). grupo: etiqueta por persona (2 categorias).
    matching: habilidad (theta) o puntaje por persona. items_meta: [{item, ra}] opcional.
    """
    X = np.asarray(X, float)
    grupo = np.asarray(grupo)
    cats = list(dict.fromkeys(grupo.tolist()))
    if len(cats) != 2:
        raise ValueError("El DIF requiere exactamente 2 grupos.")
    focal = etiqueta_focal if etiqueta_focal in cats else cats[-1]
    ref = [c for c in cats if c != focal][0]
    g = (grupo == focal).astype(int)
    n, k = X.shape
    meta = {m["item"]: m for m in (items_meta or [])}

    resultados = []
    for j in range(k):
        mh = mantel_haenszel(X[:, j], g, matching)
        lr = logistica_dif(X[:, j], g, matching)
        # Bandera combinada: DIF relevante SOLO si hay SIGNIFICANCIA ademas de tamano de
        # efecto B/C (evita falsos positivos por ruido con muestras chicas).
        mh_dif = mh["clase_ets"] in ("B", "C")  # _clasifica_ets ya exige p<0.05
        lr_sig = lr.get("disponible") and (
            (lr.get("p_uniforme", 1) < 0.05) or (lr.get("p_no_uniforme", 1) < 0.05))
        lr_clase = lr.get("clase_jodoin_gierl", "A") if lr.get("disponible") else "A"
        lr_dif = bool(lr_sig and lr_clase in ("B", "C"))
        clases_activas = [c for c, activo in ((mh["clase_ets"], mh_dif), (lr_clase, lr_dif)) if activo]
        clase = max(clases_activas) if clases_activas else "A"
        resultados.append({
            "item": j + 1, "ra": (meta.get(j + 1, {}) or {}).get("ra"),
            "mh": mh, "logistica": lr, "clase": clase,
            "con_dif": bool(mh_dif or lr_dif),
        })

    con_dif = [r for r in resultados if r["con_dif"]]
    texto = _interpretar(resultados, con_dif, ref, focal)
    return {
        "grupos": {"referencia": ref, "focal": focal,
                   "n_ref": int((g == 0).sum()), "n_focal": int((g == 1).sum())},
        "metodo": "Mantel-Haenszel (ETS A/B/C) + regresion logistica (Jodoin-Gierl)",
        "items": resultados,
        "items_con_dif": [r["item"] for r in con_dif],
        "interpretacion": texto,
        "gobernanza": "El agrupamiento requiere consentimiento del estudiante (G4) y datos seudonimizados (G2).",
    }


def _interpretar(resultados, con_dif, ref, focal) -> str:
    if not con_dif:
        return (f"Ningun item muestra DIF relevante entre '{ref}' y '{focal}': a igual "
                f"habilidad, ambos grupos responden de forma equivalente. Evidencia de "
                f"equidad e imparcialidad del instrumento.")
    partes = []
    for r in con_dif:
        mh = r["mh"]
        fav = mh.get("favorece")
        favtxt = (f"favorece a {focal if fav == 'focal' else ref}"
                  if fav else "con funcionamiento diferencial")
        partes.append(f"P{r['item']} (clase {r['clase']}, {favtxt})")
    return (f"{len(con_dif)} item(es) muestran DIF relevante: {', '.join(partes)}. "
            f"Conviene revisarlos por posible sesgo (lenguaje, contexto o contenido que "
            f"ventaje a un grupo con igual habilidad) antes de usarlos en decisiones.")
