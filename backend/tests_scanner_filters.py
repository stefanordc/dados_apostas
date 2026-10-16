"""Filtros dinâmicos da tabela public.odds: sem conexão real com o banco."""
import sys
import types
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None, history_engine=None, history_connection=lambda: None))

from app.services import market_scanner_service as scanner
from app.routers.analysis_v3 import MarketScan
import pytest


ROWS = [
    {'pais':'Brasil','campeonato':'Brasileiro','divisao':'1','formato':'Liga','continente':None},
    {'pais':'Brasil','campeonato':'Brasileiro','divisao':'2','formato':'Liga','continente':None},
    {'pais':'Brasil','campeonato':'Brasileiro','divisao':'1','formato':'Liga','continente':None},
    {'pais':'Inglaterra','campeonato':'Inglês','divisao':'1','formato':'Liga','continente':None},
    {'pais':'América do Sul','campeonato':'Libertadores','divisao':None,'formato':'Copa','continente':None},
    {'pais':'Japão','campeonato':'Japonês','divisao':'1','formato':'Liga','continente':None},
]


def test_combinations_are_distinct_and_include_mapped_continents():
    combos=scanner._normalize_filter_rows(ROWS)
    assert len(combos)==5
    assert next(c for c in combos if c['country']=='Brasil')['continent']=='América do Sul'
    assert next(c for c in combos if c['country']=='Inglaterra')['continent']=='Europa'
    assert next(c for c in combos if c['competition']=='Libertadores')['continent']=='América do Sul'
    assert next(c for c in combos if c['country']=='Japão')['continent']=='Ásia'


def test_unknown_country_is_not_misclassified():
    combos=scanner._normalize_filter_rows([{'pais':'Planeta X','campeonato':'Z','divisao':'','formato':''}])
    assert combos[0]['continent']=='Não informado'


def test_continent_country_restriction():
    catalog={'combinations':scanner._normalize_filter_rows(ROWS)}
    assert scanner._continent_countries('Europa',catalog)==['Inglaterra']
    assert scanner._continent_countries('América do Sul',catalog)==['América do Sul','Brasil']
    with pytest.raises(ValueError,match='Continente inválido'):
        scanner._continent_countries('Supercontinente',catalog)


def test_optional_scanner_filter_model():
    default=MarketScan(group='over_ht')
    assert default.continent is None and default.division is None and default.format is None
    selected=MarketScan(group='mo_ft',continent='Europa',country='Inglaterra',
                        competition='Inglês',division='1',format='Liga')
    assert selected.country=='Inglaterra' and selected.format=='Liga'


class Result:
    def mappings(self):return self
    def __iter__(self):return iter([{'data':'2026-03-01','pais':'Brasil','campeonato':'Brasileiro',
                              'gols_casa':2,'gols_fora':0,'jogo_id':'1','odd_casa_ft':2.2}])
class Connection:
    def __init__(self):self.statement='';self.params={}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execution_options(self,**kwargs):return self
    def execute(self,statement,params):
        self.statement=str(statement)
        self.params=params
        return Result()
class Engine:
    def __init__(self):self.connection=Connection()
    def connect(self):return self.connection


def test_analyze_applies_all_dimensions_in_sql(monkeypatch):
    engine=Engine()
    monkeypatch.setattr(scanner,'_source',lambda:(engine,{'data','pais','campeonato','gols_casa','gols_fora','jogo_id','divisao','formato','odd_casa_ft'}))
    monkeypatch.setattr(scanner,'filter_options',lambda:{'combinations':scanner._normalize_filter_rows(ROWS)})
    result=scanner.analyze('mo_ft','Brasil','Brasileiro',2025,2026,'América do Sul','1','Liga')
    statement=engine.connection.statement
    assert 'pais = ANY(:continent_countries)' in statement
    assert 'pais=:country' in statement and 'campeonato=:competition' in statement
    assert 'divisao::text=:division' in statement and 'formato::text=:format' in statement
    assert engine.connection.params['continent_countries']==['América do Sul','Brasil']
    assert result['markets'][0]['metrics']['games']==1


def test_bad_continent_country_combination_fails(monkeypatch):
    engine=Engine()
    monkeypatch.setattr(scanner,'_source',lambda:(engine,{'data','pais','campeonato','gols_casa','gols_fora','odd_casa_ft'}))
    monkeypatch.setattr(scanner,'filter_options',lambda:{'combinations':scanner._normalize_filter_rows(ROWS)})
    with pytest.raises(ValueError,match='País não pertence'):
        scanner.analyze('mo_ft','Brasil',None,None,None,'Europa')
