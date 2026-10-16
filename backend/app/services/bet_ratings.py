"""Força dos clubes no tempo (Elo com saldo de gols) para precificar jogos sem odds cadastradas.

Fontes: `historico_jogos` (primeiras divisões, desde 2012) + `jogos` (SofaScore, inclui estaduais e copas).
O rating de cada clube é guardado como linha do tempo, permitindo consultar a força "até a data limite"
sem usar nenhum jogo posterior. Clubes nunca vistos (ex.: times de estaduais) começam abaixo da média
da primeira divisão, porque as fontes só cobrem as elites nacionais.
"""
from __future__ import annotations

import pickle
import threading
import time
from bisect import bisect_right
from datetime import date
from math import log
from pathlib import Path

import numpy as np
from sqlalchemy import text

from ..db import history_connection
from .elo_service import normalize_name

CACHE_FILE = Path(__file__).resolve().parents[2] / '.cache' / 'ratings_rows.pkl'
CACHE_HOURS = 12
START = date(2012, 1, 1)
BASE = 1500.0          # clube médio de primeira divisão
NEWCOMER = 1330.0      # clube sem histórico nas fontes (divisões inferiores / estaduais)
HOME_ADV = 60.0
K = 22.0
YEAR_RETENTION = 0.85  # regressão anual à média
DEFAULT_GOALS = 2.6

_lock = threading.Lock()
_state: dict = {}


def _fetch_history():
    try:
        if CACHE_FILE.exists() and time.time() - CACHE_FILE.stat().st_mtime < CACHE_HOURS * 3600:
            return pickle.loads(CACHE_FILE.read_bytes())
    except Exception:
        pass
    rows, last = [], 0
    while True:
        for attempt in range(4):
            try:
                with history_connection() as conn:
                    chunk = [tuple(r) for r in conn.execute(text(
                        '''SELECT id, data, pais, campeonato, casa, fora, gols_casa, gols_fora FROM public.historico_jogos
                           WHERE id > :last AND data >= :start AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
                           ORDER BY id LIMIT 5000'''), {'last': last, 'start': START})]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1][0]
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_bytes(pickle.dumps(rows))
    except Exception:
        pass
    return rows


def _build(extra_games):
    """extra_games: dicts da tabela jogos (data, pais, campeonato, casa, fora, gh, ga)."""
    seen, games = set(), []
    for _id, d, pais, camp, casa, fora, gh, ga in _fetch_history():
        key = (d, normalize_name(casa), normalize_name(fora))
        seen.add(key)
        games.append((d, pais, camp, casa, fora, int(gh), int(ga)))
    for g in extra_games:
        if g['gh'] is None or g['ga'] is None:
            continue
        key = (g['data'], normalize_name(g['casa']), normalize_name(g['fora']))
        if key in seen:
            continue
        seen.add(key)
        games.append((g['data'], g['pais'], g['campeonato'], g['casa'], g['fora'], int(g['gh']), int(g['ga'])))
    games.sort(key=lambda r: r[0])

    countries_by_name: dict[str, set] = {}
    for d, pais, camp, casa, fora, gh, ga in games:
        if camp and pais and not _is_continental(pais):
            for n in (casa, fora):
                countries_by_name.setdefault(normalize_name(n), set()).add(pais)

    rating: dict = {}; last_year: dict = {}; played: dict = {}
    timeline: dict = {}                    # key -> ([datas], [rating após o jogo])
    comp_goals: dict = {}                  # (pais, campeonato) -> ([datas], [gols acumulados], [jogos acumulados])
    xs, ys = [], []
    for d, pais, camp, casa, fora, gh, ga in games:
        kh = _key(pais, casa, countries_by_name); ka = _key(pais, fora, countries_by_name)
        rh = _current(kh, d, rating, last_year); ra = _current(ka, d, rating, last_year)
        diff = rh + HOME_ADV - ra
        if played.get(kh, 0) >= 15 and played.get(ka, 0) >= 15 and d.year >= 2014:
            xs.append(rh - ra); ys.append(gh - ga)
        expected = 1 / (1 + 10 ** (-diff / 400))
        result = 1.0 if gh > ga else 0.5 if gh == ga else 0.0
        mult = log(abs(gh - ga) + 1) + 1
        delta = K * mult * (result - expected)
        rating[kh] = rh + delta; rating[ka] = ra - delta
        for k in (kh, ka):
            last_year[k] = d.year; played[k] = played.get(k, 0) + 1
            tl = timeline.setdefault(k, ([], []))
            tl[0].append(d); tl[1].append(rating[k])
        cg = comp_goals.setdefault((pais, camp), ([], [], []))
        prev_g = cg[1][-1] if cg[1] else 0; prev_n = cg[2][-1] if cg[2] else 0
        cg[0].append(d); cg[1].append(prev_g + gh + ga); cg[2].append(prev_n + 1)
    # calibração: saldo de gols esperado ~ a + b*(Rmandante - Rvisitante)
    if len(xs) > 500:
        A = np.vstack([np.ones(len(xs)), np.array(xs)]).T
        a, b = np.linalg.lstsq(A, np.array(ys, dtype=float), rcond=None)[0]
    else:
        a, b = 0.35, 0.0045
    return {'timeline': timeline, 'comp_goals': comp_goals, 'countries': countries_by_name,
            'a': float(a), 'b': float(b), 'games': len(games)}


