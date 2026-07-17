"""
Motor de referencias del módulo Investigador (rutas de investigación · revisión de literatura).

Fuente primaria: OpenAlex (250M+ trabajos, gratis, sin clave) — aporta ABSTRACT (índice
invertido), conteo de citas, estado open-access, tipo y puntaje de relevancia. Se enriquece
con Crossref (metadatos DOI canónicos: autores limpios, volumen/número/páginas).

Principios metodológicos (líneas rojas):
  · NUNCA inventa referencias: si un ítem no trae DOI/PMID verificable, se descarta.
  · Deduplica por DOI (y por título normalizado como respaldo) para no doblar el conteo.
  · Ventana temporal explícita (5 / 10 / 15 / +) — clave para una búsqueda defendible.
  · No fabrica cuartiles: expone ISSN y citas (señales abiertas); el SJR se mapea aparte.

Sin claves: OpenAlex y Crossref son APIs públicas (usan el "polite pool" con mailto).
"""
from __future__ import annotations

import datetime
import json
import re
import ssl
import urllib.parse
import urllib.request

try:  # CA bundle explícito: evita fallos de verificación TLS en contenedores mínimos
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = ssl.create_default_context()
_MAILTO = "soporte@evalys.app"
_UA = f"Evalys/1.0 (https://evalys.app; mailto:{_MAILTO})"

_PARTICULAS = {"de", "del", "la", "las", "los", "van", "von", "der", "den", "da", "di",
               "dos", "das", "du", "el", "al", "bin", "ibn", "san", "santa", "st", "le"}


def _get(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read())


# ───────────────────────────────────────────── utilidades de identidad
def _norm_doi(doi: str | None) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d


