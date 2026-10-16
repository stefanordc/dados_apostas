"""Consultas em lote para a aba Liga (sem passar por cada campeonato).

A análise SEM ODDS recebe somente agregados de placares por liga/temporada/mês.
Todas as leituras são somente leitura. Acesso a historico_odds é proibido aqui.
"""
from __future__ import annotations

import time
from functools import lru_cache
from sqlalchemy import text

from ..config import settings
from ..db import history_connection


def _columns(conn) -> set[str]:
    return {row[0] for row in conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema=:schema AND table_name=:table
    """), {'schema': settings.history_schema, 'table': settings.history_table}).all()}


def _scope(country: str | None, competition: str | None, season: str | None,
           division: str | None, format_: str | None, cols: set[str],
           year_from: int | None = None, year_to: int | None = None,
           continent_countries: tuple[str, ...] | None = None):
    clauses = ["data IS NOT NULL", "data <= CURRENT_DATE", "gols_casa IS NOT NULL", "gols_fora IS NOT NULL"]
    params = {}
    if year_from is not None:
        clauses.append('data >= CAST(:year_start AS DATE)')
        params['year_start'] = f'{year_from:04d}-01-01'
    if year_to is not None:
        clauses.append('data < CAST(:year_end_exclusive AS DATE)')
        params['year_end_exclusive'] = f'{year_to + 1:04d}-01-01'
    if continent_countries is not None:
        clauses.append('pais = ANY(:continent_countries)')
        params['continent_countries'] = list(continent_countries)
    if country:
        clauses.append('pais=:country')
        params['country'] = country
    if competition:
        clauses.append('campeonato=:competition')
        params['competition'] = competition
    # O ano da temporada pode estar em formato YYYY/YY; filtramos após normalizar.
    if division:
        clauses.append('BTRIM(divisao::text)=:divisao' if 'divisao' in cols else 'false')
        params['divisao'] = division
    if format_:
        clauses.append('BTRIM(formato::text)=:formato' if 'formato' in cols else 'false')
        params['formato'] = format_
    return ' AND '.join(clauses), params


@lru_cache(maxsize=12)
def _aggregated(country: str | None, competition: str | None,
                division: str | None, format_: str | None, bucket: int,
                year_from: int | None = None, year_to: int | None = None,
                continent_countries: tuple[str, ...] | None = None) -> tuple[dict, ...]:
    with history_connection() as conn:
        columns = _columns(conn)
        where, params = _scope(country, competition, None, division, format_, columns, year_from, year_to, continent_countries)
        div_expr = "NULLIF(BTRIM(divisao::text),'')" if 'divisao' in columns else 'NULL::text'
        fmt_expr = "NULLIF(BTRIM(formato::text),'')" if 'formato' in columns else 'NULL::text'
        # Apenas 1 SELECT para todos os países/ligas. Agrupa gols e mês para
        # calcular todos os mercados, correct score e séries anuais posteriormente.
        query = text(f"""
            SELECT pais AS country, campeonato AS competition,
                temporada::text AS season,
                date_trunc('month', data)::date AS month,
                {div_expr} AS divisao, {fmt_expr} AS formato,
                gols_casa::integer AS gh, gols_fora::integer AS ga,
                count(*)::integer AS weight
            FROM {settings.history_schema}.{settings.history_table}
            WHERE {where}
            GROUP BY pais, campeonato, temporada::text,
                date_trunc('month',data)::date, {div_expr}, {fmt_expr},
                gols_casa, gols_fora
        """)
        return tuple(dict(row) for row in conn.execute(query, params).mappings())


@lru_cache(maxsize=32)
def _option_rows(country: str | None, competition: str | None, bucket: int,
                 continent_countries: tuple[str, ...] | None = None) -> tuple[dict, ...]:
    with history_connection() as conn:
        columns = _columns(conn)
        where, params = _scope(country, competition, None, None, None, columns, continent_countries=continent_countries)
        div_expr = "NULLIF(BTRIM(divisao::text),'')" if 'divisao' in columns else 'NULL::text'
        fmt_expr = "NULLIF(BTRIM(formato::text),'')" if 'formato' in columns else 'NULL::text'
        # Nem clubs nem odds nem reconciliação. Dimensões diretamente do histórico.
        rows = conn.execute(text(f"""
            SELECT DISTINCT temporada::text AS season, {div_expr} AS divisao,
                            {fmt_expr} AS formato
            FROM {settings.history_schema}.{settings.history_table}
            WHERE {where}
        """), params).mappings()
        return tuple(dict(row) for row in rows)


def options(country: str | None = None, competition: str | None = None,
            continent_countries: tuple[str, ...] | None = None) -> dict:
    from .backtesting_service import _display_season, _season_key
    rows = _option_rows(country, competition, int(time.time() // 180), continent_countries)
    seasons = sorted({_display_season(r['season']) for r in rows if r['season']}, key=_season_key, reverse=True)
    pairs = {(str(r['divisao'] or '').strip(), str(r['formato'] or '').strip()) for r in rows}
    pairs.discard(('', ''))
    ordered = sorted(pairs, key=lambda r: (r[0].casefold(), r[1].casefold()))
    return {
        'seasons': seasons,
        'divisions': sorted({d for d,f in ordered if d},key=str.casefold),
        'formats': sorted({f for d,f in ordered if f},key=str.casefold),
        'division_formats': [{'divisao': d, 'formato':f} for d,f in ordered],
    }


def grouped_games(country: str | None, competition: str | None,
                  season: str, division: str | None, format_: str | None,
                  catalog: list[dict], year_from: int | None = None,
                  year_to: int | None = None,
                  continent_countries: tuple[str, ...] | None = None) -> list[dict]:
    from .backtesting_service import _display_season, _season_key
    comp_lookup = {(c['country'], c['competition']): int(c['id']) for c in catalog}
    bucket = int(time.time() // 180)
    if continent_countries is not None:
        rows = _aggregated(country, competition, division, format_, bucket,
                           year_from, year_to, continent_countries)
    elif year_from is not None or year_to is not None:
        rows = _aggregated(country, competition, division, format_, bucket, year_from, year_to)
    else:
        rows = _aggregated(country, competition, division, format_, bucket)
    games=[]
    for r in rows:
        key=(r['country'],r['competition'])
        if key not in comp_lookup:
            continue
        display = _display_season(r['season'])
        if season not in ('', 'all') and display != season:
            continue
        month = str(r['month'])[:7]
        games.append({
            'date':f'{month}-01', 'year':int(month[:4]), 'month': month,
            'season':display, 'season_key':_season_key(display),
            'competition_id':comp_lookup[key], 'competition':key[1], 'country':key[0],
            'divisao':r['divisao'], 'formato':r['formato'],
            'gh':int(r['gh']), 'ga':int(r['ga']), '_weight':int(r['weight']),
            'home':'','away':'',
            'home_odd':None,'away_odd':None,'draw_odd':None,'over25_odd':None,
            'odds_source':None,
        })
    return games


def clear_cache():
    _option_rows.cache_clear()
    _aggregated.cache_clear()


def recent_games(country: str | None, competition: str | None, season: str,
                 division: str | None, format_: str | None, catalog: list[dict],
                 limit: int = 160, year_from: int | None = None,
                 year_to: int | None = None) -> list[dict]:
    """Amostra final para a auditoria, com clubes/datas REAIS e sem cotação.

    A consulta é independente da agregação e limitada a 160 partidas.
    """
    from .backtesting_service import _display_season, _season_key
    catalog_names={(c['country'],c['competition']):c for c in catalog}
    with history_connection() as conn:
        cols=_columns(conn)
        where,params=_scope(country,competition,None,division,format_,cols,year_from,year_to)
        if season not in ('','all'):
            year=_season_key(season)[0]
            where+=' AND left(btrim(temporada::text),4)=:first_year'
            params['first_year']=str(year)
        sql=text(f"""
            SELECT data,pais,campeonato,temporada,casa,fora,
                   gols_casa,gols_fora,
                   {'NULLIF(BTRIM(divisao::text),'')' if 'divisao' in cols else 'NULL::text'} AS divisao,
                   {'NULLIF(BTRIM(formato::text),'')' if 'formato' in cols else 'NULL::text'} AS formato
            FROM {settings.history_schema}.{settings.history_table}
            WHERE {where}
            ORDER BY data DESC, id DESC LIMIT :limit
        """)
        params['limit']=max(40,min(500,int(limit)))
        rows=conn.execute(sql,params).mappings()
        sample=[]
        for r in rows:
            comp=catalog_names.get((r['pais'],r['campeonato']))
            if not comp:
                continue
            season_value=_display_season(r['temporada'])
            if season not in ('','all') and season_value!=season:
                continue
            when=str(r['data'])[:10]
            sample.append({
                'date':when,'year':int(when[:4]),'season':season_value,
                'season_key':_season_key(season_value),'home':str(r['casa']),
                'away':str(r['fora']), 'gh':int(r['gols_casa']), 'ga':int(r['gols_fora']),
                'divisao':r['divisao'],'formato':r['formato'],
                'competition_id':comp['id'],'competition':comp['competition'],
                'country':comp['country'], 'home_odd':None,'draw_odd':None,
                'away_odd':None,'over25_odd':None,'odds_source':None,
            })
        return sample
