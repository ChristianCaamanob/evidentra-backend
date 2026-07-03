"""Raiz de pytest: asegura que el paquete `app` sea importable desde tests/."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
