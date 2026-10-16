import math
import time
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection


TABLE_DEFS = {
    "assistencias": {
        "label": "Assistências",
        "tables": ["assistencias"],
        "metric": ["assistencias", "assistencia", "assists", "ast", "total_assistencias", "qtd_assistencias"],
    },
    "minutos": {
        "label": "Minutos",
        "tables": ["minutos"],
        "metric": ["minutos", "minutes", "min", "minutos_jogados", "minutagem", "tempo_jogado"],
    },
    "gols_marcados": {
        "label": "Gols Marcados",
        "tables": ["gols_marcados"],
        "metric": ["gols_marcados", "gols", "goals", "gls", "total_gols", "qtd_gols"],
    },
    "gols_sofridos": {
        "label": "Gols Sofridos",
        "tables": ["gols_sofridos"],
        "metric": ["gols_sofridos", "goals_conceded", "conceded", "ga", "gols", "total_gols_sofridos"],
    },
    "disciplina": {
        "label": "Disciplina",
        "tables": ["disciplina"],
        "metric": ["disciplina", "disciplinary_points", "cartoes", "cartoes_total", "total_cartoes"],
    },
    "hat_tricks": {
        "label": "Hat-tricks",
        "tables": ["hat_tricks", "hat_trick"],
        "metric": ["hat_tricks", "hat_trick", "hattricks", "total_hat_tricks"],
    },
}

PLAYER_ID_ALIASES = ["jogador_id", "id_jogador", "player_id", "id_player", "atleta_id", "id_atleta", "playerid"]
NAME_ALIASES = ["jogador", "nome_jogador", "nome", "player", "player_name", "atleta", "nome_atleta", "nome_player"]
PHOTO_ALIASES = ["foto", "foto_url", "url_foto", "photo", "photo_url", "imagem", "imagem_url", "url_imagem", "foto_jogador"]
POSITION_ALIASES = ["posicao", "posição", "position", "pos", "funcao", "função", "posicao_jogador", "posição_jogador"]
NATIONALITY_ALIASES = ["nacionalidade", "nationality", "nation", "pais_jogador", "país_jogador", "pais_nascimento", "país_nascimento", "nacionalidade_jogador"]
CLUB_ALIASES = ["clube", "club", "time", "team", "equipe", "nome_clube", "squad", "clube_atual", "nome_time"]
SEASON_ALIASES = ["temporada", "season", "epoca", "época", "ano"]
COMPETITION_ALIASES = ["campeonato", "competicao", "competição", "competition", "league", "liga"]

YELLOW_ALIASES = ["amarelos", "cartoes_amarelos", "cartões_amarelos", "yellow_cards", "amarelo", "crdy"]
SECOND_YELLOW_ALIASES = ["segundo_amarelo", "segundos_amarelos", "second_yellow", "second_yellow_cards"]
RED_ALIASES = ["vermelhos", "cartoes_vermelhos", "cartões_vermelhos", "red_cards", "vermelho", "crdr"]
HAT_COMPONENT_ALIASES = [
    "3_gols", "tres_gols", "três_gols", "4_gols", "quatro_gols",
    "5_mais_gols", "5mais_gols", "5_ou_mais_gols", "5+_gols",
]

HAT_RANKING_DEFS = {
    "dobletes": {
        "label": "Dobletes",
        "aliases": ["dobletes", "doblete", "doubles", "braces", "2_gols", "dois_gols", "dois_golos"],
    },
    "hat_tricks": {
        "label": "Hat-Tricks",
        "aliases": ["hat_tricks", "hat_trick", "hattricks", "3_gols", "tres_gols", "três_gols"],
    },
    "poker_tricks": {
        "label": "Poker Tricks",
        "aliases": ["poker_tricks", "poker_trick", "poker", "4_gols", "quatro_gols"],
    },
    "cinco_mais_gols": {
        "label": "5 ou mais gols",
        "aliases": ["5_mais_gols", "5mais_gols", "5_ou_mais_gols", "5+_gols", "cinco_mais_gols", "cinco_ou_mais_gols"],
    },
}

