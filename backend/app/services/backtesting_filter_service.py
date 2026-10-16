"""Consultas leves para os seletores de Backtesting.

Não executa conciliação, leitura de cotações ou cálculo de mercados para
mostrar o próximo filtro. Usa cache curto e uma agregação por competição.
"""
from __future__ import annotations

import time
from functools import lru_cache

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from .clubs_conciliation_service import load_mappings
from .elo_service import normalize_name


def _clean(items):
    return [str(v).strip() for v in (items or []) if v is not None and str(v).strip()]


def _historical_options(country: str, competition: str):
    """Uma agregação retorna somente nomes/temporadas/dimensões distintas."""
    with history_connection() as conn:
        cols = {r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=:schema AND table_name=:table
        """), {'schema':settings.history_schema,'table':settings.history_table}).all()}
        div = "NULLIF(BTRIM(divisao::text), '')" if 'divisao' in cols else 'NULL::text'
        fmt = "NULLIF(BTRIM(formato::text), '')" if 'formato' in cols else 'NULL::text'
        result = conn.execute(text(f"""
            SELECT
                array_agg(DISTINCT NULLIF(BTRIM(temporada::text), '')) AS seasons,
                array_agg(DISTINCT NULLIF(BTRIM(casa::text), '')) AS homes,
                array_agg(DISTINCT NULLIF(BTRIM(fora::text), '')) AS aways,
                array_agg(DISTINCT ({div})) AS divisions,
                array_agg(DISTINCT ({fmt})) AS formats,
                array_agg(DISTINCT concat_ws(chr(31), coalesce({div}, ''), coalesce({fmt}, ''))) AS pairs
            FROM {settings.history_schema}.{settings.history_table}
            WHERE pais=:country AND campeonato=:competition
              AND data IS NOT NULL AND data <= CURRENT_DATE
              AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
        """), {'country': country, 'competition':competition}).mappings().one()
    return dict(result)


def _odds_dimensions(country: str, competition: str) -> list[tuple[str, str]]:
    """Busca apenas divisão/formato distintos das odds, nunca partidas/odds."""
    for connect in (app_engine.connect, history_connection):
        with connect() as conn:
            names = {row[0] for row in conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name='historico_odds'
                  AND column_name IN ('pais','campeonato','divisao','formato')
            """)).all()}
            if not {'pais','campeonato'}.issubset(names):
                continue
            div = "BTRIM(divisao::text)" if 'divisao' in names else "''::text"
            fmt = "BTRIM(formato::text)" if 'formato' in names else "''::text"
            rows = list(conn.execute(text(f"""
                SELECT DISTINCT {div} AS divisao, {fmt} AS formato
                FROM public.historico_odds
                WHERE lower(btrim(pais::text)) = lower(btrim(:country))
                  AND lower(btrim(campeonato::text)) = lower(btrim(:competition))
            """), {'country':country,'competition':competition}).mappings())
            if rows:
                return [(str(r['divisao'] or '').strip(),str(r['formato'] or '').strip()) for r in rows]
            # Fallback dos históricos com acentuação diferente no campeonato.
            # Retorna apenas pares distintos de dimensões, nunca linhas de odds.
            other_names = conn.execute(text(f"""
                SELECT DISTINCT campeonato::text AS nome, {div} AS divisao, {fmt} AS formato
                FROM public.historico_odds
                WHERE lower(btrim(pais::text)) = lower(btrim(:country))
            """), {'country':country}).mappings()
            matched = [(str(r['divisao'] or '').strip(),str(r['formato'] or '').strip())
                       for r in other_names if normalize_name(r['nome']) == normalize_name(competition)]
            if matched:
                return matched
    return []


def _pairs(raw: dict) -> set[tuple[str, str]]:
    result = set()
    for item in raw.get('pairs') or []:
        div, _, fmt = str(item or '').partition(chr(31))
        if div or fmt:
            result.add((div.strip(),fmt.strip()))
    return result


