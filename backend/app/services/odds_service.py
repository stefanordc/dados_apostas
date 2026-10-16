import csv
import hashlib
import io
import re
import unicodedata
from datetime import datetime

from sqlalchemy import text

from ..config import settings
from ..db import app_engine
from .elo_service import normalize_name

HEADER_ALIASES = {
    "season": {"temporada", "season"},
    "date": {"date", "data", "matchdate"},
    "round": {"round", "rodada", "fase", "stage"},
    "home": {"home", "hometeam", "casa", "mandante", "timecasa"},
    "away": {"away", "awayteam", "fora", "visitante", "timefora"},
    "home_odd": {"b365h", "oddhome", "oddhomeft", "oddcasa", "oddmandante", "homeodd"},
    "draw_odd": {"b365d", "odddraw", "oddempate", "drawodd"},
    "away_odd": {"b365a", "oddaway", "oddawayft", "oddfora", "oddvisitante", "awayodd"},
    "over_25": {"over25", "over2.5", "oddover25", "oddover2.5", "o25", "b365over25"},
    "under_25": {"under25", "under2.5", "oddunder25", "oddunder2.5", "u25", "b365under25"},
}


def norm_header(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9.]+", "", s)


def parse_num(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        # pt-BR com milhar + decimal: 1.234,56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(v):
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def normalize_season(value: str | None) -> str:
    raw = str(value or "").strip().replace("-", "/")
    if not raw:
        return ""
    m = re.fullmatch(r"(\d{4})/(\d{4})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"(\d{4})/(\d{2})", raw)
    if m:
        start = int(m.group(1))
        end = (start // 100) * 100 + int(m.group(2))
        if end < start:
            end += 100
        return f"{start:04d}/{end:04d}"
    m = re.fullmatch(r"(\d{4})", raw)
    if m:
        start = int(m.group(1))
        return f"{start:04d}/{start + 1:04d}"
    raise ValueError(f"Temporada inválida: {raw}. Use o padrão 2020/2021.")


def _season_summary(seasons: list[str]) -> str:
    ordered = sorted(set(seasons))
    if not ordered:
        return "—"
    if len(ordered) == 1:
        return ordered[0]
    return f"{ordered[0]} → {ordered[-1]} ({len(ordered)} temporadas)"


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


def _markdown_dict_rows(raw_text: str):
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return None, None

    def cells(line: str):
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in line.split("|")]

    headers = cells(lines[0])
    if not headers or len(headers) < 3:
        return None, None

    start = 1
    if len(lines) > 1 and _is_markdown_separator(cells(lines[1])):
        start = 2

    rows = []
    for line in lines[start:]:
        vals = cells(line)
        if len(vals) != len(headers):
            continue
        rows.append(dict(zip(headers, vals)))
    return headers, rows


def _delimited_dict_rows(raw_text: str):
    lines = [line for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return None, None

    first = lines[0]
    # Cópia do Excel/Google Sheets usa TAB. Priorizamos TAB e ponto-e-vírgula
    # para não confundir a vírgula decimal das odds com delimitador CSV.
    if "\t" in first:
        delimiter = "\t"
    elif ";" in first:
        delimiter = ";"
    else:
        return None, None

    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    return reader.fieldnames, list(reader) if reader.fieldnames else []


def _aligned_dict_rows(raw_text: str):
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return None, None

    headers = [x.strip() for x in re.split(r"\s{2,}", lines[0].strip()) if x.strip()]
    if len(headers) < 5:
        return None, None

    rows = []
    for line in lines[1:]:
        values = [x.strip() for x in re.split(r"\s{2,}", line.strip())]
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    return headers, rows


def _headerless_rows(raw_text: str):
    """Fallback para tabela sem cabeçalho copiada de uma grade visual.

    Espera: Data, Mandante, Visitante, Odd Casa, Odd Empate, Odd Fora
    e opcionalmente Over 2,5 / Under 2,5.
    """
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines or not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\b", lines[0].strip()):
        return None, None

    headers = ["Data", "Mandante", "Visitante", "Odd Casa", "Odd Empate", "Odd Fora", "Over 2,5", "Under 2,5"]
    rows = []
    for line in lines:
        values = [x.strip() for x in re.split(r"\t+|\s{2,}", line.strip()) if x.strip()]
        if 6 <= len(values) <= 8:
            padded = values + [""] * (8 - len(values))
            rows.append(dict(zip(headers, padded)))
    return headers, rows


def parse_rows(raw_text: str, fallback_season: str | None = None):
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Cole as odds antes de validar.")

    fieldnames, raw_rows = _markdown_dict_rows(raw_text)
    if not fieldnames:
        fieldnames, raw_rows = _delimited_dict_rows(raw_text)
    if not fieldnames:
        fieldnames, raw_rows = _aligned_dict_rows(raw_text)
    if not fieldnames:
        fieldnames, raw_rows = _headerless_rows(raw_text)
    if not fieldnames:
        raise ValueError("Cole os dados com cabeçalho ou em uma tabela reconhecível.")

    found = {}
    for original in fieldnames:
        n = norm_header(original)
        for canonical, aliases in HEADER_ALIASES.items():
            if n in aliases and canonical not in found:
                found[canonical] = original

    missing = [x for x in ("home", "away", "home_odd", "draw_odd", "away_odd") if x not in found]
    if missing:
        raise ValueError(
            "Colunas não reconhecidas: "
            + ", ".join(missing)
            + ". Aceitamos Mandante/Visitante/Odd Casa/Odd Empate/Odd Fora, "
              "HomeTeam/AwayTeam/B365H/B365D/B365A e equivalentes."
        )

    normalized_fallback = normalize_season(fallback_season) if fallback_season else ""
    if "season" not in found and not normalized_fallback:
        raise ValueError("A coluna Temporada é obrigatória quando nenhuma temporada de fallback foi informada.")

    rows = []
    for idx, row in enumerate(raw_rows, 1):
        home = str(row.get(found["home"]) or "").strip()
        away = str(row.get(found["away"]) or "").strip()
        if not home or not away:
            continue
        # Ignora eventual segunda linha separadora que tenha passado pelo parser CSV.
        if _is_markdown_separator([home, away]):
            continue
        home_odd = parse_num(row.get(found["home_odd"]))
        draw_odd = parse_num(row.get(found["draw_odd"]))
        away_odd = parse_num(row.get(found["away_odd"]))
        if not all(v is not None and v > 1 for v in (home_odd, draw_odd, away_odd)):
            continue
        season_value = (
            normalize_season(row.get(found["season"]))
            if "season" in found and str(row.get(found["season"]) or "").strip()
            else normalized_fallback
        )
        match_date = parse_date(row.get(found.get("date", ""))) if "date" in found else None
        if not match_date:
            raise ValueError(f"Linha {idx}: data inválida ou ausente. Use dd/mm/aaaa.")
        rows.append(
            {
                "row": idx,
                "season": season_value,
                "date": match_date,
                "round": str(row.get(found.get("round", "")) or "").strip() if "round" in found else "",
                "home": home,
                "away": away,
                "home_odd": home_odd,
                "draw_odd": draw_odd,
                "away_odd": away_odd,
                "over_25": parse_num(row.get(found["over_25"])) if "over_25" in found else None,
                "under_25": parse_num(row.get(found["under_25"])) if "under_25" in found else None,
            }
        )
    if not rows:
        raise ValueError("Nenhuma linha válida de odds foi identificada. Confira o cabeçalho e as odds 1X2.")
    return rows, found


def registry(competition_id: int):
    with app_engine.connect() as conn:
        clubs = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT DISTINCT cl.id, cl.nome, cl.escudo_url
                    FROM {settings.app_schema}.clubes cl
                    JOIN {settings.app_schema}.clubes_campeonatos cc ON cc.clube_id = cl.id
                    WHERE cc.campeonato_id = :c
                    ORDER BY cl.nome
                    """
                ),
                {"c": competition_id},
            ).mappings()
        ]
        aliases = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT clube_id, alias
                    FROM {settings.app_schema}.clubes_aliases
                    WHERE campeonato_id = :c OR campeonato_id IS NULL
                    """
                ),
                {"c": competition_id},
            ).mappings()
        ]
    mp = {normalize_name(c["nome"]): c["id"] for c in clubs}
    for a in aliases:
        mp[normalize_name(a["alias"])] = a["clube_id"]
    return clubs, mp


