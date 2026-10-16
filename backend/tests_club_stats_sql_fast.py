"""Comportamento da agregação rápida; não acessa banco de produção."""
import sys
import types

sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))
from app.services import club_statistics_service as service
from app.services.backtesting_service import MARKETS, _market_evaluation


def test_single_aggregation_sql_global_eligibility_and_date_cut():
    stmt,params=service._fast_ranking_sql('Brasil','Brasileiro',None,2024,2026)
    sql=str(stmt)
    assert sql.count('FROM public.historico_jogos') == 1
    assert 'WITH valid_games AS MATERIALIZED' in sql
    assert 'COUNT(*)>500' in sql
    assert "INTERVAL '3 years')>=100" in sql
    assert 'competition=:competition' in sql
    assert 'data>=CAST(:year_from AS DATE)' in sql
    assert params['year_from']=='2024-01-01'
    assert params['year_to']=='2027-01-01'
    for key,_,_ in MARKETS:
        assert f'AS {key}_games' in sql
        assert f'AS {key}_wins' in sql


def test_fast_ranking_only_eligible_and_real_sample(monkeypatch):
    class Connection:
        def execute(self,query,params):
            assert 'HAVING COUNT(*)>500' in str(query)
            good={
                'country':'Brasil','club':'Clube A',
                'all_games':560,'recent_games':30,
            }
            for key,_,_ in MARKETS:
                good[f'{key}_games']=7
                good[f'{key}_wins']=4
            empty=dict(good,club='Clube B',all_games=140,recent_games=110)
            for key,_,_ in MARKETS:
                empty[f'{key}_games']=0
                empty[f'{key}_wins']=0
            return type('Rows',(),{'mappings':lambda self:[good,empty]})()
        def __enter__(self):return self
        def __exit__(self,*args):return None
    monkeypatch.setattr(service,'history_connection',lambda:Connection())
    monkeypatch.setattr(service,'_registered_countries',lambda bucket:{'clube a':'Brasil'})
    results=service._fast_ranking_without_odds()
    assert results['eligible_count']==1
    for group in results['markets'].values():
        assert len(group['items'])==1
        row=group['items'][0]
        assert (row['games'],row['wins'],row['losses'])==(7,4,3)
        assert row['win_rate']==57.14
        assert row['profit'] is None and row['roi'] is None


def test_fast_market_conditions_correspond_to_prior_evaluation():
    # Documento verificável das regras usadas na agregação SQL.
    # Confere escopo de mando para todos os 12 mercados.
    assert set(service._MARKET_CONDITIONS)=={key for key,_,_ in MARKETS}
    assert service._MARKET_CONDITIONS['back_home']==("venue='home'",'gh>ga')
    assert service._MARKET_CONDITIONS['back_away']==("venue='away'",'ga>gh')
    assert service._MARKET_CONDITIONS['lay_big_home'][1]=='NOT (gh>ga AND gh>=4)'
    assert service._MARKET_CONDITIONS['lay_big_away'][1]=='NOT (ga>gh AND ga>=4)'


def test_fast_autocomplete_preserves_global_qualification(monkeypatch):
    seen=[]
    class Conn:
        def execute(self,query,params):
            seen.append((str(query),params))
            return type('Res',(),{'mappings':lambda self:[{'country':'Brasil','club':'Atlético'}]})()
        def __enter__(self):return self
        def __exit__(self,*args):return None
    monkeypatch.setattr(service,'history_connection',lambda:Conn())
    got=service._fast_candidates('Brasil','Brasileiro','Atlé',10)
    assert got['clubs']==['Atlético']
    assert 'BOOL_OR(competition=:competition)' in seen[0][0]
    assert seen[0][1]['term']=='%Atlé%'


def test_production_ranking_uses_sql_shortcut(monkeypatch):
    seen=[]
    monkeypatch.setattr(service, 'app_engine', object())
    monkeypatch.setattr(service, '_cached_fast_ranking_without_odds',
                        lambda *args: (seen.append(args) or {'markets':{},'eligible_count':0}))
    monkeypatch.setattr(service, '_market_rows',
                        lambda *args: (_ for _ in ()).throw(AssertionError('Não pode carregar jogos linha a linha')))
    got=service.ranking({'use_odds':False})
    assert got['eligible_count']==0
    assert seen and seen[0][:5]==(None,None,None,None,None)
