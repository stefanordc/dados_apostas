import math
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from datetime import date, datetime
from sqlalchemy import text
from ..config import settings
from ..db import app_engine
from ..repositories.history_repository import competition_games

BETA = 100.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
RETENTION = 0.80
PERF_WEIGHT = 0.80
MARKET_WEIGHT = 0.20


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def season_key(season: str):
    nums = re.findall(r"\d{4}", season or "")
    return tuple(int(x) for x in nums[:2]) or (0,)


def _competition_meta(competition_id: int):
    with app_engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT c.id, c.nome AS competition, c.pais_id, c.principal, p.nome AS country
            FROM {settings.app_schema}.campeonatos c
            JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
            WHERE c.id = :id
        """), {"id":competition_id}).mappings().first()
    if not row: raise ValueError("Campeonato não encontrado.")
    return dict(row)


def _club_registry(competition_id: int, season: str):
    with app_engine.connect() as conn:
        clubs = conn.execute(text(f"""
            SELECT cl.id, cl.nome, cl.escudo_url, cl.pais_id
            FROM {settings.app_schema}.clubes_campeonatos cc
            JOIN {settings.app_schema}.clubes cl ON cl.id = cc.clube_id
            WHERE cc.campeonato_id = :competition_id AND cc.temporada = :season
            ORDER BY cl.nome
        """), {"competition_id":competition_id,"season":season}).mappings().all()
        aliases = conn.execute(text(f"""
            SELECT a.clube_id, a.alias
            FROM {settings.app_schema}.clubes_aliases a
            WHERE a.campeonato_id = :competition_id OR a.campeonato_id IS NULL
        """), {"competition_id":competition_id}).mappings().all()
    mapping={}
    for c in clubs: mapping[normalize_name(c["nome"])]=c["id"]
    club_ids={c["id"] for c in clubs}
    for a in aliases:
        if a["clube_id"] in club_ids: mapping[normalize_name(a["alias"])]=a["clube_id"]
    return [dict(c) for c in clubs], mapping


def elo_status(competition_id: int, season: str):
    with app_engine.connect() as conn:
        counts = conn.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {settings.app_schema}.clubes_campeonatos WHERE campeonato_id=:c AND temporada=:s)::int expected,
              (SELECT COUNT(*) FROM {settings.app_schema}.valores_mercado WHERE campeonato_id=:c AND temporada=:s)::int valued
        """), {"c":competition_id,"s":season}).mappings().one()
        st = conn.execute(text(f"""
            SELECT completo, jogos_processados, jogos_ignorados, atualizado_em
            FROM {settings.app_schema}.elo_temporadas
            WHERE campeonato_id=:c AND temporada=:s
        """), {"c":competition_id,"s":season}).mappings().first()
    out={"clubes_esperados":counts["expected"],"clubes_com_valor":counts["valued"],"pronto":counts["expected"]>1 and counts["expected"]==counts["valued"]}
    if st: out.update(dict(st))
    return out


