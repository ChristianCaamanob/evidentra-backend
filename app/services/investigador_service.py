"""
Modulo Investigador - Orquestacion e INTERPRETACION del analisis psicometrico.

Toma el analisis clasico (curso_stats_service, TCT) y el analisis IRT
(irt_service, Rasch) de UN instrumento y produce un objeto de investigacion
completo y AUTO-INTERPRETADO, listo para su uso posterior (I2 validez/DIF,
I3 longitudinal, I4 cualitativo, I5 paquete de publicacion).

La interpretacion es data-driven: se genera desde los datos con umbrales
establecidos en la literatura de medicion educativa, no se escribe a mano.
Referencias de los umbrales:
  - Fiabilidad de separacion / KR-20: >=.70 aceptable, >=.80 buena, >=.90 excelente.
  - Ajuste Rasch (infit/outfit MSQ): 0.5-1.5 productivo; 1.5-2.0 poco productivo; >2 desajuste; <0.5 sobreajuste (Linacre).
  - Discriminacion punto-biserial (TCT): >=.30 buena, .20-.29 aceptable, <.20 revisar, <0 problematica.
  - Dificultad p (TCT): rango util 0.30-0.85 para seleccion multiple.
  - Targeting (Rasch): idealmente media(theta) ~ media(b)=0; |media(theta)|>0.5 sugiere desajuste.
"""
from __future__ import annotations

from statistics import mean


# ───────────────────────────────────────────── interpretaciones data-driven
def interpretar_fiabilidad(irt: dict, ctt: dict) -> dict:
    sp = irt["fiabilidad"]["separacion_personas"]
    si = irt["fiabilidad"]["separacion_items"]
    kr20 = ctt.get("confiabilidad_kr20")

    def _nivel(v):
        if v is None: return "sin dato"
        if v >= 0.90: return "excelente"
        if v >= 0.80: return "buena"
        if v >= 0.70: return "aceptable"
        if v >= 0.50: return "moderada"
        return "baja"

    texto = (
        f"El instrumento mide de forma {_nivel(kr20)} (KR-20 = {kr20}). En la metrica "
        f"de Rasch, la separacion de personas es {_nivel(sp)} ({sp}) y la de items "
        f"{_nivel(si)} ({si}): la jerarquia de habilidad y la de dificultad son "
        f"{'confiables' if min(sp, si) >= 0.7 else 'aun poco estables (conviene mas casos o mas items)'}."
    )
    return {"kr20": kr20, "separacion_personas": sp, "separacion_items": si,
            "nivel_kr20": _nivel(kr20), "nivel_personas": _nivel(sp),
            "nivel_items": _nivel(si), "texto": texto}


def interpretar_targeting(irt: dict) -> dict:
    bs = sorted(it["b"] for it in irt["items"])
    thetas = sorted(p["theta"] for p in irt["personas"] if not p.get("extremo"))
    media_b = round(mean(bs), 2)
    media_t = round(mean(thetas), 2) if thetas else 0.0
    delta = round(media_t - media_b, 2)

    # Brechas de dificultad: rangos de habilidad con estudiantes pero sin items cercanos (+/-0.5 logit).
    brechas = []
    if thetas:
        lo, hi = min(thetas), max(thetas)
        paso = 0.5
        x = round(lo, 1)
        while x <= hi:
            hay_alumnos = any(abs(t - x) <= 0.25 for t in thetas)
            hay_item = any(abs(b - x) <= 0.5 for b in bs)
            if hay_alumnos and not hay_item:
                brechas.append(round(x, 1))
            x = round(x + paso, 1)
    # compactar brechas contiguas en rangos
    rangos = []
    for v in brechas:
        if rangos and abs(v - rangos[-1][1]) <= 0.55:
            rangos[-1][1] = v
        else:
            rangos.append([v, v])

    if delta > 0.5:
        diag = "los estudiantes, en promedio, superan la dificultad del test: el instrumento resulta facil para el grupo"
    elif delta < -0.5:
        diag = "los estudiantes, en promedio, quedan bajo la dificultad del test: el instrumento resulta exigente para el grupo"
    else:
        diag = "el test esta bien centrado respecto de la habilidad promedio del grupo"

    texto = (
        f"Dificultad media de los items b={media_b} y habilidad media theta={media_t} "
        f"(delta={delta:+}). En terminos de targeting, {diag}."
    )
    if rangos:
        zonas = ", ".join(f"{a} a {b} logits" if a != b else f"~{a} logits" for a, b in rangos)
        texto += (f" Ademas, faltan items en zonas donde si hay estudiantes ({zonas}): "
                  f"ahi la medicion es menos precisa y conviene agregar items de esa dificultad.")
    return {"media_b": media_b, "media_theta": media_t, "delta": delta,
            "zonas_sin_items": rangos, "texto": texto}


