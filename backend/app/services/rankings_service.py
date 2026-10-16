from __future__ import annotations

import re
from collections import defaultdict
from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection
from .elo_service import normalize_name, season_key


def _country_name(country_id: int | None):
    if not country_id:
        return None
    with app_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT nome FROM {settings.app_schema}.paises WHERE id = :id"),
            {"id": country_id},
        ).scalar()


def _competition_meta(competition_id: int | None):
    if not competition_id:
        return None
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT c.id, c.nome, c.pais_id, c.principal, p.nome AS pais
                FROM {settings.app_schema}.campeonatos c
                JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
                WHERE c.id = :id
                """
            ),
            {"id": competition_id},
        ).mappings().first()
    return dict(row) if row else None


def _all_seasons(country_id: int | None = None) -> list[str]:
    country_name = _country_name(country_id)
    clauses = []
    params = {}
    if country_name:
        clauses.append("pais = :country")
        params["country"] = country_name
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with history_connection() as conn:
        values = [
            str(r["temporada"])
            for r in conn.execute(
                text(
                    f"""
                    SELECT DISTINCT temporada::text AS temporada
                    FROM {settings.history_schema}.{settings.history_table}
                    {where}
                    AND temporada IS NOT NULL
                    """ if where else f"""
                    SELECT DISTINCT temporada::text AS temporada
                    FROM {settings.history_schema}.{settings.history_table}
                    WHERE temporada IS NOT NULL
                    """
                ),
                params,
            ).mappings()
            if r.get("temporada")
        ]
    return sorted(set(values), key=season_key, reverse=True)


def _years_from_seasons(seasons: list[str]) -> set[int]:
    found: set[int] = set()
    for season in seasons:
        for part in re.split(r"[/\-]", str(season or "")):
            if part.isdigit():
                value = int(part)
                if 1850 <= value <= 2100:
                    found.add(value)
    return found


def _all_years(country_id: int | None = None, seasons: list[str] | None = None) -> list[int]:
    """Anos-calendário a partir da data em `jogos` (e fallbacks)."""
    years: set[int] = set(_years_from_seasons(seasons or []))
    country_name = _country_name(country_id)
    params: dict = {}
    country_clause = ""
    if country_name:
        country_clause = " AND pais = :country"
        params["country"] = country_name

    # Fonte principal pedida: data dos jogos (SofaScore).
    try:
        with history_connection() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT DISTINCT EXTRACT(YEAR FROM data)::int AS ano
                    FROM {settings.history_schema}.jogos
                    WHERE data IS NOT NULL{country_clause}
                    ORDER BY 1 DESC
                    """
                ),
                params,
            )
            years.update(int(r[0]) for r in rows if r[0] is not None)
    except Exception:
        pass

    # Complemento: historico_jogos (cobre anos sem linha em jogos).
    if len(years) < 3:
        try:
            with history_connection() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT DISTINCT EXTRACT(YEAR FROM data)::int AS ano
                        FROM {settings.history_schema}.{settings.history_table}
                        WHERE data IS NOT NULL{country_clause}
                        ORDER BY 1 DESC
                        LIMIT 200
                        """
                    ),
                    params,
                )
                years.update(int(r[0]) for r in rows if r[0] is not None)
        except Exception:
            pass

    return sorted(years, reverse=True)


def _normalize_year(year) -> int | None:
    if year in (None, "", "all"):
        return None
    try:
        value = int(year)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ano inválido.") from exc
    if value < 1850 or value > 2100:
        raise ValueError("Ano inválido.")
    return value


def _normalize_min_games(min_games, default: int = 5) -> int:
    if min_games in (None, "", "all"):
        return default
    try:
        value = int(min_games)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mínimo de jogos inválido.") from exc
    if value < 1 or value > 500:
        raise ValueError("Mínimo de jogos deve estar entre 1 e 500.")
    return value


def _history_dimensions(country_id: int | None = None, competition_id: int | None = None):
    """Divisões e formatos distintos de historico_jogos para o recorte."""
    comp = _competition_meta(competition_id)
    country_name = comp["pais"] if comp else _country_name(country_id)
    with history_connection() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema=:s AND table_name=:t
                    """
                ),
                {"s": settings.history_schema, "t": settings.history_table},
            )
        }
        if "divisao" not in cols and "formato" not in cols:
            return {"divisions": [], "formats": [], "division_formats": []}
        div_expr = "NULLIF(BTRIM(divisao::text),'')" if "divisao" in cols else "NULL::text"
        fmt_expr = "NULLIF(BTRIM(formato::text),'')" if "formato" in cols else "NULL::text"
        clauses, params = [], {}
        if country_name:
            clauses.append("pais = :country")
            params["country"] = country_name
        if comp:
            clauses.append("campeonato = :competition")
            params["competition"] = comp["nome"]
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT DISTINCT {div_expr} AS divisao, {fmt_expr} AS formato
                    FROM {settings.history_schema}.{settings.history_table}
                    {where}
                    """
                ),
                params,
            ).mappings()
        ]
    pairs = sorted(
        {
            (str(r.get("divisao") or "").strip(), str(r.get("formato") or "").strip())
            for r in rows
            if (r.get("divisao") not in (None, "") or r.get("formato") not in (None, ""))
        },
        key=lambda x: (x[0].casefold(), x[1].casefold()),
    )
    divisions = sorted({d for d, _ in pairs if d}, key=lambda s: s.casefold())
    formats = sorted({f for _, f in pairs if f}, key=lambda s: s.casefold())
    return {
        "divisions": divisions,
        "formats": formats,
        "division_formats": [{"divisao": d, "formato": f} for d, f in pairs if d or f],
    }


def filters(country_id: int | None = None, competition_id: int | None = None):
    with app_engine.connect() as conn:
        from ..repositories.catalog_repository import list_countries
        countries = [
            {"id": country["id"], "nome": country["nome"]}
            for country in list_countries(with_games=True)
        ]
        params = {}
        where = ""
        if country_id:
            params["country"] = country_id
            where = "WHERE c.pais_id = :country"
        competitions = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT c.id, c.nome, c.pais_id, c.principal, p.nome AS pais
                    FROM {settings.app_schema}.campeonatos c
                    JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
                    {where}
                    ORDER BY c.principal DESC, p.nome, c.nome
                    """
                ),
                params,
            ).mappings()
        ]

    seasons = _all_seasons(country_id)
    years = _all_years(country_id, seasons=seasons)
    dims = _history_dimensions(country_id, competition_id)
    return {
        "countries": countries,
        "competitions": competitions,
        "seasons": seasons,
        "years": years,
        "current_season": seasons[0] if seasons else None,
        **dims,
    }


def _pick_latest(rows: list[dict], club_key: str = "clube_id"):
    selected = {}
    for row in rows:
        cid = row[club_key]
        current = selected.get(cid)
        if current is None:
            selected[cid] = row
            continue
        row_key = (
            season_key(str(row.get("temporada") or "")),
            bool(row.get("principal")),
            str(row.get("atualizado_em") or ""),
        )
        cur_key = (
            season_key(str(current.get("temporada") or "")),
            bool(current.get("principal")),
            str(current.get("atualizado_em") or ""),
        )
        if row_key > cur_key:
            selected[cid] = row
    return list(selected.values())