@lru_cache(maxsize=96)
def _cached(competition_id: int, use_odds: bool, time_bucket: int) -> dict:
    # Catálogo do aplicativo pode viver em outra conexão.
    with app_engine.connect() as conn:
        meta = conn.execute(text(f"""
            SELECT c.nome AS competition, p.nome AS country
            FROM {settings.app_schema}.campeonatos c
            JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
            WHERE c.id=:id
        """), {'id':competition_id}).mappings().first()
    if meta is None:
        raise ValueError('Campeonato não encontrado.')
    raw = _historical_options(meta['country'],meta['competition'])
    from .backtesting_service import _display_season, _season_key
    seasons = sorted({_display_season(s) for s in _clean(raw.get('seasons'))},key=_season_key,reverse=True)
    names = set(_clean(raw.get('homes')) + _clean(raw.get('aways')))
    # Nomes aprovados devem aparecer iguais nos filtros e nos resultados.
    decisions = load_mappings(competition_id)
    clubs = sorted({decisions.get(normalize_name(n),n) for n in names},key=str.casefold)
    pairs = _pairs(raw)
    if use_odds:
        pairs.update(_odds_dimensions(meta['country'],meta['competition']))
    pairs.discard(('', ''))
    ordered = sorted(pairs,key=lambda x:(x[0].casefold(),x[1].casefold()))
    return {
        'clubs': clubs,
        'seasons': seasons,
        'divisions': sorted({d for d,f in ordered if d},key=str.casefold),
        'formats': sorted({f for d,f in ordered if f},key=str.casefold),
        'division_formats': [{'divisao':d,'formato':f} for d,f in ordered],
        # A conciliação é consultada separadamente, apenas quando necessária.
        'odds_reconciliation': None,
    }


def options(competition_id:int, use_odds:bool=True) -> dict:
    return _cached(competition_id,use_odds,int(time.time()//120))


@lru_cache(maxsize=64)
def _league_cached(country_id: int | None, competition_id: int | None,
                   use_odds: bool, time_bucket: int) -> dict:
    from .backtesting_service import _competition_catalog
    from .league_fast_service import options as fast_options
    metas = _competition_catalog(country_id=country_id, competition_id=competition_id)
    country_name = next((r['country'] for r in metas if r['country_id'] == country_id), None) if country_id else None
    comp_name = metas[0]['competition'] if competition_id and metas else None
    result = fast_options(country_name, comp_name)
    if not use_odds:
        return result
    # Consulta UMA vez os pares de dimensões da tabela de odds; não faz N
    # queries, uma por campeonato, nem usa o conciliador para listas.
    from .league_bulk_odds_service import distinct_odds_dimensions
    pairs = {(p['divisao'],p['formato']) for p in result['division_formats']}
    pairs.update(distinct_odds_dimensions(country_name, comp_name))
    pairs.discard(('', ''))
    ordered = sorted(pairs,key=lambda x:(x[0].casefold(),x[1].casefold()))
    result = dict(result)
    result['divisions'] = sorted({d for d,f in ordered if d},key=str.casefold)
    result['formats'] = sorted({f for d,f in ordered if f},key=str.casefold)
    result['division_formats'] = [{'divisao':d,'formato':f} for d,f in ordered]
    return result


@lru_cache(maxsize=64)
def _league_history_cached(country: str | None, competition: str | None,
                           use_odds: bool, bucket: int,
                           continent: str | None = None) -> dict:
    from .league_catalog_service import selected
    catalog = selected(country, competition, continent)  # Verifica o recorte contra o histórico.
    from .league_fast_service import options as fast_options
    result = (fast_options(country, competition, tuple(sorted({r['country'] for r in catalog})))
              if continent else fast_options(country, competition))
    if not use_odds:
        return result
    from .league_bulk_odds_service import distinct_odds_dimensions
    pairs = {(p['divisao'], p['formato']) for p in result['division_formats']}
    pairs.update(distinct_odds_dimensions(country, competition))
    pairs.discard(('', ''))
    ordered = sorted(pairs, key=lambda pair: (pair[0].casefold(), pair[1].casefold()))
    return {
        **result,
        'divisions': sorted({d for d, f in ordered if d}, key=str.casefold),
        'formats': sorted({f for d, f in ordered if f}, key=str.casefold),
        'division_formats': [{'divisao': d, 'formato': f} for d, f in ordered],
    }


def league_options(country_id: int | None = None, competition_id: int | None = None,
                   use_odds: bool = True, league_country: str | None = None,
                   league_competition: str | None = None,
                   league_continent: str | None = None) -> dict:
    if league_country or league_competition or league_continent or (country_id is None and competition_id is None):
        return _league_history_cached(league_country, league_competition, use_odds, int(time.time()//180), league_continent)
    return _league_cached(country_id, competition_id, use_odds, int(time.time()//180))


def clear_cache():
    _cached.cache_clear()
    _league_cached.cache_clear()
    _league_history_cached.cache_clear()
    from .league_fast_service import clear_cache as clear_fast
    clear_fast()
    from .league_bulk_odds_service import clear_cache as clear_bulk
    clear_bulk()