def _norm_titulo(t: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _split_nombre(display: str) -> dict:
    """OpenAlex entrega el nombre completo sin separar. Heurística: el apellido es la última
    palabra, absorbiendo partículas previas (de, van, del…). Compuestos españoles con dos
    apellidos quedan con el último; Crossref, cuando hay DOI, corrige esto con datos limpios."""
    partes = [p for p in (display or "").replace(",", " ").split() if p]
    if not partes:
        return {"family": "", "given": ""}
    if len(partes) == 1:
        return {"family": partes[0], "given": ""}
    i = len(partes) - 1
    family = [partes[i]]
    j = i - 1
    while j >= 1 and partes[j].lower().strip(".") in _PARTICULAS:
        family.insert(0, partes[j])
        j -= 1
    return {"family": " ".join(family), "given": " ".join(partes[:j + 1])}


def _abstract_desde_invertido(idx: dict | None, limite: int = 1500) -> str | None:
    """OpenAlex da el abstract como {palabra: [posiciones]}. Se reconstruye en orden."""
    if not idx:
        return None
    pares = []
    for palabra, posiciones in idx.items():
        for p in posiciones:
            pares.append((p, palabra))
    if not pares:
        return None
    pares.sort()
    texto = " ".join(w for _, w in pares).strip()
    return (texto[:limite] + "…") if len(texto) > limite else texto


# ───────────────────────────────────────────── OpenAlex (fuente primaria)
_OA_SELECT = ("id,ids,doi,title,display_name,publication_year,authorships,primary_location,"
              "open_access,cited_by_count,type,biblio,abstract_inverted_index,language")


def _oa_item(it: dict) -> dict | None:
    """Parsea un trabajo de OpenAlex a nuestra ref. Devuelve None si no es verificable (sin DOI)."""
    doi = _norm_doi(it.get("doi"))
    titulo = it.get("title") or it.get("display_name")
    if not doi or not titulo:
        return None
    ids = (it.get("ids") or {})
    pmid = (ids.get("pmid") or "").rstrip("/").rsplit("/", 1)[-1] or None
    pmcid = (ids.get("pmcid") or "").rstrip("/").rsplit("/", 1)[-1] or None
    loc = (it.get("primary_location") or {})
    fuente = (loc.get("source") or {})
    biblio = (it.get("biblio") or {})
    oa = (it.get("open_access") or {})
    autores = []
    for a in (it.get("authorships") or []):
        nom = (a.get("author") or {}).get("display_name")
        if nom:
            autores.append(_split_nombre(nom))
    pag = None
    fp, lp = biblio.get("first_page"), biblio.get("last_page")
    if fp:
        pag = (f"{fp}-{lp}" if lp and lp != fp else str(fp))
    return {
        "id_tipo": "DOI", "id": doi, "url": "https://doi.org/" + doi,
        "pmid": pmid, "pmcid": pmcid,
        "titulo": titulo.strip(), "autores": autores,
        "revista": fuente.get("display_name"), "issn": fuente.get("issn_l"),
        "source_id": (fuente.get("id") or "").rsplit("/", 1)[-1] if fuente.get("id") else None,
        "anio": it.get("publication_year"),
        "volumen": biblio.get("volume"), "numero": biblio.get("issue"), "paginas": pag,
        "tipo": it.get("type"),
        "abstract": _abstract_desde_invertido(it.get("abstract_inverted_index")),
        "citas": it.get("cited_by_count"),
        "oa": bool(oa.get("is_oa")), "oa_estado": oa.get("oa_status"), "oa_url": oa.get("oa_url"),
        "idioma": it.get("language"), "_fuente": "OpenAlex",
    }


def _oa_url(query: str, per_page: int, desde_anio: int | None, cursor: str | None = None) -> str:
    filtros = ["type:article|review|book-chapter"]
    if desde_anio:
        filtros.append(f"from_publication_date:{desde_anio}-01-01")
    params = {"search": query, "per_page": str(per_page), "select": _OA_SELECT,
              "filter": ",".join(filtros), "mailto": _MAILTO}
    if cursor:
        params["cursor"] = cursor
    return "https://api.openalex.org/works?" + urllib.parse.urlencode(params)


def _openalex(query: str, rows: int, desde_anio: int | None) -> list[dict]:
    data = _get(_oa_url(query, min(rows, 25), desde_anio))
    return [r for r in (_oa_item(it) for it in (data.get("results") or [])) if r]


# ───────────────────────────────────────────── Crossref (enriquece autores/metadatos)
def _crossref(query: str, rows: int = 8, desde_anio: int | None = None) -> list[dict]:
    filtro = f"&filter=from-pub-date:{desde_anio}-01-01" if desde_anio else ""
    url = ("https://api.crossref.org/works?rows=" + str(rows)
           + "&select=DOI,title,author,container-title,issued,volume,issue,page,type,ISSN"
           + filtro + "&mailto=" + _MAILTO
           + "&query.bibliographic=" + urllib.parse.quote(query))
    data = _get(url)
    items = (data.get("message") or {}).get("items", [])
    refs = []
    for it in items:
        doi = _norm_doi(it.get("DOI"))
        titulo = (it.get("title") or [None])[0]
        if not doi or not titulo:
            continue
        autores = [{"family": a.get("family", ""), "given": a.get("given", "")}
                   for a in (it.get("author") or []) if a.get("family")]
        issued = (((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])
        anio = issued[0] if issued else None
        refs.append({
            "id_tipo": "DOI", "id": doi, "url": "https://doi.org/" + doi,
            "titulo": titulo.strip(), "autores": autores,
            "revista": (it.get("container-title") or [None])[0],
            "issn": (it.get("ISSN") or [None])[0],
            "anio": anio, "volumen": it.get("volume"), "numero": it.get("issue"),
            "paginas": it.get("page"), "tipo": it.get("type"), "_fuente": "Crossref",
        })
    return refs


# ───────────────────────────────────────────── formato de cita
def _norm_family(f: str) -> str:
    """Apellidos en MAYÚSCULAS -> Capitalizado (respeta guiones y compuestos con espacio)."""
    if f and f == f.upper():
        return " ".join("-".join(w.capitalize() for w in parte.split("-")) for parte in f.split())
    return f


def _iniciales(given: str) -> str:
    partes = [p for p in (given or "").replace(".", " ").split() if p]
    return " ".join(p[0].upper() + "." for p in partes)


def _apa_autores(autores: list[dict]) -> str:
    if not autores:
        return ""
    fmt = [_norm_family(a["family"]) + (", " + _iniciales(a.get("given", "")) if a.get("given") else "")
           for a in autores[:20]]
    if len(fmt) == 1:
        return fmt[0]
    return ", ".join(fmt[:-1]) + ", & " + fmt[-1]


def _vanc_autores(autores: list[dict]) -> str:
    fmt = [(_norm_family(a["family"]) + " " + _iniciales(a.get("given", "")).replace(".", "")).strip()
           for a in autores[:6]]
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


# ───────────────────────────────────────────── export a gestores (BibTeX / RIS)
def _cite_key(ref: dict) -> str:
    fam = ""
    if ref.get("autores"):
        fam = re.sub(r"[^A-Za-z]", "", (ref["autores"][0].get("family") or "").split()[-1] if ref["autores"][0].get("family") else "")
    return (fam or "ref") + str(ref.get("anio") or "")


def _bibtex(ref: dict) -> str:
    autores = " and ".join(
        (a.get("family", "") + (", " + a["given"] if a.get("given") else "")) for a in ref.get("autores", []))
    campos = [("author", autores), ("title", ref.get("titulo")), ("journal", ref.get("revista")),
              ("year", ref.get("anio")), ("volume", ref.get("volumen")), ("number", ref.get("numero")),
              ("pages", (ref.get("paginas") or "").replace("-", "--") if ref.get("paginas") else None),
              ("doi", ref.get("id")), ("issn", ref.get("issn"))]
    cuerpo = ",\n  ".join(f"{k} = {{{v}}}" for k, v in campos if v)
    return "@article{" + _cite_key(ref) + ",\n  " + cuerpo + "\n}"


def _ris(ref: dict) -> str:
    lineas = ["TY  - JOUR"]
    for a in ref.get("autores", []):
        au = a.get("family", "") + (", " + a["given"] if a.get("given") else "")
        lineas.append("AU  - " + au)
    campos = [("TI", ref.get("titulo")), ("JO", ref.get("revista")), ("PY", ref.get("anio")),
              ("VL", ref.get("volumen")), ("IS", ref.get("numero")), ("DO", ref.get("id")),
              ("SN", ref.get("issn"))]
    for tag, v in campos:
        if v:
            lineas.append(f"{tag}  - {v}")
    if ref.get("paginas") and "-" in str(ref["paginas"]):
        sp, ep = str(ref["paginas"]).split("-", 1)
        lineas += ["SP  - " + sp, "EP  - " + ep]
    elif ref.get("paginas"):
        lineas.append("SP  - " + str(ref["paginas"]))
    lineas.append("ER  - ")
    return "\n".join(lineas)


# ───────────────────────────────────────────── fusión + deduplicación
def _fusionar(primaria: list[dict], enriquecedora: list[dict]) -> list[dict]:
    """Parte de la lista primaria (OpenAlex, ordenada por relevancia) y la enriquece con datos
    limpios de Crossref cuando comparten DOI; luego añade los de Crossref no presentes."""
    por_doi = {_norm_doi(r["id"]): r for r in enriquecedora}
    vistos_doi, vistos_tit = set(), set()
    salida = []
    for r in primaria:
        d = _norm_doi(r["id"])
        cr = por_doi.get(d)
        if cr:  # Crossref manda en autores/volumen/número/páginas (metadatos canónicos)
            for k in ("autores", "volumen", "numero", "paginas"):
                if cr.get(k):
                    r[k] = cr[k]
            r["revista"] = r.get("revista") or cr.get("revista")
        vistos_doi.add(d)
        vistos_tit.add(_norm_titulo(r["titulo"]))
        salida.append(r)
    for cr in enriquecedora:
        d = _norm_doi(cr["id"])
        if d in vistos_doi or _norm_titulo(cr["titulo"]) in vistos_tit:
            continue
        vistos_doi.add(d)
        vistos_tit.add(_norm_titulo(cr["titulo"]))
        salida.append(cr)
    return salida


# ───────────────────────────────────────────── API pública
# ───────────────────────────────────────────── Cobertura (¿cuántos hay en total, por fuente?)
def _oa_count(query: str, desde_anio: int | None) -> int | None:
    try:
        data = _get(_oa_url(query, 1, desde_anio), timeout=10)
        return (data.get("meta") or {}).get("count")
    except Exception:
        return None


def _pubmed_count(query: str, desde_anio: int | None) -> int | None:
    """Total en PubMed/MEDLINE vía E-utilities (solo el conteo, rápido)."""
    try:
        term = query
        if desde_anio:
            term += f" AND {desde_anio}:{datetime.date.today().year}[dp]"
        url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax=0&retmode=json"
               "&term=" + urllib.parse.quote(term))
        return int(((_get(url, timeout=10).get("esearchresult") or {}).get("count")) or 0)
    except Exception:
        return None


def _crossref_count(query: str, desde_anio: int | None) -> int | None:
    try:
        filtro = f"&filter=from-pub-date:{desde_anio}-01-01" if desde_anio else ""
        url = "https://api.crossref.org/works?rows=0&query=" + urllib.parse.quote(query) + filtro + "&mailto=" + _MAILTO
        return ((_get(url, timeout=10).get("message") or {}).get("total-results"))
    except Exception:
        return None


def _doaj_count(query: str) -> int | None:
    """Total en DOAJ (revistas de acceso abierto confiables)."""
    try:
        url = "https://doaj.org/api/v2/search/articles/" + urllib.parse.quote(query) + "?pageSize=1"
        return (_get(url, timeout=10).get("total"))
    except Exception:
        return None


def cobertura(query: str, anios: int | None = None) -> dict:
    """Cuántos resultados hay para la línea en cada gran fuente abierta (embudo de cobertura)."""
    query = (query or "").strip()
    desde = (datetime.date.today().year - int(anios) + 1) if (anios and anios > 0) else None
    return {"openalex": _oa_count(query, desde), "pubmed": _pubmed_count(query, desde),
            "crossref": _crossref_count(query, desde), "doaj": _doaj_count(query),
            "ventana_anios": anios or None}


# ───────────────────────────────────────────── Métricas de revista (OpenAlex Sources, abierto)
def metricas_revistas(source_ids: list[str]) -> dict:
    """Por revista (source de OpenAlex): país, H-index, nº de trabajos, citas 2y, DOAJ, editorial,
    ISSN y APC. Es la base ABIERTA de indicadores (el cuartil SJR se añade con el CSV de SCImago).
    Devuelve {source_id: {...}}. Lote de hasta 50 por llamada."""
    ids = [s for s in dict.fromkeys(source_ids) if s]
    out = {}
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        try:
            sel = "id,display_name,issn_l,issn,country_code,works_count,cited_by_count,summary_stats,is_in_doaj,host_organization_name,apc_usd"
            url = ("https://api.openalex.org/sources?per_page=50&mailto=" + _MAILTO +
                   "&select=" + sel + "&filter=ids.openalex:" + "|".join(lote))
            for s in (_get(url, timeout=12).get("results") or []):
                sid = (s.get("id") or "").rsplit("/", 1)[-1]
                ss = s.get("summary_stats") or {}
                issn = s.get("issn_l")
                m = {
                    "revista": s.get("display_name"), "issn": issn,
                    "pais": s.get("country_code"), "h_index": ss.get("h_index"),
                    "citas_2y": round(ss.get("2yr_mean_citedness"), 2) if ss.get("2yr_mean_citedness") is not None else None,
                    "works": s.get("works_count"), "citas_total": s.get("cited_by_count"),
                    "en_doaj": bool(s.get("is_in_doaj")), "editorial": s.get("host_organization_name"),
                    "apc_usd": s.get("apc_usd"),
                }
                # Cuartil SJR oficial (SCImago) por ISSN — el indicador de calidad autoritativo.
                try:
                    from app.services import scimago_service
                    sjr = None
                    for cand in ([issn] + list((s.get("issn") or []))):
                        sjr = scimago_service.metrica(cand)
                        if sjr:
                            break
                    if sjr:
                        m.update({"cuartil": sjr.get("cuartil"), "sjr": sjr.get("sjr"),
                                  "categorias": sjr.get("categorias"),
                                  "pais_sjr": sjr.get("pais_sjr")})
                except Exception:
                    pass
                out[sid] = m
        except Exception:
            continue
    return out


def buscar(query: str, rows: int = 8, anios: int | None = None) -> dict:
    """Artículos reales verificados por DOI, con abstract, citas, OA, cita APA 7/Vancouver y
    export BibTeX/RIS. `anios`: ventana temporal (5/10/15…; 0 o None = sin límite).

    Fuente primaria OpenAlex (relevancia + abstract + citas + OA), enriquecida con Crossref.
    Nunca inventa referencias; deduplica por DOI/título."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "n": 0, "articulos": [], "fuente": "OpenAlex",
                "nota": "Escribe una línea de investigación para buscar."}

    desde_anio = None
    if anios and anios > 0:
        desde_anio = datetime.date.today().year - int(anios) + 1

    primaria, enriquecedora, fuentes = [], [], []
    try:
        primaria = _openalex(query, rows=max(rows, 8), desde_anio=desde_anio)
        if primaria:
            fuentes.append("OpenAlex")
    except Exception:
        primaria = []
    try:
        enriquecedora = _crossref(query, rows=max(rows, 8), desde_anio=desde_anio)
        if enriquecedora:
            fuentes.append("Crossref")
    except Exception:
        enriquecedora = []

    if not primaria and not enriquecedora:
        return {"query": query, "n": 0, "articulos": [], "fuente": "OpenAlex",
                "error": "sin_conexion",
                "nota": "No se pudo consultar OpenAlex/Crossref en este momento."}

    fusion = _fusionar(primaria or enriquecedora, enriquecedora if primaria else [])
    seleccion = fusion[:rows]
    # métricas de revista (OpenAlex Sources) para las revistas del resultado
    met = {}
    try:
        met = metricas_revistas([r.get("source_id") for r in seleccion if r.get("source_id")])
    except Exception:
        met = {}
    arts = []
    for r in seleccion:
        arts.append({
            "titulo": r["titulo"], "anio": r.get("anio"), "revista": r.get("revista"),
            "id_tipo": r["id_tipo"], "id": r["id"], "url": r["url"], "tipo": r.get("tipo"),
            "pmid": r.get("pmid"), "pmcid": r.get("pmcid"),
            "abstract": r.get("abstract"), "citas": r.get("citas"),
            "oa": r.get("oa"), "oa_estado": r.get("oa_estado"), "oa_url": r.get("oa_url"),
            "issn": r.get("issn"), "idioma": r.get("idioma"),
            "metricas": met.get(r.get("source_id")),   # país, H-index, citas, DOAJ, editorial…
            "apa": formatear(r, "apa"), "vancouver": formatear(r, "vancouver"),
            "bibtex": _bibtex(r), "ris": _ris(r),
        })
    total = None
    try:
        total = _oa_count(query, desde_anio)
    except Exception:
        total = None
    nota = "Referencias reales verificadas por DOI; nunca inventadas."
    if desde_anio:
        nota += f" Ventana: {desde_anio}–{datetime.date.today().year} (últimos {anios} años)."
    return {"query": query, "n": len(arts), "articulos": arts, "total": total,
            "fuente": " + ".join(fuentes) or "OpenAlex",
            "ventana_anios": anios or None, "desde_anio": desde_anio, "nota": nota}


def buscar_corpus(query: str, anios: int | None = None, limite: int = 150) -> dict:
    """Corpus de candidatos para el tablero de cribado de una revisión sistemática.

    Pagina OpenAlex por cursor (per_page 100) hasta `limite`. Devuelve el conjunto completo,
    deduplicado por DOI, con los campos que necesita el cribado (abstract, citas, OA, cita APA).
    Solo OpenAlex (sin enriquecer con Crossref: a esta escala la latencia no lo permite; la cita
    limpia se enriquece al seleccionar el estudio). Nunca incluye ítems sin DOI verificable."""
    query = (query or "").strip()
    limite = max(10, min(int(limite or 150), 300))
    if not query:
        return {"query": query, "n": 0, "articulos": [], "fuente": "OpenAlex",
                "limite": limite, "truncado": False, "nota": "Escribe una línea de investigación."}

    desde_anio = None
    if anios and anios > 0:
        desde_anio = datetime.date.today().year - int(anios) + 1

    per_page = 100
    vistos_doi, vistos_tit, refs = set(), set(), []
    cursor = "*"
    total_disponible = None
    try:
        while cursor and len(refs) < limite:
            data = _get(_oa_url(query, per_page, desde_anio, cursor), timeout=20)
            if total_disponible is None:
                total_disponible = (data.get("meta") or {}).get("count")
            resultados = data.get("results") or []
            if not resultados:
                break
            for it in resultados:
                r = _oa_item(it)
                if not r:
                    continue
                d = _norm_doi(r["id"])
                t = _norm_titulo(r["titulo"])
                if d in vistos_doi or t in vistos_tit:
                    continue
                vistos_doi.add(d)
                vistos_tit.add(t)
                refs.append(r)
                if len(refs) >= limite:
                    break
            cursor = (data.get("meta") or {}).get("next_cursor")
    except Exception:
        if not refs:
            return {"query": query, "n": 0, "articulos": [], "fuente": "OpenAlex",
                    "limite": limite, "truncado": False, "error": "sin_conexion",
                    "nota": "No se pudo consultar OpenAlex en este momento."}

    # métricas de revista (país, H-index, DOAJ, cuartil SJR…) para todo el corpus
    met = {}
    try:
        met = metricas_revistas([r.get("source_id") for r in refs if r.get("source_id")])
    except Exception:
        met = {}
    arts = []
    for r in refs:
        arts.append({
            "titulo": r["titulo"], "anio": r.get("anio"), "revista": r.get("revista"),
            "id_tipo": r["id_tipo"], "id": r["id"], "url": r["url"], "tipo": r.get("tipo"),
            "pmid": r.get("pmid"), "pmcid": r.get("pmcid"),
            "abstract": r.get("abstract"), "citas": r.get("citas"),
            "oa": r.get("oa"), "oa_estado": r.get("oa_estado"), "oa_url": r.get("oa_url"),
            "issn": r.get("issn"), "idioma": r.get("idioma"),
            "metricas": met.get(r.get("source_id")),
            "autores_str": _apa_autores(r.get("autores", [])),
            "apa": formatear(r, "apa"), "vancouver": formatear(r, "vancouver"),
            "bibtex": _bibtex(r), "ris": _ris(r),
        })
    truncado = bool(total_disponible and total_disponible > len(arts))
    nota = f"{len(arts)} candidatos verificados por DOI (OpenAlex)."
    if desde_anio:
        nota += f" Ventana {desde_anio}–{datetime.date.today().year}."
    if truncado:
        nota += f" Hay ~{total_disponible} en total; se trajeron los {len(arts)} más relevantes."
    return {"query": query, "n": len(arts), "articulos": arts, "fuente": "OpenAlex",
            "limite": limite, "total_disponible": total_disponible, "truncado": truncado,
            "ventana_anios": anios or None, "desde_anio": desde_anio, "nota": nota}
