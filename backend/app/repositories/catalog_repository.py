import re
from sqlalchemy import text
from ..config import settings
from ..db import app_engine, history_connection


def _rows(query: str, params=None):
    with app_engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        return [dict(r._mapping) for r in result]


def list_countries(q: str | None = None):
    where = "WHERE nome ILIKE :q" if q else ""
    params = {"q": f"%{q}%"} if q else {}
    return _rows(
        f"SELECT id, nome, continente FROM {settings.app_schema}.paises {where} ORDER BY nome",
        params,
    )


def create_country(nome: str, continente: str):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.paises (nome, continente)
                VALUES (:nome, :continente)
                ON CONFLICT ((LOWER(nome)))
                DO UPDATE SET nome = EXCLUDED.nome, continente = EXCLUDED.continente
                RETURNING id, nome, continente
            """),
            {"nome": nome.strip(), "continente": continente.strip()},
        ).mappings().one()
        return dict(row)


def list_competitions(country_id: int | None = None, q: str | None = None):
    clauses, params = [], {}
    if country_id:
        clauses.append("c.pais_id = :country_id")
        params["country_id"] = country_id
    if q:
        clauses.append("c.nome ILIKE :q")
        params["q"] = f"%{q}%"
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return _rows(
        f"""
        SELECT c.id, c.nome, c.pais_id, c.principal, p.nome AS pais
        FROM {settings.app_schema}.campeonatos c
        JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
        {where}
        ORDER BY c.principal DESC, c.nome
        """,
        params,
    )


def create_competition(nome: str, pais_id: int, principal: bool = False):
    with app_engine.begin() as conn:
        if principal:
            conn.execute(
                text(f"UPDATE {settings.app_schema}.campeonatos SET principal = FALSE WHERE pais_id = :pais_id"),
                {"pais_id": pais_id},
            )
        row = conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.campeonatos (nome, pais_id, principal)
                VALUES (:nome, :pais_id, :principal)
                ON CONFLICT (pais_id, (LOWER(nome)))
                DO UPDATE SET nome = EXCLUDED.nome, principal = EXCLUDED.principal
                RETURNING id, nome, pais_id, principal
            """),
            {"nome": nome.strip(), "pais_id": pais_id, "principal": principal},
        ).mappings().one()
        return dict(row)


def list_clubs(
    country_id: int | None = None,
    competition_id: int | None = None,
    season: str | None = None,
    q: str | None = None,
    exclude_market_values: bool = False,
):
    joins, clauses, params = [], [], {}
    if competition_id or season:
        joins.append(f"JOIN {settings.app_schema}.clubes_campeonatos cc ON cc.clube_id = cl.id")
    if country_id:
        clauses.append("cl.pais_id = :country_id")
        params["country_id"] = country_id
    if competition_id:
        clauses.append("cc.campeonato_id = :competition_id")
        params["competition_id"] = competition_id
    if season:
        clauses.append("cc.temporada = :season")
        params["season"] = season
    if q:
        clauses.append("cl.nome ILIKE :q")
        params["q"] = f"%{q}%"
    if exclude_market_values and season and competition_id:
        clauses.append(f"""
            NOT EXISTS (
                SELECT 1 FROM {settings.app_schema}.valores_mercado vm
                WHERE vm.clube_id = cl.id
                  AND vm.campeonato_id = :competition_id
                  AND vm.temporada = :season
            )
        """)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return _rows(
        f"""
        SELECT DISTINCT cl.id, cl.nome, cl.pais_id, cl.escudo_url, p.nome AS pais
        FROM {settings.app_schema}.clubes cl
        JOIN {settings.app_schema}.paises p ON p.id = cl.pais_id
        {' '.join(joins)}
        {where}
        ORDER BY cl.nome
        """,
        params,
    )


