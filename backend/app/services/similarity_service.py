import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from .elo_service import normalize_name

MARKET_LABELS = {
    "home_win": "Vitória do mandante",
    "away_win": "Vitória do visitante",
    "over_15": "Over 1,5",
    "over_25": "Over 2,5",
    "btts": "Ambos marcam",
}


def _parse_cutoff(value: str | None):
    if not value:
        return date.today()
    raw = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError("Data limite inválida. Use dd/mm/aaaa.")


def _club_name_map(club_ids):
    club_ids = sorted({int(x) for x in club_ids})
    if not club_ids:
        return {}
    params = {f"id{i}": club_id for i, club_id in enumerate(club_ids)}
    placeholders = ", ".join(f":id{i}" for i in range(len(club_ids)))
    with app_engine.connect() as conn:
        clubs = conn.execute(
            text(
                f"""
                SELECT id, nome
                FROM {settings.app_schema}.clubes
                WHERE id IN ({placeholders})
                """
            ),
            params,
        ).mappings().all()
        aliases = conn.execute(
            text(
                f"""
                SELECT clube_id, alias
                FROM {settings.app_schema}.clubes_aliases
                WHERE clube_id IN ({placeholders})
                """
            ),
            params,
        ).mappings().all()

    out = defaultdict(set)
    for row in clubs:
        out[int(row["id"])].add(normalize_name(row["nome"]))
    for row in aliases:
        out[int(row["clube_id"])].add(normalize_name(row["alias"]))
    return out


def _candidate_rows(home_odd: float, draw_odd: float, away_odd: float, cutoff: date, tolerance_pct: float):
    tolerance = float(tolerance_pct) / 100.0
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    o.id,
                    o.data,
                    o.campeonato_id,
                    o.temporada,
                    o.clube_casa_id,
                    o.clube_fora_id,
                    o.mandante_origem,
                    o.visitante_origem,
                    o.odd_casa::float,
                    o.odd_empate::float,
                    o.odd_fora::float,
                    c.nome AS campeonato,
                    p.nome AS pais,
                    hc.nome AS mandante,
                    ac.nome AS visitante,
                    SQRT(
                        POWER(LN(o.odd_casa::float / :home_odd), 2) +
                        POWER(LN(o.odd_empate::float / :draw_odd), 2) +
                        POWER(LN(o.odd_fora::float / :away_odd), 2)
                    ) AS distance
                FROM {settings.app_schema}.odds_jogos o
                JOIN {settings.app_schema}.campeonatos c ON c.id = o.campeonato_id
                JOIN {settings.app_schema}.paises p ON p.id = o.pais_id
                JOIN {settings.app_schema}.clubes hc ON hc.id = o.clube_casa_id
                JOIN {settings.app_schema}.clubes ac ON ac.id = o.clube_fora_id
                WHERE o.data IS NOT NULL
                  AND o.data < :cutoff
                  AND o.odd_casa > 1.001
                  AND o.odd_empate > 1.001
                  AND o.odd_fora > 1.001
                  AND o.odd_casa BETWEEN :home_low AND :home_high
                  AND o.odd_empate BETWEEN :draw_low AND :draw_high
                  AND o.odd_fora BETWEEN :away_low AND :away_high
                ORDER BY distance ASC
                LIMIT 5000
                """
            ),
            {
                "home_odd": home_odd,
                "draw_odd": draw_odd,
                "away_odd": away_odd,
                "home_low": home_odd * (1.0 - tolerance),
                "home_high": home_odd * (1.0 + tolerance),
                "draw_low": draw_odd * (1.0 - tolerance),
                "draw_high": draw_odd * (1.0 + tolerance),
                "away_low": away_odd * (1.0 - tolerance),
                "away_high": away_odd * (1.0 + tolerance),
                "cutoff": cutoff,
            },
        ).mappings().all()

    result = []
    for row in rows:
        d = dict(row)
        d["max_relative_diff"] = max(
            abs(float(d["odd_casa"]) / home_odd - 1),
            abs(float(d["odd_empate"]) / draw_odd - 1),
            abs(float(d["odd_fora"]) / away_odd - 1),
        )
        if d["max_relative_diff"] <= tolerance + 1e-12:
            result.append(d)
    return result


def _history_map(candidates, cutoff: date):
    if not candidates:
        return {}
    min_date = min(row["data"] for row in candidates if row.get("data"))
    with history_connection() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT data, casa, fora, gols_casa, gols_fora
                FROM {settings.history_schema}.{settings.history_table}
                WHERE data >= :min_date AND data < :cutoff
                  AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
                """
            ),
            {"min_date": min_date, "cutoff": cutoff},
        ).mappings().all()

    out = {}
    for row in rows:
        key = (str(row["data"]), normalize_name(row["casa"]), normalize_name(row["fora"]))
        out[key] = {"gols_casa": int(row["gols_casa"]), "gols_fora": int(row["gols_fora"])}
    return out


