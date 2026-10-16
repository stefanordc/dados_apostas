from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    app_database_url: str
    history_database_url: str
    app_schema: str = "backtest_apostas"
    history_schema: str = "public"
    history_table: str = "historico_jogos"
    frontend_origin: str = "http://localhost:5173"
    futpy_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