def rebuild_elo(competition_id: int, season: str, force: bool = False):
    if "_relative_strengths" in globals():
        _relative_strengths.cache_clear()
    meta=_competition_meta(competition_id)
    clubs, name_map=_club_registry(competition_id, season)
    expected=len(clubs)
    with app_engine.connect() as conn:
        values=[dict(r) for r in conn.execute(text(f"""
            SELECT vm.clube_id, vm.valor::float AS valor, vm.moeda
            FROM {settings.app_schema}.valores_mercado vm
            WHERE vm.campeonato_id=:c AND vm.temporada=:s
        """), {"c":competition_id,"s":season}).mappings().all()]
    if expected < 2:
        return {"status":"aguardando","message":"Cadastre os clubes da temporada antes de calcular o ELO.", **elo_status(competition_id,season)}
    if len(values) != expected and not force:
        return {"status":"aguardando","message":"O ELO será calculado quando todos os clubes tiverem valor de mercado.", **elo_status(competition_id,season)}
    currencies={v["moeda"] for v in values}
    if len(currencies)>1:
        return {"status":"erro","message":"Todos os clubes do campeonato/temporada precisam usar a mesma moeda no valor de mercado."}
    value_by={v["clube_id"]:float(v["valor"]) for v in values if float(v["valor"])>0}
    if len(value_by)!=expected:
        return {"status":"erro","message":"Há clube sem valor de mercado válido."}
    geomean=math.exp(sum(math.log(v) for v in value_by.values())/len(value_by))
    market={cid:1500.0+BETA*math.log(v/geomean,2) for cid,v in value_by.items()}

    with app_engine.connect() as conn:
        prev_seasons=[r[0] for r in conn.execute(text(f"SELECT DISTINCT temporada FROM {settings.app_schema}.elo_clubes WHERE campeonato_id=:c"),{"c":competition_id}).all()]
    prev_candidates=[s for s in prev_seasons if season_key(s)<season_key(season)]
    prev_season=max(prev_candidates,key=season_key) if prev_candidates else None
    prev={}; prev_mean=1500.0
    if prev_season:
        with app_engine.connect() as conn:
            rows=conn.execute(text(f"SELECT clube_id, elo_atual::float FROM {settings.app_schema}.elo_clubes WHERE campeonato_id=:c AND temporada=:s"),{"c":competition_id,"s":prev_season}).all()
        prev={int(cid):float(e) for cid,e in rows}
        if prev: prev_mean=sum(prev.values())/len(prev)

    raw={}
    for cid in value_by:
        if cid in prev:
            perf=1500.0+RETENTION*(prev[cid]-prev_mean)
            raw[cid]=PERF_WEIGHT*perf+MARKET_WEIGHT*market[cid]
        else:
            raw[cid]=market[cid]
    raw_mean=sum(raw.values())/len(raw)
    initial={cid:r-raw_mean+1500.0 for cid,r in raw.items()}
    ratings=initial.copy(); maxima=initial.copy(); minima=initial.copy(); games_count=defaultdict(int)

    games=competition_games(meta["country"], meta["competition"], season)
    movements=[]; ignored=0
    for g in games:
        h=name_map.get(normalize_name(g["casa"])); a=name_map.get(normalize_name(g["fora"]))
        if not h or not a or h not in ratings or a not in ratings:
            ignored+=1; continue
        rh,ra=ratings[h],ratings[a]
        expected_home=1.0/(1.0+10**((ra-(rh+HOME_ADVANTAGE))/400.0))
        gh,gf=int(g["gols_casa"]),int(g["gols_fora"])
        actual=1.0 if gh>gf else 0.5 if gh==gf else 0.0
        delta=K_FACTOR*(actual-expected_home)
        ratings[h]=rh+delta; ratings[a]=ra-delta
        maxima[h]=max(maxima[h],ratings[h]); maxima[a]=max(maxima[a],ratings[a])
        minima[h]=min(minima[h],ratings[h]); minima[a]=min(minima[a],ratings[a])
        games_count[h]+=1; games_count[a]+=1
        d=g.get("data")
        if isinstance(d, datetime): d=d.date()
        game_key=str(g.get("jogo_id") or g.get("id"))
        movements.append({"game_key":game_key,"data":d,"rodada":str(g.get("rodada") or ''),"h":h,"a":a,"gh":gh,"gf":gf,"rh":rh,"ra":ra,"exp":expected_home,"actual":actual,"delta":delta,"nh":ratings[h],"na":ratings[a]})

    with app_engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {settings.app_schema}.elo_movimentos WHERE campeonato_id=:c AND temporada=:s"),{"c":competition_id,"s":season})
        conn.execute(text(f"DELETE FROM {settings.app_schema}.elo_clubes WHERE campeonato_id=:c AND temporada=:s"),{"c":competition_id,"s":season})
        for cid in sorted(ratings):
            conn.execute(text(f"""
                INSERT INTO {settings.app_schema}.elo_clubes
                (campeonato_id,temporada,clube_id,elo_mercado,elo_inicial,elo_atual,elo_max,elo_min,jogos)
                VALUES (:c,:s,:cid,:market,:initial,:current,:max,:min,:games)
            """), {"c":competition_id,"s":season,"cid":cid,"market":market[cid],"initial":initial[cid],"current":ratings[cid],"max":maxima[cid],"min":minima[cid],"games":games_count[cid]})
        for m in movements:
            conn.execute(text(f"""
                INSERT INTO {settings.app_schema}.elo_movimentos
                (campeonato_id,temporada,history_game_key,data,rodada,casa_clube_id,fora_clube_id,gols_casa,gols_fora,
                 elo_casa_antes,elo_fora_antes,expectativa_casa,resultado_casa,delta_casa,elo_casa_depois,elo_fora_depois)
                VALUES (:c,:s,:game_key,:data,:rodada,:h,:a,:gh,:gf,:rh,:ra,:exp,:actual,:delta,:nh,:na)
            """), {"c":competition_id,"s":season,**m})
        conn.execute(text(f"""
            INSERT INTO {settings.app_schema}.elo_temporadas
            (pais_id,campeonato_id,temporada,completo,clubes_esperados,clubes_com_valor,jogos_processados,jogos_ignorados,beta,k_factor,vantagem_mando,retencao,peso_performance,peso_mercado,atualizado_em)
            VALUES (:p,:c,:s,TRUE,:expected,:valued,:processed,:ignored,:beta,:k,:ha,:ret,:pw,:mw,NOW())
            ON CONFLICT (campeonato_id,temporada) DO UPDATE SET
              completo=TRUE,clubes_esperados=EXCLUDED.clubes_esperados,clubes_com_valor=EXCLUDED.clubes_com_valor,
              jogos_processados=EXCLUDED.jogos_processados,jogos_ignorados=EXCLUDED.jogos_ignorados,atualizado_em=NOW()
        """), {"p":meta["pais_id"],"c":competition_id,"s":season,"expected":expected,"valued":len(values),"processed":len(movements),"ignored":ignored,"beta":BETA,"k":K_FACTOR,"ha":HOME_ADVANTAGE,"ret":RETENTION,"pw":PERF_WEIGHT,"mw":MARKET_WEIGHT})
    return {"status":"ok","message":"ELO calculado.","jogos_processados":len(movements),"jogos_ignorados":ignored,"clubes":expected}


