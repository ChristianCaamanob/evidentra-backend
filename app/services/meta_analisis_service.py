"""Metaanálisis — síntesis cuantitativa para el módulo de Revisión Sistemática (Fase D).

Corazón de la RS: convierte "leí k estudios" en un efecto combinado con su incertidumbre.
Todo en Python puro y determinista (sin numpy/R), con estadística correcta (t de Student y
beta incompleta para p-valores e IC exactos). metafor (Viechtbauer, 2010) es la referencia
de contraste; aquí se computa nativamente para no depender de R en el servidor.

Incluye:
  · Tamaños de efecto: Hedges' g (SMD, con corrección de muestra pequeña), ln(OR), z de Fisher.
  · Efectos aleatorios: τ² por DerSimonian-Laird; IC del combinado por normal y por
    Hartung-Knapp-Sidik-Jonkman (t, más honesto con k pequeño).
  · Heterogeneidad: Q de Cochran, I², H², τ² e intervalo de predicción (Higgins et al., 2009).
  · Sesgo de publicación: prueba de Egger (regresión) + asimetría del funnel.
  · Certeza: señales tipo GRADE (inconsistencia, imprecisión, sesgo de publicación).

Referencias: DerSimonian & Laird (1986); Hedges & Olkin (1985); Higgins & Thompson (2002);
Higgins, Thompson & Spiegelhalter (2009); IntHout, Ioannidis & Borm (2014, HKSJ);
Egger et al. (1997); Viechtbauer (2010, metafor); GRADE Working Group (2008).
"""
from __future__ import annotations

import math

Z975 = 1.959963984540054


# ───────────────────────────── estadística base (sin dependencias)
def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Función beta incompleta regularizada I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_sf(t: float, df: float) -> float:
    """P(T > t) para T ~ t de Student con df grados de libertad (cola derecha)."""
    x = df / (df + t * t)
    ib = 0.5 * _betai(df / 2.0, 0.5, x)
    return ib if t > 0 else 1.0 - ib


def _t_two_sided_p(t: float, df: float) -> float:
    return 2.0 * _t_sf(abs(t), df)


def _t_quantile(p: float, df: float) -> float:
    """Cuantil t_{df}(p) por bisección sobre la CDF (p en (0,1))."""
    if df <= 0:
        return Z975
    lo, hi = -100.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        cdf = 1.0 - _t_sf(mid, df)
        if cdf < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2.0


# ───────────────────────────── tamaños de efecto
def hedges_g(m1, sd1, n1, m2, sd2, n2) -> dict:
    gl = n1 + n2 - 2
    sp2 = ((n1 - 1) * sd1 * sd1 + (n2 - 1) * sd2 * sd2) / gl if gl > 0 else 0.0
    sp = math.sqrt(sp2) if sp2 > 0 else 1e-9
    d = (m1 - m2) / sp
    J = 1.0 - 3.0 / (4.0 * (n1 + n2) - 9.0)
    g = J * d
    var_d = (n1 + n2) / (n1 * n2) + d * d / (2.0 * gl) if gl > 0 else 0.0
    return {"y": round(g, 4), "v": max(J * J * var_d, 1e-9)}


def ln_or(e1, n1, e2, n2) -> dict:
    a, b, c, dd = e1, n1 - e1, e2, n2 - e2
    if min(a, b, c, dd) == 0:                     # corrección de continuidad de Haldane
        a, b, c, dd = a + 0.5, b + 0.5, c + 0.5, dd + 0.5
    lnor = math.log((a * dd) / (b * c))
    v = 1.0 / a + 1.0 / b + 1.0 / c + 1.0 / dd
    return {"y": round(lnor, 4), "v": v}


def fisher_z(r, n) -> dict:
    r = max(min(r, 0.999), -0.999)
    z = 0.5 * math.log((1 + r) / (1 - r))
    return {"y": round(z, 4), "v": 1.0 / (n - 3) if n > 3 else 0.25}