CONTINENTAL = {'europa', 'américa do sul', 'america do sul', 'mundo', 'internacional', 'ásia', 'asia', 'áfrica', 'africa',
               'concacaf', 'américa do norte', 'oceania', 'conmebol', 'uefa'}


def _is_continental(pais):
    return (pais or '').strip().lower() in CONTINENTAL


def _key(pais, name, countries_by_name):
    n = normalize_name(name)
    if _is_continental(pais):
        options = countries_by_name.get(n)
        if options and len(options) == 1:
            return (next(iter(options)), n)
    return (pais, n)


def _current(key, d, rating, last_year):
    r = rating.get(key)
    if r is None:
        return NEWCOMER
    years = d.year - last_year.get(key, d.year)
    return BASE + (r - BASE) * (YEAR_RETENTION ** years) if years > 0 else r


def state(extra_loader):
    bucket = int(time.time() // 3600)
    with _lock:
        if _state.get('bucket') != bucket:
            _state.clear()
            _state.update(_build(extra_loader()))
            _state['bucket'] = bucket
        return _state


def rating_at(st, pais, name, as_of: date):
    key = _key(pais, name, st['countries'])
    tl = st['timeline'].get(key)
    if not tl:
        return NEWCOMER, 0
    i = bisect_right(tl[0], as_of)
    if i == 0:
        return NEWCOMER, 0
    r = tl[1][i - 1]
    years = as_of.year - tl[0][i - 1].year
    if years > 0:
        r = BASE + (r - BASE) * (YEAR_RETENTION ** years)
    return r, i


def league_goals(st, pais, campeonato, as_of: date):
    cg = st['comp_goals'].get((pais, campeonato))
    if not cg:
        return DEFAULT_GOALS, 0
    i = bisect_right(cg[0], as_of)
    if i == 0:
        return DEFAULT_GOALS, 0
    j = max(0, i - 400)          # últimos ~400 jogos do campeonato
    goals = cg[1][i - 1] - (cg[1][j - 1] if j > 0 else 0)
    n = cg[2][i - 1] - (cg[2][j - 1] if j > 0 else 0)
    mu = goals / n if n else DEFAULT_GOALS
    # encolhe para a média padrão quando há poucos jogos
    w = min(n / 60, 1.0)
    return w * mu + (1 - w) * DEFAULT_GOALS, n


def expected_goals(st, game, as_of: date):
    """(λ mandante, λ visitante, detalhes) usando apenas dados até `as_of`."""
    rh, nh = rating_at(st, game['pais'], game['casa'], as_of)
    ra, na = rating_at(st, game['pais'], game['fora'], as_of)
    mu, n_league = league_goals(st, game['pais'], game['campeonato'], as_of)
    supremacy = st['a'] + st['b'] * (rh - ra)
    supremacy = max(-3.2, min(3.2, supremacy))
    lh = max(0.15, (mu + supremacy) / 2)
    la = max(0.15, (mu - supremacy) / 2)
    # mantém o total esperado próximo da média do campeonato após o corte em 0,15
    scale = mu / (lh + la) if lh + la > mu + 0.3 else 1.0
    return lh * scale, la * scale, {'rating_casa': round(rh), 'rating_fora': round(ra), 'jogos_casa': nh, 'jogos_fora': na,
                                    'media_gols_campeonato': round(mu, 2)}
