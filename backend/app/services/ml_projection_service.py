"""Calibração supervisionada de gols com separação temporal.

Modelo de regressão Poisson leve, treinado apenas em características conhecidas
ANTES de cada partida. Usa predição basal xG/forma como offset, compara
log-loss Poisson com o basal nos 20% de jogos mais recentes e só aceita o
ajuste quando melhora. Não depende de scikit-learn.
"""
from __future__ import annotations
from collections import defaultdict, deque
from datetime import date
from functools import lru_cache
from math import exp, log, lgamma, isfinite
from random import Random
import time
from sqlalchemy import text
from ..config import settings
from ..db import history_connection


def _profile(games,club):
    from .sofascore_match_service import _profile as origin
    return origin(list(reversed(games)),club,len(games)) if games else None


def _baseline_and_features(h,a):
    from .sofascore_match_service import _lambdas,_clamp
    bh,ba,_,_=_lambdas(h,a,h,a)
    def ft(own,other,baseline):
        def diff(x,y,scale):
            v=own.get(x);w=other.get(y)
            return _clamp(((v or 0)-(w or 0))/scale,-1.5,1.5) if v is not None and w is not None else 0.
        return (1.,diff('xg','xg_against',2),diff('goals_for','goals_against',2),
                diff('chutes_gol','sot_against',6),
                _clamp(((own.get('posse_bola') or 50)-50)/25,-1.5,1.5))
    return [(bh,ft(h,a,bh)),(ba,ft(a,h,ba))]


def _fit(samples,epochs=220):
    weights=[0.]*5
    if not samples:return weights
    normalizer=sum(w for _b,_x,_y,w in samples)
    for epoch in range(epochs):
        gradients=[0.]*len(weights)
        for base,x,goals,w in samples:
            z=max(-1.1,min(1.1,sum(b*v for b,v in zip(weights,x))))
            pred=max(.05,min(6.0,base*exp(z)))
            residual=w*(goals-pred)
            for i in range(len(weights)):
                gradients[i]+=residual*x[i]
        learning=.1/(1+epoch/120)
        for i in range(len(weights)):
            weights[i]=max(-.6,min(.6,weights[i]+learning*(gradients[i]/normalizer-.03*weights[i])))
    return weights


def _predict(base,x,weights):
    return max(.10,min(5.5,base*exp(max(-1.1,min(1.1,sum(w*v for w,v in zip(weights,x)))))))


def _loss(samples,weights):
    if not samples:return None
    return sum(w*(_predict(b,x,weights)-g*log(_predict(b,x,weights))+lgamma(g+1))
               for b,x,g,w in samples)/sum(r[3] for r in samples)