def _resolved_key(competition_id: int, r: dict, home_id: int, away_id: int):
    return (
        int(competition_id),
        r["season"],
        r["date"],
        int(home_id),
        int(away_id),
    )


def _display_duplicate(r: dict):
    return {
        "season": r["season"],
        "date": r["date"].strftime("%d/%m/%Y") if r.get("date") else "—",
        "home": r["home"],
        "away": r["away"],
    }


def _existing_keys(conn, competition_id: int, resolved_rows: list[tuple[dict, int, int]]):
    if not resolved_rows:
        return set()

    seasons = sorted({r["season"] for r, _, _ in resolved_rows})
    dates = sorted({r["date"] for r, _, _ in resolved_rows})
    club_ids = sorted({cid for _, h, a in resolved_rows for cid in (h, a)})

    rows = conn.execute(
        text(
            f"""
            SELECT campeonato_id, temporada, data, clube_casa_id, clube_fora_id
            FROM {settings.app_schema}.odds_jogos
            WHERE campeonato_id = :c
              AND temporada = ANY(:seasons)
              AND data = ANY(:dates)
              AND clube_casa_id = ANY(:club_ids)
              AND clube_fora_id = ANY(:club_ids)
            """
        ),
        {
            "c": competition_id,
            "seasons": seasons,
            "dates": dates,
            "club_ids": club_ids,
        },
    ).all()
    return {
        (int(c), str(season), date, int(home_id), int(away_id))
        for c, season, date, home_id, away_id in rows
    }


