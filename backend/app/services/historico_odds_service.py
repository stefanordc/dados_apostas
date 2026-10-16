"""Conciliação conservadora de odds históricas com placares reais.

Nenhum placar é gravado em `historico_odds`; o join é feito em memória, por
país+competição (filtrados no SQL), temporada, data, mandante E visitante.
Nomes alternativos conhecidos podem ser conciliados por ID cadastrado.
Combinações ambíguas nunca são liquidadas.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any
import re

from sqlalchemy import text
from ..db import app_engine, history_connection
from .elo_service import normalize_name

# Colunas Lay opcionais: não existem no esquema fornecido; só são utilizadas
# se o usuário vier a cadastrá-las com odds Lay reais.
LAY_OPTIONAL_COLUMNS = ('lay_casa', 'lay_fora', 'lay_goleada_casa', 'lay_goleada_fora')
ODD_COLUMNS = (
    'odd_casa', 'odd_empate', 'odd_fora',
    'over_0_5', 'under_0_5', 'over_1_5', 'under_1_5',
    'over_2_5', 'under_2_5', 'over_3_5', 'under_3_5',
    'over_4_5', 'under_4_5', 'ambos_marcam_sim', 'ambos_marcam_nao',
)
QUOTE_MAP = {
    'odd_casa': 'home_odd', 'odd_empate': 'draw_odd', 'odd_fora': 'away_odd',
    'over_0_5': 'over05_odd', 'under_0_5': 'under05_odd',
    'over_1_5': 'over15_odd', 'under_1_5': 'under15_odd',
    'over_2_5': 'over25_odd', 'under_2_5': 'under25_odd',
    'over_3_5': 'over35_odd', 'under_3_5': 'under35_odd',
    'over_4_5': 'over45_odd', 'under_4_5': 'under45_odd',
    'ambos_marcam_sim': 'btts_odd', 'ambos_marcam_nao': 'btts_no_odd',
    'lay_casa': 'lay_home_odd', 'lay_fora': 'lay_away_odd',
    'lay_goleada_casa': 'lay_big_home_odd', 'lay_goleada_fora': 'lay_big_away_odd',
}
REQUIRED = {'data', 'pais', 'campeonato', 'temporada', 'casa', 'fora'}
OPTIONAL_DIMENSIONS = ('divisao', 'formato')


def season_code(raw: Any) -> str:
    s = str(raw or '').strip()
    m = re.fullmatch(r'(\d{4})(?:\s*[/\-]\s*(\d{2,4}))?', s)
    if not m:
        return s.casefold()
    start = int(m[1]); end = m[2]
    if end is None:
        return str(start)
    year = int(end)
    if len(end) == 2:
        year += (start//100)*100
        if year < start: year += 100
    return f'{start}/{year}'


def date_code(value: Any) -> str:
    if value is None: return ''
    if isinstance(value, (date, datetime)): return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    s = str(value).strip()
    if not s: return ''
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', s):
        try: return datetime.strptime(s, '%d/%m/%Y').date().isoformat()
        except ValueError: return ''
    try: return date.fromisoformat(s[:10]).isoformat()
    except ValueError: return ''


def odd_value(raw: Any) -> float | None:
    if raw is None or str(raw).strip() in ('', '-', '—', 'None'):
        return None
    s = str(raw).strip().replace(' ', '').replace('\u00a0', '')
    if ',' in s:
        if '.' in s and s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '.')
    try:
        number = float(Decimal(s))
    except (ValueError, InvalidOperation, OverflowError):
        return None
    return number if isfinite(number) and 1.0 < number <= 1000 else None


def _quotation(row: dict) -> dict:
    return {dest: odd_value(row.get(src)) for src, dest in QUOTE_MAP.items()}


def _identity(row: dict) -> tuple:
    return (season_code(row.get('temporada') or row.get('season')),
            date_code(row.get('data') or row.get('date')))


def canonical_name(value: str, decisions: dict[str, str] | None = None) -> str:
    return (decisions or {}).get(normalize_name(value), value)


def _game_names(row: dict, odds: bool, decisions: dict[str, str] | None = None) -> tuple[str, str]:
    if odds:
        home, away = str(row.get('casa') or ''), str(row.get('fora') or '')
    else:
        home, away = str(row.get('home') or ''), str(row.get('away') or '')
    return (normalize_name(canonical_name(home, decisions)),
            normalize_name(canonical_name(away, decisions)))


def _approved(game_name: str, odd_name: str, decisions: dict[str, str],
              names: dict[str, int]) -> bool:
    if game_name.strip() == odd_name.strip():
        return True
    gkey, okey = normalize_name(game_name), normalize_name(odd_name)
    # Mesma grafia normalizada não é autorização para escolher nome de exibição.
    if gkey in decisions and okey in decisions:
        if normalize_name(decisions[gkey]) == normalize_name(decisions[okey]):
            return True
    # Mesmo que o cadastro de clubes saiba os IDs, uma nova divergência
    # entre as DUAS fontes exige escolha de nome padrão no site.
    return False


def _pair_approved(game: dict, row: dict, decisions: dict[str, str],
                   names: dict[str, int]) -> bool:
    return (_approved(str(game.get('home') or ''), str(row.get('casa') or ''), decisions, names)
            and _approved(str(game.get('away') or ''), str(row.get('fora') or ''), decisions, names))


def pending_name_pairs(games: list[dict], rows: list[dict],
                       decisions: dict[str, str] | None = None,
                       names: dict[str, int] | None = None) -> list[dict]:
    """Sugestões de conciliação por jogo; nunca aprova nem funde clubes por similaridade.

    Só compara mesma data + temporada. Se houver vários confrontos na mesma
    data, exige pelo menos um lado reconhecível e candidato único.
    """
    decisions, names = decisions or {}, names or {}
    by_day: dict[tuple, list[dict]] = defaultdict(list)
    games_by_day: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if all(_identity(row)):
            by_day[_identity(row)].append(row)
    for game in games:
        if all(_identity(game)):
            games_by_day[_identity(game)].append(game)
    found: dict[tuple, dict] = {}
    for game in games:
        if game.get('odds_source') == 'historico_odds':
            continue
        identity = _identity(game)
        possible = by_day.get(identity, [])
        if not possible:
            continue
        gh, ga = _game_names(game, False, decisions)
        ranked = []
        seen_fixtures = set()
        for row in possible:
            signature = (str(row.get('casa') or ''), str(row.get('fora') or ''))
            if signature in seen_fixtures:
                continue
            seen_fixtures.add(signature)
            oh, oa = _game_names(row, True, decisions)
            # Maior prioridade: ao menos um clube já reconhecido no confronto.
            score = int(gh == oh or (names.get(gh) is not None and names.get(gh) == names.get(oh)))
            score += int(ga == oa or (names.get(ga) is not None and names.get(ga) == names.get(oa)))
            ranked.append((score, row))
        if not ranked:
            continue
        best_score = max(score for score, _ in ranked)
        candidates = [row for score, row in ranked if score == best_score]
        # Se as duas fontes contiverem somente um jogo no dia, mostrar como
        # sugestão de BAIXA certeza para confirmação humana, sem vínculo automático.
        unique_day = len(games_by_day.get(identity, [])) == 1 and len(seen_fixtures) == 1
        if (best_score < 1 and not unique_day) or len(candidates) != 1:
            continue
        odd = candidates[0]
        if _pair_approved(game, odd, decisions, names):
            continue
        for side, game_field, odd_field in [('casa','home','casa'),('fora','away','fora')]:
            game_label = str(game.get(game_field) or '').strip()
            odds_label = str(odd.get(odd_field) or '').strip()
            if not game_label or not odds_label or _approved(game_label, odds_label, decisions, names):
                continue
            key = (normalize_name(game_label), normalize_name(odds_label), side)
            if key not in found:
                found[key] = {'historico_jogos':game_label, 'historico_odds':odds_label,
                              'posicao':side, 'ocorrencias':0,
                              'exemplo_data':date_code(game.get('date')),
                              'exemplo_jogo':f"{game.get('home')} × {game.get('away')}",
                              'exemplo_odds':f"{odd.get('casa')} × {odd.get('fora')}",
                              'confianca':'verificar' if best_score == 0 else 'alta'}
            found[key]['ocorrencias'] += 1
    return sorted(found.values(), key=lambda row:(-row['ocorrencias'],row['historico_jogos'].casefold()))

def unresolved_fixture_matches(games: list[dict], rows: list[dict],
                               decisions: dict[str, str] | None = None,
                               names: dict[str, int] | None = None) -> list[dict]:
    """Partidas com possíveis cotações no mesmo dia, mas associação não única.

    A pessoa deverá escolher qual jogo em odds corresponde ao jogo do histórico.
    Nenhuma dessas sugestões participa dos cálculos ou é aceita automaticamente.
    """
    decisions, names = decisions or {}, names or {}
    by_day = defaultdict(dict)
    games_by_day = defaultdict(list)
    for row in rows:
        if all(_identity(row)):
            by_day[_identity(row)][(str(row.get('casa')),str(row.get('fora')))] = row
    for game in games:
        if all(_identity(game)):
            games_by_day[_identity(game)].append(game)
    unresolved = []
    for game in games:
        if game.get('odds_source') == 'historico_odds':
            continue
        identity = _identity(game)
        candidates = list(by_day.get(identity, {}).values())
        if not candidates or any(_pair_approved(game, row, decisions, names) for row in candidates):
            continue
        gh, ga = _game_names(game, False, decisions)
        scores = []
        for row in candidates:
            oh, oa = _game_names(row, True, decisions)
            score = int(gh == oh or (names.get(gh) is not None and names.get(gh) == names.get(oh)))
            score += int(ga == oa or (names.get(ga) is not None and names.get(ga) == names.get(oa)))
            scores.append(score)
        top = max(scores)
        if (top > 0 and scores.count(top) == 1) or (len(games_by_day[identity]) == 1 and len(candidates) == 1):
            # Este caso já aparece nas divergências de nomes simples.
            continue
        unresolved.append({
            'data':identity[1], 'temporada':identity[0],
            'jogos_casa':str(game.get('home') or ''),
            'jogos_fora':str(game.get('away') or ''),
            'candidatos':[{'odds_casa':str(row.get('casa') or ''),
                           'odds_fora':str(row.get('fora') or '')}
                          for row in candidates],
        })
    return unresolved

def _dedup(candidates: list[dict]) -> dict | None:
    # Identical repeated imports can be safely collapsed; differing prices are ambiguous.
    if not candidates: return None
    # Two prices with the same fixture but different labels are ambiguous too.
    signatures = {(tuple(_quotation(r).items()), tuple((c, str(r.get(c) or '').strip()) for c in OPTIONAL_DIMENSIONS)) for r in candidates}
    return candidates[0] if len(signatures) == 1 else None


def reconcile(games: list[dict], rows: list[dict], name_to_id: dict[str, int] | None = None,
              decisions: dict[str, str] | None = None) -> dict:
    """Attach prices to games without altering scores. Mutates only in-memory games."""
    names, decisions = name_to_id or {}, decisions or {}
    by_text = defaultdict(list)
    by_id = defaultdict(list)
    for row in rows:
        identity = _identity(row)
        home, away = _game_names(row, True, decisions)
        if not all(identity) or not home or not away: continue
        by_text[(*identity, home, away)].append(row)
        hid, aid = names.get(home), names.get(away)
        if hid is not None and aid is not None:
            by_id[(*identity, hid, aid)].append(row)

    matched = ambiguous = no_match = 0
    for game in games:
        identity = _identity(game)
        home, away = _game_names(game, False, decisions)
        candidates = by_text.get((*identity, home, away), [])
        if not candidates:
            hid, aid = names.get(home), names.get(away)
            if hid is not None and aid is not None:
                candidates = by_id.get((*identity, hid, aid), [])
        # Não confiar numa coincidência fonética ou normalização automática.
        # Ambas as diferenças devem ser aprovadas pelo usuário previamente.
        candidates = [row for row in candidates if _pair_approved(game, row, decisions, names)]
        if not candidates:
            no_match += 1
            continue
        found = _dedup(candidates)
        if found is None:
            ambiguous += 1
            game['odds_source'] = 'ambiguous'
            for price_field in QUOTE_MAP.values(): game[price_field] = None
            continue
        new_prices = _quotation(found)
        # Preserve a snapshot of JUST historico_odds quotations for the strict mode.
        # Existing merged fallback values remain available to other legacy callers.
        game['historico_odds_quotes'] = new_prices
        game.update({key: val if val is not None else game.get(key) for key,val in new_prices.items()})
        for dim in OPTIONAL_DIMENSIONS:
            # Descriptive metadata; never overwrite with empty values.
            val = str(found.get(dim) or '').strip()
            if val: game[dim] = val
        game['odds_source'] = 'historico_odds'
        matched += 1
    return {'source': 'historico_odds', 'odds_rows': len(rows), 'matched_games': matched,
            'ambiguous_games': ambiguous, 'unmatched_games': no_match, 'games_total': len(games)}


def _table_exists(conn) -> bool:
    return bool(conn.execute(text("SELECT to_regclass('public.historico_odds') IS NOT NULL")).scalar())


def _required_columns(conn) -> bool:
    cols = {r[0] for r in conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='historico_odds'
    """)).all()}
    return REQUIRED.issubset(cols)