def _attach_results(candidates):
    if not candidates:
        return []
    club_ids = []
    for row in candidates:
        club_ids.extend([row["clube_casa_id"], row["clube_fora_id"]])
    names = _club_name_map(club_ids)
    upper = max(row["data"] for row in candidates)
    history = _history_map(candidates, upper + timedelta(days=1))

    matched = []
    for row in candidates:
        home_names = set(names.get(int(row["clube_casa_id"]), set()))
        away_names = set(names.get(int(row["clube_fora_id"]), set()))
        home_names.add(normalize_name(row.get("mandante_origem") or ""))
        away_names.add(normalize_name(row.get("visitante_origem") or ""))
        home_names.add(normalize_name(row.get("mandante") or ""))
        away_names.add(normalize_name(row.get("visitante") or ""))

        result = None
        match_date = str(row["data"])
        for home_name in home_names:
            if not home_name:
                continue
            for away_name in away_names:
                if not away_name:
                    continue
                result = history.get((match_date, home_name, away_name))
                if result:
                    break
            if result:
                break
        if not result:
            continue

        item = dict(row)
        item.update(result)
        gh, ga = item["gols_casa"], item["gols_fora"]
        item["outcome"] = "home" if gh > ga else "away" if ga > gh else "draw"
        item["over_15"] = gh + ga > 1.5
        item["over_25"] = gh + ga > 2.5
        item["btts"] = gh > 0 and ga > 0
        if float(item["odd_casa"]) < float(item["odd_fora"]):
            item["favorite_side"] = "home"
        elif float(item["odd_fora"]) < float(item["odd_casa"]):
            item["favorite_side"] = "away"
        else:
            item["favorite_side"] = None
        item["favorite_won"] = item["favorite_side"] == item["outcome"]
        item["underdog_won"] = (
            item["favorite_side"] is not None
            and item["outcome"] in {"home", "away"}
            and item["favorite_side"] != item["outcome"]
        )
        matched.append(item)
    return matched


def _success(row, market: str):
    if market == "home_win": return row["outcome"] == "home"
    if market == "away_win": return row["outcome"] == "away"
    if market == "over_15": return bool(row["over_15"])
    if market == "over_25": return bool(row["over_25"])
    if market == "btts": return bool(row["btts"])
    return False


def _market_odd(market, home_odd, away_odd, market_odds):
    if market == "home_win": return home_odd
    if market == "away_win": return away_odd
    value = market_odds.get(market)
    if value is None:
        raise ValueError(f"Informe a odd de {MARKET_LABELS.get(market, market)}.")
    return float(value)


def _summary(sample):
    n = len(sample)
    if not n:
        return {
            "games": 0, "home_win_pct": 0, "draw_pct": 0, "away_win_pct": 0,
            "favorite_win_pct": 0, "underdog_win_pct": 0, "avg_home_goals": 0,
            "avg_away_goals": 0, "avg_total_goals": 0, "over_15_pct": 0,
            "over_25_pct": 0, "btts_pct": 0,
        }
    pct = lambda count: count / n * 100
    return {
        "games": n,
        "home_win_pct": pct(sum(x["outcome"] == "home" for x in sample)),
        "draw_pct": pct(sum(x["outcome"] == "draw" for x in sample)),
        "away_win_pct": pct(sum(x["outcome"] == "away" for x in sample)),
        "favorite_win_pct": pct(sum(bool(x.get("favorite_won")) for x in sample)),
        "underdog_win_pct": pct(sum(bool(x.get("underdog_won")) for x in sample)),
        "avg_home_goals": sum(x["gols_casa"] for x in sample) / n,
        "avg_away_goals": sum(x["gols_fora"] for x in sample) / n,
        "avg_total_goals": sum(x["gols_casa"] + x["gols_fora"] for x in sample) / n,
        "over_15_pct": pct(sum(bool(x["over_15"]) for x in sample)),
        "over_25_pct": pct(sum(bool(x["over_25"]) for x in sample)),
        "btts_pct": pct(sum(bool(x["btts"]) for x in sample)),
    }


