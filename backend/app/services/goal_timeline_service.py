"""Sequência de gols dos jogos do SofaScore; sem inferir eventos não registrados.

A tabela minutos_gols pode variar entre cargas: valida esquema antes de selecionar
colunas. Toda partida com gols deve possuir a sequência completa e reconciliar
com o placar final, caso contrário ela é excluída dos indicadores de sequência.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime
from functools import lru_cache
import re
import time
from sqlalchemy import text
from ..config import settings
from ..db import history_connection

TABLE = f'{settings.history_schema}.minutos_gols'
BANDS = ('0-15','16-30','31-45','45+','46-60','61-75','76-90','90+')


def _field(cols, *names):
    return next((c for c in names if c in cols), None)


@lru_cache(maxsize=4)
def _layout(bucket):
    with history_connection() as conn:
        rows = conn.execute(text('''SELECT column_name FROM information_schema.columns
            WHERE table_schema=:s AND table_name='minutos_gols' '''),{'s':settings.history_schema}).all()
    cols={r[0] for r in rows}
    if not cols:
        return None, 'Tabela minutos_gols não encontrada: indicadores de gols indisponíveis.'
    layout={
      'game':_field(cols,'id_jogo','jogo_id','id_partida','match_id'),
      'minute':_field(cols,'minuto','minutos','minuto_gol','tempo_gol','tempo','minute'),
      'score_home':_field(cols,'placar_casa','placar_mandante','gols_casa','home_goals','home_score','score_home'),
      'score_away':_field(cols,'placar_fora','placar_visitante','gols_fora','away_goals','away_score','score_away'),
      'score':_field(cols,'placar','placar_gerado','placar_apos','placar_apos_gol','resultado_gol','score_after','score'),
      'order':_field(cols,'id_incidente','id_gol','sequencia','id'),
    }
    if not layout['game'] or not layout['minute'] or not ((layout['score_home'] and layout['score_away']) or layout['score']):
        return None, 'minutos_gols precisa de ID do jogo, minuto e placar após o gol; verifique os nomes das colunas.'
    return layout,None


def _minute(v):
    if v is None: return None
    s=str(v).strip().replace('′','').replace("'",'').replace('’','')
    match=re.search(r'^(\d{1,3})(?:\s*\+\s*(\d{1,2}))?$',s)
    if not match:return None
    base=int(match.group(1)); extra=match.group(2)
    if base>120:return None
    return base, bool(extra is not None),int(extra or 0)


def _band(value):
    result=_minute(value)
    if not result:return None,None
    base,extra,added=result
    if base==45 and extra:return '45+',1
    if base==90 and extra:return '90+',2
    if base>90:return '90+',2
    if base<=15:return '0-15',1
    if base<=30:return '16-30',1
    if base<=45:return '31-45',1
    if base<=60:return '46-60',2
    if base<=75:return '61-75',2
    return '76-90',2


def _score(row):
    try:
        if row.get('score_home') is not None and row.get('score_away') is not None:
            h,a=int(row['score_home']),int(row['score_away'])
        else:
            match=re.fullmatch(r'\s*(\d+)\s*[-x×:]\s*(\d+)\s*',str(row.get('score') or ''))
            if not match:return None
            h,a=map(int,match.groups())
        return (h,a) if h>=0 and a>=0 else None
    except (ValueError,TypeError):return None


def fetch(game_ids):
    layout,error=_layout(int(time.time()//300))
    if error:return {},error
    if not game_ids:return {},None
    columns={k:(f'"{v}"' if v else 'NULL')+f' AS {k}' for k,v in layout.items() if k!='game'}
    sql=f'''SELECT "{layout['game']}"::text AS id_jogo,{','.join(columns.values())}
           FROM {TABLE} WHERE "{layout['game']}"::text = ANY(:ids)'''
    with history_connection() as conn:
        rows=[dict(r) for r in conn.execute(text(sql),{'ids':[str(i) for i in set(game_ids)]}).mappings()]
    grouped=defaultdict(list)
    for row in rows:grouped[str(row['id_jogo'])].append(row)
    return grouped,None


def _sequence(game,events):
    """Retorna sequência válida e completa; em empate 0x0 não há gols nem eventos."""
    gh,ga=int(game['gh']),int(game['ga'])
    if gh+ga==0:return [] if not events else None
    if not events:return None
    parsed=[]
    for row in events:
        score=_score(row)
        timing=_minute(row.get('minute'))
        if score is None or timing is None:return None
        base,extra,added=timing
        # 45+4 ocorre ANTES de 46 regular; 90+3 ocorre após 90.
        period=0 if base<=45 else 1
        minute_order=base + added/100 if extra else base
        parsed.append((period,minute_order,score[0]+score[1],str(row.get('order') or ''),score,row['minute']))
    parsed.sort(key=lambda row:(row[0],row[1],row[2],row[3]))
    prior=(0,0)
    result=[]
    for _,_,_,_,score,minute in parsed:
        if (score[0]-prior[0],score[1]-prior[1]) not in ((1,0),(0,1)):
            return None
        side='h' if score[0]>prior[0] else 'a'
        band,half=_band(minute)
        if not band:return None
        # Minuto efetivo do relógio: acréscimos do 1º tempo contam como 45; do 2º, 90+N.
        base,extra,added=_minute(minute)
        at=45 if base==45 and extra else base+added if base>=90 else base
        result.append({'side':side,'score':score,'before':prior,'band':band,'half':half,'at':at})
        prior=score
    return result if prior==(gh,ga) else None


def _team_metrics(games,team,events_by_game):
    valid=[]; goals=[]; halves={1:0,2:0}; bands=dict.fromkeys(BANDS,0)
    opened=extended=equalized=won_after=lost_after=0
    for game in games:
        events=_sequence(game,events_by_game.get(str(game['id_jogo']),[]))
        if events is None:continue
        home=game['casa']==team
        side='h' if home else 'a'
        valid.append(game)
        first=events[0]['side'] if events else None
        own_open=first==side
        if own_open:
            opened+=1
            extended_here=False;equalized_here=False
            for ev in events[1:]:
                own,other=ev['score'] if home else tuple(reversed(ev['score']))
                old_own,old_other=ev['before'] if home else tuple(reversed(ev['before']))
                if ev['side']==side and old_own>old_other and (own-other)>(old_own-old_other):extended_here=True
                if ev['side']!=side and own==other and old_own>old_other:equalized_here=True
            extended+=int(extended_here);equalized+=int(equalized_here)
            gf=int(game['gh'] if home else game['ga']);ga=int(game['ga'] if home else game['gh'])
            won_after+=int(gf>ga);lost_after+=int(gf<ga)
        for ev in events:
            if ev['side']==side:
                goals.append(ev)
                bands[ev['band']]+=1
                halves[ev['half']]+=1
    matches=len(valid);total=len(goals)
    pct=lambda numerator,denom:round(numerator*100/denom,2) if denom else None
    return {
      'valid_games':matches,'requested_games':len(games),'goals_recorded':total,
      'opened':{'value':pct(opened,matches),'count':opened,'total':matches},
      'extended_after_open':{'value':pct(extended,opened),'count':extended,'total':opened},
      'equalized_after_open':{'value':pct(equalized,opened),'count':equalized,'total':opened},
      'won_after_open':{'value':pct(won_after,opened),'count':won_after,'total':opened},
      'lost_after_open':{'value':pct(lost_after,opened),'count':lost_after,'total':opened},
      'first_half':{'value':pct(halves[1],total),'count':halves[1],'total':total},
      'second_half':{'value':pct(halves[2],total),'count':halves[2],'total':total},
      'minute_bands':[{'label':b,'value':pct(bands[b],total),'count':bands[b],'total':total} for b in BANDS]
    }


def _state(own,other):
    return 'winning' if own>other else 'drawing' if own==other else 'losing'


def _correct_score(games,team,events_by_game):
    """Repetição dos placares finais (jogos) e minutos em cada placar (minutos_gols).

    Placares sempre na ótica do clube (gols do clube-gols do adversário). Duração do
    jogo: 90 min; se o último gol saiu depois dos 90, termina 2 min após esse gol.
    """
    finals=Counter()
    for game in games:
        home=game['casa']==team
        finals[(int(game['gh'] if home else game['ga']),int(game['ga'] if home else game['gh']))]+=1
    minutes=defaultdict(float);appeared=Counter();valid=0;total=0.0
    for game in games:
        events=_sequence(game,events_by_game.get(str(game['id_jogo']),[]))
        if events is None:continue
        home=game['casa']==team
        valid+=1
        orient=(lambda s:s) if home else (lambda s:(s[1],s[0]))
        end=90.0
        if events and events[-1]['at']>90:end=events[-1]['at']+2.0
        clock=0.0;score=(0,0)
        steps=[(ev['at'],ev['score']) for ev in events]+[(end,None)]
        seen=set()
        for at,nxt in steps:
            at=max(clock,min(float(at),end))
            key=orient(score)
            minutes[key]+=at-clock;total+=at-clock
            if at-clock>0:seen.add(key)
            clock=at
            if nxt is not None:score=nxt
        appeared.update(seen)
    pct=lambda v,d:round(v*100/d,2) if d else None
    n=len(games)
    by_state={'winning':0.0,'drawing':0.0,'losing':0.0}
    for (own,other),m in minutes.items():by_state[_state(own,other)]+=m
    scores=[{'score':f'{o}-{p}','state':_state(o,p),'minutes':round(m,1),'pct':pct(m,total),
             'games':appeared[(o,p)],'avg_minutes':round(m/valid,1) if valid else None}
            for (o,p),m in sorted(minutes.items(),key=lambda kv:-kv[1]) if m>0]
    return {'requested_games':n,'valid_games':valid,'total_minutes':round(total,1),
            'final_scores':[{'score':f'{o}-{p}','state':_state(o,p),'count':c,'pct':pct(c,n)}
                            for (o,p),c in sorted(finals.items(),key=lambda kv:(-kv[1],kv[0]))],
            'time_by_state':{k:{'minutes':round(v,1),'pct':pct(v,total)} for k,v in by_state.items()},
            'scores':scores}


def analyze(home_games,away_games,home,away,interval):
    hg=home_games[:interval];ag=away_games[:interval]
    try:
        rows,error=fetch([g['id_jogo'] for g in hg+ag])
    except Exception as ex:
        # Estatísticas faltantes não devem bloquear comparação SofaScore.
        return {'home':None,'away':None,'warning':f'Não foi possível consultar minutos_gols ({type(ex).__name__}).'}
    if error:return {'home':None,'away':None,'warning':error}
    return {'home':_team_metrics(hg,home,rows),'away':_team_metrics(ag,away,rows),
            'correct_score':{'home':_correct_score(hg,home,rows),'away':_correct_score(ag,away,rows)},
            'warning':None,'denominators':'Abertura: partidas com sequência completa; eventos após abertura: partidas em que abriu; distribuição temporal: gols registrados do clube.'}
