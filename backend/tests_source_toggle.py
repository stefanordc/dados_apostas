"""Regressões: modos com/s/odds em todas as abas, independentes de conexão."""
import sys
import types
from datetime import date

sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))
import pytest
from app.services import backtesting_service as b


def example(when, home, away, gh, ga, source, price=None, h_div='1', o_div='2'):
    return {
        'date': when, 'year': int(when[:4]), 'season': '2025/2026',
        'season_key': (2025, 2026), 'home': home, 'away': away,
        'gh': gh, 'ga': ga,
        'divisao': o_div if source == 'historico_odds' else h_div,
        'history_divisao': h_div, 'formato': 'Liga', 'history_formato': 'Liga',
        'home_odd': price, 'away_odd': 3.0, 'draw_odd': 3.2, 'over25_odd': 1.9,
        'odds_source': source,
    }


DATA = (
    example('2025-08-01', 'A', 'B', 2, 0, 'historico_odds', 2.1),
    example('2025-09-01', 'B', 'A', 1, 1, 'odds_jogos', 2.5),
    example('2025-10-01', 'A', 'C', 0, 1, None, None),
    example('2025-11-01', 'A', 'B', 2, 1, 'historico_odds', 1.8),
)


@pytest.fixture(autouse=True)
def mock_source(monkeypatch):
    monkeypatch.setattr(b, '_source', lambda comp, bucket: (
        DATA, ['2025/2026'], ['A', 'B', 'C'],
        {'status': 'ok', 'matched_games': 2, 'legacy_only_games': 1, 'ambiguous_games': 0,
         'without_any_odds': 1}, [], [],
    ))


def run_mode(use_odds, tab='league', **kwargs):
    return b.evaluate({'competition_id': 1, 'tab': tab, 'start_season': '2025/2026',
                       'use_odds': use_odds, **kwargs})


def test_only_confirmed_historico_odds_are_priced():
    got = run_mode(True)
    assert got['games'] == 2
    assert got['data_source'] == 'historico_odds'
    assert got['markets']['back_home']['wins'] == 2
    assert got['markets']['back_home']['settled'] == 2
    assert got['markets']['back_home']['profit'] == 190.0
    assert got['markets']['back_home']['stakes'] == 1.9
    assert got['odds_suggestions'] is not None
    assert got['odds_reconciliation'] is not None
    assert not got.get('historical_trends')
    assert all(row['date'] in ('2025-08-01', '2025-11-01') for row in got['odds_audit']['games']['back_home'])


def test_history_mode_ignores_all_quotes_even_legacy_and_retains_history_metadata():
    got = run_mode(False)
    assert got['games'] == 4
    assert got['data_source'] == 'historico_jogos'
    assert len(got['markets']) == 12
    home = got['markets']['back_home']
    assert (home['games'], home['wins'], home['losses'], home['rate']) == (4, 2, 2, 50)
    assert home['profit'] is None and home['stakes'] is None
    assert home['settled'] == 0 and home['avg_odd'] is None
    assert got['odds_reconciliation'] is None
    assert got.get('odds_suggestions') is None
    assert len(got['odds_audit']['games']['back_home']) == 4
    assert all(g['odd'] is None and g['profit'] is None and g['divisao'] == '1' for g in got['odds_audit']['games']['back_home'])
    assert got['historical_trends']['markets'][0]['total']['win_rate'] == 50
    assert got['historical_trends']['markets'][0]['posterior']['games'] == 2
    assert got['annual'][0]['values']['back_home']['settled'] == 0
    assert got['league_overview']['games'] == 4


def test_history_mode_ignores_stale_odd_filters():
    got = run_mode(False, mo_min=1000, mo_max=1001, over25_min=50, btts_max=100)
    assert got['markets']['back_home']['games'] == 4
    assert len(got['odds_audit']['games']['back_home']) == 4


def test_mode_switch_applies_to_each_tab_and_h2h():
    for tab in ('league','team','mo_home','mo_away','lay_home','lay_away',
                'lay_big_home','lay_big_away','scores'):
        extra = {} if tab=='league' else {'club':'A','opponent':'B'}
        with_prices = run_mode(True, tab, **extra)
        without_prices = run_mode(False, tab, **extra)
        assert len(with_prices['markets']) == 12, tab
        assert len(without_prices['markets']) == 12, tab
        assert with_prices['games'] <= without_prices['games'], tab
        assert all(x['profit'] is None for x in without_prices['markets'].values()), tab
        if tab not in ('league',):
            assert all(x['profit'] is None for x in without_prices['head_to_head']['markets'].values()), tab
        if tab == 'scores':
            assert with_prices['scores']['total'] < without_prices['scores']['total']


def test_history_audit_cumulative_wr_uses_all_prior_games():
    got = run_mode(False)
    audit = got['odds_audit']['games']['back_home']
    assert [r['date'] for r in audit] == ['2025-11-01','2025-10-01','2025-09-01','2025-08-01']
    assert [(r['cumulative_games'], r['cumulative_rate']) for r in audit] == [
        (4, 50), (3, round(100/3, 2)), (2, 50), (1, 100)
    ]


def test_historical_trends_never_make_financial_claims():
    res = run_mode(False)
    for entry in res['historical_trends']['markets']:
        assert set(entry['total']) == {'games','wins','losses','win_rate'}
        assert entry['initial']['games'] + entry['posterior']['games'] == entry['total']['games']
    assert res['has_odds'] is False


def test_rejects_non_boolean_mode():
    with pytest.raises(ValueError,match='seletor'):
        b.evaluate({'competition_id':1,'tab':'league','start_season':'2025/2026', 'use_odds':'false'})


def test_with_odds_must_not_fallback_to_legacy_market_prices(monkeypatch):
    from app.services.historico_odds_service import QUOTE_MAP
    # An old market quote exists in odds_jogos, but historico_odds has no quote for it.
    sample = dict(DATA[0], over25_odd=1.9,
                  historico_odds_quotes={field: None for field in QUOTE_MAP.values()})
    sample['historico_odds_quotes']['home_odd'] = 2.1
    monkeypatch.setattr(b, '_source', lambda comp, bucket: (
        (sample,), ['2025/2026'], ['A','B'], {'status':'ok'}, [], [],
    ))
    report = run_mode(True)
    assert report['markets']['back_home']['settled'] == 1
    assert report['markets']['over25']['settled'] == 0
    assert report['markets']['over25']['profit'] is None
    assert not report['odds_audit']['games']['over25']
