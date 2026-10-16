from fastapi import APIRouter, Query
from ..schemas import CountryCreate, CompetitionCreate, ClubCreate, MarketValueCreate, MarketValueBulkRequest
from ..repositories import catalog_repository as repo
from ..services.elo_service import rebuild_if_complete
from ..services import market_value_service

router = APIRouter(prefix="/api", tags=["cadastros"])

@router.get("/countries")
def countries(q: str | None = Query(default=None), with_games: bool = False):
    return repo.list_countries(q, with_games=with_games)

@router.post("/countries")
def create_country(payload: CountryCreate):
    return repo.create_country(payload.nome, payload.continente)

@router.get("/competitions")
def competitions(country_id: int | None = None, q: str | None = None):
    return repo.list_competitions(country_id, q)

@router.post("/competitions")
def create_competition(payload: CompetitionCreate):
    return repo.create_competition(payload.nome, payload.pais_id, payload.principal)

@router.get("/clubs")
def clubs(country_id: int | None = None, competition_id: int | None = None,
          season: str | None = None, q: str | None = None, exclude_market_values: bool = False):
    return repo.list_clubs(country_id, competition_id, season, q, exclude_market_values)

@router.post("/clubs")
def create_club(payload: ClubCreate):
    return repo.create_club(payload.nome, payload.pais_id, payload.campeonato_id, payload.temporada, payload.escudo_url)

@router.post("/market-values")
def create_market_value(payload: MarketValueCreate):
    if payload.moeda not in {"EUR","USD","BRL"}: raise ValueError("Moeda inválida.")
    row=repo.save_market_value(payload.model_dump())
    row['elo']=rebuild_if_complete(payload.campeonato_id,payload.temporada)
    return row


@router.post("/market-values/bulk/preview")
def preview_market_values_bulk(payload: MarketValueBulkRequest):
    from fastapi import HTTPException
    try:
        return market_value_service.preview(
            payload.pais_id, payload.campeonato_id, payload.moeda, payload.raw_text
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/market-values/bulk/import")
def import_market_values_bulk(payload: MarketValueBulkRequest):
    from fastapi import HTTPException
    try:
        return market_value_service.import_data(
            payload.pais_id, payload.campeonato_id, payload.moeda, payload.raw_text
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/market-values/bulk/imports")
def market_value_imports(limit: int = Query(default=10, ge=1, le=50)):
    return market_value_service.list_imports(limit)

@router.delete("/market-values/bulk/imports/{batch_id}")
def delete_market_value_import(batch_id: int):
    from fastapi import HTTPException
    result = market_value_service.delete_import(batch_id)
    if not result:
        raise HTTPException(status_code=404, detail="Carga de valor de mercado não encontrada.")
    return result

@router.get("/market-values")
def market_values(limit: int = Query(default=20, ge=1, le=100)):
    return repo.list_market_values(limit)
