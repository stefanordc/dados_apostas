from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import PROJECT_ROOT, get_settings
from src.countries import COUNTRIES


@lru_cache(maxsize=1)
def app_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.app_database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        future=True,
    )


@lru_cache(maxsize=1)
def history_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.history_database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        future=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


def ensure_schema() -> None:
    schema_file = Path(PROJECT_ROOT) / "sql" / "schema.sql"
    sql = schema_file.read_text(encoding="utf-8")
    statements = [chunk.strip() for chunk in sql.split("-- statement") if chunk.strip()]
    with app_engine().begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)


def seed_countries() -> None:
    with app_engine().begin() as conn:
        for name, continent in COUNTRIES:
            exists = conn.execute(
                text("SELECT id FROM backtest_apostas.paises WHERE LOWER(nome)=LOWER(:nome) LIMIT 1"),
                {"nome": name},
            ).scalar_one_or_none()
            if exists is None:
                conn.execute(
                    text("INSERT INTO backtest_apostas.paises (nome, continente) VALUES (:nome, :continente)"),
                    {"nome": name, "continente": continent},
                )


def initialize_database() -> None:
    ensure_schema()
    seed_countries()