def rebuild_if_complete(competition_id:int, season:str):
    st=elo_status(competition_id,season)
    return rebuild_elo(competition_id,season) if st["pronto"] else {"status":"aguardando",**st}


def filters():
    with app_engine.connect() as conn:
        countries=[dict(r) for r in conn.execute(text(f"""
            SELECT DISTINCT p.id,p.nome FROM {settings.app_schema}.valores_mercado vm
            JOIN {settings.app_schema}.paises p ON p.id=vm.pais_id ORDER BY p.nome
        """)).mappings()]
        seasons=[str(r[0]) for r in conn.execute(text(f"SELECT DISTINCT temporada FROM {settings.app_schema}.valores_mercado")).all()]
    seasons=sorted(seasons,key=season_key,reverse=True)
    return {"countries":countries,"seasons":seasons}




@lru_cache(maxsize=256)
def _relative_strengths(competition_id: int, season: str):
    """Return attack/defense factors adjusted for home/away league baselines.

    1.00 is league average.
    Offensive strength > 1.00 means scoring above the league baseline.
    Defensive strength < 1.00 means conceding below the league baseline (better).
    Home/away splits are also returned so matchup analysis can respect venue.
    """
    meta = _competition_meta(competition_id)
    clubs, name_map = _club_registry(competition_id, season)
    games = competition_games(meta["country"], meta["competition"], season)

    valid = []
    for g in games:
        h = name_map.get(normalize_name(g["casa"]))
        a = name_map.get(normalize_name(g["fora"]))
        if not h or not a:
            continue
        valid.append((h, a, int(g["gols_casa"]), int(g["gols_fora"])))

    empty = {
        "forca_ofensiva": None,
        "forca_defensiva": None,
        "forca_ofensiva_casa": None,
        "forca_defensiva_casa": None,
        "forca_ofensiva_fora": None,
        "forca_defensiva_fora": None,
    }
    if not valid:
        return {c["id"]: dict(empty) for c in clubs}

    league_home_avg = sum(x[2] for x in valid) / len(valid)
    league_away_avg = sum(x[3] for x in valid) / len(valid)
    acc = defaultdict(
        lambda: {
            "home_games": 0,
            "away_games": 0,
            "home_gf": 0,
            "home_ga": 0,
            "away_gf": 0,
            "away_ga": 0,
        }
    )

    for h, a, gh, ga in valid:
        acc[h]["home_games"] += 1
        acc[h]["home_gf"] += gh
        acc[h]["home_ga"] += ga
        acc[a]["away_games"] += 1
        acc[a]["away_gf"] += ga
        acc[a]["away_ga"] += gh

    out = {}
    for c in clubs:
        cid = c["id"]
        d = acc[cid]
        hg = d["home_games"]
        ag = d["away_games"]
        total = hg + ag
        if not total:
            out[cid] = dict(empty)
            continue

        attack_home = defense_home = attack_away = defense_away = None
        parts_attack = []
        parts_defense = []

        if hg and league_home_avg > 0 and league_away_avg > 0:
            attack_home = (d["home_gf"] / hg) / league_home_avg
            defense_home = (d["home_ga"] / hg) / league_away_avg
            parts_attack.append((attack_home, hg))
            parts_defense.append((defense_home, hg))

        if ag and league_away_avg > 0 and league_home_avg > 0:
            attack_away = (d["away_gf"] / ag) / league_away_avg
            defense_away = (d["away_ga"] / ag) / league_home_avg
            parts_attack.append((attack_away, ag))
            parts_defense.append((defense_away, ag))

        attack = (
            sum(v * w for v, w in parts_attack) / sum(w for _, w in parts_attack)
            if parts_attack
            else None
        )
        defense = (
            sum(v * w for v, w in parts_defense) / sum(w for _, w in parts_defense)
            if parts_defense
            else None
        )

        out[cid] = {
            "forca_ofensiva": round(attack, 4) if attack is not None else None,
            "forca_defensiva": round(defense, 4) if defense is not None else None,
            "forca_ofensiva_casa": round(attack_home, 4) if attack_home is not None else None,
            "forca_defensiva_casa": round(defense_home, 4) if defense_home is not None else None,
            "forca_ofensiva_fora": round(attack_away, 4) if attack_away is not None else None,
            "forca_defensiva_fora": round(defense_away, 4) if defense_away is not None else None,
        }
    return out


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _registered_seasons(competition_id: int, cutoff: str | None = None):
    with app_engine.connect() as conn:
        seasons = [
            str(r[0]) for r in conn.execute(
                text(f"SELECT DISTINCT temporada FROM {settings.app_schema}.clubes_campeonatos WHERE campeonato_id=:c"),
                {"c": competition_id},
            ).all() if r[0] is not None
        ]
    if cutoff:
        key = season_key(cutoff)
        seasons = [x for x in seasons if season_key(x) <= key]
    return sorted(set(seasons), key=season_key, reverse=True)


