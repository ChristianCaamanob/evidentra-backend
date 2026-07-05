"""
I8b - Invarianza de medicion (de Rasch) entre grupos.

La invarianza es la propiedad que un instrumento debe cumplir para comparar grupos de
forma justa: los parametros del item NO deben depender del grupo. Complementa al DIF de I2
(que evalua item por item) con una vista de ESCALA: calibra el Rasch por separado en cada
grupo y compara las dificultades.

    - Grafico de invarianza : dificultad grupo A vs grupo B por item (deben caer sobre la
                              identidad si hay invarianza).
    - Correlacion de parametros: alta => estructura invariante.
    - Items fuera de banda   : |z| > 1,96 Y |diferencia| > 0,5 logits (doble criterio, como
                              en el DIF, para no sobre-marcar).
    - Veredicto de escala.

Enfoque de invarianza de RASCH (invarianza de los estimadores del item entre submuestras;
Engelhard, 2013), NO CFA multigrupo (que requeriria un motor SEM). Se declara el metodo.

Referencias: Engelhard (2013) Invariant Measurement; Wright & Stone (1979); Millsap (2011).
"""
from __future__ import annotations

import numpy as np

from app.services.irt_service import estimar_rasch


def invarianza_rasch(X: np.ndarray, grupo, umbral_z: float = 1.96,
                     umbral_dif: float = 0.5) -> dict:
    """
    X: persona x item (0/1). grupo: etiqueta por persona (2 grupos). Calibra Rasch por
    grupo y compara las dificultades de item (ambas centradas en 0 -> misma escala).
    """
    X = np.asarray(X, dtype=float)
    grupo = np.asarray(grupo)
    etiquetas = list(dict.fromkeys(grupo.tolist()))
    if len(etiquetas) != 2:
        raise ValueError("Se requieren exactamente 2 grupos.")
    gA, gB = etiquetas
    rA = estimar_rasch(X[grupo == gA])
    rB = estimar_rasch(X[grupo == gB])

    items = []
    bAs, bBs = [], []
    for iA, iB in zip(rA["items"], rB["items"]):
        extremo = iA["extremo"] or iB["extremo"]
        bA, bB = iA["b"], iB["b"]
        se = float(np.sqrt(iA["se_b"] ** 2 + iB["se_b"] ** 2))
        dif = bA - bB
        z = dif / se if se > 0 else 0.0
        no_invariante = (not extremo) and abs(z) > umbral_z and abs(dif) > umbral_dif
        items.append({
            "item": iA["item"],
            "b_grupo_A": round(float(bA), 3), "b_grupo_B": round(float(bB), 3),
            "diferencia": round(float(dif), 3), "z": round(float(z), 2),
            "no_invariante": bool(no_invariante), "extremo": bool(extremo),
        })
        if not extremo:
            bAs.append(bA); bBs.append(bB)

    corr = float(np.corrcoef(bAs, bBs)[0, 1]) if len(bAs) > 2 else 0.0
    flagged = [it for it in items if it["no_invariante"]]
    n_eval = len(bAs)
    invariante = corr >= 0.9 and len(flagged) <= max(0, int(0.05 * n_eval))

    return {
        "metodo": "Invarianza de medicion de Rasch (calibracion separada por grupo)",
        "grupos": {"A": str(gA), "B": str(gB),
                   "n_A": int((grupo == gA).sum()), "n_B": int((grupo == gB).sum())},
        "correlacion_parametros": round(corr, 3),
        "n_items_evaluados": n_eval,
        "items": items,
        "items_no_invariantes": [it["item"] for it in flagged],
        "invariante": bool(invariante),
        "veredicto": (
            "Medicion INVARIANTE entre grupos: las comparaciones son justas; el instrumento "
            "funciona igual en ambos." if invariante else
            f"Invarianza PARCIAL: {len(flagged)} item(s) funcionan distinto entre grupos "
            f"({', '.join(str(i) for i in [it['item'] for it in flagged])}). Revisar esos "
            "items o modelar la no-invarianza antes de comparar grupos."),
        "grafico_invarianza": {"b_A": bAs, "b_B": bBs},
        "nota_metodo": "Enfoque Rasch (invarianza de estimadores del item), no CFA multigrupo. "
                       "Purificacion iterativa del anclaje queda como refinamiento futuro.",
        "gobernanza": "Analisis agregado y seudonimizado (G2); evidencia de equidad, no altera "
                      "notas (G1). Complementa el DIF de I2.",
    }
