"""Motor de referencias (Investigador #1): dedup, cero citas inventadas, export, ventana.

Sin red: se mockean _openalex / _crossref para probar la lógica de fusión y formato.
"""
from app.services import literatura_service as L


def _oa_ref(doi, titulo, anio=2022, autores=None, abstract="abs", citas=10, oa=True):
    return {"id_tipo": "DOI", "id": doi, "url": "https://doi.org/" + doi, "titulo": titulo,
            "autores": autores if autores is not None else [{"family": "Perez", "given": "Ana"}],
            "revista": "Rev X", "issn": "1234-5678", "anio": anio, "volumen": "9", "numero": "3",
            "paginas": "10-20", "tipo": "article", "abstract": abstract, "citas": citas,
            "oa": oa, "oa_estado": "gold" if oa else "closed", "oa_url": None, "_fuente": "OpenAlex"}


def _cr_ref(doi, titulo, anio=2022, autores=None):
    return {"id_tipo": "DOI", "id": doi, "url": "https://doi.org/" + doi, "titulo": titulo,
            "autores": autores if autores is not None else [{"family": "García", "given": "Juan Luis"}],
            "revista": "Rev X", "issn": "1234-5678", "anio": anio, "volumen": "9",
            "numero": "3", "paginas": "10-20", "tipo": "article", "_fuente": "Crossref"}


def test_dedup_por_doi(monkeypatch):
    # El mismo DOI en OpenAlex y Crossref no debe duplicarse.
    monkeypatch.setattr(L, "_openalex", lambda q, rows, desde_anio: [_oa_ref("10.1/a", "Uno")])
    monkeypatch.setattr(L, "_crossref", lambda q, rows=8, desde_anio=None: [_cr_ref("10.1/A", "Uno")])
    r = L.buscar("algo", rows=8)
    assert r["n"] == 1  # 10.1/a == 10.1/A tras normalizar


def test_crossref_enriquece_autores(monkeypatch):
    # OpenAlex trae abstract/citas; Crossref aporta los autores limpios del mismo DOI.
    monkeypatch.setattr(L, "_openalex", lambda q, rows, desde_anio: [
        _oa_ref("10.1/a", "Uno", autores=[{"family": "Garcialuis", "given": ""}])])
    monkeypatch.setattr(L, "_crossref", lambda q, rows=8, desde_anio=None: [
        _cr_ref("10.1/a", "Uno", autores=[{"family": "García", "given": "Juan Luis"}])])
    a = L.buscar("algo")["articulos"][0]
    assert "García" in a["apa"] and a["abstract"] == "abs" and a["citas"] == 10


def test_cero_inventadas_sin_doi(monkeypatch):
    # Un ítem sin DOI jamás aparece (regla de integridad).
    monkeypatch.setattr(L, "_openalex", lambda q, rows, desde_anio: [])
    monkeypatch.setattr(L, "_crossref", lambda q, rows=8, desde_anio=None: [])
    r = L.buscar("algo")
    assert r["n"] == 0 and r["articulos"] == []


def test_ventana_anios_calcula_desde(monkeypatch):
    import datetime
    capt = {}

    def fake_oa(q, rows, desde_anio):
        capt["desde"] = desde_anio
        return [_oa_ref("10.1/a", "Uno")]
    monkeypatch.setattr(L, "_openalex", fake_oa)
    monkeypatch.setattr(L, "_crossref", lambda q, rows=8, desde_anio=None: [])
    r = L.buscar("algo", anios=10)
    assert capt["desde"] == datetime.date.today().year - 9
    assert r["ventana_anios"] == 10


def test_export_bibtex_y_ris():
    ref = _cr_ref("10.1/a", "Un título")
    bib = L._bibtex(ref)
    ris = L._ris(ref)
    assert bib.startswith("@article{") and "doi = {10.1/a}" in bib
    assert "TY  - JOUR" in ris and "ER  - " in ris and "SP  - 10" in ris and "EP  - 20" in ris


def test_abstract_invertido():
    idx = {"Formative": [0], "assessment": [1], "works": [2]}
    assert L._abstract_desde_invertido(idx) == "Formative assessment works"
    assert L._abstract_desde_invertido(None) is None


def test_split_nombre_particulas():
    assert L._split_nombre("Jörg Henseler")["family"] == "Henseler"
    r = L._split_nombre("Jan van der Berg")
    assert r["family"] == "van der Berg" and r["given"] == "Jan"


def _oa_work(doi, titulo, anio=2022):
    return {"doi": "https://doi.org/" + doi, "title": titulo, "publication_year": anio,
            "authorships": [{"author": {"display_name": "Ana Perez"}}],
            "primary_location": {"source": {"display_name": "Rev X", "issn_l": "1-2"}},
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "cited_by_count": 5, "type": "article", "biblio": {"volume": "1"},
            "abstract_inverted_index": {"Hola": [0]}}


def test_corpus_pagina_dedup_y_trunca(monkeypatch):
    # Dos páginas; la 2ª repite un DOI (dedup) y trae uno nuevo. total_disponible>n -> truncado.
    paginas = [
        {"results": [_oa_work("10.1/a", "Uno"), _oa_work("10.1/b", "Dos")],
         "meta": {"count": 50, "next_cursor": "c2"}},
        {"results": [_oa_work("10.1/B", "Dos"), _oa_work("10.1/c", "Tres")],
         "meta": {"count": 50, "next_cursor": None}},
    ]
    llamadas = {"i": 0}

    def fake_get(url, timeout=12):
        p = paginas[llamadas["i"]]; llamadas["i"] += 1
        return p
    monkeypatch.setattr(L, "_get", fake_get)
    r = L.buscar_corpus("algo", limite=150)
    dois = [a["id"] for a in r["articulos"]]
    assert r["n"] == 3 and len(set(dois)) == 3           # a, b, c (B duplicado eliminado)
    assert r["total_disponible"] == 50 and r["truncado"] is True
    assert all(a.get("autores_str") and a.get("bibtex") for a in r["articulos"])


def test_corpus_respeta_limite(monkeypatch):
    def fake_get(url, timeout=12):
        return {"results": [_oa_work(f"10.1/{i}", f"T{i}") for i in range(100)],
                "meta": {"count": 999, "next_cursor": "x"}}
    monkeypatch.setattr(L, "_get", fake_get)
    r = L.buscar_corpus("algo", limite=30)
    assert r["n"] == 30 and r["truncado"] is True
