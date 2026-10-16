from fastapi import APIRouter, HTTPException, Query

from ..repositories.player_repository import (
    list_players,
    player_filter_options,
    player_profile,
    player_ranking,
)

router = APIRouter(tags=["jogadores"])


@router.get("/api/player-directory/filters")
def directory_filters():
    return player_filter_options()


@router.get("/api/player-directory")
def directory(
    q: str | None = None,
    position: str | None = None,
    nationality: str | None = None,
    club: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=60, ge=1, le=100),
):
    return list_players(q, position, nationality, club, page, page_size)


@router.get("/api/player-directory/{player_id}/profile")
def profile(player_id: str, season: str | None = None, club: str | None = None):
    try:
        return player_profile(player_id, season, club)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/player-rankings/filters")
def ranking_filters():
    return player_filter_options()


@router.get("/api/player-rankings")
def rankings(
    metric: str = Query(default="assistencias"),
    season: str | None = None,
    club: str | None = None,
    position: str | None = None,
    nationality: str | None = None,
):
    try:
        return player_ranking(metric, season, club, position, nationality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
