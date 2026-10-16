"""Regressões para indicações estatísticas de faixas de odds (sem banco)."""
import sys
import types
from datetime import date, timedelta

sys.modules['app.db'] = types.SimpleNamespace(app_engine=None, history_connection=lambda: None)
from app.services import backtesting_service as b

EMPTY_FILTERS = {k: (None, None) for k in ('mo', 'over05', 'over15', 'over25', 'under35', 'btts')}


def _games(count=70, home_price=2.0, win_share=0.7, lay_price=None):
    rows=[]
    for i in range(count):
        win = i % 10 < round(win_share * 10)
        rows.append({
            'date': (date(2025, 1, 1)+timedelta(days=i)).isoformat(),
            'year': 2025, 'season':'2024/2025','season_key':(2024,2025),
            'home':'Casa', 'away':'Visitante', 'odds_source':'historico_odds', 'gh':2 if win else 0, 'ga':0 if win else 1,
            'home_odd':home_price, 'away_odd':3.5, 'draw_odd':3.2,
            'over05_odd':1.12, 'over15_odd':1.55, 'over25_odd':2.0,
            'under35_odd':1.30, 'btts_odd':1.90,
            'lay_home_odd':lay_price, 'lay_big_home_odd':None,
        })
    return rows


def test_profitable_real_back_ranges_have_positive_training_and_later_roi():
    rows = _games()
    response = b._odds_suggestions(rows, EMPTY_FILTERS, '', 'any', ['back_home'])
    m = response['markets'][0]
    assert m['key'] == 'back_home'
    assert m['kind'] == 'observed_profit'
    assert m['quoted_games'] == 70
    assert m['suggestions']
    suggestion = m['suggestions'][0]
    assert suggestion['odd_min'] == suggestion['odd_max'] == 2.0
    assert suggestion['total']['games'] == 70
    assert suggestion['total']['wins'] == 49
    assert suggestion['total']['profit'] == 2800.0
    assert suggestion['total']['roi'] == 40.0
    assert suggestion['training']['roi'] > 0 and suggestion['validation']['roi'] > 0
    # O botão Aplicar faixa usa exatamente estes limites de preço no mesmo filtro de MO.
    filtered = dict(EMPTY_FILTERS, mo=(suggestion['odd_min'], suggestion['odd_max']))
    audit = b._audit_games(rows, filtered, '', 'any', ['back_home'])
    assert len(audit['games']['back_home']) == 40 # limite de linhas de conferência
    assert all(row['odd'] == 2.0 for row in audit['games']['back_home'])


def test_unprofitable_back_ranges_are_not_recommended():
    m = b._odds_suggestions(_games(win_share=0.2), EMPTY_FILTERS, '', 'any', ['back_home'])['markets'][0]
    assert m['kind'] == 'observed_profit'
    assert m['suggestions'] == []


def test_missing_lay_quotes_never_generate_profit():
    m = b._odds_suggestions(_games(win_share=0.2), EMPTY_FILTERS, '', 'any', ['lay_home'])['markets'][0]
    assert m['kind'] == 'historical_frequency'
    assert m['quoted_games'] == 0
    assert m['reference_label'].startswith('Odd Back')
    assert m['suggestions']
    for row in m['suggestions']:
        assert row['total']['profit'] is None
        assert row['total']['roi'] is None
        assert row['total']['fair_lay_odd'] == 5.0 # 80% verdes => odd 5 para equilíbrio (sem margem)


def test_real_lay_quote_and_liability_used():
    m = b._odds_suggestions(_games(win_share=0.2,lay_price=4.0), EMPTY_FILTERS, '', 'any', ['lay_home'])['markets'][0]
    assert m['kind'] == 'observed_profit'
    assert m['quoted_games'] == 70
    assert m['suggestions']
    assert m['suggestions'][0]['total']['profit'] > 0
    assert m['suggestions'][0]['total']['roi'] > 0
    # Lay Green com odd 4.0 rende R$ 33,33; Lay Red perde R$ 100 (responsabilidade).
    assert round(m['suggestions'][0]['total']['profit'],2) == round(56*33.33-14*100,2)


def test_over05_and_under35_odds_filter_restricts_only_own_market():
    a = _games(count=30)
    b_games = [dict(g, over05_odd=1.90, under35_odd=3.0) for g in a]
    both = a + b_games
    filters = dict(EMPTY_FILTERS, over05=(1.0,1.2), under35=(2.50,3.50))
    assert b._summary(both,'over05','', 'any',filters)['games'] == 30
    assert b._summary(both,'under35','', 'any',filters)['games'] == 30
    assert b._summary(both,'back_home','', 'any',filters)['games'] == 60


def test_insufficient_history_does_not_claim_a_strategy():
    m = b._odds_suggestions(_games(count=10), EMPTY_FILTERS, '', 'any',['back_home'])['markets'][0]
    assert not m['suggestions']
    assert m['quoted_games']==10


def test_date_order_is_chronological_and_filters_apply_before_test_split():
    games = list(reversed(_games()))
    response=b._odds_suggestions(games, EMPTY_FILTERS, '', 'any', ['back_home'])
    row = response['markets'][0]['suggestions'][0]
    assert row['period_initial'] == min(g['date'] for g in games)
    assert row['period_final'] == max(g['date'] for g in games)
    after = b._odds_suggestions(games, dict(EMPTY_FILTERS,mo=(2.01,3.0)), '', 'any', ['back_home'])
    assert after['markets'][0]['suggestions'] == []


def test_evaluate_places_strategy_suggestions_in_same_market_as_audit_and_h2h():
    source=b._source
    try:
        games=_games()
        b._source=lambda competition_id,bucket:(tuple(games),['2024/2025'],['Casa','Visitante'],{'status':'ok'},[],[])
        report=b.evaluate({'competition_id':1,'tab':'mo_home','club':'Casa','opponent':'Visitante', 'start_season':'2024/2025'})
        assert report['odds_suggestions']['default_market']=='back_home'
        assert [x['key'] for x in report['odds_suggestions']['markets']]==['back_home']
        assert [x['key'] for x in report['odds_audit']['markets']]==['back_home']
        report_all=b.evaluate({'competition_id':1,'tab':'team','club':'Casa','opponent':'Visitante'})
        assert len(report_all['odds_suggestions']['markets'])==12
        assert len(report_all['markets'])==12
        report_lay=b.evaluate({'competition_id':1,'tab':'lay_big_home','club':'Casa'})
        assert report_lay['odds_suggestions']['markets'][0]['kind']=='historical_frequency'
        assert report_lay['odds_audit']['default_market']=='lay_big_home'
    finally:
        b._source=source
