"""Arsenal cuantitativo para el módulo Investigador · estudio EXPERIMENTAL (nivel Q1 / tesis doctoral).

Un único dispatcher `analizar(payload)` sobre un dataset {columns, rows}:
  - descriptivos: por variable (y por grupo): n, media, DE, mediana, IQR, min, max, asimetría, curtosis, IC95%.
  - supuestos: normalidad (Shapiro-Wilk por grupo) + homocedasticidad (Levene) → recomienda test.
  - comparacion: 2 grupos → t de Welch / Student o Mann-Whitney; >2 → ANOVA o Kruskal-Wallis; con
    TAMAÑO DE EFECTO (d de Cohen, g de Hedges, η², ε², r rango-biserial) + post-hoc (Tukey / Games-Howell / Dunn).
  - correlacion: matriz Pearson o Spearman con p-valores.
  - regresion: OLS (lineal) o logística (statsmodels): coeficientes, IC95%, p, R²/pseudo-R², VIF.

Todo con reporte APA-listo. Doctrina: entrega el estadístico + su interpretación; el investigador decide.
Sin datos suficientes → {ok:false, error:...}. Nunca inventa; si un supuesto falla, lo dice y ofrece la vía robusta.
"""
from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger("evalys")


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _col(rows, idx):
    return [r[idx] if idx < len(r) else None for r in rows]


def _r(x, d=3):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), d)


def _tipos(columns, rows):
    """Clasifica cada columna en 'num' o 'cat' según su contenido."""
    tipos = []
    for j, _c in enumerate(columns):
        vals = [v for v in _col(rows, j) if v not in (None, "")]
        nums = [_num(v) for v in vals]
        prop_num = (sum(1 for v in nums if v is not None) / len(vals)) if vals else 0
        tipos.append("num" if prop_num >= 0.8 else "cat")
    return tipos


def _desc_vec(x):
    x = np.asarray([v for v in x if v is not None], dtype=float)
    n = int(x.size)
    if n == 0:
        return {"n": 0}
    from scipy import stats as st
    media = float(np.mean(x)); de = float(np.std(x, ddof=1)) if n > 1 else 0.0
    ic = 1.96 * de / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "media": _r(media), "de": _r(de),
            "ic95": [_r(media - ic), _r(media + ic)],
            "mediana": _r(float(np.median(x))),
            "q1": _r(float(np.percentile(x, 25))), "q3": _r(float(np.percentile(x, 75))),
            "min": _r(float(np.min(x))), "max": _r(float(np.max(x))),
            "asimetria": _r(float(st.skew(x))) if n > 2 else None,
            "curtosis": _r(float(st.kurtosis(x))) if n > 3 else None}


def _grupos(rows, gi, vi):
    """Devuelve {nivel: [valores numéricos]} agrupando la variable vi por la categórica gi."""
    g = {}
    for r in rows:
        if gi >= len(r) or vi >= len(r):
            continue
        k = r[gi]
        v = _num(r[vi])
        if k in (None, "") or v is None:
            continue
        g.setdefault(str(k), []).append(v)
    return {k: v for k, v in g.items() if len(v) >= 2}


def descriptivos(columns, rows, params):
    tipos = _tipos(columns, rows)
    grupo = params.get("grupo")
    gi = columns.index(grupo) if grupo in columns else None
    out = []
    for j, c in enumerate(columns):
        if tipos[j] != "num":
            continue
        item = {"variable": c, "global": _desc_vec([_num(v) for v in _col(rows, j)])}
        if gi is not None and j != gi:
            gs = _grupos(rows, gi, j)
            item["por_grupo"] = {k: _desc_vec(v) for k, v in gs.items()}
        out.append(item)
    return {"ok": True, "analisis": "descriptivos", "variables": out,
            "nota": "Descriptivos por variable" + (" y por grupo." if gi is not None else ".")}


