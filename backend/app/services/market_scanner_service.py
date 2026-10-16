"""Scanner: apenas odds reais em public.odds; nunca combina cotações inexistentes.

A seleção exploratória usa intervalos de odds fixos e exige evidência nas
partições cronológicas de 70% e 30%. Não é validação fora da amostra genuína.
"""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
from datetime import date
import re
import time
from sqlalchemy import text
from ..db import app_engine, history_engine
from .continent_service import for_country, CONTINENTS

TABLE='public.odds'
GROUPS={
    'mo_ft': ('Match Odds FT', [('odd_casa_ft','Casa FT','home_ft'),('odd_empate_ft','Empate FT','draw_ft'),('odd_fora_ft','Fora FT','away_ft')]),
    'mo_ht': ('Match Odds HT', [('odd_casa_ht','Casa HT','home_ht'),('odd_empate_ht','Empate HT','draw_ht'),('odd_fora_ht','Fora HT','away_ht')]),
    'over_ht': ('Over HT',[(f'over_{t}_ht',f'Over {t.replace("_",",")} HT',f'over_{t}_ht') for t in ('0_5','1_5','2_5')]),
    'under_ht': ('Under HT',[(f'under_{t}_ht',f'Under {t.replace("_",",")} HT',f'under_{t}_ht') for t in ('0_5','1_5','2_5')]),
    'over_ft': ('Over FT',[(f'over_{t}_ft',f'Over {t.replace("_",",")} FT',f'over_{t}_ft') for t in ('0_5','1_5','2_5','3_5','4_5')]),
    'under_ft': ('Under FT',[(f'under_{t}_ft',f'Under {t.replace("_",",")} FT',f'under_{t}_ft') for t in ('0_5','1_5','2_5','3_5','4_5')]),
    'btts': ('Ambos Marcam', [('ambos_marcam_sim','Sim','btts_yes'),('ambos_marcam_nao','Não','btts_no')]),
    'double_chance': ('Dupla Chance',[('dupla_chance_1x','1X','dc_1x'),('dupla_chance_12','12','dc_12'),('dupla_chance_x2','X2','dc_x2')]),
    'correct_score': ('Placar Exato',[(f'correct_score_{h}_{a}',f'{h} × {a}',f'cs_{h}_{a}') for h in range(4) for a in range(4)]),
}
CUTS=(1.01,1.30,1.50,1.80,2.00,2.40,3.00,4.00,5.00,8.00,12.00,20.00,1000.01)
LIMIT=80_000


@lru_cache(maxsize=4)
def _engine_columns(bucket):
    for engine in (app_engine,history_engine):
        try:
            with engine.connect() as conn:
                cols={r[0] for r in conn.execute(text('''SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='odds' ''')).all()}
            if {'data','pais','campeonato','gols_casa','gols_fora'}.issubset(cols):
                return engine,cols
        except Exception:
            continue
    raise ValueError('Tabela public.odds não encontrada ou sem colunas obrigatórias. Confira a conexão do banco.')


