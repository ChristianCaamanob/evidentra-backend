#!/usr/bin/env python3
"""
Guarda de gobernanza G6 - POSTURA PROPOSITIVA (no auditora).

Regla (doc de gobernanza Evalys): el lenguaje de reportes y UI es propositivo,
nunca auditor del curriculo. Este check falla si aparecen terminos prohibidos
en archivos de reporte/UI (.html, .jsx, .md, .py de templates/reportes).

Uso:
    python checks/check_propositiva.py [ruta]
    python checks/check_propositiva.py --self-test   # verifica que atrapa el termino prohibido en fixtures/

Salida: exit 0 si limpio, exit 1 si encuentra lenguaje auditor.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

FORBIDDEN_PHRASES = [
    r"auditar el curr[ií]culo",
    r"auditor[ií]a curricular",
    r"brecha[s]? del programa",
    r"desalineaci[oó]n",
    r"evaluar (la )?calidad del curr[ií]culo",
    r"inconsistencias del perfil de egreso",
    r"detectar desalinea",
]

SCAN_EXT = {".html", ".jsx", ".tsx", ".js", ".md", ".py", ".txt"}


def scan(root: Path, include_fixtures: bool = False) -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    patterns = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PHRASES]
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in SCAN_EXT:
            continue
        if any(part in {".venv", "venv", "__pycache__", "node_modules", ".git"} for part in f.parts):
            continue
        if not include_fixtures and "fixtures" in f.parts:
            continue  # ejemplos malos a proposito, no codigo real
        # No auto-marcar este propio check ni el ledger (contienen los terminos como ejemplo).
        if f.name in {"check_propositiva.py", "estados.json", "README.md"}:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for pat in patterns:
                    if pat.search(line):
                        findings.append((f, i, pat.pattern))
        except Exception:
            continue
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
            print("[G6] self-test OK: el check atrapa el lenguaje auditor en fixtures/.")
            return 0
        print("[G6] self-test FALLO: no se atrapo el termino prohibido esperado.")
        return 1

    root = Path(argv[1]) if len(argv) > 1 else _code_root_from_config()
    if not root.exists():
        print(f"[G6] ruta inexistente: {root} (nada que revisar).")
        return 0
    findings = scan(root)
    if not findings:
        print(f"[G6] POSTURA PROPOSITIVA OK: sin lenguaje auditor ({root}).")
        return 0
    print(f"[G6] VIOLACION: lenguaje auditor detectado ({len(findings)}):")
    for p, lineno, pat in findings:
        print(f"   - {p}:{lineno}  coincide /{pat}/")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
