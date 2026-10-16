"""Estatísticas por Clube, com elegibilidade independente do recorte.

Sempre lê placares em historico_jogos. No modo ON, obtém cotações
exclusivamente por conciliação aprovada em historico_odds.
O campo country representa pais em historico_jogos (país da competição),
NÃO nacionalidade confirmada do clube.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache
import time

from sqlalchemy import text
from ..config import settings
from ..db import history_connection, app_engine
from .elo_service import normalize_name
from .continent_service import CONTINENTS, allowed_countries
from .backtesting_service import MARKETS, MARKET_BY_KEY, _summary, _base_games, _odds_bounds, STAKE


@lru_cache(maxsize=2)
def _registered_countries(bucket: int) -> dict[str, str]:
    """Usa país oficial apenas quando o nome é inequívoco no catálogo de clubes.

    Clubes homônimos de países diferentes nunca recebem país arbitrário.
    """
    records=defaultdict(set)
    try:
        with app_engine.connect() as conn:
            rows=conn.execute(text(f"""
                SELECT c.nome AS club, p.nome AS country
                FROM {settings.app_schema}.clubes c
                JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
            """)).mappings()
            for r in rows:
                records[normalize_name(str(r['club']))].add(str(r['country']))
    except Exception:
        return {}
    return {name:next(iter(countries)) for name,countries in records.items() if len(countries)==1}


def _country_label(club: str, competition_country: str):
    registered=_registered_countries(int(time.time()//600)).get(normalize_name(club))
    return (registered,'país cadastrado do clube') if registered else (competition_country,'país/região do campeonato (histórico)')


def _where(country=None, competition=None, club=None, start_year=None, end_year=None):
    clauses = ['data IS NOT NULL', 'data <= CURRENT_DATE',
               'gols_casa IS NOT NULL', 'gols_fora IS NOT NULL']
    params = {}
    if country:
        clauses.append('pais = :country'); params['country'] = country
    if competition:
        clauses.append('campeonato = :competition'); params['competition'] = competition
    if club:
        clauses.append('(casa = :club OR fora = :club)'); params['club'] = club
    if start_year is not None:
        clauses.append('data >= CAST(:year_start AS DATE)'); params['year_start'] = f'{start_year:04d}-01-01'
    if end_year is not None:
        clauses.append('data < CAST(:year_end AS DATE)'); params['year_end'] = f'{end_year+1:04d}-01-01'
    return ' AND '.join(clauses), params


@lru_cache(maxsize=3)
def _eligible(bucket: int) -> dict[tuple[str, str], dict]:
    """Regra global: >500 partidas OU >=100 nos últimos 3 anos corridos.

    Caches curtos evitam escanear o histórico inteiro a cada clique/mercado.
    Conta cada jogo uma vez por clube, inclusive mandante/visitante.
    """
    where, params = _where()
    sql = text(f"""
        WITH appearances AS (
          SELECT BTRIM(pais::text) country, BTRIM(casa::text) club, data
          FROM {settings.history_schema}.{settings.history_table}
          WHERE {where} AND NULLIF(BTRIM(casa::text),'') IS NOT NULL
          UNION ALL
          SELECT BTRIM(pais::text) country, BTRIM(fora::text) club, data
          FROM {settings.history_schema}.{settings.history_table}
          WHERE {where} AND NULLIF(BTRIM(fora::text),'') IS NOT NULL
        )
        SELECT country, club, COUNT(*)::bigint AS all_games,
          COUNT(*) FILTER (WHERE data >= CURRENT_DATE - INTERVAL '3 years')::bigint AS recent_games
        FROM appearances GROUP BY country, club
        HAVING COUNT(*) > 500
          OR COUNT(*) FILTER (WHERE data >= CURRENT_DATE - INTERVAL '3 years') >= 100
    """)
    with history_connection() as conn:
        rows = conn.execute(sql, params).mappings()
        return {(str(r['country']),str(r['club'])): {
            'all_games':int(r['all_games']), 'recent_games':int(r['recent_games'])
        } for r in rows}


def eligible():
    return _eligible(int(time.time()//600))


def candidates(country=None, competition=None, q=None, limit=120, continent=None) -> dict:
    # O autocomplete não deve aguardar a contagem global de todos os clubes.
    from .league_catalog_service import selected
    chosen = selected(country, competition, continent) if continent else None
    allowed = {c["country"] for c in chosen} if chosen is not None else None
    # Com uma busca digitada, agrega só os nomes correspondentes no próprio banco.
    if q and q.strip() and app_engine is not None:
        return _fast_candidates(country, competition, q.strip(), limit, allowed)
    qualify = eligible()
    names = sorted({club for c, club in qualify if (not country or country == c) and (allowed is None or c in allowed)}, key=str.casefold)
    if q:
        names = [name for name in names if q.casefold() in name.casefold()]
    # If competition selected, use just matching participating clubs from it.
    if competition:
        where, params = _where(country, competition)
        with history_connection() as conn:
            rows = conn.execute(text(f"""
                SELECT DISTINCT BTRIM(pais::text) country, BTRIM(casa::text) club
                FROM {settings.history_schema}.{settings.history_table} WHERE {where}
                UNION SELECT DISTINCT BTRIM(pais::text), BTRIM(fora::text)
                FROM {settings.history_schema}.{settings.history_table} WHERE {where}
            """),params).all()
        in_comp={club for c, club in rows if (c,club) in qualify}
        names=[name for name in names if name in in_comp]
    return {'clubs':names[:max(1,min(500,limit))], 'eligible_count':len(names),
            'eligibility_rule':'Mais de 500 jogos no histórico OU pelo menos 100 jogos nos últimos 3 anos.'}



def _fast_candidates(country=None, competition=None, q=None, limit=120, allowed=None):
    params={'term':f'%{q}%'}
    criteria=['data IS NOT NULL','data<=CURRENT_DATE',
              'gols_casa IS NOT NULL','gols_fora IS NOT NULL',
              '(BTRIM(casa::text) ILIKE :term OR BTRIM(fora::text) ILIKE :term)']
    if allowed is not None:
        criteria.append('BTRIM(pais::text) = ANY(:allowed)')
        params['allowed'] = list(allowed)
    if country:
        criteria.append('BTRIM(pais::text)=:country')
        params['country']=country
    if competition:
        params['competition']=competition
    comp_filter='BOOL_OR(competition=:competition)' if competition else 'TRUE'
    sql=text(f"""
      WITH matches AS MATERIALIZED (
        SELECT BTRIM(pais::text) country,BTRIM(campeonato::text) competition,
               BTRIM(casa::text) home,BTRIM(fora::text) away,data
        FROM {settings.history_schema}.{settings.history_table}
        WHERE {' AND '.join(criteria)}
      ), appearance AS (
        SELECT country,competition,home AS club,data FROM matches
          WHERE home ILIKE :term AND NULLIF(home,'') IS NOT NULL
        UNION ALL
        SELECT country,competition,away AS club,data FROM matches
          WHERE away ILIKE :term AND NULLIF(away,'') IS NOT NULL
      )
      SELECT country,club FROM appearance GROUP BY country,club
      HAVING (COUNT(*)>500 OR COUNT(*) FILTER
              (WHERE data>=CURRENT_DATE-INTERVAL '3 years')>=100)
         AND {comp_filter}
      ORDER BY club,country
    """)
    with history_connection() as conn:
        rows=list(conn.execute(sql,params).mappings())
    names=sorted({str(r['club']) for r in rows},key=str.casefold)
    return {'clubs':names[:max(1,min(500,limit))], 'eligible_count':len(names),
            'eligibility_rule':'Mais de 500 jogos no histórico OU pelo menos 100 jogos nos últimos 3 anos.'}


def _grouped_without_odds(country=None, competition=None, club=None, year_from=None, year_to=None):
    """Uma consulta agrupada para milhares de clubes e todos os mercados.

    Mantém o ano-calendário na dimensão para permitir o drill de 10 anos.
    """
    where, params = _where(country, competition, club, year_from, year_to)
    source = f'{settings.history_schema}.{settings.history_table}'
    sql = text(f"""
      WITH appearances AS (
        SELECT BTRIM(pais::text) country, BTRIM(casa::text) club,
          'home'::text AS venue, EXTRACT(YEAR FROM data)::integer AS year,
          gols_casa::integer gh,gols_fora::integer ga
        FROM {source} WHERE {where}
        UNION ALL
        SELECT BTRIM(pais::text) country, BTRIM(fora::text) club,
          'away'::text AS venue, EXTRACT(YEAR FROM data)::integer AS year,
          gols_casa::integer gh,gols_fora::integer ga
        FROM {source} WHERE {where}
      )
      SELECT country,club,venue,year,gh,ga,COUNT(*)::bigint AS weight
      FROM appearances WHERE NULLIF(club,'') IS NOT NULL
      GROUP BY country,club,venue,year,gh,ga
    """)
    with history_connection() as conn:
        return [dict(row) for row in conn.execute(sql,params).mappings()]


def _odds_games(country=None, competition=None, year_from=None, year_to=None, continent=None):
    """Usa o conciliador existente; não substitui odds Lay por odds Back."""
    from .league_catalog_service import selected
    from .league_bulk_odds_service import load
    catalog=selected(country,competition,continent)
    return load(country,competition,catalog,year_from=year_from,year_to=year_to)[0]


def _market_rows(country=None,competition=None,club=None,year_from=None,year_to=None,use_odds=False,continent=None):
    qualification=eligible()
    if not use_odds:
        groups=defaultdict(list)
        for r in _grouped_without_odds(country,competition,club,year_from,year_to):
            key=(str(r['country']),str(r['club']))
            if key not in qualification: continue
            year=int(r['year']); venue=str(r['venue']); name=key[1]
            groups[key].append({
                'year':year,'date':f'{year}-01-01','home':name if venue=='home' else '',
                'away':name if venue=='away' else '', 'gh':int(r['gh']), 'ga':int(r['ga']),
                '_weight':int(r['weight']), 'home_odd':None,'away_odd':None,
                'draw_odd':None,'over25_odd':None,
            })
        return groups
    groups=defaultdict(list)
    source = (_odds_games(country,competition,year_from,year_to,continent=continent)
              if continent else _odds_games(country,competition,year_from,year_to))
    for game in source:
        for side in ('home','away'):
            key=(str(game.get('country') or ''),str(game.get(side) or ''))
            if key not in qualification or (club and key[1]!=club): continue
            groups[key].append(game)
    return groups


# Uma única agregação em PostgreSQL substitui a leitura de centenas de milhares
# de combinações (clube, ano, placar, mando) no Python. A elegibilidade é global:
# país + clube, independente dos filtros de campeonato e de período.
_MARKET_CONDITIONS = {
    'back_home': ("venue='home'", 'gh>ga'),
    'lay_home': ("venue='home'", 'gh<=ga'),
    'draw': ('TRUE', 'gh=ga'),
    'back_away': ("venue='away'", 'ga>gh'),
    'lay_away': ("venue='away'", 'ga<=gh'),
    'over05': ('TRUE', 'gh+ga>=1'),
    'over15': ('TRUE', 'gh+ga>=2'),
    'over25': ('TRUE', 'gh+ga>=3'),
    'under35': ('TRUE', 'gh+ga<=3'),
    'btts': ('TRUE', 'gh>0 AND ga>0'),
    'lay_big_home': ("venue='home'", 'NOT (gh>ga AND gh>=4)'),
    'lay_big_away': ("venue='away'", 'NOT (ga>gh AND ga>=4)'),
}


def _fast_ranking_sql(country=None, competition=None, club=None,
                      year_from=None, year_to=None, allowed=None):
    params = {}
    conditions = ['data IS NOT NULL', 'data<=CURRENT_DATE',
                  'gols_casa IS NOT NULL', 'gols_fora IS NOT NULL']
    if allowed is not None:
        conditions.append('BTRIM(pais::text) = ANY(:continent_countries)')
        params['continent_countries'] = list(allowed)
    if country:
        conditions.append('BTRIM(pais::text)=:country')
        params['country'] = country
    if club:
        conditions.append('(BTRIM(casa::text)=:club OR BTRIM(fora::text)=:club)')
        params['club'] = club
    period = []
    if competition:
        period.append('competition=:competition')
        params['competition'] = competition
    if year_from is not None:
        period.append('data>=CAST(:year_from AS DATE)')
        params['year_from'] = f'{int(year_from):04d}-01-01'
    if year_to is not None:
        period.append('data<CAST(:year_to AS DATE)')
        params['year_to'] = f'{int(year_to)+1:04d}-01-01'
    chosen = ' AND '.join(period) or 'TRUE'
    scores = []
    for market, (applicable, success) in _MARKET_CONDITIONS.items():
        scores.append(f'COUNT(*) FILTER (WHERE selected AND ({applicable}))::bigint AS {market}_games')
        scores.append(f'COUNT(*) FILTER (WHERE selected AND ({applicable}) AND ({success}))::bigint AS {market}_wins')
    sql = f"""
      WITH valid_games AS MATERIALIZED (
        SELECT BTRIM(pais::text) AS country, BTRIM(campeonato::text) AS competition,
               BTRIM(casa::text) AS home, BTRIM(fora::text) AS away,
               data, gols_casa::integer AS gh, gols_fora::integer AS ga
        FROM {settings.history_schema}.{settings.history_table}
        WHERE {' AND '.join(conditions)}
      ),
      appearances AS (
        SELECT country,competition,data,home AS club,'home'::text AS venue,gh,ga
        FROM valid_games WHERE NULLIF(home,'') IS NOT NULL
        UNION ALL
        SELECT country,competition,data,away AS club,'away'::text AS venue,gh,ga
        FROM valid_games WHERE NULLIF(away,'') IS NOT NULL
      ),
      selected_games AS (
        SELECT country,club,venue,gh,ga,data,({chosen}) AS selected
        FROM appearances
      )
      SELECT country,club, COUNT(*)::bigint AS all_games,
          COUNT(*) FILTER (WHERE data>=CURRENT_DATE-INTERVAL '3 years')::bigint AS recent_games,
          {','.join(scores)}
      FROM selected_games
      GROUP BY country,club
      HAVING COUNT(*)>500 OR COUNT(*) FILTER (WHERE data>=CURRENT_DATE-INTERVAL '3 years')>=100
    """
    return text(sql), params


def _fast_ranking_without_odds(country=None, competition=None, club=None,
                               year_from=None, year_to=None, allowed=None):
    sql, params = _fast_ranking_sql(country, competition, club, year_from, year_to, allowed)
    with history_connection() as conn:
        aggregates = [dict(r) for r in conn.execute(sql, params).mappings()]
    registered = _registered_countries(int(time.time()//600))
    results = {key: {'market': key, 'label': label, 'kind': kind, 'items': []}
               for key,label,kind in MARKETS}
    eligible_in_sample = 0
    for agg in aggregates:
        club_name, club_country = str(agg['club']), str(agg['country'])
        if not any(int(agg[f'{key}_games']) for key,_,_ in MARKETS):
            continue
        eligible_in_sample += 1
        official = registered.get(normalize_name(club_name))
        label_country = official or club_country
        label_type = 'país cadastrado do clube' if official else 'país/região do campeonato (histórico)'
        for key, _label, _kind in MARKETS:
            games, wins = int(agg[f'{key}_games']), int(agg[f'{key}_wins'])
            if not games:
                continue
            results[key]['items'].append({
                'club':club_name, 'country':club_country,
                'club_country':label_country, 'country_type':label_type,
                'games':games,'wins':wins,'losses':games-wins,
                'win_rate':round(wins*100/games,2),
                'settled':0,'profit':None,'roi':None,
                'all_games':int(agg['all_games']), 'recent_games':int(agg['recent_games']),
            })
    for group in results.values():
        group['items'].sort(key=lambda row:(-row['win_rate'], -row['games'],
                                            row['club'].casefold(),row['country'].casefold()))
    return {'markets':results,'eligible_count':eligible_in_sample,
            'use_odds':False,'source':'historico_jogos',
            'criterion':'Mais de 500 jogos no histórico OU pelo menos 100 jogos nos últimos 3 anos. Elegibilidade global, antes dos filtros.',
            'country_note':'Prioriza o país cadastrado em clubes. Se indisponível ou ambíguo, usa pais do histórico, identificado como país/região do campeonato.'}


@lru_cache(maxsize=5)
def _cached_fast_ranking_without_odds(country, competition, club, year_from, year_to, bucket, allowed=None):
    # Evita reler o histórico em filtros repetidos ou após trocar de aba.
    return _fast_ranking_without_odds(country, competition, club, year_from, year_to, allowed)

def _club_eligibility(country: str, club: str) -> bool:
    # Checagem pontual do drilldown. Evita reconstruir o ranking global.
    query=text(f"""
      SELECT COUNT(*)::bigint AS all_games,
             COUNT(*) FILTER (WHERE data>=CURRENT_DATE-INTERVAL '3 years')::bigint AS recent_games
      FROM {settings.history_schema}.{settings.history_table}
      WHERE pais=:country AND (casa=:club OR fora=:club)
        AND data IS NOT NULL AND data<=CURRENT_DATE
        AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
    """)
    with history_connection() as conn:
        row=conn.execute(query, {'country':country, 'club':club}).mappings().first()
    return bool(row and (int(row['all_games'])>500 or int(row['recent_games'])>=100))

def ranking(payload:dict) -> dict:
    country=str(payload.get('country') or '').strip() or None
    competition=str(payload.get('competition') or '').strip() or None
    continent=str(payload.get('continent') or '').strip() or None
    if continent and continent not in CONTINENTS: raise ValueError('Continente inválido.')
    club=str(payload.get('club') or '').strip() or None
    year_from=payload.get('year_from'); year_to=payload.get('year_to')
    use_odds=payload.get('use_odds',False)
    if not isinstance(use_odds,bool):raise ValueError('Fonte inválida.')
    if year_from and year_to and year_from>year_to:raise ValueError('Ano de não pode superar Ano até.')
    from .league_catalog_service import selected
    comps = selected(country, competition, continent) if (country or competition or continent) else None
    allowed = tuple(sorted({r['country'] for r in comps})) if continent else None
    if not use_odds and app_engine is not None:
        return _cached_fast_ranking_without_odds(country,competition,club,year_from,year_to,int(time.time()//180),allowed)
    filters=_odds_bounds(payload) if use_odds else {}
    groups=(_market_rows(country,competition,club,year_from,year_to,use_odds,continent=continent)
            if continent and use_odds else _market_rows(country,competition,club,year_from,year_to,use_odds))
    if allowed is not None:
        groups = {k:v for k,v in groups.items() if k[0] in allowed}
    result={}
    for market,label,kind in MARKETS:
        items=[]
        for (club_country,club_name),games in groups.items():
            # market evaluation requires the actual club to distinguish venue
            summary=_summary(games,market,club_name,'any',filters)
            if summary['games']==0:continue
            settled=summary['settled']; profit=summary['profit']
            display_country, country_type=_country_label(club_name,club_country)
            items.append({'club':club_name,'country':club_country,
                'club_country':display_country, 'country_type':country_type,
                'games':summary['games'],'wins':summary['wins'],'losses':summary['losses'],
                'win_rate':summary['rate'],'settled':settled,'profit':profit,
                'roi':round(profit*100/(settled*STAKE),2) if profit is not None and settled else None,
                **eligible()[(club_country,club_name)]})
        items.sort(key=lambda r:(-(r['win_rate'] if r['win_rate'] is not None else -1),-r['games'],r['club'].casefold(),r['country'].casefold()))
        result[market]={'market':market,'label':label,'kind':kind,'items':items}
    return {'markets':result,'eligible_count':len(groups),'use_odds':use_odds,
            'source':'historico_odds' if use_odds else 'historico_jogos',
            'criterion':'Mais de 500 jogos no histórico OU pelo menos 100 nos últimos 3 anos. Elegibilidade global, antes dos filtros.',
            'country_note':'Prioriza o país cadastrado em clubes. Se indisponível ou ambíguo, usa pais do histórico, identificado como país/região do campeonato.'}


def history(payload:dict) -> dict:
    market=str(payload.get('market') or '')
    if market not in MARKET_BY_KEY:raise ValueError('Mercado inválido.')
    country=str(payload.get('country') or '').strip()
    club=str(payload.get('club') or '').strip()
    if not country or not club:raise ValueError('Informe o país do histórico e o clube.')
    continent=str(payload.get('continent') or '').strip() or None
    if continent:
        from .league_catalog_service import selected
        selected(country, None, continent)
    if not (_club_eligibility(country,club) if app_engine is not None else (country,club) in eligible()):
        raise ValueError('Clube fora do critério mínimo de jogos.')
    use_odds=payload.get('use_odds',False)
    if not isinstance(use_odds,bool):raise ValueError('Fonte inválida.')
    end=date.today().year; start=end-9
    competition=str(payload.get('competition') or '').strip() or None
    filters=_odds_bounds(payload) if use_odds else {}
    if not use_odds and app_engine is not None:
        groups=defaultdict(list)
        for r in _grouped_without_odds(country,competition,club,start,end):
            key=(str(r['country']),str(r['club']))
            if key != (country,club):
                continue
            year=int(r['year']); venue=str(r['venue'])
            groups[key].append({
                'year':year,'date':f'{year}-01-01',
                'home':club if venue=='home' else '',
                'away':club if venue=='away' else '',
                'gh':int(r['gh']),'ga':int(r['ga']), '_weight':int(r['weight']),
                'home_odd':None,'away_odd':None,'draw_odd':None,'over25_odd':None
            })
    else:
        groups=_market_rows(country,competition,club,start,end,use_odds)
    summary=_summary(groups.get((country,club),[]),market,club,'any',filters)
    years=[]
    for year in range(start,end+1):
        row=summary['years'].get(str(year),{})
        n=int(row.get('games') or 0); wins=int(row.get('wins') or 0)
        settled=int(row.get('settled') or 0);profit=row.get('profit')
        years.append({'year':year,'games':n,'wins':wins,'losses':n-wins,
            'win_rate':round(wins*100/n,2) if n else None,
            'settled':settled,'profit':profit if use_odds else None,
            'roi':round(profit*100/(settled*STAKE),2) if profit is not None and settled and use_odds else None})
    display_country,country_type=_country_label(club,country)
    return {'club':club,'country':country,'club_country':display_country,'country_type':country_type,
            'market':market,'market_label':MARKET_BY_KEY[market][0],
            'year_from':start,'year_to':end,'years':years,
            'total':{'games':summary['games'],'wins':summary['wins'],
                     'losses':summary['losses'],'win_rate':summary['rate']},
            'use_odds':use_odds}
