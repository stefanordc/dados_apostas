"""Explorador descritivo de resultados e P/L, sem odds sintéticas.

O banco de jogos é somente leitura. Cotações são buscadas no banco principal.
Uma ausência de cotação produz P/L = null (nunca zero fictício).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_left
from datetime import date
from functools import lru_cache
import re
import time
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from .elo_service import normalize_name
from .historico_odds_service import (
    load_historical_odds, reconcile, QUOTE_MAP, pending_name_pairs, canonical_name,
    unresolved_fixture_matches, date_code, season_code
)
from .clubs_conciliation_service import load_mappings, save_mapping

STAKE = 100.0
MARKETS = [
    ("back_home", "Back mandante (clube alvo)", "back"),
    ("lay_home", "Lay mandante (clube alvo)", "lay"),
    ("draw", "Empate", "back"),
    ("back_away", "Back visitante (clube alvo)", "back"),
    ("lay_away", "Lay visitante (clube alvo)", "lay"),
    ("over05", "Over 0,5", "back"),
    ("over15", "Over 1,5", "back"),
    ("over25", "Over 2,5", "back"),
    ("under35", "Under 3,5", "back"),
    ("btts", "Ambos marcam — Sim", "back"),
    ("lay_big_home", "Lay goleada mandante", "lay"),
    ("lay_big_away", "Lay goleada visitante", "lay"),
]
MARKET_BY_KEY = {k: (label, kind) for k, label, kind in MARKETS}
SCORES = [
    (0,0),(1,1),(2,2),(3,3),(4,4),
    (1,0),(2,0),(3,0),(4,0),(2,1),(3,1),(4,1),(3,2),(4,2),
    (0,1),(0,2),(0,3),(0,4),(1,2),(1,3),(1,4),(2,3),(2,4),(3,4),(4,3),
]


def _season_key(s: Any) -> tuple[int, int]:
    m = re.match(r"^\s*(\d{4})(?:\s*[/-]\s*(\d{2,4}))?", str(s or ""))
    if not m:
        return (0, 0)
    first = int(m.group(1))
    last = m.group(2)
    if not last:
        return (first, first)
    year = int(last)
    if len(last) == 2:
        year += (first // 100) * 100
        if year < first:
            year += 100
    return first, year


def _calendar_year_range(payload: dict, league_mode: bool) -> tuple[int | None, int | None]:
    if not league_mode:
        return None, None
    first, last = payload.get('year_from'), payload.get('year_to')
    try:
        first = int(first) if first not in (None, '') else None
        last = int(last) if last not in (None, '') else None
    except (TypeError, ValueError) as exc:
        raise ValueError('Informe anos válidos nos campos De e Até.') from exc
    if any(y is not None and not (1850 <= y <= 2100) for y in (first, last)):
        raise ValueError('Informe anos entre 1850 e 2100.')
    if first is not None and last is not None and first > last:
        raise ValueError('O ano De não pode ser maior que o ano Até.')
    return first, last


def _filter_calendar_years(games, first: int | None, last: int | None):
    return [g for g in games if (first is None or int(g['year']) >= first)
            and (last is None or int(g['year']) <= last)]


def _display_season(s: Any) -> str:
    raw = str(s or "").strip()
    first, last = _season_key(raw)
    if first and last != first:
        return f"{first:04d}/{last:04d}"
    return raw


def _tables() -> tuple[str, str]:
    # The same trusted schema settings already used by the project.
    return f"{settings.history_schema}.{settings.history_table}", f"{settings.app_schema}.odds_jogos"


def _competition(competition_id: int) -> dict:
    if app_engine is None:
        return {'id': competition_id, 'competition': f'Campeonato {competition_id}', 'country': '', 'country_id': None}
    with app_engine.connect() as conn:
        row = conn.execute(text(f"""
          SELECT c.id, c.nome competition, c.pais_id country_id, p.nome country
          FROM {settings.app_schema}.campeonatos c
          JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
          WHERE c.id=:id
        """), {"id": competition_id}).mappings().first()
    if not row:
        raise ValueError("Campeonato não encontrado.")
    return dict(row)


def _competition_catalog(country_id: int | None = None, competition_id: int | None = None) -> list[dict]:
    if app_engine is None:
        if competition_id:
            return [{'id': competition_id, 'competition': f'Campeonato {competition_id}', 'country': '', 'country_id': country_id or None}]
        return []
    clauses = []
    params: dict[str, Any] = {}
    if country_id:
        clauses.append('c.pais_id=:country_id')
        params['country_id'] = country_id
    if competition_id:
        clauses.append('c.id=:competition_id')
        params['competition_id'] = competition_id
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    with app_engine.connect() as conn:
        rows = conn.execute(text(f"""
          SELECT c.id, c.nome competition, c.pais_id country_id, p.nome country
          FROM {settings.app_schema}.campeonatos c
          JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
          {where}
          ORDER BY p.nome, c.principal DESC, c.nome
        """), params).mappings().all()
    return [dict(row) for row in rows]


def _bucket():
    return int(time.time() // 300)


@lru_cache(maxsize=12)
def _history_source(competition_id: int, bucket: int):
    """Somente historico_jogos: nunca consulta odds_jogos/historico_odds."""
    meta=_competition(competition_id)
    table,_=_tables()
    with history_connection() as conn:
        cols={r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=:schema AND table_name=:table
        """), {'schema':settings.history_schema,'table':settings.history_table}).all()}
        columns=''.join(f", {c}::text AS {c}" for c in ('divisao','formato') if c in cols)
        source=conn.execute(text(f"""
            SELECT data,temporada,casa,fora,gols_casa,gols_fora {columns}
            FROM {table}
            WHERE pais=:country AND campeonato=:competition
              AND data IS NOT NULL AND data<=CURRENT_DATE
              AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
            ORDER BY data, casa, fora
        """),{'country':meta['country'],'competition':meta['competition']}).mappings()
        originals=[dict(r) for r in source]
    quote_none={field:None for field in QUOTE_MAP.values()}
    output=[];seasons=set();clubs=set()
    for r in originals:
        season=_display_season(r['temporada']);seasons.add(season)
        home,away=str(r['casa']),str(r['fora']);clubs.update((home,away))
        div=str(r.get('divisao') or '').strip() or None
        fmt=str(r.get('formato') or '').strip() or None
        output.append({**quote_none,
            'date':str(r['data']),'year':int(str(r['data'])[:4]),
            'season':season,'season_key':_season_key(r['temporada']),
            'home':home,'away':away,'gh':int(r['gols_casa']),'ga':int(r['gols_fora']),
            'divisao':div,'formato':fmt,'history_divisao':div,'history_formato':fmt,
            'odds_source':None,'home_odd':None,'away_odd':None,'draw_odd':None,
            'over25_odd':None})
    return (output,sorted(seasons,key=_season_key,reverse=True),sorted(clubs),
            {'status':'histórico','games_total':len(output),'matched_games':0},[],[])


