"""Conciliação de jogos e clubes entre `jogos`, `odds` e `historico_odds` (+ resultados de `historico_jogos`).

Prioridade das fontes: jogos (SofaScore) > odds > historico_odds. Um mesmo jogo é identificado por
data + país + nome padrão do mandante + nome padrão do visitante. Nomes diferentes entre fontes só são
unidos depois que o usuário confirma o vínculo (tabela `bet_vinculos`); o motor apenas sugere.
"""
from __future__ import annotations

import pickle
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..db import app_engine, history_connection

S = settings.app_schema
PRIORITY = {'jogos': 0, 'odds': 1, 'historico_odds': 2, 'api': 3}
ODDS_ORDER = ('odds', 'historico_odds', 'api')
PAIS_ALIAS = {'england': 'Inglaterra'}
HO_FILE = Path(__file__).resolve().parents[2] / '.cache' / 'ho_rows.pkl'
HO_FROM = date(2023, 12, 1)
CACHE_HOURS = 6
HO_ODDS = {'odd_casa': 'odd_casa_ft', 'odd_empate': 'odd_empate_ft', 'odd_fora': 'odd_fora_ft',
           'over_0_5': 'over_0_5_ft', 'under_0_5': 'under_0_5_ft', 'over_1_5': 'over_1_5_ft', 'under_1_5': 'under_1_5_ft',
           'over_2_5': 'over_2_5_ft', 'under_2_5': 'under_2_5_ft', 'over_3_5': 'over_3_5_ft', 'under_3_5': 'under_3_5_ft',
           'over_4_5': 'over_4_5_ft', 'under_4_5': 'under_4_5_ft', 'ambos_marcam_sim': 'ambos_marcam_sim',
           'ambos_marcam_nao': 'ambos_marcam_nao'}

_lock = threading.RLock()
_version = 0
_links_cache: dict = {}
_merged_cache: dict = {}


def norm(value) -> str:
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', s)


def pais_of(value):
    return PAIS_ALIAS.get((value or '').strip().lower(), (value or '').strip())


# ----------------------------------------------------------------------------------------
# Vínculos salvos
# ----------------------------------------------------------------------------------------
_ready = False


def ensure():
    global _ready
    if _ready:
        return
    with app_engine.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS {S}'))
        c.execute(text(f'''CREATE TABLE IF NOT EXISTS {S}.bet_vinculos (
            id BIGSERIAL PRIMARY KEY, pais TEXT NOT NULL, fonte TEXT NOT NULL, nome_fonte TEXT NOT NULL,
            nome_padrao TEXT, status TEXT NOT NULL DEFAULT 'vinculado',
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (pais, fonte, nome_fonte))'''))
    _ready = True


def links():
    """{(pais, fonte, norm(nome_fonte)): {'padrao': str|None, 'status': str, 'nome_fonte': str}}"""
    ensure()
    with _lock:
        if _links_cache.get('v') == _version:
            return _links_cache['data']
    with app_engine.connect() as c:
        rows = c.execute(text(f'SELECT pais, fonte, nome_fonte, nome_padrao, status FROM {S}.bet_vinculos')).mappings().all()
    data = {(pais_of(r['pais']), r['fonte'], norm(r['nome_fonte'])): {'padrao': r['nome_padrao'], 'status': r['status'],
                                                                      'nome_fonte': r['nome_fonte']} for r in rows}
    with _lock:
        _links_cache.update(v=_version, data=data)
    return data


def invalidate():
    global _version
    with _lock:
        _version += 1
        _merged_cache.clear()


def save_link(pais, fonte, nome_fonte, nome_padrao, status='vinculado'):
    ensure()
    if fonte not in PRIORITY:
        raise ValueError('Fonte inválida.')
    nome_fonte = (nome_fonte or '').strip()
    nome_padrao = (nome_padrao or '').strip() or None
    if not nome_fonte:
        raise ValueError('Informe o nome do clube na fonte.')
    if status == 'vinculado' and not nome_padrao:
        raise ValueError('Informe o nome padrão do clube.')
    with app_engine.begin() as c:
        c.execute(text(f'''INSERT INTO {S}.bet_vinculos (pais, fonte, nome_fonte, nome_padrao, status)
                           VALUES (:p, :f, :n, :d, :s)
                           ON CONFLICT (pais, fonte, nome_fonte) DO UPDATE SET nome_padrao=:d, status=:s'''),
                  {'p': pais_of(pais), 'f': fonte, 'n': nome_fonte, 'd': nome_padrao, 's': status})
    invalidate()


