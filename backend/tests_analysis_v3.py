"""Regressões isoladas para as novas páginas (sem banco de dados)."""
from __future__ import annotations
import sys,types
from datetime import date,timedelta
sys.modules.setdefault('app.db',types.SimpleNamespace(app_engine=None, history_engine=None, history_connection=lambda:None))
from app.services import match_analysis_service as m
from app.services import market_scanner_service as s
import pytest


def game(days,casa,fora,gh,ga,season='2026'):
    return {'data':date.today()-timedelta(days=days),'temporada':season,
            'casa':casa,'fora':fora,'gh':gh,'ga':ga}


def test_match_metrics_home_and_away_perspective():
    rows=[game(1,'A','B',4,0),game(8,'C','A',1,2),game(15,'B','A',0,0)]
    a=m.metrics(rows,'A')
    assert a['games']==3 and a['wins']==2 and a['draws']==1
    assert a['clean_sheets']==2 and a['scored_4plus']==1
    assert a['goals_for']==6 and a['goals_against']==1
    assert a['common_score'] in ('4 × 0','2 × 1','0 × 0')


def test_last_five_recency_and_contexts():
    rows=[game(i*10,'A','B',i%3,0) for i in range(25)]
    data=m._contexts(rows,rows,'A')
    assert data['last_5']['games']==5
    assert data['last_10']['games']==10
    assert data['last_20']['games']==20
    assert data['h2h_all']['games']==25
    assert m._decay(rows[0],0)>m._decay(rows[10],10)


def test_probabilities_coherent_and_monotone():
    a=[game(i*30,'A','B',2,1) for i in range(65)]
    b=[game(i*30,'A','B',2,1) for i in range(65)]
    results,method=m._predictions(a,b,a[:6],'A','B')
    d={x['key']:x['probability'] for x in results}
    assert 99.95<d['home_win']+d['away_win']+(100-d['home_win']-d['away_win'])<100.05
    assert d['over_0_5_ft']>=d['over_1_5_ft']>=d['over_2_5_ft']
    assert all(x['probability'] is None or 0<=x['probability']<=100 for x in results)
    assert method['home_venue_games']==60


def test_ev_fair_and_good_value():
    fair=m.expected_value(50,2.0)
    positive=m.expected_value(60,2.0)
    assert fair['ev_percent']==0
    assert fair['positive_value'] is False
    assert positive['ev_percent']==20 and positive['positive_value']
    with pytest.raises(ValueError):m.expected_value(50,1.0)


def test_ht_goals_unknown_are_not_assumed_zero():
    assert s._ht_minutes(None,2) is None
    assert s._ht_minutes(None,0)==0
    assert s._ht_minutes('[9, 45+2, 78]',3)==2
    assert s.half_score({'minutos_gols_casa':None,'minutos_gols_fora':None,
                         'gols_casa':2,'gols_fora':0}) is None


def test_event_coverage():
    assert s._market_event('over_1_5_ft',2,0,None)
    assert not s._market_event('under_1_5_ft',2,0,None)
    assert s._market_event('dc_1x',1,1,None)
    assert s._market_event('cs_3_2',3,2,None)
    assert s._market_event('home_ht',2,1,(1,0))
    assert s._market_event('home_ht',2,1,None) is None


def test_scanner_runs_and_fair_profit():
    entries=[{'date':f'2026-01-{i+1:02d}','game_id':str(i),'odd':2.1,'green':bool(x)}
             for i,x in enumerate([1,1,0,0,0,1,1,1])]
    d=s._metrics(entries)
    assert d['good_run']==3 and d['bad_run']==3
    assert d['games']==8 and d['green']==5
    assert d['roi']==31.25


def test_price_ranges_respect_validation_and_min_sample():
    # 50 entradas com odd 2,4 e 100% greens, ambas as janelas positivas.
    good=[{'date':f'2025-{i//28+1:02d}-{i%28+1:02d}','game_id':str(i),'odd':2.4,'green':True} for i in range(50)]
    assert s._bands(good)
    losing=[dict(g,green=False) for g in good]
    assert not s._bands(losing)
    assert not s._bands(good[:20])


