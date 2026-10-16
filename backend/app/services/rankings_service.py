from __future__ import annotations

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


def filters(country_id: int | None = None):
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
    return {
        "countries": countries,
        "competitions": competitions,
        "seasons": seasons,
        "current_season": seasons[0] if seasons else None,
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

    with history_connection() as conn:
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
):
    by_id, mapping = _registered_directory()
    games = _history_games(
        country_id,
        competition_id,
        exact_season=season if exact_season else None,
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


def _period_stats(country_id, competition_id, season, venue):
    """MGM/MGS do recorte. season=None significa todo o histórico."""
    meta, series = _history_series(
        country_id,
        competition_id,
        season,
        venue,
        exact_season=bool(season),
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


def _enrich_rows_with_season_stats(rows, country_id, competition_id, season, venue):
    by_id, by_name = _period_stats(country_id, competition_id, season, venue)
    for row in rows:
        stats = by_id.get(int(row["clube_id"])) if isinstance(row.get("clube_id"), int) else None
        if not stats:
            stats = by_name.get((normalize_name(row.get("pais") or ""), normalize_name(row.get("clube") or "")), {})
        row["mgm"] = stats.get("mgm")
        row["mgs"] = stats.get("mgs")
    return rows


def elo_ranking(country_id, competition_id, season, venue):
    clauses, params = [], {}
    if country_id:
        clauses.append("p.id = :country"); params["country"] = country_id
    if competition_id:
        clauses.append("e.campeonato_id = :competition"); params["competition"] = competition_id
    if season:
        clauses.append("e.temporada = :season"); params["season"] = season
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

    out = _enrich_rows_with_season_stats(out, country_id, competition_id, season, venue)
    out.sort(key=lambda x: (-float(x["valor"]), str(x["clube"]).casefold()))
    for i, row in enumerate(out, 1):
        row["posicao"] = i
        row["metrica"] = "ELO médio" if not season else "ELO"
    return {"rows": out, "direction": "desc", "unit": "pts", "all_seasons": not bool(season)}


def _history_strengths(country_id, competition_id, season):
    by_id, mapping = _registered_directory()
    games = _history_games(country_id, competition_id, exact_season=season or None)
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


def strength_ranking(metric, country_id, competition_id, season, venue):
    rows=_history_strengths(country_id, competition_id, season)
    suffix="_casa" if venue=="home" else "_fora" if venue=="away" else ""
    field=("forca_ofensiva" if metric=="offense" else "forca_defensiva")+suffix
    out=[]
    for row in rows:
        value=row.get(field)
        if value is None: continue
        item=dict(row); item["valor"]=float(value); item["metrica"]="Força ofensiva" if metric=="offense" else "Força defensiva"; out.append(item)
    out=_enrich_rows_with_season_stats(out,country_id,competition_id,season,venue)
    reverse=metric=="offense"
    out.sort(key=lambda x:(-float(x["valor"]) if reverse else float(x["valor"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc" if reverse else "asc","unit":"índice","defense_lower_is_better":metric=="defense"}


def market_ranking(country_id, competition_id, season, venue):
    clauses, params = [], {}
    if country_id:
        clauses.append("p.id = :country"); params["country"] = country_id
    if competition_id:
        clauses.append("vm.campeonato_id = :competition"); params["competition"] = competition_id
    if season:
        clauses.append("vm.temporada = :season"); params["season"] = season
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

    rows=_enrich_rows_with_season_stats(rows,country_id,competition_id,season,venue)
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


def performance_ranking(period, country_id, competition_id, season, venue):
    meta, series=_history_series(country_id,competition_id,season,venue,exact_season=False)
    limit=int(period) if period in {"5","10","20"} else None
    out=[]
    for key,all_rows in series.items():
        rows=all_rows
        if limit: rows=rows[:limit]
        elif period=="season": rows=[r for r in rows if not season or r["season"]==season]
        if not rows: continue
        item=_stats_item(meta[key],rows); item["temporada"]=season; out.append(item)
    out.sort(key=lambda x:(-float(x["valor"]),-int(x["saldo_gols"]),-int(x["vitorias"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc","unit":"%"}


def threshold_ranking(metric, country_id, competition_id, season, venue):
    meta, series=_history_series(country_id,competition_id,season,venue,exact_season=True)
    labels={"over15":"Over 1,5","over25":"Over 2,5","btts":"Ambos marcam"}
    out=[]
    for key,rows in series.items():
        if not rows: continue
        if metric=="over15": hits=sum(r["total"]>1.5 for r in rows)
        elif metric=="over25": hits=sum(r["total"]>2.5 for r in rows)
        else: hits=sum(bool(r["btts"]) for r in rows)
        item=_stats_item(meta[key],rows,labels[metric]); item["valor"]=hits; item["taxa"]=hits/len(rows)*100; item["temporada"]=season; out.append(item)
    out.sort(key=lambda x:(-int(x["valor"]),-float(x["taxa"]),-int(x["jogos"]),str(x["clube"]).casefold()))
    for i,row in enumerate(out,1): row["posicao"]=i
    return {"rows":out,"direction":"desc","unit":"jogos"}


def ranking(metric, country_id=None, competition_id=None, season=None, venue="all"):
    # O frontend usa "all" para representar todas as temporadas.
    normalized_season = None if season in (None, "", "all") else season
    if metric=="elo": return elo_ranking(country_id,competition_id,normalized_season,venue)
    if metric=="offense": return strength_ranking("offense",country_id,competition_id,normalized_season,venue)
    if metric=="defense": return strength_ranking("defense",country_id,competition_id,normalized_season,venue)
    if metric=="market": return market_ranking(country_id,competition_id,normalized_season,venue)
    if metric in {"5","10","20","season","history"}: return performance_ranking(metric,country_id,competition_id,normalized_season,venue)
    if metric in {"over15","over25","btts"}: return threshold_ranking(metric,country_id,competition_id,normalized_season,venue)
    raise ValueError("Ranking inválido.")


