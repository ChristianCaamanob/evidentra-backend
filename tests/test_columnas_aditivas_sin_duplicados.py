"""Una clave repetida en _COLUMNAS_ADITIVAS se pierde en silencio.

Ocurrió de verdad: `courses` estaba dos veces y la segunda ocurrencia descartó
`color`/`emoji`, así que las columnas nunca se crearon en producción y
GET /courses/ caía con 500 al leer `c.color`. Python no avisa de esto, así que
lo revisamos sobre el árbol sintáctico, que sí conserva ambas ocurrencias.
"""
import ast
import pathlib
from collections import Counter

DB_PY = pathlib.Path(__file__).resolve().parents[1] / "app" / "core" / "db.py"

DICTS_VIGILADOS = {"_COLUMNAS_ADITIVAS"}


def _dicts_literales():
    arbol = ast.parse(DB_PY.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Dict):
            continue
        nombre = getattr(nodo.targets[0], "id", None)
        if nombre in DICTS_VIGILADOS:
            yield nombre, nodo.value


def test_sin_tablas_repetidas():
    for nombre, dic in _dicts_literales():
        tablas = [k.value for k in dic.keys if isinstance(k, ast.Constant)]
        repetidas = {t: n for t, n in Counter(tablas).items() if n > 1}
        assert not repetidas, (
            f"{nombre} repite {sorted(repetidas)}: la última ocurrencia pisa a las "
            f"anteriores y esas columnas nunca se crean. Fusiona las entradas."
        )


def test_courses_declara_identidad_visual():
    """color/emoji son los que se perdieron; que no vuelvan a desaparecer."""
    from app.core.db import _COLUMNAS_ADITIVAS

    cols = _COLUMNAS_ADITIVAS["courses"]
    assert "color" in cols and "emoji" in cols
