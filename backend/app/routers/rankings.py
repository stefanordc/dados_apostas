from fastapi import APIRouter, HTTPException, Query

from ..services import rankings_service

router = APIRouter(prefix="/api/rankings", tags=["rankings"])

METRIC_PATTERN = (
    "^(elo|offense|defense|market|5|10|20|season|history|over15|over25|btts|"
    "opens_score|opens_and_wins|opens_and_equalized|opens_and_overturned|"
    "goals_band_0_15|goals_band_16_30|goals_band_31_45|goals_band_46_60|"
    "goals_band_61_75|goals_band_76_90|goals_band_90p|"
    "shots|shots_on_target|shots_per_game|shots_per_goal|sot_per_goal|"
    "pass_accuracy|possession|tackles|xg|big_chances|big_chances_scored|"
    "corners|interceptions|recoveries|duel_pct|dribble_pct|tackle_pct|"
    "shots_in_box|saves|yellow_cards|red_cards|fouls|offsides|woodwork|"
    "crosses|long_balls|through_balls)$"
)


@router.get("/filters")
def filters(country_id: int | None = None, competition_id: int | None = None):
    return rankings_service.filters(country_id, competition_id)


@router.get("")
def ranking(
    metric: str = Query(pattern=METRIC_PATTERN),
    country_id: int | None = None,
    competition_id: int | None = None,
    season: str | None = None,
    year: int | str | None = None,
    min_games: int | str | None = None,
    venue: str = Query(default="all", pattern="^(all|home|away)$"),
    divisao: str | None = None,
    formato: str | None = None,
):
    try:
        return rankings_service.ranking(
            metric,
            country_id,
            competition_id,
            season,
            venue,
            divisao,
            formato,
            year,
            min_games,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
