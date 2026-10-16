import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from statistics import mean, pstdev
from time import time

import numpy as np
from sqlalchemy import text
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..config import settings
from ..db import app_engine, history_connection
from .elo_service import HOME_ADVANTAGE, elo_probability, normalize_name, season_key
from .odds_service import norm_header, parse_date, parse_num

CACHE_SECONDS = 600
MARKETS = {
    "home": "Vitória do mandante",
    "away": "Vitória do visitante",
    "over15": "Over 1,5",
    "over25": "Over 2,5",
    "btts": "Ambos marcam",
}
FEATURE_NAMES = [
    "market_home", "market_draw", "market_away", "market_over25",
    "elo_home", "elo_away", "elo_diff",
    "home_perf5", "home_perf10", "home_perf20",
    "away_perf5", "away_perf10", "away_perf20",
    "home_gf10", "home_ga10", "away_gf10", "away_ga10",
    "home_attack", "home_defense", "away_attack", "away_defense",
    "home_over15_10", "home_over25_10", "home_btts10",
    "away_over15_10", "away_over25_10", "away_btts10",
    "home_cg1", "home_cg2", "home_cv_cg1", "home_cv_cg2",
    "away_cg1", "away_cg2", "away_cv_cg1", "away_cv_cg2",
    "market_value_gap", "h2h_home", "h2h_draw", "h2h_away",
    "poisson_home_lambda", "poisson_away_lambda", "poisson_over15", "poisson_over25", "poisson_btts",
]

FEATURE_INDEX = {name: idx for idx, name in enumerate(FEATURE_NAMES)}
# A odd não entra mais como variável explicativa da probabilidade esportiva.
# Ela é usada depois, apenas para preço/edge/EV.
SPORT_FEATURE_INDEXES = [
    idx for idx, name in enumerate(FEATURE_NAMES)
    if not name.startswith("market_")
]


def _sports_vector(feature_row):
    return [feature_row[i] for i in SPORT_FEATURE_INDEXES]


def _finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _mean_present(values):
    vals = [v for v in (_finite(x) for x in values) if v is not None and v > 0]
    return sum(vals) / len(vals) if vals else None


def _inverse_percentile(value, samples):
    """Quanto menor o valor, maior o score. Retorna 0..1."""
    value = _finite(value)
    vals = sorted(v for v in (_finite(x) for x in samples) if v is not None and v > 0)
    if value is None or not vals:
        return 0.5
    # Fração da amostra com valor >= ao atual. Custo/CV menor => score maior.
    return sum(1 for x in vals if x >= value) / len(vals)


def _cost_goal_context(feature_row, train_rows, market):
    if market == "over25":
        cost_names = ("home_cg2", "away_cg2")
        cv_names = ("home_cv_cg2", "away_cv_cg2")
        label = "2.0"
    else:
        cost_names = ("home_cg1", "away_cg1")
        cv_names = ("home_cv_cg1", "away_cv_cg1")
        label = "1.0"

    costs = [feature_row[FEATURE_INDEX[n]] for n in cost_names]
    cvs = [feature_row[FEATURE_INDEX[n]] for n in cv_names]
    avg_cost = _mean_present(costs)
    avg_cv = _mean_present(cvs)

    ref_cost = []
    ref_cv = []
    for r in train_rows:
        f = r["X"]
        ref_cost.extend(f[FEATURE_INDEX[n]] for n in cost_names)
        ref_cv.extend(f[FEATURE_INDEX[n]] for n in cv_names)

    cost_rank = _inverse_percentile(avg_cost, ref_cost)
    cv_rank = _inverse_percentile(avg_cv, ref_cv)
    score = 0.60 * cost_rank + 0.40 * cv_rank

    return {
        "label": label,
        "home_cost": _finite(costs[0]),
        "away_cost": _finite(costs[1]),
        "home_cv": _finite(cvs[0]),
        "away_cv": _finite(cvs[1]),
        "avg_cost": avg_cost,
        "avg_cv": avg_cv,
        "score": score,
    }


def _recent_market_rate(feature_row, market):
    if market == "over15":
        names = ("home_over15_10", "away_over15_10")
    elif market == "over25":
        names = ("home_over25_10", "away_over25_10")
    elif market == "btts":
        names = ("home_btts10", "away_btts10")
    else:
        return None
    vals = [_finite(feature_row[FEATURE_INDEX[n]]) for n in names]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _clip_probability(value: float, floor: float = 1e-5) -> float:
    return max(floor, min(1.0 - floor, float(value)))


def _normalize_probs(values):
    arr = np.asarray(values, dtype=float)
    arr = np.clip(arr, 1e-9, None)
    total = float(arr.sum())
    if total <= 0:
        return np.repeat(1.0 / len(arr), len(arr))
    return arr / total


def _wilson_interval(successes: float, n: float, z: float = 1.959963984540054):
    """Intervalo de Wilson para proporção. z=1,96 => IC bilateral de 95%."""
    if n <= 0:
        return 0.0, 1.0
    p = max(0.0, min(1.0, successes / n))
    denom = 1.0 + (z * z) / n
    center = p + (z * z) / (2.0 * n)
    spread = z * math.sqrt((p * (1.0 - p) / n) + (z * z) / (4.0 * n * n))
    lower = max(0.0, (center - spread) / denom)
    upper = min(1.0, (center + spread) / denom)
    return lower, upper


def _wilson_lower(successes: float, n: float, z: float = 1.2815515655446004) -> float:
    """Limite unilateral mais leve usado no freio conservador operacional."""
    return _wilson_interval(successes, n, z=z)[0]


def _direct_percentile(value, samples):
    """Quanto maior o valor, maior o score. Retorna 0..1."""
    value = _finite(value)
    vals = sorted(v for v in (_finite(x) for x in samples) if v is not None and v > 0)
    if value is None or not vals:
        return 0.5
    return sum(1 for x in vals if x <= value) / len(vals)


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _strength_context(feature_row):
    """Confronto ataque/defesa relativo à liga. Ataque >1 é melhor; defesa <1 é melhor."""
    ha = max(float(feature_row[FEATURE_INDEX["home_attack"]]), 0.05)
    hd = max(float(feature_row[FEATURE_INDEX["home_defense"]]), 0.05)
    aa = max(float(feature_row[FEATURE_INDEX["away_attack"]]), 0.05)
    ad = max(float(feature_row[FEATURE_INDEX["away_defense"]]), 0.05)
    home_threat = ha * ad
    away_threat = aa * hd
    ratio = away_threat / max(home_threat, 0.05)
    matchup_score = 1.0 / (1.0 + math.exp(-2.6 * math.log(max(ratio, 1e-6))))
    return {
        "home_attack": ha, "home_defense": hd,
        "away_attack": aa, "away_defense": ad,
        "home_threat": home_threat, "away_threat": away_threat,
        "away_matchup_ratio": ratio, "away_matchup_score": matchup_score,
    }


def _away_cost_context(feature_row, train_rows):
    """Qualidade do custo do gol do visitante, relativa ao histórico da competição."""
    away_cost = _finite(feature_row[FEATURE_INDEX["away_cg1"]])
    away_cv = _finite(feature_row[FEATURE_INDEX["away_cv_cg1"]])
    home_cost = _finite(feature_row[FEATURE_INDEX["home_cg1"]])

    ref_away_cost = [r["X"][FEATURE_INDEX["away_cg1"]] for r in train_rows]
    ref_away_cv = [r["X"][FEATURE_INDEX["away_cv_cg1"]] for r in train_rows]
    ref_home_cost = [r["X"][FEATURE_INDEX["home_cg1"]] for r in train_rows]

    own_cost_score = _inverse_percentile(away_cost, ref_away_cost)
    own_cv_score = _inverse_percentile(away_cv, ref_away_cv)
    opponent_cost_score = _direct_percentile(home_cost, ref_home_cost)
    score = 0.50 * own_cost_score + 0.30 * own_cv_score + 0.20 * opponent_cost_score
    return {
        "away_cost": away_cost, "away_cv": away_cv, "home_cost": home_cost,
        "score": score,
        "away_cost_percentile": own_cost_score,
        "away_cv_percentile": own_cv_score,
        "home_cost_percentile": opponent_cost_score,
    }


