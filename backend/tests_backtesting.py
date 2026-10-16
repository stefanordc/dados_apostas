"""Testes de regressão autônomos (não precisam dos dois bancos ativos)."""
import sys, types
sys.modules['app.db']=types.SimpleNamespace(app_engine=None,history_connection=lambda:None)
from app.services import backtesting_service as b

GAMES = [
 {'date':'2024-01-01','year':2024,'season':'2023/2024','season_key':(2023,2024),'home':'Chelsea','away':'Fulham','gh':4,'ga':3,
  'odds_source':'historico_odds','home_odd':2.0,'away_odd':3.9,'draw_odd':3.3,'over25_odd':1.8},
 {'date':'2024-01-07','year':2024,'season':'2023/2024','season_key':(2023,2024),'home':'Fulham','away':'Chelsea','gh':0,'ga':2,
  'odds_source':'historico_odds','home_odd':2.5,'away_odd':2.85,'draw_odd':3.1,'over25_odd':2.1},
 {'date':'2025-03-05','year':2025,'season':'2024/2025','season_key':(2024,2025),'home':'Chelsea','away':'Arsenal','gh':8,'ga':7,
  'odds_source':'historico_odds','home_odd':1.7,'away_odd':4.6,'draw_odd':3.7,'over25_odd':1.35},
]

def test_correct_score_and_goleada():
    assert b._market_evaluation(GAMES[2],'lay_big_home','Chelsea','any')[1] is False
    assert b._market_evaluation(GAMES[2],'lay_big_away','Chelsea','any')[1] is True
    assert b._market_evaluation(GAMES[0],'lay_big_home','Chelsea','any')[1] is False
    scores=b._correct_scores(GAMES)
    assert scores['total']==3
    assert next(r for r in scores['scores'] if r['score']=='Outros placares')['games']==1

def test_back_profit():
    f={k:(None,None) for k in ['mo','over15','over25','btts']}
    s=b._summary(GAMES,'back_home','Chelsea','any',f)
    assert s['games']==2 and s['wins']==2
    assert s['profit']==170.0 and s['stakes']==1.7
    assert s['breakeven_odd']==1.0

def test_lay_has_no_synthetic_profit():
    f={k:(None,None) for k in ['mo','over15','over25','btts']}
    s=b._summary(GAMES,'lay_home','Chelsea','any',f)
    assert s['profit'] is None and s['settled']==0
    assert s['breakeven_type']=='max'

def test_filter_with_missing_odds():
    f={'mo':(None,None),'over15':(1.5,2.5),'over25':(None,None),'btts':(None,None)}
    s=b._summary(GAMES,'over15','Chelsea','any',f)
    assert s['games']==0

def test_season_keys():
    assert b._season_key('2025/26')==(2025,2026)
    assert b._season_key('2026')==(2026,2026)
    assert b._display_season('2025/26')=='2025/2026'


def test_evaluate_annual_independent_of_start_season():
    old=b._source
    try:
        b._source=lambda competition_id,bucket:(tuple(GAMES),['2024/2025','2023/2024'],['Chelsea','Fulham','Arsenal'],{'status':'ok'},[],[])
        d=b.evaluate({'competition_id':1,'tab':'team','club':'Chelsea','start_season':'2024/2025','years':3})
        assert d['games']==1
        older=next(y for y in d['annual'] if y['year']==2024)
        assert older['values']['back_home']['games']==1
        assert older['values']['back_away']['games']==1
    finally:
        b._source=old

def test_h2h_with_opponent_only():
    old=b._source
    try:
        b._source=lambda competition_id,bucket:(tuple(GAMES),[],['Chelsea','Fulham','Arsenal'],{'status':'ok'},[],[])
        d=b.evaluate({'competition_id':1,'tab':'team','club':'Chelsea','opponent':'Fulham'})
        assert d['games']==3 and d['head_to_head']['games']==2
        assert d['head_to_head']['scores']['total']==2
    finally:
        b._source=old



def test_every_tab_returns_twelve_markets():
    original=b._source
    try:
        b._source=lambda competition_id,bucket:(tuple(GAMES),['2024/2025','2023/2024'],['Chelsea','Fulham','Arsenal'],{'status':'ok'},[],[])
        expected={key for key,_,_ in b.MARKETS}
        assert len(expected)==12
        for tab in ('team','mo_home','mo_away','lay_home','lay_away','lay_big_home','lay_big_away','scores'):
            result=b.evaluate({'competition_id':1,'tab':tab,'club':'Chelsea','opponent':'Fulham'})
            assert set(result['markets'])==expected,tab
            assert set(result['head_to_head']['markets'])==expected,tab
            if tab=='scores':
                assert result['scores']['total']>0
                assert result['head_to_head']['scores']['total']>0
    finally:
        b._source=original

if __name__=='__main__':
    for name,fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('PASS',name)


