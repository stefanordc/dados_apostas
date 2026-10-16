"""Regressão de filtro continente sem conexão ao banco."""
import sys
import types
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))

import pytest
from app.services import continent_service as c
from app.services import league_catalog_service as l
from app.services import league_fast_service as f
from app.services import club_statistics_service as club


def test_continent_assignments_and_unknown():
    assert c.for_country('Brasil') == 'América do Sul'
    assert c.for_country('América do Sul') == 'América do Sul'
    assert c.for_country('Estados Unidos') == 'América do Norte'
    assert c.for_country('Alemanha') == 'Europa'
    assert c.for_country('Austrália') == 'Oceania'
    assert c.for_country('País desconhecido') == 'Não informado'
    assert c.for_country('Brasil', 'Europa') == 'Europa'  # coluna salva tem preferência


def test_history_catalog_filters_continent(monkeypatch):
    monkeypatch.setattr(l, 'catalog', lambda: [
        {'country': 'Brasil','continent': 'América do Sul','competition': 'Brasileiro'},
        {'country': 'América do Sul','continent': 'América do Sul','competition': 'Libertadores'},
        {'country': 'Inglaterra','continent': 'Europa','competition': 'Inglês'},
    ])
    assert len(l.selected(continent='América do Sul')) == 2
    assert [r['competition'] for r in l.selected(continent='Europa')] == ['Inglês']
    with pytest.raises(ValueError, match='não pertence'):
        l.selected('Inglaterra',continent='América do Sul')


def test_sql_scope_restricts_continent_and_preserves_period():
    sql, params = f._scope(None,None,None,None,None,set(),2024,2025,
                            ('Brasil','Argentina','América do Sul'))
    assert 'pais = ANY(:continent_countries)' in sql
    assert params['continent_countries'] == ['Brasil','Argentina','América do Sul']
    assert params['year_start'] == '2024-01-01'
    assert params['year_end_exclusive'] == '2026-01-01'


def test_club_fast_sql_uses_continent_countries_before_aggregation():
    sql, params = club._fast_ranking_sql(allowed=('Brasil','Argentina'))
    assert 'BTRIM(pais::text) = ANY(:continent_countries)' in str(sql)
    assert params['continent_countries'] == ['Brasil','Argentina']
    assert 'HAVING COUNT(*)>500' in str(sql)
    assert "INTERVAL '3 years')>=100" in str(sql)


def test_continent_options_from_catalog(monkeypatch):
    monkeypatch.setattr(l, 'catalog', lambda: [
        {'id': 1, 'country': 'Brasil', 'continent': 'América do Sul', 'competition': 'Brasileiro'},
        {'id': 2, 'country': 'América do Sul', 'continent': 'América do Sul', 'competition': 'Libertadores'},
        {'id': 3, 'country': 'Inglaterra', 'continent': 'Europa', 'competition': 'Inglês'},
    ])
    options = l.choices()
    assert {c['nome'] for c in options['continents']} == {'Europa','América do Sul'}
    assert len(options['countries']) == 3
    assert next(c['continente'] for c in options['competitions'] if c['nome']=='Brasileiro') == 'América do Sul'
