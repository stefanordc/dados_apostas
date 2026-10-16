import re
import time
from functools import lru_cache

from sqlalchemy import text
from ..config import settings
from ..db import history_connection


def _table():
    return f"{settings.history_schema}.{settings.history_table}"


def _cache_bucket():
    return int(time.time() // 300)


def _normalize_season(value) -> str:
    """Padroniza temporada para YYYY/YYYY."""
    if value is None:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    raw = raw.replace("-", "/")

    m = re.fullmatch(r"(\d{4})/(\d{4})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    m = re.fullmatch(r"(\d{4})/(\d{2})", raw)
    if m:
        start = int(m.group(1))
        end2 = int(m.group(2))
        century = (start // 100) * 100
        end = century + end2
        if end < start:
            end += 100
        return f"{start:04d}/{end:04d}"

    m = re.fullmatch(r"(\d{4})", raw)
    if m:
        start = int(m.group(1))
        return f"{start:04d}/{start + 1:04d}"

    return raw


def _season_sort_key(value: str):
    normalized = _normalize_season(value)
    m = re.fullmatch(r"(\d{4})/(\d{4})", normalized)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (-1, -1)


def _season_candidates(value: str) -> list[str]:
    """
    Aceita no banco as variações antigas, mas expõe ao frontend só YYYY/YYYY.
    Ex.: 2026/2027 também encontra 2026/27, 2026-2027, 2026-27 e 2026.
    """
    normalized = _normalize_season(value)
    m = re.fullmatch(r"(\d{4})/(\d{4})", normalized)
    if not m:
        return [str(value).strip()]

    start = m.group(1)
    end = m.group(2)
    short_end = end[-2:]

    return list(dict.fromkeys([
        f"{start}/{end}",
        f"{start}/{short_end}",
        f"{start}-{end}",
        f"{start}-{short_end}",
        start,
    ]))


def _season_filter_clause(value: str, prefix: str = "season"):
    candidates = _season_candidates(value)
    clauses = []
    params = {}
    for idx, candidate in enumerate(candidates):
        key = f"{prefix}_{idx}"
        clauses.append(f"temporada::text = :{key}")
        params[key] = candidate
    return "(" + " OR ".join(clauses) + ")", params


def _base_filters(filters: dict, skip: str | None = None):
    clauses, params = [], {}
    def add(key, sql, value):
        if skip != key and value not in (None, "", []):
            clauses.append(sql); params[key] = value
    add("country", "pais = :country", filters.get("country"))
    season = filters.get("season")
    if skip != "season" and season not in (None, "", []):
        season_clause, season_params = _season_filter_clause(str(season), "season")
        clauses.append(season_clause)
        params.update(season_params)
    add("competition", "campeonato = :competition", filters.get("competition"))
    add("round", "rodada::text = :round", filters.get("round"))
    add("home", "casa = :home", filters.get("home"))
    add("away", "fora = :away", filters.get("away"))
    club = filters.get("club")
    if skip != "club" and club:
        clauses.append("(casa = :club OR fora = :club)"); params["club"] = club
    winner = filters.get("winner")
    if skip != "winner" and winner:
        clauses.append("((casa = :winner AND gols_casa > gols_fora) OR (fora = :winner AND gols_fora > gols_casa))")
        params["winner"] = winner
    home_win = filters.get("home_win")
    if skip != "home_win" and home_win == "sim": clauses.append("gols_casa > gols_fora")
    elif skip != "home_win" and home_win == "nao": clauses.append("gols_casa <= gols_fora")
    away_win = filters.get("away_win")
    if skip != "away_win" and away_win == "sim": clauses.append("gols_fora > gols_casa")
    elif skip != "away_win" and away_win == "nao": clauses.append("gols_fora <= gols_casa")
    for key, col in [("home_goals_min","gols_casa"),("home_goals_max","gols_casa"),("away_goals_min","gols_fora"),("away_goals_max","gols_fora")]:
        val = filters.get(key)
        if skip != key and val is not None:
            clauses.append(f"{col} {'>=' if key.endswith('_min') else '<='} :{key}"); params[key] = val
    for key, op in [("goal_diff_min",">="),("goal_diff_max","<=")]:
        val = filters.get(key)
        if skip != key and val is not None:
            clauses.append(f"ABS(gols_casa - gols_fora) {op} :{key}"); params[key] = val
    return clauses, params


def _distinct_scalar(expr: str, filters: dict, skip: str):
    clauses, params = _base_filters(filters, skip=skip)
    clauses.append(f"{expr} IS NOT NULL")
    with history_connection() as conn:
        return [r.value for r in conn.execute(text(f"SELECT DISTINCT {expr} AS value FROM {_table()} WHERE {' AND '.join(clauses)} ORDER BY value"), params) if r.value is not None]


def options(filters: dict):
    clauses, params = _base_filters(filters)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with history_connection() as conn:
        clubs = [r.value for r in conn.execute(text(f"""
            SELECT DISTINCT clube AS value FROM (
                SELECT casa AS clube FROM {_table()} {where}
                UNION SELECT fora AS clube FROM {_table()} {where}
            ) x WHERE clube IS NOT NULL ORDER BY value
        """), params)]
        winners = [r.value for r in conn.execute(text(f"""
            SELECT DISTINCT vencedor AS value FROM (
                SELECT CASE WHEN gols_casa > gols_fora THEN casa WHEN gols_fora > gols_casa THEN fora END AS vencedor
                FROM {_table()} {where}
            ) x WHERE vencedor IS NOT NULL ORDER BY value
        """), params)]
    return {
        "countries": _distinct_scalar("pais", filters, "country"),
        "seasons": sorted(
            {
                _normalize_season(x)
                for x in _distinct_scalar("temporada", filters, "season")
                if _normalize_season(x)
            },
            key=_season_sort_key,
            reverse=True,
        ),
        "competitions": _distinct_scalar("campeonato", filters, "competition"),
        "rounds": [str(x) for x in _distinct_scalar("rodada", filters, "round")],
        "home_teams": _distinct_scalar("casa", filters, "home"),
        "away_teams": _distinct_scalar("fora", filters, "away"),
        "clubs": clubs, "winners": winners,
    }


def search(filters: dict, page: int = 1, page_size: int = 50):
    clauses, params = _base_filters(filters)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    offset = (page - 1) * page_size
    data_sql = f"""
        SELECT id, jogo_id, data, temporada, campeonato, pais, rodada,
               id_casa, casa, gols_casa, gols_fora, fora, id_fora,
               ABS(gols_casa - gols_fora) AS saldo_gols,
               CASE WHEN gols_casa > gols_fora THEN casa WHEN gols_fora > gols_casa THEN fora ELSE 'Empate' END AS vencedor
        FROM {_table()} {where}
        ORDER BY data DESC NULLS LAST, id DESC LIMIT :limit OFFSET :offset
    """
    stats_sql = f"""
        SELECT COUNT(*)::int AS total_jogos,
               SUM(CASE WHEN gols_casa > gols_fora THEN 1 ELSE 0 END)::int AS vitorias_casa,
               SUM(CASE WHEN gols_fora > gols_casa THEN 1 ELSE 0 END)::int AS vitorias_fora,
               SUM(CASE WHEN gols_casa = gols_fora THEN 1 ELSE 0 END)::int AS empates,
               COALESCE(SUM(gols_casa),0)::int AS gols_casa,
               COALESCE(SUM(gols_fora),0)::int AS gols_fora,
               COALESCE(AVG(gols_casa),0)::float AS media_gols_casa,
               COALESCE(AVG(gols_fora),0)::float AS media_gols_fora,
               COALESCE(AVG(gols_casa + gols_fora),0)::float AS media_geral_gols
        FROM {_table()} {where}
    """
    with history_connection() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {_table()} {where}"), params).scalar_one()
        rows = [dict(r._mapping) for r in conn.execute(text(data_sql), {**params,"limit":page_size,"offset":offset})]
        stats = dict(conn.execute(text(stats_sql), params).mappings().one())
    n = stats["total_jogos"] or 0
    stats["percentual_vitorias_casa"] = round(stats["vitorias_casa"] / n * 100, 2) if n else 0
    stats["percentual_empates"] = round(stats["empates"] / n * 100, 2) if n else 0
    stats["percentual_vitorias_fora"] = round(stats["vitorias_fora"] / n * 100, 2) if n else 0
    stats["total_gols"] = stats["gols_casa"] + stats["gols_fora"]
    for row in rows:
        if row.get("data") is not None:
            row["data"] = str(row["data"])
        if row.get("temporada") is not None:
            row["temporada"] = _normalize_season(row["temporada"])
    return {"total": total, "page": page, "page_size": page_size, "stats": stats, "rows": rows}


@lru_cache(maxsize=256)
def _competition_games_cached(country: str, competition: str, season: str, bucket: int):
    season_clause, season_params = _season_filter_clause(season, "competition_season")
    with history_connection() as conn:
        rows = conn.execute(text(f"""
            SELECT id, jogo_id, data, rodada, casa, fora, gols_casa, gols_fora
            FROM {_table()}
            WHERE pais = :country AND campeonato = :competition AND {season_clause}
              AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
            ORDER BY data ASC NULLS LAST, id ASC
        """), {"country": country, "competition": competition, **season_params}).mappings().all()
    return tuple(dict(r) for r in rows)


def competition_games(country: str, competition: str, season: str):
    return [dict(r) for r in _competition_games_cached(country, competition, season, _cache_bucket())]


@lru_cache(maxsize=1024)
def _club_games_cached(names: tuple[str, ...], country: str | None, competition: str | None, season: str | None, venue: str, bucket: int):
    if not names: return tuple()
    params = {}
    home_parts=[]; away_parts=[]
    for i,name in enumerate(names):
        params[f"n{i}"] = name
        home_parts.append(f"casa = :n{i}")
        away_parts.append(f"fora = :n{i}")
    if venue == "home": club_clause = "(" + " OR ".join(home_parts) + ")"
    elif venue == "away": club_clause = "(" + " OR ".join(away_parts) + ")"
    else: club_clause = "((" + " OR ".join(home_parts) + ") OR (" + " OR ".join(away_parts) + "))"
    clauses=[club_clause]
    if country: clauses.append("pais = :country"); params["country"]=country
    if competition: clauses.append("campeonato = :competition"); params["competition"]=competition
    if season:
        season_clause, season_params = _season_filter_clause(season, "club_season")
        clauses.append(season_clause); params.update(season_params)
    with history_connection() as conn:
        rows = conn.execute(text(f"""
            SELECT id, jogo_id, data, temporada, campeonato, pais, rodada, casa, fora, gols_casa, gols_fora
            FROM {_table()}
            WHERE {' AND '.join(clauses)} AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
            ORDER BY data DESC NULLS LAST, id DESC
        """), params).mappings().all()
    return tuple(dict(r) for r in rows)


def club_games(names: list[str], country: str | None = None, competition: str | None = None,
               season: str | None = None, venue: str = "all"):
    return [dict(r) for r in _club_games_cached(tuple(names), country, competition, season, venue, _cache_bucket())]