def test_audit_is_scoped_to_selected_tab_and_filters():
    original = b._source
    try:
        b._source = lambda competition_id, bucket: (
            tuple(GAMES), ['2024/2025', '2023/2024'],
            ['Chelsea', 'Fulham', 'Arsenal'], {'status': 'ok'}, [], []
        )
        result = b.evaluate({
            'competition_id': 1, 'tab': 'lay_big_home',
            'club': 'Chelsea', 'opponent': 'Fulham', 'start_season': '2023/2024',
            'mo_max': 2.1,
        })
        audit = result['odds_audit']
        assert audit['default_market'] == 'lay_big_home'
        assert len(audit['markets']) == 1
        rows = audit['games']['lay_big_home']
        assert len(rows) == 1
        assert rows[0]['home'] == 'Chelsea' and rows[0]['away'] == 'Fulham'
        assert rows[0]['green'] is False and rows[0]['priced'] is False
        assert rows[0]['profit'] is None and rows[0]['odd'] is None
    finally:
        b._source = original


def test_real_lay_quote_settles_with_fixed_liability():
    f = {k: (None, None) for k in ('mo', 'over15', 'over25', 'btts')}
    g1 = {**GAMES[0], 'lay_big_home_odd': 3.0}
    g2 = {**GAMES[1], 'lay_big_home_odd': 3.0}
    report = b._summary([g1, g2], 'lay_big_home', '', 'home', f)
    assert report['settled'] == 2
    assert report['wins'] == 1
    # 4 x 3: lay de goleada perde a responsabilidade; 0 x 2: lay ganha R$50.
    assert report['profit'] == -50.0
    assert report['stakes'] == -0.5
    audit = b._audit_games([g1, g2], f, '', 'home', ['lay_big_home'])
    assert len(audit['games']['lay_big_home']) == 2
    assert sorted(x['profit'] for x in audit['games']['lay_big_home']) == [-100.0, 50.0]


def test_history_market_correct_red_green_without_quote():
    f = {k: (None, None) for k in ('mo', 'over15', 'over25', 'btts')}
    # Lay permite auditar resultado mesmo quando não há odd; Back exige odd real.
    rows = b._audit_games(GAMES, f, 'Chelsea', 'any', ['lay_big_home', 'back_home'])
    assert len(rows['games']['lay_big_home']) == 2
    assert all(r['profit'] is None for r in rows['games']['lay_big_home'])
    assert len(rows['games']['back_home']) == 2
    assert all(r['priced'] for r in rows['games']['back_home'])


def test_divisao_formato_filters_are_shared_across_all_tabs():
    original=b._source
    old_options=b.options
    demo=[
        {**GAMES[0], 'divisao':'1ª Divisão', 'formato':'Pontos corridos'},
        {**GAMES[1], 'divisao':'2ª Divisão', 'formato':'Pontos corridos'},
        {**GAMES[2], 'divisao':'1ª Divisão', 'formato':'Mata-mata'},
    ]
    try:
        b._source=lambda comp,bucket:(tuple(demo), ['2024/2025', '2023/2024'], ['Chelsea','Fulham','Arsenal'], {'status':'ok'}, [], [])
        # Este teste valida filtros das abas; os seletores têm testes próprios.
        def stub_options(comp):
            pairs={(g.get('divisao',''),g.get('formato','')) for g in demo}
            return {'divisions': sorted({p[0] for p in pairs}),
                    'formats': sorted({p[1] for p in pairs}),
                    'division_formats':[{'divisao':d,'formato':f} for d,f in pairs]}
        b.options=stub_options
        catalog=b.options(1)
        assert catalog['divisions']==['1ª Divisão','2ª Divisão']
        assert catalog['formats']==['Mata-mata','Pontos corridos']
        assert {'divisao':'1ª Divisão','formato':'Mata-mata'} in catalog['division_formats']
        for tab in ('team','mo_home','mo_away','lay_home','lay_away','lay_big_home','lay_big_away','scores'):
            payload={'competition_id':1,'tab':tab,'club':'Chelsea','divisao':'1ª Divisão','formato':'Pontos corridos', 'years':5, 'opponent':'Fulham'}
            result=b.evaluate(payload)
            assert result['games']==1,tab
            assert result['head_to_head']['games']==1,tab
            assert result['divisao']=='1ª Divisão'
            assert result['formato']=='Pontos corridos'
            assert set(result['markets']) == {k for k,_,_ in b.MARKETS}
            assert sum(y['values']['back_home']['games'] for y in result['annual'])==1,tab
        all_data=b.evaluate({'competition_id':1,'tab':'scores','divisao':'1ª Divisão','years':5})
        assert all_data['scores']['total']==2
        # Só divisão desconhecida significa amostra vazia, não fallback para todos.
        empty=b.evaluate({'competition_id':1,'tab':'scores','divisao':'3ª Divisão'})
        assert empty['games']==0
    finally:
        b._source=original
        b.options=old_options


def test_historical_odds_metadata_scopes_audit():
    original=b._source
    try:
        g={**GAMES[0],'divisao':'Primeira', 'formato':'Liga'}
        b._source=lambda comp,bucket:((g,),[],['Chelsea','Fulham'],{'status':'ok'},[],[])
        report=b.evaluate({'competition_id':1,'tab':'mo_home','club':'Chelsea','divisao':'Primeira','formato':'Liga'})
        assert report['odds_audit']['games']['back_home'][0]['divisao']=='Primeira'
        assert report['odds_audit']['games']['back_home'][0]['formato']=='Liga'
    finally:
        b._source=original