def preview(pais_id: int, competition_id: int, temporada: str | None, raw_text: str):
    rows, found = parse_rows(raw_text, temporada)
    clubs, mp = registry(competition_id)
    unresolved = set()
    recognized = 0
    resolved_rows = []
    seen = set()
    duplicates_in_paste = []

    for r in rows:
        h = mp.get(normalize_name(r["home"]))
        a = mp.get(normalize_name(r["away"]))
        r["home_club_id"] = h
        r["away_club_id"] = a
        if h and a:
            recognized += 1
            key = _resolved_key(competition_id, r, h, a)
            if key in seen:
                duplicates_in_paste.append(_display_duplicate(r))
            else:
                seen.add(key)
                resolved_rows.append((r, h, a))
        if not h:
            unresolved.add(r["home"])
        if not a:
            unresolved.add(r["away"])

    with app_engine.connect() as conn:
        existing_keys = _existing_keys(conn, competition_id, resolved_rows)

    duplicates_existing = [
        _display_duplicate(r)
        for r, h, a in resolved_rows
        if _resolved_key(competition_id, r, h, a) in existing_keys
    ]

    preview_rows = []
    for r in rows[:12]:
        item = dict(r)
        if item.get("date"):
            item["date"] = item["date"].isoformat()
        preview_rows.append(item)

    seasons = sorted({r["season"] for r in rows})
    return {
        "total_rows": len(rows),
        "recognized_rows": recognized,
        "unresolved": sorted(unresolved),
        "clubs": clubs,
        "detected_columns": found,
        "has_over_25": "over_25" in found,
        "has_under_25": "under_25" in found,
        "seasons": seasons,
        "season_count": len(seasons),
        "duplicate_in_paste_count": len(duplicates_in_paste),
        "duplicate_existing_count": len(duplicates_existing),
        "duplicates_in_paste": duplicates_in_paste[:20],
        "duplicates_existing": duplicates_existing[:20],
        "sample": preview_rows,
    }


def _match_source_key(competition_id: int, temporada: str, r: dict, home_id: int, away_id: int):
    anchor = r["date"].isoformat() if r["date"] else (r.get("round") or f"row-{r['row']}")
    raw_key = f"v3|{competition_id}|{temporada}|{anchor}|{home_id}|{away_id}"
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()


