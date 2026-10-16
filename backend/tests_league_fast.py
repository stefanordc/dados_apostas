"""Regressões rápidas para análise agrupada SEM ODDS (não toca bancos)."""
import sys
import types
sys.modules.setdefault('app.db',types.SimpleNamespace(app_engine=None,history_connection=lambda:None))
from app.services import backtesting_service as b
from app.services import league_fast_service as fast


def fixture(comp, score, count, month='2025-01'):
    gh,ga=score
    return {
        'date':month+'-01','year':int(month[:4]),'season':'2024/2025','season_key':(2024,2025),
        'home':'','away':'','competition_id':comp,'competition':f'Liga {comp}',
        'country':'Brasil','gh':gh,'ga':ga,'_weight':count,
        'divisao':'1','formato':'Liga','home_odd':None,'draw_odd':None,'away_odd':None,
        'over25_odd':None,'odds_source':None,
    }


def test_grouped_counts_are_not_counted_as_one_game():
    groups=[fixture(1,(2,1),95), fixture(1,(0,0),5,'2025-02'),fixture(2,(1,0),20,'2025-03')]
    got=b._evaluate_fast_leagues(groups,{}, {},'all',None,None)
    assert got['games']==120
    assert got['league_overview']['games']==120
    assert got['league_overview']['home_wins']==115
    assert got['markets']['back_home']['games']==120
    assert got['markets']['back_home']['wins']==115
    assert got['scores']['total']==120
    assert got['scores']['scores'][0]['games']==95
    assert got['annual'][0]['values']['back_home']['games']==120
    assert got['historical_trends']['markets'][0]['total']['games']==120
    assert got['league_comparison']['total_leagues']==2
    home=next(m for m in got['league_comparison']['markets'] if m['key']=='back_home')
    assert [(i['competition'],i['games']) for i in home['items']]==[('Liga 2',20),('Liga 1',100)]
    assert got['data_source']=='historico_jogos'
    assert got['odds_audit'] is None


def test_aggregate_split_uses_game_weight_not_group_count():
    groups=[fixture(1,(2,1),70), fixture(1,(0,0),30,'2025-05')]
    trend=b._historical_trends(groups)['markets'][0]
    assert trend['initial']['games']==70
    assert trend['initial']['win_rate']==100
    assert trend['posterior']['games']==30
    assert trend['posterior']['win_rate']==0
    assert trend['total']['win_rate']==70


def test_grouped_games_filters_and_does_not_expose_prices(monkeypatch):
    sample=[{'country':'Brasil','competition':'Liga 1','season':'2024/2025',
             'month':'2025-04-01','divisao':'1','formato':'Liga','gh':4,'ga':3,'weight':30},
            {'country':'Brasil','competition':'Liga 1','season':'2025/2026',
             'month':'2026-04-01','divisao':'2','formato':'Liga','gh':1,'ga':0,'weight':50}]
    monkeypatch.setattr(fast, '_aggregated', lambda country,competition,division,format_,bucket:sample)
    catalog=[{'id':1,'competition':'Liga 1','country':'Brasil'}]
    got=fast.grouped_games('Brasil',None,'2024/2025',None,None,catalog)
    assert len(got)==1 and got[0]['_weight']==30
    assert got[0]['home_odd'] is None
    assert got[0]['odds_source'] is None


def test_league_filters_single_call_independent_of_number_of_clubs(monkeypatch):
    from app.services import backtesting_filter_service as bf
    from app.services import league_bulk_odds_service as odds
    monkeypatch.setattr(b, '_competition_catalog', lambda country_id=None, competition_id=None: [
        {'id':1,'country_id':1,'country':'Brasil','competition':'Serie A'},
        {'id':2,'country_id':1,'country':'Brasil','competition':'Serie B'},
    ])
    counter={'history':0,'odds':0}
    def mock_options(country, competition):
        counter['history']+=1
        return {'seasons':['2025'], 'divisions':['1'],'formats':['Liga'],
                'division_formats':[{'divisao':'1','formato':'Liga'}]}
    def mock_dims(country, competition):
        counter['odds']+=1
        return (('2','Copa'),)
    bf.clear_cache()
    monkeypatch.setattr(fast,'options',mock_options)
    monkeypatch.setattr(odds,'distinct_odds_dimensions',mock_dims)
    off=bf.league_options(1,None,False)
    assert off['seasons']==['2025']
    assert counter=={'history':1,'odds':0}
    on=bf.league_options(1,None,True)
    assert counter=={'history':2,'odds':1}
    assert on['divisions']==['1','2']
    assert len(on['division_formats'])==2


def test_aggregated_global_query_uses_no_per_league_reads(monkeypatch):
    from sqlalchemy import text as sqltext
    class FakeResult:
        def __init__(self, rows): self.rows=rows
        def all(self): return self.rows
        def mappings(self):return self
        def __iter__(self):return iter(self.rows)
    class Connection:
        queries=[]
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,params=None):
            self.queries.append((str(query),params))
            if 'information_schema.columns' in str(query):
                return FakeResult([('pais',),('campeonato',),('data',),('temporada',),('gols_casa',),('gols_fora',),('divisao',),('formato',)])
            return FakeResult([{
                'country':'Brasil','competition':'Serie A',
                'season':'2025','month':'2025-01-01','divisao':'1','formato':'Liga',
                'gh':2,'ga':1,'weight':11,
            }])
    c=Connection()
    monkeypatch.setattr(fast,'history_connection',lambda:c)
    fast._aggregated.cache_clear()
    items=fast._aggregated(None,None,None,None,123)
    assert len(items)==1 and items[0]['weight']==11
    assert len(c.queries)==2
    assert 'GROUP BY pais' in c.queries[1][0]
    assert 'odds' not in c.queries[1][0]


def test_recent_audit_uses_full_history_denominator(monkeypatch):
    # 100 jogos no agrupado, mas apenas os 2 últimos têm nomes para exibição.
    from app.services import league_fast_service as fast
    groups=[fixture(1,(2,1),70),fixture(1,(1,1),30,'2025-05')]
    samples=[{
        **fixture(1,(2,1),1,'2025-05'),
        'home':'Brasil A','away':'Brasil B','date':'2025-05-11'
    },{
        **fixture(1,(1,1),1,'2025-05'),
        'home':'Brasil C','away':'Brasil D','date':'2025-05-12'
    }]
    monkeypatch.setattr(fast,'recent_games',lambda *args,**kwargs:samples)
    audit=b._evaluate_fast_leagues(groups,{}, {},'all',None,None,
             catalog=[{'id':1,'country':'Brasil','competition':'Liga 1'}],country_name='Brasil')['odds_audit']
    assert audit is not None
    home=audit['games']['back_home']
    assert home[0]['home']=='Brasil C'
    assert home[0]['cumulative_games']==100
    assert home[0]['cumulative_rate']==70
    assert home[1]['cumulative_games']==99
    assert home[1]['cumulative_rate']==round(70*100/99,2)
