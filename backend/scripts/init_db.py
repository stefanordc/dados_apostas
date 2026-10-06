from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schema import initialize_database

initialize_database()
print("Banco principal inicializado.")