# ───────────────────────────── prueba de Egger (sesgo de publicación)
def egger(ys: list[float], vs: list[float]) -> dict | None:
    k = len(ys)
    if k < 3:
        return None
    xs = [1.0 / math.sqrt(v) for v in vs]            # precisión
    zs = [y / math.sqrt(v) for y, v in zip(ys, vs)]  # efecto estandarizado
    n = k
    sx, sz = sum(xs), sum(zs)
    sxx = sum(x * x for x in xs)
    sxz = sum(x * z for x, z in zip(xs, zs))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    slope = (n * sxz - sx * sz) / denom
    intercept = (sz - slope * sx) / n
    resid = [z - (intercept + slope * x) for x, z in zip(xs, zs)]
    df = n - 2
    s2 = sum(r * r for r in resid) / df if df > 0 else 0.0
    se_int = math.sqrt(s2 * sxx / denom) if denom > 0 and s2 > 0 else None
    if not se_int:
        return None
    t = intercept / se_int
    return {"intercepto": round(intercept, 3), "t": round(t, 3), "df": df,
            "p": round(_t_two_sided_p(t, df), 4),
            "sesgo_probable": _t_two_sided_p(t, df) < 0.10}


# ───────────────────────────── síntesis de efectos aleatorios
def sintetizar(estudios: list[dict], medida: str = "smd") -> dict:
    """estudios: lista con y,v ya calculados o datos crudos (según `medida`)."""
    prep, labels = [], []
    for i, e in enumerate(estudios):
        labels.append(e.get("label") or f"Estudio {i + 1}")
        if "y" in e and "v" in e:
            prep.append({"y": float(e["y"]), "v": float(e["v"])})
        elif medida == "smd":
            prep.append(hedges_g(e["m1"], e["sd1"], e["n1"], e["m2"], e["sd2"], e["n2"]))
        elif medida == "or":
            prep.append(ln_or(e["e1"], e["n1"], e["e2"], e["n2"]))
        elif medida == "z":
            prep.append(fisher_z(e["r"], e["n"]))
        else:
            raise ValueError("medida no soportada")
    ys = [p["y"] for p in prep]
    vs = [p["v"] for p in prep]
    k = len(ys)
    if k < 2:
        return {"error": "Se requieren al menos 2 estudios combinables.", "k": k}

    w = [1.0 / v for v in vs]                         # pesos de efecto fijo
    sw = sum(w)
    m_fixed = sum(wi * yi for wi, yi in zip(w, ys)) / sw
    Q = sum(wi * (yi - m_fixed) ** 2 for wi, yi in zip(w, ys))
    df = k - 1
    C = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (Q - df) / C) if C > 0 else 0.0
    I2 = max(0.0, (Q - df) / Q) * 100 if Q > 0 else 0.0
    H2 = Q / df if df > 0 else None

    wr = [1.0 / (v + tau2) for v in vs]              # pesos de efecto aleatorio
    swr = sum(wr)
    M = sum(wi * yi for wi, yi in zip(wr, ys)) / swr
    var_M = 1.0 / swr
    se_M = math.sqrt(var_M)
    ci_z = [M - Z975 * se_M, M + Z975 * se_M]

    # Hartung-Knapp-Sidik-Jonkman (t con k-1 gl)
    q_hk = sum(wi * (yi - M) ** 2 for wi, yi in zip(wr, ys)) / df
    se_hk = math.sqrt(q_hk / swr) if q_hk > 0 else se_M
    tcrit = _t_quantile(0.975, df)
    ci_hk = [M - tcrit * se_hk, M + tcrit * se_hk]
    z_stat = M / se_M
    p_pooled = 2.0 * (1.0 - _norm_cdf(abs(z_stat)))

    # intervalo de predicción (Higgins et al., 2009), requiere k>=3
    pi = None
    if k >= 3:
        tcrit_pi = _t_quantile(0.975, k - 2)
        sp = math.sqrt(tau2 + var_M)
        pi = [round(M - tcrit_pi * sp, 4), round(M + tcrit_pi * sp, 4)]

    peso_total = sum(wr)
    forest = [{"label": labels[i], "y": round(ys[i], 4),
               "ci": [round(ys[i] - Z975 * math.sqrt(vs[i]), 4),
                      round(ys[i] + Z975 * math.sqrt(vs[i]), 4)],
               "peso_pct": round(wr[i] / peso_total * 100, 1),
               "se": round(math.sqrt(vs[i]), 4)} for i in range(k)]
    funnel = [{"label": labels[i], "y": round(ys[i], 4), "se": round(math.sqrt(vs[i]), 4)}
              for i in range(k)]

    eg = egger(ys, vs)
    Q_p = 1.0 - _chi2_cdf(Q, df) if df > 0 else None

    out = {
        "k": k, "medida": medida,
        "combinado": {
            "estimador": round(M, 4), "se": round(se_M, 4),
            "ic95_normal": [round(ci_z[0], 4), round(ci_z[1], 4)],
            "ic95_hksj": [round(ci_hk[0], 4), round(ci_hk[1], 4)],
            "z": round(z_stat, 3), "p": round(p_pooled, 5),
            "intervalo_prediccion": pi,
        },
        "heterogeneidad": {
            "Q": round(Q, 3), "df": df, "Q_p": round(Q_p, 4) if Q_p is not None else None,
            "I2": round(I2, 1), "H2": round(H2, 2) if H2 else None, "tau2": round(tau2, 4),
            "nivel": ("baja" if I2 < 25 else "moderada" if I2 < 50 else "sustancial" if I2 < 75 else "considerable"),
        },
        "fijo": {"estimador": round(m_fixed, 4)},
        "egger": eg,
        "forest": forest, "funnel": funnel,
        "efecto_escala": ("ln(OR)" if medida == "or" else "z de Fisher" if medida == "z" else "Hedges g"),
    }
    out["grade"] = _grade(out)
    out["interpretacion"] = _interpretar(out)
    out["referencia"] = ("DerSimonian & Laird (1986); Higgins & Thompson (2002); IntHout et al. "
                         "(2014, HKSJ); Egger et al. (1997). Cómputo nativo; metafor como contraste.")
    return out


