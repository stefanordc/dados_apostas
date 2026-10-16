"""Regressões da aba Estatísticas por Clube sem acesso ao banco real."""
import sys
import types
from datetime import date
import pytest

sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))
from app.services import club_statistics_service as c


@pytest.fixture(autouse=True)
def sample(monkeypatch):
    qualifying={
      ('Brasil','Atlético'): {'all_games':620,'recent_games':35},
      ('Brasil','Recente FC'): {'all_games':150,'recent_games':101},
    }
    monkeypatch.setattr(c,'eligible',lambda:qualifying)
    monkeypatch.setattr(c,'_registered_countries',lambda bucket:{})
    monkeypatch.setattr(c,'_grouped_without_odds', lambda *args: [
      dict(country='Brasil',club='Atlético',venue='home',year=2024,gh=2,ga=0,weight=6),
      dict(country='Brasil',club='Atlético',venue='away',year=2024,gh=1,ga=2,weight=4),
      dict(country='Brasil',club='Recente FC',venue='home',year=2025,gh=0,ga=0,weight=3),
      dict(country='Brasil',club='Pequeno',venue='home',year=2025,gh=1,ga=0,weight=90),
    ])


def test_two_eligibility_paths_and_small_club_exclusion():
    result=c.ranking({'use_odds':False})
    home=result['markets']['back_home']['items']
    assert {x['club'] for x in home}=={'Atlético','Recente FC'}
    assert next(x for x in home if x['club']=='Atlético')['games']==6
    assert next(x for x in home if x['club']=='Atlético')['wins']==6
    away=result['markets']['back_away']['items']
    assert away[0]['games']==4 and away[0]['wins']==4
    assert result['eligible_count']==2


def test_correct_market_and_weighted_frequency():
    d=c.ranking({'use_odds':False})
    target=lambda key: next(x for x in d['markets'][key]['items'] if x['club']=='Atlético')
    assert target('lay_home')['wins']==0
    assert target('lay_away')['wins']==0
    assert target('over15')['games']==10
    assert target('over25')['wins']==4
    assert target('btts')['wins']==4
    assert target('lay_big_home')['wins']==6
    assert target('back_home')['profit'] is None


def test_optional_filters_forwarded(monkeypatch):
    seen=[]
    monkeypatch.setattr(c,'_grouped_without_odds',lambda *args: (seen.append(args) or []))
    monkeypatch.setattr('app.services.league_catalog_service.selected',lambda *args:[{'id':1}])
    c.ranking({'country':'Brasil','competition':'Brasileiro','club':'Atlético','year_from':2023,'year_to':2025})
    assert seen == [('Brasil','Brasileiro','Atlético',2023,2025)]


def test_invalid_year_range():
    with pytest.raises(ValueError,match='Ano de'):
        c.ranking({'year_from':2026,'year_to':2024})


def test_year_history_independent_of_ranking_range():
    result=c.history({'country':'Brasil','club':'Atlético','market':'back_home','use_odds':False,'year_from':1990,'year_to':1991})
    assert len(result['years'])==10
    assert result['years'][-1]['year']==date.today().year
    assert result['total']['games']==6
    assert result['years'][-3]['games'] == (6 if date.today().year-2==2024 else 0)


def test_no_odd_not_forged_even_in_lay(monkeypatch):
    monkeypatch.setattr(c,'_odds_games',lambda *args: [
      {'date':'2026-01-01','year':2026,'home':'Atlético','away':'Oponente','gh':2,'ga':0,
       'country':'Brasil','home_odd':2.0,'away_odd':3.0,'draw_odd':3.0,
       'lay_home_odd':None,'over25_odd':None},
    ])
    result=c.ranking({'use_odds':True})
    assert result['markets']['back_home']['items'][0]['profit']==100.0
    assert result['markets']['back_home']['items'][0]['roi']==100.0
    assert result['markets']['lay_home']['items'][0]['profit'] is None
    assert result['markets']['lay_home']['items'][0]['roi'] is None


def test_country_catalog_fallback_when_unknown():
    assert c._country_label('Não Cadastrado','América do Sul')==(
      'América do Sul','país/região do campeonato (histórico)')


def test_sql_qualification_exact_threshold(monkeypatch):
    sql=[]
    class Conn:
        def execute(self,query,params):
            sql.append(str(query))
            return type('Rows',(),{'mappings':lambda self:self,'__iter__':lambda self:iter([])})()
        def __enter__(self):return self
        def __exit__(self,*a):pass
    monkeypatch.setattr(c,'history_connection',lambda:Conn())
    c._eligible.cache_clear()
    assert c._eligible(987654)=={}
    assert 'HAVING COUNT(*) > 500' in sql[0]
    assert "INTERVAL '3 years') >= 100" in sql[0]
