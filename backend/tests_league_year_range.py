"""Regressões: intervalo de anos pelo calendário, não rótulo da temporada."""
import sys
import types
import pytest
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))
from app.services import backtesting_service as b
from app.services import league_fast_service as f


def game(when, season, comp, gh, ga):
    return {
        'date': when, 'year': int(when[:4]), 'season': season,
        'season_key': b._season_key(season), 'home': 'Casa', 'away': 'Fora',
        'gh': gh, 'ga': ga, 'odds_source': 'historico_odds',
        'home_odd': 2.0, 'away_odd': 2.5, 'draw_odd': 3.1, 'over25_odd': 1.9,
        'competition_id': comp, 'competition': 'Liga Europa' if comp == 1 else 'Liga Brasil',
        'country': 'Europa' if comp == 1 else 'Brasil',
    }


GAMES = (
    game('2023-12-29','2023/2024',1,1,0),
    game('2024-01-15','2023/2024',1,2,0),
    game('2024-05-10','2024',2,1,1),
    game('2024-09-07','2024/2025',1,0,2),
    game('2025-01-15','2024/2025',1,0,0),
)


@pytest.fixture(autouse=True)
def source(monkeypatch):
    monkeypatch.setattr(b,'_source',lambda comp,bucket: (
        GAMES,['2023/2024','2024/2025','2024'],['Casa','Fora'],
        {'status':'ok','matched_games':5,'ambiguous_games':0,'legacy_only_games':0,'without_any_odds':0},[],[]
    ))


def test_2024_uses_match_date_not_season_start():
    result=b.evaluate({'tab':'league','competition_id':1,'year_from':2024,'year_to':2024,'use_odds':False})
    assert result['games']==3
    assert result['league_overview']['draws']==1
    assert result['year_from']==2024 and result['year_to']==2024
    assert result['markets']['back_home']['wins']==1
    assert set(g['date'][:4] for g in result['odds_audit']['games']['back_home'])=={'2024'}


def test_boundary_filters_can_be_independently_omitted():
    assert b.evaluate({'tab':'league','competition_id':1,'year_from':2025,'use_odds':False})['games']==1
    assert b.evaluate({'tab':'league','competition_id':1,'year_to':2023,'use_odds':False})['games']==1
    assert b.evaluate({'tab':'league','competition_id':1,'use_odds':False})['games']==5


def test_reversed_years_rejected():
    with pytest.raises(ValueError,match='maior'):
        b.evaluate({'tab':'league','competition_id':1,'year_from':2025,'year_to':2024})


def test_global_fast_uses_years_without_season_logic(monkeypatch):
    catalog=[{'id':1,'competition':'Liga Europa','country':'Europa','country_id':1},
             {'id':2,'competition':'Liga Brasil','country':'Brasil','country_id':2}]
    monkeypatch.setattr(b, '_competition_catalog', lambda country_id=None,competition_id=None:catalog)
    def mock_group(country,competition,season,division,format_,rows,year_from=None,year_to=None):
        assert season=='all' and year_from==2024 and year_to==2024
        return [{**g,'_weight':1} for g in GAMES if g['year']==2024]
    monkeypatch.setattr(f,'grouped_games',mock_group)
    monkeypatch.setattr(f,'recent_games',lambda *args,**kwargs:[])
    result=b.evaluate({'tab':'league','year_from':2024,'year_to':2024,'use_odds':False})
    assert result['games']==3
    assert result['league_comparison']['total_leagues']==2
    assert result['year_from']==2024 and result['year_to']==2024


def test_fast_scope_past_and_future_bounds():
    clauses,params=f._scope(None,None,None,None,None,{'data'},2023,2025)
    assert 'data >= CAST(:year_start AS DATE)' in clauses
    assert 'data < CAST(:year_end_exclusive AS DATE)' in clauses
    assert params=={'year_start':'2023-01-01','year_end_exclusive':'2026-01-01'}


def test_other_tabs_ignore_year_range_fields():
    result=b.evaluate({'tab':'mo_home','competition_id':1,'year_from':2024,'year_to':2024,'use_odds':False})
    assert result['games']==5
