from fastapi import APIRouter, HTTPException, Query

from ..schemas import ScannerBacktestRequest, ScannerGenerateMethodsRequest, ScannerInsightRequest, ScannerMethodCreate, ScannerCondition
from ..services import methods_service

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.get("/catalog")
def catalog():
    return methods_service.condition_catalog()


@router.get("/seasons")
def seasons(competition_id: int = Query(..., ge=1)):
    return methods_service.available_seasons(competition_id)


@router.post("/insights")
def scanner_insights(payload: ScannerInsightRequest):
    try:
        return methods_service.insights(
            payload.campeonato_id,
            payload.temporada_alvo,
            payload.sequencia_vitorias,
            payload.proximo_mando,
            payload.faixa_mo_min,
            payload.faixa_mo_max,
            payload.faixa_over25_min,
            payload.faixa_over25_max,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/methods")
def methods():
    return methods_service.list_methods()


@router.post("/methods/generate")
def generate_methods(payload: ScannerGenerateMethodsRequest):
    try:
        return methods_service.generate_profitable_methods(
            payload.campeonato_id,
            payload.temporada_alvo,
            payload.quantidade,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/methods")
def create_method(payload: ScannerMethodCreate):
    try:
        return methods_service.create_method(
            payload.nome,
            payload.mercado,
            [c.model_dump() for c in payload.condicoes],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/methods/{method_id}")
def update_method(method_id: int, payload: ScannerMethodCreate):
    try:
        return methods_service.update_method(
            method_id,
            payload.nome,
            payload.mercado,
            [c.model_dump() for c in payload.condicoes],
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if message == "Método não encontrado." else 422
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/methods/{method_id}/conditions")
def append_condition(method_id: int, payload: ScannerCondition):
    try:
        return methods_service.append_method_condition(method_id, payload.model_dump())
    except ValueError as exc:
        status = 404 if str(exc) == "Método não encontrado." else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/methods/{method_id}")
def delete_method(method_id: int):
    if not methods_service.delete_method(method_id):
        raise HTTPException(status_code=404, detail="Método não encontrado.")
    return {"ok": True}


@router.post("/backtest")
def run_backtest(payload: ScannerBacktestRequest):
    try:
        return methods_service.backtest(
            payload.campeonato_id,
            payload.temporada_alvo,
            payload.metodo_id,
            payload.stake,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