def interpretar_precision(irt: dict) -> dict:
    tif = irt["informacion_test"]
    grid, info, sem = tif["theta_grid"], tif["info"], tif["sem"]
    pk = max(range(len(info)), key=lambda i: info[i])
    theta_opt = grid[pk]
    sem_min = round(sem[pk], 2)
    # zonas de baja precision (SEM > 0.5) dentro del rango habitual [-3, 3]
    zonas = [grid[i] for i in range(len(grid)) if sem[i] > 0.5 and -3 <= grid[i] <= 3]
    texto = (
        f"La informacion del test es maxima en theta={theta_opt} (error de medicion "
        f"minimo SEM={sem_min}). El instrumento mide con mayor certeza a los estudiantes "
        f"de habilidad {'media' if abs(theta_opt) < 0.6 else 'alta' if theta_opt > 0 else 'baja'} "
        f"y pierde precision en los extremos."
    )
    return {"theta_optimo": theta_opt, "sem_minimo": sem_min,
            "zonas_baja_precision": zonas, "texto": texto}


def flags_items(ctt: dict, irt: dict) -> list[dict]:
    """Sintesis accionable: combina senales de TCT e IRT por item."""
    irt_by = {it["item"]: it for it in irt["items"]}
    out = []
    for c in ctt["items"]:
        it = c["item"]
        r = irt_by.get(it, {})
        motivos = []
        # TCT: discriminacion
        if c["discriminacion_pbis"] < 0.0:
            motivos.append("discriminacion negativa (los mejores lo fallan mas): revisar clave/enunciado")
        elif c["discriminacion_pbis"] < 0.20:
            motivos.append(f"discriminacion baja ({c['discriminacion_pbis']}): distingue poco entre niveles")
        # TCT: dificultad extrema con poca info
        if c["dificultad_p"] >= 0.90:
            motivos.append(f"muy facil (p={c['dificultad_p']}): aporta poca informacion")
        elif c["dificultad_p"] <= 0.20:
            motivos.append(f"muy dificil (p={c['dificultad_p']}): revisar contenido o redaccion")
        # IRT: ajuste
        if r.get("infit_msq", 1) > 1.5 or r.get("outfit_msq", 1) > 2.0:
            motivos.append(f"desajuste al modelo (infit={r.get('infit_msq')}, outfit={r.get('outfit_msq')})")
        # distractor con fuga: una alternativa incorrecta elegida por >35%
        for alt, d in c["distractores"].items():
            if not d["correcta"] and d["pct"] > 35:
                motivos.append(f"distractor {alt} demasiado atractivo ({d['pct']}%): posible ambiguedad o concepcion erronea frecuente")
        if motivos:
            sev = "alta" if any(("negativa" in m or "desajuste" in m) for m in motivos) else "media"
            out.append({"item": it, "ra": c["ra"], "severidad": sev, "motivos": motivos})
    out.sort(key=lambda x: (0 if x["severidad"] == "alta" else 1, x["item"]))
    return out


def jerarquia_dificultad(irt: dict, ctt: dict) -> dict:
    items = irt["items"]
    ra_by = {c["item"]: c["ra"] for c in ctt["items"]}
    mas_dificil = max(items, key=lambda i: i["b"])
    mas_facil = min(items, key=lambda i: i["b"])
    por_ra: dict[str, list] = {}
    for it in items:
        por_ra.setdefault(ra_by.get(it["item"]) or "sin_ra", []).append(it["b"])
    ra_orden = sorted(((ra, round(mean(v), 2)) for ra, v in por_ra.items()),
                      key=lambda x: -x[1])
    texto = (
        f"El item mas dificil es P{mas_dificil['item']} (b={mas_dificil['b']}) y el mas "
        f"facil P{mas_facil['item']} (b={mas_facil['b']}). Por resultado de aprendizaje, la "
        f"mayor dificultad en logits recae en {ra_orden[0][0]} (b medio {ra_orden[0][1]})."
    )
    return {"mas_dificil": mas_dificil["item"], "mas_facil": mas_facil["item"],
            "b_por_ra": [{"ra": r, "b_medio": v} for r, v in ra_orden], "texto": texto}