def _away_structural_pattern(feature_row, train_rows, draw_rate):
    """Padrão visitante: ELO + encaixe ataque/defesa + custo do gol."""
    market_p = float(feature_row[FEATURE_INDEX["market_away"]])
    eh = float(feature_row[FEATURE_INDEX["elo_home"]]) * 2000.0
    ea = float(feature_row[FEATURE_INDEX["elo_away"]]) * 2000.0
    elo_p = float(elo_probability(eh, ea, draw_rate)["away"])
    away_gap = ea - (eh + HOME_ADVANTAGE)
    elo_edge = elo_p - market_p
    elo_edge_score = _clamp01(0.5 + elo_edge / 0.10)
    elo_gap_score = 1.0 / (1.0 + math.exp(-away_gap / 90.0))
    elo_score = 0.65 * elo_edge_score + 0.35 * elo_gap_score

    strength = _strength_context(feature_row)
    cost = _away_cost_context(feature_row, train_rows)
    core = 0.42 * elo_score + 0.38 * strength["away_matchup_score"] + 0.20 * cost["score"]
    return {
        "score": core, "elo_score": elo_score, "elo_probability": elo_p,
        "elo_edge": elo_edge, "away_elo_gap": away_gap,
        "strength": strength, "cost": cost,
    }


def _learn_away_pattern_threshold(train_rows, draw_rate):
    """Aprende um limiar de confluência em uma janela temporal recente do histórico."""
    if len(train_rows) < 140:
        return {"threshold": 0.60, "bets": 0, "roi": None, "roi_ci95_lower": None}

    split = max(100, int(len(train_rows) * 0.70))
    reference = train_rows[:split]
    validation = train_rows[split:]
    observations = []
    for r in validation:
        odd = r.get("odds", {}).get("away")
        if not odd or float(odd) <= 1:
            continue
        ctx = _away_structural_pattern(r["X"], reference, draw_rate)
        market_p = float(r["market_probs"]["away"])
        if ctx["elo_probability"] <= market_p:
            continue
        ret = (float(odd) - 1.0) if r["labels"]["away"] else -1.0
        observations.append((ctx["score"], ret))

    min_bets = max(15, int(len(validation) * 0.05))
    candidates = []
    for threshold in np.arange(0.52, 0.721, 0.02):
        selected = [ret for score, ret in observations if score >= float(threshold)]
        if len(selected) < min_bets:
            continue
        roi = float(np.mean(selected))
        if len(selected) > 1:
            se = float(np.std(selected, ddof=1)) / math.sqrt(len(selected))
            lower95 = roi - 1.959963984540054 * se
        else:
            lower95 = -1.0
        candidates.append((float(threshold), len(selected), roi, lower95))

    if not candidates:
        return {"threshold": 0.60, "bets": 0, "roi": None, "roi_ci95_lower": None}

    positive = [x for x in candidates if x[2] > 0]
    chosen = max(positive or candidates, key=lambda x: (x[3], x[2], x[1]))
    threshold = max(0.56, min(0.68, chosen[0]))
    return {
        "threshold": round(threshold, 3), "bets": chosen[1],
        "roi": round(chosen[2] * 100, 2),
        "roi_ci95_lower": round(chosen[3] * 100, 2),
    }


def _ece_binary(y_true, probs, bins: int = 10) -> float:
    if not probs:
        return 0.0
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if lo <= p < hi or (b == bins - 1 and p == 1)]
        if not idx:
            continue
        conf = sum(probs[i] for i in idx) / len(idx)
        actual = sum(y_true[i] for i in idx) / len(idx)
        ece += len(idx) / len(probs) * abs(conf - actual)
    return ece


def _ece_multiclass(y_true, probs, bins: int = 10) -> float:
    if not probs:
        return 0.0
    confs = [max(p) for p in probs]
    preds = [int(np.argmax(p)) for p in probs]
    correct = [int(pred == y) for pred, y in zip(preds, y_true)]
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(confs) if lo <= p < hi or (b == bins - 1 and p == 1)]
        if not idx:
            continue
        conf = sum(confs[i] for i in idx) / len(idx)
        actual = sum(correct[i] for i in idx) / len(idx)
        ece += len(idx) / len(confs) * abs(conf - actual)
    return ece


def _season_text(value: str | None) -> str:
    raw = str(value or "").strip().replace("-", "/")
    if re.fullmatch(r"\d{4}", raw):
        return raw
    if re.fullmatch(r"\d{4}/\d{4}", raw):
        return raw
    if re.fullmatch(r"\d{4}/\d{2}", raw):
        start, short = raw.split("/")
        end = (int(start) // 100) * 100 + int(short)
        if end < int(start):
            end += 100
        return f"{start}/{end:04d}"
    return raw


def _season_ge(a: str, b: str) -> bool:
    return season_key(_season_text(a)) >= season_key(_season_text(b))


def _competition_meta(competition_id: int):
    with app_engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT c.id, c.nome AS competition, c.pais_id, p.nome AS country
            FROM {settings.app_schema}.campeonatos c
            JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
            WHERE c.id=:id
        """), {"id": competition_id}).mappings().first()
    if not row:
        raise ValueError("Campeonato não encontrado.")
    return dict(row)


def _registry(competition_id: int):
    with app_engine.connect() as conn:
        clubs = [dict(r) for r in conn.execute(text(f"""
            SELECT DISTINCT cl.id, cl.nome
            FROM {settings.app_schema}.clubes cl
            JOIN {settings.app_schema}.clubes_campeonatos cc ON cc.clube_id=cl.id
            WHERE cc.campeonato_id=:c
        """), {"c": competition_id}).mappings()]
        aliases = [dict(r) for r in conn.execute(text(f"""
            SELECT clube_id, alias FROM {settings.app_schema}.clubes_aliases
            WHERE campeonato_id=:c OR campeonato_id IS NULL
        """), {"c": competition_id}).mappings()]
    mp = {normalize_name(r["nome"]): int(r["id"]) for r in clubs}
    names = {int(r["id"]): r["nome"] for r in clubs}
    for a in aliases:
        mp[normalize_name(a["alias"])] = int(a["clube_id"])
    return names, mp


def _all_history(meta: dict):
    with history_connection() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT id, jogo_id, data, temporada, campeonato, pais, rodada,
                   casa, fora, gols_casa, gols_fora
            FROM {settings.history_schema}.{settings.history_table}
            WHERE pais=:country AND campeonato=:competition
              AND data IS NOT NULL AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
            ORDER BY data ASC, id ASC
        """), {"country": meta["country"], "competition": meta["competition"]}).mappings()]
    return rows


def _all_odds(competition_id: int):
    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT id, temporada, data, clube_casa_id, clube_fora_id,
                   odd_casa::float, odd_empate::float, odd_fora::float,
                   odd_over_25::float, odd_under_25::float
            FROM {settings.app_schema}.odds_jogos
            WHERE campeonato_id=:c AND data IS NOT NULL
            ORDER BY data ASC, id ASC
        """), {"c": competition_id}).mappings()]
    return rows


def _market_values(competition_id: int):
    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT temporada, clube_id, valor::float
            FROM {settings.app_schema}.valores_mercado
            WHERE campeonato_id=:c
        """), {"c": competition_id}).mappings()]
    by = {(str(r["temporada"]), int(r["clube_id"])): float(r["valor"]) for r in rows}
    geo = {}
    grouped = defaultdict(list)
    for r in rows:
        grouped[str(r["temporada"])].append(float(r["valor"]))
    for s, vals in grouped.items():
        positives = [v for v in vals if v > 0]
        if positives:
            geo[s] = math.exp(sum(math.log(v) for v in positives) / len(positives))
    return by, geo


