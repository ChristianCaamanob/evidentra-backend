"""
I3 - Analisis longitudinal para el modulo Investigador.

Compara el desempeno a lo largo del tiempo (varios solemnes / cohortes) con las
herramientas que exige una publicacion de alto estandar:

  - Ganancia normalizada de Hake  g = (post - pre) / (100 - pre)  (grupo e individual).
  - Tamano de efecto: Cohen d y Hedges g (correccion J para muestras chicas) con IC,
    interpretado con los benchmarks de Kraft (2020) calibrados para EDUCACION.
  - Seleccion de la prueba guiada por normalidad (Shapiro-Wilk):
      * pareado (mismos estudiantes)  -> t pareada  o  Wilcoxon (signed-rank).
      * independiente (cohortes)      -> t de Welch  o  Mann-Whitney U.
  - Modelo multinivel (medidas repetidas anidadas en el estudiante): pendiente por
    solemne, su significancia y el ICC (cuanta varianza es entre estudiantes).

VALIDEZ (no negociable): las notas / % son comparables entre instrumentos como logro,
pero la habilidad latente theta de Rasch de tests DISTINTOS no es directamente
comparable sin equating (items ancla). Las comparaciones de este modulo se hacen sobre
la escala de logro/nota o mediante tamanos de efecto estandarizados. El vinculo por RA
solo es longitudinal si los RA estan mapeados entre instrumentos (cada uno con su TE).
"""
from __future__ import annotations

import numpy as np
from scipy import stats as st

try:
    import statsmodels.formula.api as _smf
    import pandas as _pd
except Exception:  # pragma: no cover
    _smf = None
    _pd = None


# ───────────────────────────────────────────── ganancia de Hake
def ganancia_hake(pre_pct, post_pct) -> dict:
    """Ganancia normalizada de Hake, a nivel de grupo e individual."""
    pre = np.asarray(pre_pct, float)
    post = np.asarray(post_pct, float)
    mpre, mpost = float(pre.mean()), float(post.mean())
    g_grupo = (mpost - mpre) / (100 - mpre) if mpre < 100 else None
    # individual: definido si pre < 100
    ok = pre < 100
    g_ind = (post[ok] - pre[ok]) / (100 - pre[ok])

    def _cl(g):
        if g is None:
            return "indefinida"
        if g >= 0.7:
            return "alta"
        if g >= 0.3:
            return "media"
        if g >= 0:
            return "baja"
        return "negativa"

    return {
        "pre_medio": round(mpre, 1), "post_medio": round(mpost, 1),
        "g_grupo": round(g_grupo, 3) if g_grupo is not None else None,
        "clase_grupo": _cl(g_grupo),
        "g_individual_medio": round(float(g_ind.mean()), 3) if len(g_ind) else None,
        "g_individual": [round(float(x), 3) for x in g_ind.tolist()],
    }


# ───────────────────────────────────────────── tamano de efecto
def _kraft(g: float) -> str:
    a = abs(g)
    if a < 0.05:
        return "pequeno"
    if a < 0.20:
        return "mediano (educativamente relevante)"
    return "grande"


def _cohen(g: float) -> str:
    a = abs(g)
    if a < 0.20:
        return "trivial"
    if a < 0.50:
        return "pequeno"
    if a < 0.80:
        return "mediano"
    return "grande"


def tamano_efecto(a, b, pareado: bool = False) -> dict:
    """
    Cohen d y Hedges g (correccion J) con IC 95%.
    pareado=True: d_z sobre las diferencias (mismos sujetos).
    """
    a = np.asarray(a, float); b = np.asarray(b, float)
    if pareado:
        dif = b - a
        n = len(dif)
        sd = dif.std(ddof=1) or 1e-9
        d = float(dif.mean() / sd)
        se = float(np.sqrt(1 / n + d ** 2 / (2 * n)))
        J = 1 - 3 / (4 * (2 * n) - 9)
    else:
        n1, n2 = len(a), len(b)
        sp = np.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2)) or 1e-9
        d = float((b.mean() - a.mean()) / sp)
        se = float(np.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2))))
        J = 1 - 3 / (4 * (n1 + n2) - 9)
        n = n1 + n2
    g = J * d
    ci = [round(g - 1.96 * J * se, 3), round(g + 1.96 * J * se, 3)]
    return {"cohen_d": round(d, 3), "hedges_g": round(g, 3), "ic95": ci,
            "correccion_J": round(J, 4), "interpretacion_kraft": _kraft(g),
            "interpretacion_cohen": _cohen(g), "n": int(n)}


# ───────────────────────────────────────────── comparacion (test guiado por normalidad)
def _es_normal(x) -> bool:
    x = np.asarray(x, float)
    if len(x) < 3 or len(x) > 5000:
        return True
    return float(st.shapiro(x).pvalue) > 0.05


