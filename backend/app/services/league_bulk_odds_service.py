"""Conciliação em lote da aba Liga (sem executar _source para cada liga).

A origem de gols é sempre historico_jogos. Os preços vêm exclusivamente de
historico_odds. Divergências de clubes exigem aliases aprovados previamente.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import time

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from ..services.historico_odds_service import (
    ODD_COLUMNS, LAY_OPTIONAL_COLUMNS, OPTIONAL_DIMENSIONS, QUOTE_MAP,
    REQUIRED, reconcile, _table_exists, season_code,
)
from ..services.elo_service import normalize_name


def _available_odds_table():
    for label, opener in (('principal',app_engine.connect), ('historico',history_connection)):
        with opener() as conn:
            if not _table_exists(conn):
                continue
            cols={row[0] for row in conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name='historico_odds'
            """)).all()}
            if not REQUIRED.issubset(cols):
                raise ValueError('historico_odds não contém todas as colunas obrigatórias.')
            return label, cols
    raise ValueError('Tabela historico_odds não encontrada.')


@lru_cache(maxsize=32)
def distinct_odds_dimensions(country: str | None, competition: str | None):
    try:
        label, cols = _available_odds_table()
    except ValueError:
        return tuple()
    expr_div = "NULLIF(BTRIM(divisao::text),'')" if 'divisao' in cols else 'NULL::text'
    expr_fmt = "NULLIF(BTRIM(formato::text),'')" if 'formato' in cols else 'NULL::text'
    clauses=[]; params={}
    if country:
        clauses.append('lower(btrim(pais::text))=lower(btrim(:country))');params['country']=country
    if competition:
        clauses.append('lower(btrim(campeonato::text))=lower(btrim(:competition))');params['competition']=competition
    where=' WHERE '+ ' AND '.join(clauses) if clauses else ''
    opener=app_engine.connect if label=='principal' else history_connection
    with opener() as conn:
        rows=conn.execute(text(f"""SELECT DISTINCT {expr_div} AS divisao, {expr_fmt} AS formato
            FROM public.historico_odds {where}"""),params).mappings()
        return tuple((str(r['divisao'] or '').strip(),str(r['formato'] or '').strip()) for r in rows)


