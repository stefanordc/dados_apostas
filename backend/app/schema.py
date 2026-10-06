from sqlalchemy import text
from .config import settings
from .db import app_engine
from .seed_data import COUNTRIES_BY_CONTINENT

DDL = [
    "CREATE SCHEMA IF NOT EXISTS {schema}",
    """
    CREATE TABLE IF NOT EXISTS {schema}.paises (
        id BIGSERIAL PRIMARY KEY,
        nome TEXT NOT NULL,
        continente TEXT NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.campeonatos (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE CASCADE,
        nome TEXT NOT NULL,
        principal BOOLEAN NOT NULL DEFAULT FALSE,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE {schema}.campeonatos ADD COLUMN IF NOT EXISTS principal BOOLEAN NOT NULL DEFAULT FALSE",
    """
    CREATE TABLE IF NOT EXISTS {schema}.clubes (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE CASCADE,
        nome TEXT NOT NULL,
        escudo_url TEXT,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE {schema}.clubes ADD COLUMN IF NOT EXISTS escudo_url TEXT",
    """
    CREATE TABLE IF NOT EXISTS {schema}.clubes_campeonatos (
        clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE CASCADE,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE CASCADE,
        temporada TEXT NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (clube_id, campeonato_id, temporada)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.valores_mercado (
        id BIGSERIAL PRIMARY KEY,
        temporada TEXT NOT NULL,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE RESTRICT,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE RESTRICT,
        clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE RESTRICT,
        valor NUMERIC(18,2) NOT NULL CHECK (valor >= 0),
        moeda TEXT NOT NULL CHECK (moeda IN ('EUR','USD','BRL')),
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.valor_mercado_importacoes (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE RESTRICT,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE RESTRICT,
        moeda TEXT NOT NULL CHECK (moeda IN ('EUR','USD','BRL')),
        temporadas TEXT NOT NULL,
        total_linhas INTEGER NOT NULL DEFAULT 0,
        linhas_importadas INTEGER NOT NULL DEFAULT 0,
        origem TEXT NOT NULL DEFAULT 'manual',
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        excluido_em TIMESTAMPTZ
    )
    """,
    "ALTER TABLE {schema}.valores_mercado ADD COLUMN IF NOT EXISTS carga_id BIGINT REFERENCES {schema}.valor_mercado_importacoes(id) ON DELETE SET NULL",
    """
    CREATE TABLE IF NOT EXISTS {schema}.clubes_aliases (
        id BIGSERIAL PRIMARY KEY,
        clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE CASCADE,
        campeonato_id BIGINT REFERENCES {schema}.campeonatos(id) ON DELETE CASCADE,
        alias TEXT NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.odds_importacoes (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE RESTRICT,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE RESTRICT,
        temporada TEXT NOT NULL,
        total_linhas INTEGER NOT NULL DEFAULT 0,
        linhas_importadas INTEGER NOT NULL DEFAULT 0,
        origem TEXT NOT NULL DEFAULT 'manual',
        resumo_hash TEXT,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        excluido_em TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.odds_jogos (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE RESTRICT,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE RESTRICT,
        temporada TEXT NOT NULL,
        data DATE,
        rodada TEXT,
        clube_casa_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE RESTRICT,
        clube_fora_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE RESTRICT,
        mandante_origem TEXT NOT NULL,
        visitante_origem TEXT NOT NULL,
        odd_casa NUMERIC(10,4),
        odd_empate NUMERIC(10,4),
        odd_fora NUMERIC(10,4),
        source_key TEXT NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE {schema}.odds_jogos ADD COLUMN IF NOT EXISTS odd_over_25 NUMERIC(10,4)",
    "ALTER TABLE {schema}.odds_jogos ADD COLUMN IF NOT EXISTS odd_under_25 NUMERIC(10,4)",
    "ALTER TABLE {schema}.odds_jogos ADD COLUMN IF NOT EXISTS carga_id BIGINT REFERENCES {schema}.odds_importacoes(id) ON DELETE SET NULL",
    """
    CREATE TABLE IF NOT EXISTS {schema}.app_migrations (
        chave TEXT PRIMARY KEY,
        detalhe TEXT,
        executado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.elo_temporadas (
        id BIGSERIAL PRIMARY KEY,
        pais_id BIGINT NOT NULL REFERENCES {schema}.paises(id) ON DELETE CASCADE,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE CASCADE,
        temporada TEXT NOT NULL,
        completo BOOLEAN NOT NULL DEFAULT FALSE,
        clubes_esperados INTEGER NOT NULL DEFAULT 0,
        clubes_com_valor INTEGER NOT NULL DEFAULT 0,
        jogos_processados INTEGER NOT NULL DEFAULT 0,
        jogos_ignorados INTEGER NOT NULL DEFAULT 0,
        beta NUMERIC(8,3) NOT NULL DEFAULT 100,
        k_factor NUMERIC(8,3) NOT NULL DEFAULT 20,
        vantagem_mando NUMERIC(8,3) NOT NULL DEFAULT 60,
        retencao NUMERIC(8,4) NOT NULL DEFAULT 0.8,
        peso_performance NUMERIC(8,4) NOT NULL DEFAULT 0.8,
        peso_mercado NUMERIC(8,4) NOT NULL DEFAULT 0.2,
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.elo_clubes (
        id BIGSERIAL PRIMARY KEY,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE CASCADE,
        temporada TEXT NOT NULL,
        clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE CASCADE,
        elo_mercado NUMERIC(12,4) NOT NULL,
        elo_inicial NUMERIC(12,4) NOT NULL,
        elo_atual NUMERIC(12,4) NOT NULL,
        elo_max NUMERIC(12,4) NOT NULL,
        elo_min NUMERIC(12,4) NOT NULL,
        jogos INTEGER NOT NULL DEFAULT 0,
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.elo_movimentos (
        id BIGSERIAL PRIMARY KEY,
        campeonato_id BIGINT NOT NULL REFERENCES {schema}.campeonatos(id) ON DELETE CASCADE,
        temporada TEXT NOT NULL,
        history_game_key TEXT NOT NULL,
        data DATE,
        rodada TEXT,
        casa_clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE CASCADE,
        fora_clube_id BIGINT NOT NULL REFERENCES {schema}.clubes(id) ON DELETE CASCADE,
        gols_casa INTEGER NOT NULL,
        gols_fora INTEGER NOT NULL,
        elo_casa_antes NUMERIC(12,4) NOT NULL,
        elo_fora_antes NUMERIC(12,4) NOT NULL,
        expectativa_casa NUMERIC(12,8) NOT NULL,
        resultado_casa NUMERIC(4,2) NOT NULL,
        delta_casa NUMERIC(12,4) NOT NULL,
        elo_casa_depois NUMERIC(12,4) NOT NULL,
        elo_fora_depois NUMERIC(12,4) NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_paises_nome_lower ON {schema}.paises ((LOWER(nome)))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_campeonatos_pais_nome_lower ON {schema}.campeonatos (pais_id, (LOWER(nome)))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_campeonatos_principal_pais ON {schema}.campeonatos (pais_id) WHERE principal",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_clubes_pais_nome_lower ON {schema}.clubes (pais_id, (LOWER(nome)))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_vm_temporada_campeonato_clube ON {schema}.valores_mercado (temporada, campeonato_id, clube_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_alias_campeonato_lower ON {schema}.clubes_aliases (COALESCE(campeonato_id,0), (LOWER(alias)))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_source_key ON {schema}.odds_jogos (source_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_elo_temporada ON {schema}.elo_temporadas (campeonato_id, temporada)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_elo_clube ON {schema}.elo_clubes (campeonato_id, temporada, clube_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_elo_movimento_jogo ON {schema}.elo_movimentos (campeonato_id, temporada, history_game_key)",
    "CREATE INDEX IF NOT EXISTS ix_cc_temporada_campeonato ON {schema}.clubes_campeonatos (temporada, campeonato_id)",
    "CREATE INDEX IF NOT EXISTS ix_vm_temporada_campeonato ON {schema}.valores_mercado (temporada, campeonato_id)",
    "CREATE INDEX IF NOT EXISTS ix_vm_carga ON {schema}.valores_mercado (carga_id)",
    "CREATE INDEX IF NOT EXISTS ix_vm_importacoes_data ON {schema}.valor_mercado_importacoes (criado_em DESC)",
    "CREATE INDEX IF NOT EXISTS ix_odds_comp_temp_clubes ON {schema}.odds_jogos (campeonato_id, temporada, clube_casa_id, clube_fora_id)",
    "CREATE INDEX IF NOT EXISTS ix_odds_data ON {schema}.odds_jogos (data)",
    "CREATE INDEX IF NOT EXISTS ix_odds_carga ON {schema}.odds_jogos (carga_id)",
    "CREATE INDEX IF NOT EXISTS ix_odds_importacoes_data ON {schema}.odds_importacoes (criado_em DESC)",
    "CREATE INDEX IF NOT EXISTS ix_elo_mov_clubes_data ON {schema}.elo_movimentos (campeonato_id, temporada, casa_clube_id, fora_clube_id, data)",
]


def initialize_database() -> None:
    schema = settings.app_schema
    with app_engine.begin() as conn:
        for stmt in DDL:
            conn.exec_driver_sql(stmt.format(schema=schema))

        # Migração única: remove a carga problemática do Alemão 2018/2019
        # autorizada pelo usuário e registra o evento no histórico de cargas.
        migration_key = "remove_bad_odds_alemao_2018_2019_20261005"
        already = conn.execute(
            text(f"SELECT 1 FROM {schema}.app_migrations WHERE chave = :key"),
            {"key": migration_key},
        ).scalar()
        if not already:
            bad = conn.execute(
                text(f"""
                    SELECT o.id, o.pais_id, o.campeonato_id, o.temporada, o.criado_em
                    FROM {schema}.odds_jogos o
                    JOIN {schema}.campeonatos c ON c.id = o.campeonato_id
                    JOIN {schema}.paises p ON p.id = o.pais_id
                    WHERE LOWER(p.nome) = LOWER('Alemanha')
                      AND LOWER(c.nome) = LOWER('Alemão')
                      AND o.temporada = '2018/2019'
                """),
            ).mappings().all()
            if bad:
                batch_id = conn.execute(
                    text(f"""
                        INSERT INTO {schema}.odds_importacoes
                            (pais_id, campeonato_id, temporada, total_linhas, linhas_importadas, origem, criado_em, excluido_em)
                        VALUES (:p, :c, '2018/2019', :n, :n, 'legado-removido',
                                COALESCE(:created_at, NOW()), NOW())
                        RETURNING id
                    """),
                    {
                        "p": bad[0]["pais_id"],
                        "c": bad[0]["campeonato_id"],
                        "n": len(bad),
                        "created_at": max((r["criado_em"] for r in bad if r["criado_em"]), default=None),
                    },
                ).scalar_one()
                conn.execute(
                    text(f"""
                        DELETE FROM {schema}.odds_jogos o
                        USING {schema}.campeonatos c, {schema}.paises p
                        WHERE o.campeonato_id = c.id
                          AND o.pais_id = p.id
                          AND LOWER(p.nome) = LOWER('Alemanha')
                          AND LOWER(c.nome) = LOWER('Alemão')
                          AND o.temporada = '2018/2019'
                    """),
                )
                detalhe = f"{len(bad)} odds removidas; carga histórica {batch_id}."
            else:
                detalhe = "Nenhuma odd encontrada para Alemanha / Alemão / 2018/2019."
            conn.execute(
                text(f"INSERT INTO {schema}.app_migrations (chave, detalhe) VALUES (:key, :detail)"),
                {"key": migration_key, "detail": detalhe},
            )

        # Backfill de cargas antigas ainda sem carga_id. Agrupa por país/campeonato/temporada.
        legacy_groups = conn.execute(
            text(f"""
                SELECT pais_id, campeonato_id, temporada, COUNT(*) AS n, MAX(criado_em) AS criado_em
                FROM {schema}.odds_jogos
                WHERE carga_id IS NULL
                GROUP BY pais_id, campeonato_id, temporada
                ORDER BY MAX(criado_em)
            """),
        ).mappings().all()
        for group in legacy_groups:
            batch_id = conn.execute(
                text(f"""
                    INSERT INTO {schema}.odds_importacoes
                        (pais_id, campeonato_id, temporada, total_linhas, linhas_importadas, origem, criado_em)
                    VALUES (:p, :c, :s, :n, :n, 'legado', COALESCE(:created_at, NOW()))
                    RETURNING id
                """),
                {
                    "p": group["pais_id"],
                    "c": group["campeonato_id"],
                    "s": group["temporada"],
                    "n": group["n"],
                    "created_at": group["criado_em"],
                },
            ).scalar_one()
            conn.execute(
                text(f"""
                    UPDATE {schema}.odds_jogos
                    SET carga_id = :batch
                    WHERE carga_id IS NULL
                      AND pais_id = :p
                      AND campeonato_id = :c
                      AND temporada = :s
                """),
                {
                    "batch": batch_id,
                    "p": group["pais_id"],
                    "c": group["campeonato_id"],
                    "s": group["temporada"],
                },
            )

        country_count = conn.execute(
            text(f"SELECT COUNT(*) FROM {schema}.paises")
        ).scalar_one()

        if int(country_count or 0) == 0:
            for continent, names in COUNTRIES_BY_CONTINENT.items():
                for name in names:
                    conn.execute(
                        text(f"""
                            INSERT INTO {schema}.paises (nome, continente)
                            VALUES (:nome, :continente)
                            ON CONFLICT ((LOWER(nome)))
                            DO NOTHING
                        """),
                        {"nome": name, "continente": continent},
                    )