def delete_link(pais, fonte, nome_fonte):
    ensure()
    with app_engine.begin() as c:
        n = c.execute(text(f'DELETE FROM {S}.bet_vinculos WHERE pais=:p AND fonte=:f AND nome_fonte=:n'),
                      {'p': pais_of(pais), 'f': fonte, 'n': nome_fonte}).rowcount
    invalidate()
    return bool(n)


def std_name(pais, fonte, name):
    """Nome padrão do clube (vínculo confirmado ou o próprio nome)."""
    link = links().get((pais_of(pais), fonte, norm(name)))
    if link and link['status'] == 'vinculado' and link['padrao']:
        return link['padrao']
    return name


# ----------------------------------------------------------------------------------------
# Fonte historico_odds (+ resultado em historico_jogos)
# ----------------------------------------------------------------------------------------
def _ho_rows():
    try:
        if HO_FILE.exists() and time.time() - HO_FILE.stat().st_mtime < CACHE_HOURS * 3600:
            return pickle.loads(HO_FILE.read_bytes())
    except Exception:
        pass
    cols = ', '.join(f'ho.{c}' for c in HO_ODDS)
    rows, last = [], 0
    while True:
        for attempt in range(4):
            try:
                with history_connection() as conn:
                    chunk = [dict(r) for r in conn.execute(text(f'''
                        SELECT ho.id, ho.data, ho.pais, ho.campeonato, ho.formato, ho.temporada, ho.casa, ho.fora, {cols},
                               hj.gols_casa AS gh, hj.gols_fora AS ga
                        FROM public.historico_odds ho
                        LEFT JOIN public.historico_jogos hj ON hj.data = ho.data AND hj.casa = ho.casa AND hj.fora = ho.fora
                        WHERE ho.id > :last AND ho.data >= :start ORDER BY ho.id LIMIT 4000'''),
                        {'last': last, 'start': HO_FROM}).mappings()]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1]['id']
    try:
        HO_FILE.parent.mkdir(exist_ok=True)
        HO_FILE.write_bytes(pickle.dumps(rows))
    except Exception:
        pass
    return rows


def refresh_cache_files():
    try:
        HO_FILE.unlink()
    except FileNotFoundError:
        pass
    invalidate()


def ho_games():
    out = []
    for r in _ho_rows():
        g = {'fonte': 'historico_odds', 'id': r['id'], 'jogo_id': f"h{r['id']}", 'data': r['data'], 'pais': pais_of(r['pais']),
             'campeonato': r['campeonato'], 'temporada': r['temporada'], 'formato': r['formato'] or 'Liga', 'rodada': None,
             'casa': r['casa'], 'fora': r['fora'], 'gh': r['gh'], 'ga': r['ga'], 'goals': [], 'goal_minutes': []}
        g['timeline_ok'] = r['gh'] == 0 and r['ga'] == 0
        for src, dst in HO_ODDS.items():
            if r.get(src) is not None:
                g[dst] = float(r[src])
        out.append(g)
    return out


# ----------------------------------------------------------------------------------------
# União dos jogos
# ----------------------------------------------------------------------------------------
def _key(g, fonte):
    pais = pais_of(g['pais'])
    return (g['data'], pais, norm(std_name(pais, fonte, g['casa'])), norm(std_name(pais, fonte, g['fora'])))


def _source_of(g):
    if g.get('fonte') == 'jogos':
        return 'jogos'
    if g.get('fonte') == 'historico_odds':
        return 'historico_odds'
    return 'odds'


