"""
Búsqueda de literatura en vivo para el módulo Investigador (rutas de investigación).

Consulta Crossref (DOI) y PubMed (PMID) por un tema (la "línea de investigación" que el
investigador va desarrollando) y devuelve artículos REALES con su identificador verificado y
la cita formateada en APA 7 o Vancouver. NUNCA inventa referencias: si un ítem no trae DOI/PMID
verificable, se descarta.

Sin claves: Crossref y PubMed E-utilities son APIs públicas.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

_CTX = ssl.create_default_context()
_UA = "Evalys/1.0 (https://evalys.app; mailto:soporte@evalys.app)"


def _get(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read())


# ───────────────────────────────────────────── Crossref (DOI)
def _crossref(query: str, rows: int = 6) -> list[dict]:
    url = ("https://api.crossref.org/works?rows=" + str(rows)
           + "&select=DOI,title,author,container-title,issued,volume,issue,page,type"
           + "&query.bibliographic=" + urllib.parse.quote(query))
    data = _get(url)
    items = (data.get("message") or {}).get("items", [])
    refs = []
    for it in items:
        doi = it.get("DOI")
        titulo = (it.get("title") or [None])[0]
        if not doi or not titulo:
            continue          # sin DOI o sin título -> no verificable, se descarta
        autores = [{"family": a.get("family", ""), "given": a.get("given", "")}
                   for a in (it.get("author") or []) if a.get("family")]
        issued = (((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])
        anio = issued[0] if issued else None
        refs.append({
            "id_tipo": "DOI", "id": doi, "url": "https://doi.org/" + doi,
            "titulo": titulo.strip(), "autores": autores,
            "revista": (it.get("container-title") or [None])[0],
            "anio": anio, "volumen": it.get("volume"), "numero": it.get("issue"),
            "paginas": it.get("page"), "tipo": it.get("type"),
        })
    return refs


# ───────────────────────────────────────────── formato de cita
def _norm_family(f: str) -> str:
    """Apellidos que Crossref devuelve en MAYÚSCULAS -> Capitalizado (respeta guiones)."""
    if f and f == f.upper():
        return "-".join(w.capitalize() for w in f.split("-"))
    return f


def _iniciales(given: str) -> str:
    partes = [p for p in given.replace(".", " ").split() if p]
    return " ".join(p[0].upper() + "." for p in partes)


def _apa_autores(autores: list[dict]) -> str:
    if not autores:
        return ""
    fmt = [_norm_family(a["family"]) + ", " + _iniciales(a.get("given", "")) for a in autores[:20]]
    if len(fmt) == 1:
        return fmt[0]
    return ", ".join(fmt[:-1]) + ", & " + fmt[-1]


def _vanc_autores(autores: list[dict]) -> str:
    fmt = [_norm_family(a["family"]) + " " + _iniciales(a.get("given", "")).replace(".", "") for a in autores[:6]]
    s = ", ".join(fmt)
    if len(autores) > 6:
        s += ", et al"
    return s


def formatear(ref: dict, fmt: str = "apa") -> str:
    autores = ref.get("autores", [])
    anio = ref.get("anio") or "s.f."
    titulo = ref.get("titulo", "")
    rev = ref.get("revista") or ""
    vol = ref.get("volumen"); num = ref.get("numero"); pag = ref.get("paginas")
    doi = ref.get("url", "")
    if fmt == "vancouver":
        vp = ""
        if vol:
            vp = str(vol) + (("(" + str(num) + ")") if num else "") + ((":" + str(pag)) if pag else "")
        partes = [p for p in [_vanc_autores(autores) + "." if autores else "", titulo + ".",
                              rev + "." if rev else "", (str(anio) + ";" + vp if vp else str(anio)) + "."] if p]
        return " ".join(partes).strip()
    # APA 7
    vp = ""
    if vol:
        vp = str(vol) + (("(" + str(num) + ")") if num else "") + ((", " + str(pag)) if pag else "")
    cola = (rev + ", " + vp if (rev and vp) else (rev or "")).strip().rstrip(",")
    partes = [_apa_autores(autores), "(" + str(anio) + ").", titulo + ".",
              (cola + "." if cola else ""), doi]
    return " ".join(p for p in partes if p).strip()


def buscar(query: str, rows: int = 5) -> dict:
    """Devuelve artículos reales verificados por DOI, con cita en APA 7 y Vancouver."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "n": 0, "articulos": [], "fuente": "crossref",
                "nota": "Escribe una línea de investigación para buscar."}
    try:
        refs = _crossref(query, rows=rows)
    except Exception as e:
        return {"query": query, "n": 0, "articulos": [], "fuente": "crossref",
                "error": type(e).__name__, "nota": "No se pudo consultar Crossref en este momento."}
    arts = []
    for r in refs[:rows]:
        arts.append({
            "titulo": r["titulo"], "anio": r["anio"], "revista": r["revista"],
            "id_tipo": r["id_tipo"], "id": r["id"], "url": r["url"], "tipo": r.get("tipo"),
            "apa": formatear(r, "apa"), "vancouver": formatear(r, "vancouver"),
        })
    return {"query": query, "n": len(arts), "articulos": arts, "fuente": "Crossref",
            "nota": "Referencias reales verificadas por DOI; nunca inventadas."}