NUMERIC_TYPES = {
    "smallint", "integer", "bigint", "decimal", "numeric", "real", "double precision",
    "smallserial", "serial", "bigserial",
}


def _bucket(seconds: int = 300) -> int:
    return int(time.time() // seconds)


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in value:
        value = value.replace("__", "_")
    return value


def _q(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _pick(columns: dict[str, dict], aliases: list[str]) -> str | None:
    by_norm = {_norm(name): name for name in columns}
    for alias in aliases:
        if _norm(alias) in by_norm:
            return by_norm[_norm(alias)]
    return None


def _json_value(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_value(x) for x in value]
    return value


def _source_connect(source: str):
    return history_connection() if source == "history" else app_engine.connect()


def _schemas_for(source: str) -> list[str]:
    if source == "history":
        return list(dict.fromkeys([settings.history_schema, "public"]))
    return list(dict.fromkeys([settings.app_schema, "public"]))


def _table_exists(source: str, schema: str, table: str) -> bool:
    with _source_connect(source) as conn:
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = :schema AND LOWER(table_name) = LOWER(:table)
                LIMIT 1
                """
            ),
            {"schema": schema, "table": table},
        ).first()
    return bool(row)


def _column_info(source: str, schema: str, table: str) -> dict[str, dict]:
    with _source_connect(source) as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name, data_type, udt_name, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :table
                ORDER BY ordinal_position
                """
            ),
            {"schema": schema, "table": table},
        ).mappings().all()
    return {r["column_name"]: dict(r) for r in rows}


def _numeric_expr(column: str, info: dict | None = None) -> str:
    col = _q(column)
    data_type = (info or {}).get("data_type", "")
    if data_type in NUMERIC_TYPES:
        return f"COALESCE({col}::numeric, 0)"
    return (
        "COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(" + col + "::text, '[^0-9,.-]', '', 'g'), ',', '.'), '')::numeric, 0)"
    )


def _metric_parts(logical: str, columns: dict[str, dict]) -> list[tuple[str, float]]:
    direct = _pick(columns, TABLE_DEFS[logical]["metric"])
    if direct:
        return [(direct, 1.0)]

    if logical == "disciplina":
        found = []
        for aliases in (YELLOW_ALIASES, SECOND_YELLOW_ALIASES, RED_ALIASES):
            col = _pick(columns, aliases)
            if col and col not in [x[0] for x in found]:
                found.append((col, 1.0))
        return found

    if logical == "hat_tricks":
        found = []
        by_norm = {_norm(c): c for c in columns}
        for alias in HAT_COMPONENT_ALIASES:
            actual = by_norm.get(_norm(alias))
            if actual and actual not in [x[0] for x in found]:
                found.append((actual, 1.0))
        return found
    return []


@lru_cache(maxsize=32)
def _discover_sources_cached(bucket: int):
    found = {}
    for logical, definition in TABLE_DEFS.items():
        resolved = None
        # O banco histórico é preferido: estas tabelas são analíticas e permanecem somente leitura.
        for source in ("history", "app"):
            for schema in _schemas_for(source):
                for table in definition["tables"]:
                    if not _table_exists(source, schema, table):
                        continue
                    columns = _column_info(source, schema, table)
                    player_id = _pick(columns, PLAYER_ID_ALIASES)
                    if not player_id:
                        continue
                    metric_parts = _metric_parts(logical, columns)
                    if not metric_parts:
                        continue
                    resolved = {
                        "logical": logical,
                        "label": definition["label"],
                        "source": source,
                        "schema": schema,
                        "table": table,
                        "columns": columns,
                        "player_id": player_id,
                        "name": _pick(columns, NAME_ALIASES),
                        "photo": _pick(columns, PHOTO_ALIASES),
                        "position": _pick(columns, POSITION_ALIASES),
                        "nationality": _pick(columns, NATIONALITY_ALIASES),
                        "club": _pick(columns, CLUB_ALIASES),
                        "season": _pick(columns, SEASON_ALIASES),
                        "competition": _pick(columns, COMPETITION_ALIASES),
                        "metric_parts": metric_parts,
                    }
                    break
                if resolved:
                    break
            if resolved:
                break
        if resolved:
            found[logical] = resolved
    return found


