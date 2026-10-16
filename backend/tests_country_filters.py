"""Validação dos filtros por países com jogos, sem dependência de bancos reais."""
from __future__ import annotations

from unittest.mock import patch
import sys
import types
sys.modules.setdefault("app.db", types.SimpleNamespace(app_engine=None, history_connection=lambda:None))

from app.services import country_activity_service as activity
from app.repositories import catalog_repository


class FakeScalars:
    def __init__(self, values):
        self.values = values
    def all(self):
        return self.values


class FakeResult:
    def __init__(self, values):
        self.values = values
    def scalars(self):
        return FakeScalars(self.values)


class FakeConnection:
    def __init__(self, values):
        self.values = values
        self.sql = None
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, statement):
        self.sql = str(statement)
        return FakeResult(self.values)


def test_only_countries_with_games_are_included():
    conn = FakeConnection(['Alemanha', ' INGLATERRA ', 'Áustria', None, '  '])
    countries = [
        {'id':1,'nome':'Alemanha'},
        {'id':2,'nome':'Inglaterra'},
        {'id':3,'nome':'França'},
        {'id':4,'nome':'Austria'},
    ]
    with patch.object(activity, 'history_connection', return_value=conn), patch.object(activity.time, 'time', return_value=123456):
        activity._countries_with_games_cached.cache_clear()
        result = activity.filter_countries_with_games(countries)
    assert [r['nome'] for r in result] == ['Alemanha', 'Inglaterra', 'Austria']
    assert 'DISTINCT pais' in conn.sql
    assert 'historico_jogos' in conn.sql
    activity._countries_with_games_cached.cache_clear()


def test_countries_without_games_do_not_appear():
    with patch.object(activity, '_countries_with_games_cached', return_value=frozenset()):
        assert activity.filter_countries_with_games([{'nome':'Brasil'}]) == []


def test_cached_country_activity_refreshes_next_minute():
    conn1 = FakeConnection(['Alemanha'])
    conn2 = FakeConnection(['Alemanha', 'França'])
    reads = iter([conn1,conn2])
    countries = [{'nome':'Alemanha'}, {'nome':'França'}]
    with patch.object(activity, 'history_connection', side_effect=lambda:next(reads)), patch.object(activity.time, 'time', side_effect=[60.0, 70.0, 121.0]):
        activity._countries_with_games_cached.cache_clear()
        first = activity.filter_countries_with_games(countries)
        cached = activity.filter_countries_with_games(countries)
        refreshed = activity.filter_countries_with_games(countries)
    assert len(first) == 1
    assert len(cached) == 1
    assert len(refreshed) == 2
    activity._countries_with_games_cached.cache_clear()


def test_catalog_management_remains_unfiltered():
    countries = [{'id':1,'nome':'Brasil'}, {'id':2,'nome':'França'}]
    with patch.object(catalog_repository, '_rows', return_value=countries), patch.object(
        activity, 'filter_countries_with_games', return_value=[countries[1]]
    ) as filter_fn:
        assert catalog_repository.list_countries() == countries
        filter_fn.assert_not_called()
        assert catalog_repository.list_countries(with_games=True) == [countries[1]]
        filter_fn.assert_called_once()
