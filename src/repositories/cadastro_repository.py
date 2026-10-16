from __future__ import annotations

from decimal import Decimal

import pandas as pd
from sqlalchemy import text

from src.db import app_engine


def _rows(query: str, params: dict | None = None) -> list[dict]:
    with app_engine().connect() as conn:
        result = conn.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]


def list_countries() -> list[dict]:
    return _rows(
        "SELECT id, nome, continente FROM backtest_apostas.paises ORDER BY continente, nome"
    )


def get_country_by_name(name: str) -> dict | None:
    rows = _rows(
        "SELECT id, nome, continente FROM backtest_apostas.paises WHERE LOWER(nome)=LOWER(:nome) LIMIT 1",
        {"nome": name.strip()},
    )
    return rows[0] if rows else None


def create_country(name: str, continent: str) -> int:
    name = name.strip()
    existing = get_country_by_name(name)
    if existing:
        return int(existing["id"])
    with app_engine().begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO backtest_apostas.paises (nome, continente) VALUES (:nome, :continente) RETURNING id"
                ),
                {"nome": name, "continente": continent},
            ).scalar_one()
        )


def list_championships(country_id: int | None = None) -> list[dict]:
    sql = """
        SELECT c.id, c.nome, c.pais_id, p.nome AS pais
        FROM backtest_apostas.campeonatos c
        JOIN backtest_apostas.paises p ON p.id=c.pais_id
        WHERE c.ativo=TRUE
    """
    params: dict = {}
    if country_id is not None:
        sql += " AND c.pais_id=:pais_id"
        params["pais_id"] = country_id
    sql += " ORDER BY p.nome, c.nome"
    return _rows(sql, params)


def get_or_create_championship(country_id: int, name: str) -> int:
    name = name.strip()
    with app_engine().begin() as conn:
        found = conn.execute(
            text(
                "SELECT id FROM backtest_apostas.campeonatos "
                "WHERE pais_id=:pais_id AND LOWER(nome)=LOWER(:nome) LIMIT 1"
            ),
            {"pais_id": country_id, "nome": name},
        ).scalar_one_or_none()
        if found is not None:
            return int(found)
        return int(
            conn.execute(
                text(
                    "INSERT INTO backtest_apostas.campeonatos (pais_id, nome) "
                    "VALUES (:pais_id, :nome) RETURNING id"
                ),
                {"pais_id": country_id, "nome": name},
            ).scalar_one()
        )


def list_clubs(
    country_id: int | None = None,
    championship_id: int | None = None,
    season: str | None = None,
) -> list[dict]:
    sql = """
        SELECT DISTINCT cl.id, cl.nome, cl.pais_id, p.nome AS pais
        FROM backtest_apostas.clubes cl
        JOIN backtest_apostas.paises p ON p.id=cl.pais_id
    """
    params: dict = {}
    if championship_id is not None or season:
        sql += " LEFT JOIN backtest_apostas.clubes_campeonatos cc ON cc.clube_id=cl.id "
    sql += " WHERE cl.ativo=TRUE "
    if country_id is not None:
        sql += " AND cl.pais_id=:pais_id"
        params["pais_id"] = country_id
    if championship_id is not None:
        sql += " AND cc.campeonato_id=:campeonato_id"
        params["campeonato_id"] = championship_id
    if season:
        sql += " AND cc.temporada=:temporada"
        params["temporada"] = season
    sql += " ORDER BY cl.nome"
    return _rows(sql, params)


def get_or_create_club(country_id: int, name: str) -> int:
    name = name.strip()
    with app_engine().begin() as conn:
        found = conn.execute(
            text(
                "SELECT id FROM backtest_apostas.clubes "
                "WHERE pais_id=:pais_id AND LOWER(nome)=LOWER(:nome) LIMIT 1"
            ),
            {"pais_id": country_id, "nome": name},
        ).scalar_one_or_none()
        if found is not None:
            return int(found)
        return int(
            conn.execute(
                text(
                    "INSERT INTO backtest_apostas.clubes (pais_id, nome) "
                    "VALUES (:pais_id, :nome) RETURNING id"
                ),
                {"pais_id": country_id, "nome": name},
            ).scalar_one()
        )