def _load_rows(country: str | None, competition: str | None, catalog: list[dict],
               year_from: int | None = None, year_to: int | None = None) -> tuple[list[dict], list[dict], dict]:
    from .backtesting_service import _display_season, _season_key
    catalog_names={(normalize_name(c['country']),normalize_name(c['competition'])):c for c in catalog}
    catalog_countries = sorted({str(c['country']) for c in catalog})
    with history_connection() as conn:
        cols={r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=:schema AND table_name=:table
        """), {'schema':settings.history_schema,'table':settings.history_table}).all()}
        dims=', '+', '.join(f'{name}::text AS {name}' for name in ('divisao','formato') if name in cols) if {'divisao','formato'}&cols else ''
        wheres=['data IS NOT NULL','data<=CURRENT_DATE','gols_casa IS NOT NULL','gols_fora IS NOT NULL']
        params={}
        if country:
            wheres.append('pais=:country');params['country']=country
        elif catalog_countries:
            wheres.append('pais = ANY(:catalog_countries)');params['catalog_countries']=catalog_countries
        if competition:
            wheres.append('campeonato=:competition');params['competition']=competition
        if year_from is not None:
            wheres.append('data >= CAST(:year_start AS DATE)');params['year_start']=f'{year_from:04d}-01-01'
        if year_to is not None:
            wheres.append('data < CAST(:year_end_exclusive AS DATE)');params['year_end_exclusive']=f'{year_to + 1:04d}-01-01'
        rows=conn.execute(text(f"""
            SELECT data,pais,campeonato,temporada,casa,fora,gols_casa,gols_fora{dims}
            FROM {settings.history_schema}.{settings.history_table}
            WHERE {' AND '.join(wheres)}
        """),params).mappings()
        games=[]
        for r in rows:
            comp=catalog_names.get((normalize_name(r['pais']),normalize_name(r['campeonato'])))
            if not comp:
                continue
            when=str(r['data'])[:10]
            gh=int(r['gols_casa']);ga=int(r['gols_fora'])
            season=_display_season(r['temporada'])
            game={
                'date':when,'year':int(when[:4]),'season':season,'season_key':_season_key(season),
                'home':str(r['casa']),'away':str(r['fora']),'gh':gh,'ga':ga,
                'competition_id':int(comp['id']),'competition':comp['competition'],'country':comp['country'],
                'divisao':str(r.get('divisao') or '').strip() or None,
                'formato':str(r.get('formato') or '').strip() or None,
                'history_divisao':str(r.get('divisao') or '').strip() or None,
                'history_formato':str(r.get('formato') or '').strip() or None,
                'odds_source':None,
                **{field:None for field in QUOTE_MAP.values()},
            }
            games.append(game)
    label, cols=_available_odds_table()
    expressions=[]
    for col in list(ODD_COLUMNS)+list(LAY_OPTIONAL_COLUMNS)+list(OPTIONAL_DIMENSIONS):
        if col in cols:
            expressions.append(col)
        elif col in ODD_COLUMNS or col in LAY_OPTIONAL_COLUMNS:
            expressions.append(f'NULL::numeric AS {col}')
        else:
            expressions.append(f'NULL::text AS {col}')
    wheres=[];params={}
    if country:
        wheres.append('lower(btrim(pais::text))=lower(btrim(:country))');params['country']=country
    if competition:
        wheres.append('lower(btrim(campeonato::text))=lower(btrim(:competition))');params['competition']=competition
    if year_from is not None:
        wheres.append('data >= CAST(:year_start AS DATE)');params['year_start']=f'{year_from:04d}-01-01'
    if year_to is not None:
        wheres.append('data < CAST(:year_end_exclusive AS DATE)');params['year_end_exclusive']=f'{year_to + 1:04d}-01-01'
    where=' WHERE '+' AND '.join(wheres) if wheres else ''
    opener=app_engine.connect if label=='principal' else history_connection
    with opener() as conn:
        odds=[dict(r) for r in conn.execute(text(f"""
            SELECT data,pais,campeonato,temporada,casa,fora,{','.join(expressions)}
            FROM public.historico_odds {where}
        """),params).mappings()]
    return games,odds,{'database':label, 'status':'ok','odds_rows':len(odds)}


@lru_cache(maxsize=3)
def _cached(country: str | None, competition: str | None,
            catalog_signature: tuple[tuple[int, str, str, int | None], ...], bucket: int,
            year_from: int | None = None, year_to: int | None = None):
    catalog=[{'id':cid,'country':country_name,'competition':competition_name,
              'app_competition_id':app_id}
             for cid,country_name,competition_name,app_id in catalog_signature]
    games,odds,meta=(_load_rows(country,competition,catalog,year_from,year_to)
                     if year_from is not None or year_to is not None
                     else _load_rows(country,competition,catalog))
    groups=defaultdict(list)
    for game in games:
        groups[game['competition_id']].append(game)
    lookup={(normalize_name(c['country']),normalize_name(c['competition'])):int(c['id']) for c in catalog}
    odds_groups=defaultdict(list)
    for o in odds:
        cid=lookup.get((normalize_name(o['pais']),normalize_name(o['campeonato'])))
        if cid:
            odds_groups[cid].append(o)
    # Decisões por campeonato, carregadas de uma vez do banco principal.
    decisions=defaultdict(dict)
    app_to_league = {int(c['app_competition_id']): int(c['id']) for c in catalog
                     if c.get('app_competition_id') is not None}
    # Compatibilidade com catálogos anteriores, cujos IDs já eram do aplicativo.
    if not app_to_league and catalog and not any('app_competition_id' in c for c in catalog):
        app_to_league = {int(c['id']): int(c['id']) for c in catalog}
    if app_to_league:
        with app_engine.connect() as conn:
            for r in conn.execute(text(f"""SELECT campeonato_id,nome_normalizado,nome_padrao
                    FROM {settings.app_schema}.clubes_conciliacao
                    WHERE campeonato_id = ANY(:ids)"""),{'ids':list(app_to_league)}).mappings():
                decisions[app_to_league[int(r['campeonato_id'])]][r['nome_normalizado']]=r['nome_padrao']
    diagnostics={'status':meta['status'],'database':meta['database'],
                 'odds_rows':meta['odds_rows'],'matched_games':0,'ambiguous_games':0,
                 'unmatched_games':0,'legacy_only_games':0,'without_any_odds':0,
                 'games_total':len(games)}
    for cid,group in groups.items():
        info=reconcile(group,odds_groups.get(cid,[]),{},decisions.get(cid,{}))
        for key in ('matched_games','ambiguous_games','unmatched_games'):
            diagnostics[key]+=int(info[key])
    games=[{**g,**(g.get('historico_odds_quotes') or {})} for g in games
           if g.get('odds_source')=='historico_odds']
    return tuple(games), diagnostics


def load(country: str | None, competition: str | None, catalog: list[dict],
         year_from: int | None = None, year_to: int | None = None):
    signature=tuple(sorted((int(c['id']),str(c['country']),str(c['competition']),
                            int(c['app_competition_id']) if c.get('app_competition_id') is not None else
                            (int(c['id']) if 'app_competition_id' not in c else None))
                           for c in catalog))
    games,diag=_cached(country, competition, signature, int(time.time()//180), year_from, year_to)
    return [dict(game) for game in games],dict(diag)


def clear_cache():
    _cached.cache_clear()
    distinct_odds_dimensions.cache_clear()