def create_club(nome: str, pais_id: int, campeonato_id: int | None = None,
                temporada: str | None = None, escudo_url: str | None = None):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.clubes (nome, pais_id, escudo_url)
                VALUES (:nome, :pais_id, :escudo_url)
                ON CONFLICT (pais_id, (LOWER(nome)))
                DO UPDATE SET
                    nome = EXCLUDED.nome,
                    escudo_url = COALESCE(NULLIF(EXCLUDED.escudo_url, ''), {settings.app_schema}.clubes.escudo_url)
                RETURNING id, nome, pais_id, escudo_url
            """),
            {"nome": nome.strip(), "pais_id": pais_id, "escudo_url": (escudo_url or '').strip() or None},
        ).mappings().one()
        club = dict(row)
        if campeonato_id and temporada:
            conn.execute(
                text(f"""
                    INSERT INTO {settings.app_schema}.clubes_campeonatos (clube_id, campeonato_id, temporada)
                    VALUES (:clube_id, :campeonato_id, :temporada)
                    ON CONFLICT DO NOTHING
                """),
                {"clube_id": club["id"], "campeonato_id": campeonato_id, "temporada": temporada.strip()},
            )
        return club


def save_market_value(data: dict):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.valores_mercado
                    (temporada, pais_id, campeonato_id, clube_id, valor, moeda)
                VALUES (:temporada, :pais_id, :campeonato_id, :clube_id, :valor, :moeda)
                ON CONFLICT (temporada, campeonato_id, clube_id)
                DO UPDATE SET pais_id = EXCLUDED.pais_id, valor = EXCLUDED.valor,
                              moeda = EXCLUDED.moeda, atualizado_em = NOW()
                RETURNING id, temporada, pais_id, campeonato_id, clube_id, valor, moeda
            """),
            data,
        ).mappings().one()
        conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.clubes_campeonatos (clube_id, campeonato_id, temporada)
                VALUES (:clube_id, :campeonato_id, :temporada)
                ON CONFLICT DO NOTHING
            """),
            {"clube_id": data["clube_id"], "campeonato_id": data["campeonato_id"], "temporada": data["temporada"]},
        )
        return dict(row)


def list_market_values(limit: int = 20):
    limit = max(1, min(int(limit), 100))
    return _rows(
        f"""
        SELECT vm.id, vm.temporada, p.nome AS pais, c.nome AS campeonato,
               cl.nome AS clube, cl.escudo_url, vm.valor, vm.moeda,
               vm.criado_em, vm.atualizado_em
        FROM {settings.app_schema}.valores_mercado vm
        JOIN {settings.app_schema}.paises p ON p.id = vm.pais_id
        JOIN {settings.app_schema}.campeonatos c ON c.id = vm.campeonato_id
        JOIN {settings.app_schema}.clubes cl ON cl.id = vm.clube_id
        ORDER BY vm.atualizado_em DESC, vm.id DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

# --- MANAGEMENT CRUD ---


def _paged(query: str, count_query: str, params: dict, page: int, page_size: int):
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    params = dict(params)
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    with app_engine.connect() as conn:
        total = int(conn.execute(text(count_query), params).scalar_one() or 0)
        rows = [dict(r._mapping) for r in conn.execute(text(query), params)]

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def manage_countries(q: str | None = None, page: int = 1, page_size: int = 20):
    params = {}
    where = ""
    if q:
        params["q"] = f"%{q.strip()}%"
        where = """
        WHERE p.nome ILIKE :q
           OR p.continente ILIKE :q
           OR p.id::text ILIKE :q
        """

    return _paged(
        f"""
        SELECT p.id, p.nome, p.continente, p.criado_em
        FROM {settings.app_schema}.paises p
        {where}
        ORDER BY p.nome
        LIMIT :limit OFFSET :offset
        """,
        f"SELECT COUNT(*) FROM {settings.app_schema}.paises p {where}",
        params, page, page_size,
    )


def update_country(country_id: int, nome: str, continente: str):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                UPDATE {settings.app_schema}.paises
                SET nome = :nome, continente = :continente
                WHERE id = :id
                RETURNING id, nome, continente
            """),
            {"id": country_id, "nome": nome.strip(), "continente": continente.strip()},
        ).mappings().one_or_none()
        return dict(row) if row else None


def delete_country(country_id: int):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {settings.app_schema}.odds_jogos WHERE pais_id = :id"),
            {"id": country_id},
        )
        conn.execute(
            text(f"DELETE FROM {settings.app_schema}.valores_mercado WHERE pais_id = :id"),
            {"id": country_id},
        )
        row = conn.execute(
            text(f"DELETE FROM {settings.app_schema}.paises WHERE id = :id RETURNING id, nome"),
            {"id": country_id},
        ).mappings().one_or_none()
        return dict(row) if row else None


def manage_competitions(q: str | None = None, page: int = 1, page_size: int = 20):
    params = {}
    where = ""
    if q:
        params["q"] = f"%{q.strip()}%"
        where = """
        WHERE c.nome ILIKE :q
           OR p.nome ILIKE :q
           OR c.id::text ILIKE :q
           OR CASE WHEN c.principal THEN 'principal' ELSE 'não' END ILIKE :q
        """

    base = f"""
        FROM {settings.app_schema}.campeonatos c
        JOIN {settings.app_schema}.paises p ON p.id = c.pais_id
        {where}
    """
    return _paged(
        f"""
        SELECT c.id, c.nome, c.pais_id, p.nome AS pais, c.principal, c.criado_em
        {base}
        ORDER BY p.nome, c.principal DESC, c.nome
        LIMIT :limit OFFSET :offset
        """,
        f"SELECT COUNT(*) {base}",
        params, page, page_size,
    )


def update_competition(competition_id: int, nome: str, pais_id: int, principal: bool):
    with app_engine.begin() as conn:
        if principal:
            conn.execute(
                text(f"""
                    UPDATE {settings.app_schema}.campeonatos
                    SET principal = FALSE
                    WHERE pais_id = :pais_id AND id <> :id
                """),
                {"pais_id": pais_id, "id": competition_id},
            )

        row = conn.execute(
            text(f"""
                UPDATE {settings.app_schema}.campeonatos
                SET nome = :nome, pais_id = :pais_id, principal = :principal
                WHERE id = :id
                RETURNING id, nome, pais_id, principal
            """),
            {
                "id": competition_id,
                "nome": nome.strip(),
                "pais_id": pais_id,
                "principal": principal,
            },
        ).mappings().one_or_none()

        if row:
            conn.execute(
                text(f"""
                    UPDATE {settings.app_schema}.valores_mercado
                    SET pais_id = :pais_id, atualizado_em = NOW()
                    WHERE campeonato_id = :id
                """),
                {"pais_id": pais_id, "id": competition_id},
            )
            conn.execute(
                text(f"""
                    UPDATE {settings.app_schema}.odds_jogos
                    SET pais_id = :pais_id, atualizado_em = NOW()
                    WHERE campeonato_id = :id
                """),
                {"pais_id": pais_id, "id": competition_id},
            )

        return dict(row) if row else None


def delete_competition(competition_id: int):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {settings.app_schema}.odds_jogos WHERE campeonato_id = :id"),
            {"id": competition_id},
        )
        conn.execute(
            text(f"DELETE FROM {settings.app_schema}.valores_mercado WHERE campeonato_id = :id"),
            {"id": competition_id},
        )
        row = conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.campeonatos
                WHERE id = :id
                RETURNING id, nome
            """),
            {"id": competition_id},
        ).mappings().one_or_none()
        return dict(row) if row else None


