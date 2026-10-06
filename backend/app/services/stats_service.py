import math
from datetime import date
from statistics import pstdev

from sqlalchemy import text

from ..config import settings
from ..db import app_engine
from ..repositories.history_repository import club_games
from .elo_service import (
    elo_evolution,
    elo_probability,
    matchup_strengths,
    normalize_name,
    season_key,
    strength_profile,
)


def _club_meta(club_id: int):
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT cl.id, cl.nome, cl.escudo_url, cl.pais_id, p.nome AS pais
                FROM {settings.app_schema}.clubes cl
                JOIN {settings.app_schema}.paises p ON p.id = cl.pais_id
                WHERE cl.id = :id
                """
            ),
            {"id": club_id},
        ).mappings().first()
        aliases = conn.execute(
            text(
                f"SELECT alias FROM {settings.app_schema}.clubes_aliases WHERE clube_id = :id"
            ),
            {"id": club_id},
        ).scalars().all()

    if not row:
        raise ValueError("Clube não encontrado.")
    data = dict(row)
    data["names"] = [data["nome"], *aliases]
    return data


def _competition(competition_id: int | None):
    if not competition_id:
        return None
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT c.id, c.nome, c.principal, p.nome AS pais
                FROM {settings.app_schema}.campeonatos c
                JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
                WHERE c.id = :id
                """
            ),
            {"id": competition_id},
        ).mappings().first()
    return dict(row) if row else None


def club_filter_options(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
    venue: str = "all",
):
    meta = _club_meta(club_id)
    with app_engine.connect() as conn:
        competitions = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT DISTINCT c.id, c.nome, c.principal
                    FROM {settings.app_schema}.campeonatos c
                    WHERE c.pais_id = :country
                    ORDER BY c.principal DESC, c.nome
                    """
                ),
                {"country": meta["pais_id"]},
            ).mappings()
        ]

    comp = _competition(competition_id)
    season_games = club_games(
        meta["names"],
        country=meta["pais"],
        competition=comp["nome"] if comp else None,
        season=None,
        venue="all",
    )
    games = club_games(
        meta["names"],
        country=meta["pais"],
        competition=comp["nome"] if comp else None,
        season=season or None,
        venue=venue,
    )
    own = {normalize_name(x) for x in meta["names"]}
    seasons = sorted(
        {str(g["temporada"]) for g in season_games if g.get("temporada") not in (None, "")},
        key=season_key,
        reverse=True,
    )
    opponents = set()
    for g in games:
        is_home = normalize_name(g["casa"]) in own
        opponents.add(g["fora"] if is_home else g["casa"])

    return {
        "competitions": competitions,
        "seasons": seasons,
        "opponents": sorted(opponents, key=lambda x: x.casefold()),
    }


def _odd_rows(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
    season_cutoff: str | None = None,
):
    clauses = ["(clube_casa_id = :club OR clube_fora_id = :club)"]
    params = {"club": club_id}
    if competition_id:
        clauses.append("campeonato_id = :competition")
        params["competition"] = competition_id
    if season:
        clauses.append("temporada = :season")
        params["season"] = season

    with app_engine.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT data, temporada, campeonato_id, clube_casa_id, clube_fora_id,
                           odd_casa::float, odd_empate::float, odd_fora::float
                    FROM {settings.app_schema}.odds_jogos
                    WHERE {' AND '.join(clauses)}
                    """
                ),
                params,
            ).mappings()
        ]
    if season_cutoff:
        cutoff = season_key(season_cutoff)
        rows = [
            r for r in rows
            if not r.get("temporada") or season_key(str(r["temporada"])) <= cutoff
        ]
    return rows


