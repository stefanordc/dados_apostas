from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    app_database_url: str
    history_database_url: str
    history_schema: str = "public"
    history_table: str = "historico_jogos"


def get_settings() -> Settings:
    app_url = os.getenv("APP_DATABASE_URL", "").strip()
    history_url = os.getenv("HISTORY_DATABASE_URL", "").strip()
    if not app_url or not history_url:
        raise RuntimeError(
            "As variáveis APP_DATABASE_URL e HISTORY_DATABASE_URL não foram configuradas. "
            "Crie o arquivo .env a partir do .env.example ou execute atualizar_projeto.ps1."
        )
    return Settings(
        app_database_url=app_url,
        history_database_url=history_url,
        history_schema=os.getenv("HISTORY_SCHEMA", "public").strip() or "public",
        history_table=os.getenv("HISTORY_TABLE", "historico_jogos").strip() or "historico_jogos",
    )