def manage_clubs(
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    temporada: str | None = None,
    pais_id: int | None = None,
    campeonato_id: int | None = None,
):
    params = {}
    clauses = []

    if q:
        params["q"] = f"%{q.strip()}%"
        clauses.append(
            f"""
            (
                cl.nome ILIKE :q
                OR p.nome ILIKE :q
                OR COALESCE(cl.escudo_url, '') ILIKE :q
                OR cl.id::text ILIKE :q
                OR EXISTS (
                    SELECT 1
                    FROM {settings.app_schema}.clubes_campeonatos cc2
                    JOIN {settings.app_schema}.campeonatos c2
                      ON c2.id = cc2.campeonato_id
                    WHERE cc2.clube_id = cl.id
                      AND (
                          cc2.temporada ILIKE :q
                          OR c2.nome ILIKE :q
                      )
                )
            )
            """
        )

    if pais_id:
        clauses.append("cl.pais_id = :pais_id")
        params["pais_id"] = pais_id

    if temporada:
        clauses.append(
            f"""
            EXISTS (
                SELECT 1
                FROM {settings.app_schema}.clubes_campeonatos cc3
                WHERE cc3.clube_id = cl.id
                  AND cc3.temporada = :temporada
            )
            """
        )
        params["temporada"] = temporada

    if campeonato_id:
        clauses.append(
            f"""
            EXISTS (
                SELECT 1
                FROM {settings.app_schema}.clubes_campeonatos cc4
                WHERE cc4.clube_id = cl.id
                  AND cc4.campeonato_id = :campeonato_id
                  {"AND cc4.temporada = :temporada" if temporada else ""}
            )
            """
        )
        params["campeonato_id"] = campeonato_id

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    base = f"""
        FROM {settings.app_schema}.clubes cl
        JOIN {settings.app_schema}.paises p ON p.id = cl.pais_id
        {where}
    """

    return _paged(
        f"""
        SELECT
            cl.id,
            cl.nome,
            cl.pais_id,
            p.nome AS pais,
            cl.escudo_url,
            cl.criado_em,
            COALESCE(
                (
                    SELECT STRING_AGG(
                        cc.temporada || ' · ' || c.nome,
                        ' | '
                        ORDER BY cc.temporada DESC, c.nome
                    )
                    FROM {settings.app_schema}.clubes_campeonatos cc
                    JOIN {settings.app_schema}.campeonatos c
                      ON c.id = cc.campeonato_id
                    WHERE cc.clube_id = cl.id
                ),
                ''
            ) AS vinculos
        {base}
        ORDER BY cl.nome
        LIMIT :limit OFFSET :offset
        """,
        f"SELECT COUNT(*) {base}",
        params,
        page,
        page_size,
    )

