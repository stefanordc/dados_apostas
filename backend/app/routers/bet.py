"""Rotas do BET Teste (métodos, Nostradamus, Casa de Apostas e Relatório)."""
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services import bet_engine as engine
from ..services import bet_service as svc

router = APIRouter(prefix='/api/bet', tags=['bet-teste'])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class MethodPayload(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    definicao: dict[str, Any]


class NostradamusPayload(BaseModel):
    metodo_id: int | None = None
    definicao: dict[str, Any] | None = None
    stake: float = Field(default=100.0, gt=0, le=1_000_000)
    stake_mode: str = 'stake'
    comissao: float = Field(default=0.0, ge=0, le=0.2)
    formato: str | None = None
    data_inicio: date | None = None
    data_fim: date | None = None


class BetPayload(BaseModel):
    data_limite: date
    jogo_id: str
    mercado: str
    selecao: str
    lado: str
    minuto: int = Field(default=0, ge=0, le=90)
    stake: float = Field(gt=0, le=10_000_000)
    odd: float | None = Field(default=None, gt=1, le=1000)
    odd_origem: str | None = None


@router.get('/catalogo')
def catalog():
    # Cobertura do calendário = tabela jogos (não a tabela odds).
    years = {}
    for g in engine.all_games():
        fontes = g.get('fontes') or ([g.get('fonte')] if g.get('fonte') else [])
        if 'jogos' not in fontes and g.get('calendario') != 'jogos':
            continue
        years[g['data'].year] = years.get(g['data'].year, 0) + 1
    return {'cobertura': [{'ano': y, 'jogos': n} for y, n in sorted(years.items())], 'mercados': engine.market_catalog(), 'campos': engine.condition_fields(),
            'paises': engine.countries(), 'campeonatos': [{'pais': p, 'campeonato': c} for p, c in engine.competitions()],
            'saidas': svc.EXIT_MODES, 'operadores': list(svc.OPS)}


@router.get('/metodos')
def methods():
    return _run(svc.list_methods)


@router.post('/metodos')
def create_method(payload: MethodPayload):
    return _run(svc.save_method, None, payload.nome, payload.definicao)


@router.put('/metodos/{method_id}')
def update_method(method_id: int, payload: MethodPayload):
    return _run(svc.save_method, method_id, payload.nome, payload.definicao)


@router.delete('/metodos/{method_id}')
def delete_method(method_id: int):
    if not svc.delete_method(method_id):
        raise HTTPException(status_code=404, detail='Método não encontrado.')
    return {'ok': True}


@router.post('/nostradamus')
def nostradamus(payload: NostradamusPayload):
    if not payload.metodo_id and not payload.definicao:
        raise HTTPException(status_code=422, detail='Selecione um método.')
    overrides = {k: v for k, v in {'formato': payload.formato, 'date_from': payload.data_inicio,
                                   'date_to': payload.data_fim}.items() if v}
    return _run(svc.nostradamus, payload.metodo_id, payload.definicao, payload.stake, payload.stake_mode,
                payload.comissao, overrides)


@router.post('/atualizar-dados')
def refresh():
    engine.refresh_cache()
    return {'jogos': len(engine.games())}


@router.get('/jogos')
def fixtures(data_limite: date, formato: str = 'Liga', janela_dias: int = Query(default=14, ge=1, le=120)):
    return _run(svc.fixtures, data_limite, formato, janela_dias)


@router.get('/jogo/{jogo_id}/mercados')
def game_markets(jogo_id: str, minuto: int = Query(default=0, ge=0, le=90), data_limite: date | None = None):
    return _run(svc.game_markets, jogo_id, minuto, data_limite)


@router.get('/jogo/{jogo_id}/estatisticas')
def game_stats(jogo_id: str, data_limite: date):
    return _run(svc.game_statistics, jogo_id, data_limite)


@router.get('/config')
def get_config():
    return svc.get_config()


@router.put('/config')
def put_config(payload: dict[str, Any]):
    return _run(svc.update_config, payload)


@router.post('/apostas')
def place_bet(payload: BetPayload):
    return _run(svc.place_bet, {**payload.model_dump(), 'data_limite': payload.data_limite.isoformat()})


@router.get('/apostas/pendentes')
def pending_bets():
    return _run(svc.list_pending_bets)


@router.post('/apostas/{bet_id}/finalizar')
def finalize_bet(bet_id: int):
    return _run(svc.finalize_bet, bet_id)


class ExitPayload(BaseModel):
    minuto: int = Field(ge=0, le=90)
    data_limite: date | None = None


@router.post('/apostas/{bet_id}/sair')
def exit_bet(bet_id: int, payload: ExitPayload):
    return _run(
        svc.exit_bet,
        bet_id,
        payload.minuto,
        payload.data_limite.isoformat() if payload.data_limite else None,
    )


@router.delete('/apostas/{bet_id}')
def delete_bet(bet_id: int):
    return _run(svc.delete_bet, bet_id)


@router.delete('/apostas')
def reset_bets():
    return {'removidas': svc.reset_bets()}


class ResetPayload(BaseModel):
    senha: str = Field(max_length=100)


class ProphecyPayload(BaseModel):
    texto: str = Field(min_length=10, max_length=20_000)
    top: int = Field(default=12, ge=3, le=40)


@router.post('/banca/redefinir')
def reset_bankroll(payload: ResetPayload):
    try:
        return svc.reset_bankroll(payload.senha)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get('/relatorio')
def report():
    return svc.report()


@router.post('/profecia')
def prophecy_route(payload: ProphecyPayload):
    from ..services import bet_prophecy as prophecy_svc
    return _run(prophecy_svc.prophecy, payload.texto, payload.top)


def _warm_up():
    """Pré-carrega odds, jogos e a força dos clubes ao subir o servidor (evita a espera no primeiro clique)."""
    try:
        engine.all_games()
        engine._ratings_state()
    except Exception:
        pass


import threading  # noqa: E402

threading.Thread(target=_warm_up, name='bet-warm-up', daemon=True).start()


class LinkPayload(BaseModel):
    pais: str = Field(min_length=1, max_length=80)
    fonte: str = Field(min_length=1, max_length=30)
    nome_fonte: str = Field(min_length=1, max_length=120)
    nome_padrao: str | None = Field(default=None, max_length=120)
    status: str = 'vinculado'


@router.get('/conciliacao')
def reconciliation(pais: str | None = None):
    return _run(svc.reconciliation, pais)


@router.post('/conciliacao/vinculo')
def save_link(payload: LinkPayload):
    return _run(svc.save_reconciliation, payload.pais, payload.fonte, payload.nome_fonte, payload.nome_padrao, payload.status)


@router.delete('/conciliacao/vinculo')
def delete_link(pais: str, fonte: str, nome_fonte: str):
    return {'removido': svc.delete_reconciliation(pais, fonte, nome_fonte)}


class ApiImport(BaseModel):
    pais: str = Field(min_length=2, max_length=60)
    liga: str = Field(min_length=2, max_length=60)
    temporada: str = Field(min_length=4, max_length=9)


@router.get('/api/importados')
def api_imported():
    return svc.api_list()


@router.post('/api/importar')
def api_import(payload: ApiImport):
    return _run(svc.api_import, payload.pais, payload.liga, payload.temporada)


@router.delete('/api/importados')
def api_remove(pais: str, liga: str, temporada: str):
    return {'removido': svc.api_remove(pais, liga, temporada)}