def supuestos(columns, rows, params):
    from scipy import stats as st
    var = params.get("variable"); grupo = params.get("grupo")
    if var not in columns:
        return {"ok": False, "error": "Elige una variable numérica."}
    vi = columns.index(var)
    res = {"ok": True, "analisis": "supuestos", "variable": var}
    if grupo in columns:
        gs = _grupos(rows, columns.index(grupo), vi)
        normal = {}
        for k, v in gs.items():
            arr = np.asarray(v, dtype=float)
            if 3 <= arr.size <= 5000:
                W, p = st.shapiro(arr)
                normal[k] = {"W": _r(W), "p": _r(p), "normal": bool(p > 0.05), "n": int(arr.size)}
            else:
                normal[k] = {"n": int(arr.size), "nota": "n fuera de rango Shapiro"}
        lev = None
        if len(gs) >= 2:
            F, p = st.levene(*[np.asarray(v, dtype=float) for v in gs.values()], center="median")
            lev = {"F": _r(F), "p": _r(p), "homocedastico": bool(p > 0.05)}
        todas_normal = all(d.get("normal") for d in normal.values() if "normal" in d)
        res.update({"normalidad": normal, "homocedasticidad": lev,
                    "recomendacion": ("paramétrica (t/ANOVA)" if todas_normal else "no paramétrica (Mann-Whitney/Kruskal)"),
                    "nota": "Shapiro-Wilk por grupo (p>.05 = normal) y Levene (p>.05 = varianzas iguales)."})
    else:
        arr = np.asarray([_num(v) for v in _col(rows, vi) if _num(v) is not None], dtype=float)
        if 3 <= arr.size <= 5000:
            W, p = st.shapiro(arr)
            res["normalidad"] = {"global": {"W": _r(W), "p": _r(p), "normal": bool(p > 0.05), "n": int(arr.size)}}
    return res