def _registered_directory():
    with app_engine.connect() as conn:
        clubs = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT cl.id, cl.nome, cl.escudo_url, cl.pais_id, p.nome AS pais
                    FROM {settings.app_schema}.clubes cl
                    JOIN {settings.app_schema}.paises p ON p.id = cl.pais_id
                    """
                )
            ).mappings()
        ]
        aliases = [
            dict(r)
            for r in conn.execute(
                text(f"SELECT clube_id, alias FROM {settings.app_schema}.clubes_aliases")
            ).mappings()
        ]

    by_id = {int(c["id"]): c for c in clubs}
    mapping = {}
    for c in clubs:
        mapping[(normalize_name(c["pais"]), normalize_name(c["nome"]))] = int(c["id"])
    for a in aliases:
        club = by_id.get(int(a["clube_id"]))
        if club:
            mapping[(normalize_name(club["pais"]), normalize_name(a["alias"]))] = int(a["clube_id"])
    return by_id, mapping


def _history_games(
    country_id: int | None,
    competition_id: int | None,
    exact_season: str | None = None,
    divisao: str | None = None,
    formato: str | None = None,
    year: int | None = None,
):
    comp = _competition_meta(competition_id)
    country_name = comp["pais"] if comp else _country_name(country_id)
    clauses = ["gols_casa IS NOT NULL", "gols_fora IS NOT NULL"]
    params = {}

    if country_name:
        clauses.append("pais = :country")
        params["country"] = country_name
    if comp:
        clauses.append("campeonato = :competition")
        params["competition"] = comp["nome"]
    if exact_season:
        clauses.append("temporada::text = :season")
        params["season"] = exact_season
    if year is not None:
        clauses.append("EXTRACT(YEAR FROM data)::int = :year")
        params["year"] = year
    if divisao:
        clauses.append("BTRIM(divisao::text) = :divisao")
        params["divisao"] = divisao
    if formato:
        clauses.append("BTRIM(formato::text) = :formato")
        params["formato"] = formato

    with history_connection() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema=:s AND table_name=:t
                    """
                ),
                {"s": settings.history_schema, "t": settings.history_table},
            )
        }
        if divisao and "divisao" not in cols:
            return []
        if formato and "formato" not in cols:
            return []
        return [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT id, data, temporada::text AS temporada, campeonato, pais,
                           casa, fora, gols_casa, gols_fora
                    FROM {settings.history_schema}.{settings.history_table}
                    WHERE {' AND '.join(clauses)}
                    ORDER BY data DESC NULLS LAST, id DESC
                    """
                ),
                params,
            ).mappings()
        ]


def _identity(pais: str, clube: str, by_id: dict, mapping: dict):
    key = (normalize_name(pais), normalize_name(clube))
    cid = mapping.get(key)
    if cid and cid in by_id:
        c = by_id[cid]
        return f"id:{cid}", {
            "clube_id": cid,
            "clube": c["nome"],
            "escudo_url": c.get("escudo_url"),
            "pais_id": c.get("pais_id"),
            "pais": c.get("pais") or pais,
        }
    hist_key = f"hist:{normalize_name(pais)}:{normalize_name(clube)}"
    return hist_key, {
        "clube_id": hist_key,
        "clube": clube,
        "escudo_url": None,
        "pais_id": None,
        "pais": pais,
    }


def _history_series(
    country_id: int | None,
    competition_id: int | None,
    season: str | None,
    venue: str,
    exact_season: bool,
    divisao: str | None = None,
    formato: str | None = None,
    year: int | None = None,
):
    by_id, mapping = _registered_directory()
    games = _history_games(
        country_id,
        competition_id,
        exact_season=season if exact_season else None,
        divisao=divisao,
        formato=formato,
        year=year,
    )
    cutoff = season_key(season or "9999/9999")
    series = defaultdict(list)
    meta = {}

    for g in games:
        game_season = str(g.get("temporada") or "")
        if not exact_season and season and season_key(game_season) > cutoff:
            continue
        gh, ga = int(g["gols_casa"]), int(g["gols_fora"])
        home_key, home_meta = _identity(str(g.get("pais") or ""), str(g["casa"]), by_id, mapping)
        away_key, away_meta = _identity(str(g.get("pais") or ""), str(g["fora"]), by_id, mapping)
        meta[home_key] = home_meta
        meta[away_key] = away_meta

        common = {
            "date": g.get("data"),
            "season": game_season,
            "competition": g.get("campeonato"),
            "total": gh + ga,
            "btts": gh > 0 and ga > 0,
        }
        if venue in ("all", "home"):
            series[home_key].append({
                **common,
                "venue": "home",
                "gf": gh,
                "ga": ga,
                "result": "W" if gh > ga else "D" if gh == ga else "L",
            })
        if venue in ("all", "away"):
            series[away_key].append({
                **common,
                "venue": "away",
                "gf": ga,
                "ga": gh,
                "result": "W" if ga > gh else "D" if ga == gh else "L",
            })

    return meta, series


def _period_stats(country_id, competition_id, season, venue, divisao=None, formato=None, year=None):
    """MGM/MGS do recorte. season=None significa todo o histórico."""
    meta, series = _history_series(
        country_id,
        competition_id,
        season,
        venue,
        exact_season=bool(season),
        divisao=divisao,
        formato=formato,
        year=year,
    )
    by_numeric_id = {}
    by_name = {}
    for key, rows in series.items():
        if not rows:
            continue
        gf = sum(r["gf"] for r in rows)
        ga = sum(r["ga"] for r in rows)
        n = len(rows)
        stats = {
            "mgm": gf / n,
            "mgs": ga / n,
            "jogos": n,
            "gols_marcados": gf,
            "gols_sofridos": ga,
        }
        m = meta[key]
        if isinstance(m.get("clube_id"), int):
            by_numeric_id[int(m["clube_id"])] = stats
        by_name[(normalize_name(m.get("pais") or ""), normalize_name(m.get("clube") or ""))] = stats
    return by_numeric_id, by_name


def _enrich_rows_with_season_stats(rows, country_id, competition_id, season, venue, divisao=None, formato=None, year=None):
    by_id, by_name = _period_stats(country_id, competition_id, season, venue, divisao, formato, year)
    for row in rows:
        stats = by_id.get(int(row["clube_id"])) if isinstance(row.get("clube_id"), int) else None
        if not stats:
            stats = by_name.get((normalize_name(row.get("pais") or ""), normalize_name(row.get("clube") or "")), {})
        row["mgm"] = stats.get("mgm")
        row["mgs"] = stats.get("mgs")
    return rows


def elo_ranking(country_id, competition_id, season, venue, divisao=None, formato=None, year=None):
    clauses, params = [], {}
    if country_id:
        clauses.append("p.id = :country"); params["country"] = country_id
    if competition_id:
        clauses.append("e.campeonato_id = :competition"); params["competition"] = competition_id
    if season:
        clauses.append("e.temporada = :season"); params["season"] = season
    elif year is not None:
        # Temporadas que mencionam o ano-calendário (ex.: 2024 → 2023/2024 e 2024/2025).
        clauses.append("e.temporada::text LIKE :year_pat")
        params["year_pat"] = f"%{year}%"
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT e.clube_id, cl.nome AS clube, cl.escudo_url,
                   e.temporada, e.elo_atual::float AS valor,
                   e.jogos, c.id AS campeonato_id, c.nome AS campeonato,
                   c.principal, p.id AS pais_id, p.nome AS pais,
                   e.atualizado_em
            FROM {settings.app_schema}.elo_clubes e
            JOIN {settings.app_schema}.clubes cl ON cl.id = e.clube_id
            JOIN {settings.app_schema}.campeonatos c ON c.id = e.campeonato_id
            JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
            {where}
        """), params).mappings()]

    if season:
        out = rows
    else:
        # Em "Todas as temporadas", o ELO é a média dos ELOs finais de cada temporada.
        grouped = defaultdict(list)
        for row in rows:
            grouped[int(row["clube_id"])].append(row)
        out = []
        for club_rows in grouped.values():
            latest = max(
                club_rows,
                key=lambda r: (season_key(str(r.get("temporada") or "")), str(r.get("atualizado_em") or "")),
            )
            item = dict(latest)
            item["valor"] = sum(float(r["valor"]) for r in club_rows) / len(club_rows)
            item["jogos"] = sum(int(r.get("jogos") or 0) for r in club_rows)
            item["temporada"] = "Todas"
            item["temporadas_consideradas"] = len(club_rows)
            out.append(item)

    out = _enrich_rows_with_season_stats(out, country_id, competition_id, season, venue, divisao, formato, year)
    out.sort(key=lambda x: (-float(x["valor"]), str(x["clube"]).casefold()))
    for i, row in enumerate(out, 1):
        row["posicao"] = i
        row["metrica"] = "ELO médio" if not season else "ELO"
    return {"rows": out, "direction": "desc", "unit": "pts", "all_seasons": not bool(season)}


