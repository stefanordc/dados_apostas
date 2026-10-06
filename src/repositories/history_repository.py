from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import text

from src.config import get_settings
from src.db import history_engine
from src.utils import normalize_text

COLUMN_ALIASES: dict[str, list[str]] = {
    "pais": ["pais", "país", "country"],
    "temporada": ["temporada", "season"],
    "campeonato": ["campeonato", "competicao", "competição", "liga", "league", "tournament"],
    "rodada": ["rodada", "fase", "round", "stage"],
    "mandante": ["mandante", "casa", "time_casa", "clube_casa", "home_team", "home", "hometeam"],
    "visitante": ["visitante", "fora", "time_fora", "clube_fora", "away_team", "away", "awayteam"],
    "gols_casa": ["gols_casa", "gols_mandante", "gol_casa", "home_goals", "fthg", "hg"],
    "gols_fora": ["gols_fora", "gols_visitante", "gol_fora", "away_goals", "ftag", "ag"],
    "data": ["data", "data_jogo", "match_date", "date"],
}

REQUIRED = ["pais", "temporada", "campeonato", "rodada", "mandante", "visitante", "gols_casa", "gols_fora"]


@dataclass(frozen=True)
class HistoryFilters:
    country: str | None = None
    season: str | None = None
    championship: str | None = None
    phase: str | None = None
    club: str | None = None
    home: str | None = None
    away: str | None = None
    goals_home_min: int | None = None
    goals_home_max: int | None = None
    goals_away_min: int | None = None
    goals_away_max: int | None = None
    goal_diff_min: int | None = None
    goal_diff_max: int | None = None
    winner: str | None = None
    home_winner: str | None = None  # Todos / Sim / Não
    away_winner: str | None = None


@lru_cache(maxsize=1)
def detect_history_schema() -> dict[str, str]:
    settings = get_settings()
    with history_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=:schema AND table_name=:table
                ORDER BY ordinal_position
                """
            ),
            {"schema": settings.history_schema, "table": settings.history_table},
        ).scalars().all()
    if not rows:
        raise RuntimeError(
            f"A tabela {settings.history_schema}.{settings.history_table} não foi encontrada no banco histórico."
        )

    by_normalized = {normalize_text(name): name for name in rows}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            actual = by_normalized.get(normalize_text(alias))
            if actual:
                mapping[canonical] = actual
                break

    missing = [name for name in REQUIRED if name not in mapping]
    if missing:
        available = ", ".join(rows)
        raise RuntimeError(
            "Não foi possível identificar automaticamente as colunas: "
            + ", ".join(missing)
            + f". Colunas encontradas em historico_jogos: {available}"
        )
    return mapping


def history_columns() -> list[str]:
    settings = get_settings()
    with history_engine().connect() as conn:
        return list(
            conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema=:schema AND table_name=:table
                    ORDER BY ordinal_position
                    """
                ),
                {"schema": settings.history_schema, "table": settings.history_table},
            ).scalars().all()
        )


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_ref() -> str:
    settings = get_settings()
    return f"{_q(settings.history_schema)}.{_q(settings.history_table)}"


def _base_aliases() -> tuple[dict[str, str], dict[str, str]]:
    mapping = detect_history_schema()
    q = {key: f"h.{_q(value)}" for key, value in mapping.items()}
    return mapping, q


def _where(filters: HistoryFilters) -> tuple[str, dict[str, Any]]:
    _mapping, c = _base_aliases()
    clauses = [f"{c['gols_casa']} IS NOT NULL", f"{c['gols_fora']} IS NOT NULL"]
    params: dict[str, Any] = {}

    def add_eq(key: str, value: Any, param: str) -> None:
        if value is not None and value != "":
            clauses.append(f"{c[key]} = :{param}")
            params[param] = value

    add_eq("pais", filters.country, "country")
    add_eq("temporada", filters.season, "season")
    add_eq("campeonato", filters.championship, "championship")
    add_eq("rodada", filters.phase, "phase")
    add_eq("mandante", filters.home, "home")
    add_eq("visitante", filters.away, "away")

    if filters.club:
        clauses.append(f"({c['mandante']} = :club OR {c['visitante']} = :club)")
        params["club"] = filters.club

    if filters.winner:
        clauses.append(
            f"(({c['mandante']} = :winner AND {c['gols_casa']} > {c['gols_fora']}) "
            f"OR ({c['visitante']} = :winner AND {c['gols_fora']} > {c['gols_casa']}))"
        )
        params["winner"] = filters.winner

    ranges = [
        (filters.goals_home_min, f"{c['gols_casa']} >= :goals_home_min", "goals_home_min"),
        (filters.goals_home_max, f"{c['gols_casa']} <= :goals_home_max", "goals_home_max"),
        (filters.goals_away_min, f"{c['gols_fora']} >= :goals_away_min", "goals_away_min"),
        (filters.goals_away_max, f"{c['gols_fora']} <= :goals_away_max", "goals_away_max"),
        (filters.goal_diff_min, f"ABS({c['gols_casa']} - {c['gols_fora']}) >= :goal_diff_min", "goal_diff_min"),
        (filters.goal_diff_max, f"ABS({c['gols_casa']} - {c['gols_fora']}) <= :goal_diff_max", "goal_diff_max"),
    ]
    for value, clause, name in ranges:
        if value is not None:
            clauses.append(clause)
            params[name] = int(value)

    if filters.home_winner == "Sim":
        clauses.append(f"{c['gols_casa']} > {c['gols_fora']}")
    elif filters.home_winner == "Não":
        clauses.append(f"{c['gols_casa']} <= {c['gols_fora']}")

    if filters.away_winner == "Sim":
        clauses.append(f"{c['gols_fora']} > {c['gols_casa']}")
    elif filters.away_winner == "Não":
        clauses.append(f"{c['gols_fora']} <= {c['gols_casa']}")

    return " AND ".join(clauses), params