def _ev_block(sample, markets, home_odd, away_odd, market_odds):
    rows = []
    groups = defaultdict(list)
    for item in sample:
        groups[int(item["data"].year)].append(item)

    def calculate(label, games):
        values = {}
        for market in markets:
            odd = _market_odd(market, home_odd, away_odd, market_odds)
            hits = sum(_success(g, market) for g in games)
            p = hits / len(games) if games else 0.0
            values[market] = {
                "label": MARKET_LABELS[market], "games": len(games), "hits": hits,
                "hit_rate": p * 100, "odd": odd, "ev_pct": (p * odd - 1.0) * 100,
            }
        return {"period": label, "games": len(games), "markets": values}

    for year in sorted(groups):
        rows.append(calculate(str(year), groups[year]))
    return rows, calculate("Geral", sample)


def _current_elo_difference(home_id: int, away_id: int, competition_id: int, season: str):
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT clube_id, elo_atual::float AS elo
                FROM {settings.app_schema}.elo_clubes
                WHERE campeonato_id = :competition
                  AND temporada = :season
                  AND clube_id IN (:home_id, :away_id)
                """
            ),
            {"competition": competition_id, "season": season, "home_id": home_id, "away_id": away_id},
        ).mappings().all()
    values = {int(r["clube_id"]): float(r["elo"]) for r in rows}
    if home_id not in values or away_id not in values:
        return None
    return {
        "home_elo": values[home_id],
        "away_elo": values[away_id],
        "difference": values[home_id] - values[away_id],
    }


def _elo_similar_games(
    home_id: int,
    away_id: int,
    competition_id: int,
    season: str,
    cutoff: date,
    tolerance_points: float,
    markets: list[str],
    home_odd: float,
    away_odd: float,
    market_odds: dict[str, float],
):
    target = _current_elo_difference(home_id, away_id, competition_id, season)
    if not target:
        return {
            "available": False,
            "message": "O confronto ainda não possui ELO calculado para os dois clubes.",
            "target_difference": None,
            "tolerance_points": float(tolerance_points),
            "sample_size": 0,
            "summary": _summary([]),
            "ev_yearly": [],
            "ev_overall": None,
            "games": [],
        }

    target_diff = float(target["difference"])
    tolerance = float(tolerance_points)
    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            text(
                f"""
                SELECT
                    em.data,
                    em.temporada,
                    c.nome AS campeonato,
                    p.nome AS pais,
                    hc.nome AS mandante,
                    ac.nome AS visitante,
                    em.gols_casa,
                    em.gols_fora,
                    em.elo_casa_antes::float AS elo_casa,
                    em.elo_fora_antes::float AS elo_fora,
                    (em.elo_casa_antes - em.elo_fora_antes)::float AS elo_diff,
                    ABS((em.elo_casa_antes - em.elo_fora_antes)::float - :target_diff) AS elo_distance
                FROM {settings.app_schema}.elo_movimentos em
                JOIN {settings.app_schema}.campeonatos c ON c.id = em.campeonato_id
                JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
                JOIN {settings.app_schema}.clubes hc ON hc.id = em.casa_clube_id
                JOIN {settings.app_schema}.clubes ac ON ac.id = em.fora_clube_id
                WHERE em.data IS NOT NULL
                  AND em.data < :cutoff
                  AND ABS((em.elo_casa_antes - em.elo_fora_antes)::float - :target_diff) <= :tolerance
                ORDER BY elo_distance ASC, em.data DESC
                LIMIT 500
                """
            ),
            {"target_diff": target_diff, "tolerance": tolerance, "cutoff": cutoff},
        ).mappings()]

    normalized = []
    for row in rows:
        gh, ga = int(row["gols_casa"]), int(row["gols_fora"])
        item = dict(row)
        item["outcome"] = "home" if gh > ga else "away" if ga > gh else "draw"
        item["over_15"] = gh + ga > 1.5
        item["over_25"] = gh + ga > 2.5
        item["btts"] = gh > 0 and ga > 0
        normalized.append(item)

    elo_ev_yearly, elo_ev_overall = _ev_block(
        normalized,
        markets,
        float(home_odd),
        float(away_odd),
        {k: float(v) for k, v in (market_odds or {}).items()},
    )

    examples = [
        {
            "date": str(x["data"]),
            "country": x["pais"],
            "competition": x["campeonato"],
            "season": x["temporada"],
            "home": x["mandante"],
            "away": x["visitante"],
            "score": f"{x['gols_casa']}–{x['gols_fora']}",
            "home_elo": x["elo_casa"],
            "away_elo": x["elo_fora"],
            "elo_difference": x["elo_diff"],
            "distance_points": x["elo_distance"],
        }
        for x in normalized[:30]
    ]

    return {
        "available": True,
        "message": None if normalized else "Nenhum jogo histórico ficou dentro da faixa de ELO informada.",
        "current_home_elo": target["home_elo"],
        "current_away_elo": target["away_elo"],
        "target_difference": target_diff,
        "tolerance_points": tolerance,
        "sample_size": len(normalized),
        "summary": _summary(normalized),
        "ev_yearly": elo_ev_yearly,
        "ev_overall": elo_ev_overall,
        "games": examples,
    }


def analyze_similar_games(
    home_id: int,
    away_id: int,
    competition_id: int,
    season: str,
    home_odd: float,
    draw_odd: float,
    away_odd: float,
    selected_markets: list[str],
    market_odds: dict[str, float],
    cutoff_date: str | None = None,
    odds_tolerance_pct: float = 10.0,
    elo_tolerance_points: float = 50.0,
):
    for value, label in ((home_odd, "odd do mandante"), (draw_odd, "odd do empate"), (away_odd, "odd do visitante")):
        if value is None or float(value) <= 1.0:
            raise ValueError(f"Informe uma {label} válida, maior que 1,00.")

    tolerance_pct = float(odds_tolerance_pct)
    if tolerance_pct < 1 or tolerance_pct > 50:
        raise ValueError("A faixa relativa das odds deve ficar entre 1% e 50%.")
    elo_tolerance = float(elo_tolerance_points)
    if elo_tolerance < 5 or elo_tolerance > 400:
        raise ValueError("A faixa de ELO deve ficar entre 5 e 400 pontos.")

    markets = [m for m in selected_markets if m in MARKET_LABELS]
    if not markets:
        raise ValueError("Selecione pelo menos um mercado para calcular o EV.")
    for market in markets:
        odd = _market_odd(market, float(home_odd), float(away_odd), market_odds)
        if odd <= 1.0:
            raise ValueError(f"A odd de {MARKET_LABELS[market]} deve ser maior que 1,00.")

    cutoff = _parse_cutoff(cutoff_date)
    candidates = _candidate_rows(float(home_odd), float(draw_odd), float(away_odd), cutoff, tolerance_pct)
    matched = _attach_results(candidates) if candidates else []
    matched.sort(key=lambda x: float(x["distance"]))
    sample = matched[:300]

    summary = _summary(sample)
    yearly, overall = _ev_block(
        sample, markets, float(home_odd), float(away_odd),
        {k: float(v) for k, v in (market_odds or {}).items()},
    )

    examples = [
        {
            "date": str(x["data"]), "country": x["pais"], "competition": x["campeonato"],
            "season": x["temporada"], "home": x["mandante"], "away": x["visitante"],
            "score": f"{x['gols_casa']}–{x['gols_fora']}", "home_odd": x["odd_casa"],
            "draw_odd": x["odd_empate"], "away_odd": x["odd_fora"],
            "max_relative_diff_pct": float(x["max_relative_diff"]) * 100,
        }
        for x in sample[:30]
    ]

    elo_similarity = _elo_similar_games(
        home_id,
        away_id,
        competition_id,
        season,
        cutoff,
        elo_tolerance,
        markets,
        float(home_odd),
        float(away_odd),
        {k: float(v) for k, v in (market_odds or {}).items()},
    )

    message = None
    if not sample:
        message = "Nenhum jogo com odds 1X2 ficou dentro da faixa relativa informada. Aumente a faixa se quiser ampliar a amostra."

    return {
        "cutoff_date": cutoff.isoformat(),
        "sample_size": len(sample),
        "matched_available": len(matched),
        "tolerance_pct": tolerance_pct,
        "summary": summary,
        "ev_yearly": yearly,
        "ev_overall": overall,
        "market_labels": {m: MARKET_LABELS[m] for m in markets},
        "similar_games": examples,
        "elo_similarity": elo_similarity,
        "message": message,
        "method": "Historical 1X2 prices filtered by the exact user-defined relative band. ELO similarity uses the signed pre-match difference ELO_home - ELO_away and a user-defined point tolerance.",
    }