def import_data(
    pais_id: int,
    competition_id: int,
    temporada: str | None,
    raw_text: str,
    mappings: dict[str, int],
):
    rows, _ = parse_rows(raw_text, temporada)
    _, mp = registry(competition_id)
    normalized_mappings = {normalize_name(k): int(v) for k, v in mappings.items()}
    mp.update(normalized_mappings)

    unresolved = set()
    resolved_rows = []
    seen = set()
    duplicates_in_paste = 0

    for r in rows:
        h = mp.get(normalize_name(r["home"]))
        a = mp.get(normalize_name(r["away"]))
        if not h:
            unresolved.add(r["home"])
        if not a:
            unresolved.add(r["away"])
        if not h or not a:
            continue

        key = _resolved_key(competition_id, r, h, a)
        if key in seen:
            duplicates_in_paste += 1
            continue
        seen.add(key)
        resolved_rows.append((r, h, a))

    if unresolved:
        raise ValueError(
            "Existem clubes ainda não conciliados: " + ", ".join(sorted(unresolved))
        )

    imported = 0
    duplicates_existing = 0
    seasons = sorted({r["season"] for r, _, _ in resolved_rows})

    with app_engine.begin() as conn:
        existing_keys = _existing_keys(conn, competition_id, resolved_rows)
        rows_to_import = [
            (r, h, a)
            for r, h, a in resolved_rows
            if _resolved_key(competition_id, r, h, a) not in existing_keys
        ]
        duplicates_existing = len(resolved_rows) - len(rows_to_import)

        if not rows_to_import:
            raise ValueError(
                "Nenhum jogo novo para importar. Todas as linhas válidas já estão cadastradas "
                "ou estão repetidas dentro da própria colagem."
            )

        batch_id = conn.execute(
            text(
                f"""
                INSERT INTO {settings.app_schema}.odds_importacoes
                    (pais_id, campeonato_id, temporada, total_linhas, linhas_importadas, origem, resumo_hash)
                VALUES (:p, :c, :s, :total, 0, 'manual-multitemporada', :hash)
                RETURNING id
                """
            ),
            {
                "p": pais_id,
                "c": competition_id,
                "s": _season_summary(seasons),
                "total": len(rows),
                "hash": hashlib.sha1(raw_text.encode("utf-8")).hexdigest(),
            },
        ).scalar_one()

        for source, cid in mappings.items():
            conn.execute(
                text(
                    f"""
                    INSERT INTO {settings.app_schema}.clubes_aliases (clube_id, campeonato_id, alias)
                    VALUES (:club, :c, :alias)
                    ON CONFLICT ((COALESCE(campeonato_id,0)),(LOWER(alias)))
                    DO UPDATE SET clube_id = EXCLUDED.clube_id
                    """
                ),
                {"club": cid, "c": competition_id, "alias": source.strip()},
            )

        for r, h, a in rows_to_import:
            key = _match_source_key(competition_id, r["season"], r, h, a)
            params = {
                "p": pais_id,
                "c": competition_id,
                "s": r["season"],
                "date": r["date"],
                "round": r["round"] or None,
                "h": h,
                "a": a,
                "ho": r["home"],
                "ao": r["away"],
                "oh": r["home_odd"],
                "od": r["draw_odd"],
                "oa": r["away_odd"],
                "o25": r["over_25"],
                "u25": r["under_25"],
                "key": key,
                "batch": batch_id,
            }

            result = conn.execute(
                text(
                    f"""
                    INSERT INTO {settings.app_schema}.odds_jogos
                        (pais_id, campeonato_id, temporada, data, rodada,
                         clube_casa_id, clube_fora_id, mandante_origem, visitante_origem,
                         odd_casa, odd_empate, odd_fora, odd_over_25, odd_under_25,
                         source_key, carga_id)
                    VALUES
                        (:p, :c, :s, :date, :round, :h, :a, :ho, :ao,
                         :oh, :od, :oa, :o25, :u25, :key, :batch)
                    ON CONFLICT (campeonato_id, temporada, data, clube_casa_id, clube_fora_id)
                    WHERE data IS NOT NULL
                    DO NOTHING
                    """
                ),
                params,
            )
            if (result.rowcount or 0) > 0:
                imported += 1
            else:
                duplicates_existing += 1

        conn.execute(
            text(
                f"""
                UPDATE {settings.app_schema}.odds_importacoes
                SET linhas_importadas = :n
                WHERE id = :id
                """
            ),
            {"n": imported, "id": batch_id},
        )

    return {
        "batch_id": int(batch_id),
        "imported": imported,
        "duplicates_skipped": duplicates_existing + duplicates_in_paste,
        "duplicates_existing": duplicates_existing,
        "duplicates_in_paste": duplicates_in_paste,
        "unresolved": [],
        "total_rows": len(rows),
        "seasons": seasons,
    }

def list_imports(limit: int = 10):
    limit = max(1, min(int(limit), 50))
    with app_engine.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    f"""
                    SELECT i.id, i.temporada, i.total_linhas, i.linhas_importadas,
                           i.origem, i.criado_em, i.excluido_em,
                           p.nome AS pais, c.nome AS campeonato,
                           COUNT(o.id)::int AS linhas_ativas
                    FROM {settings.app_schema}.odds_importacoes i
                    JOIN {settings.app_schema}.paises p ON p.id = i.pais_id
                    JOIN {settings.app_schema}.campeonatos c ON c.id = i.campeonato_id
                    LEFT JOIN {settings.app_schema}.odds_jogos o ON o.carga_id = i.id
                    GROUP BY i.id, p.nome, c.nome
                    ORDER BY i.criado_em DESC, i.id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings()
        ]
    return rows


def delete_import(batch_id: int):
    with app_engine.begin() as conn:
        batch = conn.execute(
            text(
                f"""
                SELECT id, excluido_em
                FROM {settings.app_schema}.odds_importacoes
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": batch_id},
        ).mappings().first()
        if not batch:
            return None
        if batch["excluido_em"] is not None:
            return {"id": batch_id, "deleted_rows": 0, "already_deleted": True}

        deleted = conn.execute(
            text(f"DELETE FROM {settings.app_schema}.odds_jogos WHERE carga_id = :id"),
            {"id": batch_id},
        ).rowcount or 0
        conn.execute(
            text(
                f"""
                UPDATE {settings.app_schema}.odds_importacoes
                SET excluido_em = NOW()
                WHERE id = :id
                """
            ),
            {"id": batch_id},
        )
    return {"id": batch_id, "deleted_rows": int(deleted), "already_deleted": False}