def _chi2_cdf(x: float, k: int) -> float:
    """CDF chi-cuadrado por beta/gamma incompleta (para el p de Q)."""
    if x <= 0:
        return 0.0
    return _gammp(k / 2.0, x / 2.0)


def _gammp(a: float, x: float) -> float:
    if x < 0 or a <= 0:
        return 0.0
    if x < a + 1.0:
        ap, s, term = a, 1.0 / a, 1.0 / a
        for _ in range(300):
            ap += 1.0
            term *= x / ap
            s += term
            if abs(term) < abs(s) * 1e-12:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    b = x + 1.0 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 300):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-12:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _grade(out: dict) -> dict:
    señales = []
    if out["heterogeneidad"]["I2"] >= 50:
        señales.append({"dominio": "Inconsistencia", "baja": True,
                        "razon": f"I² = {out['heterogeneidad']['I2']}% (heterogeneidad {out['heterogeneidad']['nivel']})."})
    ci = out["combinado"]["ic95_hksj"]
    cruza_nulo = (ci[0] <= 0 <= ci[1]) if out["medida"] != "or" else (ci[0] <= 0 <= ci[1])
    if cruza_nulo or out["k"] < 5:
        señales.append({"dominio": "Imprecisión", "baja": True,
                        "razon": ("El IC incluye el efecto nulo." if cruza_nulo else f"Pocos estudios (k={out['k']}).")})
    if out.get("egger") and out["egger"].get("sesgo_probable"):
        señales.append({"dominio": "Sesgo de publicación", "baja": True,
                        "razon": f"Egger p = {out['egger']['p']} (asimetría del funnel)."})
    certeza = {0: "Alta", 1: "Moderada", 2: "Baja"}.get(len(señales), "Muy baja")
    return {"señales": señales, "certeza": certeza,
            "nota": "Señales orientativas GRADE (no sustituyen el juicio del revisor)."}


def _interpretar(out: dict) -> str:
    c = out["combinado"]
    het = out["heterogeneidad"]
    esc = out["efecto_escala"]
    sig = "significativo" if c["p"] < 0.05 else "no significativo"
    pi = f" Intervalo de predicción [{c['intervalo_prediccion'][0]}, {c['intervalo_prediccion'][1]}]." if c["intervalo_prediccion"] else ""
    return (f"Efecto combinado ({esc}) = {c['estimador']} (IC95 HKSJ [{c['ic95_hksj'][0]}, {c['ic95_hksj'][1]}]), "
            f"{sig} (p = {c['p']}). Heterogeneidad {het['nivel']} (I² = {het['I2']}%, τ² = {het['tau2']}).{pi} "
            f"Certeza GRADE: {out['grade']['certeza']}.")