def _latest_strength_season(competition_id: int, club_ids: list[int], cutoff: str | None = None):
    """Latest registered season up to cutoff with actual historical match-derived strengths."""
    for candidate in _registered_seasons(competition_id, cutoff):
        strengths = _relative_strengths(competition_id, candidate)
        ok = True
        for cid in club_ids:
            item = strengths.get(cid) or {}
            if item.get("forca_ofensiva") is None or item.get("forca_defensiva") is None:
                ok = False
                break
        if ok:
            return candidate
    return None


def strength_profile(club_id: int, competition_id: int | None = None, season: str | None = None):
    """Historical/current strength profile for one club versus its league peers.

    If the selected/latest registered season has no played matches yet, the current
    comparison falls back to the latest season with real historical match data.
    """
    clauses = ["cc.clube_id = :club"]
    params = {"club": club_id}
    if competition_id:
        clauses.append("cc.campeonato_id = :competition")
        params["competition"] = competition_id

    with app_engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT DISTINCT cc.temporada, c.id AS campeonato_id, c.nome AS campeonato,
                   c.principal, p.nome AS pais
            FROM {settings.app_schema}.clubes_campeonatos cc
            JOIN {settings.app_schema}.campeonatos c ON c.id = cc.campeonato_id
            JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
            WHERE {' AND '.join(clauses)}
        """), params).mappings()]

    if not rows:
        return None

    rows.sort(key=lambda r: (season_key(str(r["temporada"])), bool(r["principal"])), reverse=True)

    requested = None
    if season:
        requested = next((r for r in rows if str(r["temporada"]) == str(season)), None)
    base = requested or rows[0]
    comp_id = int(base["campeonato_id"])
    requested_season = str(base["temporada"])

    effective = _latest_strength_season(comp_id, [club_id], requested_season)
    current_season = effective or requested_season

    same_comp = [r for r in rows if int(r["campeonato_id"]) == comp_id]
    cutoff_key = season_key(current_season)
    hist_seasons = sorted(
        {str(r["temporada"]) for r in same_comp if season_key(str(r["temporada"])) <= cutoff_key},
        key=season_key,
    )

    club_hist_attack = []
    club_hist_defense = []
    peer_hist_attack = []
    peer_hist_defense = []
    current_strengths = {}
    current_peers = {"forca_ofensiva": None, "forca_defensiva": None}

    for s in hist_seasons:
        strengths = _relative_strengths(comp_id, s)
        club_strength = strengths.get(club_id)
        if club_strength:
            club_hist_attack.append(club_strength.get("forca_ofensiva"))
            club_hist_defense.append(club_strength.get("forca_defensiva"))

        peers = [v for cid, v in strengths.items() if cid != club_id and v.get("forca_ofensiva") is not None]
        peer_hist_attack.extend(v.get("forca_ofensiva") for v in peers)
        peer_hist_defense.extend(v.get("forca_defensiva") for v in peers)

        if s == current_season:
            current_strengths = club_strength or {}
            current_peers = {
                "forca_ofensiva": _mean(v.get("forca_ofensiva") for v in peers),
                "forca_defensiva": _mean(v.get("forca_defensiva") for v in peers),
            }

    return {
        "competition_id": comp_id,
        "competition": base["campeonato"],
        "country": base["pais"],
        "requested_season": requested_season,
        "current_season": current_season,
        "used_fallback_season": current_season != requested_season,
        "defense_lower_is_better": True,
        "club": {
            "historical_attack": _mean(club_hist_attack),
            "historical_defense": _mean(club_hist_defense),
            "current_attack": current_strengths.get("forca_ofensiva"),
            "current_defense": current_strengths.get("forca_defensiva"),
        },
        "peers": {
            "historical_attack": _mean(peer_hist_attack),
            "historical_defense": _mean(peer_hist_defense),
            "current_attack": current_peers.get("forca_ofensiva"),
            "current_defense": current_peers.get("forca_defensiva"),
        },
    }

def matchup_strengths(home_id: int, away_id: int, competition_id: int, season: str):
    reference = _latest_strength_season(competition_id, [home_id, away_id], season)
    effective = reference or season
    strengths = _relative_strengths(competition_id, effective)
    home = strengths.get(home_id, {})
    away = strengths.get(away_id, {})
    return {
        "requested_season": season,
        "reference_season": effective,
        "used_fallback_season": effective != season,
        "defense_lower_is_better": True,
        "home": {
            "attack_general": home.get("forca_ofensiva"),
            "defense_general": home.get("forca_defensiva"),
            "attack_venue": home.get("forca_ofensiva_casa"),
            "defense_venue": home.get("forca_defensiva_casa"),
        },
        "away": {
            "attack_general": away.get("forca_ofensiva"),
            "defense_general": away.get("forca_defensiva"),
            "attack_venue": away.get("forca_ofensiva_fora"),
            "defense_venue": away.get("forca_defensiva_fora"),
        },
    }

def ranking(country_id:int|None=None, season:str|None=None, competition_id:int|None=None, club_id:int|None=None):
    clauses=[]; params={}
    if country_id: clauses.append("p.id=:p"); params["p"]=country_id
    if season: clauses.append("e.temporada=:s"); params["s"]=season
    if competition_id: clauses.append("e.campeonato_id=:c"); params["c"]=competition_id
    if club_id: clauses.append("e.clube_id=:club"); params["club"]=club_id
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    with app_engine.connect() as conn:
        rows=[dict(r) for r in conn.execute(text(f"""
            SELECT e.temporada,e.clube_id,cl.nome AS clube,cl.escudo_url,e.elo_mercado::float,e.elo_inicial::float,
                   e.elo_atual::float,e.elo_max::float,e.elo_min::float,e.jogos,
                   c.id AS campeonato_id,c.nome AS campeonato,c.principal,p.id AS pais_id,p.nome AS pais
            FROM {settings.app_schema}.elo_clubes e
            JOIN {settings.app_schema}.clubes cl ON cl.id=e.clube_id
            JOIN {settings.app_schema}.campeonatos c ON c.id=e.campeonato_id
            JOIN {settings.app_schema}.paises p ON p.id=c.pais_id
            {where}
            ORDER BY e.elo_atual DESC, cl.nome
        """),params).mappings()]
    strength_cache={}
    for r in rows:
        key=(int(r["campeonato_id"]),str(r["temporada"]))
        if key not in strength_cache:
            strength_cache[key]=_relative_strengths(key[0],key[1])
        strengths=strength_cache[key].get(r["clube_id"],{})
        r["forca_ofensiva"]=strengths.get("forca_ofensiva")
        r["forca_defensiva"]=strengths.get("forca_defensiva")
    for i,r in enumerate(rows,1): r["posicao"]=i
    return rows


def elo_evolution(club_id:int, competition_id:int, season:str, limit:int=20):
    """Latest ELO movements up to the selected season, crossing season boundaries when needed."""
    cutoff = season_key(season)
    with app_engine.connect() as conn:
        current_row = conn.execute(text(f"""
            SELECT elo_inicial::float, elo_atual::float, jogos
            FROM {settings.app_schema}.elo_clubes
            WHERE clube_id=:club AND campeonato_id=:c AND temporada=:s
        """), {"club":club_id,"c":competition_id,"s":season}).mappings().first()
        rows = [dict(r) for r in conn.execute(text(f"""
            SELECT temporada,data,rodada,casa_clube_id,fora_clube_id,
                   elo_casa_depois::float,elo_fora_depois::float,id
            FROM {settings.app_schema}.elo_movimentos
            WHERE campeonato_id=:c AND (casa_clube_id=:club OR fora_clube_id=:club)
            ORDER BY data ASC NULLS LAST,id ASC
        """), {"c":competition_id,"club":club_id}).mappings()]

    rows = [r for r in rows if season_key(str(r.get("temporada") or "")) <= cutoff]
    rows = rows[-limit:]
    points=[]
    for r in rows:
        elo=float(r["elo_casa_depois"] if r["casa_clube_id"]==club_id else r["elo_fora_depois"])
        rodada=str(r.get("rodada") or "")
        temp=str(r.get("temporada") or "")
        points.append({
            "label": f"{temp} · {rodada}" if rodada else temp,
            "elo": round(elo,2),
            "data": str(r["data"]) if r.get("data") else None,
            "temporada": temp,
        })

    # Se a temporada selecionada já tem ELO calculado mas ainda não teve jogos,
    # adicionamos o ELO atual/inicial como último ponto para não deixar o gráfico vazio.
    if current_row:
        current_elo = float(current_row["elo_atual"] if current_row["elo_atual"] is not None else current_row["elo_inicial"])
        has_selected_movement = any(str(p.get("temporada")) == str(season) for p in points)
        if not has_selected_movement:
            points.append({"label": f"Atual {season}", "elo": round(current_elo,2), "data": None, "temporada": season})

    if not points and current_row:
        points.append({"label": f"Atual {season}", "elo": round(float(current_row["elo_atual"]),2), "data": None, "temporada": season})
    return points[-(limit+1):]

def elo_probability(home_elo:float, away_elo:float, draw_rate:float=0.25):
    q=10**(((home_elo+HOME_ADVANTAGE)-away_elo)/400.0)
    d=max(0.05,min(0.50,draw_rate))
    nu=2*d/(1-d)
    root=math.sqrt(q); den=q+1+nu*root
    return {"home":q/den,"draw":nu*root/den,"away":1/den,"nu":nu}


def _classification_metrics(items):
    if not items:
        return None
    correct = 0
    brier = 0.0
    logloss = 0.0
    buckets = {i: [] for i in range(10)}
    labels = ('home', 'draw', 'away')
    for probs, actual in items:
        pred = max(labels, key=lambda k: probs[k])
        is_correct = 1 if pred == actual else 0
        correct += is_correct
        for k in labels:
            y = 1.0 if k == actual else 0.0
            brier += (probs[k] - y) ** 2
        logloss += -math.log(max(1e-12, probs[actual]))
        conf = max(probs.values())
        bucket = min(9, int(conf * 10))
        buckets[bucket].append((conf, is_correct))
    n = len(items)
    calibration = []
    ece = 0.0
    for b in range(10):
        vals = buckets[b]
        if not vals:
            continue
        avg_conf = sum(x[0] for x in vals) / len(vals)
        acc = sum(x[1] for x in vals) / len(vals)
        ece += len(vals) / n * abs(avg_conf - acc)
        calibration.append({
            'bucket': f'{b*10}-{(b+1)*10}%',
            'games': len(vals),
            'avg_confidence': avg_conf * 100,
            'actual_accuracy': acc * 100,
        })
    return {
        'games': n,
        'accuracy': correct / n * 100,
        'brier': brier / n,
        'logloss': logloss / n,
        'ece': ece * 100,
        'calibration': calibration,
    }


def validation(competition_id: int, season: str):
    with app_engine.connect() as conn:
        moves = [dict(r) for r in conn.execute(text(f"""
            SELECT data, casa_clube_id, fora_clube_id, gols_casa, gols_fora,
                   elo_casa_antes::float, elo_fora_antes::float
            FROM {settings.app_schema}.elo_movimentos
            WHERE campeonato_id=:c AND temporada=:s
            ORDER BY data,id
        """), {'c': competition_id, 's': season}).mappings()]
        odds = [dict(r) for r in conn.execute(text(f"""
            SELECT data, clube_casa_id, clube_fora_id,
                   odd_casa::float, odd_empate::float, odd_fora::float
            FROM {settings.app_schema}.odds_jogos
            WHERE campeonato_id=:c AND temporada=:s
        """), {'c': competition_id, 's': season}).mappings()]
    if not moves:
        return {'games': 0, 'elo': None, 'market': None, 'draw_rate': None, 'davidson_nu': None}
    draws = sum(1 for m in moves if m['gols_casa'] == m['gols_fora'])
    draw_rate = draws / len(moves)
    nu = 2 * draw_rate / max(1e-9, 1 - draw_rate)
    elo_items = []
    for m in moves:
        q = 10 ** (((m['elo_casa_antes'] + HOME_ADVANTAGE) - m['elo_fora_antes']) / 400.0)
        root = math.sqrt(q)
        den = q + 1 + nu * root
        probs = {'home': q / den, 'draw': nu * root / den, 'away': 1 / den}
        actual = 'home' if m['gols_casa'] > m['gols_fora'] else 'away' if m['gols_fora'] > m['gols_casa'] else 'draw'
        elo_items.append((probs, actual))
    odds_map = {}
    for o in odds:
        if not o['data']:
            continue
        odds_map[(str(o['data']), o['clube_casa_id'], o['clube_fora_id'])] = o
    market_items = []
    for m in moves:
        if not m['data']:
            continue
        o = odds_map.get((str(m['data']), m['casa_clube_id'], m['fora_clube_id']))
        if not o or not o['odd_casa'] or not o['odd_empate'] or not o['odd_fora']:
            continue
        raw = {'home': 1 / o['odd_casa'], 'draw': 1 / o['odd_empate'], 'away': 1 / o['odd_fora']}
        overround = sum(raw.values())
        probs = {k: v / overround for k, v in raw.items()}
        actual = 'home' if m['gols_casa'] > m['gols_fora'] else 'away' if m['gols_fora'] > m['gols_casa'] else 'draw'
        market_items.append((probs, actual))
    return {
        'games': len(moves),
        'draw_rate': draw_rate * 100,
        'davidson_nu': nu,
        'elo': _classification_metrics(elo_items),
        'market': _classification_metrics(market_items),
    }