def _elo_movements(competition_id: int):
    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT data, temporada, casa_clube_id, fora_clube_id,
                   elo_casa_antes::float, elo_fora_antes::float,
                   elo_casa_depois::float, elo_fora_depois::float
            FROM {settings.app_schema}.elo_movimentos
            WHERE campeonato_id=:c
        """), {"c": competition_id}).mappings()]
        current = [dict(r) for r in conn.execute(text(f"""
            SELECT temporada, clube_id, elo_atual::float, elo_inicial::float
            FROM {settings.app_schema}.elo_clubes WHERE campeonato_id=:c
        """), {"c": competition_id}).mappings()]
    exact = {}
    latest = {}
    for r in rows:
        if not r.get("data"):
            continue
        key = (str(r["data"]), int(r["casa_clube_id"]), int(r["fora_clube_id"]))
        exact[key] = (float(r["elo_casa_antes"]), float(r["elo_fora_antes"]))
        latest[int(r["casa_clube_id"])] = float(r["elo_casa_depois"])
        latest[int(r["fora_clube_id"])] = float(r["elo_fora_depois"])
    by_season = {(str(r["temporada"]), int(r["clube_id"])): float(r["elo_atual"]) for r in current}
    initial = {(str(r["temporada"]), int(r["clube_id"])): float(r["elo_inicial"]) for r in current}
    return exact, latest, by_season, initial


def _pct(rows, n: int | None = None):
    data = rows[-n:] if n else rows
    if not data:
        return 0.5
    return sum(x["points"] for x in data) / (3 * len(data))


def _avg(rows, key, n=10, default=0.0):
    data = rows[-n:] if n else rows
    vals = [float(x[key]) for x in data if x.get(key) is not None]
    return sum(vals) / len(vals) if vals else default


def _rate(rows, key, n=10, default=0.5):
    data = rows[-n:] if n else rows
    if not data:
        return default
    return sum(1 for x in data if x.get(key)) / len(data)


def _cv(rows, key, n=10):
    vals = [float(x[key]) for x in rows[-n:] if x.get(key) is not None]
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return pstdev(vals) / m if m else 0.0


def _team_strength(team_rows, venue: str, league_home_avg: float, league_away_avg: float):
    venue_rows = [r for r in team_rows if r.get("venue") == venue][-12:]
    rows = venue_rows if len(venue_rows) >= 3 else team_rows[-12:]
    if not rows:
        return 1.0, 1.0
    gf = sum(r["gf"] for r in rows) / len(rows)
    ga = sum(r["ga"] for r in rows) / len(rows)
    if venue == "home":
        return gf / max(league_home_avg, 0.15), ga / max(league_away_avg, 0.15)
    return gf / max(league_away_avg, 0.15), ga / max(league_home_avg, 0.15)


def _h2h(h2h_rows):
    data = h2h_rows[-10:]
    if not data:
        return 0.4, 0.25, 0.35
    n = len(data)
    return (
        sum(r == "H" for r in data) / n,
        sum(r == "D" for r in data) / n,
        sum(r == "A" for r in data) / n,
    )


def _no_vig_1x2(h, d, a):
    inv = [1 / max(float(x), 1.0001) for x in (h, d, a)]
    s = sum(inv)
    return [x / s for x in inv]


def _no_vig_binary(over, under):
    if not over or not under or over <= 1 or under <= 1:
        return None
    a, b = 1 / over, 1 / under
    return a / (a + b)


def _poisson_pmf(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _poisson_markets(home_lambda: float, away_lambda: float):
    total = max(home_lambda + away_lambda, 0.01)
    p0 = math.exp(-total)
    p1 = p0 * total
    p2 = p1 * total / 2
    over15 = 1 - p0 - p1
    over25 = 1 - p0 - p1 - p2
    home_zero = math.exp(-max(home_lambda, 0.01))
    away_zero = math.exp(-max(away_lambda, 0.01))
    btts = 1 - home_zero - away_zero + math.exp(-total)
    return over15, over25, btts


def _feature_vector(home_id, away_id, season, home_rows, away_rows, league_state,
                    h2h_rows, odds, values, geo, elo_home, elo_away):
    mh, md, ma = _no_vig_1x2(odds["home_odd"], odds["draw_odd"], odds["away_odd"])
    market_o25 = _no_vig_binary(odds.get("over25"), odds.get("under25"))
    market_o25 = market_o25 if market_o25 is not None else 0.5
    league_home_avg = league_state["home_goals"] / league_state["games"] if league_state["games"] else 1.45
    league_away_avg = league_state["away_goals"] / league_state["games"] if league_state["games"] else 1.15
    ha, hd = _team_strength(home_rows, "home", league_home_avg, league_away_avg)
    aa, ad = _team_strength(away_rows, "away", league_home_avg, league_away_avg)
    h2h_h, h2h_d, h2h_a = _h2h(h2h_rows)
    home_lambda = max(0.05, league_home_avg * ha * ad)
    away_lambda = max(0.05, league_away_avg * aa * hd)
    poisson_o15, poisson_o25, poisson_btts = _poisson_markets(home_lambda, away_lambda)

    season_candidates = [str(season)]
    sk = season_key(str(season))
    # single-year and cross-year variants are intentionally not coerced here.
    hv = None
    av = None
    center = None
    for ss in season_candidates:
        hv = values.get((ss, home_id)) if hv is None else hv
        av = values.get((ss, away_id)) if av is None else av
        center = geo.get(ss) if center is None else center
    if hv and av and center:
        mv_gap = math.log2(hv / center) - math.log2(av / center)
    elif hv and av:
        mv_gap = math.log2(max(hv,1) / max(av,1))
    else:
        mv_gap = 0.0

    return [
        mh, md, ma, market_o25,
        elo_home / 2000.0, elo_away / 2000.0, (elo_home + HOME_ADVANTAGE - elo_away) / 400.0,
        _pct(home_rows,5), _pct(home_rows,10), _pct(home_rows,20),
        _pct(away_rows,5), _pct(away_rows,10), _pct(away_rows,20),
        _avg(home_rows,"gf"), _avg(home_rows,"ga"), _avg(away_rows,"gf"), _avg(away_rows,"ga"),
        ha, hd, aa, ad,
        _rate(home_rows,"over15"), _rate(home_rows,"over25"), _rate(home_rows,"btts"),
        _rate(away_rows,"over15"), _rate(away_rows,"over25"), _rate(away_rows,"btts"),
        _avg(home_rows,"cg1",10,0.0), _avg(home_rows,"cg2",10,0.0), _cv(home_rows,"cg1"), _cv(home_rows,"cg2"),
        _avg(away_rows,"cg1",10,0.0), _avg(away_rows,"cg2",10,0.0), _cv(away_rows,"cg1"), _cv(away_rows,"cg2"),
        mv_gap, h2h_h, h2h_d, h2h_a,
        home_lambda, away_lambda, poisson_o15, poisson_o25, poisson_btts,
    ]


def _training_cache_key(competition_id, cutoff_season):
    return int(time() // CACHE_SECONDS), competition_id, cutoff_season


@lru_cache(maxsize=24)
def _build_dataset_cached(bucket: int, competition_id: int, cutoff_season: str):
    meta = _competition_meta(competition_id)
    names, name_map = _registry(competition_id)
    history = _all_history(meta)
    odds_rows = _all_odds(competition_id)
    odds_map = {(str(r["data"]), int(r["clube_casa_id"]), int(r["clube_fora_id"])): r for r in odds_rows if r.get("data")}
    values, geo = _market_values(competition_id)
    elo_exact, _, _, elo_initial = _elo_movements(competition_id)

    team_hist = defaultdict(list)
    h2h = defaultdict(list)
    league = {"games": 0, "home_goals": 0, "away_goals": 0}
    rolling_elo = defaultdict(lambda: 1500.0)
    rows = []

    for game in history:
        home_id = name_map.get(normalize_name(game.get("casa") or ""))
        away_id = name_map.get(normalize_name(game.get("fora") or ""))
        if not home_id or not away_id or not game.get("data"):
            continue
        season = _season_text(game.get("temporada"))
        d = str(game["data"])
        gh, ga = int(game["gols_casa"]), int(game["gols_fora"])
        key = (d, home_id, away_id)
        odds = odds_map.get(key)
        elo_pair = elo_exact.get(key)
        if elo_pair:
            eh, ea = elo_pair
        else:
            eh = elo_initial.get((season, home_id), rolling_elo[home_id])
            ea = elo_initial.get((season, away_id), rolling_elo[away_id])

        if odds and _season_ge(season, cutoff_season):
            odds_input = {
                "home_odd": float(odds["odd_casa"]), "draw_odd": float(odds["odd_empate"]), "away_odd": float(odds["odd_fora"]),
                "over25": float(odds["odd_over_25"]) if odds.get("odd_over_25") else None,
                "under25": float(odds["odd_under_25"]) if odds.get("odd_under_25") else None,
            }
            feat = _feature_vector(home_id, away_id, season, team_hist[home_id], team_hist[away_id], league,
                                   h2h[(min(home_id,away_id), max(home_id,away_id))], odds_input, values, geo, eh, ea)
            mh, md, ma = _no_vig_1x2(
                odds_input["home_odd"], odds_input["draw_odd"], odds_input["away_odd"]
            )
            market_o25 = _no_vig_binary(odds_input.get("over25"), odds_input.get("under25"))
            rows.append({
                "date": d, "season": season, "home_id": home_id, "away_id": away_id,
                "home": names.get(home_id, game["casa"]), "away": names.get(away_id, game["fora"]),
                "X": feat,
                "outcome": 0 if gh > ga else 2 if ga > gh else 1,
                "labels": {
                    "home": int(gh > ga), "away": int(ga > gh), "over15": int(gh + ga > 1.5),
                    "over25": int(gh + ga > 2.5), "btts": int(gh > 0 and ga > 0),
                },
                "market_probs": {
                    "home": mh, "draw": md, "away": ma, "over25": market_o25,
                },
                "odds": {
                    "home": odds_input["home_odd"], "draw": odds_input["draw_odd"],
                    "away": odds_input["away_odd"], "over25": odds_input["over25"],
                    "under25": odds_input["under25"],
                },
            })

        # Update rolling histories after the pre-match feature is recorded.
        mh = 1 / float(odds["odd_casa"]) if odds and odds.get("odd_casa") else None
        ma = 1 / float(odds["odd_fora"]) if odds and odds.get("odd_fora") else None
        home_rec = {
            "gf": gh, "ga": ga, "points": 3 if gh > ga else 1 if gh == ga else 0, "venue": "home",
            "over15": gh+ga>1.5, "over25": gh+ga>2.5, "btts": gh>0 and ga>0,
            "cg1": gh / mh if mh else None, "cg2": (gh/2 + mh/2) if mh else None,
        }
        away_rec = {
            "gf": ga, "ga": gh, "points": 3 if ga > gh else 1 if gh == ga else 0, "venue": "away",
            "over15": gh+ga>1.5, "over25": gh+ga>2.5, "btts": gh>0 and ga>0,
            "cg1": ga / ma if ma else None, "cg2": (ga/2 + ma/2) if ma else None,
        }
        team_hist[home_id].append(home_rec)
        team_hist[away_id].append(away_rec)
        league["games"] += 1; league["home_goals"] += gh; league["away_goals"] += ga
        h2h_key=(min(home_id,away_id),max(home_id,away_id))
        h2h[h2h_key].append("H" if gh>ga else "D" if gh==ga else "A")
        # fallback rolling ELO, used only when stored ELO movements do not exist.
        expected = 1/(1+10**((rolling_elo[away_id]-(rolling_elo[home_id]+HOME_ADVANTAGE))/400))
        actual = 1 if gh>ga else .5 if gh==ga else 0
        delta = 20*(actual-expected)
        rolling_elo[home_id]+=delta; rolling_elo[away_id]-=delta

    context = {
        "team_hist": dict(team_hist), "h2h": dict(h2h), "league": league,
        "values": values, "geo": geo, "elo_latest": dict(rolling_elo), "names": names, "name_map": name_map,
    }
    return rows, context


def _parse_table(raw_text: str, fallback_season: str):
    raw = (raw_text or "").strip()
    if not raw:
        raise ValueError("Cole os jogos e as odds antes de analisar.")
    lines = [x.strip() for x in raw.splitlines() if x.strip()]

    def cells(line):
        s=line.strip()
        if s.startswith("|"): s=s[1:]
        if s.endswith("|"): s=s[:-1]
        return [x.strip() for x in s.split("|")]

    if "|" in lines[0]:
        headers=cells(lines[0]); start=2 if len(lines)>1 and all(re.fullmatch(r":?-{3,}:?",x) for x in cells(lines[1])) else 1
        data=[cells(x) for x in lines[start:]]
    elif "\t" in lines[0]:
        headers=[x.strip() for x in lines[0].split("\t")]; data=[[x.strip() for x in line.split("\t")] for line in lines[1:]]
    else:
        raise ValueError("Use tabela Markdown ou cole diretamente do Excel/Google Sheets com cabeçalho.")

    aliases={
        "season":{"temporada","season"}, "date":{"data","date"}, "home":{"mandante","casa","home","hometeam"},
        "away":{"visitante","fora","away","awayteam"}, "home_odd":{"oddcasa","oddmandante","b365h"},
        "draw_odd":{"oddempate","b365d"}, "away_odd":{"oddfora","oddvisitante","b365a"},
        "over15":{"over15","over1.5","oddover15"}, "under15":{"under15","under1.5","oddunder15"},
        "over25":{"over25","over2.5","oddover25"}, "under25":{"under25","under2.5","oddunder25"},
        "btts":{"ambosmarcam","btts","bttssim","oddbtts"}, "btts_no":{"ambosnao","ambosnaomarcam","bttsnao","bttsno","oddbttsnao"},
    }
    found={}
    for h in headers:
        n=norm_header(h)
        for key, opts in aliases.items():
            if n in opts and key not in found: found[key]=headers.index(h)
    for req in ("date","home","away","home_odd","draw_odd","away_odd"):
        if req not in found: raise ValueError(f"Coluna obrigatória não encontrada: {req}.")
    out=[]
    for idx,row in enumerate(data,1):
        if len(row)<len(headers): row += [""]*(len(headers)-len(row))
        if len(row)>len(headers): continue
        get=lambda k: row[found[k]] if k in found else ""
        home,away=get("home").strip(),get("away").strip()
        if not home or not away: continue
        dt=parse_date(get("date")); ho,do,ao=parse_num(get("home_odd")),parse_num(get("draw_odd")),parse_num(get("away_odd"))
        if not dt or not all(v and v>1 for v in (ho,do,ao)): continue
        out.append({
            "row":idx,"season":_season_text(get("season") or fallback_season),"date":dt,"home":home,"away":away,
            "home_odd":ho,"draw_odd":do,"away_odd":ao,"over15":parse_num(get("over15")),"over25":parse_num(get("over25")),
            "btts":parse_num(get("btts")),"btts_no":parse_num(get("btts_no")),
            "under15":parse_num(get("under15")),"under25":parse_num(get("under25")),
        })
    if not out: raise ValueError("Nenhum jogo válido foi identificado.")
    return out


def _binary_pipeline(kind="logistic"):
    if kind == "tree":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                max_depth=4, max_iter=120, learning_rate=.04,
                l2_regularization=1.5, random_state=42,
            )),
        ])
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=900, C=.45, random_state=42)),
    ])


def _multiclass_pipeline(kind="logistic"):
    if kind == "tree":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                max_depth=4, max_iter=140, learning_rate=.04,
                l2_regularization=2.0, random_state=42,
            )),
        ])
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=1200, C=.35, random_state=42)),
    ])


def _fit_binary(X, y):
    y = np.asarray(y, dtype=int)
    if len(set(y.tolist())) < 2:
        return None
    m1 = _binary_pipeline("logistic")
    m1.fit(X, y)
    m2 = None
    if len(y) >= 450:
        m2 = _binary_pipeline("tree")
        m2.fit(X, y)
    return m1, m2


def _predict_binary(models, X):
    if not models:
        return None
    p1 = models[0].predict_proba(X)[:, 1]
    if models[1] is None:
        return p1
    p2 = models[1].predict_proba(X)[:, 1]
    return .72 * p1 + .28 * p2


def _fit_multiclass(X, y):
    y = np.asarray(y, dtype=int)
    if len(set(y.tolist())) < 3:
        return None
    m1 = _multiclass_pipeline("logistic")
    m1.fit(X, y)
    m2 = None
    if len(y) >= 500:
        m2 = _multiclass_pipeline("tree")
        m2.fit(X, y)
    return m1, m2


def _predict_multiclass(models, X):
    if not models:
        return None
    p1 = models[0].predict_proba(X)
    if models[1] is None:
        return p1
    p2 = models[1].predict_proba(X)
    return .75 * p1 + .25 * p2


def _best_blend_alpha(y_true, model_probs, base_probs, multiclass=False):
    """Peso escolhido exclusivamente por validação temporal; nada de 65% fixo."""
    if not y_true or not model_probs or not base_probs:
        return 0.0
    best_alpha, best_loss = 0.0, float("inf")
    for alpha in np.linspace(0.0, 1.0, 21):
        if multiclass:
            blended = [
                _normalize_probs(alpha * np.asarray(pm) + (1.0 - alpha) * np.asarray(pb))
                for pm, pb in zip(model_probs, base_probs)
            ]
            loss = log_loss(y_true, np.asarray(blended), labels=[0, 1, 2])
        else:
            blended = [
                _clip_probability(alpha * float(pm) + (1.0 - alpha) * float(pb))
                for pm, pb in zip(model_probs, base_probs)
            ]
            loss = log_loss(y_true, blended, labels=[0, 1])
        if loss < best_loss - 1e-10:
            best_loss, best_alpha = float(loss), float(alpha)
    return best_alpha


def _goal_structural_base(feature_row, market):
    recent = _recent_market_rate(feature_row, market)
    recent = 0.5 if recent is None else recent
    if market == "over15":
        poisson = float(feature_row[FEATURE_INDEX["poisson_over15"]])
    elif market == "over25":
        poisson = float(feature_row[FEATURE_INDEX["poisson_over25"]])
    else:
        poisson = float(feature_row[FEATURE_INDEX["poisson_btts"]])
    return _clip_probability(.68 * poisson + .32 * recent), poisson, recent


def _walk_forward_1x2(rows):
    rows = sorted(rows, key=lambda r: r["date"])
    n = len(rows)
    if n < 100:
        empty = {"samples": n, "validation_samples": 0, "brier": None, "log_loss": None,
                 "ece": None, "accuracy": None, "roi": None, "bets": 0, "blend_alpha": 0.0}
        return empty, empty, 0.0

    start = max(90, int(n * .55))
    step = max(30, int(n * .08))
    ys, p_models, p_markets = [], [], []
    home_odds, away_odds = [], []

    for pos in range(start, n, step):
        tr = rows[:pos]
        te = rows[pos:min(pos + step, n)]
        model = _fit_multiclass(
            np.asarray([_sports_vector(r["X"]) for r in tr], dtype=float),
            [r["outcome"] for r in tr],
        )
        if not model:
            continue
        pred = _predict_multiclass(model, np.asarray([_sports_vector(r["X"]) for r in te], dtype=float))
        for r, p in zip(te, pred):
            ys.append(int(r["outcome"]))
            p_models.append(_normalize_probs(p))
            p_markets.append(np.asarray([
                r["market_probs"]["home"], r["market_probs"]["draw"], r["market_probs"]["away"]
            ], dtype=float))
            home_odds.append(r["odds"].get("home"))
            away_odds.append(r["odds"].get("away"))

    if not ys:
        empty = {"samples": n, "validation_samples": 0, "brier": None, "log_loss": None,
                 "ece": None, "accuracy": None, "roi": None, "bets": 0, "blend_alpha": 0.0}
        return empty, empty, 0.0

    alpha = _best_blend_alpha(ys, p_models, p_markets, multiclass=True)
    probs = [_normalize_probs(alpha * pm + (1.0 - alpha) * pb) for pm, pb in zip(p_models, p_markets)]
    arr = np.asarray(probs)
    onehot = np.eye(3)[np.asarray(ys, dtype=int)]
    multiclass_brier = float(np.mean(np.sum((arr - onehot) ** 2, axis=1)))
    ll = float(log_loss(ys, arr, labels=[0, 1, 2]))
    acc = float(np.mean(np.argmax(arr, axis=1) == np.asarray(ys)))
    ece = _ece_multiclass(ys, probs)

    def side_health(side_idx, odds_list, label_name):
        event_y = [1 if y == side_idx else 0 for y in ys]
        event_p = [float(p[side_idx]) for p in probs]
        brier = float(brier_score_loss(event_y, event_p))
        returns = []
        for y, p, odd in zip(event_y, event_p, odds_list):
            if odd and p * float(odd) - 1.0 > 0:
                returns.append((float(odd) - 1.0) if y else -1.0)
        return {
            "samples": n,
            "validation_samples": len(event_p),
            "brier": round(brier, 4),
            "log_loss": round(ll, 4),
            "ece": round(_ece_binary(event_y, event_p) * 100, 2),
            "accuracy": round(acc * 100, 2),
            "roi": round(sum(returns) / len(returns) * 100, 2) if returns else None,
            "bets": len(returns),
            "blend_alpha": round(alpha, 2),
            "multiclass_brier": round(multiclass_brier, 4),
            "market_anchor_pct": round((1.0 - alpha) * 100, 1),
            "label": label_name,
        }

    return side_health(0, home_odds, "Casa"), side_health(2, away_odds, "Fora"), alpha


def _walk_forward_binary(rows, market):
    rows = sorted(rows, key=lambda r: r["date"])
    n = len(rows)
    if n < 100:
        return {
            "samples": n, "validation_samples": 0, "brier": None, "log_loss": None,
            "ece": None, "accuracy": None, "roi": None, "bets": 0,
            "blend_alpha": 0.0, "baseline": "estrutural",
        }, 0.0

    start = max(90, int(n * .55))
    step = max(30, int(n * .08))
    ys, p_models, p_bases, odds = [], [], [], []
    baseline_kind = "estrutural"

    for pos in range(start, n, step):
        tr = rows[:pos]
        te = rows[pos:min(pos + step, n)]
        model = _fit_binary(
            np.asarray([_sports_vector(r["X"]) for r in tr], dtype=float),
            [r["labels"][market] for r in tr],
        )
        if not model:
            continue
        pred = _predict_binary(model, np.asarray([_sports_vector(r["X"]) for r in te], dtype=float))
        for r, p in zip(te, pred):
            structural, _, _ = _goal_structural_base(r["X"], market)
            base = structural
            if market == "over25" and r["market_probs"].get("over25") is not None:
                base = float(r["market_probs"]["over25"])
                baseline_kind = "mercado"
            ys.append(int(r["labels"][market]))
            p_models.append(float(p))
            p_bases.append(float(base))
            odds.append(r["odds"].get(market))

    if not ys:
        return {
            "samples": n, "validation_samples": 0, "brier": None, "log_loss": None,
            "ece": None, "accuracy": None, "roi": None, "bets": 0,
            "blend_alpha": 0.0, "baseline": baseline_kind,
        }, 0.0

    alpha = _best_blend_alpha(ys, p_models, p_bases, multiclass=False)
    probs = [_clip_probability(alpha * pm + (1.0 - alpha) * pb) for pm, pb in zip(p_models, p_bases)]
    brier = float(brier_score_loss(ys, probs))
    ll = float(log_loss(ys, probs, labels=[0, 1]))
    acc = float(np.mean((np.asarray(probs) >= .5) == np.asarray(ys, dtype=bool)))
    ece = _ece_binary(ys, probs)
    returns = []
    for y, p, odd in zip(ys, probs, odds):
        if odd and p * float(odd) - 1.0 > 0:
            returns.append((float(odd) - 1.0) if y else -1.0)
    return {
        "samples": n,
        "validation_samples": len(probs),
        "brier": round(brier, 4),
        "log_loss": round(ll, 4),
        "ece": round(ece * 100, 2),
        "accuracy": round(acc * 100, 2),
        "roi": round(sum(returns) / len(returns) * 100, 2) if returns else None,
        "bets": len(returns),
        "blend_alpha": round(alpha, 2),
        "market_anchor_pct": round((1.0 - alpha) * 100, 1),
        "baseline": baseline_kind,
    }, alpha


SIMILARITY_FEATURES = {
    "home": ["market_home", "market_draw", "market_away", "elo_diff", "home_perf10", "away_perf10",
             "home_attack", "home_defense", "away_attack", "away_defense", "market_value_gap"],
    "away": ["market_home", "market_draw", "market_away", "elo_diff", "home_perf10", "away_perf10",
             "home_attack", "home_defense", "away_attack", "away_defense", "market_value_gap"],
    "over15": ["poisson_over15", "home_over15_10", "away_over15_10", "home_attack", "home_defense",
               "away_attack", "away_defense", "home_cg1", "away_cg1", "home_cv_cg1", "away_cv_cg1"],
    "over25": ["market_over25", "poisson_over25", "home_over25_10", "away_over25_10", "home_attack",
               "home_defense", "away_attack", "away_defense", "home_cg2", "away_cg2", "home_cv_cg2", "away_cv_cg2"],
    "btts": ["poisson_btts", "home_btts10", "away_btts10", "home_attack", "home_defense", "away_attack",
             "away_defense", "home_cg1", "away_cg1", "home_cv_cg1", "away_cv_cg1"],
}


def _similarity_stats(train_rows, candidate_feature, market, limit=80):
    names = SIMILARITY_FEATURES[market]
    idxs = [FEATURE_INDEX[n] for n in names]
    matrix = np.asarray([[float(r["X"][i]) for i in idxs] for r in train_rows], dtype=float)
    candidate = np.asarray([float(candidate_feature[i]) for i in idxs], dtype=float)
    if len(matrix) == 0:
        return {"n": 0, "rate": None, "lower": None, "distance": None}

    med = np.nanmedian(matrix, axis=0)
    matrix = np.where(np.isfinite(matrix), matrix, med)
    candidate = np.where(np.isfinite(candidate), candidate, med)
    scale = np.nanstd(matrix, axis=0)
    scale = np.where(scale < 1e-6, 1.0, scale)
    dist = np.sqrt(np.mean(((matrix - candidate) / scale) ** 2, axis=1))
    order = np.argsort(dist)[:min(limit, len(train_rows))]

    # Dá mais peso aos realmente próximos sem zerar a amostra.
    weights = np.exp(-np.clip(dist[order], 0, 8))
    labels = np.asarray([train_rows[int(i)]["labels"][market] for i in order], dtype=float)
    wsum = float(weights.sum())
    rate = float((labels * weights).sum() / wsum) if wsum > 0 else float(labels.mean())
    eff_n = float((wsum * wsum) / max(float((weights * weights).sum()), 1e-9))
    lower = _wilson_lower(rate * eff_n, eff_n)
    ci95_lower, ci95_upper = _wilson_interval(rate * eff_n, eff_n)
    return {
        "n": int(len(order)),
        "effective_n": round(eff_n, 1),
        "rate": round(rate, 6),
        "lower": round(lower, 6),
        "ci95_lower": round(ci95_lower, 6),
        "ci95_upper": round(ci95_upper, 6),
        "distance": round(float(np.median(dist[order])), 4),
    }


def _candidate_market_probability(candidate, market):
    if market in ("home", "away"):
        mh, _, ma = _no_vig_1x2(candidate["home_odd"], candidate["draw_odd"], candidate["away_odd"])
        return mh if market == "home" else ma
    if market == "over25":
        p = _no_vig_binary(candidate.get("over25"), candidate.get("under25"))
        if p is not None:
            return p
    if market == "over15":
        p = _no_vig_binary(candidate.get("over15"), candidate.get("under15"))
        if p is not None:
            return p
    if market == "btts":
        p = _no_vig_binary(candidate.get("btts"), candidate.get("btts_no"))
        if p is not None:
            return p
    odd = candidate.get(market if market != "home" and market != "away" else f"{market}_odd")
    if odd and odd > 1:
        return min(0.999, 1.0 / float(odd))
    return None


def _evidence_confidence(health, similarity, conservative_ev, signal_margin):
    ece = float(health.get("ece") or 99.0) / 100.0
    n = float(similarity.get("effective_n") or 0.0)
    validation_n = int(health.get("validation_samples") or 0)
    if conservative_ev <= 0 or signal_margin <= 0:
        return "Baixa"
    if validation_n >= 180 and ece <= .07 and n >= 45 and conservative_ev >= .04 and signal_margin >= .015:
        return "Alta"
    if validation_n >= 100 and ece <= .13 and n >= 25 and conservative_ev > 0:
        return "Média"
    return "Baixa"


def _conservative_probability(final_p, health, similarity, similarity_weight=.28):
    ece = max(.005, float(health.get("ece") or 8.0) / 100.0)
    calibrated_floor = max(0.0, final_p - ece)
    if similarity.get("lower") is None or float(similarity.get("effective_n") or 0) < 20:
        return calibrated_floor
    similarity_floor = float(similarity["lower"])
    w = max(0.0, min(0.45, float(similarity_weight)))
    evidence_floor = (1.0 - w) * final_p + w * similarity_floor
    return max(0.0, min(calibrated_floor, evidence_floor))


def _training_context_until(meta, competition_id, earliest):
    meta_hist = _all_history(meta)
    names, name_map = _registry(competition_id)
    values, geo = _market_values(competition_id)
    elo_exact, _, _, elo_initial = _elo_movements(competition_id)
    team_hist = defaultdict(list)
    h2h = defaultdict(list)
    league = {"games": 0, "home_goals": 0, "away_goals": 0}
    odds_map = {
        (str(r["data"]), int(r["clube_casa_id"]), int(r["clube_fora_id"])): r
        for r in _all_odds(competition_id) if r.get("data")
    }
    rolling_elo = defaultdict(lambda: 1500.0)
    last_season = {}

    for game in meta_hist:
        gd = game.get("data")
        if not gd or gd >= earliest:
            break
        hid = name_map.get(normalize_name(game.get("casa") or ""))
        aid = name_map.get(normalize_name(game.get("fora") or ""))
        if not hid or not aid:
            continue
        season = _season_text(game.get("temporada"))
        gh, ga = int(game["gols_casa"]), int(game["gols_fora"])
        d = str(gd)
        odd = odds_map.get((d, hid, aid))

        pair = elo_exact.get((d, hid, aid))
        if pair:
            rolling_elo[hid], rolling_elo[aid] = float(pair[0]), float(pair[1])
        else:
            # Na primeira partida da temporada, respeita o ELO inicial já calculado.
            if last_season.get(hid) != season:
                rolling_elo[hid] = float(elo_initial.get((season, hid), rolling_elo[hid]))
            if last_season.get(aid) != season:
                rolling_elo[aid] = float(elo_initial.get((season, aid), rolling_elo[aid]))

        mh = 1 / float(odd["odd_casa"]) if odd and odd.get("odd_casa") else None
        ma = 1 / float(odd["odd_fora"]) if odd and odd.get("odd_fora") else None
        team_hist[hid].append({
            "gf": gh, "ga": ga, "points": 3 if gh > ga else 1 if gh == ga else 0, "venue": "home",
            "over15": gh + ga > 1.5, "over25": gh + ga > 2.5, "btts": gh > 0 and ga > 0,
            "cg1": gh / mh if mh else None, "cg2": (gh / 2 + mh / 2) if mh else None,
        })
        team_hist[aid].append({
            "gf": ga, "ga": gh, "points": 3 if ga > gh else 1 if gh == ga else 0, "venue": "away",
            "over15": gh + ga > 1.5, "over25": gh + ga > 2.5, "btts": gh > 0 and ga > 0,
            "cg1": ga / ma if ma else None, "cg2": (ga / 2 + ma / 2) if ma else None,
        })
        league["games"] += 1
        league["home_goals"] += gh
        league["away_goals"] += ga
        h2h[(min(hid, aid), max(hid, aid))].append("H" if gh > ga else "D" if gh == ga else "A")

        expected = 1 / (1 + 10 ** ((rolling_elo[aid] - (rolling_elo[hid] + HOME_ADVANTAGE)) / 400))
        actual = 1 if gh > ga else .5 if gh == ga else 0
        delta = 20 * (actual - expected)
        rolling_elo[hid] += delta
        rolling_elo[aid] -= delta
        last_season[hid] = season
        last_season[aid] = season

    return {
        "names": names, "name_map": name_map, "values": values, "geo": geo,
        "elo_initial": elo_initial, "rolling_elo": rolling_elo, "last_season": last_season,
        "team_hist": team_hist, "h2h": h2h, "league": league,
    }


def analyze(competition_id: int, target_season: str, cutoff_season: str, raw_text: str, ev_min: float = 0.0):
    meta = _competition_meta(competition_id)
    candidates = _parse_table(raw_text, target_season)
    rows, _ = _build_dataset_cached(*_training_cache_key(competition_id, cutoff_season))
    earliest = min(c["date"] for c in candidates)
    train = [r for r in rows if datetime.fromisoformat(r["date"]).date() < earliest]
    if len(train) < 100:
        raise ValueError(
            f"Amostra insuficiente antes de {earliest.strftime('%d/%m/%Y')}: {len(train)} jogos com odds conciliadas. "
            "Use pelo menos 100 jogos para o Scanner de Valor."
        )

    # OOF walk-forward escolhe o peso do modelo contra o mercado/estrutura.
    health_home, health_away, alpha_1x2 = _walk_forward_1x2(train)
    health = {"home": health_home, "away": health_away}
    binary_alphas = {}
    for market in ("over15", "over25", "btts"):
        health[market], binary_alphas[market] = _walk_forward_binary(train, market)

    X = np.asarray([_sports_vector(r["X"]) for r in train], dtype=float)
    model_1x2 = _fit_multiclass(X, [r["outcome"] for r in train])
    binary_models = {
        market: _fit_binary(X, [r["labels"][market] for r in train])
        for market in ("over15", "over25", "btts")
    }
    if not model_1x2:
        raise ValueError("Não foi possível treinar o modelo 1X2 com as três classes.")

    ctx = _training_context_until(meta, competition_id, earliest)
    names, name_map = ctx["names"], ctx["name_map"]
    values, geo = ctx["values"], ctx["geo"]
    team_hist, h2h, league = ctx["team_hist"], ctx["h2h"], ctx["league"]
    rolling_elo, elo_initial, last_season = ctx["rolling_elo"], ctx["elo_initial"], ctx["last_season"]

    draw_rate = sum(1 for r in train if r["outcome"] == 1) / max(len(train), 1)
    away_pattern_rule = _learn_away_pattern_threshold(train, draw_rate)
    results, unmatched = [], []

    for c in candidates:
        hid = name_map.get(normalize_name(c["home"]))
        aid = name_map.get(normalize_name(c["away"]))
        if not hid or not aid:
            unmatched.append({
                "row": c["row"], "home": c["home"], "away": c["away"],
                "missing": [x for x, v in ((c["home"], hid), (c["away"], aid)) if not v],
            })
            continue

        season = c["season"]
        eh = float(rolling_elo[hid])
        ea = float(rolling_elo[aid])
        if last_season.get(hid) != season:
            eh = float(elo_initial.get((season, hid), eh))
        if last_season.get(aid) != season:
            ea = float(elo_initial.get((season, aid), ea))

        odds_input = {
            "home_odd": c["home_odd"], "draw_odd": c["draw_odd"], "away_odd": c["away_odd"],
            "over25": c.get("over25"), "under25": c.get("under25"),
        }
        feat = _feature_vector(
            hid, aid, season, team_hist[hid], team_hist[aid], league,
            h2h[(min(hid, aid), max(hid, aid))], odds_input, values, geo, eh, ea,
        )
        xx = np.asarray([_sports_vector(feat)], dtype=float)
        market_1x2 = np.asarray(_no_vig_1x2(c["home_odd"], c["draw_odd"], c["away_odd"]), dtype=float)
        ml_1x2 = _normalize_probs(_predict_multiclass(model_1x2, xx)[0])
        final_1x2 = _normalize_probs(alpha_1x2 * ml_1x2 + (1.0 - alpha_1x2) * market_1x2)
        elo_probs = elo_probability(eh, ea, draw_rate)
        elo_vec = {"home": elo_probs["home"], "away": elo_probs["away"]}
        elo_gap = (eh + HOME_ADVANTAGE) - ea

        offered = {
            "home": c["home_odd"], "away": c["away_odd"],
            "over15": c.get("over15"), "over25": c.get("over25"), "btts": c.get("btts"),
        }
        suggestions = []

        for market, label in MARKETS.items():
            odd = offered.get(market)
            if not odd or odd <= 1:
                continue

            market_p = _candidate_market_probability(c, market)
            cost_ctx = _cost_goal_context(feat, train, market)
            prob_elo = None
            prob_poisson = None
            prob_recent = None

            if market in ("home", "away"):
                side_idx = 0 if market == "home" else 2
                p_ml = float(ml_1x2[side_idx])
                final_p = float(final_1x2[side_idx])
                prob_elo = float(elo_vec[market])
                alpha = alpha_1x2
            else:
                p_ml = float(_predict_binary(binary_models[market], xx)[0]) if binary_models.get(market) else .5
                structural_base, prob_poisson, prob_recent = _goal_structural_base(feat, market)
                if market == "over25" and _no_vig_binary(c.get("over25"), c.get("under25")) is not None:
                    base = float(_no_vig_binary(c.get("over25"), c.get("under25")))
                else:
                    base = structural_base
                alpha = binary_alphas[market]
                final_p = _clip_probability(alpha * p_ml + (1.0 - alpha) * base)

            similarity = _similarity_stats(train, feat, market)
            similarity_weight = .15 if market == "away" else .28
            conservative_p = _conservative_probability(
                final_p, health[market], similarity, similarity_weight=similarity_weight
            )
            break_even = 1.0 / float(odd)
            edge = (final_p - market_p) if market_p is not None else (final_p - break_even)
            ev = final_p * float(odd) - 1.0
            conservative_ev = conservative_p * float(odd) - 1.0
            reasons = []
            vetoes = []
            strength_ctx = _strength_context(feat)
            away_pattern = None
            away_confluence = None

            if market in ("home", "away"):
                side_gap = elo_gap if market == "home" else -elo_gap
                reasons.append(
                    f"ELO pré-jogo {eh:.0f} × {ea:.0f}; diferença ajustada ao lado escolhido {side_gap:+.0f} pts."
                )
                reasons.append(
                    f"Mercado sem margem {market_p*100:.1f}%; ELO {prob_elo*100:.1f}%; modelo calibrado {final_p*100:.1f}%."
                )
                if market == "away":
                    away_pattern = _away_structural_pattern(feat, train, draw_rate)
                    ev_score = _clamp01(max(0.0, conservative_ev) / 0.08)
                    away_confluence = 0.85 * away_pattern["score"] + 0.15 * ev_score
                    reasons.append(
                        f"Confluência visitante {away_confluence*100:.1f}/100 "
                        f"(ELO {away_pattern['elo_score']*100:.0f}, "
                        f"ataque/defesa {away_pattern['strength']['away_matchup_score']*100:.0f}, "
                        f"custo do gol {away_pattern['cost']['score']*100:.0f})."
                    )
                    reasons.append(
                        f"Ataque/defesa: casa {strength_ctx['home_attack']:.2f}/{strength_ctx['home_defense']:.2f}; "
                        f"visitante {strength_ctx['away_attack']:.2f}/{strength_ctx['away_defense']:.2f}. "
                        "Ataque >1 e defesa <1 são melhores."
                    )
                    if prob_elo <= (market_p or break_even) + .005:
                        vetoes.append("Vitória visitante exige ELO pelo menos 0,5 p.p. acima do mercado.")
                    if final_p <= (market_p or break_even):
                        vetoes.append("A probabilidade calibrada do visitante não supera o mercado.")
                    if away_pattern["cost"]["score"] < .22:
                        vetoes.append("Custo do gol do visitante está fraco/instável demais para uma entrada fora de casa.")
                    if away_confluence < float(away_pattern_rule["threshold"]):
                        vetoes.append(
                            f"Confluência visitante abaixo do padrão aprendido ({away_pattern_rule['threshold']*100:.0f}/100)."
                        )
                    if conservative_ev < .015:
                        vetoes.append("Vitória visitante exige pelo menos +1,5% de EV conservador.")
                else:
                    if prob_elo <= (market_p or break_even):
                        vetoes.append("O ELO não confirma vantagem sobre o preço de mercado.")
                    if p_ml <= (market_p or break_even):
                        vetoes.append("O modelo estatístico não confirma vantagem sobre o mercado.")
                    if final_p <= (market_p or break_even):
                        vetoes.append("A probabilidade calibrada não supera a referência do mercado.")
            else:
                reasons.append(
                    f"Poisson {prob_poisson*100:.1f}%; padrão recente {prob_recent*100:.1f}%; modelo calibrado {final_p*100:.1f}%."
                )
                if cost_ctx.get("avg_cost") is not None:
                    reasons.append(
                        f"Custo do gol {cost_ctx['label']} {cost_ctx['avg_cost']:.2f}; CV médio {(cost_ctx.get('avg_cv') or 0)*100:.1f}%."
                    )
                if cost_ctx["score"] < .40:
                    vetoes.append("Custo do gol/CV não apresenta estabilidade suficiente frente ao histórico da competição.")
                if prob_poisson < break_even:
                    vetoes.append("Poisson não supera a probabilidade mínima exigida pela odd.")

            if similarity.get("rate") is not None:
                reasons.append(
                    f"Jogos semelhantes: {similarity['n']} (n efetivo {similarity['effective_n']:.1f}), "
                    f"ocorrência {similarity['rate']*100:.1f}%, "
                    f"IC95% {similarity['ci95_lower']*100:.1f}%–{similarity['ci95_upper']*100:.1f}%, "
                    f"limite conservador operacional {similarity['lower']*100:.1f}%."
                )
                if float(similarity.get("effective_n") or 0) < 20:
                    vetoes.append("Amostra efetiva de jogos semelhantes ainda é pequena.")
                elif market == "away":
                    if float(similarity["rate"]) <= break_even:
                        vetoes.append("Nos jogos semelhantes, a taxa central de vitória visitante não supera o break-even.")
                elif float(similarity["lower"]) <= break_even:
                    vetoes.append("O limite conservador dos jogos semelhantes não supera o break-even da odd.")
            else:
                vetoes.append("Não há jogos semelhantes suficientes para confirmar a entrada.")

            if conservative_p <= break_even:
                vetoes.append("A probabilidade conservadora não supera o break-even da odd.")

            signal_margin = conservative_p - break_even
            confidence = _evidence_confidence(health[market], similarity, conservative_ev, signal_margin)
            if confidence == "Baixa":
                vetoes.append("A evidência out-of-sample ainda não sustenta confiança suficiente.")

            approved = (
                not vetoes
                and conservative_ev > 0
                and conservative_ev * 100 >= ev_min
                and confidence in ("Média", "Alta")
            )
            status = "Entrada recomendada" if approved else ("Valor aparente, sem confirmação" if ev > 0 else "Sem valor")
            reasons.extend(vetoes)

            suggestions.append({
                "market": market, "label": label, "status": status, "approved": approved,
                "prob_model": round(final_p * 100, 2),
                "prob_ml": round(p_ml * 100, 2),
                "prob_elo": round(prob_elo * 100, 2) if prob_elo is not None else None,
                "prob_poisson": round(prob_poisson * 100, 2) if prob_poisson is not None else None,
                "prob_recent": round(prob_recent * 100, 2) if prob_recent is not None else None,
                "prob_market": round(market_p * 100, 2) if market_p is not None else None,
                "prob_similar": round(float(similarity["rate"]) * 100, 2) if similarity.get("rate") is not None else None,
                "prob_similar_lower": round(float(similarity["lower"]) * 100, 2) if similarity.get("lower") is not None else None,
                "prob_similar_ci95_lower": round(float(similarity["ci95_lower"]) * 100, 2) if similarity.get("ci95_lower") is not None else None,
                "prob_similar_ci95_upper": round(float(similarity["ci95_upper"]) * 100, 2) if similarity.get("ci95_upper") is not None else None,
                "prob_conservative": round(conservative_p * 100, 2),
                "fair_odd": round(1.0 / final_p, 3),
                "conservative_fair_odd": round(1.0 / max(conservative_p, 1e-6), 3),
                "offered_odd": round(float(odd), 3),
                "break_even": round(break_even * 100, 2),
                "edge_pp": round(edge * 100, 2),
                "ev_pct": round(ev * 100, 2),
                "adjusted_ev_pct": round(conservative_ev * 100, 2),
                "confidence": confidence,
                "blend_alpha": round(float(alpha), 2),
                "market_anchor_pct": round((1.0 - float(alpha)) * 100, 1),
                "elo_home": round(eh, 1), "elo_away": round(ea, 1), "elo_gap": round(elo_gap, 1),
                "strength": strength_ctx,
                "away_pattern": away_pattern,
                "away_confluence": round(away_confluence * 100, 1) if away_confluence is not None else None,
                "away_pattern_threshold": round(float(away_pattern_rule["threshold"]) * 100, 1) if market == "away" else None,
                "cost_goal": cost_ctx, "similarity": similarity, "reasons": reasons,
            })

        results.append({
            "date": c["date"].isoformat(), "season": season,
            "home": names.get(hid, c["home"]), "away": names.get(aid, c["away"]),
            "suggestions": sorted(suggestions, key=lambda x: (x["approved"], x["adjusted_ev_pct"], x["ev_pct"]), reverse=True),
        })

    recommendations, apparent = [], []
    for match in results:
        for s in match["suggestions"]:
            item = {**s, "date": match["date"], "season": match["season"], "home": match["home"], "away": match["away"]}
            if s["approved"]:
                recommendations.append(item)
            elif s["ev_pct"] > 0:
                apparent.append(item)
    recommendations.sort(key=lambda x: (x["adjusted_ev_pct"], x["confidence"] == "Alta"), reverse=True)
    apparent.sort(key=lambda x: x["ev_pct"], reverse=True)

    return {
        "competition": meta["competition"], "country": meta["country"], "cutoff_season": cutoff_season,
        "training_games": len(train), "training_until": earliest.fromordinal(earliest.toordinal() - 1).isoformat(),
        "games_received": len(candidates), "games_analyzed": len(results), "unmatched": unmatched,
        "health": health, "matches": results, "recommendations": recommendations,
        "apparent_value": apparent, "discarded_structural": len(apparent),
        "away_pattern_rule": away_pattern_rule,
        "model_note": (
            "1X2 usa regressão multiclasse com variáveis esportivas; as odds não entram como feature do modelo. "
            "O mercado sem margem entra depois como âncora, e o peso do modelo contra o mercado é escolhido por walk-forward. "
            "ELO entra como variável estrutural "
            "e também precisa confirmar a direção da entrada. Mercados de gols combinam modelo, Poisson, padrão recente "
            "e custo do gol/CV. Jogos historicamente semelhantes geram um limite conservador; a recomendação só aparece "
            "quando o EV permanece positivo nesse cenário conservador. Para vitória visitante, existe uma camada extra de "
            "confluência entre ELO, encaixe ataque/defesa, custo do gol e EV conservador; o limiar é calibrado no histórico recente. "
            "O IC95% dos jogos semelhantes é exibido como medida de incerteza, sem ser usado isoladamente como veto."
        ),
    }