@lru_cache(maxsize=12)
def _source(competition_id: int, bucket: int):
    meta = _competition(competition_id)
    hist_table, odds_table = _tables()
    with history_connection() as conn:
        # Support labels on historico_jogos too, when present.
        hist_cols = {r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=:schema AND table_name=:table
        """), {'schema':settings.history_schema, 'table':settings.history_table}).all()}
        metadata_columns = ''.join(f', {c}::text AS {c}' for c in ('divisao', 'formato') if c in hist_cols)
        games = [dict(r) for r in conn.execute(text(f"""
            SELECT id, data, temporada, casa, fora, gols_casa, gols_fora {metadata_columns}
            FROM {hist_table}
            WHERE pais=:country AND campeonato=:competition
              AND data IS NOT NULL AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
              AND data <= CURRENT_DATE
            ORDER BY data ASC, id ASC
        """), {"country":meta['country'], "competition":meta['competition']}).mappings()]
    with app_engine.connect() as conn:
        clubs = [dict(r) for r in conn.execute(text(f"""
            SELECT c.id, c.nome FROM {settings.app_schema}.clubes c
            WHERE c.pais_id=:country_id
        """), {"country_id":meta['country_id']}).mappings()]
        aliases = [dict(r) for r in conn.execute(text(f"""
            SELECT a.clube_id, a.alias FROM {settings.app_schema}.clubes_aliases a
            JOIN {settings.app_schema}.clubes c ON c.id=a.clube_id
            WHERE c.pais_id=:country_id AND (a.campeonato_id=:competition_id OR a.campeonato_id IS NULL)
        """), {"country_id":meta['country_id'], "competition_id":competition_id}).mappings()]
        odds = [dict(r) for r in conn.execute(text(f"""
            SELECT id, data, temporada, clube_casa_id, clube_fora_id,
                   odd_casa::float odd_casa, odd_empate::float odd_empate,
                   odd_fora::float odd_fora, odd_over_25::float odd_over_25
            FROM {odds_table}
            WHERE campeonato_id=:competition_id AND data IS NOT NULL
        """), {"competition_id":competition_id}).mappings()]
    decisions = load_mappings(competition_id)
    names = {normalize_name(r['nome']): int(r['id']) for r in clubs}
    for row in aliases:
        names[normalize_name(row['alias'])] = int(row['clube_id'])
    odds_lookup = {(str(o['data']),int(o['clube_casa_id']),int(o['clube_fora_id'])):o for o in odds}
    merged = []
    for g in games:
        home, away = str(g['casa']),str(g['fora'])
        home_id, away_id = names.get(normalize_name(home)),names.get(normalize_name(away))
        odd = odds_lookup.get((str(g['data']),home_id,away_id)) if home_id and away_id else None
        gh, ga = int(g['gols_casa']),int(g['gols_fora'])
        merged.append({
            'history_divisao': str(g.get('divisao') or '').strip() or None,
            'history_formato': str(g.get('formato') or '').strip() or None,
            'date': str(g['data']), 'year': g['data'].year if hasattr(g['data'],'year') else int(str(g['data'])[:4]),
            'season': _display_season(g['temporada']), 'season_key': _season_key(g['temporada']),
            'home':home, 'away':away, 'gh':gh, 'ga':ga,
            'divisao':str(g.get('divisao') or '').strip() or None,
            'formato':str(g.get('formato') or '').strip() or None,
            'home_odd': odd.get('odd_casa') if odd else None,
            'away_odd': odd.get('odd_fora') if odd else None,
            'draw_odd': odd.get('odd_empate') if odd else None,
            'over25_odd': odd.get('odd_over_25') if odd else None,
            'odds_source': 'odds_jogos' if odd else None,
            **{field: None for field in QUOTE_MAP.values()
               if field not in ('home_odd', 'draw_odd', 'away_odd', 'over25_odd')},
        })
    # New complete odds source supersedes the former limited odds_jogos entries.
    public_odds, odds_meta = load_historical_odds(meta['country'], meta['competition'])
    diagnostics = reconcile(merged, public_odds, names, decisions)
    pending = pending_name_pairs(merged, public_odds, decisions, names)
    unresolved = unresolved_fixture_matches(merged, public_odds, decisions, names)
    diagnostics['pending_clubs'] = len(pending)
    diagnostics['pending_fixtures'] = len(unresolved)
    # Nome padrão é exclusivamente para apresentação/consultas no site;
    # ambas as tabelas originais continuam sem alterações.
    for game in merged:
        game['home_original'] = game['home']
        game['away_original'] = game['away']
        game['home'] = canonical_name(game['home'], decisions)
        game['away'] = canonical_name(game['away'], decisions)
    diagnostics.update(odds_meta)
    diagnostics['legacy_only_games'] = sum(g['odds_source'] == 'odds_jogos' for g in merged)
    diagnostics['without_any_odds'] = sum(not any(g.get(k) is not None for k in QUOTE_MAP.values()) for g in merged)
    seasons = sorted({g['season'] for g in merged},key=_season_key,reverse=True)
    clubs_from_history = sorted({g['home'] for g in merged}|{g['away'] for g in merged},key=lambda x:x.casefold())
    return tuple(merged), seasons, clubs_from_history, diagnostics, pending, unresolved


def reconciliation_options(competition_id: int) -> dict:
    _games, _seasons, _clubs, diagnostics, pending, unresolved = _source(competition_id, _bucket())
    return {'competition_id':competition_id, 'pending_count':len(pending),
            'pending':pending, 'unresolved':unresolved, 'odds_reconciliation':diagnostics}


def save_reconciliation(competition_id: int, historico_jogos: str,
                        historico_odds: str, nome_padrao: str) -> dict:
    # Somente pares encontrados no cruzamento real podem ser aprovados.
    _games, _seasons, _clubs, _diagnostics, pending, _unresolved = _source(competition_id, _bucket())
    key = (normalize_name(historico_jogos), normalize_name(historico_odds))
    if not any((normalize_name(r['historico_jogos']),normalize_name(r['historico_odds'])) == key
               for r in pending):
        raise ValueError('Esta divergência não está pendente. Atualize a lista e tente novamente.')
    record = save_mapping(competition_id, historico_jogos, historico_odds, nome_padrao)
    _source.cache_clear()
    from .backtesting_filter_service import clear_cache
    clear_cache()
    return {'saved':record, **reconciliation_options(competition_id)}

def save_manual_fixture(competition_id: int, data: str, temporada: str,
                        jogos_casa: str, jogos_fora: str, odds_casa: str,
                        odds_fora: str, posicao: str, nome_padrao: str) -> dict:
    if posicao not in ('casa', 'fora'):
        raise ValueError('Selecione mandante ou visitante.')
    meta = _competition(competition_id)
    games, _seasons, _clubs, _diag, _pending, unresolved = _source(competition_id, _bucket())
    # Exigir que a partida de origem ainda figure na fila de revisão.
    key = (date_code(data), season_code(temporada), jogos_casa.strip(), jogos_fora.strip())
    if not any((r['data'],r['temporada'],r['jogos_casa'],r['jogos_fora']) == key and
               any(c['odds_casa']==odds_casa.strip() and c['odds_fora']==odds_fora.strip()
                   for c in r['candidatos']) for r in unresolved):
        raise ValueError('Este confronto já não está pendente ou não é candidato. Atualize a lista.')
    # Os candidatos foram produzidos do banco original no mesmo campeonato,
    # temporada e data; nenhuma semelhança é tomada como verdade sem confirmação.
    chosen_game = jogos_casa if posicao == 'casa' else jogos_fora
    chosen_odd = odds_casa if posicao == 'casa' else odds_fora
    if chosen_game.strip() == chosen_odd.strip():
        raise ValueError('Os nomes nesta posição são iguais; selecione a posição divergente.')
    record = save_mapping(competition_id, chosen_game, chosen_odd, nome_padrao)
    _source.cache_clear()
    from .backtesting_filter_service import clear_cache
    clear_cache()
    return {'saved':record, **reconciliation_options(competition_id)}

def options(competition_id: int, use_odds: bool = True):
    # A cascata de filtros não precisa carregar todas as partidas e odds.
    from .backtesting_filter_service import options as fast_options
    return fast_options(competition_id, use_odds)


def league_options(country_id: int | None = None, competition_id: int | None = None,
                   use_odds: bool = True, league_country: str | None = None,
                   league_competition: str | None = None,
                   league_continent: str | None = None) -> dict:
    from .backtesting_filter_service import league_options as fast_league_options
    return fast_league_options(country_id, competition_id, use_odds, league_country, league_competition, league_continent)


def _sample_games(competition_ids: list[int], use_odds: bool) -> tuple[list[dict], list[str], dict]:
    games: list[dict] = []
    seasons: set[str] = set()
    diagnostics = {
        'status': 'ok', 'database': None,
        'odds_rows': 0, 'matched_games': 0, 'ambiguous_games': 0,
        'unmatched_games': 0, 'legacy_only_games': 0,
        'without_any_odds': 0, 'games_total': 0,
    }
    for comp_id in competition_ids:
        meta = _competition(comp_id)
        rows, comp_seasons, _clubs, diag, _pending, _unresolved = _source(comp_id, _bucket())
        for row in rows:
            game = {**row, 'competition_id': comp_id,
                    'competition': meta['competition'], 'country': meta['country']}
            games.append(game)
        seasons.update(comp_seasons)
        for key in ('odds_rows', 'matched_games', 'ambiguous_games', 'unmatched_games',
                    'legacy_only_games', 'without_any_odds', 'games_total'):
            diagnostics[key] += int(diag.get(key) or 0)
        if diag.get('status') not in (None, 'ok'):
            diagnostics['status'] = diag.get('status')
            diagnostics['database'] = diag.get('database')
    if use_odds:
        filtered = []
        for game in games:
            if game.get('odds_source') == 'historico_odds':
                filtered.append({**game, **(game.get('historico_odds_quotes') or {})})
        games = filtered
    else:
        games = _history_only(games)
    return games, sorted(seasons, key=_season_key, reverse=True), diagnostics


def _base_games(all_games, club: str, season: str | None, focus: str, venue: str | None, opponent: str | None,
                divisao: str | None = None, formato: str | None = None):
    games = [g for g in all_games if not season or season == 'all' or g['season_key'] >= _season_key(season)]
    if divisao:
        games = [g for g in games if normalize_name(str(g.get('divisao') or '')) == normalize_name(divisao)]
    if formato:
        games = [g for g in games if normalize_name(str(g.get('formato') or '')) == normalize_name(formato)]
    if club:
        target = normalize_name(club)
        def contains(g):
            h = normalize_name(g['home']) == target
            a = normalize_name(g['away']) == target
            if focus == 'home' or venue == 'home': return h
            if focus == 'away' or venue == 'away': return a
            return h or a
        games = [g for g in games if contains(g)]
    if opponent:
        opp = normalize_name(opponent)
        games = [g for g in games if normalize_name(g['home']) == opp or normalize_name(g['away']) == opp]
    return games


def _market_evaluation(g, market: str, club: str, focus: str):
    """(is_applicable, success, observed back odd). Lay quote intentionally None."""
    gh, ga = g['gh'],g['ga']
    h_target = bool(club and normalize_name(g['home']) == normalize_name(club))
    a_target = bool(club and normalize_name(g['away']) == normalize_name(club))
    home_scope = not club or h_target
    away_scope = not club or a_target
    if focus == 'home': home_scope,away_scope=True,True # filtered fixtures already fix club at home
    if focus == 'away': home_scope,away_scope=True,True
    if market=='back_home': return home_scope, gh>ga, g['home_odd']
    if market=='lay_home': return home_scope, gh<=ga, g.get('lay_home_odd')
    if market=='draw': return True,gh==ga,g['draw_odd']
    if market=='back_away': return away_scope,ga>gh,g['away_odd']
    if market=='lay_away': return away_scope,ga<=gh,g.get('lay_away_odd')
    if market=='over05': return True,gh+ga>=1,g.get('over05_odd')
    if market=='over15': return True,gh+ga>=2,g.get('over15_odd')
    if market=='over25': return True,gh+ga>=3,g['over25_odd']
    if market=='under35': return True,gh+ga<=3,g.get('under35_odd')
    if market=='btts': return True,gh>0 and ga>0,g.get('btts_odd')
    # Goleada means winning and scoring four goals, *not* 4-goal margin.
    if market=='lay_big_home': return home_scope,not(gh>ga and gh>=4),g.get('lay_big_home_odd')
    if market=='lay_big_away': return away_scope,not(ga>gh and ga>=4),g.get('lay_big_away_odd')
    return False,False,None


def _range_matches(odd, bounds) -> bool:
    low,high = bounds or (None,None)
    if low is None and high is None:return True
    if odd is None:return False
    return (low is None or odd>=low) and (high is None or odd<=high)


def _match_market_filter(g, market, filters):
    # Price conditions only apply to their named market. No conversion of back to lay odds.
    if market in ('back_home','lay_home','back_away','lay_away','draw','lay_big_home','lay_big_away'):
        # Lay odds unavailable: use the corresponding Back *price* only as a match selection filter.
        quote = g['home_odd'] if market in ('back_home','lay_home','lay_big_home') else g['away_odd'] if market in ('back_away','lay_away','lay_big_away') else g['draw_odd']
        return _range_matches(quote,filters.get('mo'))
    if market=='over05':return _range_matches(g.get('over05_odd'),filters.get('over05'))
    if market=='under35':return _range_matches(g.get('under35_odd'),filters.get('under35'))
    if market=='over25':return _range_matches(g['over25_odd'],filters.get('over25'))
    if market=='over15':return _range_matches(g.get('over15_odd'),filters.get('over15'))
    if market=='btts':return _range_matches(g.get('btts_odd'),filters.get('btts'))
    return True


def _valid_quote(odd):
    try:
        return odd is not None and 1.001 < float(odd) <= 1000
    except (ValueError, TypeError, OverflowError):
        return False


def _net_profit(market: str, success: bool, odd: float) -> float:
    """Back: stake R$100; Lay: responsabilidade fixa R$100 (sem comissão)."""
    if MARKET_BY_KEY[market][1] == 'lay':
        return round(STAKE / (float(odd) - 1) if success else -STAKE, 2)
    return round(STAKE * (float(odd) - 1) if success else -STAKE, 2)


def _summary(games, market, club, focus, filters):
    entries, wins, settled, profit, odds_sum, odds_count = 0,0,0,0.0,0.0,0
    yearly = defaultdict(lambda: defaultdict(lambda:{'n':0,'wins':0,'bets':0,'profit':0.0}))
    for g in games:
        relevant,success,odd = _market_evaluation(g,market,club,focus)
        if not relevant or not _match_market_filter(g,market,filters):continue
        weight=int(g.get('_weight', 1))
        entries+=weight
        wins+=int(success)*weight
        month=str(g['date'])[:7]
        year=int(g['year'])
        r=yearly[year][month]
        r['n']+=weight;r['wins']+=int(success)*weight
        # L/P somente com a odd real do próprio mercado. Nunca usa Back como Lay.
        if _valid_quote(odd):
            settled+=weight
            delta=_net_profit(market,success,float(odd))
            profit+=delta*weight;odds_sum+=float(odd)*weight;odds_count+=weight
            r['bets']+=weight;r['profit']+=delta*weight
    rate=(wins/entries*100) if entries else None
    # At a Back market, odds must be >= 1/p. For Lay, the *maximum* Lay odd is 1/(1 - p_lay).
    p=wins/entries if entries else None
    if p is None: fair=None
    elif MARKET_BY_KEY[market][1]=='lay':fair=round(1/(1-p),3) if p<1 else None
    else:fair=round(1/p,3) if p>0 else None
    # The market is analytically observed even if there are no odds, but P/L is not estimated.
    result={
        'key':market,'name':MARKET_BY_KEY[market][0], 'kind':MARKET_BY_KEY[market][1],
        'games':entries,'wins':wins,'losses':entries-wins,
        'rate':round(rate,2) if rate is not None else None,'breakeven_odd':fair,
        'breakeven_type':'max' if MARKET_BY_KEY[market][1]=='lay' else 'min',
        'settled':settled, 'unpriced':entries-settled,
        'profit':round(profit,2) if settled else None,
        'stakes':round(profit/STAKE,2) if settled else None,
        'avg_odd':round(odds_sum/odds_count,3) if odds_count else None,
        'years':{},
    }
    for year,months in yearly.items():
        per_month=[]
        for month,row in sorted(months.items()):
            per_month.append({'month':month,'games':row['n'],'wins':row['wins'],
              'settled':row['bets'],'profit':round(row['profit'],2) if row['bets'] else None,
              'stakes':round(row['profit']/STAKE,2) if row['bets'] else None})
        bets=sum(r['bets'] for r in months.values())
        cash=sum(r['profit'] for r in months.values())
        result['years'][str(year)]={'games':sum(r['n'] for r in months.values()),
            'wins':sum(r['wins'] for r in months.values()),'settled':bets,
            'profit':round(cash,2) if bets else None,
            'stakes':round(cash/STAKE,2) if bets else None,'months':per_month}
    return result


def _odds_bounds(raw):
    filters={}
    for key in ('mo','over05','over15','over25','under35','btts'):
        a,b=raw.get(key+'_min'),raw.get(key+'_max')
        a=float(a) if a is not None else None
        b=float(b) if b is not None else None
        if (a is not None and a<=1) or (b is not None and b<=1):
            raise ValueError('As odds precisam ser maiores que 1,00.')
        if a is not None and b is not None and a>b:
            raise ValueError(f'Intervalo inválido: odd mínima maior que máxima ({key}).')
        filters[key]=(a,b)
    return filters


def _correct_scores(games):
    tally=Counter()
    for g in games:
        tally[(g['gh'],g['ga'])] += int(g.get('_weight',1))
    total=sum(int(g.get('_weight',1)) for g in games)
    ordered=sorted((score for score in SCORES if tally[score]>0),key=lambda s:(-tally[s],s[0]+s[1],s[0],s[1]))
    known=sum(tally[k] for k in SCORES)
    out=[{'score':f'{h} × {a}', 'games':tally[h,a], 'percentage':round(100*tally[h,a]/total,2) if total else 0} for h,a in ordered]
    if total-known: out.append({'score':'Outros placares','games':total-known,'percentage':round(100*(total-known)/total,2)})
    return {'total':total,'scores':out}




# A conferência respeita a aba: em abas de mercado exibe apenas aquela entrada;
# em Resultado por Time permite escolher um dos doze mercados dos cards.
AUDIT_MARKETS = [(key, name) for key, name, _kind in MARKETS]


def _audit_games(games, filters, club='', focus='any', market_keys=None, per_market=40, use_odds=True):
    """Conferência do mercado/aba e dos mesmos filtros do backtest.

    Lay sem odd apresenta taxa de acerto observada, nunca lucro fictício.
    Em Back sem odd, não houve entrada com cotação: a partida não entra na lista.
    """
    chosen = [key for key in (market_keys or [key for key, _ in AUDIT_MARKETS])
              if key in MARKET_BY_KEY]
    out = {key: [] for key in chosen}
    totals = {key: {'games': 0, 'wins': 0} for key in chosen}
    # Acumulados no sentido cronológico; a apresentação segue do mais recente ao antigo.
    for g in sorted(games, key=lambda row: (row['date'], row.get('home',''))):
        for key in chosen:
            relevant, success, odd = _market_evaluation(g, key, club, focus)
            if not relevant or not _match_market_filter(g, key, filters):
                continue
            priced = use_odds and _valid_quote(odd)
            if use_odds and MARKET_BY_KEY[key][1] == 'back' and not priced:
                continue
            totals[key]['games'] += 1
            totals[key]['wins'] += int(success)
            out[key].append({
                'date': g['date'], 'season': g['season'],
                'divisao':g.get('divisao') or None,'formato':g.get('formato') or None,
                'home': g['home'], 'away': g['away'],
                'score': f"{g['gh']} × {g['ga']}",
                'odd': round(float(odd), 3) if priced else None,
                'green': bool(success), 'priced': bool(priced),
                'profit': _net_profit(key,success,float(odd)) if priced else None,
                'cumulative_rate': round(100*totals[key]['wins']/totals[key]['games'], 2),
                'cumulative_games': totals[key]['games'],
            })
    for key in chosen:
        out[key] = list(reversed(out[key][-per_market:]))
    return {'markets':[{'key':key,'label':MARKET_BY_KEY[key][0]} for key in chosen],
            'default_market':chosen[0] if chosen else None,
            'games':out}



# A seleção de faixas é exploratória, com limites predefinidos para reduzir
# a sobre-otimização. A partida sempre é avaliada com a odd real do mercado.
# Sem cotação Lay, a odd Back é usada SOMENTE para segmentar partidas.
SUGGESTION_REFERENCE = {
    'back_home': ('home_odd', 'mo', 'Odd Back casa'),
    'lay_home': ('home_odd', 'mo', 'Odd Back casa (filtro; NÃO é odd Lay)'),
    'draw': ('draw_odd', 'mo', 'Odd Back empate'),
    'back_away': ('away_odd', 'mo', 'Odd Back fora'),
    'lay_away': ('away_odd', 'mo', 'Odd Back fora (filtro; NÃO é odd Lay)'),
    'over05': ('over05_odd', 'over05', 'Odd Over 0,5'),
    'over15': ('over15_odd', 'over15', 'Odd Over 1,5'),
    'over25': ('over25_odd', 'over25', 'Odd Over 2,5'),
    'under35': ('under35_odd', 'under35', 'Odd Under 3,5'),
    'btts': ('btts_odd', 'btts', 'Odd Ambos marcam — Sim'),
    'lay_big_home': ('home_odd', 'mo', 'Odd Back casa (filtro; NÃO é odd Lay)'),
    'lay_big_away': ('away_odd', 'mo', 'Odd Back fora (filtro; NÃO é odd Lay)'),
}
SUGGESTION_CUTS = (1.30, 1.60, 2.00, 2.50, 3.00, 4.00, 6.00, 10.00, 20.00, 50.00, 1000.00)
MIN_PRICED_SAMPLE = 20
MIN_HISTORY_SAMPLE = 12


def _suggestion_bucket(odd: float) -> int:
    return bisect_left(SUGGESTION_CUTS, odd)


def _suggestion_evidence(entries: list[dict], market: str, priced: bool) -> dict:
    count = len(entries)
    wins = sum(int(row['success']) for row in entries)
    losses = count - wins
    base = {'games': count, 'wins': wins, 'losses': losses,
            'win_rate': round(100 * wins / count, 2) if count else None}
    # Para Lay, o preço teórico máximo (sem comissão/margem) é 1/(1-p).
    # 100% de Greens NÃO significa Lay infinito/seguro: retornar null.
    if MARKET_BY_KEY[market][1] == 'lay':
        base['fair_lay_odd'] = round(count / losses, 3) if losses else None
    else:
        base['fair_lay_odd'] = None
    if priced and count:
        profit = round(sum(_net_profit(market, r['success'], r['odd']) for r in entries), 2)
        base.update(profit=profit, roi=round(100 * profit / (STAKE * count), 2))
    else:
        base.update(profit=None, roi=None)
    return base


def _suggest_market(games, market: str, club: str, focus: str, filters: dict) -> dict:
    reference_field, filter_key, reference_label = SUGGESTION_REFERENCE[market]
    entries = []
    for g in games:
        applies, success, own_quote = _market_evaluation(g, market, club, focus)
        reference_quote = g.get(reference_field)
        if not applies or not _match_market_filter(g, market, filters) or not _valid_quote(reference_quote):
            continue
        entries.append({
            'date': str(g['date']), 'home': str(g['home']), 'away': str(g['away']),
            'success': bool(success), 'reference': float(reference_quote),
            'odd': float(own_quote) if _valid_quote(own_quote) else None,
            'bucket': _suggestion_bucket(float(reference_quote)),
        })
    entries.sort(key=lambda x: (x['date'], x['home'], x['away']))
    quoted = [g for g in entries if g['odd'] is not None]
    # Apenas dinheiro realizado com preço REAL do próprio mercado permite
    # chamar uma faixa de candidata rentável. A ausência de preços não vira ROI.
    financial = len(quoted) >= MIN_PRICED_SAMPLE
    pool = quoted if financial else entries
    min_sample = MIN_PRICED_SAMPLE if financial else MIN_HISTORY_SAMPLE
    cuts_used = {row['bucket'] for row in pool}
    candidates = []
    for first in sorted(cuts_used):
        for last in range(first, min(first + 5, len(SUGGESTION_CUTS))):
            selected = [r for r in pool if first <= r['bucket'] <= last]
            if len(selected) < min_sample:
                continue
            # Divisão temporal POR faixa, sem sortear nem embaralhar jogos.
            split = max(1, int(len(selected) * 0.70))
            early, later = selected[:split], selected[split:]
            if financial and (len(early) < 14 or len(later) < 6):
                continue
            if not financial and (len(early) < 8 or len(later) < 4):
                continue
            early_metrics = _suggestion_evidence(early, market, financial)
            later_metrics = _suggestion_evidence(later, market, financial)
            all_metrics = _suggestion_evidence(selected, market, financial)
            if financial and (early_metrics['roi'] <= 0 or later_metrics['roi'] <= 0):
                continue
            # Ausência de Lay real: não prometer retorno financeiro.
            # Mostrar faixas apenas como padrões estatísticos observáveis.
            low = min(r['reference'] for r in selected)
            high = max(r['reference'] for r in selected)
            candidates.append({
                'odd_min': low, 'odd_max': high,
                'period_initial': early[0]['date'], 'period_final': later[-1]['date'],
                'training': early_metrics, 'validation': later_metrics, 'total': all_metrics,
                'kind': 'observed_profit' if financial else 'historical_frequency',
                '_first': first, '_last': last,
                '_ids': { (r['date'],r['home'],r['away']) for r in selected },
            })
    if financial:
        # Prefere regularidade de ROI inicial e posterior, além de amostra maior.
        candidates.sort(key=lambda c: (min(c['training']['roi'], c['validation']['roi']),
                                        c['total']['games'], c['validation']['roi']), reverse=True)
    else:
        # Sem odd real: maior suporte amostral, depois taxa posterior.
        candidates.sort(key=lambda c: (c['validation']['win_rate'], c['total']['games']), reverse=True)
    # Evita mostrar 6 intervalos quase iguais com os mesmos jogos.
    distinct = []
    for candidate in candidates:
        if any(len(candidate['_ids'] & previous['_ids']) /
               max(1, len(candidate['_ids'] | previous['_ids'])) > 0.70
               for previous in distinct):
            continue
        distinct.append(candidate)
        if len(distinct) >= 6:
            break
    for item in distinct:
        for private in ('_first','_last','_ids'):
            item.pop(private, None)
    return {
        'key': market, 'label': MARKET_BY_KEY[market][0],
        'reference_label': reference_label, 'filter_key': filter_key,
        'kind': 'observed_profit' if financial else 'historical_frequency',
        'reference_games': len(entries), 'quoted_games': len(quoted),
        'suggestions': distinct,
    }


def _odds_suggestions(games, filters, club='', focus='any', market_keys=None):
    keys = market_keys or [key for key, _label, _kind in MARKETS]
    items = [_suggest_market(games, key, club, focus, filters) for key in keys]
    return {'markets': items, 'default_market': items[0]['key'] if items else None,
            'min_priced_sample': MIN_PRICED_SAMPLE,
            'explanation': 'Faixas pré-definidas; 70% das partidas mais antigas e 30% das mais recentes por faixa. É uma análise exploratória, não previsão nem lucro garantido.'}



def _league_overview(games: list[dict]) -> dict:
    """Indicadores descritivos da temporada selecionada, sem preços simulados."""
    total = sum(int(g.get('_weight',1)) for g in games)
    home = sum((g['gh'] > g['ga']) * int(g.get('_weight',1)) for g in games)
    away = sum((g['ga'] > g['gh']) * int(g.get('_weight',1)) for g in games)
    draws = total - home - away
    goals = sum((g['gh'] + g['ga']) * int(g.get('_weight',1)) for g in games)
    return {
        'games': total,
        'goals': goals,
        'avg_goals': round(goals / total, 2) if total else None,
        'home_wins': home,
        'draws': draws,
        'away_wins': away,
        'home_rate': round(home * 100 / total, 2) if total else None,
        'draw_rate': round(draws * 100 / total, 2) if total else None,
        'away_rate': round(away * 100 / total, 2) if total else None,
        'over25_rate': round(sum((g['gh'] + g['ga'] >= 3) * int(g.get('_weight',1)) for g in games) * 100 / total, 2) if total else None,
        'btts_rate': round(sum((g['gh'] > 0 and g['ga'] > 0) * int(g.get('_weight',1)) for g in games) * 100 / total, 2) if total else None,
    }




def _history_only(games: list[dict] | tuple[dict, ...]) -> list[dict]:
    """Cria uma visão independente de odds sem alterar o cache da fonte original.

    Somente dados de historico_jogos determinam amostra, metadados e resultados.
    """
    cleaned = []
    for original in games:
        game = {**original, **{field: None for field in QUOTE_MAP.values()}}
        # Testes/fixtures antigos podem não possuir o campo history_divisao.
        game['divisao'] = original.get('history_divisao', original.get('divisao'))
        game['formato'] = original.get('history_formato', original.get('formato'))
        game['odds_source'] = None
        cleaned.append(game)
    return cleaned


def _historical_trends(games, club='', focus='any', market_keys=None) -> dict:
    """Mesmas definições de Green/Red, apenas frequência e validação cronológica."""
    items=[]
    for key in (market_keys or [k for k, _, _ in MARKETS]):
        entries=[]
        for g in games:
            applies, green, _odd = _market_evaluation(g, key, club, focus)
            if applies:
                entries.append((str(g['date']), str(g['home']), str(g['away']), bool(green), int(g.get('_weight',1))))
        entries.sort()
        total_games = sum(r[4] for r in entries)
        # Divide por contagem de jogos, mesmo quando a consulta foi agrupada.
        cutoff = max(1, int(total_games*0.70)) if total_games else 0
        early_count = early_wins = late_count = late_wins = 0
        for _date, _home, _away, green, weight in entries:
            early = max(0, min(weight, cutoff - early_count))
            early_count += early
            early_wins += early * int(green)
            late_count += weight-early
            late_wins += (weight-early)*int(green)
        def metrics(count, wins):
            return {'games':count, 'wins':wins, 'losses':count-wins,
                    'win_rate':round(100*wins/count, 2) if count else None}
        items.append({'key':key, 'label':MARKET_BY_KEY[key][0],
                      'initial':metrics(early_count,early_wins),
                      'posterior':metrics(late_count,late_wins),
                      'total':metrics(total_games,early_wins+late_wins),
                      'period_start':entries[0][0] if entries else None,
                      'period_end':entries[-1][0] if entries else None})
    return {'markets':items,
            'explanation':'Taxas descritivas em ordem cronológica (70% inicial e 30% posterior), sem preços, simulações ou rentabilidade. Amostras pequenas podem oscilar.'}


def _league_comparison(games, filters) -> dict:
    grouped: dict[tuple[int | None, str, str], list[dict]] = defaultdict(list)
    for game in games:
        grouped[(game.get('competition_id'), str(game.get('competition') or ''),
                 str(game.get('country') or ''))].append(game)
    markets = []
    for key, label, _kind in MARKETS:
        rows = []
        for (competition_id, competition, country), comp_games in grouped.items():
            summary = _summary(comp_games, key, '', 'any', filters)
            if summary['games'] == 0:
                continue
            roi = round((summary['profit'] or 0) * 100 / (summary['settled'] * STAKE), 2) if summary['settled'] else None
            rows.append({
                'competition_id': competition_id,
                'competition': competition,
                'country': country,
                'games': summary['games'],
                'wins': summary['wins'],
                'losses': summary['losses'],
                'win_rate': summary['rate'],
                'profit': summary['profit'],
                'roi': roi,
                'settled': summary['settled'],
            })
        rows.sort(key=lambda item: ((item['win_rate'] or -1), item['games'], item['competition'].casefold()), reverse=True)
        markets.append({'key': key, 'label': label, 'items': rows})
    return {
        'total_leagues': len(grouped),
        'markets': markets,
        'explanation': 'Comparativo por campeonato no recorte filtrado. Os gráficos usam Win Rate; os valores com odds são calculados apenas com cotações reais conciliadas.'
    }



def league_market_history(payload: dict) -> dict:
    """Série por ano-calendário de uma liga e mercado, somente sob demanda.

    O intervalo de dez anos termina no ano atual. Não depende do intervalo
    do comparativo: o clique sempre consulta o histórico dos últimos dez anos.
    """
    from .league_catalog_service import selected

    country = str(payload.get('country') or '').strip()
    competition = str(payload.get('competition') or '').strip()
    market = str(payload.get('market') or '').strip()
    use_odds = payload.get('use_odds', False)
    divisao = str(payload.get('divisao') or '').strip() or None
    formato = str(payload.get('formato') or '').strip() or None
    if not country or not competition:
        raise ValueError('Informe país e campeonato para consultar os últimos dez anos.')
    if market not in MARKET_BY_KEY:
        raise ValueError('Mercado inválido.')
    if not isinstance(use_odds, bool):
        raise ValueError('O seletor de odds precisa ser verdadeiro ou falso.')
    catalog = selected(country, competition)
    year_end = date.today().year
    year_start = year_end - 9
    filters = _odds_bounds(payload) if use_odds else {k:(None,None) for k in ('mo','over05','over15','over25','under35','btts')}

    if use_odds:
        from .league_bulk_odds_service import load
        games, _diagnostics = load(country, competition, catalog, year_from=year_start, year_to=year_end)
        games = _base_games(games, '', None, 'any', None, None, divisao, formato)
    else:
        from .league_fast_service import grouped_games
        games = grouped_games(country, competition, 'all', divisao, formato, catalog,
                              year_from=year_start, year_to=year_end)
    summary = _summary(games, market, '', 'any', filters)
    years = []
    for year in range(year_start, year_end+1):
        item = summary['years'].get(str(year), {})
        count = int(item.get('games') or 0)
        wins = int(item.get('wins') or 0)
        settled = int(item.get('settled') or 0)
        profit = item.get('profit') if use_odds else None
        years.append({
            'year': year,
            'games': count,
            'wins': wins,
            'losses': count-wins,
            'win_rate': round(wins*100/count,2) if count else None,
            'settled': settled if use_odds else 0,
            'profit': profit,
            'roi': round(100*profit/(settled*STAKE),2) if profit is not None and settled else None,
        })
    return {
        'country': country,
        'competition': competition,
        'market': market,
        'market_label': MARKET_BY_KEY[market][0],
        'use_odds': use_odds,
        'year_from': year_start,
        'year_to': year_end,
        'years': years,
        'total': {
            'games': summary['games'],
            'wins': summary['wins'],
            'losses': summary['losses'],
            'win_rate': summary['rate'],
        },
    }

def _evaluate_fast_leagues(games, payload, filters, season, divisao, formato,
                           catalog=None, country_name=None, include_legacy_panels=True):
    """Mesmo contrato dos painéis, calculado com amostras agregadas.

    Nenhuma cotação ou reconciliação é consultada no modo sem odds.
    A conferência de partidas individuais é omitida neste recorte geral:
    linhas agrupadas não contêm clubes ou datas reais.
    """
    keys=[k for k,_,_ in MARKETS]
    summaries={key:_summary(games,key,'','any',filters) for key in keys}
    years=sorted({int(g['year']) for g in games})
    annual=[{'year':year,'values':{key:(summaries[key]['years'].get(str(year)) or {
        'games':0,'wins':0,'settled':0,'profit':None,'stakes':None,'months':[]}) for key in keys}}
        for year in years]
    count=sum(int(g.get('_weight',1)) for g in games)
    result = {
        'tab':'league','market':None,'markets':summaries,'annual':annual,
        'years':years,'games':count,'club':'','opponent':None,'stake':STAKE,
        'start_season':season,'divisao':divisao,'formato':formato,
        'year_from': payload.get('year_from'), 'year_to': payload.get('year_to'),
        'use_odds':False,'data_source':'historico_jogos','has_odds':False,
        'odds_reconciliation':None,'league_overview':_league_overview(games),
        'scores':_correct_scores(games),
        'league_comparison':_league_comparison(games,filters),
        # O comparativo por campeonato não exibe estas tabelas. O modo legado
        # é preservado apenas para clientes antigos e testes de regressão.
        'historical_trends':_historical_trends(games) if include_legacy_panels else None,
        'odds_audit':None,
        'explanation': ('Comparativo geral calculado diretamente em historico_jogos, '
                        'agrupando resultados por campeonato, temporada, mês e placar. '
                        'Win Rate sem odds, sem estimativa de lucro. '
                        'Conferência detalhada: até 40 jogos recentes por mercado, com WR cumulativo sobre o histórico completo.'),
    }

    if catalog and include_legacy_panels:
        from .league_fast_service import recent_games
        sampled = recent_games(country_name, None, season, divisao, formato, catalog,
                               year_from=payload.get('year_from'), year_to=payload.get('year_to'))
        if sampled:
            audit = _audit_games(sampled, filters, '', 'any', keys, use_odds=False)
            # Win Rate acumulado real de toda a amostra, não apenas dos
            # jogos recentes consultados para exibir nomes e datas.
            for key in keys:
                count = summaries[key]['games']
                wins = summaries[key]['wins']
                for row in audit['games'].get(key, []):
                    row['cumulative_games'] = count
                    row['cumulative_rate'] = round(100*wins/count,2) if count else 0
                    count -= 1
                    wins -= int(row['green'])
            result['odds_audit'] = audit
    return result


def evaluate(payload:dict):
    tab = payload.get('tab') or 'team'
    if tab not in ('league','team','mo_home','mo_away','lay_home','lay_away','lay_big_home','lay_big_away','scores'):
        raise ValueError('Aba inválida.')
    league_mode = tab == 'league'
    continent = str(payload.get('continent') or payload.get('league_continent') or '').strip() or None
    from .continent_service import for_country, CONTINENTS
    if continent and continent not in CONTINENTS:
        raise ValueError('Continente inválido.')
    comp_id = int(payload.get('competition_id') or 0)
    country_id = int(payload.get('country_id') or 0)
    if not league_mode and comp_id < 1:
        raise ValueError('Selecione o campeonato.')
    use_odds = payload.get('use_odds', True)
    statistics_only = payload.get('statistics_only') is True
    if statistics_only and use_odds:
        raise ValueError('A página Estatísticas não aceita odds.')
    if not isinstance(use_odds, bool):
        raise ValueError('O seletor de odds precisa ser verdadeiro ou falso.')
    years = int(payload.get('years') or 3)
    if not 1 <= years <= 30:
        raise ValueError('Informe entre 1 e 30 anos.')
    season = str(payload.get('start_season') or 'all').strip() or 'all'
    year_from, year_to = _calendar_year_range(payload, league_mode)
    divisao = str(payload.get('divisao') or '').strip() or None
    formato = str(payload.get('formato') or '').strip() or None
    filters = _odds_bounds(payload) if use_odds else {k:(None,None) for k in ('mo','over05','over15','over25','under35','btts')}
    focus = 'home' if tab in ('mo_home','mo_away','lay_home','lay_away','lay_big_home','lay_big_away') else 'any'
    chosen_market = {'mo_home':'back_home','mo_away':'back_away','lay_home':'lay_home',
                     'lay_away':'lay_away','lay_big_home':'lay_big_home','lay_big_away':'lay_big_away'}.get(tab)
    keys = [k for k,_,_ in MARKETS]

    if league_mode:
        history_catalog_mode = payload.get('use_history_catalog') is True
        if history_catalog_mode:
            # Os IDs do seletor Liga não são IDs do catálogo ELO.
            # Usa exclusivamente país e nome do campeonato presentes em historico_jogos.
            comp_id = 0
        if comp_id > 0:
            all_games, available_seasons, _available_clubs, diagnostics, _pending, _unresolved = (_history_source(comp_id, _bucket()) if statistics_only else _source(comp_id, _bucket()))
            meta = _competition(comp_id)
            if continent and for_country(meta['country']) != continent:
                raise ValueError('O campeonato selecionado não pertence ao continente.')
            all_games = [{**game, 'competition_id': comp_id,
                          'competition': meta['competition'], 'country': meta['country']} for game in all_games]
            all_games = ([{**g, **(g.get('historico_odds_quotes') or {})} for g in all_games
                          if g.get('odds_source') == 'historico_odds'] if use_odds else _history_only(all_games))
            if season != 'all' and season not in set(available_seasons):
                raise ValueError('Temporada não encontrada no histórico deste campeonato.')
            valid_divisoes = {str(g.get('divisao')).strip() for g in all_games if g.get('divisao') not in (None, '')}
            valid_formatos = {str(g.get('formato')).strip() for g in all_games if g.get('formato') not in (None, '')}
            if divisao and divisao not in valid_divisoes:
                divisao = None
            if formato and formato not in valid_formatos:
                formato = None
            main = _base_games(all_games, '', None, focus, None, None, divisao, formato)
            if season != 'all':
                main = [g for g in main if g['season'] == season]
            main = _filter_calendar_years(main, year_from, year_to)
            annual_games = main
            league_diagnostics = {
                **diagnostics,
                'games_total': len(main),
                'matched_games': sum(g.get('odds_source') == 'historico_odds' for g in main),
                'legacy_only_games': sum(g.get('odds_source') == 'odds_jogos' for g in main),
                'ambiguous_games': sum(g.get('odds_source') == 'ambiguous' for g in main),
                'without_any_odds': sum(not any(g.get(k) is not None for k in QUOTE_MAP.values()) for g in main),
            }
            league_diagnostics['unmatched_games'] = (
                len(main) - league_diagnostics['matched_games'] - league_diagnostics['ambiguous_games']
            )
        else:
            if history_catalog_mode:
                from .league_catalog_service import selected as selected_history
                country_name = str(payload.get('league_country') or '').strip() or None
                competition_name = str(payload.get('league_competition') or '').strip() or None
                comps = selected_history(country_name, competition_name, continent)
            else:
                comps = _competition_catalog(country_id=country_id or None)
                country_name = next((c['country'] for c in comps if c['country_id'] == country_id), None) if country_id else None
                competition_name = None
            if not history_catalog_mode and continent:
                comps = [r for r in comps if for_country(r['country']) == continent]
            if not comps:
                raise ValueError('Nenhum campeonato com jogos encontrado para o recorte selecionado.')
            continent_countries = tuple(sorted({r['country'] for r in comps})) if continent else None
            if not use_odds:
                from .league_fast_service import grouped_games
                if continent_countries is not None:
                    main = grouped_games(country_name, competition_name, season, divisao, formato, comps,
                                         year_from=year_from, year_to=year_to, continent_countries=continent_countries)
                elif year_from is not None or year_to is not None:
                    main = grouped_games(country_name, competition_name, season, divisao, formato, comps,
                                         year_from=year_from, year_to=year_to)
                else:
                    main = grouped_games(country_name, competition_name, season, divisao, formato, comps)
                return _evaluate_fast_leagues(main, payload, filters, season, divisao, formato,
                                              catalog=comps, country_name=country_name,
                                              include_legacy_panels=False)
            from .league_bulk_odds_service import load as load_bulk_odds
            all_games, league_diagnostics = (load_bulk_odds(country_name, competition_name, comps, year_from=year_from, year_to=year_to)
                                              if year_from is not None or year_to is not None
                                              else load_bulk_odds(country_name, competition_name, comps))
            available_seasons = sorted({g['season'] for g in all_games}, key=_season_key, reverse=True)
            valid_divisoes = {str(g.get('divisao')).strip() for g in all_games if g.get('divisao') not in (None, '')}
            valid_formatos = {str(g.get('formato')).strip() for g in all_games if g.get('formato') not in (None, '')}
            if divisao and divisao not in valid_divisoes:
                divisao = None
            if formato and formato not in valid_formatos:
                formato = None
            main = _base_games(all_games, '', None, focus, None, None, divisao, formato)
            if season != 'all':
                main = [g for g in main if g['season'] == season]
            main = _filter_calendar_years(main, year_from, year_to)
            annual_games = main
        main_results = {key:_summary(main,key,'','any',filters) for key in keys}
        annual_results = {key:_summary(annual_games,key,'','any',filters) for key in keys}
        annual_years = sorted({int(g['year']) for g in annual_games})
        def as_annual(results):
            return [{'year':year,'values':{key:(results[key]['years'].get(str(year)) or {
                'games':0,'wins':0,'settled':0,'profit':None,'stakes':None,'months':[]}) for key in keys}}
                for year in annual_years]
        result = {
            'tab': tab,
            'market': chosen_market,
            'markets': main_results,
            'annual': as_annual(annual_results),
            'years': annual_years,
            'games': len(main),
            'club': '',
            'opponent': None,
            'stake': STAKE,
            'start_season': season,
            'year_from': year_from, 'year_to': year_to,
            'divisao': divisao,
            'formato': formato,
            'use_odds': use_odds,
            'data_source': 'historico_odds' if use_odds else 'historico_jogos',
            'has_odds': any(r['settled'] for r in main_results.values()),
            'odds_reconciliation': league_diagnostics if use_odds else None,
            'league_overview': _league_overview(main),
            'scores': _correct_scores(main),
            'league_comparison': _league_comparison(main, filters),
            'explanation': ('Odds conciliadas por país, campeonato, temporada, data, mandante e visitante. '
                            'Divisão/formato vêm do histórico de odds (ou dos jogos, se disponíveis). '
                            'L/P somente com a odd real do próprio mercado. Para Lay, responsabilidade R$ 100 sem comissão; '
                            'sem cotação Lay, apenas win rate histórico.' if use_odds else
                            'Análise baseada apenas em historico_jogos. Todos os resultados são Win Rate (acertos / partidas); '
                            'não há lucro, unidades, ROI ou cotações neste modo.')
        }
        audit_keys = [chosen_market] if chosen_market else [k for k,_,_ in MARKETS]
        if use_odds:
            result['odds_suggestions'] = _odds_suggestions(main, filters, '', 'any', audit_keys)
        else:
            result['historical_trends'] = _historical_trends(main, '', 'any', audit_keys)
        # O catálogo direto do histórico corresponde ao painel moderno (sem a
        # tabela de conferência). Preserva auditoria em clientes antigos.
        result['odds_audit'] = (None if history_catalog_mode else
                               _audit_games(main, filters, '', 'any', audit_keys, use_odds=use_odds))
        if history_catalog_mode and payload.get('league_competition'):
            result['explanation'] += ' Aba Liga: campeonato selecionado diretamente de historico_jogos.'
        elif history_catalog_mode and payload.get('league_country'):
            result['explanation'] += ' Aba Liga: todos os campeonatos encontrados em historico_jogos para o país selecionado.'
        elif history_catalog_mode:
            result['explanation'] += ' Aba Liga: todos os campeonatos encontrados em historico_jogos.'
        elif comp_id > 0:
            result['explanation'] += ' Aba Liga: todos os clubes do campeonato selecionado, respeitando temporada, divisão e formato.'
        elif country_id > 0:
            result['explanation'] += ' Aba Liga: comparativo entre os campeonatos do país selecionado, respeitando temporada, divisão e formato.'
        else:
            result['explanation'] += ' Aba Liga: comparativo geral entre todos os campeonatos cadastrados, respeitando temporada, divisão e formato.'
        return result

    # Demais abas exigem um campeonato específico.
    if continent and for_country(_competition(comp_id)['country']) != continent:
        raise ValueError('O campeonato selecionado não pertence ao continente.')
    all_games, _, available_clubs, diagnostics, _pending, _unresolved = (_history_source(comp_id, _bucket()) if statistics_only else _source(comp_id, _bucket()))
    available_seasons = {g['season'] for g in all_games}
    all_games = ([{**g, **(g.get('historico_odds_quotes') or {})} for g in all_games
                  if g.get('odds_source') == 'historico_odds'] if use_odds else _history_only(all_games))
    club = (payload.get('club') or '').strip()
    opponent = (payload.get('opponent') or '').strip()
    if tab == 'team' and not club:
        raise ValueError('Selecione o clube para Resultado por Time.')
    if club and normalize_name(club) not in {normalize_name(c) for c in available_clubs}:
        raise ValueError('Clube não encontrado no histórico deste campeonato.')
    if opponent and not club:
        raise ValueError('Selecione um clube antes do adversário.')
    if opponent and normalize_name(opponent) == normalize_name(club):
        raise ValueError('Clube e adversário devem ser diferentes.')
    games = _base_games(all_games, club, season, focus, None, None, divisao, formato)
    h2h = _base_games(all_games, club, season, focus, None, opponent, divisao, formato) if opponent else []
    annual_games = _base_games(all_games, club, None, focus, None, None, divisao, formato)
    annual_h2h = _base_games(all_games, club, None, focus, None, opponent, divisao, formato) if opponent else []
    main = games
    main_results = {key:_summary(main,key,club,focus,filters) for key in keys}
    h2h_results = {key:_summary(h2h,key,club,focus,filters) for key in keys} if opponent else None
    annual_results = {key:_summary(annual_games,key,club,focus,filters) for key in keys}
    annual_h2h_results = {key:_summary(annual_h2h,key,club,focus,filters) for key in keys} if opponent else None
    current_year = date.today().year
    annual_years = list(range(current_year-years+1,current_year+1))
    def as_annual(results):
        return [{'year':year,'values':{key:(results[key]['years'].get(str(year)) or {
            'games':0,'wins':0,'settled':0,'profit':None,'stakes':None,'months':[]}) for key in keys}}
            for year in annual_years]
    result = {'tab':tab,'market':chosen_market,'markets':main_results,'annual':as_annual(annual_results),
        'years':annual_years,'games':len(main),'club':club,'opponent':opponent or None,
        'stake':STAKE,'start_season':season or 'all','divisao':divisao,'formato':formato,
        'use_odds':use_odds,'data_source':'historico_odds' if use_odds else 'historico_jogos',
        'has_odds':any(r['settled'] for r in main_results.values()),
        'odds_reconciliation':diagnostics if use_odds else None,
        'explanation':'Odds conciliadas por país, campeonato, temporada, data, mandante e visitante. Divisão/formato vêm do histórico de odds (ou dos jogos, se disponíveis). L/P somente com a odd real do próprio mercado. Para Lay, responsabilidade R$ 100 sem comissão; sem cotação Lay, apenas win rate histórico.',
    }
    if not use_odds:
        result['explanation'] = ('Análise baseada apenas em historico_jogos. Todos os resultados são Win Rate (acertos / partidas); '
                                 'não há lucro, unidades, ROI ou cotações neste modo.')
    audit_games = h2h if opponent else main
    audit_keys = [chosen_market] if chosen_market else [k for k,_,_ in MARKETS]
    if use_odds:
        result['odds_suggestions'] = _odds_suggestions(audit_games, filters, club, focus, audit_keys)
    else:
        result['historical_trends'] = _historical_trends(audit_games, club, focus, audit_keys)
    result['odds_audit'] = _audit_games(audit_games, filters, club, focus, audit_keys, use_odds=use_odds)
    if tab == 'scores':
        result['scores'] = _correct_scores(main)
    if opponent:
        result['head_to_head'] = {'games':len(h2h), 'markets':h2h_results,
             'annual':as_annual(annual_h2h_results) if annual_h2h_results is not None else [],
             'scores':_correct_scores(h2h)}
    return result