def discover_sources():
    return _discover_sources_cached(_bucket())


def _array_expr(column: str | None, alias: str) -> str:
    if not column:
        return f"ARRAY[]::text[] AS {alias}"
    qcol = _q(column)
    return (
        f"COALESCE(array_agg(DISTINCT BTRIM({qcol}::text)) "
        f"FILTER (WHERE {qcol} IS NOT NULL AND BTRIM({qcol}::text) <> ''), ARRAY[]::text[]) AS {alias}"
    )


def _max_text_expr(column: str | None, alias: str) -> str:
    if not column:
        return f"NULL::text AS {alias}"
    qcol = _q(column)
    return f"MAX(NULLIF(BTRIM({qcol}::text), '')) AS {alias}"


def _table_qualified(spec: dict) -> str:
    return f"{_q(spec['schema'])}.{_q(spec['table'])}"


@lru_cache(maxsize=16)
def _player_index_cached(bucket: int):
    players: dict[str, dict] = {}
    for logical, spec in discover_sources().items():
        pid = _q(spec["player_id"])
        sql = f"""
            SELECT {pid}::text AS player_id,
                   {_array_expr(spec['name'], 'names')},
                   {_array_expr(spec['position'], 'positions')},
                   {_array_expr(spec['nationality'], 'nationalities')},
                   {_array_expr(spec['club'], 'clubs')},
                   {_array_expr(spec['season'], 'seasons')},
                   {_max_text_expr(spec['photo'], 'photo')}
            FROM {_table_qualified(spec)}
            WHERE {pid} IS NOT NULL
            GROUP BY {pid}::text
        """
        with _source_connect(spec["source"]) as conn:
            rows = conn.execute(text(sql)).mappings().all()
        for row in rows:
            player_id = str(row["player_id"])
            item = players.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "names": set(),
                    "positions": set(),
                    "nationalities": set(),
                    "clubs": set(),
                    "seasons": set(),
                    "photos": set(),
                    "tables": set(),
                },
            )
            for key in ("names", "positions", "nationalities", "clubs", "seasons"):
                item[key].update(str(x).strip() for x in (row.get(key) or []) if str(x).strip())
            if row.get("photo"):
                item["photos"].add(str(row["photo"]).strip())
            item["tables"].add(logical)

    result = []
    for player_id, item in players.items():
        names = sorted(item["names"], key=lambda x: (len(x), x.casefold()))
        positions = sorted(item["positions"], key=str.casefold)
        nationalities = sorted(item["nationalities"], key=str.casefold)
        clubs = sorted(item["clubs"], key=str.casefold)
        seasons = sorted(item["seasons"], reverse=True)
        photos = sorted(item["photos"])
        result.append(
            {
                "player_id": player_id,
                "nome": names[0] if names else f"Jogador {player_id}",
                "aliases": names,
                "foto_url": photos[0] if photos else None,
                "posicao": positions[0] if positions else None,
                "posicoes": positions,
                "nacionalidade": nationalities[0] if nationalities else None,
                "nacionalidades": nationalities,
                "clube": clubs[-1] if clubs else None,
                "clubes": clubs,
                "temporadas": seasons,
                "tabelas": sorted(item["tables"]),
            }
        )
    result.sort(key=lambda x: x["nome"].casefold())
    return tuple(result)


def player_index():
    return [dict(x) for x in _player_index_cached(_bucket())]