def link_club_to_championship(club_id: int, championship_id: int, season: str) -> None:
    with app_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO backtest_apostas.clubes_campeonatos (clube_id, campeonato_id, temporada) "
                "VALUES (:clube_id, :campeonato_id, :temporada) "
                "ON CONFLICT (clube_id, campeonato_id, temporada) DO NOTHING"
            ),
            {"clube_id": club_id, "campeonato_id": championship_id, "temporada": season},
        )


def save_market_value(
    *,
    season: str,
    country_id: int,
    championship_id: int,
    club_id: int,
    currency: str,
    value: Decimal,
) -> None:
    link_club_to_championship(club_id, championship_id, season)
    with app_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO backtest_apostas.valores_mercado
                    (temporada, pais_id, campeonato_id, clube_id, moeda, valor)
                VALUES
                    (:temporada, :pais_id, :campeonato_id, :clube_id, :moeda, :valor)
                ON CONFLICT (temporada, campeonato_id, clube_id)
                DO UPDATE SET
                    pais_id=EXCLUDED.pais_id,
                    moeda=EXCLUDED.moeda,
                    valor=EXCLUDED.valor,
                    atualizado_em=NOW()
                """
            ),
            {
                "temporada": season,
                "pais_id": country_id,
                "campeonato_id": championship_id,
                "clube_id": club_id,
                "moeda": currency,
                "valor": value,
            },
        )


def market_values_dataframe(limit: int = 300) -> pd.DataFrame:
    query = text(
        """
        SELECT vm.temporada AS "Temporada",
               p.nome AS "País",
               c.nome AS "Campeonato",
               cl.nome AS "Clube",
               vm.moeda AS "Moeda",
               vm.valor AS "Valor de mercado",
               vm.atualizado_em AS "Atualizado em"
        FROM backtest_apostas.valores_mercado vm
        JOIN backtest_apostas.paises p ON p.id=vm.pais_id
        JOIN backtest_apostas.campeonatos c ON c.id=vm.campeonato_id
        JOIN backtest_apostas.clubes cl ON cl.id=vm.clube_id
        ORDER BY vm.atualizado_em DESC, vm.temporada DESC, p.nome, c.nome, cl.nome
        LIMIT :limit
        """
    )
    with app_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"limit": limit})


def countries_dataframe() -> pd.DataFrame:
    with app_engine().connect() as conn:
        return pd.read_sql(
            text("SELECT nome AS \"País\", continente AS \"Continente\" FROM backtest_apostas.paises ORDER BY continente, nome"),
            conn,
        )


def championships_dataframe(country_id: int | None = None) -> pd.DataFrame:
    sql = """
        SELECT p.nome AS "País", c.nome AS "Campeonato"
        FROM backtest_apostas.campeonatos c
        JOIN backtest_apostas.paises p ON p.id=c.pais_id
        WHERE c.ativo=TRUE
    """
    params: dict = {}
    if country_id:
        sql += " AND c.pais_id=:pais_id"
        params["pais_id"] = country_id
    sql += " ORDER BY p.nome, c.nome"
    with app_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def clubs_dataframe(country_id: int | None = None) -> pd.DataFrame:
    sql = """
        SELECT p.nome AS "País", cl.nome AS "Clube"
        FROM backtest_apostas.clubes cl
        JOIN backtest_apostas.paises p ON p.id=cl.pais_id
        WHERE cl.ativo=TRUE
    """
    params: dict = {}
    if country_id:
        sql += " AND cl.pais_id=:pais_id"
        params["pais_id"] = country_id
    sql += " ORDER BY p.nome, cl.nome"
    with app_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
