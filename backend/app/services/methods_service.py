import json
import math
import re
import time
from collections import defaultdict
from datetime import date
from functools import lru_cache
from statistics import mean, median, pstdev

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from .elo_service import HOME_ADVANTAGE, normalize_name, season_key

STAKE_DEFAULT = 100.0
CACHE_SECONDS = 300

MARKETS = {
    "home": "Vitória do mandante",
    "draw": "Empate",
    "away": "Vitória do visitante",
    "over25": "Over 2,5",
    "under25": "Under 2,5",
}

CONDITION_CATALOG = [
    {"key": "entry_odd", "label": "Odd da entrada", "kind": "number"},
    {"key": "home_odd", "label": "Odd do mandante", "kind": "number"},
    {"key": "draw_odd", "label": "Odd do empate", "kind": "number"},
    {"key": "away_odd", "label": "Odd do visitante", "kind": "number"},
    {"key": "over25_odd", "label": "Odd Over 2,5", "kind": "number"},
    {"key": "under25_odd", "label": "Odd Under 2,5", "kind": "number"},
    {"key": "home_team_id", "label": "Time mandante", "kind": "team"},
    {"key": "away_team_id", "label": "Time visitante", "kind": "team"},
    {"key": "home_win_streak", "label": "Vitórias seguidas do mandante", "kind": "integer"},
    {"key": "away_win_streak", "label": "Vitórias seguidas do visitante", "kind": "integer"},
    {"key": "home_home_win_streak", "label": "Vitórias seguidas do mandante em casa", "kind": "integer"},
    {"key": "away_away_win_streak", "label": "Vitórias seguidas do visitante fora", "kind": "integer"},
    {"key": "home_unbeaten_streak", "label": "Jogos sem perder do mandante", "kind": "integer"},
    {"key": "away_unbeaten_streak", "label": "Jogos sem perder do visitante", "kind": "integer"},
    {"key": "home_loss_streak", "label": "Derrotas seguidas do mandante", "kind": "integer"},
    {"key": "away_loss_streak", "label": "Derrotas seguidas do visitante", "kind": "integer"},
    {"key": "home_win_pct_5", "label": "% vitórias mandante - últimos 5", "kind": "percent"},
    {"key": "away_win_pct_5", "label": "% vitórias visitante - últimos 5", "kind": "percent"},
    {"key": "home_win_pct_10", "label": "% vitórias mandante - últimos 10", "kind": "percent"},
    {"key": "away_win_pct_10", "label": "% vitórias visitante - últimos 10", "kind": "percent"},
    {"key": "home_ppg_5", "label": "Pontos/jogo mandante - últimos 5", "kind": "number"},
    {"key": "away_ppg_5", "label": "Pontos/jogo visitante - últimos 5", "kind": "number"},
    {"key": "home_ppg_10", "label": "Pontos/jogo mandante - últimos 10", "kind": "number"},
    {"key": "away_ppg_10", "label": "Pontos/jogo visitante - últimos 10", "kind": "number"},
    {"key": "home_avg_gf_5", "label": "Média gols marcados mandante - últimos 5", "kind": "number"},
    {"key": "away_avg_gf_5", "label": "Média gols marcados visitante - últimos 5", "kind": "number"},
    {"key": "home_avg_ga_5", "label": "Média gols sofridos mandante - últimos 5", "kind": "number"},
    {"key": "away_avg_ga_5", "label": "Média gols sofridos visitante - últimos 5", "kind": "number"},
    {"key": "home_avg_gf_10", "label": "Média gols marcados mandante - últimos 10", "kind": "number"},
    {"key": "away_avg_gf_10", "label": "Média gols marcados visitante - últimos 10", "kind": "number"},
    {"key": "home_avg_ga_10", "label": "Média gols sofridos mandante - últimos 10", "kind": "number"},
    {"key": "away_avg_ga_10", "label": "Média gols sofridos visitante - últimos 10", "kind": "number"},
    {"key": "home_over25_pct_10", "label": "% Over 2,5 mandante - últimos 10", "kind": "percent"},
    {"key": "away_over25_pct_10", "label": "% Over 2,5 visitante - últimos 10", "kind": "percent"},
    {"key": "match_avg_goals_10", "label": "Média combinada de gols - últimos 10", "kind": "number"},
    {"key": "elo_home", "label": "ELO mandante", "kind": "number"},
    {"key": "elo_away", "label": "ELO visitante", "kind": "number"},
    {"key": "elo_diff", "label": "Diferença ELO com mando (casa - fora)", "kind": "number"},
    {"key": "home_attack_strength", "label": "Força ofensiva mandante", "kind": "number"},
    {"key": "home_defense_strength", "label": "Força defensiva mandante (menor = melhor)", "kind": "number"},
    {"key": "away_attack_strength", "label": "Força ofensiva visitante", "kind": "number"},
    {"key": "away_defense_strength", "label": "Força defensiva visitante (menor = melhor)", "kind": "number"},
    {"key": "home_cg1", "label": "Custo do gol 1.0 mandante", "kind": "number"},
    {"key": "away_cg1", "label": "Custo do gol 1.0 visitante", "kind": "number"},
    {"key": "home_cv_cg1", "label": "CV custo do gol 1.0 mandante", "kind": "percent"},
    {"key": "away_cv_cg1", "label": "CV custo do gol 1.0 visitante", "kind": "percent"},
    {"key": "home_cg2", "label": "Custo do gol 2.0 mandante", "kind": "number"},
    {"key": "away_cg2", "label": "Custo do gol 2.0 visitante", "kind": "number"},
    {"key": "home_cv_cg2", "label": "CV custo do gol 2.0 mandante", "kind": "percent"},
    {"key": "away_cv_cg2", "label": "CV custo do gol 2.0 visitante", "kind": "percent"},
    {"key": "home_elo_adv", "label": "Vantagem ELO do mandante (com mando)", "kind": "number"},
    {"key": "away_elo_adv", "label": "Vantagem ELO do visitante (com mando)", "kind": "number"},
    {"key": "home_attack_adv", "label": "Vantagem ofensiva do mandante", "kind": "number"},
    {"key": "away_attack_adv", "label": "Vantagem ofensiva do visitante", "kind": "number"},
    {"key": "home_defense_adv", "label": "Vantagem defensiva do mandante", "kind": "number"},
    {"key": "away_defense_adv", "label": "Vantagem defensiva do visitante", "kind": "number"},
    {"key": "home_cg1_adv", "label": "Vantagem custo do gol 1.0 do mandante", "kind": "number"},
    {"key": "away_cg1_adv", "label": "Vantagem custo do gol 1.0 do visitante", "kind": "number"},
    {"key": "home_cg2_adv", "label": "Vantagem custo do gol 2.0 do mandante", "kind": "number"},
    {"key": "away_cg2_adv", "label": "Vantagem custo do gol 2.0 do visitante", "kind": "number"},
    {"key": "avg_cg1", "label": "Custo do gol 1.0 médio do confronto", "kind": "number"},
    {"key": "avg_cg2", "label": "Custo do gol 2.0 médio do confronto", "kind": "number"},
    {"key": "avg_cv_cg1", "label": "CV médio do custo do gol 1.0", "kind": "percent"},
    {"key": "avg_cv_cg2", "label": "CV médio do custo do gol 2.0", "kind": "percent"},
    {"key": "combined_attack_strength", "label": "Força ofensiva combinada", "kind": "number"},
    {"key": "combined_defense_weakness", "label": "Fragilidade defensiva combinada", "kind": "number"},
]
CATALOG_BY_KEY = {x["key"]: x for x in CONDITION_CATALOG}


def _season_text(value):
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


def _same_season(a, b):
    return season_key(_season_text(a)) == season_key(_season_text(b))


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
    name_map = {normalize_name(r["nome"]): int(r["id"]) for r in clubs}
    names = {int(r["id"]): r["nome"] for r in clubs}
    for a in aliases:
        name_map[normalize_name(a["alias"])] = int(a["clube_id"])
    return names, name_map


def _history(competition_id: int):
    meta = _competition_meta(competition_id)
    with history_connection() as conn:
        return [dict(r) for r in conn.execute(text(f"""
            SELECT id, data, temporada, casa, fora, gols_casa, gols_fora
            FROM {settings.history_schema}.{settings.history_table}
            WHERE pais=:country AND campeonato=:competition
              AND data IS NOT NULL AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
            ORDER BY data ASC, id ASC
        """), {"country": meta["country"], "competition": meta["competition"]}).mappings()]


def _odds(competition_id: int):
    with app_engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(f"""
            SELECT data, temporada, clube_casa_id, clube_fora_id,
                   odd_casa::float, odd_empate::float, odd_fora::float,
                   odd_over_25::float, odd_under_25::float
            FROM {settings.app_schema}.odds_jogos
            WHERE campeonato_id=:c AND data IS NOT NULL
            ORDER BY data ASC, id ASC
        """), {"c": competition_id}).mappings()]


def _elo(competition_id: int):
    with app_engine.connect() as conn:
        movements = [dict(r) for r in conn.execute(text(f"""
            SELECT data, casa_clube_id, fora_clube_id,
                   elo_casa_antes::float, elo_fora_antes::float
            FROM {settings.app_schema}.elo_movimentos
            WHERE campeonato_id=:c AND data IS NOT NULL
        """), {"c": competition_id}).mappings()]
        initials = [dict(r) for r in conn.execute(text(f"""
            SELECT temporada, clube_id, elo_inicial::float
            FROM {settings.app_schema}.elo_clubes WHERE campeonato_id=:c
        """), {"c": competition_id}).mappings()]
    exact = {(str(r["data"]), int(r["casa_clube_id"]), int(r["fora_clube_id"])): (float(r["elo_casa_antes"]), float(r["elo_fora_antes"])) for r in movements}
    initial = {(_season_text(r["temporada"]), int(r["clube_id"])): float(r["elo_inicial"]) for r in initials}
    return exact, initial


