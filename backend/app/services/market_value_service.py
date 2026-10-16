import csv
import io
import re
import unicodedata
from collections import OrderedDict

from sqlalchemy import text

from ..config import settings
from ..db import app_engine
from .elo_service import normalize_name, rebuild_if_complete


HEADER_ALIASES = {
    "season": {"temporada", "season"},
    "club": {"clube", "club", "time", "team"},
    "value": {"valordemercado", "marketvalue", "valor", "value"},
    "crest": {"escudo", "escudourl", "logo", "crest", "badge"},
}


def norm_header(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def parse_market_value(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw:
        return None

    if "," in raw:
        # pt-BR: 1.234.567,89
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") >= 1:
        parts = raw.split(".")
        # Na planilha de valor de mercado o ponto é separador de milhar.
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            raw = "".join(parts)

    try:
        number = float(raw)
    except ValueError:
        return None
    return number if number > 0 else None


def clean_url(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("\\://", "://")
    return raw


def parse_season(value) -> str | None:
    """
    Formatos aceitos:
    - YYYY      -> exemplo: 2026
    - YYYY/YYYY -> exemplo: 2026/2027

    O valor é preservado exatamente nesse padrão, sem transformar
    campeonatos de ano-calendário em temporada cruzando dois anos.
    """
    raw = str(value or "").strip()
    if not raw:
        return None

    if re.fullmatch(r"\d{4}", raw):
        return raw

    if re.fullmatch(r"\d{4}/\d{4}", raw):
        start, end = (int(x) for x in raw.split("/", 1))
        if end != start + 1:
            return None
        return f"{start:04d}/{end:04d}"

    return None


def _cells_markdown(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _markdown_rows(raw_text: str):
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return None, None
    headers = _cells_markdown(lines[0])
    start = 2 if len(lines) > 1 and _is_separator(_cells_markdown(lines[1])) else 1
    rows = []
    for line in lines[start:]:
        cells = _cells_markdown(line)
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return headers, rows


def _delimited_rows(raw_text: str):
    lines = [line for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return None, None

    first = lines[0]
    if "\t" in first:
        delimiter = "\t"
    elif ";" in first:
        delimiter = ";"
    else:
        return None, None

    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    return reader.fieldnames, list(reader) if reader.fieldnames else []


def _aligned_rows(raw_text: str):
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return None, None

    # Tabelas copiadas visualmente costumam separar colunas com 2+ espaços.
    headers = [x.strip() for x in re.split(r"\s{2,}", lines[0].strip()) if x.strip()]
    if len(headers) < 3:
        return None, None

    rows = []
    for line in lines[1:]:
        vals = [x.strip() for x in re.split(r"\s{2,}", line.strip())]
        if len(vals) == len(headers):
            rows.append(dict(zip(headers, vals)))
    return headers, rows


def parse_rows(raw_text: str):
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Cole os valores de mercado antes de validar.")

    fieldnames, raw_rows = _markdown_rows(raw_text)
    if not fieldnames:
        fieldnames, raw_rows = _delimited_rows(raw_text)
    if not fieldnames:
        fieldnames, raw_rows = _aligned_rows(raw_text)
    if not fieldnames:
        raise ValueError("Não foi possível identificar as colunas da tabela colada.")

    found = {}
    for original in fieldnames:
        normalized = norm_header(original)
        for canonical, aliases in HEADER_ALIASES.items():
            if normalized in aliases and canonical not in found:
                found[canonical] = original

    missing = [key for key in ("season", "club", "value") if key not in found]
    if missing:
        raise ValueError(
            "Colunas não reconhecidas: "
            + ", ".join(missing)
            + ". Use Temporada | Clube | Valor de mercado | Escudo."
        )

    parsed = []
    invalid = []
    seen = set()

    for index, row in enumerate(raw_rows, 1):
        season = parse_season(row.get(found["season"]))
        club = str(row.get(found["club"]) or "").strip()
        value = parse_market_value(row.get(found["value"]))
        crest = clean_url(row.get(found.get("crest", ""))) if "crest" in found else None

        if not season or not club or value is None:
            invalid.append(index)
            continue

        unique_key = (season, normalize_name(club))
        if unique_key in seen:
            continue
        seen.add(unique_key)

        parsed.append(
            {
                "row": index,
                "season": season,
                "club": club,
                "value": value,
                "crest": crest,
            }
        )

    if not parsed:
        raise ValueError("Nenhuma linha válida de valor de mercado foi identificada. A temporada deve estar no formato YYYY ou YYYY/YYYY.")

    return parsed, found, invalid


def _competition_country(conn, competition_id: int):
    return conn.execute(
        text(
            f"""
            SELECT c.id, c.nome, c.pais_id, p.nome AS pais
            FROM {settings.app_schema}.campeonatos c
            JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
            WHERE c.id = :id
            """
        ),
        {"id": competition_id},
    ).mappings().one_or_none()


def _country_clubs(conn, country_id: int):
    return [
        dict(row)
        for row in conn.execute(
            text(
                f"""
                SELECT id, nome, escudo_url
                FROM {settings.app_schema}.clubes
                WHERE pais_id = :country_id
                ORDER BY nome
                """
            ),
            {"country_id": country_id},
        ).mappings()
    ]


def preview(country_id: int, competition_id: int, currency: str, raw_text: str):
    if currency not in {"EUR", "USD", "BRL"}:
        raise ValueError("Moeda inválida.")

    rows, found, invalid = parse_rows(raw_text)

    with app_engine.connect() as conn:
        competition = _competition_country(conn, competition_id)
        if not competition:
            raise ValueError("Campeonato não encontrado.")
        if int(competition["pais_id"]) != int(country_id):
            raise ValueError("O campeonato selecionado não pertence ao país informado.")
        clubs = _country_clubs(conn, country_id)

    club_map = {normalize_name(c["nome"]): c for c in clubs}
    new_names = OrderedDict()
    existing = 0

    samples = []
    for row in rows:
        matched = club_map.get(normalize_name(row["club"]))
        if matched:
            existing += 1
        else:
            new_names.setdefault(normalize_name(row["club"]), row["club"])
        if len(samples) < 20:
            samples.append(
                {
                    **row,
                    "status": "existing" if matched else "new",
                    "matched_club": matched["nome"] if matched else None,
                }
            )

    seasons = sorted({r["season"] for r in rows})
    return {
        "total_rows": len(rows),
        "existing_rows": existing,
        "new_clubs": list(new_names.values()),
        "new_clubs_count": len(new_names),
        "seasons": seasons,
        "invalid_rows": invalid,
        "detected_columns": found,
        "sample": samples,
        "competition": dict(competition),
        "currency": currency,
    }


def import_data(country_id: int, competition_id: int, currency: str, raw_text: str):
    if currency not in {"EUR", "USD", "BRL"}:
        raise ValueError("Moeda inválida.")

    rows, _, invalid = parse_rows(raw_text)
    created_clubs = 0
    reused_clubs = 0
    imported_values = 0
    seasons = sorted({r["season"] for r in rows})
    batch_id = None

    with app_engine.begin() as conn:
        competition = _competition_country(conn, competition_id)
        if not competition:
            raise ValueError("Campeonato não encontrado.")
        if int(competition["pais_id"]) != int(country_id):
            raise ValueError("O campeonato selecionado não pertence ao país informado.")

        batch_id = conn.execute(
            text(
                f"""
                INSERT INTO {settings.app_schema}.valor_mercado_importacoes
                    (pais_id, campeonato_id, moeda, temporadas, total_linhas, linhas_importadas, origem)
                VALUES (:pais_id, :campeonato_id, :moeda, :temporadas, :total, 0, 'manual')
                RETURNING id
                """
            ),
            {
                "pais_id": country_id,
                "campeonato_id": competition_id,
                "moeda": currency,
                "temporadas": " | ".join(seasons),
                "total": len(rows),
            },
        ).scalar_one()

        clubs = _country_clubs(conn, country_id)
        club_map = {normalize_name(c["nome"]): c for c in clubs}
        reused_seen = set()
        created_seen = set()

        for row in rows:
            normalized = normalize_name(row["club"])
            club = club_map.get(normalized)

            if club is None:
                inserted = conn.execute(
                    text(
                        f"""
                        INSERT INTO {settings.app_schema}.clubes (nome, pais_id, escudo_url)
                        VALUES (:nome, :pais_id, :escudo_url)
                        ON CONFLICT (pais_id, (LOWER(nome)))
                        DO UPDATE SET escudo_url = COALESCE(
                            NULLIF(EXCLUDED.escudo_url, ''),
                            {settings.app_schema}.clubes.escudo_url
                        )
                        RETURNING id, nome, escudo_url
                        """
                    ),
                    {"nome": row["club"], "pais_id": country_id, "escudo_url": row["crest"]},
                ).mappings().one()
                club = dict(inserted)
                club_map[normalized] = club
                if normalized not in created_seen:
                    created_clubs += 1
                    created_seen.add(normalized)
            else:
                if normalized not in reused_seen:
                    reused_clubs += 1
                    reused_seen.add(normalized)
                if row["crest"]:
                    conn.execute(
                        text(f"UPDATE {settings.app_schema}.clubes SET escudo_url = :escudo_url WHERE id = :id"),
                        {"id": club["id"], "escudo_url": row["crest"]},
                    )

            conn.execute(
                text(
                    f"""
                    INSERT INTO {settings.app_schema}.clubes_campeonatos
                        (clube_id, campeonato_id, temporada)
                    VALUES (:clube_id, :campeonato_id, :temporada)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"clube_id": club["id"], "campeonato_id": competition_id, "temporada": row["season"]},
            )

            conn.execute(
                text(
                    f"""
                    INSERT INTO {settings.app_schema}.valores_mercado
                        (temporada, pais_id, campeonato_id, clube_id, valor, moeda, carga_id)
                    VALUES (:temporada, :pais_id, :campeonato_id, :clube_id, :valor, :moeda, :carga_id)
                    ON CONFLICT (temporada, campeonato_id, clube_id)
                    DO UPDATE SET
                        pais_id = EXCLUDED.pais_id,
                        valor = EXCLUDED.valor,
                        moeda = EXCLUDED.moeda,
                        carga_id = EXCLUDED.carga_id,
                        atualizado_em = NOW()
                    """
                ),
                {
                    "temporada": row["season"],
                    "pais_id": country_id,
                    "campeonato_id": competition_id,
                    "clube_id": club["id"],
                    "valor": row["value"],
                    "moeda": currency,
                    "carga_id": batch_id,
                },
            )
            imported_values += 1

        conn.execute(
            text(f"UPDATE {settings.app_schema}.valor_mercado_importacoes SET linhas_importadas = :n WHERE id = :id"),
            {"n": imported_values, "id": batch_id},
        )

    elo_results = []
    for season in seasons:
        try:
            result = rebuild_if_complete(competition_id, season)
            elo_results.append({"season": season, "result": result})
        except Exception as exc:
            elo_results.append({"season": season, "error": str(exc)})

    return {
        "carga_id": batch_id,
        "imported": imported_values,
        "created_clubs": created_clubs,
        "reused_clubs": reused_clubs,
        "seasons": seasons,
        "invalid_rows": invalid,
        "elo": elo_results,
    }




def list_imports(limit: int = 10):
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT i.id, i.criado_em, i.excluido_em, i.moeda, i.temporadas,
                       i.total_linhas, i.linhas_importadas,
                       p.nome AS pais, c.nome AS campeonato,
                       COUNT(vm.id) FILTER (WHERE vm.carga_id = i.id) AS linhas_ativas
                FROM {settings.app_schema}.valor_mercado_importacoes i
                JOIN {settings.app_schema}.paises p ON p.id = i.pais_id
                JOIN {settings.app_schema}.campeonatos c ON c.id = i.campeonato_id
                LEFT JOIN {settings.app_schema}.valores_mercado vm ON vm.carga_id = i.id
                GROUP BY i.id, p.nome, c.nome
                ORDER BY i.criado_em DESC, i.id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def delete_import(batch_id: int):
    with app_engine.begin() as conn:
        batch = conn.execute(
            text(
                f"""
                SELECT id, campeonato_id, excluido_em
                FROM {settings.app_schema}.valor_mercado_importacoes
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": batch_id},
        ).mappings().one_or_none()
        if not batch:
            return None
        if batch["excluido_em"]:
            return {"id": batch_id, "deleted_rows": 0, "already_deleted": True, "seasons": []}

        seasons = [
            str(r["temporada"])
            for r in conn.execute(
                text(f"SELECT DISTINCT temporada FROM {settings.app_schema}.valores_mercado WHERE carga_id = :id"),
                {"id": batch_id},
            ).mappings().all()
        ]
        deleted = conn.execute(
            text(f"DELETE FROM {settings.app_schema}.valores_mercado WHERE carga_id = :id"),
            {"id": batch_id},
        ).rowcount or 0
        conn.execute(
            text(f"UPDATE {settings.app_schema}.valor_mercado_importacoes SET excluido_em = NOW() WHERE id = :id"),
            {"id": batch_id},
        )
        competition_id = int(batch["campeonato_id"])

    for season in seasons:
        try:
            rebuild_if_complete(competition_id, season)
        except Exception:
            pass

    return {"id": batch_id, "deleted_rows": int(deleted), "seasons": seasons}
