from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from ..services import backtesting_service
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4
from time import perf_counter


_ERROR_LOG = Path(__file__).resolve().parents[2] / 'logs' / 'backtesting_errors.log'
_logger = logging.getLogger('backtest_apostas.backtesting')


def _server_error(exc: Exception, action: str) -> HTTPException:
    # Mantém detalhes técnicos no computador do usuário (não na resposta HTTP).
    reference = uuid4().hex[:10]
    try:
        _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        if not _logger.handlers:
            handler = RotatingFileHandler(_ERROR_LOG, maxBytes=2_000_000,
                                          backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
            _logger.addHandler(handler)
        _logger.setLevel(logging.ERROR)
        _logger.propagate = False
        _logger.exception('ID=%s | operação=%s | tipo=%s', reference, action,
                          type(exc).__name__, exc_info=(type(exc), exc, exc.__traceback__))
    except Exception:
        logging.getLogger(__name__).exception('Falha ao gravar diagnóstico %s', reference)
    return HTTPException(
        status_code=500,
        detail=(f'Falha interna no Backtesting (ID {reference}). '
                'Consulte backend/logs/backtesting_errors.log para identificar a causa.')
    )

router=APIRouter(prefix='/api/backtesting',tags=['backtesting'])

class BacktestingRequest(BaseModel):
    competition_id: int | None = Field(default=None, gt=0)
    country_id: int | None = Field(default=None, gt=0)
    continent: str | None = None
    use_history_catalog: bool = False
    league_continent: str | None = None
    league_country: str | None = None
    league_competition: str | None = None
    tab: str = 'team'
    club: str | None = None
    opponent: str | None = None
    start_season: str | None = None
    year_from: int | None = Field(default=None, ge=1850, le=2100)
    year_to: int | None = Field(default=None, ge=1850, le=2100)
    divisao: str | None = None
    formato: str | None = None
    years: int = Field(default=3,ge=1,le=30)
    use_odds: bool = True
    statistics_only: bool = False
    mo_min: float | None = None
    mo_max: float | None = None
    over05_min: float | None = None
    over05_max: float | None = None
    under35_min: float | None = None
    under35_max: float | None = None
    over15_min: float | None = None
    over15_max: float | None = None
    over25_min: float | None = None
    over25_max: float | None = None
    btts_min: float | None = None
    btts_max: float | None = None

class ClubReconciliationRequest(BaseModel):
    competition_id: int = Field(gt=0)
    historico_jogos: str = Field(min_length=1, max_length=180)
    historico_odds: str = Field(min_length=1, max_length=180)
    nome_padrao: str = Field(min_length=1, max_length=180)


@router.get('/conciliation')
def conciliation(competition_id: int=Query(...,gt=0)):
    try: return backtesting_service.reconciliation_options(competition_id)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.post('/conciliation')
def approve_conciliation(payload: ClubReconciliationRequest):
    try: return backtesting_service.save_reconciliation(**payload.model_dump())
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc


class ManualFixtureRequest(BaseModel):
    competition_id: int = Field(gt=0)
    data: str = Field(min_length=8, max_length=12)
    temporada: str = Field(min_length=4, max_length=20)
    jogos_casa: str = Field(min_length=1, max_length=180)
    jogos_fora: str = Field(min_length=1, max_length=180)
    odds_casa: str = Field(min_length=1, max_length=180)
    odds_fora: str = Field(min_length=1, max_length=180)
    posicao: str
    nome_padrao: str = Field(min_length=1, max_length=180)
    confirma_mesmo_jogo: bool


@router.post('/conciliation/fixture')
def approve_manual_fixture(payload: ManualFixtureRequest):
    if not payload.confirma_mesmo_jogo:
        raise HTTPException(status_code=422,detail='Confirme que os dois registros são o mesmo jogo.')
    try: return backtesting_service.save_manual_fixture(**payload.model_dump(exclude={'confirma_mesmo_jogo'}))
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc


@router.get('/options')
def options(competition_id: int=Query(...,gt=0), use_odds: bool=True):
    try: return backtesting_service.options(competition_id, use_odds)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.get('/league-catalog')
def league_catalog():
    from ..services.league_catalog_service import choices
    return choices()


@router.get('/league-options')
def league_options(country_id: int | None = Query(default=None, gt=0),
                   competition_id: int | None = Query(default=None, gt=0),
                   use_odds: bool = True,
                   league_country: str | None = None,
                   league_competition: str | None = None,
                   league_continent: str | None = None):
    try:
        return backtesting_service.league_options(
            country_id, competition_id, use_odds, league_country, league_competition, league_continent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class LeagueMarketHistoryRequest(BaseModel):
    country: str = Field(min_length=1, max_length=150)
    competition: str = Field(min_length=1, max_length=150)
    market: str = Field(min_length=1, max_length=30)
    use_odds: bool = False
    divisao: str | None = None
    formato: str | None = None
    mo_min: float | None = None
    mo_max: float | None = None
    over05_min: float | None = None
    over05_max: float | None = None
    under35_min: float | None = None
    under35_max: float | None = None
    over15_min: float | None = None
    over15_max: float | None = None
    over25_min: float | None = None
    over25_max: float | None = None
    btts_min: float | None = None
    btts_max: float | None = None


@router.post('/league-market-history')
def league_market_history(payload: LeagueMarketHistoryRequest):
    try:
        return backtesting_service.league_market_history(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/evaluate')
def evaluate(payload: BacktestingRequest):
    try:
        # Força a serialização dentro da rota: eventuais NaN/tipos inválidos
        # também ficam no log com ID, em vez de gerar um 500 anônimo.
        result = backtesting_service.evaluate(payload.model_dump())
        return JSONResponse(content=jsonable_encoder(result))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _server_error(exc, 'POST /api/backtesting/evaluate') from exc


# Estatísticas por Clube: consultas independentes da análise por campeonatos.
# Nenhum dos três filtros é obrigatório para o ranking.
class ClubStatisticsRequest(BaseModel):
    continent: str | None = None
    country: str | None = None
    competition: str | None = None
    club: str | None = None
    year_from: int | None = Field(default=None, ge=1850, le=2100)
    year_to: int | None = Field(default=None, ge=1850, le=2100)
    use_odds: bool = False
    mo_min: float | None = None
    mo_max: float | None = None
    over05_min: float | None = None
    over05_max: float | None = None
    over15_min: float | None = None
    over15_max: float | None = None
    over25_min: float | None = None
    over25_max: float | None = None
    under35_min: float | None = None
    under35_max: float | None = None
    btts_min: float | None = None
    btts_max: float | None = None


class ClubMarketHistoryRequest(ClubStatisticsRequest):
    country: str = Field(min_length=1)
    club: str = Field(min_length=1)
    market: str = Field(min_length=1)


@router.get('/club-candidates')
def club_candidates(country: str | None = None, competition: str | None = None,
                    continent: str | None = None,
                    q: str | None = None, limit: int = Query(default=120, ge=1, le=500)):
    from ..services import club_statistics_service as service
    try: return service.candidates(country,competition,q,limit,continent=continent)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.post('/club-statistics')
def club_statistics(payload:ClubStatisticsRequest):
    from ..services import club_statistics_service as service
    started = perf_counter()
    try:
        result = service.ranking(payload.model_dump())
        return JSONResponse(content=jsonable_encoder(result))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _server_error(exc, 'POST /api/backtesting/club-statistics') from exc
    finally:
        logging.getLogger('uvicorn.error').info(
            'Estatísticas por Clube: modo=%s, filtro_pais=%s, filtro_campeonato=%s, tempo=%.2fs',
            'com_odds' if payload.use_odds else 'sem_odds', bool(payload.country),
            bool(payload.competition), perf_counter()-started)


@router.post('/club-market-history')
def club_market_history(payload:ClubMarketHistoryRequest):
    from ..services import club_statistics_service as service
    try: return service.history(payload.model_dump())
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