def get_club_management(club_id: int):
    with app_engine.connect() as conn:
        club = conn.execute(
            text(f"""
                SELECT cl.id, cl.nome, cl.pais_id, p.nome AS pais, cl.escudo_url
                FROM {settings.app_schema}.clubes cl
                JOIN {settings.app_schema}.paises p ON p.id = cl.pais_id
                WHERE cl.id = :id
            """),
            {"id": club_id},
        ).mappings().one_or_none()

        if not club:
            return None

        memberships = [
            dict(r._mapping)
            for r in conn.execute(
                text(f"""
                    SELECT cc.campeonato_id, c.nome AS campeonato, cc.temporada
                    FROM {settings.app_schema}.clubes_campeonatos cc
                    JOIN {settings.app_schema}.campeonatos c ON c.id = cc.campeonato_id
                    WHERE cc.clube_id = :id
                    ORDER BY cc.temporada DESC, c.nome
                """),
                {"id": club_id},
            )
        ]

    result = dict(club)
    result["vinculos"] = memberships
    return result


def update_club(club_id: int, nome: str, pais_id: int, escudo_url: str | None):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                UPDATE {settings.app_schema}.clubes
                SET nome = :nome, pais_id = :pais_id, escudo_url = :escudo_url
                WHERE id = :id
                RETURNING id, nome, pais_id, escudo_url
            """),
            {
                "id": club_id,
                "nome": nome.strip(),
                "pais_id": pais_id,
                "escudo_url": (escudo_url or "").strip() or None,
            },
        ).mappings().one_or_none()

        if row:
            conn.execute(
                text(f"""
                    UPDATE {settings.app_schema}.valores_mercado
                    SET pais_id = :pais_id, atualizado_em = NOW()
                    WHERE clube_id = :id
                """),
                {"pais_id": pais_id, "id": club_id},
            )

        return dict(row) if row else None


def previous_season_label(temporada: str) -> str:
    value = (temporada or "").strip()
    match = re.match(r"^(\d{4})\s*([/-])\s*(\d{2}|\d{4})$", value)
    if match:
        start = int(match.group(1))
        sep = match.group(2)
        end_raw = match.group(3)
        if len(end_raw) == 2:
            end = (int(end_raw) - 1) % 100
            return f"{start - 1}{sep}{end:02d}"
        return f"{start - 1}{sep}{int(end_raw) - 1}"
    if re.match(r"^\d{4}$", value):
        return str(int(value) - 1)
    raise ValueError("Use a temporada no formato 2016/2017, 2016-2017 ou 2017.")


def _competition_identity(conn, campeonato_id: int):
    """
    Resolve a competição pela identidade lógica (país + nome normalizado).

    Isso deixa a importação robusta até para bases antigas que possam ter mais de
    um registro técnico representando o mesmo campeonato. Para o usuário, todos
    esses registros são o mesmo campeonato.
    """
    competition = conn.execute(
        text(f"""
            SELECT id, nome, pais_id
            FROM {settings.app_schema}.campeonatos
            WHERE id = :id
        """),
        {"id": campeonato_id},
    ).mappings().one_or_none()

    if not competition:
        return None, []

    equivalent_ids = list(
        conn.execute(
            text(f"""
                SELECT id
                FROM {settings.app_schema}.campeonatos
                WHERE pais_id = :country_id
                  AND LOWER(TRIM(nome)) = LOWER(TRIM(:competition_name))
                ORDER BY id
            """),
            {
                "country_id": competition["pais_id"],
                "competition_name": competition["nome"],
            },
        ).scalars().all()
    )

    if campeonato_id not in equivalent_ids:
        equivalent_ids.append(campeonato_id)

    return competition, sorted(set(int(x) for x in equivalent_ids))


def preview_previous_season_clubs(campeonato_id: int, temporada: str):
    """
    Regra definitiva da seção "Clubes da temporada anterior":

    1. A temporada origem é EXATAMENTE a temporada imediatamente anterior.
    2. Se não existir nenhum vínculo cadastrado dessa temporada anterior para o
       campeonato, retorna lista vazia.
    3. Se a temporada anterior estiver cadastrada, usamos o histórico de jogos
       somente como proteção contra cadastros parcialmente apagados: recuperamos
       todos os clubes que efetivamente participaram do mesmo campeonato/temporada
       e restauramos no banco principal os vínculos ausentes.
    4. A lista final sempre vem do banco principal já reconciliado.

    Isso evita que a exclusão acidental de vínculos de uma temporada posterior
    destrua a capacidade de importar a temporada seguinte.
    """
    source_season = previous_season_label(temporada)
    target_season = temporada.strip()

    with app_engine.begin() as conn:
        competition, equivalent_ids = _competition_identity(conn, campeonato_id)
        if not competition:
            raise ValueError("Campeonato não encontrado.")

        country = conn.execute(
            text(f"""
                SELECT nome
                FROM {settings.app_schema}.paises
                WHERE id = :country_id
            """),
            {"country_id": competition["pais_id"]},
        ).scalar_one_or_none()

        registered_previous_count = int(
            conn.execute(
                text(f"""
                    SELECT COUNT(*)
                    FROM {settings.app_schema}.clubes_campeonatos
                    WHERE campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                      AND temporada = :source_season
                """),
                {
                    "competition_ids": equivalent_ids,
                    "source_season": source_season,
                },
            ).scalar_one()
            or 0
        )

        # Se nenhuma temporada anterior foi cadastrada no sistema, não inventamos
        # uma temporada a partir do histórico: a seção deve permanecer vazia.
        if registered_previous_count == 0:
            return {
                "campeonato": {
                    "id": competition["id"],
                    "nome": competition["nome"],
                    "pais_id": competition["pais_id"],
                },
                "temporada_origem": source_season,
                "temporada_destino": target_season,
                "clubes": [],
            }

        # Se a temporada existe mas ficou parcialmente cadastrada (por exemplo,
        # após uma exclusão antiga de clube), reconciliamos com o histórico real.
        history_names = []
        if country:
            try:
                with history_connection() as hconn:
                    history_names = [
                        str(name).strip()
                        for name in hconn.execute(
                            text(f"""
                                SELECT DISTINCT clube
                                FROM (
                                    SELECT casa AS clube
                                    FROM {settings.history_schema}.{settings.history_table}
                                    WHERE LOWER(TRIM(pais)) = LOWER(TRIM(:country))
                                      AND LOWER(TRIM(campeonato)) = LOWER(TRIM(:competition))
                                      AND temporada::text = :season
                                      AND casa IS NOT NULL

                                    UNION

                                    SELECT fora AS clube
                                    FROM {settings.history_schema}.{settings.history_table}
                                    WHERE LOWER(TRIM(pais)) = LOWER(TRIM(:country))
                                      AND LOWER(TRIM(campeonato)) = LOWER(TRIM(:competition))
                                      AND temporada::text = :season
                                      AND fora IS NOT NULL
                                ) clubs
                                WHERE clube IS NOT NULL
                                ORDER BY clube
                            """),
                            {
                                "country": country,
                                "competition": competition["nome"],
                                "season": source_season,
                            },
                        ).scalars().all()
                        if str(name).strip()
                    ]
            except Exception:
                # O histórico é somente leitura e é uma camada de reconciliação.
                # Se estiver indisponível, mantemos os vínculos já cadastrados.
                history_names = []

        for club_name in history_names:
            club = conn.execute(
                text(f"""
                    SELECT id, nome
                    FROM {settings.app_schema}.clubes
                    WHERE pais_id = :country_id
                      AND LOWER(TRIM(nome)) = LOWER(TRIM(:club_name))
                    ORDER BY id
                    LIMIT 1
                """),
                {
                    "country_id": competition["pais_id"],
                    "club_name": club_name,
                },
            ).mappings().one_or_none()

            if not club:
                club = conn.execute(
                    text(f"""
                        INSERT INTO {settings.app_schema}.clubes
                            (nome, pais_id, escudo_url)
                        VALUES (:club_name, :country_id, NULL)
                        ON CONFLICT (pais_id, (LOWER(nome)))
                        DO UPDATE SET nome = EXCLUDED.nome
                        RETURNING id, nome
                    """),
                    {
                        "club_name": club_name,
                        "country_id": competition["pais_id"],
                    },
                ).mappings().one()

            conn.execute(
                text(f"""
                    INSERT INTO {settings.app_schema}.clubes_campeonatos
                        (clube_id, campeonato_id, temporada)
                    VALUES (:club_id, :competition_id, :source_season)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "club_id": club["id"],
                    "competition_id": campeonato_id,
                    "source_season": source_season,
                },
            )

        rows = [
            dict(r._mapping)
            for r in conn.execute(
                text(f"""
                    SELECT DISTINCT
                        cl.id,
                        cl.nome,
                        cl.escudo_url,
                        p.nome AS pais,
                        EXISTS (
                            SELECT 1
                            FROM {settings.app_schema}.clubes_campeonatos target
                            WHERE target.clube_id = cl.id
                              AND target.campeonato_id = :destination_competition_id
                              AND target.temporada = :target_season
                        ) AS ja_cadastrado
                    FROM {settings.app_schema}.clubes_campeonatos source
                    JOIN {settings.app_schema}.clubes cl
                      ON cl.id = source.clube_id
                    JOIN {settings.app_schema}.paises p
                      ON p.id = cl.pais_id
                    WHERE source.campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                      AND source.temporada = :source_season
                    ORDER BY cl.nome
                """),
                {
                    "competition_ids": equivalent_ids,
                    "destination_competition_id": campeonato_id,
                    "source_season": source_season,
                    "target_season": target_season,
                },
            )
        ]

    return {
        "campeonato": {
            "id": competition["id"],
            "nome": competition["nome"],
            "pais_id": competition["pais_id"],
        },
        "temporada_origem": source_season,
        "temporada_destino": target_season,
        "clubes": rows,
    }

