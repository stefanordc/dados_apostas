from fastapi import APIRouter, Query
from ..schemas import OddsPreviewRequest, OddsImportRequest, SimilarGamesRequest
from ..repositories.catalog_repository import list_competitions, list_clubs
from ..services import elo_service, odds_service, stats_service, similarity_service

router=APIRouter(prefix='/api/elo',tags=['elo'])

@router.get('/filters')
def filters(): return elo_service.filters()

@router.get('/competitions')
def competitions(country_id:int): return list_competitions(country_id)

@router.get('/clubs')
def clubs(country_id:int|None=None,competition_id:int|None=None,season:str|None=None): return list_clubs(country_id,competition_id,season)

@router.get('/status')
def status(competition_id:int,season:str): return elo_service.elo_status(competition_id,season)

@router.post('/rebuild')
def rebuild(competition_id:int,season:str): return elo_service.rebuild_elo(competition_id,season)

@router.get('/ranking')
def ranking(country_id:int|None=None,season:str|None=None,competition_id:int|None=None,club_id:int|None=None): return elo_service.ranking(country_id,season,competition_id,club_id)

@router.get('/validation')
def validation(competition_id:int,season:str): return elo_service.validation(competition_id,season)

@router.post('/odds/preview')
def odds_preview(payload:OddsPreviewRequest): return odds_service.preview(payload.pais_id,payload.campeonato_id,payload.temporada,payload.raw_text)

@router.post('/odds/import')
def odds_import(payload:OddsImportRequest): return odds_service.import_data(payload.pais_id,payload.campeonato_id,payload.temporada,payload.raw_text,payload.mappings)


@router.get('/odds/imports')
def odds_imports(limit:int=Query(default=10,ge=1,le=50)):
    return odds_service.list_imports(limit)

@router.delete('/odds/imports/{batch_id}')
def delete_odds_import(batch_id:int):
    from fastapi import HTTPException
    result=odds_service.delete_import(batch_id)
    if result is None:
        raise HTTPException(status_code=404,detail='Carga de odds não encontrada.')
    return result

@router.get('/backtest')
def backtest(home_id:int,away_id:int,competition_id:int,season:str,period:str=Query(default='5',pattern='^(5|10|20|season)$')):
    return stats_service.matchup(home_id,away_id,competition_id,season,period)


@router.post('/similar-games')
def similar_games(payload: SimilarGamesRequest):
    from fastapi import HTTPException
    try:
        return similarity_service.analyze_similar_games(
            payload.home_id,
            payload.away_id,
            payload.competition_id,
            payload.season,
            payload.home_odd,
            payload.draw_odd,
            payload.away_odd,
            payload.selected_markets,
            payload.market_odds,
            payload.cutoff_date,
            payload.odds_tolerance_pct,
            payload.elo_tolerance_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