def _history_strengths(country_id, competition_id, season, divisao=None, formato=None, year=None):
    by_id, mapping = _registered_directory()
    games = _history_games(country_id, competition_id, exact_season=season or None, divisao=divisao, formato=formato, year=year)
    if not games:
        return []
    league_home_avg = sum(int(g["gols_casa"]) for g in games) / len(games)
    league_away_avg = sum(int(g["gols_fora"]) for g in games) / len(games)
    acc = defaultdict(lambda:{"hg":0,"ag":0,"hgf":0,"hga":0,"agf":0,"aga":0})
    meta = {}
    for g in games:
        hk, hm = _identity(str(g.get("pais") or ""), str(g["casa"]), by_id, mapping)
        ak, am = _identity(str(g.get("pais") or ""), str(g["fora"]), by_id, mapping)
        meta[hk]=hm; meta[ak]=am
        gh,ga=int(g["gols_casa"]),int(g["gols_fora"])
        a=acc[hk]; a["hg"]+=1; a["hgf"]+=gh; a["hga"]+=ga
        a=acc[ak]; a["ag"]+=1; a["agf"]+=ga; a["aga"]+=gh
    out=[]
    for key,d in acc.items():
        attack_home=(d["hgf"]/d["hg"])/league_home_avg if d["hg"] and league_home_avg else None
        defense_home=(d["hga"]/d["hg"])/league_away_avg if d["hg"] and league_away_avg else None
        attack_away=(d["agf"]/d["ag"])/league_away_avg if d["ag"] and league_away_avg else None
        defense_away=(d["aga"]/d["ag"])/league_home_avg if d["ag"] and league_home_avg else None
        total=d["hg"]+d["ag"]
        attack_parts=[(attack_home,d["hg"]),(attack_away,d["ag"])]
        defense_parts=[(defense_home,d["hg"]),(defense_away,d["ag"])]
        attack=sum(v*w for v,w in attack_parts if v is not None)/sum(w for v,w in attack_parts if v is not None) if any(v is not None for v,_ in attack_parts) else None
        defense=sum(v*w for v,w in defense_parts if v is not None)/sum(w for v,w in defense_parts if v is not None) if any(v is not None for v,_ in defense_parts) else None
        gf=d["hgf"]+d["agf"]; ga=d["hga"]+d["aga"]
        out.append({**meta[key],"temporada":season or "Todas","forca_ofensiva":attack,"forca_defensiva":defense,"forca_ofensiva_casa":attack_home,"forca_defensiva_casa":defense_home,"forca_ofensiva_fora":attack_away,"forca_defensiva_fora":defense_away,"mgm":gf/total if total else None,"mgs":ga/total if total else None})
    return out