def train_rows(fixtures):
    """Cada jogo só recebe forma de partidas com data estritamente anterior."""
    from .sofascore_match_service import _date,_team_side
    team_history=defaultdict(lambda:deque(maxlen=22))
    samples=[]
    rows=sorted(fixtures,key=lambda r:(str(r['data']),str(r['id_jogo'])))
    i=0
    while i<len(rows):
        day=_date(rows[i]['data'])
        today=[]
        while i<len(rows) and _date(rows[i]['data'])==day:
            today.append(rows[i]);i+=1
        for game in today:
            home=game['casa'];away=game['fora']
            previous_h=team_history[home];previous_a=team_history[away]
            if len(previous_h)<5 or len(previous_a)<5:continue
            h=_profile(previous_h,home);a=_profile(previous_a,away)
            if h is None or a is None:continue
            pair=_baseline_and_features(h,a)
            days_old=max(0,(date.today()-day).days)
            weight=max(.20,.5**(days_old/950))
            samples.append((str(day),pair[0][0],pair[0][1],int(game['gh']),weight))
            samples.append((str(day),pair[1][0],pair[1][1],int(game['ga']),weight))
        # Atualiza após gerar features de TODOS os jogos do mesmo dia.
        for game in today:
            team_history[game['casa']].append(game)
            team_history[game['fora']].append(game)
    if len(samples)<140:
        return {'status':'fallback','reason':'Menos de 70 partidas com histórico anterior suficiente para treinar.',
                'training_games':len(samples)//2,'validation_games':0}
    boundary=max(2,int(len(samples)*.8)//2*2)
    train=[(b,x,y,w) for _,b,x,y,w in samples[:boundary]]
    val=[(b,x,y,w) for _,b,x,y,w in samples[boundary:]]
    weights=_fit(train)
    base_loss=_loss(val,[0.]*5)
    model_loss=_loss(val,weights)
    # Improvement check prevents applying an overfitted model.
    accepted=model_loss is not None and base_loss is not None and model_loss<base_loss*.997
    return {'status':'trained' if accepted else 'fallback',
            'reason':None if accepted else 'Modelo não melhorou o Poisson na validação cronológica.',
            'weights':weights if accepted else None,
            'training_games':len(train)//2,'validation_games':len(val)//2,
            'baseline_log_loss':round(base_loss,4),'model_log_loss':round(model_loss,4)}


@lru_cache(maxsize=20)
def _training_cache(country,competition,bucket):
    from .sofascore_match_service import _schema,STATS_FIELDS,JOGOS,STATS
    schema=_schema(bucket)
    columns=schema['jogo_completo']
    # Para não varrer várias ligas com um único clique, treinamento limitado à
    # competição/país inferidos do confronto e às últimas 1600 partidas.
    select=','.join(f'{alias}.{col} AS {prefix}_{col}' if col in columns else f'NULL AS {prefix}_{col}'
        for alias,prefix in [('sh','h'),('sa','a')] for col in STATS_FIELDS)
    rules=['j.data < CURRENT_DATE','j.gols_casa IS NOT NULL','j.gols_fora IS NOT NULL']
    params={}
    if country:rules.append('j.pais=:country');params['country']=country
    if competition:rules.append('j.campeonato=:competition');params['competition']=competition
    sql=f'''SELECT * FROM (SELECT j.id_jogo,j.data,j.mandante casa,j.visitante fora,
           j.gols_casa gh,j.gols_fora ga,{select}
           FROM {JOGOS} j LEFT JOIN {STATS} sh ON sh.id_jogo=j.id_jogo AND sh.id_clube=j.id_mandante
           LEFT JOIN {STATS} sa ON sa.id_jogo=j.id_jogo AND sa.id_clube=j.id_visitante
           WHERE {' AND '.join(rules)} ORDER BY j.data DESC LIMIT 1600) t ORDER BY t.data ASC'''
    with history_connection() as conn:
        rows=[dict(r) for r in conn.execute(text(sql),params).mappings()]
    return train_rows(rows)


def calibrate(country,competition,home_profile,away_profile,expected_home,expected_away):
    try:
        trained=_training_cache(country or '',competition or '',int(time.time()//900))
        if trained['status']!='trained':return expected_home,expected_away,trained
        h,a=_baseline_and_features(home_profile,away_profile)
        ml_home=_predict(h[0],h[1],trained['weights'])
        ml_away=_predict(a[0],a[1],trained['weights'])
        # Encolhimento torna previsão menos sensível a pequenas amostras de treino.
        return round(.55*ml_home+.45*expected_home,3),round(.55*ml_away+.45*expected_away,3),trained
    except Exception as ex:
        return expected_home,expected_away,{'status':'fallback','reason':f'Treinamento indisponível ({type(ex).__name__}); Poisson convencional aplicado.',
                                             'training_games':0,'validation_games':0}


def simulations(lam_h,lam_a,n=20000):
    rng=Random(134)
    def draw(lam):
        # Inversão da distribuição Poisson com geração pseudorrandômica fixa.
        p=exp(-lam);r=rng.random();acc=p;k=0
        while r>acc and k<20:
            k+=1;p*=lam/k;acc+=p
        return k
    result=defaultdict(int)
    for _ in range(n):result[draw(lam_h),draw(lam_a)]+=1
    values={'home_win':0,'draw':0,'away_win':0,'over_1_5_ft':0,'over_2_5_ft':0,
            'btts':0,'big_home':0,'big_away':0}
    for (h,a),count in result.items():
        key='home_win' if h>a else 'away_win' if a>h else 'draw'
        values[key]+=count
        values['over_1_5_ft']+=count*(h+a>=2)
        values['over_2_5_ft']+=count*(h+a>=3)
        values['btts']+=count*(h>0 and a>0)
        values['big_home']+=count*(h>=4 and h>a)
        values['big_away']+=count*(a>=4 and a>h)
    return {key:round(value*100/n,2) for key,value in values.items()}


def strength(profile,side):
    from .sofascore_match_service import _clamp
    def normal(field,typical,reverse=False):
        v=profile.get(field)
        if v is None or profile['coverage'].get(field,0)<3:return None
        if reverse:return _clamp(80-40*v/typical,0,100)
        return _clamp(v/typical*65,0,100)
    def average(*values):
        sample=[v for v in values if v is not None]
        return round(sum(sample)/len(sample),1) if sample else None
    attack=average(normal('xg',1.5),normal('goals_for',1.5),normal('chutes_gol',5))
    defence=average(normal('xg_against',1.2,True),normal('goals_against',1.25,True),
                    normal('interceptacoes',10),normal('recuperacoes_bola',45))
    creativity=average(normal('grandes_chances_criadas',2.5),normal('chutes_dentro_area',7),normal('passes_certos',390))
    force=average(normal('posse_bola',55),normal('recuperacoes_bola',45),normal('percentual_duelos_vencidos',52))
    return {'attack':attack,'defense':defence,'creativity':creativity,'strength':force}
