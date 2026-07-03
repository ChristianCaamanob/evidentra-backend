#!/usr/bin/env python3
"""
Corre TODAS las guardas de gobernanza. El orquestador lo invoca en cada
iteracion: si algo falla, la iteracion no puede darse por buena (no hay commit,
no se marca el hito como hecho).

Uso:
    python checks/run_all_checks.py               # sobre code_root de loop_config.json
    python checks/run_all_checks.py [ruta]
    python checks/run_all_checks.py --self-test   # corre los self-test de cada guarda sobre fixtures/
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_seudonimizacion as g2  # noqa: E402
import check_propositiva as g6      # noqa: E402

CHECKS = [("G2 Seudonimizacion", g2), ("G6 Postura propositiva", g6)]


def main(argv: list[str]) -> int:
    passthrough = [a for a in argv[1:]]
    rc_total = 0
    print("=== Guardas de gobernanza Evalys ===")
    for name, mod in CHECKS:
        rc = mod.main([mod.__name__] + passthrough)
        status = "OK" if rc == 0 else "FALLA"
        print(f"  -> {name}: {status}\n")
        rc_total |= rc
    if rc_total == 0:
        print("TODAS las guardas en verde.")
    else:
        print("HAY violaciones de gobernanza. La iteracion NO se da por buena.")
    return rc_total


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
