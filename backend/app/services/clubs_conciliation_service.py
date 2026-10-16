"""Decisões manuais, persistentes e auditáveis de nomes entre as duas fontes.

O banco de histórico permanece somente leitura. O mapeamento mora no banco
principal e nunca modifica a grafia bruta das tabelas de origem.
"""
from __future__ import annotations

from sqlalchemy import text
from ..config import settings
from ..db import app_engine
from .elo_service import normalize_name


def load_mappings(competition_id: int) -> dict[str, str]:
    with app_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT nome_normalizado, nome_padrao
            FROM {settings.app_schema}.clubes_conciliacao
            WHERE campeonato_id=:competition_id
        """), {'competition_id': competition_id}).mappings()
        return {row['nome_normalizado']: row['nome_padrao'] for row in rows}


def save_mapping(competition_id: int, historico_jogos: str,
                 historico_odds: str, nome_padrao: str) -> dict:
    names = [historico_jogos.strip(), historico_odds.strip(), nome_padrao.strip()]
    if any(not x or len(x) > 180 or not normalize_name(x) for x in names):
        raise ValueError('Informe nomes válidos de até 180 caracteres.')
    key_standard = normalize_name(names[2])
    # Canonizar as grafias consultadas e também o nome de exibição escolhido.
    uniques = {normalize_name(name): name for name in names}
    schema = settings.app_schema
    with app_engine.begin() as conn:
        # Serialize por competição; protege validação+inserção contra concorrência.
        comp = conn.execute(text(f"SELECT id FROM {schema}.campeonatos WHERE id=:id FOR UPDATE"),
                            {'id': competition_id}).scalar()
        if comp is None:
            raise ValueError('Campeonato não encontrado.')
        existing = [dict(r) for r in conn.execute(text(f"""
            SELECT nome_normalizado, nome_padrao FROM {schema}.clubes_conciliacao
            WHERE campeonato_id=:id AND nome_normalizado = ANY(:keys)
        """), {'id':competition_id,'keys':list(uniques)}).mappings()]
        conflicts = [r for r in existing if normalize_name(r['nome_padrao']) != key_standard]
        if conflicts:
            raise ValueError('Um desses nomes já foi conciliado para outro clube. Revise a conciliação existente antes de alterar.')
        for key, raw in uniques.items():
            conn.execute(text(f"""
                INSERT INTO {schema}.clubes_conciliacao
                    (campeonato_id, nome_original, nome_normalizado, nome_padrao)
                VALUES (:id,:raw,:key,:standard)
                ON CONFLICT (campeonato_id,nome_normalizado)
                DO UPDATE SET nome_padrao=EXCLUDED.nome_padrao, atualizado_em=NOW()
            """), {'id':competition_id,'raw':raw,'key':key,'standard':names[2]})
        # Escolha da grafia padrão atualiza todas as grafias já vinculadas a ela.
        conn.execute(text(f"""
            UPDATE {schema}.clubes_conciliacao SET nome_padrao=:standard, atualizado_em=NOW()
            WHERE campeonato_id=:id AND nome_padrao IN (:jogos,:odds)
        """), {'id':competition_id,'standard':names[2], 'jogos':names[0], 'odds':names[1]})
    return {'historico_jogos':names[0], 'historico_odds':names[1], 'nome_padrao':names[2]}
