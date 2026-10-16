"""Testes unitários: aba Liga deve analisar temporada EXATA, sem dependência de DB."""
from __future__ import annotations

import sys
import types

sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))

import pytest
from app.services import backtesting_service as b


def game(date, season, home, away, gh, ga, home_odd=None):
    return {
        'date': date, 'year': int(date[:4]), 'season': season,
        'season_key': b._season_key(season), 'home': home, 'away': away,
        'gh': gh, 'ga': ga, 'odds_source':'historico_odds', 'home_odd': home_odd, 'away_odd': 3.7,
        'draw_odd': 3.25, 'over25_odd': 1.85,
    }


SAMPLE = (
    game('2018-09-01', '2018/2019', 'A', 'B', 2, 1, 2.0),
    game('2019-01-01', '2018/2019', 'B', 'C', 1, 1, 1.8),
    game('2019-08-31', '2019/2020', 'A', 'C', 0, 3, 3.0),
    game('2020-01-05', '2019/2020', 'B', 'A', 0, 0, 2.3),
)


@pytest.fixture(autouse=True)
def patch_source(monkeypatch):
    monkeypatch.setattr(b, '_source', lambda comp, bucket: (
        SAMPLE, ['2019/2020', '2018/2019'], ['A', 'B', 'C'],
        {'status': 'ok', 'matched_games': 4, 'legacy_only_games': 0,
         'without_any_odds': 0, 'ambiguous_games': 0}, [], [],
    ))


def test_league_accepts_optional_season_and_aggregates_all_when_missing():
    result = b.evaluate({'competition_id': 1, 'tab': 'league', 'start_season': 'all'})
    assert result['games'] == 4
    assert result['start_season'] == 'all'
    assert result['league_overview']['games'] == 4
    assert result['league_comparison']['total_leagues'] == 1


def test_league_rejects_unknown_specific_season():
    with pytest.raises(ValueError, match='temporada|Temporada'):
        b.evaluate({'competition_id': 1, 'tab': 'league', 'start_season': '2020/2021'})


def test_league_exact_season_and_full_market_cards():
    result = b.evaluate({'competition_id': 1, 'tab': 'league', 'start_season': '2018/2019', 'years': 1})
    assert result['tab'] == 'league'
    assert result['games'] == 2
    assert result['scores']['total'] == 2
    assert len(result['markets']) == 12
    assert result['markets']['back_home']['wins'] == 1
    assert result['markets']['draw']['wins'] == 1
    assert result['league_overview'] == {
        'games': 2, 'goals': 5, 'avg_goals': 2.5,
        'home_wins': 1, 'draws': 1, 'away_wins': 0,
        'home_rate': 50, 'draw_rate': 50, 'away_rate': 0,
        'over25_rate': 50, 'btts_rate': 100,
    }
    assert [y['year'] for y in result['annual']] == [2018, 2019]
    assert sum(y['values']['back_home']['games'] for y in result['annual']) == 2
    assert sum(y['values']['back_home']['settled'] for y in result['annual']) == 2
    assert all(g['season'] == '2018/2019' for g in result['odds_audit']['games']['back_home'])
    assert result['odds_suggestions']['markets'][0]['reference_games'] == 2


def test_league_ignores_stale_club_opponent_division_format_filters():
    result = b.evaluate({
        'competition_id': 1, 'tab': 'league', 'start_season': '2019/2020',
        'club': 'A', 'opponent': 'B', 'divisao': 'inexistente', 'formato': 'inexistente',
    })
    assert result['games'] == 2
    assert result['club'] == ''
    assert result['opponent'] is None
    assert result['divisao'] is None and result['formato'] is None
    assert result.get('head_to_head') is None
    assert [y['year'] for y in result['annual']] == [2019, 2020]
    assert result['league_overview']['away_wins'] == 1
    assert result['league_overview']['goals'] == 3


def test_league_compare_mode_without_competition(monkeypatch):
    monkeypatch.setattr(b, '_competition_catalog', lambda country_id=None, competition_id=None: [
        {'id': 1, 'competition': 'Liga A', 'country': 'Pais 1', 'country_id': 1},
        {'id': 2, 'competition': 'Liga B', 'country': 'Pais 2', 'country_id': 2},
    ])
    monkeypatch.setattr(b, '_competition', lambda comp_id: {
        1: {'id': 1, 'competition': 'Liga A', 'country': 'Pais 1', 'country_id': 1},
        2: {'id': 2, 'competition': 'Liga B', 'country': 'Pais 2', 'country_id': 2},
    }[comp_id])
    from app.services import league_fast_service as fast
    monkeypatch.setattr(fast, 'grouped_games', lambda country,competition,season,divisao,formato,catalog: [
        {**g, 'competition_id': 1 if i < 2 else 2, 'competition': 'Liga A' if i < 2 else 'Liga B',
         'country': 'Pais 1' if i < 2 else 'Pais 2', '_weight': 1}
        for i, g in enumerate(SAMPLE)
    ])
    monkeypatch.setattr(fast, 'recent_games', lambda *args,**kwargs: [])
    result = b.evaluate({'tab': 'league', 'start_season': 'all', 'use_odds': False})
    assert result['games'] == 4
    assert result['league_comparison']['total_leagues'] == 2
    home = next(m for m in result['league_comparison']['markets'] if m['key'] == 'back_home')
    assert {item['competition'] for item in home['items']} == {'Liga A', 'Liga B'}


def test_league_zero_sample_metrics_avoid_division_by_zero():
    result = b._league_overview([])
    assert result['games'] == 0
    assert result['avg_goals'] is None
    assert result['home_rate'] is None
    assert result['btts_rate'] is None
