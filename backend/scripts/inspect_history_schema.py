from pathlib import Path
import sys
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import history_connection
from app.config import settings

with history_connection() as conn:
    rows = conn.execute(text('''
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
    '''), {"schema": settings.history_schema, "table": settings.history_table}).scalars().all()

required = {"pais","temporada","campeonato","rodada","casa","fora","gols_casa","gols_fora"}
missing = sorted(required - set(rows))

print("Colunas historico_jogos:")
for col in rows:
    print(f"- {col}")

if missing:
    raise SystemExit("Colunas obrigatorias ausentes: " + ", ".join(missing))

print("Historico validado com sucesso.")