# ───────────────────────────────────────────── codebook (documentacion)
def codebook() -> list[dict]:
    return [
        {"variable": "student_id", "nivel": "persona", "tipo": "id_seudonimo", "descripcion": "Identificador seudonimizado del estudiante (sin nombre/RUT)."},
        {"variable": "item", "nivel": "item", "tipo": "entero", "descripcion": "Numero de pregunta en el instrumento."},
        {"variable": "ra / bloom / unidad", "nivel": "item", "tipo": "categorico", "descripcion": "Vinculo curricular segun la TE del instrumento (nulo si no hay TE)."},
        {"variable": "correcto", "nivel": "persona x item", "tipo": "binario 0/1", "descripcion": "Acierto del estudiante en el item."},
        {"variable": "pct / nota", "nivel": "persona", "tipo": "continuo", "descripcion": "Logro porcentual y nota en la escala configurada (1-7)."},
        {"variable": "dificultad_p", "nivel": "item", "tipo": "proporcion", "rango": "0-1", "descripcion": "TCT: proporcion de aciertos (facilidad; 1-p = dificultad)."},
        {"variable": "discriminacion_pbis", "nivel": "item", "tipo": "correlacion", "rango": "-1 a 1", "descripcion": "TCT: correlacion punto-biserial corregida item-total."},
        {"variable": "b", "nivel": "item", "tipo": "logit", "descripcion": "IRT/Rasch: dificultad del item en la escala latente comun."},
        {"variable": "theta", "nivel": "persona", "tipo": "logit", "descripcion": "IRT/Rasch: habilidad latente del estudiante."},
        {"variable": "infit_msq / outfit_msq", "nivel": "item", "tipo": "MSQ", "rango": "~0.5-1.5 util", "descripcion": "IRT: ajuste del item al modelo (residuales ponderados / no ponderados)."},
        {"variable": "info(theta) / SEM(theta)", "nivel": "test", "tipo": "funcion", "descripcion": "IRT: informacion y error estandar de medicion segun nivel de habilidad."},
        {"variable": "kr20 / separacion", "nivel": "test", "tipo": "fiabilidad", "descripcion": "Consistencia interna (TCT) y fiabilidad de separacion (Rasch)."},
    ]


# ───────────────────────────────────────────── orquestador
def analizar(ctt: dict, irt: dict) -> dict:
    """
    Une el analisis clasico (ctt = curso_stats_service.analizar_evaluacion) y el IRT
    (irt = irt_service.estimar_rasch) en un objeto de investigacion interpretado.
    """
    interpretacion = {
        "fiabilidad": interpretar_fiabilidad(irt, ctt),
        "targeting": interpretar_targeting(irt),
        "precision": interpretar_precision(irt),
        "jerarquia_dificultad": jerarquia_dificultad(irt, ctt),
        "items_a_revisar": flags_items(ctt, irt),
    }
    return {
        "meta": {
            "n_personas": irt["n_personas"], "n_items": irt["n_items"],
            "tiene_te": ctt["instrumento"].get("tiene_te", False),
            "modelo_irt": irt["modelo"],
            "seudonimizado": True,
            "nota": "Objeto de investigacion de UN instrumento. Analisis longitudinal/DIF "
                    "requieren varios instrumentos y grupos, cada uno con su propia TE.",
        },
        "clasica": {
            "descriptivos_nota": ctt.get("descriptivos_nota"),
            "descriptivos_pct": ctt.get("descriptivos_pct"),
            "kr20": ctt.get("confiabilidad_kr20"),
            "normalidad_nota": ctt.get("normalidad_nota"),
            "items": ctt.get("items"),
        },
        "irt": irt,
        "interpretacion": interpretacion,
        "codebook": codebook(),
        "dataset_largo": ctt.get("dataset_largo", []),
    }