def search_competition_clubs(
    campeonato_id: int,
    q: str | None = None,
    temporada: str | None = None,
    limit: int = 300,
):
    """
    Regra da lista suspensa "Adicionar clubes novos / promovidos":

    - reúne todos os clubes ÚNICOS que já foram vinculados ao mesmo campeonato
      em QUALQUER temporada;
    - ignora completamente a temporada para decidir quem pertence à lista;
    - o frontend remove dessa lista somente os clubes exibidos em
      "Clubes da temporada anterior";
    - `temporada` é mantida apenas para informar se o clube já está no destino.

    Assim, por exemplo, um Hannover cadastrado em 2015/2016 aparece ao montar
    2017/2018, desde que não esteja na lista exata da temporada 2016/2017.
    """
    term = (q or "").strip()
    limit = max(1, min(int(limit), 500))
    target_season = (temporada or "").strip() or None
    source_season = previous_season_label(target_season) if target_season else None

    with app_engine.connect() as conn:
        competition, equivalent_ids = _competition_identity(conn, campeonato_id)
        if not competition:
            return []

        params = {
            "competition_ids": equivalent_ids,
            "destination_competition_id": campeonato_id,
            "target_season": target_season,
            "source_season": source_season,
            "limit": limit,
        }

        search_clause = ""
        if term:
            search_clause = "AND cl.nome ILIKE :q"
            params["q"] = f"%{term}%"
            params["exact"] = term
            order_sql = (
                "CASE WHEN LOWER(TRIM(cl.nome)) = LOWER(TRIM(:exact)) "
                "THEN 0 ELSE 1 END, cl.nome"
            )
        else:
            order_sql = "cl.nome"

        rows = conn.execute(
            text(f"""
                SELECT
                    cl.id,
                    cl.nome,
                    cl.escudo_url,
                    cl.pais_id,
                    p.nome AS pais,
                    CASE
                        WHEN :target_season IS NULL THEN FALSE
                        ELSE EXISTS (
                            SELECT 1
                            FROM {settings.app_schema}.clubes_campeonatos target
                            WHERE target.clube_id = cl.id
                              AND target.campeonato_id = :destination_competition_id
                              AND target.temporada = :target_season
                        )
                    END AS ja_cadastrado,
                    COALESCE((
                        SELECT STRING_AGG(DISTINCT cc2.temporada, ' | ')
                        FROM {settings.app_schema}.clubes_campeonatos cc2
                        WHERE cc2.clube_id = cl.id
                          AND cc2.campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                    ), '') AS historico
                FROM {settings.app_schema}.clubes cl
                JOIN {settings.app_schema}.paises p
                  ON p.id = cl.pais_id
                WHERE EXISTS (
                    SELECT 1
                    FROM {settings.app_schema}.clubes_campeonatos cc
                    WHERE cc.clube_id = cl.id
                      AND cc.campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                )
                  AND (
                      :source_season IS NULL
                      OR NOT EXISTS (
                          SELECT 1
                          FROM {settings.app_schema}.clubes_campeonatos prev
                          WHERE prev.clube_id = cl.id
                            AND prev.campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                            AND prev.temporada = :source_season
                      )
                  )
                  {search_clause}
                ORDER BY {order_sql}
                LIMIT :limit
            """),
            params,
        ).mappings().all()

    return [dict(row) for row in rows]