def _cv(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if mean == 0:
        return None
    return pstdev(vals) / mean * 100


def _avg(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def _game_public(row):
    return {
        "date": row.get("date"),
        "season": row.get("season"),
        "competition": row.get("competition"),
        "opponent": row.get("opponent"),
        "venue": row.get("venue"),
        "gf": row.get("gf"),
        "ga": row.get("ga"),
        "score": f"{row.get('gf', 0)}–{row.get('ga', 0)}",
        "goal_diff": abs(int(row.get("gd", 0))),
        "odd": row.get("odd"),
    }


def _winning_odd_band(perspective):
    bands = [
        (1.00, 1.49, "1,00–1,49"),
        (1.50, 1.79, "1,50–1,79"),
        (1.80, 2.19, "1,80–2,19"),
        (2.20, 2.99, "2,20–2,99"),
        (3.00, 4.99, "3,00–4,99"),
        (5.00, float("inf"), "5,00+"),
    ]

    candidates = []
    for low, high, label in bands:
        games = [
            x
            for x in perspective
            if x.get("odd") is not None
            and float(x["odd"]) >= low
            and float(x["odd"]) <= high
        ]
        if not games:
            continue
        winning_games = [x for x in games if x["result"] == "W"]
        wins = len(winning_games)
        if wins == 0:
            continue
        win_pct = wins / len(games) * 100
        candidates.append(
            {
                "label": label,
                "low": low,
                "high": None if math.isinf(high) else high,
                "wins": wins,
                "games": len(games),
                "win_pct": win_pct,
                "games_detail": [
                    _game_public(x)
                    for x in sorted(
                        winning_games,
                        key=lambda r: (r.get("date") or "", float(r.get("odd") or 0)),
                        reverse=True,
                    )
                ],
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (x["wins"], x["win_pct"], x["games"]),
        reverse=True,
    )
    return candidates[0]


def calculate_club_stats(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
    limit: int | None = None,
    venue: str = "all",
    opponent: str | None = None,
    result_filter: str = "all",
    season_cutoff: str | None = None,
):
    meta = _club_meta(club_id)
    comp = _competition(competition_id)
    games = club_games(
        meta["names"],
        country=comp["pais"] if comp else meta["pais"],
        competition=comp["nome"] if comp else None,
        season=season,
        venue=venue,
    )
    if season_cutoff and season is None:
        cutoff = season_key(season_cutoff)
        games = [
            g for g in games
            if not g.get("temporada") or season_key(str(g["temporada"])) <= cutoff
        ]
    own_norm = {normalize_name(x) for x in meta["names"]}
    odds = _odd_rows(club_id, competition_id, season, season_cutoff)
    odd_by = {}
    for odd in odds:
        if odd["data"]:
            odd_by.setdefault(str(odd["data"]), []).append(odd)

    perspective = []
    opponent_norm = normalize_name(opponent) if opponent else None

    for g in games:
        is_home = normalize_name(g["casa"]) in own_norm
        opponent_name = g["fora"] if is_home else g["casa"]
        if opponent_norm and normalize_name(opponent_name) != opponent_norm:
            continue

        gf = int(g["gols_casa"] if is_home else g["gols_fora"])
        ga = int(g["gols_fora"] if is_home else g["gols_casa"])
        result = "W" if gf > ga else "D" if gf == ga else "L"
        if result_filter == "win" and result != "W":
            continue
        if result_filter == "draw" and result != "D":
            continue
        if result_filter == "loss" and result != "L":
            continue

        team_odd = None
        opp_odd = None
        odds_triplet = None
        if g.get("data"):
            for odd in odd_by.get(str(g["data"]), []):
                if is_home and odd["clube_casa_id"] == club_id:
                    team_odd = odd["odd_casa"]
                    opp_odd = odd["odd_fora"]
                    odds_triplet = [odd["odd_casa"], odd["odd_empate"], odd["odd_fora"]]
                    break
                if (not is_home) and odd["clube_fora_id"] == club_id:
                    team_odd = odd["odd_fora"]
                    opp_odd = odd["odd_casa"]
                    odds_triplet = [odd["odd_casa"], odd["odd_empate"], odd["odd_fora"]]
                    break

        p = (1.0 / team_odd) if team_odd and team_odd > 0 else None
        p_opp = (1.0 / opp_odd) if opp_odd and opp_odd > 0 else None
        cg1 = (gf / p) if p else None
        cg2 = ((gf / 2.0) + (p / 2.0)) if p else None
        gd = gf - ga
        sg1 = (gd / p) if p else None
        sg2 = (gd / p_opp) if p_opp else None
        goal_value = (gf * p_opp) if p_opp else None
        odds_cv = _cv(odds_triplet) if odds_triplet and all(x for x in odds_triplet) else None

        perspective.append(
            {
                "date": str(g["data"]) if g.get("data") else None,
                "season": str(g.get("temporada") or ""),
                "competition": g.get("campeonato"),
                "venue": "home" if is_home else "away",
                "opponent": opponent_name,
                "gf": gf,
                "ga": ga,
                "gd": gd,
                "result": result,
                "odd": team_odd,
                "over25": (gf + ga) > 2.5,
                "cg1": cg1,
                "cg2": cg2,
                "sg1": sg1,
                "sg2": sg2,
                "goal_value": goal_value,
                "odds_cv": odds_cv,
            }
        )

    if limit:
        perspective = perspective[:limit]

    n = len(perspective)
    wins = sum(x["result"] == "W" for x in perspective)
    draws = sum(x["result"] == "D" for x in perspective)
    losses = n - wins - draws
    gf = sum(x["gf"] for x in perspective)
    ga = sum(x["ga"] for x in perspective)
    pts = wins * 3 + draws
    pct = lambda count: count / n * 100 if n else 0.0
    totals = [x["gf"] + x["ga"] for x in perspective]
    points = [3 if x["result"] == "W" else 1 if x["result"] == "D" else 0 for x in perspective]
    gfvals = [x["gf"] for x in perspective]
    gavals = [x["ga"] for x in perspective]
    gdvals = [x["gd"] for x in perspective]
    cg1vals = [x["cg1"] for x in perspective if x["cg1"] is not None and x["cg1"] != 0]
    cg2vals = [x["cg2"] for x in perspective if x["cg2"] is not None]
    sg1vals = [x["sg1"] for x in perspective if x["sg1"] is not None]
    sg2vals = [x["sg2"] for x in perspective if x["sg2"] is not None]
    gvvals = [x["goal_value"] for x in perspective if x["goal_value"] is not None]

    winning_rows = [x for x in perspective if x["result"] == "W" and x["odd"] is not None]
    win_odds = [x["odd"] for x in winning_rows]
    max_win_row = max(winning_rows, key=lambda x: float(x["odd"])) if winning_rows else None
    over25_odds = [x["odd"] for x in perspective if x["over25"] and x["odd"] is not None]
    winning_band = _winning_odd_band(perspective)

    biggest_wins = [
        _game_public(x)
        for x in sorted(
            [x for x in perspective if x["result"] == "W"],
            key=lambda r: (r["gd"], r["gf"], r.get("date") or ""),
            reverse=True,
        )[:10]
    ]
    biggest_losses = [
        _game_public(x)
        for x in sorted(
            [x for x in perspective if x["result"] == "L"],
            key=lambda r: (-r["gd"], r["ga"], r.get("date") or ""),
            reverse=True,
        )[:10]
    ]

    with app_engine.connect() as conn:
        maxelo = conn.execute(
            text(
                f"SELECT MAX(elo_max)::float FROM {settings.app_schema}.elo_clubes WHERE clube_id = :club"
            ),
            {"club": club_id},
        ).scalar()

    return {
        "games": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "wins_pct": pct(wins),
        "draws_pct": pct(draws),
        "losses_pct": pct(losses),
        "goals_for": gf,
        "goals_against": ga,
        "performance_pct": (pts / (3 * n) * 100 if n else 0.0),
        "ppg": _avg(points) or 0.0,
        "cv_ppg": _cv(points),
        "avg_goals_for": gf / n if n else 0.0,
        "avg_goals_against": ga / n if n else 0.0,
        "cv_goals_for": _cv(gfvals),
        "cv_goals_against": _cv(gavals),
        "avg_goal_diff": _avg(gdvals) or 0.0,
        "cv_goal_diff": _cv(gdvals),
        "over_05_pct": pct(sum(t > 0.5 for t in totals)),
        "over_15_pct": pct(sum(t > 1.5 for t in totals)),
        "over_25_pct": pct(sum(t > 2.5 for t in totals)),
        "over_35_pct": pct(sum(t > 3.5 for t in totals)),
        "btts_pct": pct(sum(x["gf"] > 0 and x["ga"] > 0 for x in perspective)),
        "avg_odd": _avg([x["odd"] for x in perspective]),
        "avg_win_odd": _avg(win_odds),
        "max_win_odd": float(max_win_row["odd"]) if max_win_row else None,
        "max_win_odd_game": _game_public(max_win_row) if max_win_row else None,
        "winning_odd_band": winning_band,
        "avg_odd_over_25": _avg(over25_odds),
        "avg_match_odds_cv": _avg([x["odds_cv"] for x in perspective]),
        "weighted_goal_diff_1": _avg(sg1vals),
        "cv_weighted_goal_diff_1": _cv(sg1vals),
        "weighted_goal_diff_2": _avg(sg2vals),
        "cv_weighted_goal_diff_2": _cv(sg2vals),
        "goal_value": _avg(gvvals),
        "cv_goal_value": _cv(gvvals),
        "cost_goal_1": _avg(cg1vals),
        "cv_cost_goal_1": _cv(cg1vals),
        "cost_goal_2": _avg(cg2vals),
        "cv_cost_goal_2": _cv(cg2vals),
        "max_elo": float(maxelo) if maxelo is not None else None,
        "has_odds": any(x["odd"] is not None for x in perspective),
        "biggest_wins": biggest_wins,
        "biggest_losses": biggest_losses,
    }


def _poisson_pmf(lam: float, goals: int):
    if lam < 0:
        return 0.0
    if lam == 0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def _prob_to_market(probability: float):
    probability = max(0.0, min(1.0, probability))
    return {
        "probability": probability,
        "percent": probability * 100,
        "odds": (1.0 / probability) if probability > 0 else None,
    }


def poisson_distribution(home_lambda: float, away_lambda: float):
    home_lambda = max(0.0, float(home_lambda))
    away_lambda = max(0.0, float(away_lambda))
    max_goals = 30

    home_win = draw = away_win = 0.0
    for h in range(max_goals + 1):
        ph = _poisson_pmf(home_lambda, h)
        for a in range(max_goals + 1):
            pa = _poisson_pmf(away_lambda, a)
            p = ph * pa
            if h > a:
                home_win += p
            elif h == a:
                draw += p
            else:
                away_win += p

    total_lambda = home_lambda + away_lambda
    over_under = []
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        cutoff = int(math.floor(line))
        under_prob = sum(_poisson_pmf(total_lambda, g) for g in range(cutoff + 1))
        over_prob = 1.0 - under_prob
        over_under.append(
            {
                "line": line,
                "over": _prob_to_market(over_prob),
                "under": _prob_to_market(under_prob),
            }
        )

    correct_score = []
    for away_goals in range(5):
        cells = []
        for home_goals in range(5):
            p = _poisson_pmf(home_lambda, home_goals) * _poisson_pmf(away_lambda, away_goals)
            cells.append(
                {
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    **_prob_to_market(p),
                }
            )
        correct_score.append({"away_goals": away_goals, "cells": cells})

    p_home_zero = _poisson_pmf(home_lambda, 0)
    p_away_zero = _poisson_pmf(away_lambda, 0)
    p_btts_yes = 1.0 - p_home_zero - p_away_zero + (p_home_zero * p_away_zero)

    return {
        "home_expectancy": home_lambda,
        "away_expectancy": away_lambda,
        "result": {
            "home": _prob_to_market(home_win),
            "draw": _prob_to_market(draw),
            "away": _prob_to_market(away_win),
        },
        "over_under": over_under,
        "correct_score": correct_score,
        "btts": {
            "yes": _prob_to_market(p_btts_yes),
            "no": _prob_to_market(1.0 - p_btts_yes),
        },
        "clean_sheet": {
            "home": {
                "yes": _prob_to_market(p_away_zero),
                "no": _prob_to_market(1.0 - p_away_zero),
            },
            "away": {
                "yes": _prob_to_market(p_home_zero),
                "no": _prob_to_market(1.0 - p_home_zero),
            },
        },
    }


def matchup(home_id: int, away_id: int, competition_id: int, season: str, period: str = "5"):
    # Para 5/10/20 jogos, a temporada selecionada funciona como data de corte:
    # usamos os jogos mais recentes até aquela temporada, inclusive.
    # Em "Temporada inteira", usamos somente a temporada selecionada.
    limit = None if period == "season" else int(period)
    exact_season = season if period == "season" else None
    cutoff = None if period == "season" else season
    home_general = calculate_club_stats(home_id, competition_id, exact_season, limit, "all", season_cutoff=cutoff)
    away_general = calculate_club_stats(away_id, competition_id, exact_season, limit, "all", season_cutoff=cutoff)
    home_venue = calculate_club_stats(home_id, competition_id, exact_season, limit, "home", season_cutoff=cutoff)
    away_venue = calculate_club_stats(away_id, competition_id, exact_season, limit, "away", season_cutoff=cutoff)

    with app_engine.connect() as conn:
        erows = conn.execute(
            text(
                f"""
                SELECT clube_id, elo_atual::float
                FROM {settings.app_schema}.elo_clubes
                WHERE campeonato_id = :competition AND temporada = :season
                  AND clube_id IN (:home, :away)
                """
            ),
            {
                "competition": competition_id,
                "season": season,
                "home": home_id,
                "away": away_id,
            },
        ).all()

    emap = {int(club): float(elo) for club, elo in erows}
    probability = None
    if home_id in emap and away_id in emap:
        denom = home_general["games"] + away_general["games"]
        draw_rate = (
            (home_general["draws"] + away_general["draws"]) / denom if denom else 0.25
        )
        probability = elo_probability(emap[home_id], emap[away_id], draw_rate)

    evolution = {}
    for cid, label in ((home_id, "home"), (away_id, "away")):
        series = elo_evolution(cid, competition_id, season, 20)
        current = series[-1]["elo"] if series else None
        deltas = {}
        for n in (5, 10, 20):
            if current is None or len(series) < 2:
                deltas[str(n)] = None
            else:
                idx = max(0, len(series) - 1 - n)
                deltas[str(n)] = round(current - series[idx]["elo"], 2)
        evolution[label] = {"series": series, "delta": deltas, "current": current}

    home_poisson_source = home_venue if home_venue["games"] else home_general
    away_poisson_source = away_venue if away_venue["games"] else away_general
    home_lambda = _avg(
        [home_poisson_source["avg_goals_for"], away_poisson_source["avg_goals_against"]]
    ) or 0.0
    away_lambda = _avg(
        [away_poisson_source["avg_goals_for"], home_poisson_source["avg_goals_against"]]
    ) or 0.0

    return {
        "general": {"home": home_general, "away": away_general},
        "venue": {"home": home_venue, "away": away_venue},
        "elo_probability": probability,
        "elo_evolution": evolution,
        "strengths": matchup_strengths(home_id, away_id, competition_id, season),
        "poisson": poisson_distribution(home_lambda, away_lambda),
        "direct_confrontation": _direct_confrontation_stats(
            home_id, away_id, competition_id, season
        ),
    }


def _direct_confrontation_stats(
    home_id: int,
    away_id: int,
    competition_id: int,
    season: str,
):
    """
    Histórico de confronto direto entre os dois clubes escolhidos.

    general:
      considera todos os confrontos entre os clubes, independentemente do mando histórico.

    venue:
      considera apenas jogos em que o clube selecionado como mandante realmente foi mandante
      e o clube selecionado como visitante realmente foi visitante.

    A temporada selecionada funciona como corte superior do histórico:
    entram jogos da temporada selecionada e das temporadas anteriores.
    """
    home_meta = _club_meta(home_id)
    away_meta = _club_meta(away_id)
    comp = _competition(competition_id)

    home_names = {normalize_name(x) for x in home_meta["names"]}
    away_names = {normalize_name(x) for x in away_meta["names"]}

    games = club_games(
        home_meta["names"],
        country=comp["pais"] if comp else home_meta["pais"],
        competition=comp["nome"] if comp else None,
        season=None,
        venue="all",
    )

    target_season_key = season_key(season)

    direct = []
    for g in games:
        gseason = str(g.get("temporada") or "")
        if gseason and season_key(gseason) > target_season_key:
            continue

        actual_home = normalize_name(g["casa"])
        actual_away = normalize_name(g["fora"])

        if not (
            (actual_home in home_names and actual_away in away_names)
            or (actual_home in away_names and actual_away in home_names)
        ):
            continue

        selected_home_is_actual_home = actual_home in home_names

        home_goals = int(
            g["gols_casa"] if selected_home_is_actual_home else g["gols_fora"]
        )
        away_goals = int(
            g["gols_fora"] if selected_home_is_actual_home else g["gols_casa"]
        )

        direct.append(
            {
                "date": str(g.get("data") or ""),
                "season": gseason,
                "selected_home_goals": home_goals,
                "selected_away_goals": away_goals,
                "same_venue": bool(selected_home_is_actual_home),
                "actual_home": g["casa"],
                "actual_away": g["fora"],
            }
        )

    # club_games já retorna do mais recente para o mais antigo.
    direct.sort(key=lambda x: x["date"], reverse=True)

    def summarize(rows):
        n = len(rows)
        home_wins = sum(
            x["selected_home_goals"] > x["selected_away_goals"] for x in rows
        )
        draws = sum(
            x["selected_home_goals"] == x["selected_away_goals"] for x in rows
        )
        away_wins = n - home_wins - draws
        goals_home = sum(x["selected_home_goals"] for x in rows)
        goals_away = sum(x["selected_away_goals"] for x in rows)
        totals = [
            x["selected_home_goals"] + x["selected_away_goals"] for x in rows
        ]

        pct = lambda count: (count / n * 100.0) if n else 0.0

        return {
            "games": n,
            "home_wins": home_wins,
            "home_wins_pct": pct(home_wins),
            "draws": draws,
            "draws_pct": pct(draws),
            "away_wins": away_wins,
            "away_wins_pct": pct(away_wins),
            "home_goals": goals_home,
            "away_goals": goals_away,
            "avg_goals": ((goals_home + goals_away) / n) if n else 0.0,
            "over_05_pct": pct(sum(t > 0.5 for t in totals)),
            "over_15_pct": pct(sum(t > 1.5 for t in totals)),
            "over_25_pct": pct(sum(t > 2.5 for t in totals)),
            "btts_pct": pct(
                sum(
                    x["selected_home_goals"] > 0
                    and x["selected_away_goals"] > 0
                    for x in rows
                )
            ),
        }

    def blocks(rows):
        return {
            "5": summarize(rows[:5]),
            "10": summarize(rows[:10]),
            "20": summarize(rows[:20]),
            "all": summarize(rows),
        }

    venue_rows = [x for x in direct if x["same_venue"]]

    return {
        "home_name": home_meta["nome"],
        "away_name": away_meta["nome"],
        "season_cutoff": season,
        "general": blocks(direct),
        "venue": blocks(venue_rows),
    }


def market_value_evolution(
    club_id: int,
    competition_id: int | None = None,
    season: str | None = None,
):
    """Season-by-season market value versus competition/system averages and sporting performance.

    League average: all market values in the same competition, season and currency.
    Global average: all registered market values in the same season and currency.
    Performance: points won / maximum possible points in that season and competition.
    Currency is kept explicit; no FX conversion is inferred.
    """
    clauses = ["vm.clube_id = :club"]
    params = {"club": club_id}
    if competition_id:
        clauses.append("vm.campeonato_id = :competition")
        params["competition"] = competition_id

    with app_engine.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT vm.temporada,
                           vm.campeonato_id,
                           c.nome AS campeonato,
                           p.nome AS pais,
                           vm.valor::float AS valor,
                           vm.moeda,
                           vm.atualizado_em,
                           (
                               SELECT AVG(vm2.valor)::float
                               FROM {settings.app_schema}.valores_mercado vm2
                               WHERE vm2.campeonato_id = vm.campeonato_id
                                 AND vm2.temporada = vm.temporada
                                 AND vm2.moeda = vm.moeda
                           ) AS media_campeonato,
                           (
                               SELECT AVG(vm3.valor)::float
                               FROM {settings.app_schema}.valores_mercado vm3
                               WHERE vm3.temporada = vm.temporada
                                 AND vm3.moeda = vm.moeda
                           ) AS media_geral
                    FROM {settings.app_schema}.valores_mercado vm
                    JOIN {settings.app_schema}.campeonatos c ON c.id = vm.campeonato_id
                    JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
                    WHERE {' AND '.join(clauses)}
                    """
                ),
                params,
            ).mappings()
        ]

    rows.sort(key=lambda r: (season_key(str(r["temporada"])), str(r["campeonato"])))
    if season:
        cutoff = season_key(season)
        rows = [r for r in rows if season_key(str(r["temporada"])) <= cutoff]

    # Uma única leitura do histórico do clube é suficiente para calcular todas as temporadas.
    meta = _club_meta(club_id)
    history = club_games(meta["names"], country=meta["pais"], competition=None, season=None, venue="all")
    own = {normalize_name(x) for x in meta["names"]}
    perf = {}
    for game in history:
        key = (str(game.get("temporada") or ""), str(game.get("campeonato") or ""))
        is_home = normalize_name(game.get("casa") or "") in own
        gf = int(game["gols_casa"] if is_home else game["gols_fora"])
        ga = int(game["gols_fora"] if is_home else game["gols_casa"])
        bucket = perf.setdefault(key, {"games": 0, "points": 0})
        bucket["games"] += 1
        bucket["points"] += 3 if gf > ga else 1 if gf == ga else 0

    currencies = sorted({str(r.get("moeda") or "") for r in rows if r.get("moeda")})
    multi_comp = len({r["campeonato_id"] for r in rows}) > 1
    for row in rows:
        row["label"] = str(row["temporada"])
        if multi_comp:
            row["label"] += f" · {row['campeonato']}"
        bucket = perf.get((str(row["temporada"]), str(row["campeonato"])))
        if bucket and bucket["games"]:
            row["aproveitamento"] = round(bucket["points"] / (bucket["games"] * 3) * 100, 2)
            row["jogos_aproveitamento"] = bucket["games"]
        else:
            row["aproveitamento"] = None
            row["jogos_aproveitamento"] = 0

    return {
        "rows": rows,
        "currencies": currencies,
        "mixed_currencies": len(currencies) > 1,
        "comparison_rule": "Médias na mesma temporada/moeda. Aproveitamento = pontos conquistados ÷ pontos possíveis.",
    }
