"""Regras novas: todas as ligas do histórico, não apenas campeonatos do cadastro ELO."""
import sys
import types
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_connection=lambda: None))

import pytest
from app.services import league_catalog_service as cat
from app.services import backtesting_service as back
from app.services import league_fast_service as fast
from app.services import backtesting_filter_service as filt

NAMES = [
    'Alemão', 'Argentino', 'Austríaco', 'Brasileiro', 'Dinamarquês',
    'Espanhol', 'Francês', 'Holandês', 'Inglês', 'Italiano', 'Libertadores',
    'MLS', 'Norueguês', 'Português', 'Recopa Sul-Americana', 'Sueco',
    'Sul-Americana', 'Turco',
]
COUNTRIES = {
    'Alemão':'Alemanha','Argentino':'Argentina','Austríaco':'Áustria',
    'Brasileiro':'Brasil','Dinamarquês':'Dinamarca','Espanhol':'Espanha',
    'Francês':'França','Holandês':'Holanda','Inglês':'Inglaterra',
    'Italiano':'Itália','Libertadores':'América do Sul','MLS':'Estados Unidos',
    'Norueguês':'Noruega','Português':'Portugal',
    'Recopa Sul-Americana':'América do Sul','Sueco':'Suécia',
    'Sul-Americana':'América do Sul','Turco':'Turquia',
}


class Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def all(self): return self.rows
    def __iter__(self): return iter(self.rows)


class Connection:
    def __init__(self, source): self.source = source
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None):
        if self.source == 'history':
            if 'information_schema.columns' in str(sql):
                return Result([('pais',),('campeonato',)])
            assert 'DISTINCT' in str(sql).upper()
            return Result([{'country':COUNTRIES[name], 'competition':name} for name in NAMES])
        assert 'campeonatos' in str(sql)
        # Only nine leagues are present in the separate ELO catalog.
        return Result([{'id':i, 'country':COUNTRIES[name], 'competition':name}
                       for i,name in enumerate(NAMES[:9], 1)])


@pytest.fixture
def all_catalog(monkeypatch):
    cat.clear_cache()
    monkeypatch.setattr(cat, 'history_connection', lambda: Connection('history'))
    monkeypatch.setattr(cat, 'app_engine', types.SimpleNamespace(connect=lambda: Connection('app')))
    return cat.catalog()


def test_18_clubs_with_missing_elo_catalog_are_still_included(all_catalog):
    assert len(all_catalog) == 18
    assert {r['competition'] for r in all_catalog} == set(NAMES)
    assert next(x for x in all_catalog if x['competition']=='MLS')['app_competition_id'] is None
    assert next(x for x in all_catalog if x['competition']=='Alemão')['app_competition_id'] == 1
    options = cat.choices()
    assert options['total'] == 18
    assert len(options['competitions']) == 18


def test_country_and_single_competition_from_history(all_catalog):
    assert [row['competition'] for row in cat.selected(country='Brasil')] == ['Brasileiro']
    assert [row['competition'] for row in cat.selected(competition='MLS')] == ['MLS']
    assert {row['competition'] for row in cat.selected(country='América do Sul')} == {
        'Libertadores','Recopa Sul-Americana','Sul-Americana'
    }
    with pytest.raises(ValueError,match='Campeonato'):
        cat.selected(country='Brasil',competition='MLS')


def test_all_history_competitions_appear_in_comparison(all_catalog,monkeypatch):
    monkeypatch.setattr(cat, 'catalog', lambda: all_catalog)
    def fake_groups(country, competition, season, division, format_, catalog):
        assert len(catalog) in (1, 18)
        return [{
            'date':'2025-01-01','year':2025,'season':'2025','season_key':(2025,2025),
            'home':'','away':'','gh':2,'ga':1, 'competition_id':c['id'],
            'competition':c['competition'],'country':c['country'],
            'divisao':None,'formato':None,'_weight':15,
            'home_odd':None,'away_odd':None,'draw_odd':None,'over25_odd':None,'odds_source':None,
        } for c in catalog if (not country or c['country']==country) and
          (not competition or c['competition']==competition)]
    monkeypatch.setattr(fast,'grouped_games',fake_groups)
    monkeypatch.setattr(fast,'recent_games',lambda *args,**kwargs: [])
    result = back.evaluate({'tab':'league','use_odds':False,'use_history_catalog':True})
    assert result['games'] == 18 * 15
    assert result['league_comparison']['total_leagues'] == 18
    for market in result['league_comparison']['markets']:
        assert len(market['items']) == 18
    solo = back.evaluate({'tab':'league','use_odds':False,'use_history_catalog':True,
                          'league_country':'Brasil','league_competition':'Brasileiro'})
    assert solo['league_comparison']['total_leagues'] == 1
    assert solo['games'] == 15


def test_league_options_history_uses_names_and_no_elo_ids(all_catalog,monkeypatch):
    from app.services import league_fast_service
    monkeypatch.setattr(league_fast_service,'options',lambda country,comp:{
        'seasons':['2025'],'divisions':['1'],'formats':['Liga'],
        'division_formats':[{'divisao':'1','formato':'Liga'}]
    })
    filt.clear_cache()
    out = filt.league_options(None,None,False,'Brasil','Brasileiro')
    assert out['seasons'] == ['2025']
    assert out['divisions'] == ['1']
