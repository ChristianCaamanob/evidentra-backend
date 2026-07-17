"""
Índice SCImago Journal Rank (SJR) por ISSN — cuartil oficial Q1–Q4, SJR, país, categorías.

Fuente: CSV anual público de SCImago (scimagojr.com), convertido a un índice comprimido
(app/data/scimago_sjr.csv.gz, ~0.75 MB, ~53k ISSN). Datos CC BY-NC de SCImago. Se carga en
memoria la primera vez (cacheado). El cuartil SJR es el indicador de calidad de revista que
NO entrega OpenAlex; aquí se agrega como fuente autoritativa por ISSN.
"""
from __future__ import annotations

import csv
import functools
import gzip
import os
import re

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "scimago_sjr.csv.gz")


def _norm(issn) -> str:
    return re.sub(r"[^0-9Xx]", "", str(issn or "")).upper()


@functools.lru_cache(maxsize=1)
def _indice() -> dict:
    """{issn8: {q, sjr, h, pais, cat}}. La primera fila por ISSN gana (mejor cuartil, ya ordenado)."""
    idx: dict[str, dict] = {}
    try:
        with gzip.open(_PATH, "rt", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                issn = row.get("issn")
                if issn and issn not in idx:
                    idx[issn] = row
    except Exception:
        pass
    return idx


def disponible() -> bool:
    return bool(_indice())


def metrica(issn) -> dict | None:
    """Métricas SJR de la revista por ISSN (cualquiera de sus ISSN). None si no está en SCImago."""
    n = _norm(issn)
    if not n:
        return None
    r = _indice().get(n)
    if not r:
        return None
    try:
        sjr = float(r["sjr"]) if r.get("sjr") else None
    except (ValueError, TypeError):
        sjr = None
    try:
        h = int(r["h"]) if r.get("h") else None
    except (ValueError, TypeError):
        h = None
    return {"cuartil": (r.get("q") or None), "sjr": sjr, "h_index_sjr": h,
            "pais_sjr": (r.get("pais") or None), "categorias": (r.get("cat") or None)}
