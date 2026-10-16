from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError

from ..schemas import (
    CountryCreate,
    CompetitionCreate,
    ClubUpdate,
    ClubMembershipCreate,
    ClubMembershipUpdate,
    ClubSeasonImportRequest,
    MarketValueCreate,
)
from ..repositories import catalog_repository as repo
from ..services.elo_service import rebuild_if_complete

router = APIRouter(prefix="/api/manage", tags=["gestão de cadastros"])


def _not_found(entity: str):
    raise HTTPException(status_code=404, detail=f"{entity} não encontrado.")


def _integrity_error(exc: IntegrityError):
    raise HTTPException(
        status_code=409,
        detail="Não foi possível salvar porque já existe um cadastro igual ou há vínculo incompatível.",
    ) from exc


@router.get("/countries")
def countries(q: str | None = None, page: int = 1, page_size: int = Query(20, ge=1, le=100)):
    return repo.manage_countries(q, page, page_size)


@router.put("/countries/{country_id}")
def update_country(country_id: int, payload: CountryCreate):
    try:
        row = repo.update_country(country_id, payload.nome, payload.continente)
    except IntegrityError as exc:
        _integrity_error(exc)
    if not row:
        _not_found("País")
    return row


@router.delete("/countries/{country_id}")
def delete_country(country_id: int):
    row = repo.delete_country(country_id)
    if not row:
        _not_found("País")
    return {"ok": True, "deleted": row}


@router.get("/competitions")
def competitions(q: str | None = None, page: int = 1, page_size: int = Query(20, ge=1, le=100)):
    return repo.manage_competitions(q, page, page_size)


@router.put("/competitions/{competition_id}")
def update_competition(competition_id: int, payload: CompetitionCreate):
    try:
        row = repo.update_competition(
            competition_id, payload.nome, payload.pais_id, payload.principal
        )
    except IntegrityError as exc:
        _integrity_error(exc)
    if not row:
        _not_found("Campeonato")
    return row


@router.delete("/competitions/{competition_id}")
def delete_competition(competition_id: int):
    row = repo.delete_competition(competition_id)
    if not row:
        _not_found("Campeonato")
    return {"ok": True, "deleted": row}


@router.get("/clubs/import-preview")
def import_preview(campeonato_id: int, temporada: str):
    try:
        return repo.preview_previous_season_clubs(campeonato_id, temporada)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/clubs/search-competition-base")
def search_competition_base(
    campeonato_id: int,
    q: str | None = None,
    temporada: str | None = None,
    limit: int = Query(300, ge=1, le=500),
):
    return repo.search_competition_clubs(
        campeonato_id,
        q,
        temporada,
        limit,
    )


@router.post("/clubs/import-previous-season")
def import_previous_season(payload: ClubSeasonImportRequest):
    try:
        return repo.import_previous_season_clubs(
            payload.campeonato_id,
            payload.temporada,
            payload.clube_ids,
            [item.model_dump() for item in payload.novos_clubes],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/clubs")
def clubs(
    q: str | None = None,
    page: int = 1,
    page_size: int = Query(20, ge=1, le=100),
    temporada: str | None = None,
    pais_id: int | None = None,
    campeonato_id: int | None = None,
):
    return repo.manage_clubs(
        q,
        page,
        page_size,
        temporada,
        pais_id,
        campeonato_id,
    )


@router.get("/clubs/{club_id}")
def club_detail(club_id: int):
    row = repo.get_club_management(club_id)
    if not row:
        _not_found("Clube")
    return row


@router.put("/clubs/{club_id}")
def update_club(club_id: int, payload: ClubUpdate):
    try:
        row = repo.update_club(club_id, payload.nome, payload.pais_id, payload.escudo_url)
    except IntegrityError as exc:
        _integrity_error(exc)
    if not row:
        _not_found("Clube")
    return row


@router.post("/clubs/{club_id}/memberships")
def add_membership(club_id: int, payload: ClubMembershipCreate):
    repo.add_club_membership(club_id, payload.campeonato_id, payload.temporada)
    return {"ok": True}


@router.put("/clubs/{club_id}/memberships")
def update_membership(club_id: int, payload: ClubMembershipUpdate):
    repo.update_club_membership(
        club_id,
        payload.old_campeonato_id,
        payload.old_temporada,
        payload.campeonato_id,
        payload.temporada,
    )
    return {"ok": True}


@router.delete("/clubs/{club_id}/memberships")
def delete_membership(club_id: int, campeonato_id: int, temporada: str):
    repo.delete_club_membership(club_id, campeonato_id, temporada)
    return {"ok": True}


@router.delete("/clubs/{club_id}")
def delete_club(club_id: int):
    row = repo.delete_club(club_id)
    if not row:
        _not_found("Clube")
    return {"ok": True, "deleted": row}


@router.get("/market-values")
def market_values(q: str | None = None, page: int = 1, page_size: int = Query(20, ge=1, le=100)):
    return repo.manage_market_values(q, page, page_size)


@router.put("/market-values/{value_id}")
def update_market_value(value_id: int, payload: MarketValueCreate):
    if payload.moeda not in {"EUR", "USD", "BRL"}:
        raise HTTPException(status_code=422, detail="Moeda inválida.")

    try:
        result = repo.update_market_value(value_id, payload.model_dump())
    except IntegrityError as exc:
        _integrity_error(exc)

    if not result["row"]:
        _not_found("Valor de mercado")

    if result["old"]:
        rebuild_if_complete(
            result["old"]["campeonato_id"],
            result["old"]["temporada"],
        )
    rebuild_if_complete(payload.campeonato_id, payload.temporada)

    return result["row"]


@router.delete("/market-values/{value_id}")
def delete_market_value(value_id: int):
    row = repo.delete_market_value(value_id)
    if not row:
        _not_found("Valor de mercado")

    rebuild_if_complete(row["campeonato_id"], row["temporada"])
    return {"ok": True, "deleted": row}