def strength_ranking(metric, country_id, competition_id, season, venue, divisao=None, formato=None, year=None):
    rows=_history_strengths(country_id, competition_id, season, divisao, formato, year)
    suffix="_casa" if venue=="home" else "_fora" if venue=="away" else ""
    field=("forca_ofensiva" if metric=="offense" else "forca_defensiva")+suffix
    out=[]
    for row in rows:
        value=row.get(field)
        if value is None: continue
        item=dict(row); item["valor"]=float(value); item["metrica"]="Força ofensiva" if metric=="offense" else "Força defensiva"; out.append(item)
    out=_enrich_rows_with_season_stats(out,country_id,competition_id,season,venue,divisao,formato,year)
    reverse=metric=="offense"
    out.sort(key=lambda x:(-float(x["valor"]) if reverse else float(x["valor"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc" if reverse else "asc","unit":"índice","defense_lower_is_better":metric=="defense"}


def market_ranking(country_id, competition_id, season, venue, divisao=None, formato=None, year=None):
    clauses, params = [], {}
    if country_id:
        clauses.append("p.id = :country"); params["country"] = country_id
    if competition_id:
        clauses.append("vm.campeonato_id = :competition"); params["competition"] = competition_id
    if season:
        clauses.append("vm.temporada = :season"); params["season"] = season
    elif year is not None:
        clauses.append("vm.temporada::text LIKE :year_pat")
        params["year_pat"] = f"%{year}%"
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    with app_engine.connect() as conn:
        rows=[dict(r) for r in conn.execute(text(f"""
            SELECT vm.clube_id, cl.nome AS clube, cl.escudo_url,
                   vm.temporada, vm.valor::float AS valor, vm.moeda,
                   c.id AS campeonato_id, c.nome AS campeonato, c.principal,
                   p.id AS pais_id, p.nome AS pais, vm.atualizado_em
            FROM {settings.app_schema}.valores_mercado vm
            JOIN {settings.app_schema}.clubes cl ON cl.id = vm.clube_id
            JOIN {settings.app_schema}.campeonatos c ON c.id = vm.campeonato_id
            JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
            {where}
        """),params).mappings()]

    if not season:
        # Em "Todas as temporadas", soma os valores históricos por clube e moeda.
        grouped = defaultdict(list)
        for row in rows:
            grouped[(int(row["clube_id"]), str(row.get("moeda") or ""))].append(row)
        aggregated=[]
        for club_rows in grouped.values():
            latest=max(club_rows,key=lambda r:(season_key(str(r.get("temporada") or "")),str(r.get("atualizado_em") or "")))
            item=dict(latest)
            item["valor"]=sum(float(r["valor"]) for r in club_rows)
            item["temporada"]="Todas"
            item["temporadas_consideradas"]=len(club_rows)
            aggregated.append(item)
        rows=aggregated

    rows=_enrich_rows_with_season_stats(rows,country_id,competition_id,season,venue,divisao,formato,year)
    currencies=sorted({str(r.get("moeda") or "") for r in rows if r.get("moeda")})
    warning=None
    if len(currencies)<=1:
        rows.sort(key=lambda x:(-float(x["valor"]),str(x["clube"]).casefold()))
    else:
        rows.sort(key=lambda x:(str(x.get("moeda") or ""),-float(x["valor"]),str(x["clube"]).casefold()))
        warning="Há mais de uma moeda no recorte. O ranking está agrupado por moeda, sem conversão cambial."
    cur=None;pos=0
    for row in rows:
        if len(currencies)>1 and row.get("moeda")!=cur:
            cur=row.get("moeda");pos=0
        pos+=1;row["posicao"]=pos;row["metrica"]="Valor de mercado"
    return {"rows":rows,"direction":"desc","unit":"currency","warning":warning,"all_seasons":not bool(season)}


def _stats_item(meta, rows, metric_label="Desempenho"):
    n=len(rows); wins=sum(r["result"]=="W" for r in rows); draws=sum(r["result"]=="D" for r in rows); losses=n-wins-draws
    gf=sum(r["gf"] for r in rows); ga=sum(r["ga"] for r in rows)
    return {**meta,"valor":(wins*3+draws)/(3*n)*100 if n else 0,"jogos":n,"vitorias":wins,"empates":draws,"derrotas":losses,"gols_marcados":gf,"gols_sofridos":ga,"saldo_gols":gf-ga,"mgm":gf/n if n else None,"mgs":ga/n if n else None,"metrica":metric_label}


def performance_ranking(period, country_id, competition_id, season, venue, divisao=None, formato=None, year=None, min_games=5):
    meta, series=_history_series(country_id,competition_id,season,venue,exact_season=False,divisao=divisao,formato=formato,year=year)
    limit=int(period) if period in {"5","10","20"} else None
    out=[]
    for key,all_rows in series.items():
        rows=all_rows
        if limit: rows=rows[:limit]
        elif period=="season": rows=[r for r in rows if not season or r["season"]==season]
        if not rows or len(rows) < min_games: continue
        item=_stats_item(meta[key],rows); item["temporada"]=season; out.append(item)
    out.sort(key=lambda x:(-float(x["valor"]),-int(x["saldo_gols"]),-int(x["vitorias"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc","unit":"%"}


def threshold_ranking(metric, country_id, competition_id, season, venue, divisao=None, formato=None, year=None, min_games=5):
    meta, series=_history_series(country_id,competition_id,season,venue,exact_season=True,divisao=divisao,formato=formato,year=year)
    labels={"over15":"Over 1,5","over25":"Over 2,5","btts":"Ambos marcam"}
    out=[]
    for key,rows in series.items():
        if not rows or len(rows) < min_games: continue
        if metric=="over15": hits=sum(r["total"]>1.5 for r in rows)
        elif metric=="over25": hits=sum(r["total"]>2.5 for r in rows)
        else: hits=sum(bool(r["btts"]) for r in rows)
        item=_stats_item(meta[key],rows,labels[metric]); item["valor"]=hits; item["taxa"]=hits/len(rows)*100; item["temporada"]=season; out.append(item)
    out.sort(key=lambda x:(-int(x["valor"]),-float(x["taxa"]),-int(x["jogos"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc","unit":"jogos"}


# Métricas agregadas a partir de jogo_completo (+ placar em jogos para eficiência).
SOFASCORE_METRICS = {
    "shots": {"label": "Finalizações", "mode": "sum", "field": "total_chutes", "unit": "total", "decimals": 0},
    "shots_on_target": {"label": "Finalizações certas", "mode": "sum", "field": "chutes_gol", "unit": "total", "decimals": 0},
    "shots_per_game": {"label": "Finalizações por jogo", "mode": "avg", "field": "total_chutes", "unit": "média", "decimals": 2},
    "shots_per_goal": {"label": "Finalizações para fazer 1 gol", "mode": "per_goal", "field": "total_chutes", "unit": "por gol", "decimals": 2, "lower_better": True},
    "sot_per_goal": {"label": "Finalizações certas para fazer 1 gol", "mode": "per_goal", "field": "chutes_gol", "unit": "por gol", "decimals": 2, "lower_better": True},
    "pass_accuracy": {"label": "% Passes certos", "mode": "ratio_pct", "num": "passes_certos", "den": "passes", "unit": "%", "decimals": 1},
    "possession": {"label": "Posse de bola média", "mode": "avg", "field": "posse_bola", "unit": "%", "decimals": 1},
    "tackles": {"label": "Desarmes", "mode": "avg", "field": "total_desarmes", "unit": "média", "decimals": 2},
    "xg": {"label": "xG médio", "mode": "avg", "field": "xg", "unit": "média", "decimals": 2},
    "big_chances": {"label": "Grandes chances", "mode": "sum", "field": "grandes_chances_criadas", "unit": "total", "decimals": 0},
    "big_chances_scored": {"label": "Grandes chances convertidas", "mode": "sum", "field": "grandes_chances_convertidas", "unit": "total", "decimals": 0},
    "corners": {"label": "Escanteios", "mode": "avg", "field": "escanteios", "unit": "média", "decimals": 2},
    "interceptions": {"label": "Interceptações", "mode": "avg", "field": "interceptacoes", "unit": "média", "decimals": 2},
    "recoveries": {"label": "Recuperações", "mode": "avg", "field": "recuperacoes_bola", "unit": "média", "decimals": 2},
    "duel_pct": {"label": "% Duelos vencidos", "mode": "avg", "field": "percentual_duelos_vencidos", "unit": "%", "decimals": 1},
    "dribble_pct": {"label": "% Dribles certos", "mode": "avg", "field": "percentual_dribles_certos", "unit": "%", "decimals": 1},
    "tackle_pct": {"label": "% Desarmes certos", "mode": "avg", "field": "percentual_desarmes_vencidos", "unit": "%", "decimals": 1},
    "shots_in_box": {"label": "Chutes na área", "mode": "avg", "field": "chutes_dentro_area", "unit": "média", "decimals": 2},
    "saves": {"label": "Defesas do goleiro", "mode": "avg", "field": "defesas_goleiro", "unit": "média", "decimals": 2},
    "yellow_cards": {"label": "Cartões amarelos", "mode": "avg", "field": "cartoes_amarelos", "unit": "média", "decimals": 2},
    "red_cards": {"label": "Cartões vermelhos", "mode": "avg", "field": "cartoes_vermelhos", "unit": "média", "decimals": 2},
    "fouls": {"label": "Faltas", "mode": "avg", "field": "faltas", "unit": "média", "decimals": 2},
    "offsides": {"label": "Impedimentos", "mode": "avg", "field": "impedimentos", "unit": "média", "decimals": 2},
    "woodwork": {"label": "Bolas na trave", "mode": "sum", "field": "bolas_na_trave", "unit": "total", "decimals": 0},
    "crosses": {"label": "Cruzamentos certos", "mode": "avg", "field": "cruzamentos_certos", "unit": "média", "decimals": 2},
    "long_balls": {"label": "Bolas longas certas", "mode": "avg", "field": "bolas_longas_certas", "unit": "média", "decimals": 2},
    "through_balls": {"label": "Passes em profundidade", "mode": "avg", "field": "passes_profundidade_certos", "unit": "média", "decimals": 2},
}

# Colunas auxiliares coerentes com o assunto (além de # / Clube / País / métrica principal).
def _col(key, label, *, decimals=None, format="number", suffix="", role="aux"):
    return {"key": key, "label": label, "decimals": decimals, "format": format, "suffix": suffix, "role": role}


def _sofa_columns(metric: str, spec: dict) -> list[dict]:
    main = _col("valor", spec["label"], decimals=spec.get("decimals", 1),
                format="int" if spec.get("decimals", 1) == 0 else "number",
                suffix="%" if spec.get("unit") == "%" else "", role="main")
    kits = {
        "big_chances": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("por_jogo", "Grandes chances por jogo", decimals=2),
            _col("convertidas", "Grandes chances convertidas", format="int"),
            _col("taxa_conv", "% Grandes chances convertidas", decimals=1, suffix="%"),
        ],
        "big_chances_scored": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("por_jogo", "Convertidas por jogo", decimals=2),
            _col("criadas", "Grandes chances", format="int"),
            _col("taxa_conv", "% Grandes chances convertidas", decimals=1, suffix="%"),
        ],
        "shots": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("por_jogo", "Finalizações por jogo", decimals=2),
            _col("no_alvo", "Finalizações certas", format="int"),
            _col("taxa_alvo", "% no gol", decimals=1, suffix="%"),
        ],
        "shots_on_target": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("por_jogo", "Certas por jogo", decimals=2),
            _col("total_chutes", "Finalizações", format="int"),
            _col("taxa_alvo", "% no gol", decimals=1, suffix="%"),
        ],
        "shots_per_game": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_chutes", "Finalizações", format="int"),
            _col("no_alvo", "Finalizações certas", format="int"),
            _col("gols_marcados", "Gols", format="int"),
        ],
        "shots_per_goal": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_chutes", "Finalizações", format="int"),
            _col("gols_marcados", "Gols", format="int"),
        ],
        "sot_per_goal": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("no_alvo", "Finalizações certas", format="int"),
            _col("gols_marcados", "Gols", format="int"),
        ],
        "xg": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("xg_total", "xG total", decimals=1),
            _col("gols_marcados", "Gols", format="int"),
            _col("xg_diff", "Gols − xG", decimals=2),
        ],
        "shots_in_box": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_chutes", "Finalizações", format="int"),
            _col("gols_marcados", "Gols", format="int"),
        ],
        "pass_accuracy": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("passes", "Passes", format="int"),
            _col("passes_certos", "Passes certos", format="int"),
        ],
        "possession": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("mgm", "MGM", decimals=2),
            _col("mgs", "MGS", decimals=2),
        ],
        "tackles": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_desarmes", "Desarmes totais", format="int"),
            _col("tackle_pct_val", "% certos", decimals=1, suffix="%"),
        ],
        "tackle_pct": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_desarmes", "Desarmes", format="int"),
        ],
        "interceptions": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Interceptações totais", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
        ],
        "recoveries": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Recuperações totais", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
        ],
        "duel_pct": [main, _col("jogos", "Jogos", format="int"), _col("mgm", "MGM", decimals=2), _col("mgs", "MGS", decimals=2)],
        "dribble_pct": [main, _col("jogos", "Jogos", format="int"), _col("mgm", "MGM", decimals=2)],
        "saves": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Defesas totais", format="int"),
            _col("mgs", "MGS", decimals=2),
        ],
        "corners": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Escanteios totais", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
        ],
        "fouls": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Faltas totais", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
        ],
        "offsides": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Impedimentos totais", format="int"),
        ],
        "yellow_cards": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Amarelos totais", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
        ],
        "red_cards": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Vermelhos totais", format="int"),
        ],
        "woodwork": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("por_jogo", "Por jogo", decimals=2),
            _col("gols_marcados", "Gols", format="int"),
        ],
        "crosses": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Cruzamentos certos totais", format="int"),
        ],
        "long_balls": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Bolas longas totais", format="int"),
        ],
        "through_balls": [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("total_stat", "Passes em profundidade totais", format="int"),
        ],
    }
    return kits.get(metric, [
        main,
        _col("jogos", "Jogos", format="int"),
        _col("mgm", "MGM", decimals=2),
        _col("mgs", "MGS", decimals=2),
        _col("gols_marcados", "GM", format="int"),
        _col("gols_sofridos", "GS", format="int"),
    ])


