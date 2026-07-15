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