def merge(jogos_games, odds_games, ho_list, api_list=()):
    """Lista final de jogos (um por partida) com odds reais quando alguma fonte as possui."""
    groups: dict = {}
    order = []
    for fonte, lst in (('jogos', jogos_games), ('odds', odds_games), ('historico_odds', ho_list), ('api', api_list)):
        for g in lst:
            k = _key(g, fonte)
            if k not in groups:
                groups[k] = {}
                order.append(k)
            groups[k].setdefault(fonte, g)
    # nomes de campeonato diferentes entre fontes: aprende o equivalente a partir dos jogos já unidos
    votes: dict = defaultdict(Counter)
    for k in order:
        grp = groups[k]
        if len(grp) < 2:
            continue
        best = min(grp, key=lambda f: PRIORITY[f])
        for f, o in grp.items():
            if f != best and o.get('campeonato') and grp[best].get('campeonato'):
                votes[(pais_of(o['pais']), f, norm(o['campeonato']))][grp[best]['campeonato']] += 1
    comp_alias = {key: cnt.most_common(1)[0][0] for key, cnt in votes.items()}
    merged = []
    for k in order:
        grp = groups[k]
        base_src = min(grp, key=lambda f: PRIORITY[f])
        g = dict(grp[base_src])
        pais = pais_of(g['pais'])
        g['pais'] = pais
        g['campeonato'] = comp_alias.get((pais, base_src, norm(g.get('campeonato'))), g.get('campeonato'))
        g['fontes'] = sorted(grp, key=lambda f: PRIORITY[f])
        g['ids'] = [x['jogo_id'] for x in grp.values()]
        # odds reais: prioridade odds > historico_odds > api; colunas que faltam são completadas pelas demais fontes
        g['odds_fonte'] = None
        for f in ODDS_ORDER:
            o = grp.get(f)
            if o is None:
                continue
            first = g['odds_fonte'] is None
            if first:
                g['odds_fonte'] = f
            for col, val in o.items():
                if col.startswith(('odd_', 'over_', 'under_', 'correct_score_', 'dupla_', 'ambos_')) and val is not None:
                    if first or col not in g:
                        g[col] = val
        g['fontes_odds'] = [f for f in ODDS_ORDER if f in grp]
        # resultado e minutos dos gols: melhor fonte disponível
        if g.get('gh') is None:
            for f in ('odds', 'api', 'historico_odds'):
                o = grp.get(f)
                if o and o.get('gh') is not None:
                    g['gh'], g['ga'] = o['gh'], o['ga']
                    break
        if not g.get('timeline_ok'):
            for f in ('odds', 'api', 'jogos'):
                o = grp.get(f)
                if o and o.get('timeline_ok') and o.get('gh') == g.get('gh') and o.get('ga') == g.get('ga'):
                    g['timeline_ok'], g['goals'], g['goal_minutes'] = True, o['goals'], o['goal_minutes']
                    break
        if g.get('gh') is not None and g.get('ga') == 0 and g['gh'] == 0:
            g['timeline_ok'] = True
        for f in ('odds', 'api', 'jogos'):   # formato/rodada: mantém o que a fonte principal tiver
            o = grp.get(f)
            if o:
                if not g.get('rodada') or g.get('rodada') == '-':
                    g['rodada'] = o.get('rodada')
                for feat in o:
                    if feat.startswith(('home_', 'away_')) and feat not in g:
                        g[feat] = o[feat]
        g['casa'] = std_name(pais, base_src, grp[base_src]['casa'])
        g['fora'] = std_name(pais, base_src, grp[base_src]['fora'])
        g['casa_original'], g['fora_original'] = grp[base_src]['casa'], grp[base_src]['fora']
        merged.append(g)
    merged.sort(key=lambda g: (g['data'], str(g['jogo_id'])))
    return merged


# ----------------------------------------------------------------------------------------
# Sugestões (a "conciliação bancária")
# ----------------------------------------------------------------------------------------
def _tokens(name):
    return {t for t in re.split(r'[^a-z0-9]+', unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().lower()) if len(t) > 1}


