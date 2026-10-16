"""Regressões do carregamento rápido de seletores, sem acessar bancos reais."""
from __future__ import annotations

import pytest
from app.services import backtesting_filter_service as fast
from app.services import backtesting_service


class FakeResult:
    def __init__(self, rows):
        self.rows = rows
    def __iter__(self):
        return iter(self.rows)
    def mappings(self):
        return self
    def first(self):
        return self.rows[0] if self.rows else None
    def one(self):
        return self.rows[0]
    def all(self):
        return self.rows


class FakeConn:
    def __init__(self, rows, events):
        self.rows = rows
        self.events = events
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, statement, params=None):
        sql = str(statement)
        self.events.append(sql)
        if 'JOIN' in sql and 'campeonatos' in sql:
            return FakeResult([{'country':'Brasil','competition':'Brasileirão'}])
        if 'information_schema.columns' in sql:
            return FakeResult([('pais',),('campeonato',),('divisao',),('formato',)])
        if 'array_agg' in sql:
            return FakeResult([self.rows])
        if 'SELECT DISTINCT' in sql and 'historico_odds' in sql:
            return FakeResult([{'divisao':'1','formato':'Liga'}])
        return FakeResult([])


@pytest.fixture
def fixtures(monkeypatch):
    events=[]
    rows={'seasons':['2025/26','2024'], 'homes':['Atlético-MG','Flamengo'],
          'aways':['Cruzeiro','Flamengo'], 'divisions':['2'], 'formats':['Copa'],
          'pairs':['2\x1fCopa']}
    conn=FakeConn(rows,events)
    monkeypatch.setattr(fast,'app_engine',type('Engine',(),{'connect':lambda self:conn})())
    monkeypatch.setattr(fast,'history_connection',lambda:conn)
    monkeypatch.setattr(fast,'load_mappings',lambda cid:{fast.normalize_name('Atlético-MG'):'Atlético Mineiro'})
    fast.clear_cache()
    yield events
    fast.clear_cache()


def test_off_mode_never_queries_historico_odds(fixtures):
    result=fast.options(123,False)
    assert result['seasons']==['2025/2026','2024']
    assert result['clubs']==['Atlético Mineiro','Cruzeiro','Flamengo']
    assert result['divisions']==['2']
    assert result['formats']==['Copa']
    assert not any('historico_odds' in query for query in fixtures)
    assert not any('gols_casa' in query and 'SELECT id' in query for query in fixtures)


def test_on_mode_merges_only_distinct_odds_metadata(fixtures):
    result=fast.options(123,True)
    assert result['divisions']==['1','2']
    assert result['formats']==['Copa','Liga']
    assert {'divisao':'1','formato':'Liga'} in result['division_formats']
    assert any('SELECT DISTINCT' in q and 'historico_odds' in q for q in fixtures)
    assert not any('odd_casa' in q for q in fixtures)


def test_options_cache_avoids_repeated_database_queries(fixtures,monkeypatch):
    monkeypatch.setattr(fast.time,'time',lambda:1200)
    fast.options(123,False)
    amount=len(fixtures)
    fast.options(123,False)
    assert len(fixtures)==amount
    monkeypatch.setattr(fast.time,'time',lambda:1320)
    fast.options(123,False)
    assert len(fixtures)>amount


def test_current_router_service_delegates_to_light_source(fixtures):
    result=backtesting_service.options(123,False)
    assert result['seasons']==['2025/2026','2024']
