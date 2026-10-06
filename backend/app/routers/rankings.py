from fastapi import APIRouter, HTTPException, Query

from ..services import rankings_service

router = APIRouter(prefix="/api/rankings", tags=["rankings"])


@router.get("/filters")
def filters(country_id: int | None = None):
    return rankings_service.filters(country_id)


@router.get("")
def ranking(
    metric: str = Query(
        pattern="^(elo|offense|defense|market|5|10|20|season|history|over15|over25|btts)$"
    ),
    country_id: int | None = None,
    competition_id: int | None = None,
    season: str | None = None,
    venue: str = Query(default="all", pattern="^(all|home|away)$"),
):
    try:
        return rankings_service.ranking(
            metric,
            country_id,
            competition_id,
            season,
            venue,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
