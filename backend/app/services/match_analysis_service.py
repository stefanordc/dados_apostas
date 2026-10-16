"""Comparador histórico de dois clubes, sem consulta à tabela de odds.

As estimativas são heurísticas descritivas com decaimento temporal. Não constituem
probabilidades calibradas; EV é condicional à qualidade dessas estimativas.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timedelta
from math import log, exp, factorial
from functools import lru_cache
import time
from sqlalchemy import text
from ..config import settings
from ..db import history_connection

TABLE = f'{settings.history_schema}.{settings.history_table}'
# Mercados disponíveis no Scanner e Lay, para o EV do confronto.
MARKET_GROUPS = [
    ('mo_ft', 'Match Odds FT', [('home_win','Vitória da casa'),('draw','Empate'),('away_win','Vitória do visitante')]),
    ('mo_ht', 'Match Odds HT', [('home_ht','Casa HT'),('draw_ht','Empate HT'),('away_ht','Visitante HT')]),
    ('over_ht', 'Over HT', [(f'over_{i}_5_ht',f'Over {i},5 HT') for i in range(3)]),
    ('under_ht', 'Under HT', [(f'under_{i}_5_ht',f'Under {i},5 HT') for i in range(3)]),
    ('over_ft', 'Over FT', [(f'over_{i}_5_ft',f'Over {i},5 FT') for i in range(5)]),
    ('under_ft', 'Under FT', [(f'under_{i}_5_ft',f'Under {i},5 FT') for i in range(5)]),
    ('btts', 'Ambos Marcam', [('btts','Ambos marcam — Sim'),('btts_no','Ambos marcam — Não')]),
    ('double_chance', 'Dupla Chance', [('dc_1x','Casa ou empate (1X)'),('dc_12','Casa ou visitante (12)'),('dc_x2','Empate ou visitante (X2)')]),
    ('correct_score', 'Placar Exato', [(f'cs_{h}_{a}',f'{h} × {a}') for h in range(4) for a in range(4)]),
    ('big', 'Goleadas', [('big_home','Goleada da casa (vence e marca 4+)'),('big_away','Goleada do visitante (vence e marca 4+)')]),
    ('lay', 'Lay', [('lay_home','Lay casa'),('lay_away','Lay visitante'),
                   ('lay_big_home','Lay goleada da casa'),('lay_big_away','Lay goleada do visitante')]),
]
MARKET_BY_KEY = {key:(label,group) for group, _title, items in MARKET_GROUPS for key,label in items}
LAY_KEYS = {'lay_home','lay_away','lay_big_home','lay_big_away'}
HT_KEYS = {'home_ht','draw_ht','away_ht'} | {f'{side}_{i}_5_ht' for side in ('over','under') for i in range(3)}
EVENTS = tuple(key for _group,_name,items in MARKET_GROUPS for key,_label in items)
LABELS = {key: label for _group,_name,items in MARKET_GROUPS for key,label in items}


def _half_score(game):
    # Se o histórico não registra a hora de todos os gols, não presume 0x0 no HT.
    from .market_scanner_service import _ht_minutes
    h = _ht_minutes(game.get('minutos_gols_casa'), int(game['gh']))
    a = _ht_minutes(game.get('minutos_gols_fora'), int(game['ga']))
    if h is None or a is None or h > int(game['gh']) or a > int(game['ga']):
        return None
    return h,a


def _poisson(k: int, lam: float) -> float:
    return exp(-lam) * lam**k / factorial(k)


def _fair_odd(p: float | None, is_lay: bool = False):
    if p is None or not 0 <= p <= 1:
        return None
    if is_lay:
        return round(1 / (1-p), 2) if p < 1 else None
    return round(1/p, 2) if p > 0 else None


def _where(country=None, competition=None):
    filters = ['data IS NOT NULL', 'data <= CURRENT_DATE',
               'gols_casa IS NOT NULL', 'gols_fora IS NOT NULL']
    params={}
    if country:
        filters.append('pais=:country');params['country']=country
    if competition:
        filters.append('campeonato=:competition');params['competition']=competition
    return ' AND '.join(filters),params


@lru_cache(maxsize=20)
def _teams(country,competition,bucket):
    where, params=_where(country,competition)
    with history_connection() as conn:
        rows=conn.execute(text(f"""SELECT DISTINCT clube FROM (
            SELECT casa AS clube FROM {TABLE} WHERE {where}
            UNION SELECT fora AS clube FROM {TABLE} WHERE {where}
            ) t WHERE NULLIF(BTRIM(clube::text),'') IS NOT NULL ORDER BY clube"""),params)
        return tuple(row[0] for row in rows)


def choices(country=None,competition=None):
    from .league_catalog_service import catalog
    meta=catalog()  # catálogo compacto com cache de 3 minutos
    filtered=[r for r in meta if (not country or r['country']==country)
              and (not competition or r['competition']==competition)]
    # Não lista milhares de clubes até o usuário selecionar um recorte.
    teams=list(_teams(country,competition,int(time.time()//300))) if country or competition else []
    return {'countries':sorted({r['country'] for r in meta}),
            'competitions':sorted({r['competition'] for r in meta if not country or r['country']==country}),
            'teams':teams}


@lru_cache(maxsize=4)
def _goal_minute_columns(bucket):
    with history_connection() as conn:
        names={row[0] for row in conn.execute(text("""SELECT column_name FROM information_schema.columns
              WHERE table_schema=:schema AND table_name=:table
                AND column_name IN ('minutos_gols_casa','minutos_gols_fora')"""),
              {'schema':settings.history_schema,'table':settings.history_table}).all()}
    return names


def _fetch(country, competition, home, away):
    if not home or not away or home == away:
        raise ValueError('Selecione mandante e visitante diferentes.')
    where, p = _where(country,competition)
    names=_goal_minute_columns(int(time.time()//300))
    h_minutes = 'minutos_gols_casa' if 'minutos_gols_casa' in names else 'NULL::text'
    a_minutes = 'minutos_gols_fora' if 'minutos_gols_fora' in names else 'NULL::text'
    cols = f'data, temporada, pais, campeonato, casa, fora, gols_casa AS gh, gols_fora AS ga, {h_minutes} AS minutos_gols_casa, {a_minutes} AS minutos_gols_fora'
    sql = text(f'''SELECT {cols}
        FROM {TABLE} WHERE {where} AND (casa=:team OR fora=:team)
        ORDER BY data DESC, casa, fora LIMIT 350''')
    with history_connection() as conn:
        a=[dict(r) for r in conn.execute(sql,{**p,'team':home}).mappings()]
        b=[dict(r) for r in conn.execute(sql,{**p,'team':away}).mappings()]
        head=[dict(r) for r in conn.execute(text(f'''SELECT {cols} FROM {TABLE}
                  WHERE {where} AND ((casa=:home AND fora=:away) OR (casa=:away AND fora=:home))
                  ORDER BY data DESC LIMIT 1000'''),{**p,'home':home,'away':away}).mappings()]
    return sorted(a,key=lambda g:g['data'],reverse=True),sorted(b,key=lambda g:g['data'],reverse=True),head


def _event(g, team):
    is_home=g['casa']==team
    gf=int(g['gh'] if is_home else g['ga']);ga=int(g['ga'] if is_home else g['gh'])
    return gf,ga,is_home


def metrics(games, team):
    n=len(games)
    if not n:
        return {'games':0,'wins':0,'draws':0,'losses':0,'goals_for':0,'goals_against':0,
                'clean_sheets':0,'no_goals':0,'avg_for':None,'avg_against':None,
                'over05':0,'over15':0,'over25':0,'btts':0,
                'common_score':'—','scored_4plus':0,'conceded_4plus':0}
    scored=conceded=win=draw=clean=no_goals=over05=over15=over25=btts=big_for=big_against=0
    scores=Counter()
    for g in games:
        gf,ga,_=_event(g,team)
        scored+=gf;conceded+=ga
        win+=gf>ga;draw+=gf==ga;clean+=ga==0;no_goals+=gf==0
        over05+=gf+ga>=1;over15+=gf+ga>=2;over25+=gf+ga>=3;btts+=gf>0 and ga>0
        big_for+=gf>=4;big_against+=ga>=4;scores[(gf,ga)]+=1
    return {'games':n,'wins':win,'draws':draw,'losses':n-win-draw,
            'goals_for':scored,'goals_against':conceded,'clean_sheets':clean,
            'no_goals':no_goals,'avg_for':round(scored/n,2),'avg_against':round(conceded/n,2),
            'over05':round(100*over05/n,2),'over15':round(100*over15/n,2),
            'over25':round(100*over25/n,2),'btts':round(100*btts/n,2),
            'common_score':f'{scores.most_common(1)[0][0][0]} × {scores.most_common(1)[0][0][1]}',
            'scored_4plus':big_for,'conceded_4plus':big_against}


def _as_date(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    return date.fromisoformat(str(value)[:10])


def _contexts(games, h2h, team):
    latest_season = str(games[0]['temporada']) if games else ''
    threshold=date.today()-timedelta(days=365*3)
    return {
        'h2h_5':metrics(h2h[:5],team),'h2h_10':metrics(h2h[:10],team),
        'h2h_all':metrics(h2h,team),'last_5':metrics(games[:5],team),
        'last_10':metrics(games[:10],team),'last_20':metrics(games[:20],team),
        'current_season':metrics([g for g in games if str(g['temporada'])==latest_season],team),
        'last_3y':metrics([g for g in games if _as_date(g['data'])>=threshold],team),
    }


def _decay(g, rank):
    days=max(0,(date.today()-_as_date(g['data'])).days)
    return 0.5**(days/365) * (1.35 if rank<5 else 1.0)


def _weighted(games,fn,prior,prior_n=7):
    values=[(_decay(g,i),float(fn(g))) for i,g in enumerate(games[:60])]
    total=sum(w for w,v in values)
    return (sum(w*v for w,v in values)+prior_n*prior)/(total+prior_n),total


def _predictions(home_games,away_games,h2h,home,away):
    home_venue=[g for g in home_games if g['casa']==home]
    away_venue=[g for g in away_games if g['fora']==away]
    # Reorienta H2H para o mandante solicitado, inclusive os jogos invertidos.
    directed=[{**g,
               'gh':int(g['gh']) if g['casa']==home else int(g['ga']),
               'ga':int(g['ga']) if g['casa']==home else int(g['gh']),
               'minutos_gols_casa':g.get('minutos_gols_casa') if g['casa']==home else g.get('minutos_gols_fora'),
               'minutos_gols_fora':g.get('minutos_gols_fora') if g['casa']==home else g.get('minutos_gols_casa')}
              for g in h2h]
    base={'home_win':.44,'draw':.27,'away_win':.29,'over05':.90,'over15':.73,
          'over25':.51,'btts':.51,'big_home':.025,'big_away':.020}
    probs={}

    def estimate(fn, prior, only_half=False):
        pools=(home_venue,away_venue,directed)
        if only_half:
            # Dados de gols por minuto precisam cobrir também jogos COM gols.
            # Caso contrário, somente 0x0 FT seriam classificados como 0x0 HT.
            venue_rows = home_venue[:60] + away_venue[:60]
            known_venue = sum(_half_score(g) is not None for g in venue_rows)
            if known_venue < 12 or (venue_rows and known_venue / len(venue_rows) < .60):
                return None
            pools=tuple([g for g in games if _half_score(g) is not None] for games in pools)
        vals=[]
        for index,games in enumerate(pools):
            val,_=_weighted(games,fn,prior,prior_n=10 if index==2 else 7)
            vals.append(val)
        return .425*vals[0] + .425*vals[1] + .15*vals[2]

    for key in ('home_win','draw','away_win'):
        probs[key]=estimate(lambda g, key=key: (g['gh']==g['ga'] if key=='draw' else
                     g['gh']>g['ga'] if key=='home_win' else g['ga']>g['gh']),base[key])
    # 1X2 deve somar exatamente 1 (antes do arredondamento).
    factor=sum(probs[k] for k in ('home_win','draw','away_win'))
    for k in ('home_win','draw','away_win'):
        probs[k]/=factor

    for key in ('over05','over15','over25','btts','big_home','big_away'):
        def event(g,key=key):
            gh,ga=int(g['gh']),int(g['ga'])
            if key=='over05':return gh+ga>=1
            if key=='over15':return gh+ga>=2
            if key=='over25':return gh+ga>=3
            if key=='btts':return gh>0 and ga>0
            if key=='big_home':return gh>ga and gh>=4
            return ga>gh and ga>=4
        probs[key]=estimate(event,base[key])
    probs['over05']=max(probs['over05'],probs['over15'],probs['over25'])
    probs['over15']=max(probs['over15'],probs['over25'])

    for i in range(5):
        key=f'over_{i}_5_ft'
        probs[key]=(probs['over05'] if i==0 else probs['over15'] if i==1 else probs['over25']
                    if i==2 else estimate(lambda g,i=i: int(g['gh'])+int(g['ga'])>i,
                                           (0.30 if i==3 else 0.15)))
        probs[f'under_{i}_5_ft']=1-probs[key]
    # Correção de monotonicidade também para as linhas 3,5 e 4,5.
    for i in range(1,5):
        probs[f'over_{i}_5_ft']=min(probs[f'over_{i-1}_5_ft'],probs[f'over_{i}_5_ft'])
        probs[f'under_{i}_5_ft']=1-probs[f'over_{i}_5_ft']

    probs['btts_no']=1-probs['btts']
    probs['dc_1x']=1-probs['away_win']
    probs['dc_12']=1-probs['draw']
    probs['dc_x2']=1-probs['home_win']
    probs['lay_home']=1-probs['home_win']
    probs['lay_away']=1-probs['away_win']
    probs['lay_big_home']=1-probs['big_home']
    probs['lay_big_away']=1-probs['big_away']

    # Estimações para placares exatos usam frequência ponderada e um prior
    # Poisson, em vez de dividir o histórico entre 16 resultados arbitrários.
    avg_home=estimate(lambda g: int(g['gh']),1.40)
    avg_away=estimate(lambda g: int(g['ga']),1.10)
    lam_h=max(.35,min(3.0,avg_home));lam_a=max(.35,min(3.0,avg_away))
    for gh in range(4):
        for ga in range(4):
            key=f'cs_{gh}_{ga}'
            prior=_poisson(gh,lam_h)*_poisson(ga,lam_a)
            probs[key]=estimate(lambda g,gh=gh,ga=ga:int(g['gh'])==gh and int(g['ga'])==ga,prior)

    # Primeiro tempo: minutos verificados; ausência significa indisponível.
    ht_totals={}
    for key, prior in [('home_ht',.32),('draw_ht',.41),('away_ht',.27)]:
        def ht_result(g,key=key):
            h,a=_half_score(g)
            return h>a if key=='home_ht' else h==a if key=='draw_ht' else h<a
        ht_totals[key]=estimate(ht_result,prior,only_half=True)
    if all(v is not None for v in ht_totals.values()):
        total=sum(ht_totals.values())
        ht_totals={k:v/total for k,v in ht_totals.items()}
    probs.update(ht_totals)
    for i,prior in enumerate((.68,.32,.11)):
        v=estimate(lambda g,i=i:sum(_half_score(g))>i,prior,only_half=True)
        probs[f'over_{i}_5_ht']=v
    for i in range(1,3):
        if probs[f'over_{i}_5_ht'] is not None:
            probs[f'over_{i}_5_ht']=min(probs[f'over_{i-1}_5_ht'],probs[f'over_{i}_5_ht'])
    for i in range(3):
        v=probs[f'over_{i}_5_ht']
        probs[f'under_{i}_5_ht']=(1-v) if v is not None else None

    # Goleadas Back e Lay são contratos opostos. Lay usa responsabilidade fixa.
    # Exclusivamente os mercados negociáveis estão no catálogo.
    details=[]
    for key in EVENTS:
        p=probs.get(key)
        lay=key in LAY_KEYS
        details.append({'key':key,'label':LABELS[key],
                        'group': MARKET_BY_KEY[key][1],
                        'kind':'lay' if lay else 'back',
                        'probability':round(p*100,2) if p is not None else None,
                        'fair_odd':_fair_odd(p,lay)})
    return details,{'home_venue_games':len(home_venue[:60]),
                    'away_venue_games':len(away_venue[:60]),
                    'h2h_games':len(h2h[:60]),'half_life_days':365,
                    'max_games_per_side':60,
                    'ht_games':sum(_half_score(g) is not None for g in home_venue[:60])+sum(_half_score(g) is not None for g in away_venue[:60])}


def analyze(country,competition,home,away):
    a,b,h2h=_fetch(country,competition,home,away)
    if not a or not b:raise ValueError('Não foram encontrados jogos finalizados para os dois clubes no recorte.')
    predictions,method=_predictions(a,b,h2h,home,away)
    return {'home':home,'away':away,'country':country,'competition':competition,
            'contexts':[{'key':k,'label':lab,'home':_contexts(a,h2h,home)[k],
                         'away':_contexts(b,h2h,away)[k]}
                        for k,lab in [('h2h_5','Confronto direto · últimos 5'),
                                      ('h2h_10','Confronto direto · últimos 10'),
                                      ('h2h_all','Confronto direto · histórico'),
                                      ('last_5','Últimos 5 jogos'),('last_10','Últimos 10 jogos'),
                                      ('last_20','Últimos 20 jogos'),('current_season','Temporada atual'),
                                      ('last_3y','Últimos 3 anos')]],
            'probabilities':predictions,'method':method,
            'sample':{'home_total':len(a),'away_total':len(b),'h2h_total':len(h2h)}}


def expected_value(probability:float,odds:float,kind:str='back'):
    if not 1.01<=odds<=1000:
        raise ValueError('Informe uma odd decimal entre 1,01 e 1.000.')
    if kind not in ('back','lay'):
        raise ValueError('Tipo de mercado inválido.')
    p=probability/100
    ev=100*(p/(odds-1)-(1-p)) if kind=='lay' else 100*(p*odds-1)
    return {'market_probability':round(probability,2),'odd':round(odds,2),
            'fair_odd':_fair_odd(p,kind=='lay'),
            'ev_percent':round(ev,2),'expected_return_per_100':round(ev,2),
            'positive_value':ev>0,'note':'EV estimado com probabilidades heurísticas, não calibradas. Não garante retorno.'}