def comparar(a, b, pareado: bool = False, etiqueta_a="tiempo 1", etiqueta_b="tiempo 2") -> dict:
    a = np.asarray(a, float); b = np.asarray(b, float)
    if pareado:
        normal = _es_normal(b - a)
        if normal:
            stat, p = st.ttest_rel(b, a); prueba = "t pareada"
        else:
            stat, p = st.wilcoxon(b, a); prueba = "Wilcoxon (signed-rank)"
    else:
        normal = _es_normal(a) and _es_normal(b)
        if normal:
            stat, p = st.ttest_ind(b, a, equal_var=False); prueba = "t de Welch"
        else:
            stat, p = st.mannwhitneyu(b, a, alternative="two-sided"); prueba = "Mann-Whitney U"
    ef = tamano_efecto(a, b, pareado=pareado)
    direccion = "mejora" if b.mean() > a.mean() else "baja" if b.mean() < a.mean() else "sin cambio"
    sig = p < 0.05
    texto = (
        f"De {etiqueta_a} ({a.mean():.1f}) a {etiqueta_b} ({b.mean():.1f}) hay una {direccion} "
        f"{'significativa' if sig else 'no significativa'} ({prueba}, p={p:.4f}), con un tamano "
        f"de efecto Hedges g={ef['hedges_g']} (IC95 {ef['ic95']}), {ef['interpretacion_kraft']} "
        f"segun los benchmarks de educacion."
    )
    return {"prueba": prueba, "normal": bool(normal), "estadistico": round(float(stat), 3),
            "p": round(float(p), 4), "significativo": bool(sig), "efecto": ef, "texto": texto}


# ───────────────────────────────────────────── multinivel
def trayectoria_multinivel(student_ids, tiempos, scores, secciones=None) -> dict:
    """
    Medidas repetidas anidadas en el estudiante. Modelo: score ~ tiempo + (1|estudiante).
    Devuelve la pendiente por solemne, su p y el ICC (varianza entre estudiantes).
    """
    if _smf is None or _pd is None:
        return {"disponible": False}
    df = _pd.DataFrame({"student": list(student_ids), "tiempo": list(tiempos),
                        "score": list(scores)})
    if secciones is not None:
        df["seccion"] = list(secciones)
    try:
        md = _smf.mixedlm("score ~ tiempo", df, groups=df["student"], re_formula="~1")
        r = md.fit(method="lbfgs", disp=0)
    except Exception:
        return {"disponible": False}
    slope = float(r.fe_params["tiempo"])
    p = float(r.pvalues["tiempo"])
    gv = float(r.cov_re.iloc[0, 0]) if r.cov_re.shape[0] else 0.0
    rv = float(r.scale)
    icc = gv / (gv + rv) if (gv + rv) > 0 else 0.0
    texto = (
        f"En promedio, cada solemne cambia la nota/logro en {slope:+.2f} unidades "
        f"({'significativo' if p < 0.05 else 'no significativo'}, p={p:.4f}). El {icc*100:.0f}% "
        f"de la varianza es ENTRE estudiantes (ICC={icc:.2f}): las diferencias individuales "
        f"pesan {'mas' if icc > 0.5 else 'menos'} que la variacion dentro de cada trayectoria."
    )
    return {"disponible": True, "pendiente_por_solemne": round(slope, 3),
            "p": round(p, 4), "icc_estudiante": round(icc, 3), "texto": texto}


# ───────────────────────────────────────────── orquestador
def analizar_longitudinal(momentos: list[dict], pareado: bool = True) -> dict:
    """
    momentos: lista ordenada [{"etiqueta": "S1", "pct": [...], "nota": [...], "student_id":[...]}].
    Requiere >=2 momentos. Con pareado=True asume los mismos estudiantes en el mismo orden.
    """
    if len(momentos) < 2:
        raise ValueError("Se requieren al menos 2 momentos.")
    etiquetas = [m["etiqueta"] for m in momentos]
    pre, post = momentos[0], momentos[-1]

    hake = ganancia_hake(pre["pct"], post["pct"])
    comp = comparar(pre["pct"], post["pct"], pareado=pareado,
                    etiqueta_a=pre["etiqueta"], etiqueta_b=post["etiqueta"])

    # datos largos para multinivel
    sids, ts, sc = [], [], []
    for i, m in enumerate(momentos):
        ids = m.get("student_id") or [f"S{j:03d}" for j in range(len(m["pct"]))]
        for j, v in enumerate(m["pct"]):
            sids.append(ids[j]); ts.append(i); sc.append(v)
    ml = trayectoria_multinivel(sids, ts, sc)

    # resumen por momento
    resumen = [{"etiqueta": m["etiqueta"],
                "n": len(m["pct"]),
                "media_pct": round(float(np.mean(m["pct"])), 1),
                "de_pct": round(float(np.std(m["pct"], ddof=1)), 1),
                "media_nota": round(float(np.mean(m["nota"])), 2) if m.get("nota") else None}
               for m in momentos]

    return {
        "momentos": etiquetas, "pareado": pareado,
        "resumen": resumen,
        "ganancia_hake": hake,
        "comparacion_extremos": comp,
        "multinivel": ml,
        "validez": ("Comparacion sobre la escala de logro/nota. La habilidad theta de "
                    "Rasch de instrumentos distintos requiere equating (items ancla) para "
                    "ser comparable; el vinculo por RA es longitudinal solo si los RA estan "
                    "mapeados entre instrumentos."),
        "gobernanza": "Datos seudonimizados (G2); el seguimiento individual requiere consentimiento (G4).",
    }