def _sofa_aux_fields(metric: str, row: dict, n: int, gf: float) -> dict:
    """Campos auxiliares derivados das somas/médias de jogo_completo."""
    def s(field):
        return float(row.get(f"sum_{field}") or 0)

    def a(field):
        return float(row.get(f"avg_{field}") or 0)

    criadas = s("grandes_chances_criadas")
    convertidas = s("grandes_chances_convertidas")
    chutes = s("total_chutes")
    no_alvo = s("chutes_gol")
    xg_total = s("xg")
    desarmes = s("total_desarmes")
    field = SOFASCORE_METRICS.get(metric, {}).get("field")
    total_stat = s(field) if field else 0
    taxa_conv = (100.0 * convertidas / criadas) if criadas > 0 else None
    taxa_alvo = (100.0 * no_alvo / chutes) if chutes > 0 else None
    base = {
        "por_jogo": (total_stat / n) if n and field else None,
        "convertidas": int(convertidas),
        "criadas": int(criadas),
        "taxa_conv": round(taxa_conv, 2) if taxa_conv is not None else None,
        "no_alvo": int(no_alvo),
        "total_chutes": int(chutes),
        "taxa_alvo": round(taxa_alvo, 2) if taxa_alvo is not None else None,
        "xg_total": round(xg_total, 2),
        "xg_diff": round(gf - xg_total, 2) if n else None,
        "passes": int(s("passes")),
        "passes_certos": int(s("passes_certos")),
        "total_desarmes": int(desarmes),
        "tackle_pct_val": round(a("percentual_desarmes_vencidos"), 2) if row.get("n_percentual_desarmes_vencidos") else None,
        "total_stat": int(total_stat) if field else None,
    }
    if metric == "big_chances":
        base["por_jogo"] = (criadas / n) if n else None
    elif metric == "big_chances_scored":
        base["por_jogo"] = (convertidas / n) if n else None
    return base


