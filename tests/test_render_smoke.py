"""
Test de aceptacion del hito E3-render-informe (loop de avance de Evalys).

El frontend es un unico HTML con JS inline y sin toolchain (no hay node/build), asi
que el "smoke" es estructural sobre el archivo:

DoD que verifica (de estados.json):
  1. Existe un render DATA-DRIVEN (renderInformeIndividual(datos)) que consume el
     contrato `datos` de E1 (todas sus claves aparecen en el render).
  2. El informe se conecta al backend real (GET /results/{scan_id}/informe).
  3. No rompe el resto de la app: se conserva la plantilla de referencia (caso Rojas),
     el bootstrap del flujo, y las etiquetas <script> quedan balanceadas.
"""
from __future__ import annotations
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "evalys-app.html").read_text(
    encoding="utf-8", errors="ignore"
)

CONTRATO = [
    "estudiante", "evaluacion", "desempeno", "distribucion_curso",
    "dimensiones_bloom", "mapa_preguntas", "brechas", "fortalezas",
    "plan_consolidacion", "mensaje_personalizado", "metadata",
]


def _cuerpo_render() -> str:
    """Devuelve el cuerpo de la funcion renderInformeIndividual (hasta fetchInforme)."""
    ini = HTML.index("function renderInformeIndividual(datos)")
    fin = HTML.index("async function fetchInforme", ini)
    return HTML[ini:fin]


def test_existe_render_datadriven():
    assert "function renderInformeIndividual(datos)" in HTML, (
        "debe existir renderInformeIndividual(datos), el render data-driven"
    )


def test_render_consume_todo_el_contrato():
    cuerpo = _cuerpo_render()
    faltan = [k for k in CONTRATO if f"datos.{k}" not in cuerpo and f'"{k}"' not in cuerpo]
    assert not faltan, f"el render no consume estas claves de `datos`: {faltan}"


def test_conecta_endpoint_e1():
    assert "async function fetchInforme" in HTML
    assert "/results/${scanId}/informe" in HTML, (
        "fetchInforme debe pedir GET /results/{scan_id}/informe (contrato E1)"
    )


def test_no_rompe_el_resto():
    # La plantilla de referencia (Rojas) se conserva; el bootstrap del flujo sigue.
    assert "brfReportRojasContent" in HTML, "no debe eliminarse la plantilla de referencia"
    assert "renderMvpFlow" in HTML and "BRIEFING_UNIVERSE" in HTML
    # Etiquetas <script> balanceadas (heuristica de integridad del documento).
    # Se cuenta tambien el cierre escapado <\/script> que aparece dentro de strings JS
    # (p. ej. document.write('...<script>...<\/script>...')), valido y balanceado.
    abiertos = HTML.count("<script")
    cerrados = HTML.count("</script>") + HTML.count("<\\/script>")
    assert abiertos == cerrados, f"<script> desbalanceados: {abiertos} abren, {cerrados} cierran"


def test_postura_propositiva_en_el_render():
    """G6: el render no usa lenguaje auditor del programa."""
    cuerpo = _cuerpo_render().lower()
    for prohibido in ("auditar el curr", "brecha del programa", "desalinea"):
        assert prohibido not in cuerpo, f"lenguaje no propositivo en el render: {prohibido}"