def import_previous_season_clubs(
    campeonato_id: int,
    temporada: str,
    clube_ids: list[int],
    novos_clubes: list[dict] | None = None,
):
    source_season = previous_season_label(temporada)
    target_season = temporada.strip()
    requested_ids = sorted({int(x) for x in clube_ids})
    additional = novos_clubes or []

    if len(additional) > 10:
        raise ValueError("É possível adicionar no máximo 10 novos clubes por importação.")

    # Remove linhas vazias e duplicidades pelo nome digitado.
    clean_additional = []
    seen_names = set()
    for item in additional:
        name = str(item.get("nome") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        clean_additional.append({
            "nome": name,
            "clube_id": int(item["clube_id"]) if item.get("clube_id") else None,
        })

    with app_engine.begin() as conn:
        competition, equivalent_ids = _competition_identity(conn, campeonato_id)

        if not competition:
            raise ValueError("Campeonato não encontrado.")

        eligible_ids = set()
        if requested_ids:
            eligible_ids = set(
                conn.execute(
                    text(f"""
                        SELECT DISTINCT clube_id
                        FROM {settings.app_schema}.clubes_campeonatos
                        WHERE campeonato_id = ANY(CAST(:competition_ids AS BIGINT[]))
                          AND temporada = :source_season
                          AND clube_id = ANY(CAST(:club_ids AS BIGINT[]))
                    """),
                    {
                        "competition_ids": equivalent_ids,
                        "source_season": source_season,
                        "club_ids": requested_ids,
                    },
                ).scalars().all()
            )

        existing_ids = set()
        if eligible_ids:
            existing_ids = set(
                conn.execute(
                    text(f"""
                        SELECT clube_id
                        FROM {settings.app_schema}.clubes_campeonatos
                        WHERE campeonato_id = :competition_id
                          AND temporada = :target_season
                          AND clube_id = ANY(CAST(:club_ids AS BIGINT[]))
                    """),
                    {
                        "competition_id": campeonato_id,
                        "target_season": target_season,
                        "club_ids": sorted(eligible_ids),
                    },
                ).scalars().all()
            )

        imported_previous_ids = sorted(eligible_ids - existing_ids)
        for club_id in imported_previous_ids:
            conn.execute(
                text(f"""
                    INSERT INTO {settings.app_schema}.clubes_campeonatos
                        (clube_id, campeonato_id, temporada)
                    VALUES (:club_id, :competition_id, :target_season)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "club_id": club_id,
                    "competition_id": campeonato_id,
                    "target_season": target_season,
                },
            )

        created_count = 0
        reused_count = 0
        already_target_count = 0
        added_link_count = 0
        additional_result = []

        for item in clean_additional:
            club = None
            supplied_id = item.get("clube_id")

            # Se o usuário escolheu uma sugestão, validamos o clube e o país.
            if supplied_id:
                club = conn.execute(
                    text(f"""
                        SELECT id, nome, pais_id, escudo_url
                        FROM {settings.app_schema}.clubes
                        WHERE id = :id
                          AND pais_id = :country_id
                    """),
                    {"id": supplied_id, "country_id": competition["pais_id"]},
                ).mappings().one_or_none()

            # Mesmo sem escolher a sugestão, nunca duplicamos um clube já cadastrado
            # no país se o nome for exatamente o mesmo (ignorando maiúsculas/minúsculas).
            if not club:
                club = conn.execute(
                    text(f"""
                        SELECT id, nome, pais_id, escudo_url
                        FROM {settings.app_schema}.clubes
                        WHERE pais_id = :country_id
                          AND LOWER(nome) = LOWER(:name)
                        LIMIT 1
                    """),
                    {"country_id": competition["pais_id"], "name": item["nome"]},
                ).mappings().one_or_none()

            created = False
            if not club:
                club = conn.execute(
                    text(f"""
                        INSERT INTO {settings.app_schema}.clubes (nome, pais_id, escudo_url)
                        VALUES (:name, :country_id, NULL)
                        ON CONFLICT (pais_id, (LOWER(nome)))
                        DO UPDATE SET nome = EXCLUDED.nome
                        RETURNING id, nome, pais_id, escudo_url
                    """),
                    {"name": item["nome"], "country_id": competition["pais_id"]},
                ).mappings().one()
                created = True
                created_count += 1
            else:
                reused_count += 1

            already_target = bool(
                conn.execute(
                    text(f"""
                        SELECT 1
                        FROM {settings.app_schema}.clubes_campeonatos
                        WHERE clube_id = :club_id
                          AND campeonato_id = :competition_id
                          AND temporada = :target_season
                        LIMIT 1
                    """),
                    {
                        "club_id": club["id"],
                        "competition_id": campeonato_id,
                        "target_season": target_season,
                    },
                ).scalar()
            )

            if already_target:
                already_target_count += 1
            else:
                conn.execute(
                    text(f"""
                        INSERT INTO {settings.app_schema}.clubes_campeonatos
                            (clube_id, campeonato_id, temporada)
                        VALUES (:club_id, :competition_id, :target_season)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "club_id": club["id"],
                        "competition_id": campeonato_id,
                        "target_season": target_season,
                    },
                )
                added_link_count += 1

            additional_result.append({
                "id": club["id"],
                "nome": club["nome"],
                "criado": created,
                "ja_cadastrado": already_target,
            })

    return {
        "temporada_origem": source_season,
        "temporada_destino": target_season,
        "solicitados": len(requested_ids),
        "elegiveis": len(eligible_ids),
        "importados": len(imported_previous_ids),
        "ja_existentes": len(existing_ids),
        "novos_informados": len(clean_additional),
        "novos_cadastrados": created_count,
        "clubes_reaproveitados": reused_count,
        "novos_vinculos": added_link_count,
        "adicionais_ja_existentes": already_target_count,
        "clubes_adicionais": additional_result,
    }


def add_club_membership(club_id: int, campeonato_id: int, temporada: str):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.clubes_campeonatos
                    (clube_id, campeonato_id, temporada)
                VALUES (:clube_id, :campeonato_id, :temporada)
                ON CONFLICT DO NOTHING
            """),
            {
                "clube_id": club_id,
                "campeonato_id": campeonato_id,
                "temporada": temporada.strip(),
            },
        )


def update_club_membership(
    club_id: int,
    old_campeonato_id: int,
    old_temporada: str,
    campeonato_id: int,
    temporada: str,
):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.clubes_campeonatos
                WHERE clube_id = :club_id
                  AND campeonato_id = :old_comp
                  AND temporada = :old_season
            """),
            {
                "club_id": club_id,
                "old_comp": old_campeonato_id,
                "old_season": old_temporada,
            },
        )
        conn.execute(
            text(f"""
                INSERT INTO {settings.app_schema}.clubes_campeonatos
                    (clube_id, campeonato_id, temporada)
                VALUES (:club_id, :competition_id, :season)
                ON CONFLICT DO NOTHING
            """),
            {
                "club_id": club_id,
                "competition_id": campeonato_id,
                "season": temporada.strip(),
            },
        )