GOALS_BANDS = ("0-15", "16-30", "31-45", "46-60", "61-75", "76-90", "90+")
GOALS_RESULT_METRICS = {
    "opens_score": {"label": "Abre o placar", "kind": "open_rate"},
    "opens_and_wins": {"label": "Abre o placar e vence", "kind": "open_outcome", "outcome": "win"},
    "opens_and_equalized": {"label": "Abre o placar e sofre o empate", "kind": "open_outcome", "outcome": "equalized"},
    "opens_and_overturned": {"label": "Abre o placar e sofre a virada", "kind": "open_outcome", "outcome": "overturned"},
    "goals_band_0_15": {"label": "Gols por minuto (0 - 15)", "kind": "band", "band": "0-15"},
    "goals_band_16_30": {"label": "Gols por minuto (16 - 30)", "kind": "band", "band": "16-30"},
    "goals_band_31_45": {"label": "Gols por minuto (31 - 45)", "kind": "band", "band": "31-45"},
    "goals_band_46_60": {"label": "Gols por minuto (46 - 60)", "kind": "band", "band": "46-60"},
    "goals_band_61_75": {"label": "Gols por minuto (61 - 75)", "kind": "band", "band": "61-75"},
    "goals_band_76_90": {"label": "Gols por minuto (76 - 90)", "kind": "band", "band": "76-90"},
    "goals_band_90p": {"label": "Gols por minuto (90+)", "kind": "band", "band": "90+"},
}


def _map_goal_band(label: str | None) -> str | None:
    if not label:
        return None
    if label == "45+":
        return "31-45"
    return label if label in GOALS_BANDS else None


