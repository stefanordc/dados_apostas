"""Motor do BET Teste: dados da tabela `odds`, mercados, preços estimados em jogo e liquidação.

Fonte única: tabela `odds` (odds pré-jogo reais, placar final e minutos dos gols). Não há odds
reais durante a partida: no minuto 0 usamos a odd real da tabela; nos demais minutos a odd é
ESTIMADA por um modelo de Poisson ajustado às odds reais de abertura do próprio jogo.
"""
from __future__ import annotations

import json
import pickle
import threading
import time
from pathlib import Path
from bisect import bisect_right
from datetime import date, timedelta
from functools import lru_cache
from math import exp, factorial

import numpy as np
from sqlalchemy import bindparam, text

from ..db import history_connection
from . import bet_ratings as ratings
from . import bet_reconcile as recon
from . import bet_api as api

HT_SHARE = 0.45          # fatia dos gols esperados no 1º tempo
LAY_SPREAD = 1.02        # lay real ≈ back real +2% (diferença entre back e lay)
MODEL_SPREAD = 0.01      # preço do modelo: back = justo*(1-1%), lay = justo*(1+1%)
MAXK = 12


# ----------------------------------------------------------------------------------------
# Mercados
# ----------------------------------------------------------------------------------------
def _build_markets():
    m = {}
    m['match_odds'] = ('Match Odds', 'ft', {
        'home': ('Mandante', 'odd_casa_ft', lambda h, a: h > a),
        'draw': ('Empate', 'odd_empate_ft', lambda h, a: h == a),
        'away': ('Visitante', 'odd_fora_ft', lambda h, a: a > h)})
    m['match_odds_ht'] = ('Match Odds HT', 'ht', {
        'home': ('Mandante', 'odd_casa_ht', lambda h, a: h > a),
        'draw': ('Empate', 'odd_empate_ht', lambda h, a: h == a),
        'away': ('Visitante', 'odd_fora_ht', lambda h, a: a > h)})
    m['double_chance'] = ('Dupla Chance', 'ft', {
        '1x': ('Mandante ou Empate', 'dupla_chance_1x', lambda h, a: h >= a),
        '12': ('Mandante ou Visitante', 'dupla_chance_12', lambda h, a: h != a),
        'x2': ('Empate ou Visitante', 'dupla_chance_x2', lambda h, a: a >= h)})
    for line in ('0_5', '1_5', '2_5'):
        x = float(line.replace('_', '.'))
        m[f'ou_{line}_ht'] = (f'Over/Under {x:g} HT'.replace('.', ','), 'ht', {
            'over': (f'Over {x:g}'.replace('.', ','), f'over_{line}_ht', lambda h, a, x=x: h + a > x),
            'under': (f'Under {x:g}'.replace('.', ','), f'under_{line}_ht', lambda h, a, x=x: h + a < x)})
    for line in ('0_5', '1_5', '2_5', '3_5', '4_5'):
        x = float(line.replace('_', '.'))
        m[f'ou_{line}'] = (f'Over/Under {x:g}'.replace('.', ','), 'ft', {
            'over': (f'Over {x:g}'.replace('.', ','), f'over_{line}_ft', lambda h, a, x=x: h + a > x),
            'under': (f'Under {x:g}'.replace('.', ','), f'under_{line}_ft', lambda h, a, x=x: h + a < x)})
    m['btts'] = ('Ambos Marcam', 'ft', {
        'yes': ('Sim', 'ambos_marcam_sim', lambda h, a: h > 0 and a > 0),
        'no': ('Não', 'ambos_marcam_nao', lambda h, a: h == 0 or a == 0)})
    cs = {}
    for i in range(4):
        for j in range(4):
            cs[f'{i}-{j}'] = (f'{i} - {j}', f'correct_score_{i}_{j}', lambda h, a, i=i, j=j: h == i and a == j)
    cs['other'] = ('Outro placar', None, lambda h, a: h > 3 or a > 3)
    m['correct_score'] = ('Correct Score', 'ft', cs)
    m['goleada'] = ('Goleada (4+ gols)', 'ft', {
        'home': ('Goleada do mandante', None, lambda h, a: h >= 4 and h > a),
        'away': ('Goleada do visitante', None, lambda h, a: a >= 4 and a > h)})
    return m


MARKETS = _build_markets()
# mercados exibidos na Casa de Apostas (ordem do usuário)
BOOK_MARKETS = ['match_odds', 'ou_0_5_ht', 'ou_0_5', 'ou_1_5', 'ou_2_5', 'ou_3_5', 'btts', 'correct_score', 'goleada']
BOOK_SELECTIONS = {  # seleções exibidas por mercado (o usuário quer só alguns lados)
    'ou_0_5_ht': ['over'], 'ou_0_5': ['over'], 'ou_1_5': ['over'], 'ou_2_5': ['over'], 'ou_3_5': ['under'],
    'btts': ['yes'], 'goleada': ['home', 'away'],
}
# Mercados em que só Back faz sentido na aba (ex.: "Under 3,5" = entrar no under).
BOOK_BACK_ONLY = {'ou_3_5'}


