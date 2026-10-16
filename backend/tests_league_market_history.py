"""Cliques nos rankings da aba Liga, com histórico anual independente do filtro principal."""
import sys
import types
from datetime import date
from unittest.mock import patch

sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))
from app.services import backtesting_service as service
from app.services import league_fast_service
from app.services import league_bulk_odds_service


def grouped(year, gh, ga, count):
    return {
        'date': f'{year}-01-01', 'year': year, 'month': f'{year}-01',
        'season': str(year), 'season_key': (year, year),
        'competition_id': 1, 'competition': 'MLS', 'country': 'Estados Unidos',
        'divisao': '1', 'formato': 'Liga',
        'gh': gh, 'ga': ga, '_weight': count,
        'home': '', 'away': '', 'home_odd': None, 'away_odd': None,
        'draw_odd': None, 'over25_odd': None, 'odds_source': None,
    }


def test_yearly_market_history_uses_10_calendar_years_and_real_game_weights(monkeypatch):
    current = date.today().year
    observed = {}
    monkeypatch.setattr('app.services.league_catalog_service.selected', lambda country, competition: [
        {'id': 1, 'country': country, 'competition': competition}
    ])

    def mock_grouped(country, comp, season, divisao, formato, catalog, year_from=None, year_to=None):
        observed.update(country=country, competition=comp, season=season, divisao=divisao, formato=formato,
                        year_from=year_from, year_to=year_to)
        return [grouped(current - 1, 1, 0, 30), grouped(current - 1, 0, 0, 20),
                grouped(current, 2, 1, 5)]
    monkeypatch.setattr(league_fast_service, 'grouped_games', mock_grouped)
    result = service.league_market_history({
        'country':'Estados Unidos','competition':'MLS','market':'back_home',
        'divisao':'1', 'formato':'Liga','use_odds':False,
    })
    assert observed == {
        'country':'Estados Unidos','competition':'MLS','season':'all',
        'divisao':'1','formato':'Liga','year_from':current-9,'year_to':current,
    }
    assert len(result['years']) == 10
    assert result['years'][0]['year'] == current-9 and result['years'][0]['win_rate'] is None
    assert result['years'][-2]['games'] == 50
    assert result['years'][-2]['win_rate'] == 60.0
    assert result['years'][-1]['win_rate'] == 100.0
    assert result['total'] == {'games':55,'wins':35,'losses':20,'win_rate':63.64}
    assert all(row['profit'] is None and row['roi'] is None for row in result['years'])


def test_each_market_keeps_its_own_definition(monkeypatch):
    current = date.today().year
    monkeypatch.setattr('app.services.league_catalog_service.selected', lambda c,k:[{'id':1,'country':c,'competition':k}])
    monkeypatch.setattr(league_fast_service, 'grouped_games', lambda *args,**kwargs: [grouped(current,4,0,8),grouped(current,1,0,2)])
    result = service.league_market_history({'country':'Brasil','competition':'Brasileiro',
                                            'market':'lay_big_home','use_odds':False})
    assert result['years'][-1]['games'] == 10
    assert result['years'][-1]['wins'] == 2
    assert result['years'][-1]['win_rate'] == 20.0


def test_with_odds_uses_price_source_and_does_not_invent_lay_profit(monkeypatch):
    current = date.today().year
    monkeypatch.setattr('app.services.league_catalog_service.selected', lambda c,k:[{'id':1,'country':c,'competition':k}])
    observed = {}
    def fake_load(country, competition, catalog, year_from=None, year_to=None):
        observed.update(year_from=year_from,year_to=year_to)
        return [dict(grouped(current,2,1,1),home_odd=2.2,lay_home_odd=None),
                dict(grouped(current,1,2,1),home_odd=2.2,lay_home_odd=None)], {}
    monkeypatch.setattr(league_bulk_odds_service, 'load', fake_load)
    # A fonte real não envia grupos, mas este mock valida as mesmas regras de liquidação.
    result = service.league_market_history({'country':'Brasil','competition':'Brasileiro',
                                            'market':'lay_home','use_odds':True})
    row = result['years'][-1]
    assert observed == {'year_from':current-9,'year_to':current}
    assert row['games']==2 and row['wins']==1 and row['win_rate']==50.0
    assert row['profit'] is None and row['roi'] is None


def test_unknown_market_is_rejected_before_database_access():
    import pytest
    with pytest.raises(ValueError, match='Mercado inválido'):
        service.league_market_history({'country':'Brasil','competition':'Brasileiro','market':'xyz'})