def _sofascore_columns():
    with history_connection() as conn:
        return {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema=:s AND table_name='jogo_completo'
                    """
                ),
                {"s": settings.history_schema},
            )
        }


def sofascore_ranking(metric, country_id, competition_id, season, venue, divisao=None, formato=None, year=None, min_games=5):
    """Ranking por métricas de jogo_completo (SofaScore)."""
    spec = SOFASCORE_METRICS.get(metric)
    if not spec:
        raise ValueError("Ranking inválido.")
    cols = _sofascore_columns()
    needed = {spec.get("field"), spec.get("num"), spec.get("den")} - {None}
    missing = [c for c in needed if c not in cols]
    if missing:
        return {
            "rows": [],
            "direction": "asc" if spec.get("lower_better") else "desc",
            "unit": spec["unit"],
            "warning": f"Coluna(s) ausente(s) em jogo_completo: {', '.join(missing)}.",
            "decimals": spec.get("decimals", 1),
        }

    comp = _competition_meta(competition_id)
    country_name = comp["pais"] if comp else _country_name(country_id)
    jc = f"{settings.history_schema}.jogo_completo"
    jg = f"{settings.history_schema}.jogos"
    ht = f"{settings.history_schema}.{settings.history_table}"

    rules = [
        "j.gols_casa IS NOT NULL",
        "j.gols_fora IS NOT NULL",
        "(jc.id_clube = j.id_mandante OR jc.id_clube = j.id_visitante)",
    ]
    params: dict = {"min_games": int(min_games)}
    if country_name:
        rules.append("COALESCE(jc.pais, j.pais) = :country")
        params["country"] = country_name
    if comp:
        rules.append("COALESCE(jc.campeonato, j.campeonato) = :competition")
        params["competition"] = comp["nome"]
    if season:
        rules.append("COALESCE(jc.temporada::text, j.temporada::text) = :season")
        params["season"] = season
    if year is not None:
        rules.append("EXTRACT(YEAR FROM j.data)::int = :year")
        params["year"] = year
    if venue == "home":
        rules.append("jc.id_clube = j.id_mandante")
    elif venue == "away":
        rules.append("jc.id_clube = j.id_visitante")

    join_hist = ""
    if divisao or formato:
        join_hist = f"""
            INNER JOIN {ht} h ON h.data = j.data
              AND BTRIM(h.pais::text) = BTRIM(COALESCE(jc.pais, j.pais)::text)
              AND BTRIM(h.campeonato::text) = BTRIM(COALESCE(jc.campeonato, j.campeonato)::text)
              AND ((jc.id_clube = j.id_mandante AND BTRIM(h.casa::text) = BTRIM(j.mandante::text)
                    AND BTRIM(h.fora::text) = BTRIM(j.visitante::text))
                   OR (jc.id_clube = j.id_visitante AND BTRIM(h.casa::text) = BTRIM(j.mandante::text)
                    AND BTRIM(h.fora::text) = BTRIM(j.visitante::text)))
        """
        if divisao:
            rules.append("BTRIM(h.divisao::text) = :divisao")
            params["divisao"] = divisao
        if formato:
            rules.append("BTRIM(h.formato::text) = :formato")
            params["formato"] = formato

    field_exprs = []
    for name in (
        "total_chutes", "chutes_gol", "posse_bola", "passes", "passes_certos", "total_desarmes",
        "xg", "grandes_chances_criadas", "grandes_chances_convertidas", "grandes_chances_perdidas",
        "escanteios",
        "interceptacoes", "recuperacoes_bola", "percentual_duelos_vencidos", "percentual_dribles_certos",
        "percentual_desarmes_vencidos",
        "chutes_dentro_area", "defesas_goleiro", "cartoes_amarelos", "cartoes_vermelhos",
        "faltas", "impedimentos", "bolas_na_trave", "cruzamentos_certos", "bolas_longas_certas",
        "passes_profundidade_certos",
    ):
        if name in cols:
            field_exprs.append(f"SUM(COALESCE(jc.{name}::float,0)) AS sum_{name}")
            field_exprs.append(f"AVG(jc.{name}::float) AS avg_{name}")
            field_exprs.append(f"COUNT(jc.{name}) AS n_{name}")

    sql = f"""
        SELECT jc.id_clube,
               MAX(COALESCE(jc.nome_clube, CASE WHEN jc.id_clube=j.id_mandante THEN j.mandante ELSE j.visitante END)) AS clube,
               MAX(COALESCE(jc.pais, j.pais)) AS pais,
               COUNT(*)::int AS jogos,
               SUM(CASE WHEN jc.id_clube=j.id_mandante THEN j.gols_casa ELSE j.gols_fora END)::float AS gols_marcados,
               SUM(CASE WHEN jc.id_clube=j.id_mandante THEN j.gols_fora ELSE j.gols_casa END)::float AS gols_sofridos,
               {', '.join(field_exprs) if field_exprs else '1 AS _pad'}
        FROM {jc} jc
        JOIN {jg} j ON j.id_jogo = jc.id_jogo
        {join_hist}
        WHERE {' AND '.join(rules)}
        GROUP BY jc.id_clube
        HAVING COUNT(*) >= :min_games
    """
    try:
        with history_connection() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    except Exception as exc:
        return {
            "rows": [],
            "direction": "desc",
            "unit": spec["unit"],
            "warning": f"Falha ao consultar jogo_completo ({type(exc).__name__}).",
            "decimals": spec.get("decimals", 1),
        }

    by_id, mapping = _registered_directory()
    out = []
    for row in rows:
        n = int(row["jogos"] or 0)
        gf = float(row.get("gols_marcados") or 0)
        ga = float(row.get("gols_sofridos") or 0)
        mode = spec["mode"]
        value = None
        if mode == "sum":
            value = float(row.get(f"sum_{spec['field']}") or 0)
            if int(row.get(f"n_{spec['field']}") or 0) == 0:
                continue
        elif mode == "avg":
            if int(row.get(f"n_{spec['field']}") or 0) == 0:
                continue
            value = float(row.get(f"avg_{spec['field']}") or 0)
        elif mode == "per_goal":
            total = float(row.get(f"sum_{spec['field']}") or 0)
            if gf <= 0 or int(row.get(f"n_{spec['field']}") or 0) == 0:
                continue
            value = total / gf
        elif mode == "ratio_pct":
            num = float(row.get(f"sum_{spec['num']}") or 0)
            den = float(row.get(f"sum_{spec['den']}") or 0)
            if den <= 0:
                continue
            value = 100.0 * num / den
        if value is None:
            continue

        club_name = str(row.get("clube") or "")
        country = str(row.get("pais") or "")
        key, meta = _identity(country, club_name, by_id, mapping)
        # Preferência: id cadastrado quando o id_clube SofaScore coincidir com cadastro.
        sid = row.get("id_clube")
        if isinstance(sid, int) and sid in by_id:
            meta = {
                "clube_id": sid,
                "clube": by_id[sid]["nome"],
                "escudo_url": by_id[sid].get("escudo_url"),
                "pais_id": by_id[sid].get("pais_id"),
                "pais": by_id[sid].get("pais") or country,
            }
        aux = _sofa_aux_fields(metric, row, n, gf)
        # Grandes chances: destaca o total, ordena pela média/jogo.
        sort_key = value
        if metric == "big_chances" and n:
            sort_key = float(row.get("sum_grandes_chances_criadas") or 0) / n
        elif metric == "big_chances_scored" and n:
            sort_key = float(row.get("sum_grandes_chances_convertidas") or 0) / n
        out.append({
            **meta,
            **aux,
            "valor": round(value, 4),
            "sort_valor": round(sort_key, 4),
            "jogos": n,
            "gols_marcados": int(gf),
            "gols_sofridos": int(ga),
            "saldo_gols": int(gf - ga),
            "mgm": gf / n if n else None,
            "mgs": ga / n if n else None,
            "metrica": spec["label"],
            "temporada": season or "Todas",
        })

    lower = bool(spec.get("lower_better"))
    out.sort(key=lambda x: (
        float(x.get("sort_valor", x["valor"])) if lower else -float(x.get("sort_valor", x["valor"])),
        str(x["clube"]).casefold(),
    ))
    for i, row in enumerate(out, 1):
        row["posicao"] = i
    return {
        "rows": out,
        "columns": _sofa_columns(metric, spec),
        "direction": "asc" if lower else "desc",
        "unit": spec["unit"],
        "decimals": spec.get("decimals", 1),
        "lower_is_better": lower,
        "warning": None if out else (
            f"Nenhum clube com amostra suficiente em jogo_completo para este recorte (mín. {min_games} jogos)."
        ),
        "min_games": min_games,
    }


def _goals_result_columns(metric: str, spec: dict) -> list[dict]:
    main = _col("valor", spec["label"], decimals=1,
                format="number", suffix="%" if spec["kind"] != "band" else "", role="main")
    if spec["kind"] == "band":
        main = _col("valor", spec["label"], decimals=2, role="main")
        return [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("gols_faixa", "Gols na faixa", format="int"),
            _col("taxa_gols", "% dos gols", decimals=1, suffix="%"),
            _col("gols_marcados", "Gols totais", format="int"),
        ]
    if spec["kind"] == "open_rate":
        return [
            main,
            _col("jogos", "Jogos", format="int"),
            _col("aberturas", "Aberturas", format="int"),
            _col("mgm", "MGM", decimals=2),
            _col("mgs", "MGS", decimals=2),
        ]
    return [
        main,
        _col("jogos", "Jogos", format="int"),
        _col("aberturas", "Aberturas", format="int"),
        _col("ocorrencias", "Ocorrências", format="int"),
        _col("mgm", "MGM", decimals=2),
    ]


def goals_result_ranking(metric, country_id, competition_id, season, venue, divisao=None, formato=None, year=None, min_games=5):
    """Rankings de abertura de placar e gols por faixa (jogos + minutos_gols)."""
    from . import goal_timeline_service as timeline

    spec = GOALS_RESULT_METRICS.get(metric)
    if not spec:
        raise ValueError("Ranking inválido.")
    min_games = int(min_games)

    comp = _competition_meta(competition_id)
    country_name = comp["pais"] if comp else _country_name(country_id)
    jg = f"{settings.history_schema}.jogos"
    ht = f"{settings.history_schema}.{settings.history_table}"
    rules = [
        "j.gols_casa IS NOT NULL",
        "j.gols_fora IS NOT NULL",
        "j.data < CURRENT_DATE",
    ]
    params: dict = {"cap": 40_000}
    if country_name:
        rules.append("j.pais = :country")
        params["country"] = country_name
    if comp:
        rules.append("j.campeonato = :competition")
        params["competition"] = comp["nome"]
    if season:
        rules.append("j.temporada::text = :season")
        params["season"] = season
    if year is not None:
        rules.append("EXTRACT(YEAR FROM j.data)::int = :year")
        params["year"] = year

    join_hist = ""
    if divisao or formato:
        join_hist = f"""
            INNER JOIN {ht} h ON h.data = j.data
              AND BTRIM(h.pais::text) = BTRIM(j.pais::text)
              AND BTRIM(h.campeonato::text) = BTRIM(j.campeonato::text)
              AND BTRIM(h.casa::text) = BTRIM(j.mandante::text)
              AND BTRIM(h.fora::text) = BTRIM(j.visitante::text)
        """
        if divisao:
            rules.append("BTRIM(h.divisao::text) = :divisao")
            params["divisao"] = divisao
        if formato:
            rules.append("BTRIM(h.formato::text) = :formato")
            params["formato"] = formato

    sql = f"""
        SELECT DISTINCT j.id_jogo, j.data, j.pais, j.campeonato,
               j.mandante AS casa, j.visitante AS fora,
               j.gols_casa AS gh, j.gols_fora AS ga,
               j.id_mandante, j.id_visitante
        FROM {jg} j
        {join_hist}
        WHERE {' AND '.join(rules)}
        ORDER BY j.data DESC, j.id_jogo DESC
        LIMIT :cap
    """
    try:
        with history_connection() as conn:
            games = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    except Exception as exc:
        return {
            "rows": [], "columns": _goals_result_columns(metric, spec),
            "direction": "desc", "unit": "%" if spec["kind"] != "band" else "média",
            "decimals": 1 if spec["kind"] != "band" else 2,
            "warning": f"Falha ao consultar jogos ({type(exc).__name__}).",
        }

    if not games:
        return {
            "rows": [], "columns": _goals_result_columns(metric, spec),
            "direction": "desc", "unit": "%" if spec["kind"] != "band" else "média",
            "decimals": 1 if spec["kind"] != "band" else 2,
            "warning": "Nenhuma partida no recorte.",
        }

    try:
        events_by_game, timeline_error = timeline.fetch([g["id_jogo"] for g in games])
    except Exception as exc:
        return {
            "rows": [], "columns": _goals_result_columns(metric, spec),
            "direction": "desc", "unit": "%" if spec["kind"] != "band" else "média",
            "decimals": 1 if spec["kind"] != "band" else 2,
            "warning": f"Falha ao consultar minutos_gols ({type(exc).__name__}).",
        }

    # Agrega por clube (id SofaScore).
    clubs: dict = {}
    for g in games:
        for side, cid, name in (
            ("h", g.get("id_mandante"), g["casa"]),
            ("a", g.get("id_visitante"), g["fora"]),
        ):
            if cid is None:
                continue
            if venue == "home" and side != "h":
                continue
            if venue == "away" and side != "a":
                continue
            bucket = clubs.setdefault(cid, {
                "id_clube": cid, "clube": name, "pais": g.get("pais") or "",
                "valid": 0, "opened": 0, "won": 0, "equalized": 0, "overturned": 0,
                "gf": 0, "ga": 0, "goals": 0, "bands": dict.fromkeys(GOALS_BANDS, 0),
            })
            events = timeline._sequence(g, events_by_game.get(str(g["id_jogo"]), []))
            if events is None:
                continue
            bucket["valid"] += 1
            home = side == "h"
            gf = int(g["gh"] if home else g["ga"])
            ga = int(g["ga"] if home else g["gh"])
            bucket["gf"] += gf
            bucket["ga"] += ga
            first = events[0]["side"] if events else None
            if first == side:
                bucket["opened"] += 1
                equalized = False
                for ev in events[1:]:
                    own, other = (ev["score"][0], ev["score"][1]) if home else (ev["score"][1], ev["score"][0])
                    old_own, old_other = (ev["before"][0], ev["before"][1]) if home else (ev["before"][1], ev["before"][0])
                    if ev["side"] != side and own == other and old_own > old_other:
                        equalized = True
                        break
                bucket["equalized"] += int(equalized)
                bucket["won"] += int(gf > ga)
                bucket["overturned"] += int(gf < ga)
            for ev in events:
                if ev["side"] != side:
                    continue
                mapped = _map_goal_band(ev.get("band"))
                if mapped:
                    bucket["bands"][mapped] += 1
                    bucket["goals"] += 1

    by_id, mapping = _registered_directory()
    out = []
    band = spec.get("band")
    for cid, b in clubs.items():
        n = b["valid"]
        if n < min_games:
            continue
        opened = b["opened"]
        if spec["kind"] == "open_rate":
            if n <= 0:
                continue
            value = 100.0 * opened / n
            ocorrencias = opened
        elif spec["kind"] == "open_outcome":
            if opened <= 0:
                continue
            key = {"win": "won", "equalized": "equalized", "overturned": "overturned"}[spec["outcome"]]
            ocorrencias = b[key]
            value = 100.0 * ocorrencias / opened
        else:
            gols_faixa = b["bands"].get(band, 0)
            value = gols_faixa / n
            ocorrencias = gols_faixa

        club_name = str(b["clube"] or "")
        country = str(b["pais"] or "")
        _, meta = _identity(country, club_name, by_id, mapping)
        if isinstance(cid, int) and cid in by_id:
            meta = {
                "clube_id": cid,
                "clube": by_id[cid]["nome"],
                "escudo_url": by_id[cid].get("escudo_url"),
                "pais_id": by_id[cid].get("pais_id"),
                "pais": by_id[cid].get("pais") or country,
            }
        gols_faixa = b["bands"].get(band, 0) if band else 0
        goals_total = b["goals"]
        out.append({
            **meta,
            "valor": round(value, 4),
            "jogos": n,
            "aberturas": opened,
            "ocorrencias": ocorrencias if spec["kind"] != "open_rate" else opened,
            "gols_faixa": gols_faixa,
            "taxa_gols": round(100.0 * gols_faixa / goals_total, 2) if band and goals_total else None,
            "gols_marcados": b["gf"],
            "gols_sofridos": b["ga"],
            "mgm": b["gf"] / n if n else None,
            "mgs": b["ga"] / n if n else None,
            "metrica": spec["label"],
            "temporada": season or "Todas",
        })

    out.sort(key=lambda x: (-float(x["valor"]), -int(x.get("jogos") or 0), str(x["clube"]).casefold()))
    for i, row in enumerate(out, 1):
        row["posicao"] = i
    warning = timeline_error
    if not out and not warning:
        warning = f"Nenhum clube com amostra suficiente (mín. {min_games} jogos com minutos_gols válidos)."
    if len(games) >= 40_000:
        warning = ((warning + " ") if warning else "") + (
            "Amostra limitada às 40.000 partidas mais recentes do recorte."
        )
    return {
        "rows": out,
        "columns": _goals_result_columns(metric, spec),
        "direction": "desc",
        "unit": "%" if spec["kind"] != "band" else "média",
        "decimals": 1 if spec["kind"] != "band" else 2,
        "warning": warning,
        "min_games": min_games,
    }


def ranking(metric, country_id=None, competition_id=None, season=None, venue="all",
            divisao=None, formato=None, year=None, min_games=None):
    # O frontend usa "all" para representar todas as temporadas / todos os anos.
    normalized_season = None if season in (None, "", "all") else season
    normalized_year = _normalize_year(year)
    normalized_min = _normalize_min_games(min_games, default=5)
    divisao = str(divisao or "").strip() or None
    formato = str(formato or "").strip() or None
    if metric=="elo":
        return elo_ranking(country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year)
    if metric=="offense":
        return strength_ranking("offense",country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year)
    if metric=="defense":
        return strength_ranking("defense",country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year)
    if metric=="market":
        return market_ranking(country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year)
    if metric in {"5","10","20","season","history"}:
        return performance_ranking(metric,country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year,normalized_min)
    if metric in {"over15","over25","btts"}:
        return threshold_ranking(metric,country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year,normalized_min)
    if metric in SOFASCORE_METRICS:
        return sofascore_ranking(metric,country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year,normalized_min)
    if metric in GOALS_RESULT_METRICS:
        return goals_result_ranking(metric,country_id,competition_id,normalized_season,venue,divisao,formato,normalized_year,normalized_min)
    raise ValueError("Ranking inválido.")