def delete_club_membership(club_id: int, campeonato_id: int, temporada: str):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.clubes_campeonatos
                WHERE clube_id = :club_id
                  AND campeonato_id = :competition_id
                  AND temporada = :season
            """),
            {
                "club_id": club_id,
                "competition_id": campeonato_id,
                "season": temporada,
            },
        )


def delete_club(club_id: int):
    with app_engine.begin() as conn:
        conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.odds_jogos
                WHERE clube_casa_id = :id OR clube_fora_id = :id
            """),
            {"id": club_id},
        )
        conn.execute(
            text(f"DELETE FROM {settings.app_schema}.valores_mercado WHERE clube_id = :id"),
            {"id": club_id},
        )
        row = conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.clubes
                WHERE id = :id
                RETURNING id, nome
            """),
            {"id": club_id},
        ).mappings().one_or_none()
        return dict(row) if row else None


def manage_market_values(q: str | None = None, page: int = 1, page_size: int = 20):
    params = {}
    where = ""
    if q:
        params["q"] = f"%{q.strip()}%"
        where = """
        WHERE vm.temporada ILIKE :q
           OR p.nome ILIKE :q
           OR c.nome ILIKE :q
           OR cl.nome ILIKE :q
           OR vm.moeda ILIKE :q
           OR vm.valor::text ILIKE :q
           OR vm.id::text ILIKE :q
        """

    base = f"""
        FROM {settings.app_schema}.valores_mercado vm
        JOIN {settings.app_schema}.paises p ON p.id = vm.pais_id
        JOIN {settings.app_schema}.campeonatos c ON c.id = vm.campeonato_id
        JOIN {settings.app_schema}.clubes cl ON cl.id = vm.clube_id
        {where}
    """

    return _paged(
        f"""
        SELECT
            vm.id,
            vm.temporada,
            vm.pais_id,
            p.nome AS pais,
            vm.campeonato_id,
            c.nome AS campeonato,
            vm.clube_id,
            cl.nome AS clube,
            cl.escudo_url,
            vm.valor::float AS valor,
            vm.moeda,
            vm.criado_em,
            vm.atualizado_em
        {base}
        ORDER BY vm.atualizado_em DESC, vm.id DESC
        LIMIT :limit OFFSET :offset
        """,
        f"SELECT COUNT(*) {base}",
        params, page, page_size,
    )


def update_market_value(value_id: int, data: dict):
    with app_engine.begin() as conn:
        old = conn.execute(
            text(f"""
                SELECT campeonato_id, temporada
                FROM {settings.app_schema}.valores_mercado
                WHERE id = :id
            """),
            {"id": value_id},
        ).mappings().one_or_none()

        row = conn.execute(
            text(f"""
                UPDATE {settings.app_schema}.valores_mercado
                SET temporada = :temporada,
                    pais_id = :pais_id,
                    campeonato_id = :campeonato_id,
                    clube_id = :clube_id,
                    valor = :valor,
                    moeda = :moeda,
                    atualizado_em = NOW()
                WHERE id = :id
                RETURNING id, temporada, pais_id, campeonato_id, clube_id, valor, moeda
            """),
            {"id": value_id, **data},
        ).mappings().one_or_none()

        if row:
            conn.execute(
                text(f"""
                    INSERT INTO {settings.app_schema}.clubes_campeonatos
                        (clube_id, campeonato_id, temporada)
                    VALUES (:clube_id, :campeonato_id, :temporada)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "clube_id": data["clube_id"],
                    "campeonato_id": data["campeonato_id"],
                    "temporada": data["temporada"],
                },
            )

        return {
            "row": dict(row) if row else None,
            "old": dict(old) if old else None,
        }


def delete_market_value(value_id: int):
    with app_engine.begin() as conn:
        row = conn.execute(
            text(f"""
                DELETE FROM {settings.app_schema}.valores_mercado
                WHERE id = :id
                RETURNING id, temporada, campeonato_id, clube_id
            """),
            {"id": value_id},
        ).mappings().one_or_none()
        return dict(row) if row else None
