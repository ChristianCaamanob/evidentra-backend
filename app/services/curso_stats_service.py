"""
P1 - Motor de estadistica del curso (psicometria clasica) para el informe del profesor
y para el modulo de investigacion.

Entrega, para UNA evaluacion (un instrumento):
  - Descriptivos del curso: n, media, mediana, DE, varianza, min, max, rango, asimetria,
    curtosis, IC95 de la media; en % de logro y en NOTA (escala configurable, por defecto
    chilena 1,0-7,0).
  - Analisis de items (Teoria Clasica del Test): dificultad (p), discriminacion
    (punto-biserial corregido y D de Kelley por 27% superior/inferior), y distractores
    (frecuencia y % por alternativa) -- lo que entrega GradeCam/Socrative y mas.
  - Confiabilidad: KR-20.
  - Vinculo curricular por RA / Bloom / unidad SOLO si se entrega la Tabla de
    Especificaciones (TE) DE ESE instrumento. Sin TE no se proyecta nada: el vinculo
    queda como 'sin_te'. (Cada solemne futuro necesita su propia TE para ver como tributa.)
  - Datasets para el investigador: 'largo' (tidy, una fila por alumno-item) y 'ancho'
    (una fila por alumno), con todas las variables crudas para correr normalidad
    (Shapiro-Wilk) y pruebas parametricas/no parametricas (t, Wilcoxon, Mann-Whitney, etc.).

Gobernanza: trabaja con seudonimos de alumno (student_id); no requiere nombre/RUT.
"""
from __future__ import annotations

import math
from statistics import mean, median, pstdev, stdev

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

try:
    from scipy import stats as _scipy_stats
except Exception:  # pragma: no cover
    _scipy_stats = None

from app.services.result_service import calculate_grade


def _skew_kurtosis(xs: list[float]) -> tuple[float, float]:
    """Asimetria y curtosis (exceso) muestrales. Fisher, sin dependencias."""
    n = len(xs)
    if n < 3:
        return 0.0, 0.0
    m = mean(xs)
    s = pstdev(xs) or 1e-9
    skew = sum(((x - m) / s) ** 3 for x in xs) / n
    kurt = sum(((x - m) / s) ** 4 for x in xs) / n - 3.0
    return round(skew, 3), round(kurt, 3)


def _ci95_media(xs: list[float]) -> list[float]:
    n = len(xs)
    if n < 2:
        return [round(xs[0], 2), round(xs[0], 2)] if xs else [0.0, 0.0]
    m = mean(xs)
    se = stdev(xs) / math.sqrt(n)
    t = float(_scipy_stats.t.ppf(0.975, n - 1)) if _scipy_stats else 1.96
    return [round(float(m - t * se), 2), round(float(m + t * se), 2)]


def _descriptivos(valores: list[float]) -> dict:
    if not valores:
        return {}
    sk, ku = _skew_kurtosis(valores)
    return {
        "n": len(valores),
        "media": round(mean(valores), 2),
        "mediana": round(median(valores), 2),
        "de": round(stdev(valores), 2) if len(valores) > 1 else 0.0,
        "varianza": round(stdev(valores) ** 2, 2) if len(valores) > 1 else 0.0,
        "min": round(min(valores), 2),
        "max": round(max(valores), 2),
        "rango": round(max(valores) - min(valores), 2),
        "asimetria": sk,
        "curtosis_exceso": ku,
        "ic95_media": _ci95_media(valores),
    }


def _normalidad(valores: list[float]) -> dict:
    """Shapiro-Wilk si hay scipy; si no, deja los datos listos para el investigador."""
    if _scipy_stats and 3 <= len(valores) <= 5000:
        W, p = _scipy_stats.shapiro(valores)
        return {"prueba": "shapiro_wilk", "W": round(float(W), 4), "p": round(float(p), 4),
                "distribucion": "normal" if p > 0.05 else "no_normal",
                "recomendacion_test": "parametrico (t-Student, ANOVA)" if p > 0.05
                                       else "no_parametrico (Wilcoxon, Mann-Whitney, Kruskal-Wallis)"}
    return {"prueba": "shapiro_wilk", "estado": "pendiente (instalar scipy en el modulo investigador)",
            "n": len(valores)}