def _source():return _engine_columns(int(time.time()//300))


def _normalize_filter_rows(rows: list[dict]) -> list[dict]:
    """Concilia dimensões da tabela odds sem assumir coluna continente."""
    unique = set()
    for row in rows:
        country = str(row.get('pais') or '').strip()
        league = str(row.get('campeonato') or '').strip()
        if not country or not league:
            continue
        continent = for_country(country, row.get('continente'))
        unique.add((continent, country, league,
                    str(row.get('divisao') or '').strip(),
                    str(row.get('formato') or '').strip()))
    return [dict(zip(('continent','country','competition','division','format'), entry))
            for entry in sorted(unique, key=lambda r: tuple(x.casefold() for x in r))]


@lru_cache(maxsize=2)
def _filter_options_cached(bucket: int) -> dict:
    engine, cols = _source()
    column = lambda name: (f"NULLIF(BTRIM({name}::text), '')" if name in cols else 'NULL::text')
    # SELECT DISTINCT no próprio PostgreSQL. Nunca transfere todos os jogos ao frontend.
    sql = text(f"""SELECT DISTINCT {column('pais')} AS pais,
                              {column('campeonato')} AS campeonato,
                              {column('divisao')} AS divisao,
                              {column('formato')} AS formato,
                              {column('continente')} AS continente
                   FROM {TABLE}
                   WHERE pais IS NOT NULL AND campeonato IS NOT NULL""")
    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(sql).mappings()]
    combos = _normalize_filter_rows(rows)
    return {
        'combinations': combos,
        'continents': [value for value in CONTINENTS if any(c['continent'] == value for c in combos)],
        'countries': sorted({c['country'] for c in combos}, key=str.casefold),
        'competitions': sorted({c['competition'] for c in combos}, key=str.casefold),
        'divisions': sorted({c['division'] for c in combos if c['division']}, key=str.casefold),
        'formats': sorted({c['format'] for c in combos if c['format']}, key=str.casefold),
        'source': TABLE,
    }


def filter_options() -> dict:
    """Uma busca de opções a cada cinco minutos, independentemente de navegação."""
    return _filter_options_cached(int(time.time() // 300))


def _continent_countries(continent: str, options: dict) -> list[str]:
    if continent not in CONTINENTS:
        raise ValueError('Continente inválido.')
    return sorted({c['country'] for c in options['combinations'] if c['continent'] == continent})



def catalog():
    _,cols=_source()
    groups=[]
    for key,(label, markets) in GROUPS.items():
        available=[{'key':field,'label':title} for field,title, event in markets if field in cols]
        if available:groups.append({'key':key,'label':label,'markets':available})
    return {'groups':groups,'source':'public.odds'}


def _market_event(event, gh, ga, ht):
    if event.endswith('_ht') or event in ('home_ht','away_ht','draw_ht'):
        if ht is None:return None
        h,a=ht
    else:h,a=gh,ga
    if event.startswith('cs_'):
        _,sh,sa=event.split('_');return h==int(sh) and a==int(sa)
    if event.startswith('over_'):
        part=event.split('_');threshold=int(part[1])+0.5
        return h+a>threshold
    if event.startswith('under_'):
        part=event.split('_');threshold=int(part[1])+0.5
        return h+a<threshold
    return {
        'home_ft':h>a,'draw_ft':h==a,'away_ft':a>h,
        'home_ht':h>a,'draw_ht':h==a,'away_ht':a>h,
        'btts_yes':h>0 and a>0,'btts_no':h==0 or a==0,
        'dc_1x':h>=a,'dc_12':h!=a,'dc_x2':a>=h,
    }.get(event)


def _ht_minutes(raw,ft_goals):
    if raw is None or str(raw).strip() in ('','None','null'):
        return 0 if ft_goals==0 else None
    # Minutos são horários de gol, p.ex. '[12, 44, 45+3, 90+1]'.
    times=re.findall(r'(?<!\d)(\d{1,3})(?:\s*\+\s*(\d{1,2}))?(?!\d)',str(raw))
    if not times:return None
    count=0
    for minute,extra in times:
        m=int(minute)
        if m<45 or m==45:count+=1  # 45+2 ainda pertence ao primeiro tempo.
    return count


def half_score(row):
    h=_ht_minutes(row.get('minutos_gols_casa'),int(row['gols_casa']))
    a=_ht_minutes(row.get('minutos_gols_fora'),int(row['gols_fora']))
    if h is None or a is None:return None
    if h>int(row['gols_casa']) or a>int(row['gols_fora']):return None
    return h,a


def _streaks(entries):
    good=bad=current_good=current_bad=0
    for e in entries:
        if e['green']:
            current_good+=1;current_bad=0;good=max(good,current_good)
        else:
            current_bad+=1;current_good=0;bad=max(bad,current_bad)
    return {'good_run':good,'bad_run':bad}


def _metrics(entries):
    count=len(entries);good=sum(e['green'] for e in entries)
    profit=sum((e['odd']-1)*100 if e['green'] else -100 for e in entries)
    return {'games':count,'green':good,'red':count-good,'win_rate':round(good/count*100,2) if count else None,
            'profit':round(profit,2),'roi':round(profit/count,2) if count else None,
            **_streaks(entries)}


def _bands(entries):
    bins=defaultdict(list)
    for row in entries:
        for i in range(len(CUTS)-1):
            if CUTS[i] <= row['odd'] < CUTS[i+1]:
                bins[i].append(row);break
    result=[]
    for start in range(len(CUTS)-1):
        for end in range(start,min(start+4,len(CUTS)-1)):
            subset=sorted([e for idx in range(start,end+1) for e in bins[idx]],key=lambda r:(r['date'],r['game_id']))
            if len(subset)<40:continue
            split=int(len(subset)*.7)
            train,valid=subset[:split],subset[split:]
            if len(train)<28 or len(valid)<12:continue
            first,second=_metrics(train),_metrics(valid)
            if first['roi'] <= 0 or second['roi'] <= 0:continue
            total=_metrics(subset)
            result.append({'low':CUTS[start],'high':CUTS[end+1],
                           'training':first,'validation':second,'total':total})
    result.sort(key=lambda x:(min(x['training']['roi'],x['validation']['roi']),x['total']['games']),reverse=True)
    return result[:5]


def analyze(group,country=None,competition=None,year_from=None,year_to=None,
            continent=None,division=None,format=None):
    if group not in GROUPS:raise ValueError('Grupo de mercados desconhecido.')
    engine,cols=_source()
    fields=[(k,n,e) for k,n,e in GROUPS[group][1] if k in cols]
    if not fields:raise ValueError('Nenhuma coluna desse grupo existe em public.odds.')
    if year_from and year_to and year_from>year_to:raise ValueError('Ano inicial maior que o final.')
    if division and 'divisao' not in cols:
        raise ValueError('A tabela odds não possui a coluna divisao.')
    if format and 'formato' not in cols:
        raise ValueError('A tabela odds não possui a coluna formato.')
    querycols=['data','pais','campeonato','gols_casa','gols_fora']
    if 'jogo_id' in cols:querycols.append('jogo_id')
    if group in ('mo_ht','over_ht','under_ht'):
        querycols += [c for c in ('minutos_gols_casa','minutos_gols_fora') if c in cols]
    querycols += [k for k,_,_ in fields]
    where=['data IS NOT NULL','data <= CURRENT_DATE','gols_casa IS NOT NULL','gols_fora IS NOT NULL'];params={'limit':LIMIT+1}
    if continent:
        countries = _continent_countries(continent, filter_options())
        if country and country not in countries:
            raise ValueError('País não pertence ao continente selecionado.')
        # Sem países compatíveis, não busca odds de todos os países por acidente.
        where.append('pais = ANY(:continent_countries)')
        params['continent_countries'] = countries
    if country:where.append('pais=:country');params['country']=country
    if division:where.append('divisao::text=:division');params['division']=division
    if format:where.append('formato::text=:format');params['format']=format
    if competition:where.append('campeonato=:competition');params['competition']=competition
    if year_from:where.append('data >= CAST(:start AS DATE)');params['start']=f'{year_from}-01-01'
    if year_to:where.append('data < CAST(:end AS DATE)');params['end']=f'{year_to+1}-01-01'
    sql=text(f'''SELECT {','.join(querycols)} FROM {TABLE} WHERE {' AND '.join(where)}
                   ORDER BY data DESC, {('jogo_id' if 'jogo_id' in cols else 'casa, fora' if {'casa','fora'}.issubset(cols) else 'data')}
                   LIMIT :limit''')
    per={k:[] for k,_,_ in fields};scanned=0;seen=set();duplicates=0;truncated=False
    with engine.connect() as conn:
        for r in conn.execution_options(stream_results=True).execute(sql,params).mappings():
            scanned+=1
            if scanned>LIMIT:truncated=True;break
            game_id=str(r.get('jogo_id') or scanned)
            if 'jogo_id' in cols and game_id in seen:duplicates+=1;continue
            if 'jogo_id' in cols:seen.add(game_id)
            gh,ga=int(r['gols_casa']),int(r['gols_fora'])
            ht=half_score(r) if group in ('mo_ht','over_ht','under_ht') else None
            for key, label,event in fields:
                try:
                    odd=float(r[key])
                    if not 1.01<=odd<=1000:continue
                except (TypeError,ValueError):continue
                green=_market_event(event,gh,ga,ht)
                if green is None:continue
                per[key].append({'date':str(r['data']),'game_id':game_id,'odd':odd,'green':bool(green)})
    markets=[]
    for key,label,event in fields:
        entries=sorted(per[key],key=lambda item:(item['date'],item['game_id']))
        summary=_metrics(entries)
        p=summary['win_rate']/100 if summary['win_rate'] is not None else None
        markets.append({'key':key,'label':label,'metrics':summary,
                        'fair_odd':round(1/p,2) if p else None,
                        'best_ranges':_bands(entries),
                        'start':entries[0]['date'] if entries else None,
                        'end':entries[-1]['date'] if entries else None})
    return {'group':group,'group_label':GROUPS[group][0],'markets':markets,
            'scanned':scanned,'duplicates':duplicates,'truncated':truncated,
            'sample_note':'Faixas são exploratórias: ao menos 40 entradas e ROI positivo nos 70% iniciais e 30% posteriores. A escolha após examinar os dados não é validação independente. Odd de corte = 1 / Win Rate; não é preço garantidamente lucrativo.',
            'source':TABLE}
