"""Catálogo da aba Liga derivado do histórico efetivo, não dos cadastros ELO.

País e campeonato são identificados pela dupla de nomes registrada em
historico_jogos; entradas sem cadastro auxiliar também são consideradas.
Os IDs do catálogo de Liga são efêmeros e NÃO são IDs da tabela campeonatos.
"""
from __future__ import annotations

import time
from functools import lru_cache
from sqlalchemy import text
from ..config import settings
from ..db import history_connection, app_engine
from .elo_service import normalize_name
from .continent_service import for_country, CONTINENTS


@lru_cache(maxsize=3)
def _catalog_cached(bucket: int) -> tuple[dict, ...]:
    with history_connection() as conn:
        columns = {row[0] for row in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=:schema AND table_name=:table
        """), {"schema":settings.history_schema, "table":settings.history_table}).all()}
        continent_expr = "BTRIM(continente::text)" if "continente" in columns else "NULL::text"
        source = conn.execute(text(f"""
            SELECT DISTINCT BTRIM(pais::text) AS country,
                            BTRIM(campeonato::text) AS competition,
                            MAX({continent_expr}) AS continent
            FROM {settings.history_schema}.{settings.history_table}
            WHERE NULLIF(BTRIM(pais::text), '') IS NOT NULL
              AND NULLIF(BTRIM(campeonato::text), '') IS NOT NULL
            GROUP BY BTRIM(pais::text), BTRIM(campeonato::text)
            ORDER BY country, competition
        """)).mappings().all()
    registered: dict[tuple[str, str], int] = {}
    try:
        with app_engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT c.id, p.nome AS country, c.nome AS competition
                FROM {settings.app_schema}.campeonatos c
                JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
            """)).mappings()
            registered = {
                (normalize_name(str(r['country'])), normalize_name(str(r['competition']))): int(r['id'])
                for r in rows
            }
    except Exception:
        # A consulta SEM ODDS não deve depender da disponibilidade do catálogo ELO.
        registered = {}
    result = []
    for index, row in enumerate(source, 1):
        country, competition = str(row['country']).strip(), str(row['competition']).strip()
        result.append({
            'id': index,
            'country': country,
            'continent': for_country(country, row.get('continent')),
            'competition': competition,
            'app_competition_id': registered.get((normalize_name(country), normalize_name(competition))),
        })
    return tuple(result)


def catalog() -> list[dict]:
    return [dict(row) for row in _catalog_cached(int(time.time() // 180))]


def choices() -> dict:
    rows = catalog()
    country_names = sorted({row['country'] for row in rows}, key=str.casefold)
    by_country = {name: index for index, name in enumerate(country_names, 1)}
    return {
        'continents': [{'id': i+1, 'nome': name} for i, name in enumerate(CONTINENTS) if any(r['continent'] == name for r in rows)],
        'countries': [{'id': by_country[name], 'nome': name,
                       'continente': next(r['continent'] for r in rows if r['country'] == name)} for name in country_names],
        'competitions': [
            {'id': row['id'], 'nome': row['competition'], 'pais': row['country'],
             'pais_id': by_country[row['country']], 'continente': row['continent']}
            for row in rows
        ],
        'total': len(rows),
        'source': 'historico_jogos',
    }


def selected(country: str | None = None, competition: str | None = None,
             continent: str | None = None) -> list[dict]:
    rows = catalog()
    if continent and continent not in CONTINENTS:
        raise ValueError('Continente inválido.')
    if country and country not in {r['country'] for r in rows}:
        raise ValueError('País não encontrado em historico_jogos.')
    if competition and not any(r['competition'] == competition and
                               (not country or r['country'] == country) for r in rows):
        raise ValueError('Campeonato não encontrado em historico_jogos para o país selecionado.')
    if continent and country and not any(r['country'] == country and r['continent'] == continent for r in rows):
        raise ValueError('O país selecionado não pertence ao continente informado.')
    return [r for r in rows if (not country or r['country'] == country) and
            (not competition or r['competition'] == competition) and
            (not continent or r['continent'] == continent)]


def clear_cache():
    _catalog_cached.cache_clear()