def analizar_evaluacion(respuestas_alumnos: list[dict], pauta: dict,
                        te_tags: dict | None = None,
                        escala: str = "chile_1_7", exigencia: float = 60.0) -> dict:
    """
    respuestas_alumnos: [{"student_id": <seudonimo>, "respuestas": {item:int -> letra|None}}]
    pauta: {item:int -> letra_correcta}
    te_tags: {item:int -> {"ra","bloom","unidad"}} del MISMO instrumento, o None.
    """
    items = sorted(pauta.keys())
    k = len(items)
    alternativas = ["A", "B", "C", "D", "E"]

    # ── matriz alumno x item (0/1) + puntajes ──
    filas = []          # por alumno: {student_id, aciertos:{item:0/1}, puntaje, pct, nota}
    dataset_largo = []  # tidy
    for a in respuestas_alumnos:
        sid = a["student_id"]
        resp = a.get("respuestas", {})
        aciertos = {}
        puntaje = 0
        for it in items:
            elegida = resp.get(it)
            correcta = pauta[it]
            ok = 1 if (elegida is not None and str(elegida).upper() == str(correcta).upper()) else 0
            aciertos[it] = ok
            puntaje += ok
            tag = (te_tags or {}).get(it, {})
            dataset_largo.append({
                "student_id": sid, "item": it,
                "ra": tag.get("ra"), "bloom": tag.get("bloom"), "unidad": tag.get("unidad"),
                "elegida": elegida, "correcta": correcta, "correcto": ok,
            })
        pct = round(puntaje / k * 100, 1) if k else 0.0
        nota, etiqueta, aprob = calculate_grade(pct, escala, exigencia)
        filas.append({"student_id": sid, "aciertos": aciertos, "puntaje": puntaje,
                      "pct": pct, "nota": round(nota, 1), "aprobado": bool(aprob)})

    n = len(filas)
    pcts = [f["pct"] for f in filas]
    notas = [f["nota"] for f in filas]
    puntajes = [f["puntaje"] for f in filas]

    # ── analisis de items ──
    var_total = (stdev(puntajes) ** 2) if n > 1 else 0.0
    sd_total = math.sqrt(var_total) if var_total else 0.0
    orden = sorted(filas, key=lambda f: f["puntaje"], reverse=True)
    corte = max(1, round(n * 0.27)) if n >= 4 else max(1, n // 2)
    sup, inf = orden[:corte], orden[-corte:]

    items_out = []
    suma_pq = 0.0
    for it in items:
        col = [f["aciertos"][it] for f in filas]
        n_ok = sum(col)
        p = n_ok / n if n else 0.0
        q = 1 - p
        suma_pq += p * q
        # discriminacion punto-biserial CORREGIDA (item vs total-menos-item)
        if n > 1 and sd_total > 0:
            resto = [f["puntaje"] - f["aciertos"][it] for f in filas]
            m1 = mean([r for r, c in zip(resto, col) if c == 1]) if n_ok else 0.0
            m0 = mean([r for r, c in zip(resto, col) if c == 0]) if (n - n_ok) else 0.0
            sd_resto = stdev(resto) if len(resto) > 1 else 1e-9
            pbis = round((m1 - m0) / sd_resto * math.sqrt(p * q), 3) if sd_resto else 0.0
        else:
            pbis = 0.0
        d_kelley = round(sum(f["aciertos"][it] for f in sup) / corte
                         - sum(f["aciertos"][it] for f in inf) / corte, 3)
        # distractores
        conteo = {alt: 0 for alt in alternativas}
        vacias = 0
        for f in filas:
            # buscar la letra elegida en dataset (via respuestas)
            pass
        # recomputar elegidas por item
        for a in respuestas_alumnos:
            e = a.get("respuestas", {}).get(it)
            if e is None:
                vacias += 1
            else:
                le = str(e).upper()
                conteo[le] = conteo.get(le, 0) + 1
        distractores = {alt: {"n": conteo.get(alt, 0),
                              "pct": round(conteo.get(alt, 0) / n * 100, 1) if n else 0.0,
                              "correcta": (alt == str(pauta[it]).upper())}
                        for alt in alternativas}
        tag = (te_tags or {}).get(it, {})
        items_out.append({
            "item": it,
            "dificultad_p": round(p, 3),
            "nivel_dificultad": ("dificil" if p < 0.4 else "media" if p < 0.8 else "facil"),
            "discriminacion_pbis": pbis,
            "calidad_discriminacion": ("buena" if pbis >= 0.30 else "aceptable" if pbis >= 0.20
                                        else "revisar" if pbis >= 0.10 else "deficiente"),
            "discriminacion_d_kelley": d_kelley,
            "n_correctas": n_ok, "n_incorrectas": n - n_ok - vacias, "n_vacias": vacias,
            "distractores": distractores,
            "ra": tag.get("ra"), "bloom": tag.get("bloom"), "unidad": tag.get("unidad"),
        })

    # ── confiabilidad KR-20 ──
    kr20 = round((k / (k - 1)) * (1 - suma_pq / var_total), 3) if (k > 1 and var_total > 0) else None

    # ── por RA / Bloom / unidad (solo con TE del instrumento) ──
    def _agrupa(campo: str) -> list[dict] | None:
        if not te_tags:
            return None
        grupos: dict[str, list[int]] = {}
        for it in items:
            key = (te_tags.get(it, {}) or {}).get(campo) or "sin_clasificar"
            grupos.setdefault(key, []).append(it)
        out = []
        for key, its in grupos.items():
            ps = [next(x["dificultad_p"] for x in items_out if x["item"] == it) for it in its]
            out.append({"clave": key, "items": len(its),
                        "logro_promedio": round(mean(ps) * 100, 1) if ps else 0.0})
        out.sort(key=lambda x: x["logro_promedio"])
        return out

    # ── distribucion de notas por banda ──
    bandas = {"1.0-3.9 (reprobado)": 0, "4.0-4.9": 0, "5.0-5.9": 0, "6.0-7.0": 0}
    for nt in notas:
        if nt < 4.0: bandas["1.0-3.9 (reprobado)"] += 1
        elif nt < 5.0: bandas["4.0-4.9"] += 1
        elif nt < 6.0: bandas["5.0-5.9"] += 1
        else: bandas["6.0-7.0"] += 1

    aprobados = sum(1 for f in filas if f["aprobado"])

    dataset_ancho = [{"student_id": f["student_id"], "puntaje": f["puntaje"],
                      "pct": f["pct"], "nota": f["nota"], "aprobado": int(f["aprobado"])}
                     for f in filas]

    return {
        "instrumento": {"n_items": k, "n_alumnos": n, "escala": escala, "exigencia": exigencia,
                        "tiene_te": bool(te_tags)},
        "descriptivos_pct": _descriptivos(pcts),
        "descriptivos_nota": _descriptivos(notas),
        "tasa_aprobacion": round(aprobados / n * 100, 1) if n else 0.0,
        "aprobados": aprobados, "reprobados": n - aprobados,
        "distribucion_notas": bandas,
        "confiabilidad_kr20": kr20,
        "items": items_out,
        "por_ra": _agrupa("ra"),
        "por_bloom": _agrupa("bloom"),
        "por_unidad": _agrupa("unidad"),
        "normalidad_pct": _normalidad(pcts),
        "normalidad_nota": _normalidad(notas),
        "dataset_largo": dataset_largo,
        "dataset_ancho": dataset_ancho,
    }
