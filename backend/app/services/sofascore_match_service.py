"""Pré-jogo com resultados recentes (`jogos`) e SofaScore (`jogo_completo`).

Uma linha por clube e por jogo na tabela de estatísticas. Nunca une somente por nome.
Estimativas Poisson/heurísticas *não calibradas* e não equivalem a EV comprovado.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from collections import Counter
from math import exp, factorial, isfinite
from statistics import mean
import time
import re

from sqlalchemy import text
from ..config import settings
from ..db import history_connection
from .match_analysis_service import MARKET_GROUPS, LAY_KEYS, LABELS, _fair_odd

JOGOS = f'{settings.history_schema}.jogos'
STATS = f'{settings.history_schema}.jogo_completo'
# Somente atributos existentes no pipeline SofaScore; colunas ausentes tornam-se NULL.
STATS_FIELDS = (
    'xg', 'gols_esperados_no_alvo', 'total_chutes', 'chutes_gol',
    'chutes_dentro_area', 'grandes_chances_criadas', 'grandes_chances_perdidas',
    'posse_bola', 'escanteios', 'passes_certos', 'interceptacoes',
    'recuperacoes_bola', 'defesas_goleiro', 'cortes', 'cartoes_vermelhos',
    'percentual_duelos_vencidos', 'chutes_bloqueados', 'total_desarmes',
    'passes', 'perdas_posse', 'percentual_dribles_certos',
)
MARKET_ITEMS = {k: (group, label) for group, _title, entries in MARKET_GROUPS for k, label in entries}
LAY_ITEMS = LAY_KEYS | {'lay_zebra_1_0'}


def _date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    return date.fromisoformat(str(value)[:10])


def _num(value):
    if value is None or value == '': return None
    if isinstance(value, str):
        value = value.replace('%', '').replace(' ', '').replace(',', '.').strip()
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if isfinite(n) else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@lru_cache(maxsize=8)
def _schema(bucket):
    with history_connection() as conn:
        names = {}
        for table in ('jogos', 'jogo_completo'):
            rows = conn.execute(text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema=:schema AND table_name=:table"""),
                {'schema': settings.history_schema, 'table': table})
            names[table] = {row[0] for row in rows}
    required_games = {'id_jogo','data','pais','campeonato','mandante','visitante',
                      'id_mandante','id_visitante','gols_casa','gols_fora'}
    required_stats = {'id_jogo','id_clube'}
    if not required_games <= names['jogos'] or not required_stats <= names['jogo_completo']:
        raise ValueError('Tabelas jogos/jogo_completo ausentes ou sem colunas-chave; confirme a conexão HISTORY_DATABASE_URL e as colunas id_jogo/id_clube.')
    return names


def _filter(country='', competition=''):
    rules = ['j.data<CURRENT_DATE', 'j.gols_casa IS NOT NULL', 'j.gols_fora IS NOT NULL']
    params = {}
    if country:
        rules.append('j.pais=:country'); params['country'] = country
    if competition:
        rules.append('j.campeonato=:competition'); params['competition'] = competition
    return ' AND '.join(rules), params


@lru_cache(maxsize=25)
def _choice_cache(country, competition, bucket):
    _schema(bucket)
    rules, p = _filter(country, competition)
    with history_connection() as conn:
        nations = [r[0] for r in conn.execute(text(f'''SELECT DISTINCT pais FROM {JOGOS}
                 WHERE pais IS NOT NULL AND BTRIM(pais)<>'' ORDER BY pais'''))]
        championships = [r[0] for r in conn.execute(text(f'''SELECT DISTINCT campeonato FROM {JOGOS} j
                 WHERE {rules} AND campeonato IS NOT NULL AND BTRIM(campeonato)<>'' ORDER BY campeonato'''),p)]
        teams = []
        # Não oferece milhares de clubes em uma lista quando não há recorte.
        if country or competition:
            teams = [r[0] for r in conn.execute(text(f'''SELECT DISTINCT name FROM (
                 SELECT j.mandante name FROM {JOGOS} j WHERE {rules}
                 UNION ALL SELECT j.visitante name FROM {JOGOS} j WHERE {rules}
                 ) t WHERE NULLIF(BTRIM(name),'') IS NOT NULL ORDER BY name'''),p)]
    return {'countries':nations,'competitions':championships,'teams':teams}


