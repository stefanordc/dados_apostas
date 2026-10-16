from fastapi import APIRouter, Query

from ..repositories.catalog_repository import list_clubs
from ..services.elo_service import strength_profile
from ..services.stats_service import calculate_club_stats, club_filter_options, market_value_evolution

router = APIRouter(prefix="/api/club-directory", tags=["clubes"])


@router.get("")
def directory(country_id: int | None = None):
    return list_clubs(country_id=country_id)


@router.get("/{club_id}/filters")
def filters(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
    venue: str = Query(default="all", pattern="^(all|home|away)$"),
):
    return club_filter_options(club_id, competition_id, season, venue)


@router.get("/{club_id}/stats")
def club_stats(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
    opponent: str | None = None,
    venue: str = Query(default="all", pattern="^(all|home|away)$"),
    result_filter: str = Query(default="all", pattern="^(all|win|draw|loss)$"),
):
    # Retorna primeiro as estatísticas essenciais do perfil.
    # O radar é carregado separadamente para não bloquear a tela inteira.
    return calculate_club_stats(
        club_id, competition_id, season, None, venue, opponent, result_filter
    )


@router.get("/{club_id}/strength-profile")
def club_strength(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
):
    return strength_profile(club_id, competition_id, season)


@router.get("/{club_id}/market-value-evolution")
def market_values(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
):
    return market_value_evolution(club_id, competition_id, season)