def load_historical_odds(country: str, competition: str) -> tuple[list[dict], dict]:
    """Find the public table in the write database, or the read-only history database.

    A missing table does not break the page: older odds_jogos remains available.
    """
    found_table_at = None
    for label, opener in [('principal', app_engine.connect), ('historico', history_connection)]:
        with opener() as conn:
            if not _table_exists(conn):
                continue
            found_table_at = label
            if not _required_columns(conn):
                return [], {'status': 'schema_incompleto', 'database': label}
            present_columns = {r[0] for r in conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='public' AND table_name='historico_odds'
            """)).all()}
            cols = ', '.join(['data','pais','campeonato','temporada','casa','fora',
                              *ODD_COLUMNS, *[c for c in LAY_OPTIONAL_COLUMNS if c in present_columns],
                              *[c for c in OPTIONAL_DIMENSIONS if c in present_columns]])
            # Scope to one competition before transferring rows. No writes on either DB.
            rows = [dict(r) for r in conn.execute(text(f"""
                SELECT {cols} FROM public.historico_odds
                WHERE lower(btrim(pais::text)) = lower(btrim(:pais))
                  AND lower(btrim(campeonato::text)) = lower(btrim(:campeonato))
            """), {'pais': country, 'campeonato': competition}).mappings()]
            # Resolve também campeonatos com acentos diferentes (Inglês/Ingles).
            if not rows:
                possible = [dict(r) for r in conn.execute(text(f"""
                    SELECT {cols} FROM public.historico_odds
                    WHERE lower(btrim(pais::text)) = lower(btrim(:pais))
                """), {'pais':country}).mappings()]
                rows = [row for row in possible if normalize_name(str(row.get('campeonato'))) == normalize_name(competition)]
            if rows:
                return rows, {'status': 'ok', 'database':label}
    if found_table_at:
        return [], {'status': 'ok', 'database':found_table_at}
    return [], {'status': 'tabela_ausente', 'database':None}
