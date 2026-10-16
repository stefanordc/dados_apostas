"""Rotas das novas páginas Scanner e Backtesting de confrontos."""
from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field
from typing import Literal
from sqlalchemy import text
from ..config import settings
from ..db import app_engine
from ..services import market_scanner_service as scanner,match_analysis_service as matches,sofascore_match_service as sofa

router=APIRouter(prefix='/api/analysis-v3',tags=['scanner','backtesting'])

class MarketScan(BaseModel):
    group: str
    country: str | None=None
    competition: str | None=None
    continent: str | None=None
    division: str | None=None
    format: str | None=None
    year_from: int | None=Field(default=None,ge=1850,le=2100)
    year_to: int | None=Field(default=None,ge=1850,le=2100)

class MatchAnalysis(BaseModel):
    country: str | None=None
    competition: str | None=None
    home: str
    away: str
    interval_games: int = Field(default=30, ge=5, le=100)

class ValueRequest(BaseModel):
    probability:float=Field(ge=0,le=100)
    odd:float=Field(ge=1.01,le=1000)
    kind:Literal['back','lay']='back' 

@router.get('/scanner/catalog')
def scanner_catalog():
    try:return scanner.catalog()
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex

@router.get('/scanner/filter-options')
def scanner_filter_options():
    try:return scanner.filter_options()
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex

@router.post('/scanner/analyze')
def scanner_analyze(payload:MarketScan):
    try:return scanner.analyze(payload.group,payload.country,payload.competition,payload.year_from,payload.year_to,
                               payload.continent,payload.division,payload.format)
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex

@router.get('/match/options')
def match_options(country:str|None=None,competition:str|None=None):
    try:return sofa.choices(country,competition)
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex

@router.post('/match/analyze')
def match_analyze(payload:MatchAnalysis):
    try:return sofa.analyze(payload.country,payload.competition,payload.home.strip(),payload.away.strip(),payload.interval_games)
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex

@router.post('/match/value')
def match_value(payload:ValueRequest):
    try:return matches.expected_value(payload.probability,payload.odd,payload.kind)
    except ValueError as ex:raise HTTPException(status_code=422,detail=str(ex)) from ex


@router.get('/match/shields')
def match_shields(names:list[str]=Query(default=[]),country:str|None=None):
    """Escudo cadastrado (app.clubes.escudo_url) por nome de clube, sem diferenciar maiúsculas."""
    names=[n.strip() for n in names if n and n.strip()][:4]
    if not names:return {}
    try:
        with app_engine.connect() as conn:
            rows=conn.execute(text(f'''SELECT cl.nome,cl.escudo_url,p.nome AS pais
                FROM {settings.app_schema}.clubes cl LEFT JOIN {settings.app_schema}.paises p ON p.id=cl.pais_id
                WHERE NULLIF(BTRIM(cl.escudo_url),'') IS NOT NULL
                  AND LOWER(BTRIM(cl.nome))=ANY(:names)'''),{'names':[n.lower() for n in names]}).mappings().all()
    except Exception:
        return {}
    found={}
    for n in names:
        matches=[r for r in rows if r['nome'].strip().lower()==n.lower()]
        matches.sort(key=lambda r:r['pais']!=country if country else False)
        if matches:found[n]=matches[0]['escudo_url'].strip()
    return found
