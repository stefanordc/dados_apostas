"""Agregados da aba Estatísticas · Gols e Resultado."""
import sys
import types
from datetime import date, timedelta

sys.modules.setdefault(
    'app.db',
    types.SimpleNamespace(app_engine=None, history_engine=None, history_connection=lambda: None),
)

from app.services import goal_timeline_service as timeline
from app.services import statistics_goals_service as goals


def game(game_id, goals=(2, 1)):
    return {
        'id_jogo': game_id,
        'data': date.today() - timedelta(days=1),
        'casa': 'Casa',
        'fora': 'Fora',
        'gh': goals[0],
        'ga': goals[1],
        'pais': 'Brasil',
        'campeonato': 'Série A',
    }


def event(minute, score, order=1):
    return {'minute': minute, 'score': score, 'score_home': None, 'score_away': None, 'order': order}


def test_map_band_folds_first_half_stoppage():
    assert goals._map_band('45+') == '31-45'
    assert goals._map_band('90+') == '90+'
    assert goals._map_band('16-30') == '16-30'


def test_home_open_win_equalize_and_bands(monkeypatch):
    g1 = game(1, goals=(2, 1))
    g2 = game(2, goals=(1, 2))
    g3 = game(3, goals=(0, 0))
    events = {
        '1': [event('10', '1-0'), event('70', '2-0'), event('80', '2-1')],
        '2': [event('20', '0-1'), event('40', '1-1'), event('88', '1-2')],
        '3': [],
    }

    def fake_fetch(ids):
        return events, None

    monkeypatch.setattr(timeline, 'fetch', fake_fetch)
    monkeypatch.setattr(goals, '_load_games', lambda *a, **k: ([g1, g2, g3], None))
    report = goals.analyze({})
    assert report['valid_games'] == 3
    cards = {c['key']: c for c in report['cards']}
    assert cards['home_opens']['count'] == 1
    assert cards['home_opens']['value'] == round(100 / 3, 2)
    assert cards['home_opens_wins']['value'] == 100
    assert cards['away_opens']['count'] == 1
    assert cards['away_opens_wins']['value'] == 100
    assert cards['away_opens_equalized']['value'] == 100
    assert sum(b['count'] for b in report['minute_bands']) == 6
    assert next(b for b in report['minute_bands'] if b['label'] == '0-15')['count'] == 1
    assert '45+' not in {b['label'] for b in report['minute_bands']}


def test_home_comeback_after_open(monkeypatch):
    g = game(9, goals=(1, 2))
    events = {'9': [event('5', '1-0'), event('50', '1-1'), event('85', '1-2')]}
    monkeypatch.setattr(timeline, 'fetch', lambda ids: (events, None))
    monkeypatch.setattr(goals, '_load_games', lambda *a, **k: ([g], None))
    report = goals.analyze({})
    cards = {c['key']: c for c in report['cards']}
    assert cards['home_opens_equalized']['value'] == 100
    assert cards['home_opens_overturned']['value'] == 100
    assert cards['home_opens_wins']['value'] == 0
