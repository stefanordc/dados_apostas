from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.repositories.history_repository import detect_history_schema, history_columns  # noqa: E402


if __name__ == "__main__":
    print("Colunas encontradas:")
    for column in history_columns():
        print(f"- {column}")
    print("\nMapeamento automático:")
    for canonical, actual in detect_history_schema().items():
        print(f"- {canonical}: {actual}")