def choices(country='', competition=''):
    return _choice_cache(country or '',competition or '',int(time.time()//300))


def _fetch(country, competition, home, away, n):
    if not home or not away or home.casefold() == away.casefold():
        raise ValueError('Selecione mandante e visitante diferentes.')
    schema = _schema(int(time.time()//300))
    columns = schema['jogo_completo']
    stat_columns = ',\n'.join(
        f'{alias}.{field} AS {prefix}_{field}' if field in columns else f'NULL AS {prefix}_{field}'
        for alias, prefix in (('sh','h'),('sa','a')) for field in STATS_FIELDS
    )
    season = 'j.temporada' if 'temporada' in schema['jogos'] else "NULL::text AS temporada"
    rules,p = _filter(country,competition)
    select = f'''SELECT j.id_jogo,j.data,j.pais,j.campeonato,{season}, j.mandante AS casa,
        j.visitante AS fora,j.id_mandante,j.id_visitante,j.gols_casa AS gh,j.gols_fora AS ga,
        {stat_columns}
        FROM {JOGOS} j
        LEFT JOIN {STATS} sh ON sh.id_jogo=j.id_jogo AND sh.id_clube=j.id_mandante
        LEFT JOIN {STATS} sa ON sa.id_jogo=j.id_jogo AND sa.id_clube=j.id_visitante'''
    with history_connection() as conn:
        home_games = [dict(row) for row in conn.execute(text(f'''{select}
             WHERE {rules} AND (j.mandante=:team OR j.visitante=:team)
             ORDER BY j.data DESC, j.id_jogo DESC LIMIT :cap'''), {**p,'team':home,'cap':max(150,n)}).mappings()]
        away_games = [dict(row) for row in conn.execute(text(f'''{select}
             WHERE {rules} AND (j.mandante=:team OR j.visitante=:team)
             ORDER BY j.data DESC, j.id_jogo DESC LIMIT :cap'''), {**p,'team':away,'cap':max(150,n)}).mappings()]
        h2h = [dict(row) for row in conn.execute(text(f'''{select}
             WHERE {rules} AND ((j.mandante=:home AND j.visitante=:away) OR
                                   (j.mandante=:away AND j.visitante=:home))
             ORDER BY j.data DESC, j.id_jogo DESC LIMIT 100'''), {**p,'home':home,'away':away}).mappings()]
    return home_games, away_games, h2h


def _team_side(game, team):
    if game['casa'] == team:
        return 'h','a',int(game['gh']),int(game['ga']),True
    if game['fora'] == team:
        return 'a','h',int(game['ga']),int(game['gh']),False
    raise ValueError('Jogo não pertence ao clube selecionado.')


def _weight(game, rank):
    days = max(0,(date.today()-_date(game['data'])).days)
    return 0.5 ** (days / 240) * (1.25 if rank < 5 else 1.0)


def _mean_weighted(pairs):
    denom = sum(w for v,w in pairs)
    return (sum(v*w for v,w in pairs) / denom) if denom else None


def _profile(games, team, limit):
    rows = games[:limit]
    weighted = {}
    coverage = {}
    fields = list(STATS_FIELDS) + ['goals_for','goals_against','xg_against','shots_against','sot_against','big_against']
    values = {key: [] for key in fields}
    for rank, game in enumerate(rows):
        own, opp, gf, ga, venue = _team_side(game,team)
        w=_weight(game,rank)
        for field in STATS_FIELDS:
            v=_num(game.get(f'{own}_{field}'))
            if v is not None and v >= 0:
                if field=='posse_bola' and v <= 1: v *= 100
                values[field].append((v,w))
        pairs = {'goals_for':gf,'goals_against':ga,
                 'xg_against':_num(game.get(f'{opp}_xg')),
                 'shots_against':_num(game.get(f'{opp}_total_chutes')),
                 'sot_against':_num(game.get(f'{opp}_chutes_gol')),
                 'big_against':_num(game.get(f'{opp}_grandes_chances_criadas'))}
        for field,v in pairs.items():
            if v is not None and v >= 0: values[field].append((v,w))
    for key in fields:
        weighted[key] = _mean_weighted(values[key])
        coverage[key] = len(values[key])
    weighted['games'] = len(rows)
    weighted['coverage'] = coverage
    weighted['home_games'] = sum(game['casa']==team for game in rows)
    weighted['away_games'] = len(rows)-weighted['home_games']
    return weighted


def _venue_profiles(games,team,limit,home):
    venue=[g for g in games if (g['casa']==team)==home]
    # Aplica peso por data e posição na subamostra, não pela posição na amostra mista.
    subset = venue[:limit]
    return _profile(subset,team,limit)


def _combine(target, opp_allowed, goal_fallback, minimum, maximum):
    if target is None and opp_allowed is None:
        return _clamp(goal_fallback,minimum,maximum),False
    xg=(target+opp_allowed)/2 if target is not None and opp_allowed is not None else (target if target is not None else opp_allowed)
    # 75% xG quando disponível, 25% gols reais/defesa recente.
    return _clamp(.75*xg+.25*goal_fallback,minimum,maximum),True


def _modifiers(rate, profile, sample_profiles):
    # Ajustes pequenos: xG continua sendo o principal preditor.
    reference_sot=mean(v for v in (p.get('chutes_gol') for p in sample_profiles) if v is not None) if any(p.get('chutes_gol') is not None for p in sample_profiles) else None
    reference_big=mean(v for v in (p.get('grandes_chances_criadas') for p in sample_profiles) if v is not None) if any(p.get('grandes_chances_criadas') is not None for p in sample_profiles) else None
    factor=1.0
    if reference_sot and profile.get('chutes_gol') is not None and profile['coverage'].get('chutes_gol',0)>=5:
        factor+=.08*_clamp(profile['chutes_gol']/reference_sot-1,-1,1)
    if reference_big and profile.get('grandes_chances_criadas') is not None and profile['coverage'].get('grandes_chances_criadas',0)>=5:
        factor+=.06*_clamp(profile['grandes_chances_criadas']/reference_big-1,-1,1)
    if profile.get('posse_bola') is not None and profile['coverage'].get('posse_bola',0)>=5:
        factor+=.04*_clamp((profile['posse_bola']-50)/15,-1,1)
    return _clamp(rate*factor,.12,4.5)


def _lambdas(h, a, ha, aa):
    goal_home = .5*((h.get('goals_for') or 0)+(aa.get('goals_against') or 0))
    goal_away = .5*((a.get('goals_for') or 0)+(ha.get('goals_against') or 0))
    # Mínimo de cinco jogos completos por métrica para evitar um único xG atípico.
    def reliable(p, field):
        return p.get(field) if p['coverage'].get(field,0) >= 5 else None
    expected_home, hxg = _combine(reliable(h,'xg'), reliable(aa,'xg_against'),goal_home,.12,4.5)
    expected_away, axg = _combine(reliable(a,'xg'), reliable(ha,'xg_against'),goal_away,.12,4.5)
    expected_home=_modifiers(expected_home,h,[h,a])
    expected_away=_modifiers(expected_away,a,[h,a])
    # Com baixa amostragem encolhe para a taxa de gols dos próprios jogos.
    strength_home = min(h['games'],aa['games'])
    strength_away = min(a['games'],ha['games'])
    if strength_home < 5: expected_home=.7*expected_home+.3*_clamp(goal_home,.2,3.5)
    if strength_away < 5: expected_away=.7*expected_away+.3*_clamp(goal_away,.2,3.5)
    return round(expected_home,3),round(expected_away,3),hxg,axg


def _score_distribution(lam_h,lam_a):
    h=[exp(-lam_h)*(lam_h**k)/factorial(k) for k in range(13)]
    a=[exp(-lam_a)*(lam_a**k)/factorial(k) for k in range(13)]
    combinations={(i,j):h[i]*a[j] for i in range(13) for j in range(13)}
    total=sum(combinations.values())
    return {key:value/total for key,value in combinations.items()}


def _probabilities(distribution,home,away):
    gh=lambda key:sum(p for (h,a),p in distribution.items() if key(h,a))
    p_home=gh(lambda h,a:h>a);p_away=gh(lambda h,a:a>h)
    p_draw=1-p_home-p_away
    results={'home_win':p_home,'draw':p_draw,'away_win':p_away,
             'btts':gh(lambda h,a:h>0 and a>0),
             'big_home':gh(lambda h,a:h>=4 and h>a),
             'big_away':gh(lambda h,a:a>=4 and a>h)}
    results['btts_no']=1-results['btts']
    for i in range(5):
        results[f'over_{i}_5_ft']=gh(lambda h,a,i=i:h+a>i)
        results[f'under_{i}_5_ft']=1-results[f'over_{i}_5_ft']
    results.update({'dc_1x':1-p_away,'dc_12':1-p_draw,'dc_x2':1-p_home,
                    'lay_home':1-p_home,'lay_away':1-p_away,
                    'lay_big_home':1-results['big_home'], 'lay_big_away':1-results['big_away']})
    for i in range(4):
        for j in range(4):results[f'cs_{i}_{j}']=distribution[i,j]
    # Zebra: lado com menor probabilidade de vitória. Lay contra seu 1x0.
    zebra='casa' if p_home<p_away else 'visitante'
    score=(1,0) if zebra=='casa' else (0,1)
    results['lay_zebra_1_0']=1-distribution[score]
    details=[]
    for group,_title,items in MARKET_GROUPS:
        for key,label in items:
            p=results.get(key)
            kind='lay' if key in LAY_ITEMS else 'back'
            details.append({'key':key,'label':label,'group':group,'kind':kind,
                            'probability':round(p*100,2) if p is not None else None,
                            'fair_odd':_fair_odd(p,kind=='lay')})
    laylabel=f'Lay placar {score[0]}×{score[1]} da zebra ({home if zebra=="casa" else away})'
    p=results['lay_zebra_1_0']
    details.append({'key':'lay_zebra_1_0','label':laylabel,'group':'lay','kind':'lay',
                    'probability':round(100*p,2),'fair_odd':_fair_odd(p,True)})
    return details,{'underdog':home if zebra=='casa' else away,'lay_score':f'{score[0]}×{score[1]}'}


def _presentation(home,away,h,a,ha,aa,n):
    names=[('xg','xG criado'),('xg_against','xG sofrido'),('gols_esperados_no_alvo','xG no alvo'),
           ('chutes_gol','Finalizações no gol'),('total_chutes','Finalizações'),
           ('chutes_dentro_area','Chutes na área'),('grandes_chances_criadas','Grandes chances'),
           ('chutes_bloqueados','Chutes bloqueados'),('total_desarmes','Desarmes'),
           ('grandes_chances_perdidas','Grandes chances perdidas'),('posse_bola','Posse de bola',True),
           ('escanteios','Escanteios'),('passes_certos','Passes certos'),
           ('interceptacoes','Interceptações'),('recuperacoes_bola','Recuperações'),
           ('defesas_goleiro','Defesas do goleiro'),
           ('shots_against','Finalizações sofridas'),('sot_against','Finalizações no alvo sofridas'),
           ('percentual_duelos_vencidos','Duelos vencidos',True),('goals_for','Gols marcados'),
           ('goals_against','Gols sofridos')]
    items=[]
    seen=set()
    for row in names:
        key,label=row[:2]
        if key in seen:continue
        seen.add(key)
        x=h.get(key);y=a.get(key)
        if x is None and y is None:continue
        items.append({'key':key,'label':label,'home':round(x,2) if x is not None else None,
                      'away':round(y,2) if y is not None else None,'percent':len(row)>2})
    # Indicadores derivados (razões das médias ponderadas); ausentes se algum termo faltar.
    def ratio(num,den,scale=1.0):
        return lambda p:(p[num]*scale/p[den]) if p.get(num) is not None and p.get(den) else None
    def diff(x,y):
        return lambda p:(p[x]-p[y]) if p.get(x) is not None and p.get(y) is not None else None
    derived=[
      ('pct_chutes_alvo','% de finalizações no gol',ratio('chutes_gol','total_chutes',100),True),
      ('chutes_por_gol','Finalizações para marcar 1 gol',ratio('total_chutes','goals_for'),False),
      ('chutes_alvo_por_gol','Finalizações no gol para marcar 1 gol',ratio('chutes_gol','goals_for'),False),
      ('conversao_chutes','Conversão das finalizações (gols/finalizações)',ratio('goals_for','total_chutes',100),True),
      ('conversao_alvo','Conversão das finalizações no gol',ratio('goals_for','chutes_gol',100),True),
      ('pct_chutes_area','% de finalizações dentro da área',ratio('chutes_dentro_area','total_chutes',100),True),
      ('xg_por_chute','xG por finalização',ratio('xg','total_chutes'),False),
      ('conversao_grandes','Gols por grande chance criada',ratio('goals_for','grandes_chances_criadas',100),True),
      ('gols_menos_xg','Gols − xG (finalização acima/abaixo do esperado)',diff('goals_for','xg'),False),
      ('chutes_sofridos_por_gol','Finalizações sofridas por gol sofrido',ratio('shots_against','goals_against'),False),
      ('chutes_alvo_sofridos_por_gol','Finalizações no alvo sofridas por gol sofrido',ratio('sot_against','goals_against'),False),
      ('pct_defesas','% de defesas do goleiro (defesas/chutes no alvo sofridos)',ratio('defesas_goleiro','sot_against',100),True),
      ('xg_por_chute_sofrido','xG sofrido por finalização sofrida',ratio('xg_against','shots_against'),False),
      ('gols_sofridos_menos_xg','Gols sofridos − xG sofrido',diff('goals_against','xg_against'),False),
    ]
    for key,label,fn,is_pct in derived:
        x=fn(h);y=fn(a)
        if x is None and y is None:continue
        items.append({'key':key,'label':label,'home':round(x,2) if x is not None else None,
                      'away':round(y,2) if y is not None else None,'percent':is_pct})
    return items



def _results_snapshot(games,team):
    wins=draws=losses=gf_total=ga_total=clean=has_goals=0
    for row in games:
        _side,_other,gf,ga,_venue=_team_side(row,team)
        gf_total+=gf;ga_total+=ga
        wins+=int(gf>ga);draws+=int(gf==ga);losses+=int(gf<ga)
        clean+=int(ga==0);has_goals+=int(gf>0)
    return {'games':len(games),'wins':wins,'draws':draws,'losses':losses,
            'goals_for':gf_total,'goals_against':ga_total,
            'clean_sheets':clean,'scored_games':has_goals}


def analyze(country,competition,home,away,interval_games=30):
    n=int(interval_games)
    if n not in (5,10,20,30,50,100):
        raise ValueError('Escolha um intervalo válido: 5, 10, 20, 30, 50 ou 100 jogos.')
    home_games,away_games,h2h=_fetch(country,competition,home,away,n)
    if not home_games or not away_games:
        raise ValueError('Não há resultados recentes suficientes em jogos para um dos clubes.')
    # Intervalo N restringe primeiro TODAS as partidas, inclusive a amostra por mando.
    recent_home=home_games[:n]
    recent_away=away_games[:n]
    hv=_venue_profiles(recent_home,home,n,True)
    av=_venue_profiles(recent_away,away,n,False)
    h_all=_profile(recent_home,home,n)
    a_all=_profile(recent_away,away,n)
    # Mando, quando disponível. Se não há pelo menos 4 partidas no mando,
    # usa o histórico recente completo de cada equipe (exposto ao usuário).
    h=hv if hv['games']>=4 else h_all
    a=av if av['games']>=4 else a_all
    # Defesas do adversário vêm dos resultados no respectivo mando.
    expected_home,expected_away,has_xg_h,has_xg_a=_lambdas(h,a,h,a)
    # Confronto direto recente é informativo, mas tem só 5% de peso e nunca
    # substitui o desempenho contra adversários variados.
    recent_h2h=[g for g in h2h if (date.today()-_date(g['data'])).days<=730][:min(8,n)]
    if len(recent_h2h)>=3:
        hg=mean(int(g['gh'] if g['casa']==home else g['ga']) for g in recent_h2h)
        ag=mean(int(g['ga'] if g['casa']==home else g['gh']) for g in recent_h2h)
        expected_home=round(.95*expected_home+.05*_clamp(hg,.12,4.5),3)
        expected_away=round(.95*expected_away+.05*_clamp(ag,.12,4.5),3)
    # ML treinado em jogos históricos anteriores a cada partida, validado nos
    # 20% mais recentes. Se perder do basal, desativa automaticamente.
    from . import ml_projection_service as ml
    ml_country=country or recent_home[0].get('pais')
    ml_competition=competition or recent_home[0].get('campeonato')
    expected_home,expected_away,ml_diagnostics=ml.calibrate(
        ml_country,ml_competition,h,a,expected_home,expected_away)
    distribution=_score_distribution(expected_home,expected_away)
    probs,extra=_probabilities(distribution,home,away)
    # Placar mais raro restrito a 0x0 até 4x4; não confundir com placar impossível.
    normal_scores={score:p for score,p in distribution.items() if score[0]<=4 and score[1]<=4}
    likely=max(normal_scores,key=normal_scores.get)
    unlikely=min(normal_scores,key=normal_scores.get)
    zebra_home=extra['underdog']==home
    zebra_score=(1,0) if zebra_home else (0,1)
    projection={
       'most_likely':{'score':f'{likely[0]}×{likely[1]}','probability':round(distribution[likely]*100,2)},
       'least_likely':{'score':f'{unlikely[0]}×{unlikely[1]}','probability':round(distribution[unlikely]*100,2)},
       'score_scope':'Placares de 0×0 a 4×4',
       'zebra_one_zero':{'score':f'{zebra_score[0]}×{zebra_score[1]}',
                         'team':extra['underdog'],'probability':round(distribution[zebra_score]*100,2)},
       'simulations':ml.simulations(expected_home,expected_away),
       'simulation_count':20000,
       'ml':{key:value for key,value in ml_diagnostics.items() if key!='weights'},
       'radar':{'home':ml.strength(h,'h'),'away':ml.strength(a,'a')}
    }
    from . import goal_timeline_service as timeline
    goals=timeline.analyze(recent_home,recent_away,home,away,n)
    covered_h=h['coverage']['xg'];covered_a=a['coverage']['xg']
    quality='xg' if has_xg_h and has_xg_a and min(covered_h,covered_a)>=5 else 'parcial' if has_xg_h or has_xg_a else 'gols'
    warnings=[]
    if quality!='xg': warnings.append('Cobertura incompleta de xG: a estimativa utiliza também gols reais. EV é mais incerto.')
    if min(h['games'],a['games']) < 10: warnings.append('Amostra pequena; a estimativa pode variar bastante.')
    if hv['games']<4 or av['games']<4: warnings.append('Mando com poucos jogos; utilizamos jogos recentes também fora do mando para estabilizar.')
    warnings.append('Poisson independente e ajustes heurísticos não calibrados; não representam valor comprovado. Valide em jogos futuros antes de usar stakes.')
    if ml_diagnostics.get('status')!='trained':
        warnings.append('ML supervisionado em fallback: '+str(ml_diagnostics.get('reason') or 'amostra insuficiente'))
    if goals.get('warning'):
        warnings.append(goals['warning'])
    elif (goals.get('home') and goals['home'].get('valid_games',0)<5 or
          goals.get('away') and goals['away'].get('valid_games',0)<5):
        warnings.append('Poucos jogos com sequência de gols completa; percentuais da aba Gols têm alta incerteza.')
    comparison=_presentation(home,away,h,a,h,a,n)
    return {'home':home,'away':away,'country':country,'competition':competition,
            'interval_games':n,'comparison':comparison,
            'probabilities':probs, 'goals':goals, 'projection':projection,
            'recent_results':{'home':_results_snapshot(recent_home,home),
                              'away':_results_snapshot(recent_away,away)},
            'expected_goals':{'home':expected_home,'away':expected_away},
            'method':{'name':'SofaScore xG + finalizações + defesa + gols (Poisson)',
                      'data_source':'jogos + jogo_completo + minutos_gols',
                      'home_games':h['games'],'away_games':a['games'],
                      'home_venue_games':hv['games'],'away_venue_games':av['games'],
                      'h2h_games':len(h2h),
                      'xg_home_games':covered_h,'xg_away_games':covered_a,
                      'quality':quality,'half_life_days':240,'h2h_model_games':len(recent_h2h) if len(recent_h2h)>=3 else 0,'underdog':extra['underdog'],
                      'lay_zebra_score':extra['lay_score'],'warnings':warnings}}
