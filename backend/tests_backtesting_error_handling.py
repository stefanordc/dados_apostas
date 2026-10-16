"""Regressão: erro real do backend fica registrado e sem segredo na UI."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import backtesting as route
from app.services import backtesting_service as service


def test_evaluate_500_creates_diagnostic_reference(monkeypatch, tmp_path):
    for handler in list(route._logger.handlers):
        route._logger.removeHandler(handler)
        handler.close()
    target = tmp_path / 'logs' / 'backtesting_errors.log'
    monkeypatch.setattr(route, '_ERROR_LOG', target)

    def raise_db_error(_payload):
        raise RuntimeError('Falha SQL simulada')

    monkeypatch.setattr(service, 'evaluate', raise_db_error)
    with pytest.raises(HTTPException) as error:
        route.evaluate(route.BacktestingRequest(tab='league', use_odds=False))
    assert error.value.status_code == 500
    assert 'ID ' in error.value.detail
    assert 'Falha SQL simulada' not in error.value.detail
    assert target.is_file()
    log = target.read_text(encoding='utf-8')
    assert 'Falha SQL simulada' in log
    assert 'POST /api/backtesting/evaluate' in log
    for handler in list(route._logger.handlers):
        route._logger.removeHandler(handler)
        handler.close()


def test_general_league_does_not_query_hidden_panels(monkeypatch):
    from app.services import league_fast_service as fast

    def forbidden(*args, **kwargs):
        raise AssertionError('Não deve executar consulta oculta')

    monkeypatch.setattr(service, '_historical_trends', forbidden)
    monkeypatch.setattr(fast, 'recent_games', forbidden)
    row = {'date':'2025-01-01', 'year':2025, 'season':'2025', 'home':'', 'away':'',
           'competition_id':1, 'competition':'Brasileiro', 'country':'Brasil',
           'gh':2, 'ga':1, '_weight':23, 'home_odd':None, 'away_odd':None,
           'draw_odd':None, 'over25_odd':None}
    result = service._evaluate_fast_leagues([row], {}, {}, 'all', None, None,
                                            catalog=[{'id':1, 'country':'Brasil', 'competition':'Brasileiro'}],
                                            include_legacy_panels=False)
    assert result['games'] == 23
    assert result['league_comparison']['total_leagues'] == 1
    assert result['historical_trends'] is None
    assert result['odds_audit'] is None
