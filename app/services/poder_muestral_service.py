"""Poder muestral — advertencia honesta de si la muestra alcanza para cada técnica.

Integridad metodológica (Fase 2.1): NO bloquea el análisis (el investigador decide), pero
reporta el N, el mínimo recomendado por técnica y una advertencia clara de baja potencia.
Evita el error clásico de mostrar índices que *parecen* válidos con n=30.

Umbrales (defendibles según literatura habitual; son mínimos prácticos, no dogmas):
  - Rasch dicotómico: ~100 mínimo, ≥200 estable (±0.5 logits, 99% CI aprox.). Linacre.
  - TRI 2PL/GRM: ~500 mínimo; 3PL requiere ≥1000. (de Ayala; Embretson & Reise.)
  - CFA (WLSMV categórico): ≥200, idealmente 10–20 casos por parámetro libre. (Kline.)
  - CDM/DINA: ≥500 (crece con nº de atributos e ítems). (Rupp, Templin & Henson.)
  - DIF (MH / regresión logística): ≥200 por grupo para estimaciones estables. (Zwick.)
  - Dimensionalidad / EFA: ≥200 y razón sujeto:ítem ≥5–10. (Costello & Osborne.)
"""

MINIMOS = {
    "rasch": (100, 200, "Rasch dicotómico: ~100 mínimo, ≥200 para estimaciones estables (±0.5 logits)."),
    "tri": (500, 1000, "TRI 2PL/GRM: ~500 mínimo; 3PL requiere ≥1000."),
    "cfa": (200, 300, "CFA (WLSMV categórico): ≥200; idealmente 10–20 casos por parámetro libre."),
    "dina": (500, 1000, "CDM/DINA: ≥500 (crece con el nº de atributos e ítems)."),
    "dif": (200, 400, "DIF: ≥200 por grupo para estimaciones estables."),
    "dimensionalidad": (200, 300, "Dimensionalidad/EFA: ≥200 y razón sujeto:ítem ≥5–10."),
    "clasica": (30, 100, "TCT: ≥30 para descriptivos; ≥100 para fiabilidad razonable."),
}


def evaluar(tecnica: str, n_personas: int, n_items: int | None = None,
            n_grupo_min: int | None = None) -> dict:
    """Devuelve el veredicto de poder muestral para una técnica.

    n_grupo_min: para DIF/invarianza, el tamaño del grupo MÁS pequeño (es lo que limita).
    """
    n_min, n_optimo, ref = MINIMOS.get(tecnica, (100, 200, "Umbral genérico."))
    # Para técnicas de dos grupos, el que manda es el grupo más chico.
    n_ref = n_grupo_min if (n_grupo_min is not None) else n_personas

    if n_ref >= n_optimo:
        nivel, suficiente = "adecuado", True
    elif n_ref >= n_min:
        nivel, suficiente = "aceptable", True
    else:
        nivel, suficiente = "insuficiente", False

    ratio = round(n_personas / n_items, 1) if n_items else None
    ratio_bajo = (tecnica in ("dimensionalidad", "cfa") and ratio is not None and ratio < 5)

    out = {
        "tecnica": tecnica,
        "n_personas": n_personas,
        "n_min_recomendado": n_min,
        "n_optimo": n_optimo,
        "nivel": nivel,
        "suficiente": bool(suficiente and not ratio_bajo),
        "razon_sujeto_item": ratio,
        "referencia": ref,
    }
    avisos = []
    if not suficiente:
        avisos.append(
            f"Muestra {'del grupo más pequeño ' if n_grupo_min is not None else ''}"
            f"n={n_ref} por debajo del mínimo recomendado ({n_min}) para {tecnica}: "
            f"resultados de BAJA POTENCIA, interpretar con cautela y NO como concluyentes.")
    if ratio_bajo:
        avisos.append(f"Razón sujeto:ítem = {ratio} (<5): la estructura factorial puede ser inestable.")
    out["advertencia"] = " ".join(avisos) if avisos else None
    return out
