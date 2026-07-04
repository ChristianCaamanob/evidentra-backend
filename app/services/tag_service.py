"""
C3 - Etiquetado item -> RA -> Bloom y reporte de cobertura.

Patron de gobernanza (G1, la IA no decide): este modulo PROPONE un mapeo de cada
item de la evaluacion a su Resultado de Aprendizaje (RA) y nivel Bloom, y genera un
reporte de cobertura. La propuesta NO se da por hecha: la valida el especialista antes
de cerrarse (gate humano). Postura propositiva (G6): describe cobertura y foco, no juzga
el programa.

Los vinculos se persisten en los campos aditivos de C1
(AnswerKeyItem.learning_outcome_id / bloom_level / unidad), sin tocar el scoring.
"""
from __future__ import annotations

from collections import Counter

# Taxonomia de Bloom en orden creciente de complejidad cognitiva.
BLOOM_ORDEN = ["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"]


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def coverage_report(tags: list[dict], titulo: str = "DMOR0030",
                    ra_textos: dict | None = None) -> str:
    """
    Genera el reporte de cobertura (markdown) de un etiquetado item -> RA -> Bloom.

    tags: lista de dicts {"item": int, "ra": str, "bloom": str, "unidad": str}.
    ra_textos: opcional, {codigo_ra: texto literal} para mostrar el RA sin reescribirlo.
    """
    ra_textos = ra_textos or {}
    total = len(tags)
    por_ra = Counter(t.get("ra") or "sin_ra" for t in tags)
    por_bloom = Counter(t.get("bloom") or "sin_bloom" for t in tags)
    por_unidad = Counter(t.get("unidad") or "sin_unidad" for t in tags)
    sin_etiquetar = [t["item"] for t in tags if not (t.get("ra") and t.get("bloom"))]

    L: list[str] = []
    L.append(f"# Etiquetado {titulo} - RA / Bloom (propuesta)")
    L.append("")
    L.append("> **Estado:** propuesta generada por la IA. Requiere validacion del "
             "especialista antes de cerrarse (gate humano, G1). Ajusta lo que corresponda.")
    L.append("")
    L.append(f"**Items etiquetados:** {total - len(sin_etiquetar)}/{total}")
    if sin_etiquetar:
        L.append(f"**Items sin etiquetar:** {sin_etiquetar}")
    L.append("")

    L.append("## Cobertura por Resultado de Aprendizaje (RA)")
    L.append("")
    L.append("| RA | Items | Cobertura | Texto del RA |")
    L.append("|---|---:|---:|---|")
    for ra in sorted(por_ra):
        n = por_ra[ra]
        txt = ra_textos.get(ra, "").replace("|", "/")
        L.append(f"| {ra} | {n} | {_pct(n, total)}% | {txt} |")
    L.append("")

    L.append("## Cobertura por nivel Bloom")
    L.append("")
    L.append("| Nivel Bloom | Items | Cobertura |")
    L.append("|---|---:|---:|")
    orden = {b: i for i, b in enumerate(BLOOM_ORDEN)}
    for bloom in sorted(por_bloom, key=lambda b: orden.get(b, 99)):
        n = por_bloom[bloom]
        L.append(f"| {bloom} | {n} | {_pct(n, total)}% |")
    L.append("")

    L.append("## Cobertura por unidad")
    L.append("")
    L.append("| Unidad | Items | Cobertura |")
    L.append("|---|---:|---:|")
    for unidad in sorted(por_unidad):
        n = por_unidad[unidad]
        L.append(f"| {unidad} | {n} | {_pct(n, total)}% |")
    L.append("")

    L.append("## Detalle item -> RA -> Bloom")
    L.append("")
    con_enunciado = any(t.get("enunciado") for t in tags)
    if con_enunciado:
        L.append("| Item | Enunciado (resumen) | RA | Bloom | Unidad |")
        L.append("|---:|---|---|---|---|")
        for t in sorted(tags, key=lambda x: x["item"]):
            en = (t.get("enunciado") or "").replace("|", "/")
            L.append(f"| {t['item']} | {en} | {t.get('ra','-')} | {t.get('bloom','-')} | {t.get('unidad','-')} |")
    else:
        L.append("| Item | RA | Bloom | Unidad |")
        L.append("|---:|---|---|---|")
        for t in sorted(tags, key=lambda x: x["item"]):
            L.append(f"| {t['item']} | {t.get('ra','-')} | {t.get('bloom','-')} | {t.get('unidad','-')} |")
    L.append("")
    return "\n".join(L) + "\n"


def apply_tags(db, answer_key_id, tags: list[dict], version: str = "A") -> int:
    """
    Persiste el etiquetado propuesto en los items de la pauta (campos de C1).
    Devuelve cuantos items fueron etiquetados. No toca el scoring existente.
    """
    from app.models.answer_key import AnswerKeyItem
    by_num = {
        it.question_number: it
        for it in db.query(AnswerKeyItem).filter(
            AnswerKeyItem.answer_key_id == answer_key_id,
            AnswerKeyItem.version == version,
        ).all()
    }
    n = 0
    for t in tags:
        it = by_num.get(t["item"])
        if not it:
            continue
        it.learning_outcome_id = t.get("ra")
        it.bloom_level = t.get("bloom")
        it.unidad = t.get("unidad")
        n += 1
    db.commit()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# PROPUESTA de etiquetado para DMOR0030 (Solemne 1, 30 items).
# Es un punto de partida generado por la IA sobre la estructura de RA/unidades del
# programa. El especialista lo revisa y corrige contra el instrumento real antes de
# validarlo. Reemplazar por el mapeo definitivo cuando se cargue la prueba oficial.
# ─────────────────────────────────────────────────────────────────────────────
def _propuesta_dmor0030() -> list[dict]:
    plan = [
        # (rango_items, ra, unidad, [blooms ciclados])
        (range(1, 8),   "RA1", "Unidad I",   ["recordar", "comprender"]),
        (range(8, 15),  "RA2", "Unidad II",  ["comprender", "aplicar"]),
        (range(15, 23), "RA3", "Unidad III", ["aplicar", "analizar"]),
        (range(23, 31), "RA4", "Unidad IV",  ["analizar", "evaluar"]),
    ]
    tags: list[dict] = []
    for rango, ra, unidad, blooms in plan:
        for i, item in enumerate(rango):
            tags.append({"item": item, "ra": ra, "unidad": unidad,
                         "bloom": blooms[i % len(blooms)]})
    return tags


PROPUESTA_DMOR0030: list[dict] = _propuesta_dmor0030()
