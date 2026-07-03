#!/usr/bin/env python3
"""
Guarda de gobernanza G2 - SEUDONIMIZACION.

Regla (Ley 21.719, doc de gobernanza Evalys): ningun dato identificatorio
(nombre, RUT, correo) puede viajar a la IA. Este check recorre el codigo,
encuentra los sitios donde se llama a un modelo (Anthropic/Claude) y falla
si en ese call aparece un campo identificatorio prohibido.

Es heuristico a proposito (rapido y sin dependencias): busca llamadas del
tipo `*.messages.create(...)` o funciones cuyo nombre sugiera una llamada al
modelo, y revisa el texto del argumento en busca de campos prohibidos.

Uso:
    python checks/check_seudonimizacion.py [ruta]        # ruta por defecto: code_root de loop_config.json, o "."
    python checks/check_seudonimizacion.py --self-test   # corre sobre fixtures/ y verifica que atrapa el caso malo

Salida: exit 0 si limpio, exit 1 si encuentra una posible fuga.
"""
from __future__ import annotations
import ast
import json
import sys
from pathlib import Path

FORBIDDEN_FIELDS = [
    "nombre", "name", "full_name", "first_name", "last_name", "nombre_completo",
    "rut", "run", "dni", "cedula",
    "correo", "email", "mail",
]

# Senales de que una llamada apunta al modelo de IA.
AI_CALL_HINTS = ("messages.create", "anthropic", "claude", "llm", "completions.create")


def _looks_like_ai_call(call_src: str) -> bool:
    low = call_src.lower()
    return any(h in low for h in AI_CALL_HINTS)


def _scan_python(path: Path) -> list[tuple[int, str]]:
    """Devuelve [(lineno, campo_prohibido)] por posibles fugas en un .py."""
    hits: list[tuple[int, str]] = []
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return hits
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        try:
            call_src = ast.get_source_segment(src, node) or ""
        except Exception:
            call_src = ""
        if not call_src or not _looks_like_ai_call(call_src):
            continue
        low = call_src.lower()
        for field in FORBIDDEN_FIELDS:
            # Coincidencia como clave/atributo: "nombre", 'name', .email, etc.
            for pat in (f'"{field}"', f"'{field}'", f".{field}", f"[{field}]"):
                if pat in low:
                    hits.append((getattr(node, "lineno", 0), field))
                    break
    return hits


def scan(root: Path, include_fixtures: bool = False) -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    for py in root.rglob("*.py"):
        if any(part in {".venv", "venv", "__pycache__", "node_modules", ".git"} for part in py.parts):
            continue
        if not include_fixtures and "fixtures" in py.parts:
            continue  # los fixtures son ejemplos malos a proposito, no codigo real
        for lineno, field in _scan_python(py):
            findings.append((py, lineno, field))
    return findings


def _code_root_from_config() -> Path:
    cfg = Path(__file__).resolve().parent.parent / "loop_config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            cr = data.get("code_root")
            if cr:
                return Path(cr)
        except Exception:
            pass
    return Path(".")


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        root = Path(__file__).resolve().parent.parent / "fixtures"
        findings = scan(root, include_fixtures=True)
        ok = any("malo" in str(p).lower() or "bad" in str(p).lower() for p, _, _ in findings)
        if ok:
            print("[G2] self-test OK: el check atrapa la fuga en fixtures/.")
            return 0
        print("[G2] self-test FALLO: el check no atrapo la fuga esperada en fixtures/.")
        return 1

    root = Path(argv[1]) if len(argv) > 1 else _code_root_from_config()
    if not root.exists():
        print(f"[G2] ruta inexistente: {root} (nada que revisar).")
        return 0
    findings = scan(root)
    if not findings:
        print(f"[G2] SEUDONIMIZACION OK: sin identificatorios en llamadas a la IA ({root}).")
        return 0
    print(f"[G2] VIOLACION: posible identificatorio hacia la IA ({len(findings)}):")
    for p, lineno, field in findings:
        print(f"   - {p}:{lineno}  campo '{field}' en un call al modelo")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