def market_catalog():
    return [{'key': k, 'label': v[0], 'period': v[1],
             'selections': [{'key': sk, 'label': sv[0], 'real_odds': sv[1] is not None}
                            for sk, sv in v[2].items()]} for k, v in MARKETS.items()]


# ----------------------------------------------------------------------------------------
# Carga e preparação dos jogos
# ----------------------------------------------------------------------------------------
NON_ODD = {'id', 'data', 'temporada', 'pais', 'continente', 'campeonato', 'divisao', 'formato', 'jogo_id', 'rodada',
           'casa', 'fora', 'gols_casa', 'gols_fora', 'minutos_gols_casa', 'minutos_gols_fora', 'criado_em'}


def _goals(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return sorted(int(x) for x in value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _points(gf, ga):
    return 3 if gf > ga else 1 if gf == ga else 0


WINDOWS = (5, 10)


def _team_features(last, gf_key='gf'):
    """Médias móveis a partir da lista (cronológica) de jogos anteriores do clube."""
    out = {}
    for w in WINDOWS:
        rows = last[-w:]
        n = len(rows)
        out[f'jogos_{w}'] = n
        if n:
            out[f'gf_{w}'] = sum(r[0] for r in rows) / n
            out[f'ga_{w}'] = sum(r[1] for r in rows) / n
            out[f'ppg_{w}'] = sum(_points(r[0], r[1]) for r in rows) / n
            out[f'vit_{w}'] = 100 * sum(r[0] > r[1] for r in rows) / n
            out[f'over25_{w}'] = 100 * sum(r[0] + r[1] > 2 for r in rows) / n
            out[f'btts_{w}'] = 100 * sum(r[0] > 0 and r[1] > 0 for r in rows) / n
        else:
            for k in ('gf', 'ga', 'ppg', 'vit', 'over25', 'btts'):
                out[f'{k}_{w}'] = None
    return out


FEATURE_LABELS = {'gf': 'média de gols marcados', 'ga': 'média de gols sofridos', 'ppg': 'pontos por jogo',
                  'vit': '% de vitórias', 'over25': '% de Over 2,5', 'btts': '% de Ambos Marcam',
                  'jogos': 'jogos considerados'}


CACHE_FILE = Path(__file__).resolve().parents[2] / '.cache' / 'odds_rows.pkl'
CACHE_HOURS = 6
# Evita bater no banco a cada clique (apostar/mercados). Atualização diária: refresh explícito ou TTL.
VERSION_MEMO_SECONDS = 120
MERGE_SOFT_TTL_SECONDS = 600
_version_memo = {'t': 0.0, 'v': None}


def history_version():
    """Assinatura leve do histórico remoto: qualquer INSERT/UPDATE diário invalida caches."""
    now = time.time()
    if _version_memo['v'] is not None and now - _version_memo['t'] < VERSION_MEMO_SECONDS:
        return _version_memo['v']
    with history_connection() as conn:
        ver = conn.execute(text("""
            SELECT CONCAT_WS('|',
              (SELECT COALESCE(MAX(criado_em)::text, '') FROM public.minutos_gols),
              (SELECT COALESCE(MAX(GREATEST(criado_em, atualizado_em))::text, '') FROM public.jogos),
              (SELECT COALESCE(MAX(criado_em)::text, '') FROM public.odds),
              (SELECT COALESCE(MAX(GREATEST(criado_em, atualizado_em))::text, '') FROM public.historico_odds),
              (SELECT COALESCE(MAX(GREATEST(criado_em, atualizado_em))::text, '') FROM public.historico_jogos)
            )
        """)).scalar()
    _version_memo.update(t=now, v=str(ver or ''))
    return _version_memo['v']


def _cached_rows(data_version=None):
    """Cópia local da tabela `odds` (leitura remota leva ~1 min).

    Se a assinatura do banco mudou mas o pickle ainda é recente, reutiliza o arquivo —
    evita travar 'Abrir entrada' com reload completo a cada pequena atualização remota.
    """
    try:
        if CACHE_FILE.exists():
            age = time.time() - CACHE_FILE.stat().st_mtime
            cached = pickle.loads(CACHE_FILE.read_bytes())
            if isinstance(cached, dict) and cached.get('rows') is not None:
                if cached.get('version') == data_version or age < CACHE_HOURS * 3600:
                    return cached['rows']
            if isinstance(cached, list) and age < CACHE_HOURS * 3600:
                return cached
    except Exception:
        pass
    rows = _fetch_all_odds()
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_bytes(pickle.dumps({'version': data_version, 'rows': rows}))
    except Exception:
        pass
    return rows


def refresh_cache():
    _version_memo.update(t=0.0, v=None)
    for f in (CACHE_FILE, JOGOS_CACHE):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
    _load.cache_clear()
    _load_extra.cache_clear()
    recon.refresh_cache_files()
    _fit_cache.clear()
    with _merge_lock:
        _merged.update(key=None, games=[], index={}, built_at=0.0)
    recon.clear_goals_cache()


def _fetch_all_odds(page=1500):
    """Lê a tabela `odds` em páginas (o pooler derruba transferências grandes) com nova tentativa."""
    rows, last = [], 0
    while True:
        for attempt in range(4):
            try:
                with history_connection() as conn:
                    chunk = [dict(r) for r in conn.execute(
                        text('SELECT * FROM public.odds WHERE id > :last ORDER BY id LIMIT :n'),
                        {'last': last, 'n': page}).mappings()]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        if not chunk:
            return rows
        rows.extend(chunk)
        last = chunk[-1]['id']


@lru_cache(maxsize=2)
def _load(bucket):
    rows = _cached_rows(bucket)
    rows.sort(key=lambda r: (r['data'], r['id']))
    history = {}
    games = []
    for r in rows:
        for k, v in list(r.items()):
            if k not in NON_ODD and v is not None:
                r[k] = float(v)
        r['jogo_id'] = str(r['jogo_id'])
        r['gh'] = r.pop('gols_casa'); r['ga'] = r.pop('gols_fora')
        hg = _goals(r.pop('minutos_gols_casa')); ag = _goals(r.pop('minutos_gols_fora'))
        r['timeline_ok'] = (r['gh'] is not None and r['ga'] is not None and hg is not None and ag is not None
                            and len(hg) == r['gh'] and len(ag) == r['ga'])
        r['goals'] = sorted([(m, 'h') for m in hg] + [(m, 'a') for m in ag]) if r['timeline_ok'] else []
        r['goal_minutes'] = [g[0] for g in r['goals']]
        # estatísticas só com jogos ANTERIORES à data (nenhum dado do próprio jogo)
        hk = (r['pais'], r['casa']); ak = (r['pais'], r['fora'])
        for prefix, key in (('home', hk), ('away', ak)):
            for k, v in _team_features(history.get(key, [])).items():
                r[f'{prefix}_{k}'] = v
        if r['gh'] is not None and r['ga'] is not None:
            history.setdefault(hk, []).append((r['gh'], r['ga']))
            history.setdefault(ak, []).append((r['ga'], r['gh']))
        games.append(r)
    return games


def games():
    return _load(history_version())


COPA_WORDS = ('copa', 'champions', 'libertadores', 'sul-americana', 'sudamericana', 'europa league', 'conference',
              'supercopa', 'taça', 'taca', 'cup', 'mundial', 'nations', 'eliminat', 'olimp')
JOGOS_CACHE = Path(__file__).resolve().parents[2] / '.cache' / 'jogos_rows.pkl'


def _format_of(campeonato, fase):
    name = (campeonato or '').lower()
    if any(w in name for w in COPA_WORDS):
        return 'Copa'
    phase = (fase or '').strip().lower()
    return 'Liga' if phase.startswith('rodada') or phase.isdigit() or phase in ('', '-') else 'Copa'


def _read_pages(sql, key_col='id', page=3000):
    rows, last = [], 0
    while True:
        for attempt in range(4):
            try:
                with history_connection() as conn:
                    chunk = [dict(r) for r in conn.execute(text(sql), {'last': last, 'n': page}).mappings()]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        if not chunk:
            return rows
        rows.extend(chunk)
        last = chunk[-1][key_col]


def _jogos_rows(data_version=None):
    """Lê `jogos` + `minutos_gols` do banco; pickle recente serve mesmo com assinatura diferente."""
    try:
        if JOGOS_CACHE.exists():
            age = time.time() - JOGOS_CACHE.stat().st_mtime
            cached = pickle.loads(JOGOS_CACHE.read_bytes())
            if isinstance(cached, dict) and 'matches' in cached:
                if cached.get('version') == data_version or age < CACHE_HOURS * 3600:
                    return cached
    except Exception:
        pass
    matches = _read_pages("""SELECT id, id_jogo, data, pais, campeonato, temporada, fase, mandante, visitante, gols_casa, gols_fora
                             FROM public.jogos WHERE id > :last ORDER BY id LIMIT :n""")
    goals = _read_pages("""SELECT id, id_jogo, lado, minuto FROM public.minutos_gols WHERE id > :last ORDER BY id LIMIT :n""")
    data = {'version': data_version, 'matches': matches, 'goals': goals}
    try:
        JOGOS_CACHE.parent.mkdir(exist_ok=True)
        JOGOS_CACHE.write_bytes(pickle.dumps(data))
    except Exception:
        pass
    return data


@lru_cache(maxsize=2)
def _load_extra(bucket):
    """Jogos da tabela `jogos` (SofaScore) sem odds reais; as odds serão estimadas com as estatísticas dos clubes."""
    raw = _jogos_rows(bucket)
    by_game = {}
    for g in raw['goals']:
        by_game.setdefault(g['id_jogo'], []).append(g)
    history, out = {}, []
    for m in sorted(raw['matches'], key=lambda r: (r['data'], r['id'])):
        casa, fora = m['mandante'], m['visitante']
        hk, ak = (m['pais'], casa), (m['pais'], fora)
        gh, ga = m['gols_casa'], m['gols_fora']
        g = {'id': m['id'], 'jogo_id': f"s{m['id_jogo']}", 'data': m['data'], 'pais': m['pais'], 'campeonato': m['campeonato'],
             'temporada': m['temporada'], 'formato': _format_of(m['campeonato'], m['fase']), 'rodada': m['fase'],
             'casa': casa, 'fora': fora, 'gh': gh, 'ga': ga, 'fonte': 'jogos'}
        if gh is not None and ga is not None:
            evs = by_game.get(m['id_jogo'], [])
            hm = sorted(e['minuto'] for e in evs if e['lado'] == 'casa')
            am = sorted(e['minuto'] for e in evs if e['lado'] == 'fora')
            g['timeline_ok'] = len(hm) == gh and len(am) == ga
            g['goals'] = sorted([(x, 'h') for x in hm] + [(x, 'a') for x in am]) if g['timeline_ok'] else []
        else:
            g['timeline_ok'] = False
            g['goals'] = []
        g['goal_minutes'] = [x[0] for x in g['goals']]
        for prefix, key in (('home', hk), ('away', ak)):
            for k, v in _team_features(history.get(key, [])).items():
                g[f'{prefix}_{k}'] = v
        if gh is not None and ga is not None:
            history.setdefault(hk, []).append((gh, ga))
            history.setdefault(ak, []).append((ga, gh))
        out.append(g)
    return out


_merged = {'key': None, 'games': [], 'index': {}, 'built_at': 0.0}
_merge_lock = threading.RLock()
_merge_refreshing = False


def _build_merged(ver):
    """Trabalho pesado (pickle/DB/merge) — deve rodar FORA de `_merge_lock`."""
    merged = recon.merge(list(_load_extra(ver)), list(_load(ver)), recon.ho_games(ver), api.api_games())
    index = {}
    for g in merged:
        for i in g.get('ids', [g['jogo_id']]):
            index[str(i)] = g
    return merged, index


def _publish_merged(key, merged, index):
    with _merge_lock:
        _fit_cache.clear()
        _merged.update(key=key, games=merged, index=index, built_at=time.time())
        return _merged['games']


def _refresh_merged_bg():
    """Recarrega o merge em background; leitores continuam com o índice antigo."""
    global _merge_refreshing
    try:
        ver = history_version()
        key = (ver, recon._version)
        with _merge_lock:
            if _merged['key'] == key and _merged['games']:
                _merged['built_at'] = time.time()
                return
        merged, index = _build_merged(ver)
        _publish_merged(key, merged, index)
    except Exception:
        pass
    finally:
        with _merge_lock:
            _merge_refreshing = False


def all_games(force: bool = False):
    """Um jogo por partida: jogos (SofaScore) + odds + historico_odds, unidos pelos vínculos de clubes.

    Com cache em memória, devolve na hora. Se o soft-TTL expirou, serve o cache antigo e
    atualiza em background — apostar/mercados nunca esperam o reload completo (~1 min).
    """
    global _merge_refreshing
    now = time.time()
    with _merge_lock:
        has = bool(_merged['games'])
        age = now - float(_merged.get('built_at') or 0)
        if has and not force and age < MERGE_SOFT_TTL_SECONDS:
            return _merged['games']
        if has and not force:
            stale = _merged['games']
            start_bg = not _merge_refreshing
            if start_bg:
                _merge_refreshing = True
        else:
            stale = None
            start_bg = False

    if stale is not None:
        if start_bg:
            threading.Thread(target=_refresh_merged_bg, name='bet-merge-refresh', daemon=True).start()
        return stale

    ver = history_version()
    key = (ver, recon._version)
    with _merge_lock:
        if not force and _merged['key'] == key and _merged['games']:
            _merged['built_at'] = time.time()
            return _merged['games']
    merged, index = _build_merged(ver)
    return _publish_merged(key, merged, index)


def _row_to_jogos_game(m, evs=None):
    """Converte linha de `jogos` (+ minutos opcionais) no dict do motor."""
    evs = evs or []
    gh, ga = m['gols_casa'], m['gols_fora']
    g = {
        'id': m['id'], 'jogo_id': f"s{m['id_jogo']}", 'ids': [f"s{m['id_jogo']}"],
        'data': m['data'], 'pais': m['pais'], 'campeonato': m['campeonato'],
        'temporada': m.get('temporada'), 'formato': _format_of(m['campeonato'], m.get('fase')),
        'rodada': m.get('fase'), 'casa': m['mandante'], 'fora': m['visitante'],
        'gh': gh, 'ga': ga, 'fonte': 'jogos', 'calendario': 'jogos', 'fontes': ['jogos'],
        'casa_original': m['mandante'], 'fora_original': m['visitante'],
    }
    if gh is not None and ga is not None:
        hm = sorted(e['minuto'] for e in evs if e['lado'] == 'casa')
        am = sorted(e['minuto'] for e in evs if e['lado'] == 'fora')
        g['timeline_ok'] = len(hm) == gh and len(am) == ga
        g['goals'] = sorted([(x, 'h') for x in hm] + [(x, 'a') for x in am]) if g['timeline_ok'] else []
    else:
        g['timeline_ok'] = False
        g['goals'] = []
    g['goal_minutes'] = [x[0] for x in g['goals']]
    return g


def _fetch_single_jogos(jogo_id: str):
    """Um jogo da tabela `jogos` (+ minutos) sem carregar odds/histórico — caminho rápido p/ apostar."""
    jid = str(jogo_id)
    if not jid.startswith('s'):
        return None
    try:
        sid = int(jid[1:])
    except ValueError:
        return None
    with history_connection() as conn:
        m = conn.execute(text("""
            SELECT id, id_jogo, data, pais, campeonato, temporada, fase, mandante, visitante, gols_casa, gols_fora
            FROM public.jogos WHERE id_jogo = :sid LIMIT 1
        """), {'sid': sid}).mappings().first()
        if not m:
            return None
        evs = list(conn.execute(text(
            "SELECT lado, minuto FROM public.minutos_gols WHERE id_jogo = :sid"
        ), {'sid': sid}).mappings())
    return _row_to_jogos_game(m, evs)


def _odds_key(data, pais, casa, fora):
    return (data, recon.pais_of(pais), recon.norm(recon.std_name(recon.pais_of(pais), 'odds', casa)),
            recon.norm(recon.std_name(recon.pais_of(pais), 'odds', fora)))


def _jogos_key(g):
    pais = recon.pais_of(g['pais'])
    return (g['data'], pais,
            recon.norm(recon.std_name(pais, 'jogos', g.get('casa_original') or g['casa'])),
            recon.norm(recon.std_name(pais, 'jogos', g.get('fora_original') or g['fora'])))


def _attach_window_odds(games, start, end):
    """Odds só da janela (odds → historico_odds). Não carrega o histórico inteiro."""
    if not games:
        return
    with history_connection() as conn:
        odds_rows = list(conn.execute(text("""
            SELECT data, pais, casa, fora, odd_casa_ft, odd_empate_ft, odd_fora_ft
            FROM public.odds
            WHERE data >= :a AND data <= :b
              AND odd_casa_ft IS NOT NULL
        """), {'a': start, 'b': end}).mappings())
        ho_rows = list(conn.execute(text("""
            SELECT data, pais, casa, fora, odd_casa, odd_empate, odd_fora
            FROM public.historico_odds
            WHERE data >= :a AND data <= :b
              AND odd_casa IS NOT NULL
        """), {'a': start, 'b': end}).mappings())
    by_key = {}
    for r in ho_rows:
        by_key[_odds_key(r['data'], r['pais'], r['casa'], r['fora'])] = {
            'odd_casa_ft': float(r['odd_casa']) if r['odd_casa'] else None,
            'odd_empate_ft': float(r['odd_empate']) if r['odd_empate'] else None,
            'odd_fora_ft': float(r['odd_fora']) if r['odd_fora'] else None,
            'odds_fonte': 'historico_odds',
        }
    for r in odds_rows:
        by_key[_odds_key(r['data'], r['pais'], r['casa'], r['fora'])] = {
            'odd_casa_ft': float(r['odd_casa_ft']) if r['odd_casa_ft'] else None,
            'odd_empate_ft': float(r['odd_empate_ft']) if r['odd_empate_ft'] else None,
            'odd_fora_ft': float(r['odd_fora_ft']) if r['odd_fora_ft'] else None,
            'odds_fonte': 'odds',
        }
    for g in games:
        hit = by_key.get(_jogos_key(g))
        if not hit:
            # tenta sem std_name (nomes já iguais entre fontes)
            pais = recon.pais_of(g['pais'])
            hit = by_key.get((g['data'], pais, recon.norm(g['casa']), recon.norm(g['fora'])))
        if hit:
            g.update(hit)


def window_games(start, end, formato='Liga'):
    """Calendário rápido: só `jogos` na janela + odds da janela. Nunca chama all_games().

    Linha do tempo (minutos_gols) fica para quando o usuário abrir o jogo — evita IN enorme na lista.
    """
    global _merge_refreshing
    with history_connection() as conn:
        rows = list(conn.execute(text("""
            SELECT id, id_jogo, data, pais, campeonato, temporada, fase, mandante, visitante, gols_casa, gols_fora
            FROM public.jogos
            WHERE data >= :a AND data <= :b
            ORDER BY data, id
        """), {'a': start, 'b': end}).mappings())
    games = []
    for m in rows:
        g = _row_to_jogos_game(m, [])
        # Desconhecido até abrir o jogo (evita carregar minutos_gols de centenas de partidas).
        if g.get('gh') is not None and g.get('ga') is not None and (g['gh'] + g['ga']) == 0:
            g['timeline_ok'] = True
        else:
            g['timeline_ok'] = bool(g.get('timeline_ok'))
            g['_tl'] = 'pending'
        if formato not in ('', 'Todos', None) and g.get('formato') != formato:
            continue
        games.append(g)
    # Reaproveita índice quente; completa odds faltantes só na janela (sem merge completo).
    with _merge_lock:
        warm_index = dict(_merged['index']) if _merged['index'] else {}
        has_full = bool(_merged['games'])
    need_odds = []
    for g in games:
        hit = warm_index.get(str(g['jogo_id']))
        if hit and hit.get('odd_casa_ft'):
            for k in ('odd_casa_ft', 'odd_empate_ft', 'odd_fora_ft', 'odds_fonte',
                      'over_2_5_ft', 'under_2_5_ft', 'ambos_marcam_sim'):
                if hit.get(k) is not None:
                    g[k] = hit[k]
            if hit.get('ids'):
                g['ids'] = hit['ids']
        elif not g.get('odd_casa_ft'):
            need_odds.append(g)
    if need_odds:
        _attach_window_odds(need_odds, start, end)
    if not has_full:
        with _merge_lock:
            start_bg = not _merge_refreshing
            if start_bg:
                _merge_refreshing = True
        if start_bg:
            threading.Thread(target=_refresh_merged_bg, name='bet-merge-refresh', daemon=True).start()
    # Indexa a janela para place_bet/mercados sem esperar o merge.
    with _merge_lock:
        for g in games:
            cur = _merged['index'].get(str(g['jogo_id']))
            if cur is None or not cur.get('odd_casa_ft'):
                _merged['index'][str(g['jogo_id'])] = g
    return games


def _fetch_goals_for_ids(conn, ids):
    by_goals = {}
    if not ids:
        return by_goals
    stmt = text("SELECT id_jogo, lado, minuto FROM public.minutos_gols WHERE id_jogo IN :ids").bindparams(
        bindparam('ids', expanding=True))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for e in conn.execute(stmt, {'ids': chunk}).mappings():
            by_goals.setdefault(e['id_jogo'], []).append(e)
    return by_goals


def team_history_jogos(names, cutoff, exclude_ids=None, limit=40):
    """Últimos jogos de um time na tabela `jogos` até a data limite (sem all_games)."""
    names = [n for n in {str(n).strip() for n in names if n} if n]
    if not names:
        return []
    exclude_ids = {str(i) for i in (exclude_ids or [])}
    stmt = text("""
        SELECT id, id_jogo, data, pais, campeonato, temporada, fase, mandante, visitante, gols_casa, gols_fora
        FROM public.jogos
        WHERE data <= :cut AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
          AND (mandante IN :names OR visitante IN :names)
        ORDER BY data DESC, id DESC
        LIMIT :lim
    """).bindparams(bindparam('names', expanding=True))
    with history_connection() as conn:
        rows = list(conn.execute(stmt, {
            'cut': cutoff, 'names': names, 'lim': max(limit * 3, 60),
        }).mappings())
        by_goals = _fetch_goals_for_ids(conn, [r['id_jogo'] for r in rows])
    out = []
    for m in rows:
        g = _row_to_jogos_game(m, by_goals.get(m['id_jogo'], []))
        if str(g['jogo_id']) in exclude_ids:
            continue
        out.append(g)
        if len(out) >= limit:
            break
    return out


def _ensure_timeline(g):
    """Carrega minutos_gols sob demanda (lista de jogos adia isso de propósito)."""
    if not g or g.get('_tl') == 'loaded':
        return g
    if g.get('fonte') != 'jogos' and not str(g.get('jogo_id', '')).startswith('s'):
        g['_tl'] = 'loaded'
        return g
    light = _fetch_single_jogos(g['jogo_id'])
    if light:
        g['timeline_ok'] = light['timeline_ok']
        g['goals'] = light['goals']
        g['goal_minutes'] = light['goal_minutes']
        if light.get('odd_casa_ft') and not g.get('odd_casa_ft'):
            for k in ('odd_casa_ft', 'odd_empate_ft', 'odd_fora_ft', 'odds_fonte'):
                if light.get(k) is not None:
                    g[k] = light[k]
    g['_tl'] = 'loaded'
    return g


def game_by_id(jogo_id):
    """Lookup rápido: índice em memória, senão 1 query em `jogos` — nunca bloqueia no merge completo."""
    global _merge_refreshing
    jid = str(jogo_id)
    with _merge_lock:
        hit = _merged['index'].get(jid)
        if hit is not None:
            return _ensure_timeline(hit)
        cold = not _merged['games']
    if cold:
        light = _fetch_single_jogos(jid)
        if light is not None:
            light['_tl'] = 'loaded'
            with _merge_lock:
                _merged['index'].setdefault(jid, light)
                start_bg = not _merge_refreshing
                if start_bg:
                    _merge_refreshing = True
            if start_bg:
                threading.Thread(target=_refresh_merged_bg, name='bet-merge-refresh', daemon=True).start()
            return light
    all_games()
    with _merge_lock:
        hit = _merged['index'].get(jid)
    return _ensure_timeline(hit) if hit is not None else None


def reconciliation_sources():
    ver = history_version()
    return list(_load_extra(ver)), list(_load(ver)), recon.ho_games(ver), api.api_games()


@lru_cache(maxsize=1)
def condition_fields():
    sample = next(iter(games()), {})
    odd_labels = {
        'odd_casa_ft': 'Odd inicial do mandante (FT)', 'odd_empate_ft': 'Odd inicial do empate (FT)',
        'odd_fora_ft': 'Odd inicial do visitante (FT)', 'odd_casa_ht': 'Odd inicial do mandante (HT)',
        'odd_empate_ht': 'Odd inicial do empate (HT)', 'odd_fora_ht': 'Odd inicial do visitante (HT)',
        'ambos_marcam_sim': 'Odd Ambos Marcam - Sim', 'ambos_marcam_nao': 'Odd Ambos Marcam - Não',
        'dupla_chance_1x': 'Odd Dupla Chance 1X', 'dupla_chance_12': 'Odd Dupla Chance 12',
        'dupla_chance_x2': 'Odd Dupla Chance X2'}
    fields = []
    for k in sample:
        if k.startswith(('over_', 'under_', 'correct_score_', 'odd_', 'dupla_', 'ambos_')):
            if k in odd_labels:
                label = odd_labels[k]
            elif k.startswith('correct_score_'):
                label = 'Odd Correct Score ' + k[len('correct_score_'):].replace('_', '-')
            else:
                bits = k.split('_')
                label = f"Odd {bits[0].capitalize()} {bits[1]},{bits[2]} {bits[3].upper()}"
            fields.append({'key': k, 'label': label, 'group': 'Odds iniciais'})
    for prefix, who in (('home', 'mandante'), ('away', 'visitante')):
        for w in WINDOWS:
            for k in ('gf', 'ga', 'ppg', 'vit', 'over25', 'btts'):
                fields.append({'key': f'{prefix}_{k}_{w}', 'label': f'{FEATURE_LABELS[k].capitalize()} do {who} · últimos {w}',
                               'group': 'Forma dos clubes'})
            fields.append({'key': f'{prefix}_jogos_{w}', 'label': f'Jogos disponíveis do {who} (últ. {w})',
                           'group': 'Forma dos clubes'})
    return fields


def countries():
    return sorted({g['pais'] for g in games() if g['pais']})


def competitions():
    return sorted({(g['pais'], g['campeonato']) for g in games() if g['campeonato']})


# ----------------------------------------------------------------------------------------
# Modelo de preços
# ----------------------------------------------------------------------------------------
def _pmf(lam, kmax=MAXK):
    lam = np.asarray(lam, dtype=float)
    return np.array([np.exp(-lam) * lam ** k / factorial(k) for k in range(kmax + 1)])


@lru_cache(maxsize=1)
def _grid():
    lams = np.round(np.arange(0.1, 4.001, 0.05), 3)
    p = _pmf(lams)                                  # [k, idx]
    xs = np.arange(MAXK + 1)
    hm = (xs[:, None] > xs[None, :]).astype(float)
    dm = (xs[:, None] == xs[None, :]).astype(float)
    am = (xs[:, None] < xs[None, :]).astype(float)
    om = ((xs[:, None] + xs[None, :]) >= 3).astype(float)
    f = lambda mask: np.einsum('xy,xi,yj->ij', mask, p, p)
    return lams, f(hm), f(dm), f(am), f(om)


_fit_cache = {}
_fit_lock = threading.Lock()


def _ratings_state():
    def loader():
        return [{'data': m['data'], 'pais': m['pais'], 'campeonato': m['campeonato'], 'casa': m['mandante'],
                 'fora': m['visitante'], 'gh': m['gols_casa'], 'ga': m['gols_fora']} for m in _jogos_rows()['matches']]
    return ratings.state(loader)


def fit_lambdas(game, as_of=None):
    """λ (gols esperados em 90') do mandante/visitante.

    Com odds reais: ajuste às odds iniciais do jogo. Sem odds: força dos clubes (Elo) e média de gols do
    campeonato, usando apenas jogos até `as_of` (data limite) ou até a véspera da partida."""
    as_of = as_of or (game['data'] - timedelta(days=1))
    key = (game['jogo_id'], as_of)
    if key in _fit_cache:
        return _fit_cache[key]
    oh, od, oa = game.get('odd_casa_ft'), game.get('odd_empate_ft'), game.get('odd_fora_ft')
    if oh and od and oa and min(oh, od, oa) > 1:
        lams, ph, pd_, pa, po = _grid()
        inv = np.array([1 / oh, 1 / od, 1 / oa]); inv = inv / inv.sum()
        err = (ph - inv[0]) ** 2 + (pd_ - inv[1]) ** 2 + (pa - inv[2]) ** 2
        ov, un = game.get('over_2_5_ft'), game.get('under_2_5_ft')
        if ov and un and ov > 1 and un > 1:
            po_t = (1 / ov) / (1 / ov + 1 / un)
            err = err + 1.5 * (po - po_t) ** 2
        i, j = np.unravel_index(np.argmin(err), err.shape)
        result = (float(lams[i]), float(lams[j]), 'odds', None)
    else:
        lh, la, info = ratings.expected_goals(_ratings_state(), game, as_of)
        result = (lh, la, 'forca_dos_clubes', info)
    with _fit_lock:
        if len(_fit_cache) > 20000:
            _fit_cache.clear()
        _fit_cache[key] = result
    return result


def _cum_share(t):
    t = max(0.0, min(float(t), 90.0))
    return HT_SHARE * t / 45 if t <= 45 else HT_SHARE + (1 - HT_SHARE) * (t - 45) / 45


def score_at(game, minute):
    h = a = 0
    for m, side in game['goals']:
        if m <= minute:
            if side == 'h': h += 1
            else: a += 1
        else:
            break
    return h, a


# Efeito do placar no ritmo de gols (ótica do mandante): quem perde ataca mais, quem vence recua.
def _state_mult(diff):
    if diff == 0:
        return 1.0, 1.0
    if diff == 1:
        return 0.88, 1.14
    if diff >= 2:
        return 0.86, 1.04
    if diff == -1:
        return 1.14, 0.88
    return 1.04, 0.86


DP_GOALS = 9
_dist_cache = {}
_dist_lock = threading.Lock()


def _distributions(lh, la, minute, score):
    """Distribuição dos gols ADICIONAIS até o fim (e até o intervalo), minuto a minuto.

    A intensidade de cada time muda conforme o placar (efeito "estado do jogo") e o 2º tempo tem mais gols
    que o 1º. Retorna (matriz final, matriz no intervalo ou None)."""
    h0, a0 = score
    n = DP_GOALS + 1
    idx = np.arange(n)
    diff = (h0 + idx[:, None]) - (a0 + idx[None, :])
    rh = np.vectorize(lambda d: _state_mult(int(d))[0])(diff)
    ra = np.vectorize(lambda d: _state_mult(int(d))[1])(diff)
    P = np.zeros((n, n)); P[0, 0] = 1.0
    ht = P.copy() if minute >= 45 else None
    for m in range(int(minute) + 1, 91):
        w = HT_SHARE / 45 if m <= 45 else (1 - HT_SHARE) / 45
        ph = np.minimum(lh * w * rh, 0.45); pa = np.minimum(la * w * ra, 0.45)
        stay = P * (1 - ph - pa)
        stay[1:, :] += (P * ph)[:-1, :]
        stay[:, 1:] += (P * pa)[:, :-1]
        P = stay
        if m == 45:
            ht = P.copy()
    return P, ht


def selection_probability(game, market, selection, minute, score, as_of=None):
    """P(seleção) dado o placar no minuto; None se o mercado já está encerrado (HT após 45')."""
    label, period, selections = MARKETS[market]
    if period == 'ht' and minute >= 45:
        return None
    pred = selections[selection][2]
    lh, la, _src, _info = fit_lambdas(game, as_of)
    key = (round(lh, 4), round(la, 4), int(minute), score)
    with _dist_lock:
        dists = _dist_cache.get(key)
    if dists is None:
        dists = _distributions(lh, la, minute, score)
        with _dist_lock:
            if len(_dist_cache) > 50000:
                _dist_cache.clear()
            _dist_cache[key] = dists
    final, ht = dists
    M = ht if period == 'ht' else final
    h0, a0 = score
    total = 0.0
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if pred(h0 + i, a0 + j):
                total += M[i, j]
    return float(min(total / M.sum(), 1.0))


def tick(odd):
    steps = [(2, .01), (3, .02), (4, .05), (6, .1), (10, .2), (20, .5), (30, 1), (50, 2), (100, 5), (1000, 10)]
    lo = 1.0
    for hi, st in steps:
        if odd <= hi:
            n = round((odd - lo) / st)
            return round(min(max(lo + n * st, 1.01), 1000.0), 2)
        lo = hi
    return 1000.0


def quote(game, market, selection, minute, score, as_of=None):
    """Retorna {'back','lay','source'} ou None se suspenso.

    source = 'real' (odd da tabela, minuto 0 e 0x0) ou 'estimada' (modelo)."""
    label, period, selections = MARKETS[market]
    column = selections[selection][1]
    if minute <= 0 and score == (0, 0) and column and game.get(column) and game[column] > 1:
        real = float(game[column])
        return {'back': round(real, 2), 'lay': tick(real * LAY_SPREAD), 'source': 'real'}
    p = selection_probability(game, market, selection, minute, score, as_of)
    if p is None or p < 0.003 or p > 0.985:
        return None
    fair = 1 / p
    return {'back': tick(fair * (1 - MODEL_SPREAD)), 'lay': tick(fair * (1 + MODEL_SPREAD)), 'source': 'estimada'}


def settle_win(game, market, selection):
    """True se a seleção ganhou; None se não for possível (sem linha do tempo para HT)."""
    label, period, selections = MARKETS[market]
    if game['gh'] is None or game['ga'] is None:
        return None
    if period == 'ht':
        if not game['timeline_ok']:
            return None
        h, a = score_at(game, 45)
    else:
        h, a = game['gh'], game['ga']
    return bool(selections[selection][2](h, a))


def result_summary(game):
    return {'final': f"{game['gh']}-{game['ga']}" if game['gh'] is not None else None}


# ----------------------------------------------------------------------------------------
# Liquidação de posições
# ----------------------------------------------------------------------------------------
def pnl_open_close(side, stake, entry_odd, exit_odd):
    """P/L de zerar a posição (hedge igual) ao odd de saída."""
    if side == 'lay':
        return stake * (1 - entry_odd / exit_odd)
    return stake * (entry_odd / exit_odd - 1)


def pnl_settle(side, stake, odd, won, commission=0.0):
    if side == 'back':
        pl = stake * (odd - 1) if won else -stake
    else:
        pl = -stake * (odd - 1) if won else stake
    if pl > 0 and commission:
        pl *= (1 - commission)
    return pl