def similarity(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    best = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and ta & tb:
        best = max(best, 0.85 * len(ta & tb) / min(len(ta), len(tb)))
    if len(na) >= 4 and len(nb) >= 4 and (na.startswith(nb) or nb.startswith(na)):
        best = max(best, 0.88)
    return best


def suggestions(jogos_games, odds_games, ho_list, api_list=()):
    """Pares de clubes cuja grafia difere entre fontes, com evidência (jogos da mesma data/país sem par exato)."""
    groups: dict = {}
    for fonte, lst in (('jogos', jogos_games), ('odds', odds_games), ('historico_odds', ho_list), ('api', api_list)):
        for g in lst:
            groups.setdefault(_key(g, fonte), {}).setdefault(fonte, g)
    singles = defaultdict(list)          # (data, pais) -> [(fonte, jogo)]
    for grp in groups.values():
        if len(grp) == 1:
            fonte, g = next(iter(grp.items()))
            singles[(g['data'], pais_of(g['pais']))].append((fonte, g))
    agg: dict = {}
    saved = links()

    def add(pais, src_fonte, src_name, target_name, partial, pair, other_fonte):
        k = (pais, src_fonte, src_name)
        e = agg.setdefault(k, {'cands': Counter(), 'partial': Counter(), 'exemplos': [], 'ref': {}})
        e['cands'][target_name] += 1
        e['partial'][target_name] += int(partial)
        e['ref'][target_name] = other_fonte
        if len(e['exemplos']) < 4:
            e['exemplos'].append({'data': pair[0]['data'].isoformat(),
                                  'jogo_fonte': f"{pair[0]['casa']} x {pair[0]['fora']}",
                                  'jogo_outra': f"{pair[1]['casa']} x {pair[1]['fora']}", 'fonte_outra': other_fonte})

    for (d, pais), items in singles.items():
        for i, (fa, ga) in enumerate(items):
            for fb, gb in items[i + 1:]:
                if fa == fb:
                    continue
                lo, hi = sorted([(fa, ga), (fb, gb)], key=lambda t: PRIORITY[t[0]])   # lo = fonte de maior prioridade
                (flo, glo), (fhi, ghi) = lo, hi
                hs = similarity(glo['casa'], ghi['casa']); as_ = similarity(glo['fora'], ghi['fora'])
                ident_h = norm(std_name(pais, flo, glo['casa'])) == norm(std_name(pais, fhi, ghi['casa']))
                ident_a = norm(std_name(pais, flo, glo['fora'])) == norm(std_name(pais, fhi, ghi['fora']))
                partial = ident_h or ident_a
                same_comp = norm(glo.get('campeonato')) == norm(ghi.get('campeonato'))
                if not (partial or (hs >= 0.45 and as_ >= 0.45 and hs + as_ >= 1.2) or (same_comp and hs + as_ >= 0.9)):
                    continue
                if not ident_h:
                    add(pais, fhi, ghi['casa'], std_name(pais, flo, glo['casa']), partial, (glo, ghi), flo)
                if not ident_a:
                    add(pais, fhi, ghi['fora'], std_name(pais, flo, glo['fora']), partial, (glo, ghi), flo)
    out = []
    for (pais, fonte, name), e in agg.items():
        if norm(name) in {norm(c) for c in e['cands']} and len(e['cands']) == 1:
            continue
        if (pais, fonte, norm(name)) in saved:
            continue
        cands = []
        for target, n in e['cands'].most_common(4):
            if norm(target) == norm(name):
                continue
            conf = 'alta' if e['partial'][target] >= 1 or n >= 3 else 'media' if similarity(name, target) >= 0.6 else 'baixa'
            cands.append({'padrao': target, 'evidencia': n, 'parcial': e['partial'][target], 'confianca': conf,
                          'fonte_referencia': e['ref'][target], 'similaridade': round(similarity(name, target), 2)})
        if cands:
            out.append({'pais': pais, 'fonte': fonte, 'nome_fonte': name, 'candidatos': cands, 'exemplos': e['exemplos'],
                        'confianca': cands[0]['confianca']})
    rank = {'alta': 0, 'media': 1, 'baixa': 2}
    out.sort(key=lambda s: (rank[s['confianca']], -s['candidatos'][0]['evidencia'], s['pais'], s['nome_fonte']))
    return out


def coverage(merged):
    total = [g for g in merged if 'jogos' in g['fontes']]
    with_odds = [g for g in total if g.get('odds_fonte')]
    by = Counter(g['odds_fonte'] for g in with_odds)
    return {'jogos_total': len(total), 'com_odds_reais': len(with_odds), 'sem_odds': len(total) - len(with_odds),
            'por_fonte': dict(by), 'jogos_unicos': len(merged)}