def test_statistics_only_does_not_load_odds(monkeypatch):
    from app.services import backtesting_service as legacy
    fake={'date':'2026-04-01','year':2026,'season':'2026','season_key':(2026,2026),
          'home':'A','away':'B','gh':2,'ga':1,'divisao':None,'formato':None,
          'history_divisao':None,'history_formato':None,
          'home_odd':None,'draw_odd':None,'away_odd':None,'over25_odd':None,
          'odds_source':None}
    def fail(*args,**kwargs):
        raise AssertionError('Não deve carregar odds em Estatísticas')
    monkeypatch.setattr(legacy,'_source',fail)
    monkeypatch.setattr(legacy,'_history_source',lambda comp,bucket:([fake],['2026'],['A','B'],{'status':'histórico'},[],[]))
    res=legacy.evaluate({'tab':'team','competition_id':1,'club':'A','use_odds':False,'statistics_only':True})
    assert res['games']==1 and res['data_source']=='historico_jogos'
    assert res['markets']['back_home']['settled']==0


def test_scanner_catalog_respects_available_columns(monkeypatch):
    monkeypatch.setattr(s,'_source',lambda:(None,{'odd_casa_ft','odd_empate_ft','over_0_5_ht'}))
    result=s.catalog()
    names=[g['key'] for g in result['groups']]
    assert 'mo_ft' in names and 'over_ht' in names
    assert 'btts' not in names


def test_ev_markets_cover_all_scanner_groups_and_lay():
    pred,method=m._predictions([game(i,'A','B',2,1) for i in range(40)],
                               [game(i,'A','B',2,1) for i in range(40)], [], 'A','B')
    d={p['key']:p for p in pred}
    from app.services import market_scanner_service as scanner
    scanner_to_ev={
        'home_ft':'home_win','draw_ft':'draw','away_ft':'away_win',
        'btts_yes':'btts','btts_no':'btts_no',
    }
    for group, (_title,markets) in scanner.GROUPS.items():
        for _column,_title,event in markets:
            key=scanner_to_ev.get(event,event)
            assert key in d, (group,key)
    assert len(d)==len(m.EVENTS)
    assert d['lay_home']['kind']=='lay'
    assert d['lay_big_away']['kind']=='lay'
    assert d['home_ht']['probability'] is None  # sem minutos: desconhecido
    assert d['over_0_5_ht']['probability'] is None
    assert d['over_0_5_ft']['probability']>=d['over_1_5_ft']['probability']>=d['over_2_5_ft']['probability']
    assert abs(d['under_2_5_ft']['probability']+d['over_2_5_ft']['probability']-100)<0.03
    assert abs(d['btts_no']['probability']+d['btts']['probability']-100)<0.03
    assert abs(d['dc_1x']['probability']+d['away_win']['probability']-100)<0.03
    assert abs(d['lay_home']['probability']+d['home_win']['probability']-100)<0.03
    assert all(p['fair_odd'] is None or round(p['fair_odd'],2)==p['fair_odd'] for p in pred)


def test_ht_minutes_enable_only_real_first_half_market_probabilities():
    matches=[]
    for i in range(20):
        match=game(i,'A','B',2,1)
        match['minutos_gols_casa']='[12, 60]'
        match['minutos_gols_fora']='[78]'
        matches.append(match)
    pred,_=m._predictions(matches,matches,matches[:8],'A','B')
    d={p['key']:p['probability'] for p in pred}
    assert d['home_ht'] is not None
    assert d['over_0_5_ht']>d['over_1_5_ht']>=d['over_2_5_ht']
    assert abs(d['home_ht']+d['draw_ht']+d['away_ht']-100)<0.03
    assert abs(d['over_0_5_ht']+d['under_0_5_ht']-100)<0.03


def test_lay_ev_uses_fixed_liability_and_maximum_fair_odd():
    positive=m.expected_value(60,2.00,'lay')
    negative=m.expected_value(60,3.00,'lay')
    assert positive['ev_percent']==20.0
    assert negative['ev_percent']==-10.0
    assert positive['fair_odd']==2.50
    assert m.expected_value(50,2.00)['ev_percent']==0
    assert m._fair_odd(.8, True)==5.00
    assert m._fair_odd(1., True) is None
    with pytest.raises(ValueError,match='Tipo'):
        m.expected_value(50,2.00,'something')