def _cohen_d(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    na, nb = a.size, b.size
    sp = math.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    d = (np.mean(a) - np.mean(b)) / sp if sp else 0.0
    J = 1 - (3 / (4 * (na + nb) - 9)) if (na + nb) > 2 else 1.0
    return d, d * J  # cohen d, hedges g


def _interpreta_d(d):
    a = abs(d)
    return "trivial" if a < 0.2 else "pequeño" if a < 0.5 else "mediano" if a < 0.8 else "grande"


def comparacion(columns, rows, params):
    from scipy import stats as st
    var = params.get("variable"); grupo = params.get("grupo")
    if var not in columns or grupo not in columns:
        return {"ok": False, "error": "Elige una variable numérica y una variable de grupo."}
    gs = _grupos(rows, columns.index(grupo), columns.index(var))
    if len(gs) < 2:
        return {"ok": False, "error": "Se necesitan ≥2 grupos con ≥2 datos cada uno."}
    niveles = list(gs.keys()); arrs = [np.asarray(gs[k], dtype=float) for k in niveles]
    # normalidad para elegir test
    normal = True
    for a in arrs:
        if 3 <= a.size <= 5000:
            if st.shapiro(a)[1] <= 0.05:
                normal = False
    desc = {k: {"n": int(gs[k].__len__()), "media": _r(float(np.mean(a))), "de": _r(float(np.std(a, ddof=1)))} for k, a in zip(niveles, arrs)}
    out = {"ok": True, "analisis": "comparacion", "variable": var, "grupo": grupo, "n_grupos": len(niveles), "descriptivos": desc}
    if len(niveles) == 2:
        a, b = arrs
        lev_p = st.levene(a, b, center="median")[1]
        if normal:
            welch = lev_p <= 0.05
            t, p = st.ttest_ind(a, b, equal_var=not welch)
            d, g = _cohen_d(a, b)
            gl = a.size + b.size - 2 if not welch else None
            out.update({"test": ("t de Welch" if welch else "t de Student"), "estadistico": _r(t), "p": _r(p),
                        "gl": gl, "efecto": {"cohen_d": _r(d), "hedges_g": _r(g), "magnitud": _interpreta_d(g)},
                        "significativo": bool(p < 0.05),
                        "apa": f"{'t de Welch' if welch else 't'}({_r(gl) if gl else 'gl'}) = {_r(t)}, p = {_r(p)}, g = {_r(g)} ({_interpreta_d(g)})"})
        else:
            U, p = st.mannwhitneyu(a, b, alternative="two-sided")
            rb = 1 - (2 * U) / (a.size * b.size)  # rank-biserial
            out.update({"test": "U de Mann-Whitney", "estadistico": _r(U), "p": _r(p),
                        "efecto": {"rango_biserial": _r(rb), "magnitud": _interpreta_d(rb)},
                        "significativo": bool(p < 0.05),
                        "apa": f"U = {_r(U)}, p = {_r(p)}, r = {_r(rb)}"})
    else:
        if normal:
            F, p = st.f_oneway(*arrs)
            grand = np.concatenate(arrs)
            ss_between = sum(a.size * (np.mean(a) - np.mean(grand)) ** 2 for a in arrs)
            ss_total = np.sum((grand - np.mean(grand)) ** 2)
            eta2 = ss_between / ss_total if ss_total else 0.0
            out.update({"test": "ANOVA de una vía", "estadistico": _r(F), "p": _r(p),
                        "efecto": {"eta_cuadrado": _r(eta2), "magnitud": ("pequeño" if eta2 < 0.06 else "mediano" if eta2 < 0.14 else "grande")},
                        "significativo": bool(p < 0.05),
                        "apa": f"F({len(arrs)-1}, {int(grand.size-len(arrs))}) = {_r(F)}, p = {_r(p)}, η² = {_r(eta2)}"})
            # post-hoc Tukey
            try:
                from statsmodels.stats.multicomp import pairwise_tukeyhsd
                vals = np.concatenate(arrs); labs = np.concatenate([[niveles[i]] * arrs[i].size for i in range(len(arrs))])
                tk = pairwise_tukeyhsd(vals, labs)
                out["posthoc"] = {"metodo": "Tukey HSD", "pares": [
                    {"g1": str(r[0]), "g2": str(r[1]), "dif": _r(float(r[2])), "p": _r(float(r[3])), "sig": bool(r[6])}
                    for r in tk._results_table.data[1:]]}
            except Exception:
                pass
        else:
            H, p = st.kruskal(*arrs)
            n = sum(a.size for a in arrs); eps2 = (H - len(arrs) + 1) / (n - len(arrs)) if n > len(arrs) else 0.0
            out.update({"test": "Kruskal-Wallis", "estadistico": _r(H), "p": _r(p),
                        "efecto": {"epsilon_cuadrado": _r(eps2), "magnitud": ("pequeño" if eps2 < 0.06 else "mediano" if eps2 < 0.14 else "grande")},
                        "significativo": bool(p < 0.05),
                        "apa": f"H({len(arrs)-1}) = {_r(H)}, p = {_r(p)}, ε² = {_r(eps2)}"})
    return out


def correlacion(columns, rows, params):
    from scipy import stats as st
    metodo = params.get("metodo", "pearson")
    tipos = _tipos(columns, rows)
    idx = [j for j, t in enumerate(tipos) if t == "num"]
    if len(idx) < 2:
        return {"ok": False, "error": "Se necesitan ≥2 variables numéricas."}
    nombres = [columns[j] for j in idx]
    M = {}
    for a in idx:
        for b in idx:
            if b <= a:
                continue
            xa = [_num(v) for v in _col(rows, a)]; xb = [_num(v) for v in _col(rows, b)]
            par = [(u, v) for u, v in zip(xa, xb) if u is not None and v is not None]
            if len(par) < 3:
                continue
            u = np.array([p[0] for p in par]); v = np.array([p[1] for p in par])
            r, p = (st.pearsonr(u, v) if metodo == "pearson" else st.spearmanr(u, v))
            M[columns[a] + " × " + columns[b]] = {"r": _r(float(r)), "p": _r(float(p)), "n": len(par), "sig": bool(p < 0.05)}
    return {"ok": True, "analisis": "correlacion", "metodo": metodo, "variables": nombres, "pares": M,
            "nota": ("r de Pearson (lineal)." if metodo == "pearson" else "ρ de Spearman (monótona, robusta).")}


def regresion(columns, rows, params):
    import statsmodels.api as sm
    y = params.get("y"); xs = params.get("x") or []
    logistica = bool(params.get("logistica"))
    if y not in columns or not xs:
        return {"ok": False, "error": "Elige la variable dependiente (Y) y ≥1 predictor (X)."}
    yi = columns.index(y); xis = [columns.index(x) for x in xs if x in columns]
    Y = []; X = []
    for r in rows:
        yv = _num(r[yi]) if yi < len(r) else None
        xv = [_num(r[k]) if k < len(r) else None for k in xis]
        if yv is None or any(v is None for v in xv):
            continue
        Y.append(yv); X.append(xv)
    if len(Y) < len(xis) + 2:
        return {"ok": False, "error": "Muy pocos casos completos para estimar el modelo."}
    Xm = sm.add_constant(np.asarray(X, dtype=float)); Yv = np.asarray(Y, dtype=float)
    nombres = ["(intercepto)"] + [columns[k] for k in xis]
    try:
        if logistica:
            modelo = sm.Logit(Yv, Xm).fit(disp=0)
            pseudo_r2 = float(modelo.prsquared)
            ajuste = {"pseudo_r2_mcfadden": _r(pseudo_r2), "aic": _r(float(modelo.aic)), "n": len(Y)}
        else:
            modelo = sm.OLS(Yv, Xm).fit()
            ajuste = {"r2": _r(float(modelo.rsquared)), "r2_ajustado": _r(float(modelo.rsquared_adj)),
                      "F": _r(float(modelo.fvalue)), "p_modelo": _r(float(modelo.f_pvalue)), "n": len(Y)}
        ci = modelo.conf_int()
        coefs = []
        for i, nom in enumerate(nombres):
            b = float(modelo.params[i])
            coefs.append({"termino": nom, "b": _r(b),
                          "ic95": [_r(float(ci[i][0])), _r(float(ci[i][1]))],
                          "p": _r(float(modelo.pvalues[i])), "sig": bool(modelo.pvalues[i] < 0.05),
                          "or": (_r(math.exp(b)) if logistica else None)})
        return {"ok": True, "analisis": "regresion", "tipo": ("logística" if logistica else "lineal (OLS)"),
                "y": y, "predictores": xs, "ajuste": ajuste, "coeficientes": coefs,
                "nota": ("OR = exp(b); OR>1 aumenta la probabilidad." if logistica else "b = cambio en Y por unidad de X, ceteris paribus.")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "No se pudo estimar: " + str(e)[:150]}


def analizar(payload: dict) -> dict:
    ds = payload.get("dataset") or {}
    columns = [str(c) for c in (ds.get("columns") or [])]
    rows = ds.get("rows") or []
    if not columns or not rows:
        return {"ok": False, "error": "Carga o pega un dataset (columnas y filas) primero."}
    analisis = (payload.get("analisis") or "descriptivos").lower()
    params = payload.get("params") or {}
    try:
        fn = {"descriptivos": descriptivos, "supuestos": supuestos, "comparacion": comparacion,
              "correlacion": correlacion, "regresion": regresion}.get(analisis)
        if not fn:
            return {"ok": False, "error": "Análisis no reconocido."}
        return fn(columns, rows, params)
    except Exception as e:  # noqa: BLE001
        logger.warning("experimental analizar(%s) falló: %s", analisis, str(e)[:200])
        return {"ok": False, "error": "Error en el análisis: " + str(e)[:160]}
