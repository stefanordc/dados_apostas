"""Confere conexão e relacionamento, somente leitura. Execute em backend/.venv."""
from app.services import sofascore_match_service as service
from app.services import goal_timeline_service as timeline
from app.db import history_connection
from sqlalchemy import text
import time


def main():
    cols=service._schema(int(time.time()//300))
    print('[OK] Fontes encontradas em HISTORY_DATABASE_URL')
    print('  jogos:             ', len(cols['jogos']), 'colunas')
    print('  jogo_completo:     ', len(cols['jogo_completo']), 'colunas')
    available=[f for f in service.STATS_FIELDS if f in cols['jogo_completo']]
    print('  Estatisticas disponíveis:', ', '.join(available))
    with history_connection() as conn:
        result=conn.execute(text(f'''
            WITH amostra AS (
              SELECT id_jogo,id_mandante,id_visitante FROM {service.JOGOS}
              WHERE data < CURRENT_DATE AND gols_casa IS NOT NULL AND gols_fora IS NOT NULL
              ORDER BY data DESC LIMIT 200
            )
            SELECT count(*) AS jogos,
                count(sh.id_clube) AS mandantes_com_stats,
                count(sa.id_clube) AS visitantes_com_stats
            FROM amostra j
            LEFT JOIN {service.STATS} sh ON sh.id_jogo=j.id_jogo AND sh.id_clube=j.id_mandante
            LEFT JOIN {service.STATS} sa ON sa.id_jogo=j.id_jogo AND sa.id_clube=j.id_visitante
        ''')).mappings().one()
    print('  Amostra recente:', dict(result))
    if result['jogos'] and (not result['mandantes_com_stats'] or not result['visitantes_com_stats']):
        print('[AVISO] Estatísticas não conciliadas com os jogos recentes. Confira IDs e base configurada.')
    try:
        layout,warning=timeline._layout(int(time.time()//300))
        if warning:
            print('[AVISO] Linha do tempo:',warning)
        else:
            print('[OK] minutos_gols: colunas reconhecidas:',layout)
            with history_connection() as conn:
                audit=conn.execute(text(f"""
                    SELECT count(DISTINCT j.id_jogo) AS jogos_com_gols,
                           count(DISTINCT m."{layout['game']}") AS jogos_com_eventos
                    FROM (SELECT id_jogo FROM {service.JOGOS}
                          WHERE data<CURRENT_DATE AND (gols_casa+gols_fora)>0
                          ORDER BY data DESC LIMIT 200) j
                    LEFT JOIN {timeline.TABLE} m ON m."{layout['game']}"::text=j.id_jogo::text
                """)).mappings().one()
            print('  Cobertura minutos_gols (amostra de 200 jogos com gols):',dict(audit))
    except Exception as ex:
        print('[AVISO] Validação de minutos_gols não pôde ser concluída:',type(ex).__name__,str(ex)[:160])

if __name__ == '__main__':
    main()