def player_filter_options():
    rows = player_index()
    positions = sorted({x for r in rows for x in r.get("posicoes", [])}, key=str.casefold)
    nationalities = sorted({x for r in rows for x in r.get("nacionalidades", [])}, key=str.casefold)
    clubs = sorted({x for r in rows for x in r.get("clubes", [])}, key=str.casefold)
    seasons = sorted({x for r in rows for x in r.get("temporadas", [])}, reverse=True)
    return {
        "positions": positions,
        "nationalities": nationalities,
        "clubs": clubs,
        "seasons": seasons,
        "tables": [
            {"key": k, "label": TABLE_DEFS[k]["label"], "available": k in discover_sources()}
            for k in TABLE_DEFS
        ],
    }


def list_players(
    q: str | None = None,
    position: str | None = None,
    nationality: str | None = None,
    club: str | None = None,
    page: int = 1,
    page_size: int = 60,
):
    qn = _norm(q or "")
    pn = _norm(position or "")
    nn = _norm(nationality or "")
    cn = _norm(club or "")

    def matches(row: dict) -> bool:
        if qn and not any(qn in _norm(name) for name in row.get("aliases", [])):
            return False
        if pn and not any(pn == _norm(x) for x in row.get("posicoes", [])):
            return False
        if nn and not any(nn == _norm(x) for x in row.get("nacionalidades", [])):
            return False
        if cn and not any(cn == _norm(x) for x in row.get("clubes", [])):
            return False
        return True

    filtered = [r for r in player_index() if matches(r)]
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    total = len(filtered)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    return {
        "rows": filtered[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def _metric_expr(spec: dict) -> str:
    parts = []
    for col, weight in spec["metric_parts"]:
        info = spec["columns"].get(col, {})
        expr = _numeric_expr(col, info)
        parts.append(f"({expr}) * {float(weight)}")
    return " + ".join(parts) if parts else "0::numeric"


def _source_filters(spec: dict, season=None, club=None, position=None, nationality=None):
    clauses = []
    params = {}
    for value, key, field in [
        (season, "season", "season"),
        (club, "club", "club"),
        (position, "position", "position"),
        (nationality, "nationality", "nationality"),
    ]:
        col = spec.get(field)
        if value and value != "all" and col:
            clauses.append(f"BTRIM({_q(col)}::text) = :{key}")
            params[key] = value
    return clauses, params


def _metric_totals(logical: str, season=None, club=None, position=None, nationality=None):
    spec = discover_sources().get(logical)
    if not spec:
        return []
    pid = _q(spec["player_id"])
    clauses, params = _source_filters(spec, season, club, position, nationality)
    where = "WHERE " + " AND ".join([f"{pid} IS NOT NULL", *clauses])
    metric = _metric_expr(spec)
    sql = f"""
        SELECT {pid}::text AS player_id,
               SUM({metric})::float AS valor,
               {_array_expr(spec['name'], 'names')},
               {_max_text_expr(spec['photo'], 'photo')},
               {_array_expr(spec['position'], 'positions')},
               {_array_expr(spec['nationality'], 'nationalities')},
               {_array_expr(spec['club'], 'clubs')}
        FROM {_table_qualified(spec)}
        {where}
        GROUP BY {pid}::text
    """
    with _source_connect(spec["source"]) as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def _hat_ranking_column(metric: str) -> tuple[dict | None, str | None]:
    definition = HAT_RANKING_DEFS.get(metric)
    if not definition:
        return None, None
    spec = discover_sources().get("hat_tricks")
    if not spec:
        return None, None
    column = _pick(spec["columns"], definition["aliases"])
    return spec, column


def _hat_component_totals(metric: str, season=None, club=None, position=None, nationality=None):
    spec, column = _hat_ranking_column(metric)
    if not spec or not column:
        return []

    pid = _q(spec["player_id"])
    clauses, params = _source_filters(spec, season, club, position, nationality)
    where = "WHERE " + " AND ".join([f"{pid} IS NOT NULL", *clauses])
    metric_expr = _numeric_expr(column, spec["columns"].get(column, {}))
    sql = f"""
        SELECT {pid}::text AS player_id,
               SUM({metric_expr})::float AS valor,
               {_array_expr(spec['name'], 'names')},
               {_max_text_expr(spec['photo'], 'photo')},
               {_array_expr(spec['position'], 'positions')},
               {_array_expr(spec['nationality'], 'nationalities')},
               {_array_expr(spec['club'], 'clubs')}
        FROM {_table_qualified(spec)}
        {where}
        GROUP BY {pid}::text
    """
    with _source_connect(spec["source"]) as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def player_ranking(
    metric: str,
    season: str | None = None,
    club: str | None = None,
    position: str | None = None,
    nationality: str | None = None,
):
    is_hat_component = metric in HAT_RANKING_DEFS
    if metric not in TABLE_DEFS and not is_hat_component:
        raise ValueError("Ranking individual inválido.")

    meta = {r["player_id"]: r for r in player_index()}
    rows = []
    source_rows = (
        _hat_component_totals(metric, season, club, position, nationality)
        if is_hat_component
        else _metric_totals(metric, season, club, position, nationality)
    )
    for row in source_rows:
        pid = str(row["player_id"])
        base = meta.get(pid, {})
        aliases = sorted(
            set(base.get("aliases", [])) | set(row.get("names") or []),
            key=lambda x: (len(x), x.casefold()),
        )
        positions = row.get("positions") or base.get("posicoes", [])
        nationalities = row.get("nationalities") or base.get("nacionalidades", [])
        clubs = row.get("clubs") or base.get("clubes", [])
        rows.append(
            {
                "player_id": pid,
                "nome": aliases[0] if aliases else base.get("nome", f"Jogador {pid}"),
                "aliases": aliases,
                "foto_url": row.get("photo") or base.get("foto_url"),
                "posicao": positions[0] if positions else base.get("posicao"),
                "nacionalidade": nationalities[0] if nationalities else base.get("nacionalidade"),
                "clube": clubs[-1] if clubs else base.get("clube"),
                "valor": float(row.get("valor") or 0),
            }
        )
    rows.sort(key=lambda x: (x["valor"], x["nome"]), reverse=True)
    for idx, row in enumerate(rows, 1):
        row["posicao_ranking"] = idx
    if is_hat_component:
        spec, column = _hat_ranking_column(metric)
        label = HAT_RANKING_DEFS[metric]["label"]
        source_available = bool(spec and column)
    else:
        label = TABLE_DEFS[metric]["label"]
        source_available = metric in discover_sources()

    return {
        "metric": metric,
        "label": label,
        "rows": rows,
        "source_available": source_available,
    }


def _extra_numeric_columns(spec: dict) -> list[str]:
    canonical = {
        spec.get("player_id"), spec.get("name"), spec.get("photo"), spec.get("position"),
        spec.get("nationality"), spec.get("club"), spec.get("season"), spec.get("competition"),
        *[x[0] for x in spec.get("metric_parts", [])],
    }
    extras = []
    for col, info in spec["columns"].items():
        n = _norm(col)
        if col in canonical or info.get("data_type") not in NUMERIC_TYPES:
            continue
        if n == "id" or n.endswith("_id") or n.startswith("id_") or "temporada" in n or n in {"ano", "idade"}:
            continue
        extras.append(col)
    return extras


def _player_source_data(spec: dict, player_id: str, season: str | None, club: str | None):
    pid = _q(spec["player_id"])
    clauses = [f"{pid}::text = :player_id"]
    params = {"player_id": str(player_id)}
    if season and season != "all" and spec.get("season"):
        clauses.append(f"BTRIM({_q(spec['season'])}::text) = :season")
        params["season"] = season
    if club and club != "all" and spec.get("club"):
        clauses.append(f"BTRIM({_q(spec['club'])}::text) = :club")
        params["club"] = club
    where = " AND ".join(clauses)
    metric_expr = _metric_expr(spec)
    extras = _extra_numeric_columns(spec)
    extra_selects = [f"SUM({_numeric_expr(c, spec['columns'].get(c))})::float AS {_q(c)}" for c in extras]
    aggregate_sql = f"""
        SELECT SUM({metric_expr})::float AS total
               {',' if extra_selects else ''} {', '.join(extra_selects)}
        FROM {_table_qualified(spec)}
        WHERE {where}
    """
    order = f"ORDER BY {_q(spec['season'])}::text DESC NULLS LAST" if spec.get("season") else ""
    raw_sql = f"SELECT * FROM {_table_qualified(spec)} WHERE {where} {order} LIMIT 200"
    with _source_connect(spec["source"]) as conn:
        aggregate = dict(conn.execute(text(aggregate_sql), params).mappings().one())
        raw_rows = [dict(r) for r in conn.execute(text(raw_sql), params).mappings().all()]

    return {
        "key": spec["logical"],
        "label": spec["label"],
        "table": f"{spec['schema']}.{spec['table']}",
        "total": float(aggregate.pop("total") or 0),
        "extras": {k: _json_value(v) for k, v in aggregate.items() if v is not None},
        "rows": [{k: _json_value(v) for k, v in row.items()} for row in raw_rows],
    }


def player_profile(player_id: str, season: str | None = None, club: str | None = None):
    meta = next((x for x in player_index() if x["player_id"] == str(player_id)), None)
    if not meta:
        raise ValueError("Jogador não encontrado.")

    sources = []
    totals = {key: 0.0 for key in TABLE_DEFS}
    season_map: dict[str, dict] = {}

    for logical, spec in discover_sources().items():
        data = _player_source_data(spec, str(player_id), season, club)
        sources.append(data)
        totals[logical] = data["total"]

        if spec.get("season"):
            pid = _q(spec["player_id"])
            clauses = [f"{pid}::text = :player_id"]
            params = {"player_id": str(player_id)}
            if club and club != "all" and spec.get("club"):
                clauses.append(f"BTRIM({_q(spec['club'])}::text) = :club")
                params["club"] = club
            metric_expr = _metric_expr(spec)
            sql = f"""
                SELECT BTRIM({_q(spec['season'])}::text) AS season,
                       SUM({metric_expr})::float AS value
                FROM {_table_qualified(spec)}
                WHERE {' AND '.join(clauses)}
                GROUP BY BTRIM({_q(spec['season'])}::text)
            """
            with _source_connect(spec["source"]) as conn:
                for row in conn.execute(text(sql), params).mappings():
                    s = str(row["season"] or "")
                    if not s:
                        continue
                    season_map.setdefault(s, {"temporada": s})[logical] = float(row["value"] or 0)

    minutes = totals.get("minutos", 0) or 0
    goals = totals.get("gols_marcados", 0) or 0
    assists = totals.get("assistencias", 0) or 0
    conceded = totals.get("gols_sofridos", 0) or 0
    discipline = totals.get("disciplina", 0) or 0

    def per90(value):
        return value * 90 / minutes if minutes > 0 else None

    seasons = sorted(season_map.values(), key=lambda x: x["temporada"], reverse=True)
    return {
        "player": meta,
        "filters": {
            "seasons": meta.get("temporadas", []),
            "clubs": meta.get("clubes", []),
        },
        "totals": totals,
        "derived": {
            "goals_assists": goals + assists,
            "goals_per90": per90(goals),
            "assists_per90": per90(assists),
            "goal_contributions_per90": per90(goals + assists),
            "conceded_per90": per90(conceded),
            "discipline_per90": per90(discipline),
        },
        "by_season": seasons,
        "sources": sources,
    }