def _without(filters: HistoryFilters, *fields: str) -> HistoryFilters:
    updates = {field: None for field in fields}
    return replace(filters, **updates)


def distinct_options(field: str, filters: HistoryFilters) -> list[str]:
    mapping, c = _base_aliases()
    if field not in mapping:
        return []
    scoped = _without(filters, {
        "pais": "country",
        "temporada": "season",
        "campeonato": "championship",
        "rodada": "phase",
        "mandante": "home",
        "visitante": "away",
    }.get(field, "")) if field in {"pais", "temporada", "campeonato", "rodada", "mandante", "visitante"} else filters
    where, params = _where(scoped)
    sql = f"""
        SELECT DISTINCT {c[field]} AS value
        FROM {_table_ref()} h
        WHERE {where} AND {c[field]} IS NOT NULL
        ORDER BY 1
    """
    with history_engine().connect() as conn:
        values = conn.execute(text(sql), params).scalars().all()
    return [str(value) for value in values if value is not None and str(value).strip()]


def club_options(filters: HistoryFilters) -> list[str]:
    _mapping, c = _base_aliases()
    scoped = _without(filters, "club", "winner", "home", "away")
    where, params = _where(scoped)
    sql = f"""
        SELECT DISTINCT value FROM (
            SELECT {c['mandante']}::text AS value FROM {_table_ref()} h WHERE {where}
            UNION
            SELECT {c['visitante']}::text AS value FROM {_table_ref()} h WHERE {where}
        ) x
        WHERE value IS NOT NULL AND BTRIM(value) <> ''
        ORDER BY value
    """
    # where appears twice; named parameters are safe to reuse.
    with history_engine().connect() as conn:
        values = conn.execute(text(sql), params).scalars().all()
    return [str(value) for value in values]


def winner_options(filters: HistoryFilters) -> list[str]:
    _mapping, c = _base_aliases()
    scoped = _without(filters, "winner")
    where, params = _where(scoped)
    sql = f"""
        SELECT DISTINCT winner FROM (
            SELECT CASE
                WHEN {c['gols_casa']} > {c['gols_fora']} THEN {c['mandante']}::text
                WHEN {c['gols_fora']} > {c['gols_casa']} THEN {c['visitante']}::text
                ELSE NULL
            END AS winner
            FROM {_table_ref()} h
            WHERE {where}
        ) x
        WHERE winner IS NOT NULL AND BTRIM(winner) <> ''
        ORDER BY winner
    """
    with history_engine().connect() as conn:
        values = conn.execute(text(sql), params).scalars().all()
    return [str(value) for value in values]


def aggregate(filters: HistoryFilters) -> dict[str, float]:
    _mapping, c = _base_aliases()
    where, params = _where(filters)
    sql = f"""
        SELECT
            COUNT(*)::bigint AS total_jogos,
            SUM(CASE WHEN {c['gols_casa']} > {c['gols_fora']} THEN 1 ELSE 0 END)::bigint AS vitorias_casa,
            SUM(CASE WHEN {c['gols_fora']} > {c['gols_casa']} THEN 1 ELSE 0 END)::bigint AS vitorias_fora,
            COALESCE(SUM({c['gols_casa']}), 0)::numeric AS gols_casa,
            COALESCE(SUM({c['gols_fora']}), 0)::numeric AS gols_fora,
            COALESCE(AVG({c['gols_casa']}), 0)::numeric AS media_gols_casa,
            COALESCE(AVG({c['gols_fora']}), 0)::numeric AS media_gols_fora,
            COALESCE(AVG({c['gols_casa']} + {c['gols_fora']}), 0)::numeric AS media_gols_geral
        FROM {_table_ref()} h
        WHERE {where}
    """
    with history_engine().connect() as conn:
        row = conn.execute(text(sql), params).mappings().one()
    data = {key: float(value or 0) for key, value in row.items()}
    total = data["total_jogos"]
    data["pct_vitorias_casa"] = (data["vitorias_casa"] / total * 100) if total else 0.0
    data["pct_vitorias_fora"] = (data["vitorias_fora"] / total * 100) if total else 0.0
    data["total_gols"] = data["gols_casa"] + data["gols_fora"]
    return data


def filtered_games(filters: HistoryFilters, limit: int = 250, offset: int = 0) -> pd.DataFrame:
    _mapping, c = _base_aliases()
    where, params = _where(filters)
    params.update({"limit": int(limit), "offset": int(offset)})
    order = f"{c['data']} DESC NULLS LAST, " if "data" in c else ""
    order += f"{c['temporada']} DESC, {c['rodada']} DESC"
    sql = f"""
        SELECT h.*,
               ABS({c['gols_casa']} - {c['gols_fora']}) AS "Saldo de Gols",
               CASE
                   WHEN {c['gols_casa']} > {c['gols_fora']} THEN {c['mandante']}::text
                   WHEN {c['gols_fora']} > {c['gols_casa']} THEN {c['visitante']}::text
                   ELSE 'Empate'
               END AS "Vencedor"
        FROM {_table_ref()} h
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    with history_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
