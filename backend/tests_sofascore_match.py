"""Regressões: ligação por IDs, estatísticas faltantes e eventos de Lay."""
import sys
import types
from datetime import date, timedelta
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None,history_engine=None,history_connection=lambda:None))
from app.services import sofascore_match_service as sofa
import pytest


def game(i, gh=1, ga=0, with_stats=True):
    return {
        'id_jogo':i,'data':date.today()-timedelta(days=i*6+1),'temporada':'2026',
        'pais':'Brasil','campeonato':'Brasileiro','casa':'Mandante','fora':'Visitante',
        'id_mandante':1,'id_visitante':2,'gh':gh,'ga':ga,
        'h_xg':1.85 if with_stats else None,'a_xg':.65 if with_stats else None,
        'h_total_chutes':18 if with_stats else None,'a_total_chutes':7 if with_stats else None,
        'h_chutes_gol':6 if with_stats else None,'a_chutes_gol':2 if with_stats else None,
        'h_grandes_chances_criadas':4 if with_stats else None,'a_grandes_chances_criadas':1 if with_stats else None,
        'h_posse_bola':'58%' if with_stats else None,'a_posse_bola':'42%' if with_stats else None,
    }


def test_profile_is_correct_for_home_and_away():
    a=game(1)
    h=sofa._profile([a],'Mandante',20)
    v=sofa._profile([a],'Visitante',20)
    assert h['xg']==1.85 and v['xg']==.65
    assert h['xg_against']==.65 and v['xg_against']==1.85
    assert h['goals_for']==1 and v['goals_for']==0
    assert h['posse_bola']==58 and v['posse_bola']==42


def test_probabilities_coherent_lay_goleada_and_lay_1x0():
    probs,extra=sofa._probabilities(sofa._score_distribution(1.9,.8),'Mandante','Visitante')
    d={r['key']:r for r in probs}
    assert abs(d['home_win']['probability'] + d['away_win']['probability'] + d['draw']['probability'] - 100)<0.04
    assert d['over_0_5_ft']['probability']>=d['over_1_5_ft']['probability']>=d['over_2_5_ft']['probability']
    assert d['lay_big_home']['probability']+d['big_home']['probability']==pytest.approx(100,abs=.04)
    assert d['lay_zebra_1_0']['kind']=='lay'
    assert extra['underdog']=='Visitante' and extra['lay_score']=='0×1'
    assert d['lay_zebra_1_0']['fair_odd'] is not None
    assert d['home_ht']['probability'] is None


def test_missing_sofascore_is_reported_as_fallback(monkeypatch):
    vals=[game(i,2,1,False) for i in range(20)]
    monkeypatch.setattr(sofa,'_fetch',lambda *args:(vals,vals,vals[:5]))
    report=sofa.analyze('Brasil','Brasileiro','Mandante','Visitante',20)
    assert report['method']['quality']=='gols'
    assert report['method']['xg_home_games']==0
    assert report['probabilities']
    assert report['comparison']
    assert any('incompleta' in w for w in report['method']['warnings'])


def test_recent_more_important():
    a=game(0);b=game(120)
    assert sofa._weight(a,0)>sofa._weight(b,1)
    assert sofa._mean_weighted([(2,3),(0,1)])==1.5


def test_interval_validation(monkeypatch):
    with pytest.raises(ValueError, match='intervalo'):
        sofa.analyze(None,None,'A','B',13)
    fixtures=[game(i) for i in range(35)]
    monkeypatch.setattr(sofa,'_fetch',lambda *args:(fixtures,fixtures,fixtures[:3]))
    res=sofa.analyze(None,None,'Mandante','Visitante',10)
    assert res['interval_games']==10
    assert res['method']['home_games']==10 and res['method']['away_games']==10
    assert res['expected_goals']['home']>res['expected_goals']['away']


def test_null_is_not_silent_zero():
    row=game(1,with_stats=False)
    result=sofa._profile([row],'Mandante',10)
    assert result['xg'] is None
    assert result['coverage']['xg']==0
    assert result['goals_for']==1