def _avg(rows, key, n=None, default=0.0):
    data = rows[-n:] if n else rows
    vals = [float(r[key]) for r in data if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else default


def _rate(rows, key, n=None, default=0.0):
    data = rows[-n:] if n else rows
    return sum(1 for r in data if r.get(key)) / len(data) if data else default


def _cv(rows, key, n=10):
    data = rows[-n:] if n else rows
    vals = [float(r[key]) for r in data if r.get(key) not in (None, 0)]
    if len(vals) < 2:
        return None
    m = mean(vals)
    return pstdev(vals) / m * 100 if m else None


def _streak(rows, mode, venue=None):
    count = 0
    for r in reversed(rows):
        if venue and r.get("venue") != venue:
            continue
        result = r.get("result")
        ok = result == mode if mode in ("W", "L") else result in ("W", "D")
        if not ok:
            break
        count += 1
    return count


def _venue_strength(rows, venue, league_for, league_against):
    venue_rows = [r for r in rows if r.get("venue") == venue][-10:]
    if not venue_rows:
        venue_rows = rows[-10:]
    gf = _avg(venue_rows, "gf", default=league_for)
    ga = _avg(venue_rows, "ga", default=league_against)
    return gf / max(league_for, .01), ga / max(league_against, .01)


def _record_features(team_hist, home_id, away_id, league, eh, ea):
    h = team_hist[home_id]
    a = team_hist[away_id]
    league_games = max(1, league["games"])
    league_home = league["home_goals"] / league_games if league["games"] else 1.45
    league_away = league["away_goals"] / league_games if league["games"] else 1.15
    h_att, h_def = _venue_strength(h, "home", league_home, league_away)
    a_att, a_def = _venue_strength(a, "away", league_away, league_home)
    h_tot10 = [_finite(r.get("gf"), 0) + _finite(r.get("ga"), 0) for r in h[-10:]]
    a_tot10 = [_finite(r.get("gf"), 0) + _finite(r.get("ga"), 0) for r in a[-10:]]
    combined = [*h_tot10, *a_tot10]

    home_cg1 = _avg(h, "cg1", 10, None)
    away_cg1 = _avg(a, "cg1", 10, None)
    home_cg2 = _avg(h, "cg2", 10, None)
    away_cg2 = _avg(a, "cg2", 10, None)
    home_cv_cg1 = _cv(h, "cg1", 10)
    away_cv_cg1 = _cv(a, "cg1", 10)
    home_cv_cg2 = _cv(h, "cg2", 10)
    away_cv_cg2 = _cv(a, "cg2", 10)

    def pair_avg(x, y):
        vals = [float(v) for v in (x, y) if v is not None and math.isfinite(float(v))]
        return sum(vals) / len(vals) if vals else None

    elo_diff = eh + HOME_ADVANTAGE - ea
    home_attack_adv = h_att - a_att
    home_defense_adv = a_def - h_def  # defesa menor é melhor
    home_cg1_adv = (away_cg1 - home_cg1) if home_cg1 is not None and away_cg1 is not None else None
    home_cg2_adv = (away_cg2 - home_cg2) if home_cg2 is not None and away_cg2 is not None else None

    return {
        "home_win_streak": _streak(h, "W"),
        "away_win_streak": _streak(a, "W"),
        "home_home_win_streak": _streak(h, "W", "home"),
        "away_away_win_streak": _streak(a, "W", "away"),
        "home_unbeaten_streak": _streak(h, "U"),
        "away_unbeaten_streak": _streak(a, "U"),
        "home_loss_streak": _streak(h, "L"),
        "away_loss_streak": _streak(a, "L"),
        "home_win_pct_5": _rate(h, "win", 5) * 100,
        "away_win_pct_5": _rate(a, "win", 5) * 100,
        "home_win_pct_10": _rate(h, "win", 10) * 100,
        "away_win_pct_10": _rate(a, "win", 10) * 100,
        "home_ppg_5": _avg(h, "points", 5),
        "away_ppg_5": _avg(a, "points", 5),
        "home_ppg_10": _avg(h, "points", 10),
        "away_ppg_10": _avg(a, "points", 10),
        "home_avg_gf_5": _avg(h, "gf", 5),
        "away_avg_gf_5": _avg(a, "gf", 5),
        "home_avg_ga_5": _avg(h, "ga", 5),
        "away_avg_ga_5": _avg(a, "ga", 5),
        "home_avg_gf_10": _avg(h, "gf", 10),
        "away_avg_gf_10": _avg(a, "gf", 10),
        "home_avg_ga_10": _avg(h, "ga", 10),
        "away_avg_ga_10": _avg(a, "ga", 10),
        "home_over25_pct_10": _rate(h, "over25", 10) * 100,
        "away_over25_pct_10": _rate(a, "over25", 10) * 100,
        "match_avg_goals_10": sum(combined) / len(combined) if combined else 0.0,
        "elo_home": eh,
        "elo_away": ea,
        "elo_diff": elo_diff,
        "home_elo_adv": elo_diff,
        "away_elo_adv": -elo_diff,
        "home_attack_strength": h_att,
        "home_defense_strength": h_def,
        "away_attack_strength": a_att,
        "away_defense_strength": a_def,
        "home_attack_adv": home_attack_adv,
        "away_attack_adv": -home_attack_adv,
        "home_defense_adv": home_defense_adv,
        "away_defense_adv": -home_defense_adv,
        "home_cg1": home_cg1,
        "away_cg1": away_cg1,
        "home_cv_cg1": home_cv_cg1,
        "away_cv_cg1": away_cv_cg1,
        "home_cg2": home_cg2,
        "away_cg2": away_cg2,
        "home_cv_cg2": home_cv_cg2,
        "away_cv_cg2": away_cv_cg2,
        "home_cg1_adv": home_cg1_adv,
        "away_cg1_adv": -home_cg1_adv if home_cg1_adv is not None else None,
        "home_cg2_adv": home_cg2_adv,
        "away_cg2_adv": -home_cg2_adv if home_cg2_adv is not None else None,
        "avg_cg1": pair_avg(home_cg1, away_cg1),
        "avg_cg2": pair_avg(home_cg2, away_cg2),
        "avg_cv_cg1": pair_avg(home_cv_cg1, away_cv_cg1),
        "avg_cv_cg2": pair_avg(home_cv_cg2, away_cv_cg2),
        "combined_attack_strength": h_att + a_att,
        "combined_defense_weakness": h_def + a_def,
    }


def _finite(value, default=None):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _cache_bucket():
    return int(time.time() // CACHE_SECONDS)


@lru_cache(maxsize=32)
def _records_cached(competition_id: int, bucket: int):
    names, name_map = _registry(competition_id)
    hist = _history(competition_id)
    odds = _odds(competition_id)
    elo_exact, elo_initial = _elo(competition_id)
    odds_map = {(str(r["data"]), int(r["clube_casa_id"]), int(r["clube_fora_id"])): r for r in odds if r.get("data")}

    team_hist = defaultdict(list)
    league = {"games": 0, "home_goals": 0, "away_goals": 0}
    rolling_elo = defaultdict(lambda: 1500.0)
    last_season = {}
    records = []

    for g in hist:
        hid = name_map.get(normalize_name(g.get("casa") or ""))
        aid = name_map.get(normalize_name(g.get("fora") or ""))
        if not hid or not aid or not g.get("data"):
            continue
        season = _season_text(g.get("temporada"))
        d = str(g["data"])
        key = (d, hid, aid)
        odd = odds_map.get(key)

        if last_season.get(hid) != season:
            rolling_elo[hid] = elo_initial.get((season, hid), rolling_elo[hid])
        if last_season.get(aid) != season:
            rolling_elo[aid] = elo_initial.get((season, aid), rolling_elo[aid])
        pair = elo_exact.get(key)
        eh, ea = pair if pair else (rolling_elo[hid], rolling_elo[aid])
        pre = _record_features(team_hist, hid, aid, league, float(eh), float(ea))

        gh, ga = int(g["gols_casa"]), int(g["gols_fora"])
        if odd:
            record = {
                "date": g["data"], "season": season,
                "home_id": hid, "away_id": aid,
                "home": names.get(hid, g["casa"]), "away": names.get(aid, g["fora"]),
                "gh": gh, "ga": ga,
                "home_odd": _finite(odd.get("odd_casa")),
                "draw_odd": _finite(odd.get("odd_empate")),
                "away_odd": _finite(odd.get("odd_fora")),
                "over25_odd": _finite(odd.get("odd_over_25")),
                "under25_odd": _finite(odd.get("odd_under_25")),
                **pre,
            }
            record["home_win"] = gh > ga
            record["draw"] = gh == ga
            record["away_win"] = ga > gh
            record["over25"] = gh + ga >= 3
            record["under25"] = gh + ga <= 2
            records.append(record)

        h_odd = _finite(odd.get("odd_casa")) if odd else None
        a_odd = _finite(odd.get("odd_fora")) if odd else None
        h_p = 1 / h_odd if h_odd and h_odd > 1 else None
        a_p = 1 / a_odd if a_odd and a_odd > 1 else None
        team_hist[hid].append({
            "gf": gh, "ga": ga, "points": 3 if gh > ga else 1 if gh == ga else 0,
            "venue": "home", "result": "W" if gh > ga else "D" if gh == ga else "L",
            "win": gh > ga, "over25": gh + ga >= 3,
            "cg1": gh / h_p if h_p else None,
            "cg2": (gh / 2 + h_p / 2) if h_p else None,
        })
        team_hist[aid].append({
            "gf": ga, "ga": gh, "points": 3 if ga > gh else 1 if gh == ga else 0,
            "venue": "away", "result": "W" if ga > gh else "D" if gh == ga else "L",
            "win": ga > gh, "over25": gh + ga >= 3,
            "cg1": ga / a_p if a_p else None,
            "cg2": (ga / 2 + a_p / 2) if a_p else None,
        })
        league["games"] += 1
        league["home_goals"] += gh
        league["away_goals"] += ga
        expected = 1 / (1 + 10 ** ((rolling_elo[aid] - (rolling_elo[hid] + HOME_ADVANTAGE)) / 400))
        actual = 1 if gh > ga else .5 if gh == ga else 0
        delta = 20 * (actual - expected)
        rolling_elo[hid] += delta
        rolling_elo[aid] -= delta
        last_season[hid] = season
        last_season[aid] = season

    return tuple(records)


def records(competition_id: int):
    return [dict(r) for r in _records_cached(competition_id, _cache_bucket())]


def _bet_result(record, market, stake=STAKE_DEFAULT):
    if market == "home":
        odd, green = record.get("home_odd"), record.get("home_win")
    elif market == "draw":
        odd, green = record.get("draw_odd"), record.get("draw")
    elif market == "away":
        odd, green = record.get("away_odd"), record.get("away_win")
    elif market == "over25":
        odd, green = record.get("over25_odd"), record.get("over25")
    elif market == "under25":
        odd, green = record.get("under25_odd"), record.get("under25")
    else:
        return None, None, None
    if not odd or odd <= 1:
        return None, None, None
    profit = stake * (odd - 1) if green else -stake
    return float(odd), bool(green), float(profit)


def _interval_summary(items, bucket_key, bet_market, top_n=5):
    valid = [(r, _finite(r.get(bucket_key))) for r in items]
    valid = [(r, v) for r, v in valid if v is not None and v > 1]
    n = len(valid)
    if n < 8:
        return []
    vals = sorted(v for _, v in valid)
    bins = min(18, max(7, int(math.sqrt(n)) + 2))
    qs = [i / bins for i in range(bins + 1)]
    edges = []
    for q in qs:
        pos = q * (n - 1)
        lo, hi = int(math.floor(pos)), int(math.ceil(pos))
        val = vals[lo] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)
        edges.append(round(val, 2))
    edges = sorted(set(edges))
    min_games = max(8, math.ceil(n * .03))
    candidates = []
    for i in range(len(edges) - 1):
        for j in range(i + 1, min(len(edges), i + 7)):
            low, high = edges[i], edges[j]
            subset = [(r, v) for r, v in valid if low <= v <= high]
            if len(subset) < min_games:
                continue
            profits, greens, entry_odds, ids = [], 0, [], set()
            for idx, (r, _) in enumerate(subset):
                odd, green, profit = _bet_result(r, bet_market)
                if odd is None:
                    continue
                profits.append(profit); entry_odds.append(odd); greens += int(green)
                ids.add((r["date"], r["home_id"], r["away_id"]))
            entries = len(profits)
            if entries < min_games:
                continue
            lp = sum(profits)
            if lp <= 0:
                continue
            candidates.append({
                "min": low, "max": high, "entries": entries, "greens": greens,
                "reds": entries - greens, "win_rate": greens / entries * 100,
                "profit": lp, "roi": lp / (entries * STAKE_DEFAULT) * 100,
                "avg_entry_odd": sum(entry_odds) / entries,
                "ids": ids,
            })
    candidates.sort(key=lambda x: (x["profit"], x["roi"], x["entries"]), reverse=True)
    chosen = []
    for cand in candidates:
        too_similar = False
        for prev in chosen:
            inter = len(cand["ids"] & prev["ids"])
            union = len(cand["ids"] | prev["ids"])
            if union and inter / union >= .65:
                too_similar = True
                break
        if not too_similar:
            chosen.append(cand)
        if len(chosen) >= top_n:
            break
    for c in chosen:
        c.pop("ids", None)
        c["label"] = f"{c['min']:.2f}–{c['max']:.2f}".replace(".", ",")
        for k in ("profit", "roi", "win_rate", "avg_entry_odd"):
            c[k] = round(c[k], 2)
    return chosen


def _manual_interval_summary(items, bucket_key, bet_market, low, high):
    """Avalia exatamente a faixa informada pelo usuário, sem otimização automática."""
    if low is None and high is None:
        return None
    if low is None or high is None:
        raise ValueError("Informe o valor mínimo e máximo da faixa manual.")

    low = float(low)
    high = float(high)
    if low <= 1 or high <= 1:
        raise ValueError("As odds da faixa manual precisam ser maiores que 1,00.")
    if low > high:
        raise ValueError("Na faixa manual, a odd mínima não pode ser maior que a máxima.")

    profits = []
    greens = 0
    entry_odds = []
    for r in items:
        bucket_value = _finite(r.get(bucket_key))
        if bucket_value is None or not (low <= bucket_value <= high):
            continue
        odd, green, profit = _bet_result(r, bet_market)
        if odd is None:
            continue
        profits.append(profit)
        entry_odds.append(odd)
        greens += int(green)

    entries = len(profits)
    lp = sum(profits) if profits else 0.0
    return {
        "min": round(low, 2),
        "max": round(high, 2),
        "label": f"{low:.2f}–{high:.2f}".replace(".", ","),
        "entries": entries,
        "greens": greens,
        "reds": entries - greens,
        "win_rate": round(greens / entries * 100, 2) if entries else 0.0,
        "profit": round(lp, 2),
        "roi": round(lp / (entries * STAKE_DEFAULT) * 100, 2) if entries else 0.0,
        "avg_entry_odd": round(sum(entry_odds) / entries, 2) if entries else None,
        "source": "human",
    }


def _append_manual_band(auto_rows, manual_row):
    rows = list(auto_rows or [])[:5]
    if manual_row is not None:
        rows.append(manual_row)
    return rows


def _numeric_interval_summary(items, bucket_key, bet_market, top_n=5, min_value=None, max_value=None, decimals=1):
    """Descobre faixas lucrativas para qualquer indicador numérico, inclusive ELO/diferenças."""
    valid = []
    for r in items:
        value = _finite(r.get(bucket_key))
        if value is None:
            continue
        if min_value is not None and value < min_value:
            continue
        if max_value is not None and value > max_value:
            continue
        valid.append((r, value))
    n = len(valid)
    if n < 20:
        return []

    vals = sorted(v for _, v in valid)
    bins = min(14, max(6, int(math.sqrt(n) / 2) + 4))
    edges = sorted(set(round(_quantile(vals, i / bins), 4) for i in range(bins + 1)))
    min_games = max(12, math.ceil(n * .025))
    candidates = []
    for i in range(len(edges) - 1):
        for j in range(i + 1, min(len(edges), i + 6)):
            low, high = edges[i], edges[j]
            subset = [(r, v) for r, v in valid if low <= v <= high]
            if len(subset) < min_games:
                continue
            profits, greens, odds, ids = [], 0, [], set()
            for r, _ in subset:
                odd, green, profit = _bet_result(r, bet_market)
                if odd is None:
                    continue
                profits.append(profit)
                odds.append(float(odd))
                greens += int(green)
                ids.add((r["date"], r["home_id"], r["away_id"]))
            entries = len(profits)
            if entries < min_games:
                continue
            lp = sum(profits)
            if lp <= 0:
                continue
            candidates.append({
                "min": low,
                "max": high,
                "entries": entries,
                "greens": greens,
                "reds": entries - greens,
                "win_rate": greens / entries * 100,
                "profit": lp,
                "roi": lp / (entries * STAKE_DEFAULT) * 100,
                "avg_entry_odd": sum(odds) / entries,
                "ids": ids,
            })

    candidates.sort(key=lambda x: (x["roi"] * math.sqrt(x["entries"]), x["profit"]), reverse=True)
    chosen = []
    for cand in candidates:
        if any(len(cand["ids"] & prev["ids"]) / max(1, len(cand["ids"] | prev["ids"])) >= .70 for prev in chosen):
            continue
        chosen.append(cand)
        if len(chosen) >= top_n:
            break

    for c in chosen:
        stability = _season_stability(items, bet_market, [{"field": bucket_key, "operator": "between", "value": c["min"], "value2": c["max"]}])
        c.pop("ids", None)
        low = f"{c['min']:.{decimals}f}".replace(".", ",")
        high = f"{c['max']:.{decimals}f}".replace(".", ",")
        c["label"] = f"{low}–{high}"
        c["positive_seasons"] = stability["positive_seasons"]
        c["tested_seasons"] = stability["tested_seasons"]
        c["positive_season_pct"] = round(stability["positive_season_pct"], 2)
        c["median_season_roi"] = round(stability["median_season_roi"], 2)
        for k in ("profit", "roi", "win_rate", "avg_entry_odd"):
            c[k] = round(c[k], 2)
    return chosen


def _over_cost_combo_summary(items, top_n=5):
    """Procura combinações 2D de CG1 + CG2 com L/P positivo no Over 2,5."""
    valid = [r for r in items if _finite(r.get("avg_cg1")) is not None and _finite(r.get("avg_cg2")) is not None and _finite(r.get("over25_odd"))]
    if len(valid) < 40:
        return []
    cg1 = [r["avg_cg1"] for r in valid]
    cg2 = [r["avg_cg2"] for r in valid]
    q = [0, .20, .40, .60, .80, 1]
    e1 = sorted(set(round(_quantile(cg1, x), 3) for x in q))
    e2 = sorted(set(round(_quantile(cg2, x), 3) for x in q))
    min_games = max(15, math.ceil(len(valid) * .025))
    candidates = []
    for i in range(len(e1) - 1):
        for j in range(i + 1, min(len(e1), i + 3)):
            for a in range(len(e2) - 1):
                for b in range(a + 1, min(len(e2), a + 3)):
                    c1lo, c1hi = e1[i], e1[j]
                    c2lo, c2hi = e2[a], e2[b]
                    subset = [r for r in valid if c1lo <= r["avg_cg1"] <= c1hi and c2lo <= r["avg_cg2"] <= c2hi]
                    if len(subset) < min_games:
                        continue
                    profits, greens, odds, ids = [], 0, [], set()
                    for r in subset:
                        odd, green, lp = _bet_result(r, "over25")
                        if odd is None:
                            continue
                        profits.append(lp); greens += int(green); odds.append(odd)
                        ids.add((r["date"], r["home_id"], r["away_id"]))
                    if len(profits) < min_games or sum(profits) <= 0:
                        continue
                    entries = len(profits)
                    candidates.append({
                        "cg1_min": c1lo, "cg1_max": c1hi,
                        "cg2_min": c2lo, "cg2_max": c2hi,
                        "entries": entries, "greens": greens, "reds": entries-greens,
                        "win_rate": greens/entries*100,
                        "avg_entry_odd": sum(odds)/entries,
                        "profit": sum(profits),
                        "roi": sum(profits)/(entries*STAKE_DEFAULT)*100,
                        "ids": ids,
                    })
    candidates.sort(key=lambda x: (x["roi"] * math.sqrt(x["entries"]), x["profit"]), reverse=True)
    chosen = []
    for cand in candidates:
        if any(len(cand["ids"] & prev["ids"]) / max(1, len(cand["ids"] | prev["ids"])) >= .70 for prev in chosen):
            continue
        chosen.append(cand)
        if len(chosen) >= top_n:
            break
    for c in chosen:
        conditions = [
            {"field": "avg_cg1", "operator": "between", "value": c["cg1_min"], "value2": c["cg1_max"]},
            {"field": "avg_cg2", "operator": "between", "value": c["cg2_min"], "value2": c["cg2_max"]},
        ]
        stability = _season_stability(items, "over25", conditions)
        c.pop("ids", None)
        c["cg1_label"] = f"{c['cg1_min']:.2f}–{c['cg1_max']:.2f}".replace(".", ",")
        c["cg2_label"] = f"{c['cg2_min']:.2f}–{c['cg2_max']:.2f}".replace(".", ",")
        c["positive_seasons"] = stability["positive_seasons"]
        c["tested_seasons"] = stability["tested_seasons"]
        c["positive_season_pct"] = round(stability["positive_season_pct"], 2)
        c["median_season_roi"] = round(stability["median_season_roi"], 2)
        for k in ("profit", "roi", "win_rate", "avg_entry_odd"):
            c[k] = round(c[k], 2)
    return chosen


def _group_profit(items, group_key, market, min_games=8, limit=5):
    groups = defaultdict(list)
    for r in items:
        groups[r[group_key]].append(r)
    out = []
    for gid, rows in groups.items():
        profits, greens, odds = [], 0, []
        for r in rows:
            odd, green, profit = _bet_result(r, market)
            if odd is None:
                continue
            profits.append(profit); odds.append(odd); greens += int(green)
        if len(profits) < min_games:
            continue
        lp = sum(profits)
        if lp <= 0:
            continue
        out.append({
            "club_id": gid,
            "club": rows[0]["home"] if group_key == "home_id" else rows[0]["away"],
            "entries": len(profits), "greens": greens, "win_rate": greens / len(profits) * 100,
            "avg_odd": sum(odds) / len(odds), "profit": lp, "roi": lp / (len(profits) * STAKE_DEFAULT) * 100,
        })
    out.sort(key=lambda x: (x["profit"], x["roi"]), reverse=True)
    for x in out[:limit]:
        for k in ("win_rate", "avg_odd", "profit", "roi"):
            x[k] = round(x[k], 2)
    return out[:limit]


def _club_over_profit(items, min_games=10, limit=5):
    groups = defaultdict(dict)
    for r in items:
        key = (r["date"], r["home_id"], r["away_id"])
        groups[r["home_id"]][key] = r
        groups[r["away_id"]][key] = r
    out = []
    for cid, mp in groups.items():
        rows = list(mp.values())
        profits, greens, odds, totals = [], 0, [], []
        for r in rows:
            odd, green, profit = _bet_result(r, "over25")
            if odd is None:
                continue
            profits.append(profit); odds.append(odd); greens += int(green); totals.append(r["gh"] + r["ga"])
        if len(profits) < min_games:
            continue
        lp = sum(profits)
        if lp <= 0:
            continue
        name = rows[0]["home"] if rows[0]["home_id"] == cid else rows[0]["away"]
        out.append({"club_id": cid, "club": name, "entries": len(profits), "greens": greens,
                    "over25_pct": greens / len(profits) * 100, "avg_goals": sum(totals) / len(totals),
                    "avg_odd": sum(odds) / len(odds), "profit": lp, "roi": lp / (len(profits) * STAKE_DEFAULT) * 100})
    out.sort(key=lambda x: (x["profit"], x["roi"]), reverse=True)
    for x in out[:limit]:
        for k in ("over25_pct", "avg_goals", "avg_odd", "profit", "roi"):
            x[k] = round(x[k], 2)
    return out[:limit]


def _streak_insight(items, wins_required=3, next_venue="home"):
    wins_required = max(1, min(int(wins_required or 3), 20))
    next_venue = next_venue if next_venue in {"home", "away", "any"} else "home"

    bets = []
    for r in items:
        home_ok = r.get("home_win_streak", 0) >= wins_required
        away_ok = r.get("away_win_streak", 0) >= wins_required

        if next_venue == "home":
            if home_ok:
                bets.append((r, "home"))
        elif next_venue == "away":
            if away_ok:
                bets.append((r, "away"))
        else:
            # Se os dois clubes chegam com a mesma sequência, não há uma direção
            # única para a regra; o jogo é descartado para evitar apostas opostas.
            if home_ok and not away_ok:
                bets.append((r, "home"))
            elif away_ok and not home_ok:
                bets.append((r, "away"))

    profits, greens, odds = [], 0, []
    for r, market in bets:
        odd, green, profit = _bet_result(r, market)
        if odd is None:
            continue
        profits.append(profit)
        odds.append(float(odd))
        greens += int(green)

    venue_label = {"home": "casa", "away": "fora", "any": "indiferente"}[next_venue]
    result = {
        "wins_required": wins_required,
        "next_venue": next_venue,
        "next_venue_label": venue_label,
        "entries": len(profits),
        "greens": greens,
        "reds": len(profits) - greens,
        "win_rate": 0,
        "avg_odd": None,
        "profit": 0,
        "roi": 0,
    }
    if not profits:
        return result

    total_profit = sum(profits)
    result.update({
        "win_rate": round(greens / len(profits) * 100, 2),
        "avg_odd": round(sum(odds) / len(odds), 2),
        "profit": round(total_profit, 2),
        "roi": round(total_profit / (len(profits) * STAKE_DEFAULT) * 100, 2),
    })
    return result


def insights(
    competition_id: int,
    target_season: str,
    wins_required: int = 3,
    next_venue: str = "home",
    manual_mo_min: float | None = None,
    manual_mo_max: float | None = None,
    manual_over25_min: float | None = None,
    manual_over25_max: float | None = None,
):
    all_rows = records(competition_id)
    target_key = season_key(_season_text(target_season))
    base = [r for r in all_rows if season_key(r["season"]) < target_key]
    target = [r for r in all_rows if _same_season(r["season"], target_season)]
    if not base:
        return {"historical_games": 0, "target_games": len(target), "target_season": target_season,
                "note": "Não há temporadas anteriores com odds conciliadas para formar a base histórica.",
                "bands": {}, "signals": {}}
    return {
        "historical_games": len(base), "target_games": len(target), "target_season": target_season,
        "historical_until": max((r["season"] for r in base), key=season_key),
        "note": "A descoberta usa somente temporadas anteriores à temporada alvo. Além das odds, procura padrões estruturais de ELO, custo do gol e combinações de custo do gol para Over 2,5.",
        "bands": {
            "home_wins": _append_manual_band(
                _interval_summary(base, "home_odd", "home"),
                _manual_interval_summary(base, "home_odd", "home", manual_mo_min, manual_mo_max),
            ),
            "away_wins": _append_manual_band(
                _interval_summary(base, "away_odd", "away"),
                _manual_interval_summary(base, "away_odd", "away", manual_mo_min, manual_mo_max),
            ),
            "away_losses": _append_manual_band(
                _interval_summary(base, "away_odd", "home"),
                _manual_interval_summary(base, "away_odd", "home", manual_mo_min, manual_mo_max),
            ),
            "home_losses": _append_manual_band(
                _interval_summary(base, "home_odd", "away"),
                _manual_interval_summary(base, "home_odd", "away", manual_mo_min, manual_mo_max),
            ),
            "over25": _append_manual_band(
                _interval_summary(base, "over25_odd", "over25"),
                _manual_interval_summary(base, "over25_odd", "over25", manual_over25_min, manual_over25_max),
            ),
            "elo_home": _numeric_interval_summary(base, "home_elo_adv", "home", min_value=0, decimals=0),
            "elo_away": _numeric_interval_summary(base, "away_elo_adv", "away", min_value=0, decimals=0),
            "cg1_home": _numeric_interval_summary(base, "home_cg1_adv", "home", min_value=0, decimals=2),
            "cg1_away": _numeric_interval_summary(base, "away_cg1_adv", "away", min_value=0, decimals=2),
            "cg2_home": _numeric_interval_summary(base, "home_cg2_adv", "home", min_value=0, decimals=2),
            "cg2_away": _numeric_interval_summary(base, "away_cg2_adv", "away", min_value=0, decimals=2),
            "over25_cost_combo": _over_cost_combo_summary(base),
        },
        "signals": {
            "profitable_home_clubs": _group_profit(base, "home_id", "home"),
            "profitable_away_clubs": _group_profit(base, "away_id", "away"),
            "profitable_over25_clubs": _club_over_profit(base),
            "win_streak_next": _streak_insight(base, wins_required, next_venue),
        },
    }




def _quantile(values, q):
    vals = sorted(float(v) for v in values if _finite(v) is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = max(0.0, min(1.0, float(q))) * (len(vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return vals[lo] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _evaluate_method(items, market, conditions):
    entries = 0
    greens = 0
    profit = 0.0
    odds = []
    matched_ids = set()
    for r in items:
        if not all(_match_condition(r, c, market) for c in conditions):
            continue
        odd, green, lp = _bet_result(r, market, STAKE_DEFAULT)
        if odd is None:
            continue
        entries += 1
        greens += int(green)
        profit += float(lp)
        odds.append(float(odd))
        matched_ids.add((r["date"], r["home_id"], r["away_id"]))
    return {
        "entries": entries,
        "greens": greens,
        "reds": entries - greens,
        "win_rate": greens / entries * 100 if entries else 0.0,
        "profit": profit,
        "roi": profit / (entries * STAKE_DEFAULT) * 100 if entries else 0.0,
        "avg_odd": sum(odds) / entries if entries else None,
        "ids": matched_ids,
    }


def _season_stability(items, market, conditions, min_entries_per_season=5):
    by_season = defaultdict(list)
    for r in items:
        by_season[r["season"]].append(r)
    rows = []
    for season in sorted(by_season, key=season_key):
        stats = _evaluate_method(by_season[season], market, conditions)
        if stats["entries"] < min_entries_per_season:
            continue
        rows.append({
            "season": season,
            "entries": stats["entries"],
            "profit": stats["profit"],
            "roi": stats["roi"],
            "positive": stats["profit"] > 0,
        })
    positive = sum(1 for r in rows if r["positive"])
    rois = [r["roi"] for r in rows]
    return {
        "seasons": rows,
        "tested_seasons": len(rows),
        "positive_seasons": positive,
        "positive_season_pct": positive / len(rows) * 100 if rows else 0.0,
        "median_season_roi": median(rois) if rois else 0.0,
        "worst_season_roi": min(rois) if rois else 0.0,
        "best_season_roi": max(rois) if rois else 0.0,
    }


def _development_validation_split(base):
    seasons = sorted({r["season"] for r in base}, key=season_key)
    if len(seasons) >= 4:
        validation_count = max(2, math.ceil(len(seasons) * .30))
        validation_count = min(validation_count, len(seasons) - 2)
        validation_seasons = set(seasons[-validation_count:])
        development = [r for r in base if r["season"] not in validation_seasons]
        validation = [r for r in base if r["season"] in validation_seasons]
    elif len(seasons) >= 2:
        validation_seasons = {seasons[-1]}
        development = [r for r in base if r["season"] not in validation_seasons]
        validation = [r for r in base if r["season"] in validation_seasons]
    else:
        cut = max(1, int(len(base) * .70))
        development, validation = base[:cut], base[cut:]
        validation_seasons = {r["season"] for r in validation}
    return development, validation, sorted(validation_seasons, key=season_key)


def _robust_candidate_score(total, validation, stability):
    # ROI e consistência pesam mais que lucro nominal para evitar escolher apenas amostras enormes.
    return (
        validation["roi"] * 3.0
        + total["roi"] * 1.5
        + stability["positive_season_pct"] * .18
        + stability["median_season_roi"] * 1.2
        - max(0.0, -stability["worst_season_roi"]) * .20
        + min(math.sqrt(total["entries"]), 40) * .15
    )


def _candidate_key(market, conditions):
    normalized = []
    for c in conditions:
        normalized.append((
            c["field"],
            c["operator"],
            round(float(c["value"]), 4) if isinstance(c.get("value"), (int, float)) else c.get("value"),
            round(float(c["value2"]), 4) if isinstance(c.get("value2"), (int, float)) else c.get("value2"),
            c.get("compare_field"),
        ))
    return market, tuple(sorted(normalized))


def _candidate_overlap(a, b):
    ids_a, ids_b = a["stats"]["ids"], b["stats"]["ids"]
    if not ids_a or not ids_b:
        return 0.0
    inter = len(ids_a & ids_b)
    union = len(ids_a | ids_b)
    return inter / union if union else 0.0


def _profitable_method_candidates(base):
    development, validation, validation_seasons = _development_validation_split(base)
    candidates = []

    def qvalue(rows, field, q, floor=None):
        value = _quantile([r.get(field) for r in rows], q)
        if value is None:
            return None
        if floor is not None:
            value = max(float(floor), float(value))
        return round(float(value), 3)

    def add(title, market, conditions, source):
        clean = _validate_conditions(conditions)
        dev_stats = _evaluate_method(development, market, clean)
        val_stats = _evaluate_method(validation, market, clean)
        total_stats = _evaluate_method(base, market, clean)
        stability = _season_stability(base, market, clean)
        validation_stability = _season_stability(validation, market, clean, min_entries_per_season=4)

        min_dev = max(18, math.ceil(len(development) * .006))
        min_val = max(8, math.ceil(len(validation) * .004))
        if dev_stats["entries"] < min_dev or val_stats["entries"] < min_val or total_stats["entries"] < 30:
            return
        if dev_stats["profit"] <= 0 or val_stats["profit"] <= 0 or total_stats["profit"] <= 0:
            return
        if dev_stats["roi"] <= 0 or val_stats["roi"] < 1.0 or total_stats["roi"] < 1.0:
            return

        min_tested_seasons = min(3, len({r["season"] for r in base}))
        if stability["tested_seasons"] < min_tested_seasons:
            return
        if stability["positive_season_pct"] < 60.0 or stability["median_season_roi"] <= 0:
            return
        if validation_stability["tested_seasons"] and validation_stability["positive_season_pct"] < 50.0:
            return

        score = _robust_candidate_score(total_stats, val_stats, stability)
        candidates.append({
            "title": title,
            "market": market,
            "conditions": clean,
            "source": source,
            "stats": total_stats,
            "development": dev_stats,
            "validation": val_stats,
            "stability": stability,
            "validation_stability": validation_stability,
            "score": score,
        })

    # Métodos 1X2: preço NÃO é condição do gerador automático.
    # O padrão precisa combinar vantagem de força + ELO + custo do gol/forma.
    side_specs = [
        {
            "market": "home", "side": "Mandante",
            "elo": "home_elo_adv", "cg1": "home_cg1_adv", "cg2": "home_cg2_adv",
            "attack": "home_attack_adv", "defense": "home_defense_adv", "ppg": "home_ppg_5",
            "streak": "home_win_streak",
        },
        {
            "market": "away", "side": "Visitante",
            "elo": "away_elo_adv", "cg1": "away_cg1_adv", "cg2": "away_cg2_adv",
            "attack": "away_attack_adv", "defense": "away_defense_adv", "ppg": "away_ppg_5",
            "streak": "away_win_streak",
        },
    ]

    for spec in side_specs:
        for q in (.55, .65, .75):
            elo = qvalue(development, spec["elo"], q, 0)
            cg1 = qvalue(development, spec["cg1"], q, 0)
            cg2 = qvalue(development, spec["cg2"], q, 0)
            attack = qvalue(development, spec["attack"], q, 0)
            defense = qvalue(development, spec["defense"], q, 0)
            ppg = qvalue(development, spec["ppg"], q)

            if elo is not None and cg1 is not None:
                add(
                    f"{spec['side']} | ELO + custo gol 1.0 P{int(q*100)}",
                    spec["market"],
                    [
                        {"field": spec["elo"], "operator": "gte", "value": elo},
                        {"field": spec["cg1"], "operator": "gte", "value": cg1},
                    ],
                    "elo_custo_gol",
                )
            if elo is not None and attack is not None and defense is not None:
                add(
                    f"{spec['side']} | ELO + ataque + defesa P{int(q*100)}",
                    spec["market"],
                    [
                        {"field": spec["elo"], "operator": "gte", "value": elo},
                        {"field": spec["attack"], "operator": "gte", "value": attack},
                        {"field": spec["defense"], "operator": "gte", "value": defense},
                    ],
                    "elo_forcas",
                )
            if elo is not None and cg1 is not None and defense is not None:
                add(
                    f"{spec['side']} | ELO + CG1 + defesa P{int(q*100)}",
                    spec["market"],
                    [
                        {"field": spec["elo"], "operator": "gte", "value": elo},
                        {"field": spec["cg1"], "operator": "gte", "value": cg1},
                        {"field": spec["defense"], "operator": "gte", "value": defense},
                    ],
                    "elo_cg_defesa",
                )
            if elo is not None and cg1 is not None and cg2 is not None:
                add(
                    f"{spec['side']} | ELO + CG1 + CG2 P{int(q*100)}",
                    spec["market"],
                    [
                        {"field": spec["elo"], "operator": "gte", "value": elo},
                        {"field": spec["cg1"], "operator": "gte", "value": cg1},
                        {"field": spec["cg2"], "operator": "gte", "value": cg2},
                    ],
                    "elo_custos",
                )
            if elo is not None and cg1 is not None and ppg is not None:
                add(
                    f"{spec['side']} | ELO + CG1 + forma P{int(q*100)}",
                    spec["market"],
                    [
                        {"field": spec["elo"], "operator": "gte", "value": elo},
                        {"field": spec["cg1"], "operator": "gte", "value": cg1},
                        {"field": spec["ppg"], "operator": "gte", "value": ppg},
                    ],
                    "elo_cg_forma",
                )

        # Sequência só é usada em conjunto com ELO + custo do gol, nunca isoladamente.
        elo55 = qvalue(development, spec["elo"], .55, 0)
        cg55 = qvalue(development, spec["cg1"], .55, 0)
        if elo55 is not None and cg55 is not None:
            for streak in (2, 3, 4):
                add(
                    f"{spec['side']} | {streak} vitórias + ELO + CG1",
                    spec["market"],
                    [
                        {"field": spec["streak"], "operator": "gte", "value": streak},
                        {"field": spec["elo"], "operator": "gte", "value": elo55},
                        {"field": spec["cg1"], "operator": "gte", "value": cg55},
                    ],
                    "sequencia_estrutural",
                )

    # Over 2,5: combinação de custos do gol + comportamento recente + forças.
    cost_combos = _over_cost_combo_summary(development, top_n=10)
    goals60 = qvalue(development, "match_avg_goals_10", .60)
    attack60 = qvalue(development, "combined_attack_strength", .60)
    defense60 = qvalue(development, "combined_defense_weakness", .60)
    for idx, combo in enumerate(cost_combos, 1):
        conditions = [
            {"field": "avg_cg1", "operator": "between", "value": combo["cg1_min"], "value2": combo["cg1_max"]},
            {"field": "avg_cg2", "operator": "between", "value": combo["cg2_min"], "value2": combo["cg2_max"]},
        ]
        if goals60 is not None:
            conditions.append({"field": "match_avg_goals_10", "operator": "gte", "value": goals60})
        add(f"Over 2,5 | combinação CG #{idx}", "over25", conditions, "over_custos")

    for q in (.55, .65, .75):
        goals = qvalue(development, "match_avg_goals_10", q)
        attack = qvalue(development, "combined_attack_strength", q)
        defense = qvalue(development, "combined_defense_weakness", q)
        over_h = qvalue(development, "home_over25_pct_10", q)
        over_a = qvalue(development, "away_over25_pct_10", q)
        cv1 = qvalue(development, "avg_cv_cg1", 1 - (q - .50))
        cv2 = qvalue(development, "avg_cv_cg2", 1 - (q - .50))

        if goals is not None and attack is not None and defense is not None:
            add(
                f"Over 2,5 | gols + ataque + defesas P{int(q*100)}",
                "over25",
                [
                    {"field": "match_avg_goals_10", "operator": "gte", "value": goals},
                    {"field": "combined_attack_strength", "operator": "gte", "value": attack},
                    {"field": "combined_defense_weakness", "operator": "gte", "value": defense},
                ],
                "over_forcas",
            )
        if over_h is not None and over_a is not None and goals is not None:
            add(
                f"Over 2,5 | frequência + média gols P{int(q*100)}",
                "over25",
                [
                    {"field": "home_over25_pct_10", "operator": "gte", "value": over_h},
                    {"field": "away_over25_pct_10", "operator": "gte", "value": over_a},
                    {"field": "match_avg_goals_10", "operator": "gte", "value": goals},
                ],
                "over_frequencia",
            )
        if goals is not None and cv1 is not None and cv2 is not None:
            add(
                f"Over 2,5 | gols + estabilidade CG P{int(q*100)}",
                "over25",
                [
                    {"field": "match_avg_goals_10", "operator": "gte", "value": goals},
                    {"field": "avg_cv_cg1", "operator": "lte", "value": cv1},
                    {"field": "avg_cv_cg2", "operator": "lte", "value": cv2},
                ],
                "over_estabilidade_cg",
            )

    # Remove candidatos idênticos e ordena pela validação + estabilidade, não pelo lucro nominal.
    unique = {}
    for c in candidates:
        key = _candidate_key(c["market"], c["conditions"])
        prev = unique.get(key)
        if prev is None or c["score"] > prev["score"]:
            unique[key] = c
    ordered = sorted(
        unique.values(),
        key=lambda x: (
            x["score"],
            x["validation"]["roi"],
            x["stability"]["positive_season_pct"],
            x["stats"]["roi"],
        ),
        reverse=True,
    )
    return ordered, {
        "development_games": len(development),
        "validation_games": len(validation),
        "validation_seasons": validation_seasons,
    }


def generate_profitable_methods(competition_id: int, target_season: str, quantity: int = 10):
    quantity = max(1, min(int(quantity or 10), 20))
    meta = _competition_meta(competition_id)
    target_key = season_key(_season_text(target_season))
    base = [r for r in records(competition_id) if season_key(r["season"]) < target_key]
    if not base:
        raise ValueError("Não há histórico anterior à temporada alvo para gerar métodos.")

    candidates, split_info = _profitable_method_candidates(base)
    if not candidates:
        raise ValueError("Nenhum método estrutural passou pelos critérios de lucro e consistência na validação histórica.")

    selected = []
    market_count = defaultdict(int)
    for cand in candidates:
        if market_count[cand["market"]] >= 5:
            continue
        if any(_candidate_overlap(cand, prev) >= .75 and cand["market"] == prev["market"] for prev in selected):
            continue
        selected.append(cand)
        market_count[cand["market"]] += 1
        if len(selected) >= quantity:
            break

    if len(selected) < quantity:
        used = {_candidate_key(c["market"], c["conditions"]) for c in selected}
        for cand in candidates:
            key = _candidate_key(cand["market"], cand["conditions"])
            if key in used:
                continue
            selected.append(cand)
            used.add(key)
            if len(selected) >= quantity:
                break

    created = []
    prefix = f"AUTO ROBUSTO {meta['competition']}"
    legacy_prefix = f"AUTO {meta['competition']} |%"
    robust_prefix = f"AUTO ROBUSTO {meta['competition']} |%"

    with app_engine.begin() as conn:
        # Limpa somente métodos automáticos antigos desta competição. Métodos criados pelo usuário são preservados.
        conn.execute(text(f"""
            DELETE FROM {settings.app_schema}.scanner_metodos
            WHERE nome ILIKE :legacy OR nome ILIKE :robust
        """), {"legacy": legacy_prefix, "robust": robust_prefix})

        for cand in selected:
            name = f"{prefix} | {cand['title']}"
            if len(name) > 160:
                name = name[:160]
            conditions_json = json.dumps(cand["conditions"], ensure_ascii=False)
            method_id = int(conn.execute(text(f"""
                INSERT INTO {settings.app_schema}.scanner_metodos (nome, mercado, condicoes)
                VALUES (:name, :market, CAST(:conditions AS jsonb))
                RETURNING id
            """), {"name": name, "market": cand["market"], "conditions": conditions_json}).scalar_one())

            st = cand["stats"]
            dev = cand["development"]
            val = cand["validation"]
            stability = cand["stability"]
            created.append({
                "id": method_id,
                "nome": name,
                "mercado": cand["market"],
                "mercado_label": MARKETS[cand["market"]],
                "condicoes": cand["conditions"],
                "condicoes_resumo": _condition_texts(cand["conditions"]),
                "entries": st["entries"],
                "greens": st["greens"],
                "reds": st["reds"],
                "win_rate": round(st["win_rate"], 2),
                "profit": round(st["profit"], 2),
                "roi": round(st["roi"], 2),
                "avg_odd": round(st["avg_odd"], 2) if st["avg_odd"] is not None else None,
                "development_entries": dev["entries"],
                "development_profit": round(dev["profit"], 2),
                "development_roi": round(dev["roi"], 2),
                "validation_entries": val["entries"],
                "validation_profit": round(val["profit"], 2),
                "validation_roi": round(val["roi"], 2),
                "tested_seasons": stability["tested_seasons"],
                "positive_seasons": stability["positive_seasons"],
                "positive_season_pct": round(stability["positive_season_pct"], 2),
                "median_season_roi": round(stability["median_season_roi"], 2),
                "worst_season_roi": round(stability["worst_season_roi"], 2),
                "source": cand["source"],
            })

    return {
        "competition_id": competition_id,
        "competition": meta["competition"],
        "country": meta["country"],
        "target_season": target_season,
        "historical_games": len(base),
        "historical_until": max((r["season"] for r in base), key=season_key),
        "requested": quantity,
        "generated": len(created),
        "methods": created,
        "development_games": split_info["development_games"],
        "validation_games": split_info["validation_games"],
        "validation_seasons": split_info["validation_seasons"],
        "note": (
            "Os métodos automáticos não usam faixa de odd como regra principal. Cada método combina sinais estruturais "
            "(ELO, forças, custo do gol, forma e/ou frequência de gols) e precisa ter L/P positivo tanto no bloco de "
            "desenvolvimento quanto na validação histórica, além de consistência positiva por temporada. A temporada alvo permanece totalmente fora da seleção do método."
        ),
    }


def available_seasons(competition_id: int):
    """Retorna somente as temporadas realmente existentes no histórico do campeonato.

    Não usa temporadas globais, valores de mercado ou odds para preencher o filtro.
    Assim, ao selecionar um campeonato, o usuário vê apenas as temporadas que aquele
    campeonato efetivamente possui na tabela histórica.
    """
    values = {
        _season_text(r.get("temporada"))
        for r in _history(competition_id)
        if r.get("temporada")
    }
    return sorted(values, key=season_key, reverse=True)


def condition_catalog():
    return {
        "markets": [{"key": k, "label": v} for k, v in MARKETS.items()],
        "conditions": CONDITION_CATALOG,
        "operators": [
            {"key": "gt", "label": "Maior que"},
            {"key": "gte", "label": "Maior ou igual"},
            {"key": "lt", "label": "Menor que"},
            {"key": "lte", "label": "Menor ou igual"},
            {"key": "eq", "label": "Igual"},
            {"key": "between", "label": "Entre"},
        ],
    }


def _condition_texts(conditions):
    conditions = conditions or []
    team_ids = sorted({int(c.get("value")) for c in conditions if c.get("field") in {"home_team_id", "away_team_id"} and c.get("value") is not None})
    team_names = {}
    if team_ids:
        with app_engine.connect() as conn:
            team_names = {int(x["id"]): x["nome"] for x in conn.execute(text(f"SELECT id, nome FROM {settings.app_schema}.clubes WHERE id = ANY(:ids)"), {"ids": team_ids}).mappings()}
    summaries = []
    for c in conditions:
        if c.get("field") in {"home_team_id", "away_team_id"}:
            meta = CATALOG_BY_KEY.get(c.get("field"), {"label": c.get("field")})
            summaries.append(f"{meta['label']} = {team_names.get(int(c.get('value')), c.get('value'))}")
        else:
            summaries.append(condition_text(c))
    return summaries


def list_methods():
    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT id, nome, mercado, condicoes, criado_em, atualizado_em
            FROM {settings.app_schema}.scanner_metodos
            ORDER BY nome
        """)).mappings()]
    for r in rows:
        if isinstance(r.get("condicoes"), str):
            r["condicoes"] = json.loads(r["condicoes"])
        r["mercado_label"] = MARKETS.get(r["mercado"], r["mercado"])
        r["condicoes_resumo"] = _condition_texts(r.get("condicoes") or [])
        for key in ("criado_em", "atualizado_em"):
            if r.get(key): r[key] = r[key].isoformat()
    return rows


def _validate_conditions(conditions):
    clean = []
    numeric_kinds = {"number", "integer", "percent"}
    for c in conditions or []:
        field = str(c.get("field") or "")
        op = str(c.get("operator") or "")
        compare_field = str(c.get("compare_field") or "").strip() or None

        if field not in CATALOG_BY_KEY:
            raise ValueError(f"Condição inválida: {field}.")
        if op not in {"gt", "gte", "lt", "lte", "eq", "between"}:
            raise ValueError(f"Operador inválido: {op}.")

        kind = CATALOG_BY_KEY[field]["kind"]
        value = c.get("value")
        value2 = c.get("value2")

        if kind == "team":
            if compare_field:
                raise ValueError("Condições de clube não podem ser comparadas com outro indicador.")
            try:
                value = int(value)
            except Exception as exc:
                raise ValueError("Selecione um clube válido na condição.") from exc
            op = "eq"
        elif compare_field:
            if compare_field not in CATALOG_BY_KEY:
                raise ValueError(f"Indicador de comparação inválido: {compare_field}.")
            compare_kind = CATALOG_BY_KEY[compare_field]["kind"]
            if kind not in numeric_kinds or compare_kind not in numeric_kinds:
                raise ValueError("A comparação entre indicadores só aceita campos numéricos.")
            if kind != compare_kind:
                raise ValueError(
                    f"Compare indicadores do mesmo tipo: {CATALOG_BY_KEY[field]['label']} "
                    f"e {CATALOG_BY_KEY[compare_field]['label']} não são compatíveis."
                )
            if compare_field == field:
                raise ValueError("Escolha um indicador diferente para comparar.")
            if op == "between":
                raise ValueError("O operador Entre só pode ser usado com valores numéricos fixos.")
            value = None
            value2 = None
        else:
            try:
                value = float(value)
            except Exception as exc:
                raise ValueError(f"Informe um valor numérico para {CATALOG_BY_KEY[field]['label']}.") from exc
            if op == "between":
                try:
                    value2 = float(value2)
                except Exception as exc:
                    raise ValueError("O operador Entre exige dois valores.") from exc
                if value2 < value:
                    value, value2 = value2, value

        clean.append({
            "field": field,
            "operator": op,
            "value": value,
            "value2": value2,
            "compare_field": compare_field,
        })
    return clean


def create_method(name: str, market: str, conditions):
    name = (name or "").strip()
    if not name:
        raise ValueError("Informe o nome do método.")
    if market not in MARKETS:
        raise ValueError("Mercado inválido.")
    clean = _validate_conditions(conditions)
    with app_engine.begin() as conn:
        try:
            row = conn.execute(text(f"""
                INSERT INTO {settings.app_schema}.scanner_metodos (nome, mercado, condicoes)
                VALUES (:name, :market, CAST(:conditions AS jsonb))
                RETURNING id, nome, mercado, condicoes
            """), {"name": name, "market": market, "conditions": json.dumps(clean, ensure_ascii=False)}).mappings().one()
        except Exception as exc:
            if "scanner_metodos_nome_lower" in str(exc) or "duplicate" in str(exc).lower():
                raise ValueError("Já existe um método com esse nome.") from exc
            raise
    return dict(row)


def update_method(method_id: int, name: str, market: str, conditions):
    name = (name or "").strip()
    if not name:
        raise ValueError("Informe o nome do método.")
    if market not in MARKETS:
        raise ValueError("Mercado inválido.")
    clean = _validate_conditions(conditions)

    with app_engine.begin() as conn:
        exists = conn.execute(
            text(f"SELECT id FROM {settings.app_schema}.scanner_metodos WHERE id=:id"),
            {"id": method_id},
        ).scalar()
        if not exists:
            raise ValueError("Método não encontrado.")

        try:
            row = conn.execute(text(f"""
                UPDATE {settings.app_schema}.scanner_metodos
                   SET nome=:name,
                       mercado=:market,
                       condicoes=CAST(:conditions AS jsonb),
                       atualizado_em=NOW()
                 WHERE id=:id
             RETURNING id, nome, mercado, condicoes, criado_em, atualizado_em
            """), {
                "id": method_id,
                "name": name,
                "market": market,
                "conditions": json.dumps(clean, ensure_ascii=False),
            }).mappings().one()
        except Exception as exc:
            if "scanner_metodos_nome_lower" in str(exc) or "duplicate" in str(exc).lower():
                raise ValueError("Já existe outro método com esse nome.") from exc
            raise

    out = dict(row)
    if isinstance(out.get("condicoes"), str):
        out["condicoes"] = json.loads(out["condicoes"])
    out["mercado_label"] = MARKETS.get(out["mercado"], out["mercado"])
    out["condicoes_resumo"] = _condition_texts(out.get("condicoes") or [])
    for key in ("criado_em", "atualizado_em"):
        if out.get(key):
            out[key] = out[key].isoformat()
    return out



def append_method_condition(method_id: int, condition):
    """Acrescenta uma condição ao método sem substituir as demais.

    A transação bloqueia o registro para impedir perdas de atualização entre
    duas inclusões simultâneas. A mesma condição não é adicionada duas vezes.
    """
    cleaned = _validate_conditions([condition])[0]
    with app_engine.begin() as conn:
        row = conn.execute(text(f"""
            SELECT id, condicoes
            FROM {settings.app_schema}.scanner_metodos
            WHERE id = :id
            FOR UPDATE
        """), {"id": method_id}).mappings().first()
        if row is None:
            raise ValueError("Método não encontrado.")

        existing = row["condicoes"] or []
        if isinstance(existing, str):
            existing = json.loads(existing)

        # Compara apenas os campos usados nas regras, ignorando metadados.
        def identity(item):
            return (
                item.get("field"), item.get("operator"),
                item.get("compare_field") or None,
                item.get("value"), item.get("value2"),
            )

        if any(identity(item) == identity(cleaned) for item in existing):
            return {"added": False, "method_id": method_id,
                    "message": "Esta condição já existe no método."}

        updated = [*existing, cleaned]
        conn.execute(text(f"""
            UPDATE {settings.app_schema}.scanner_metodos
            SET condicoes = CAST(:conditions AS jsonb), atualizado_em = NOW()
            WHERE id = :id
        """), {
            "id": method_id,
            "conditions": json.dumps(updated, ensure_ascii=False),
        })
    return {"added": True, "method_id": method_id,
            "message": "Condição adicionada ao método.",
            "condition": condition_text(cleaned)}


def delete_method(method_id: int):
    with app_engine.begin() as conn:
        deleted = conn.execute(text(f"DELETE FROM {settings.app_schema}.scanner_metodos WHERE id=:id RETURNING id"), {"id": method_id}).scalar()
    return bool(deleted)


def _get_method(method_id: int):
    with app_engine.connect() as conn:
        row = conn.execute(text(f"SELECT id, nome, mercado, condicoes FROM {settings.app_schema}.scanner_metodos WHERE id=:id"), {"id": method_id}).mappings().first()
    if not row:
        raise ValueError("Método não encontrado.")
    out = dict(row)
    if isinstance(out.get("condicoes"), str): out["condicoes"] = json.loads(out["condicoes"])
    return out


def _entry_odd(record, market):
    return {"home": record.get("home_odd"), "draw": record.get("draw_odd"), "away": record.get("away_odd"),
            "over25": record.get("over25_odd"), "under25": record.get("under25_odd")}.get(market)


def _condition_value(record, field, market):
    if field == "entry_odd":
        return _entry_odd(record, market)
    if field == "home_team_id":
        return record.get("home_id")
    if field == "away_team_id":
        return record.get("away_id")
    return record.get(field)


def _match_condition(record, condition, market):
    actual = _condition_value(record, condition["field"], market)
    if actual is None:
        return False

    op = condition.get("operator")
    compare_field = condition.get("compare_field")

    if CATALOG_BY_KEY[condition["field"]]["kind"] == "team":
        expected = condition.get("value")
        return int(actual) == int(expected)

    if compare_field:
        expected = _condition_value(record, compare_field, market)
        if expected is None:
            return False
    else:
        expected = condition.get("value")

    actual = float(actual)
    expected = float(expected)
    if op == "gt": return actual > expected
    if op == "gte": return actual >= expected
    if op == "lt": return actual < expected
    if op == "lte": return actual <= expected
    if op == "eq": return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
    if op == "between" and not compare_field:
        return expected <= actual <= float(condition.get("value2"))
    return False


def condition_text(condition):
    meta = CATALOG_BY_KEY.get(condition.get("field"), {"label": condition.get("field")})
    labels = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "between": "entre"}
    op = condition.get("operator")
    compare_field = condition.get("compare_field")
    if compare_field:
        compare_meta = CATALOG_BY_KEY.get(compare_field, {"label": compare_field})
        return f"{meta['label']} {labels.get(op, op)} {compare_meta['label']}"
    if op == "between":
        return f"{meta['label']} entre {condition.get('value')} e {condition.get('value2')}"
    return f"{meta['label']} {labels.get(op, op)} {condition.get('value')}"




def _red_pattern_fields(market):
    common = [
        "entry_odd",
        "home_win_pct_5", "away_win_pct_5",
        "home_win_pct_10", "away_win_pct_10",
        "home_ppg_5", "away_ppg_5",
        "home_ppg_10", "away_ppg_10",
        "home_avg_gf_5", "away_avg_gf_5",
        "home_avg_ga_5", "away_avg_ga_5",
        "home_avg_gf_10", "away_avg_gf_10",
        "home_avg_ga_10", "away_avg_ga_10",
        "home_over25_pct_10", "away_over25_pct_10",
        "match_avg_goals_10",
    ]
    if market == "home":
        return common + [
            "home_odd", "away_odd",
            "home_elo_adv", "home_attack_adv", "home_defense_adv",
            "home_cg1_adv", "home_cg2_adv",
            "home_attack_strength", "away_attack_strength",
            "home_defense_strength", "away_defense_strength",
            "home_cg1", "away_cg1", "home_cv_cg1", "away_cv_cg1",
            "home_cg2", "away_cg2", "home_cv_cg2", "away_cv_cg2",
        ]
    if market == "away":
        return common + [
            "away_odd", "home_odd",
            "away_elo_adv", "away_attack_adv", "away_defense_adv",
            "away_cg1_adv", "away_cg2_adv",
            "away_attack_strength", "home_attack_strength",
            "away_defense_strength", "home_defense_strength",
            "away_cg1", "home_cg1", "away_cv_cg1", "home_cv_cg1",
            "away_cg2", "home_cg2", "away_cv_cg2", "home_cv_cg2",
        ]
    if market in ("over25", "under25"):
        return common + [
            "over25_odd", "under25_odd",
            "avg_cg1", "avg_cg2", "avg_cv_cg1", "avg_cv_cg2",
            "combined_attack_strength", "combined_defense_weakness",
            "home_attack_strength", "away_attack_strength",
            "home_defense_strength", "away_defense_strength",
            "home_cg1", "away_cg1", "home_cg2", "away_cg2",
            "home_cv_cg1", "away_cv_cg1", "home_cv_cg2", "away_cv_cg2",
        ]
    return common + ["home_odd", "draw_odd", "away_odd", "elo_diff"]


def _pattern_number(field, value):
    meta = CATALOG_BY_KEY.get(field, {})
    kind = meta.get("kind")
    if kind == "percent":
        return f"{value:.1f}%"
    if "elo" in field:
        return f"{value:.1f} pts"
    if "odd" in field:
        return f"{value:.2f}"
    return f"{value:.2f}"


def _exclusive_red_patterns(games, market, stake=STAKE_DEFAULT):
    """Encontra caudas numéricas presentes somente nos reds do backtest.

    A regra é deliberadamente conservadora: o padrão só aparece quando nenhum
    green da mesma amostra satisfaz a condição e existe suporte mínimo entre os
    reds. Isso evita chamar uma simples diferença de média de "padrão exclusivo".
    """
    reds = [g for g in games if not g.get("green")]
    greens = [g for g in games if g.get("green")]
    if len(reds) < 3 or not greens:
        return []

    minimum_reds = max(3, math.ceil(len(reds) * 0.08))
    candidates = []
    seen = set()

    for field in _red_pattern_fields(market):
        meta = CATALOG_BY_KEY.get(field)
        if not meta or meta.get("kind") == "team":
            continue
        red_vals = [
            _finite((g.get("analysis_features") or {}).get(field))
            for g in reds
        ]
        green_vals = [
            _finite((g.get("analysis_features") or {}).get(field))
            for g in greens
        ]
        red_vals = [v for v in red_vals if v is not None]
        green_vals = [v for v in green_vals if v is not None]
        if len(red_vals) < minimum_reds or len(green_vals) < 2:
            continue

        # Cauda inferior exclusiva dos reds: X < menor valor observado nos greens.
        low_boundary = min(green_vals)
        low_reds = [v for v in red_vals if v < low_boundary]
        if len(low_reds) >= minimum_reds:
            key = (field, "lt", round(low_boundary, 8))
            if key not in seen:
                seen.add(key)
                candidates.append((field, "lt", low_boundary, len(low_reds)))

        # Cauda superior exclusiva dos reds: X > maior valor observado nos greens.
        high_boundary = max(green_vals)
        high_reds = [v for v in red_vals if v > high_boundary]
        if len(high_reds) >= minimum_reds:
            key = (field, "gt", round(high_boundary, 8))
            if key not in seen:
                seen.add(key)
                candidates.append((field, "gt", high_boundary, len(high_reds)))

    # Mais reds removidos primeiro. Em empate, prioriza variáveis estruturais.
    priority = {
        "home_elo_adv": 0, "away_elo_adv": 0, "elo_diff": 0,
        "home_cg1_adv": 1, "away_cg1_adv": 1, "home_cg2_adv": 1, "away_cg2_adv": 1,
        "avg_cg1": 1, "avg_cg2": 1,
        "home_attack_adv": 2, "away_attack_adv": 2,
        "home_defense_adv": 2, "away_defense_adv": 2,
        "combined_attack_strength": 2, "combined_defense_weakness": 2,
        "entry_odd": 5,
    }
    candidates.sort(key=lambda x: (-x[3], priority.get(x[0], 3), x[0]))

    out = []
    total_profit = sum(float(g.get("profit") or 0) for g in games)
    total_greens = len(greens)
    total_entries = len(games)

    for field, op, threshold, red_count in candidates:
        if len(out) >= 6:
            break
        label = CATALOG_BY_KEY[field]["label"]
        threshold_text = _pattern_number(field, threshold)
        symbol = "<" if op == "lt" else ">"
        inverse_symbol = "≥" if op == "lt" else "≤"
        inverse_operator = "gte" if op == "lt" else "lte"

        remaining_entries = total_entries - red_count
        projected_profit = total_profit + red_count * stake
        projected_win_rate = (total_greens / remaining_entries * 100) if remaining_entries else 0.0
        projected_roi = (projected_profit / (remaining_entries * stake) * 100) if remaining_entries else 0.0

        out.append({
            "field": field,
            "field_label": label,
            "operator": op,
            "threshold": round(float(threshold), 6),
            "pattern": f"{label} {symbol} {threshold_text}",
            "reds_matched": red_count,
            "greens_matched": 0,
            "red_coverage": round(red_count / len(reds) * 100, 2),
            "suggested_operator": inverse_operator,
            "suggested_condition": f"Teste adicionar: {label} {inverse_symbol} {threshold_text}",
            "projected_profit": round(projected_profit, 2),
            "projected_roi": round(projected_roi, 2),
            "projected_win_rate": round(projected_win_rate, 2),
            "projected_entries": remaining_entries,
            "note": "Projeção na mesma amostra; confirme o ajuste em outra temporada antes de incorporá-lo ao método.",
        })

    return out

def _descriptive_backtest_analysis(games, market):
    if not games:
        return ["O método não gerou entradas nesta temporada."]
    greens = [g for g in games if g["green"]]
    reds = [g for g in games if not g["green"]]
    total_profit = sum(g["profit"] for g in games)
    lines = [
        f"O método gerou {len(games)} entradas: {len(greens)} greens e {len(reds)} reds, com L/P de R$ {total_profit:,.2f}.",
        f"Win rate de {len(greens)/len(games)*100:.1f}% e ROI de {total_profit/(len(games)*STAKE_DEFAULT)*100:.1f}% com stake fixa de R$ 100,00.",
    ]
    if greens and reds:
        avg_g_odd = mean(g["odd"] for g in greens); avg_r_odd = mean(g["odd"] for g in reds)
        lines.append(f"Odd média dos greens: {avg_g_odd:.2f}; odd média dos reds: {avg_r_odd:.2f}.")
        if market in ("home", "away"):
            sign = 1 if market == "home" else -1
            g_elo = mean(sign * g["elo_diff"] for g in greens); r_elo = mean(sign * g["elo_diff"] for g in reds)
            lines.append(f"Vantagem média de ELO na direção da entrada: {g_elo:+.1f} pts nos greens contra {r_elo:+.1f} pts nos reds.")
            g_att = mean(g["direction_attack_adv"] for g in greens); r_att = mean(g["direction_attack_adv"] for g in reds)
            lines.append(f"Diferença média de força ofensiva na direção da entrada: {g_att:+.2f} nos greens contra {r_att:+.2f} nos reds.")
        else:
            g_goals = mean(g["match_avg_goals_10"] for g in greens); r_goals = mean(g["match_avg_goals_10"] for g in reds)
            lines.append(f"Média pré-jogo de gols combinados: {g_goals:.2f} nos greens contra {r_goals:.2f} nos reds.")
    lines.append("As diferenças acima são associações descritivas do backtest; não representam causalidade.")
    return lines


def backtest(competition_id: int, target_season: str, method_id: int, stake: float = STAKE_DEFAULT):
    method = _get_method(method_id)
    stake = STAKE_DEFAULT
    rows = [r for r in records(competition_id) if _same_season(r["season"], target_season)]
    condition_descriptions = _condition_texts(method.get("condicoes") or [])
    entries = []
    for r in rows:
        if not all(_match_condition(r, c, method["mercado"]) for c in method.get("condicoes") or []):
            continue
        odd, green, _ = _bet_result(r, method["mercado"], stake)
        if odd is None:
            continue
        profit = stake * (odd - 1) if green else -stake
        conditions = condition_descriptions
        direction_attack_adv = r["home_attack_strength"] - r["away_attack_strength"] if method["mercado"] == "home" else r["away_attack_strength"] - r["home_attack_strength"]
        analysis_features = {}
        for field in _red_pattern_fields(method["mercado"]):
            value = _condition_value(r, field, method["mercado"])
            if value is not None:
                analysis_features[field] = value
        entries.append({
            "date": r["date"], "season": r["season"], "home": r["home"], "away": r["away"],
            "score": f"{r['gh']}–{r['ga']}", "odd": round(odd, 3), "green": green,
            "status": "Green" if green else "Red", "profit": round(profit, 2),
            "matched_conditions": conditions, "elo_diff": r["elo_diff"],
            "direction_attack_adv": direction_attack_adv, "match_avg_goals_10": r["match_avg_goals_10"],
            "home_cg1": r.get("home_cg1"), "away_cg1": r.get("away_cg1"),
            "analysis_features": analysis_features,
        })
    monthly = defaultdict(lambda: {"entries": 0, "greens": 0, "reds": 0, "profit": 0.0})
    for g in entries:
        key = g["date"].strftime("%m/%Y")
        monthly[key]["entries"] += 1
        monthly[key]["greens"] += int(g["green"])
        monthly[key]["reds"] += int(not g["green"])
        monthly[key]["profit"] += g["profit"]
    rows_monthly = []
    for key, data in sorted(monthly.items(), key=lambda kv: (int(kv[0].split("/")[1]), int(kv[0].split("/")[0]))):
        rows_monthly.append({"month": key, **data, "win_rate": round(data["greens"] / data["entries"] * 100, 2), "profit": round(data["profit"], 2)})
    total_entries = len(entries); total_greens = sum(g["green"] for g in entries); total_profit = sum(g["profit"] for g in entries)
    total = {"entries": total_entries, "greens": total_greens, "reds": total_entries-total_greens,
             "win_rate": round(total_greens/total_entries*100, 2) if total_entries else 0.0,
             "profit": round(total_profit, 2), "roi": round(total_profit/(total_entries*stake)*100, 2) if total_entries else 0.0,
             "stake": stake}
    red_patterns = _exclusive_red_patterns(entries, method["mercado"], stake)
    for g in entries:
        g["date"] = g["date"].isoformat()
        g.pop("analysis_features", None)
    return {"method": {"id": method["id"], "name": method["nome"], "market": method["mercado"], "market_label": MARKETS[method["mercado"]],
                       "conditions": condition_descriptions},
            "season": target_season, "monthly": rows_monthly, "total": total,
            "analysis": _descriptive_backtest_analysis(entries, method["mercado"]),
            "red_patterns": red_patterns,
            "red_patterns_message": None if red_patterns else "Não encontrei nenhum padrão exclusivo dos reds com amostra mínima. O método não pode ser lapidado com as informações atuais.",
            "games": entries}
