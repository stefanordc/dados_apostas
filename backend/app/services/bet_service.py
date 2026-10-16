"""BET Teste: métodos (bots), Nostradamus (simulação histórica) e Casa de Apostas (banca virtual)."""
from __future__ import annotations

import hashlib
import hmac
import json
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import median

from sqlalchemy import text

from ..config import settings
from ..db import app_engine
from . import bet_engine as eng

S = settings.app_schema
OPS = {'<': lambda a, b: a < b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b,
       '>=': lambda a, b: a >= b, '=': lambda a, b: abs(a - b) < 1e-9, '!=': lambda a, b: abs(a - b) >= 1e-9}
EXIT_MODES = {'never': 'Segurar até o fim do jogo', 'goal_any': 'Qualquer gol após a entrada',
              'goal_home': 'Gol do mandante', 'goal_away': 'Gol do visitante', 'minute': 'Em um minuto definido'}

DEFAULT_PASSWORD = '1313'
BANKROLL_START = 1000.0


# ----------------------------------------------------------------------------------------
# Persistência
# ----------------------------------------------------------------------------------------
_ready = False

DEFAULT_METHODS = [
    {'nome': 'Vovô da casa', 'definicao': {
        'market': 'match_odds', 'selection': 'away', 'side': 'lay',
        'entry': {'minute_from': 65, 'minute_to': 70, 'scores': ['1-0', '2-1']},
        'exit': {'mode': 'goal_away', 'minute': None, 'scores': []},
        'conditions': [{'field': 'odd_casa_ft', 'op': '<', 'value': 1.8}],
        'scope': {'formato': '', 'countries': [], 'competitions': [], 'date_from': None, 'date_to': None},
        'notes': 'Lay ao visitante entre 65 e 70 min com 1x0 ou 2x1 para o mandante; sai somente se o mandante tomar gol.'}},
    {'nome': 'Mandante do HT', 'definicao': {
        'market': 'correct_score', 'selection': '0-1', 'side': 'lay',
        'entry': {'minute_from': 0, 'minute_to': 0, 'scores': ['0-0']},
        'exit': {'mode': 'minute', 'minute': 60, 'scores': ['0-0', '0-1']},
        'conditions': [{'field': 'odd_casa_ft', 'op': '<', 'value': 1.8}],
        'scope': {'formato': '', 'countries': [], 'competitions': [], 'date_from': None, 'date_to': None},
        'notes': 'Lay ao 0x1 no minuto 0; sai aos 60 min se o placar estiver 0x0 ou 0x1.'}},
]


def ensure():
    global _ready
    if _ready:
        return
    with app_engine.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS {S}'))
        c.execute(text(f'''CREATE TABLE IF NOT EXISTS {S}.bet_metodos (
            id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, definicao JSONB NOT NULL,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW())'''))
        c.execute(text(f'''CREATE TABLE IF NOT EXISTS {S}.bet_config (
            id INT PRIMARY KEY DEFAULT 1, banca_inicial NUMERIC NOT NULL DEFAULT 1000,
            stake_fixa NUMERIC, stake_travada BOOLEAN NOT NULL DEFAULT FALSE,
            metodos_semeados BOOLEAN NOT NULL DEFAULT FALSE, data_limite DATE)'''))
        c.execute(text(f'ALTER TABLE {S}.bet_config ADD COLUMN IF NOT EXISTS senha_hash TEXT'))
        c.execute(text(f'INSERT INTO {S}.bet_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING'))
        c.execute(text(f'UPDATE {S}.bet_config SET senha_hash=:h WHERE id=1 AND senha_hash IS NULL'),
                  {'h': hashlib.sha256(DEFAULT_PASSWORD.encode()).hexdigest()})
        c.execute(text(f'''CREATE TABLE IF NOT EXISTS {S}.bet_apostas (
            id BIGSERIAL PRIMARY KEY, criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), data_limite DATE,
            jogo_id TEXT NOT NULL, data_jogo DATE NOT NULL, jogo TEXT NOT NULL, pais TEXT, campeonato TEXT,
            mercado TEXT NOT NULL, mercado_nome TEXT NOT NULL, selecao TEXT NOT NULL, selecao_nome TEXT NOT NULL,
            lado TEXT NOT NULL, odd NUMERIC NOT NULL, stake NUMERIC NOT NULL, minuto INT NOT NULL,
            placar_entrada TEXT NOT NULL, odd_origem TEXT NOT NULL, placar_final TEXT, resultado TEXT,
            lucro NUMERIC)'''))
        # Apostas abertas ficam com resultado/lucro nulos até o usuário finalizar.
        c.execute(text(f'ALTER TABLE {S}.bet_apostas ALTER COLUMN resultado DROP NOT NULL'))
        c.execute(text(f'ALTER TABLE {S}.bet_apostas ALTER COLUMN lucro DROP NOT NULL'))
        seeded = c.execute(text(f'SELECT metodos_semeados FROM {S}.bet_config WHERE id=1')).scalar()
        if not seeded:
            for m in DEFAULT_METHODS:
                c.execute(text(f'INSERT INTO {S}.bet_metodos (nome, definicao) VALUES (:n, CAST(:d AS JSONB))'),
                          {'n': m['nome'], 'd': json.dumps(m['definicao'])})
            c.execute(text(f'UPDATE {S}.bet_config SET metodos_semeados=TRUE WHERE id=1'))
    _ready = True


def _method_row(r):
    d = dict(r)
    d['definicao'] = d['definicao'] if isinstance(d['definicao'], dict) else json.loads(d['definicao'])
    for k in ('criado_em', 'atualizado_em'):
        d[k] = d[k].isoformat() if d.get(k) else None
    return d


def list_methods():
    ensure()
    with app_engine.connect() as c:
        return [_method_row(r) for r in c.execute(text(f'SELECT * FROM {S}.bet_metodos ORDER BY id')).mappings()]


def get_method(method_id):
    ensure()
    with app_engine.connect() as c:
        r = c.execute(text(f'SELECT * FROM {S}.bet_metodos WHERE id=:i'), {'i': method_id}).mappings().first()
    if not r:
        raise ValueError('Método não encontrado.')
    return _method_row(r)


def validate_definition(d: dict) -> dict:
    """Normaliza e valida a definição de um método; levanta ValueError com mensagem clara."""
    if not isinstance(d, dict):
        raise ValueError('Definição inválida.')
    market = d.get('market'); selection = d.get('selection'); side = d.get('side')
    if market not in eng.MARKETS:
        raise ValueError('Escolha um mercado válido.')
    if selection not in eng.MARKETS[market][2]:
        raise ValueError('Escolha uma seleção válida para o mercado.')
    if side not in ('back', 'lay'):
        raise ValueError('O tipo da entrada deve ser Back ou Lay.')
    entry = d.get('entry') or {}
    try:
        m1 = int(entry.get('minute_from', 0)); m2 = int(entry.get('minute_to', m1))
    except (TypeError, ValueError):
        raise ValueError('Minutos de entrada inválidos.')
    if not (0 <= m1 <= m2 <= 90):
        raise ValueError('Os minutos de entrada devem estar entre 0 e 90, com o início menor ou igual ao fim.')
    scores = [str(s).strip().replace('x', '-').replace('X', '-') for s in (entry.get('scores') or []) if str(s).strip()]
    for s in scores:
        parts = s.split('-')
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError(f'Placar de entrada inválido: {s}. Use o formato 1-0 (mandante-visitante).')
    ex = d.get('exit') or {}
    mode = ex.get('mode', 'never')
    if mode not in EXIT_MODES:
        raise ValueError('Tipo de saída inválido.')
    exit_minute = ex.get('minute')
    exit_scores = [str(s).strip().replace('x', '-').replace('X', '-') for s in (ex.get('scores') or []) if str(s).strip()]
    if mode == 'minute':
        try:
            exit_minute = int(exit_minute)
        except (TypeError, ValueError):
            raise ValueError('Informe o minuto da saída.')
        if not (1 <= exit_minute <= 90):
            raise ValueError('O minuto de saída deve estar entre 1 e 90.')
        if exit_minute <= m2 and not (m1 == m2 == 0):
            raise ValueError('O minuto de saída precisa ser posterior à janela de entrada.')
    conditions = []
    fields = {f['key'] for f in eng.condition_fields()}
    for cnd in d.get('conditions') or []:
        field = cnd.get('field'); op = cnd.get('op')
        if field not in fields:
            raise ValueError(f'Estatística desconhecida: {field}.')
        if op not in OPS:
            raise ValueError('Operador inválido.')
        item = {'field': field, 'op': op}
        if cnd.get('other_field'):
            if cnd['other_field'] not in fields:
                raise ValueError(f"Estatística desconhecida: {cnd['other_field']}.")
            item['other_field'] = cnd['other_field']
        else:
            try:
                item['value'] = float(cnd.get('value'))
            except (TypeError, ValueError):
                raise ValueError('Informe um valor numérico em cada condição.')
        conditions.append(item)
    sc = d.get('scope') or {}
    formato = sc.get('formato') or ''
    if formato not in ('', 'Liga', 'Copa'):
        raise ValueError('Formato deve ser Liga, Copa ou vazio (todos).')
    return {'market': market, 'selection': selection, 'side': side,
            'entry': {'minute_from': m1, 'minute_to': m2, 'scores': scores},
            'exit': {'mode': mode, 'minute': exit_minute if mode == 'minute' else None, 'scores': exit_scores},
            'conditions': conditions,
            'scope': {'formato': formato, 'countries': list(sc.get('countries') or []),
                      'competitions': list(sc.get('competitions') or []),
                      'date_from': sc.get('date_from') or None, 'date_to': sc.get('date_to') or None},
            'notes': str(d.get('notes') or '')[:500]}


def save_method(method_id, nome, definicao):
    ensure()
    nome = (nome or '').strip()
    if not nome:
        raise ValueError('Informe o nome do método.')
    d = validate_definition(definicao)
    with app_engine.begin() as c:
        if method_id:
            n = c.execute(text(f'''UPDATE {S}.bet_metodos SET nome=:n, definicao=CAST(:d AS JSONB), atualizado_em=NOW()
                                  WHERE id=:i'''), {'n': nome, 'd': json.dumps(d), 'i': method_id}).rowcount
            if not n:
                raise ValueError('Método não encontrado.')
            new_id = method_id
        else:
            new_id = c.execute(text(f'''INSERT INTO {S}.bet_metodos (nome, definicao) VALUES (:n, CAST(:d AS JSONB))
                                       RETURNING id'''), {'n': nome, 'd': json.dumps(d)}).scalar()
    return get_method(new_id)


def delete_method(method_id):
    ensure()
    with app_engine.begin() as c:
        return bool(c.execute(text(f'DELETE FROM {S}.bet_metodos WHERE id=:i'), {'i': method_id}).rowcount)


# ----------------------------------------------------------------------------------------
# Simulação (Nostradamus)
# ----------------------------------------------------------------------------------------
def _parse_score(s):
    h, a = s.split('-')
    return int(h), int(a)


def _cond_ok(g, c):
    left = g.get(c['field'])
    right = g.get(c['other_field']) if c.get('other_field') else c.get('value')
    if left is None or right is None:
        return False
    return OPS[c['op']](left, right)


def _in_scope(g, d, overrides):
    sc = d['scope']
    if g['gh'] is None or g['ga'] is None:
        return False
    formato = overrides.get('formato', sc.get('formato'))
    if formato and g.get('formato') != formato:
        return False
    if sc.get('countries') and g['pais'] not in sc['countries']:
        return False
    if sc.get('competitions') and g['campeonato'] not in sc['competitions']:
        return False
    df = overrides.get('date_from') or sc.get('date_from'); dt = overrides.get('date_to') or sc.get('date_to')
    if df and g['data'] < date.fromisoformat(str(df)):
        return False
    if dt and g['data'] > date.fromisoformat(str(dt)):
        return False
    return True


def _entry_point(g, entry):
    """Primeiro instante da janela em que o placar é um dos permitidos: (minuto, placar) ou None."""
    m1, m2 = entry['minute_from'], entry['minute_to']
    allowed = {_parse_score(s) for s in entry['scores']}
    candidates = [m1] + sorted({m for m in g['goal_minutes'] if m1 < m <= m2})
    for t in candidates:
        sc = eng.score_at(g, t)
        if not allowed or sc in allowed:
            return t, sc
    return None


def _exit_point(g, ex, t0, entry_score):
    """Ponto de saída após a entrada: (minuto, placar) ou None quando fica até o fim."""
    mode = ex['mode']
    if mode == 'never':
        return None
    later = [(m, s) for (m, s) in g['goals'] if m > t0]
    if mode in ('goal_any', 'goal_home', 'goal_away'):
        for m, side in later:
            if mode == 'goal_any' or (mode == 'goal_home' and side == 'h') or (mode == 'goal_away' and side == 'a'):
                return m, eng.score_at(g, m)
        return None
    minute = ex['minute']
    if minute <= t0:
        return None
    sc = eng.score_at(g, minute)
    allowed = {_parse_score(s) for s in ex['scores']}
    if allowed and sc not in allowed:
        return None
    return minute, sc


def simulate(definicao, stake=100.0, stake_mode='stake', commission=0.0, overrides=None):
    d = validate_definition(definicao)
    overrides = overrides or {}
    market, sel, side = d['market'], d['selection'], d['side']
    period = eng.MARKETS[market][1]
    needs_timeline = (d['entry']['minute_to'] > 0 or d['exit']['mode'] != 'never' or period == 'ht'
                      or any(s != '0-0' for s in d['entry']['scores']))
    rows = []
    stats = defaultdict(int)
    for g in eng.games():
        if not _in_scope(g, d, overrides):
            continue
        if not all(_cond_ok(g, c) for c in d['conditions']):
            stats['fora_das_condicoes'] += 1
            continue
        if needs_timeline and not g['timeline_ok']:
            stats['sem_linha_do_tempo'] += 1
            continue
        ep = _entry_point(g, d['entry'])
        if ep is None:
            stats['sem_entrada'] += 1
            continue
        t0, sc0 = ep
        q = eng.quote(g, market, sel, t0, sc0)
        if q is None:
            stats['sem_preco'] += 1
            continue
        odd = q[side]
        if odd <= 1.0:
            stats['sem_preco'] += 1
            continue
        s_amount = float(stake) / (odd - 1) if (side == 'lay' and stake_mode == 'liability') else float(stake)
        exposure = s_amount if side == 'back' else s_amount * (odd - 1)
        ex_pt = _exit_point(g, d['exit'], t0, sc0)
        exit_info = None
        if ex_pt:
            tx, scx = ex_pt
            qx = eng.quote(g, market, sel, tx, scx)
            if qx is not None:
                exit_odd = qx['back'] if side == 'lay' else qx['lay']
                pl = eng.pnl_open_close(side, s_amount, odd, exit_odd)
                if pl > 0 and commission:
                    pl *= (1 - commission)
                exit_info = {'minute': tx, 'score': f'{scx[0]}-{scx[1]}', 'odd': exit_odd}
        if exit_info is None:
            won = eng.settle_win(g, market, sel)
            if won is None:
                stats['sem_linha_do_tempo'] += 1
                continue
            pl = eng.pnl_settle(side, s_amount, odd, won, commission)
        rows.append({
            'id': g['jogo_id'], 'data': g['data'].isoformat(), 'jogo': f"{g['casa']} x {g['fora']}",
            'pais': g['pais'], 'campeonato': g['campeonato'], 'formato': g.get('formato'),
            'final': f"{g['gh']}-{g['ga']}", 'entrada_minuto': t0, 'entrada_placar': f'{sc0[0]}-{sc0[1]}',
            'entrada_odd': odd, 'odd_origem': q['source'], 'saida': exit_info,
            'stake': round(s_amount, 2), 'exposicao': round(exposure, 2), 'lucro': round(pl, 2),
            'resultado': 'green' if pl > 0.005 else 'red' if pl < -0.005 else 'zero',
            'odd_casa': g.get('odd_casa_ft'), 'odd_empate': g.get('odd_empate_ft'), 'odd_fora': g.get('odd_fora_ft'),
            '_g': g})
    return d, rows, dict(stats)


def _drawdown(rows):
    peak = acc = dd = 0.0
    for r in rows:
        acc += r['lucro']
        peak = max(peak, acc)
        dd = max(dd, peak - acc)
    return round(dd, 2)


def _runs(rows):
    """Maior sequência de greens (Good Run) e de reds (Bad Run), em ordem cronológica."""
    best = {'green': (0, 0.0, None, None), 'red': (0, 0.0, None, None)}
    cur_kind, cur_n, cur_pl, cur_start = None, 0, 0.0, None
    for r in rows:
        kind = 'green' if r['lucro'] > 0.005 else 'red' if r['lucro'] < -0.005 else None
        if kind != cur_kind:
            cur_kind, cur_n, cur_pl, cur_start = kind, 0, 0.0, r['data']
        if kind:
            cur_n += 1; cur_pl += r['lucro']
            if cur_n > best[kind][0]:
                best[kind] = (cur_n, round(cur_pl, 2), cur_start, r['data'])
    fmt = lambda t: {'jogos': t[0], 'lucro': t[1], 'inicio': t[2], 'fim': t[3]}
    return {'good_run': fmt(best['green']), 'bad_run': fmt(best['red'])}


def _summary(rows):
    n = len(rows)
    if not n:
        return {'jogos': 0}
    pl = sum(r['lucro'] for r in rows)
    greens = sum(r['resultado'] == 'green' for r in rows)
    exposure = sum(r['exposicao'] for r in rows)
    return {'jogos': n, 'greens': greens, 'reds': sum(r['resultado'] == 'red' for r in rows),
            'win_rate': round(100 * greens / n, 2), 'lucro': round(pl, 2),
            'roi_exposicao': round(100 * pl / exposure, 2) if exposure else None,
            'lucro_por_jogo': round(pl / n, 2), 'odd_media': round(sum(r['entrada_odd'] for r in rows) / n, 2),
            'saidas_antecipadas': sum(1 for r in rows if r['saida']),
            'entradas_estimadas': sum(1 for r in rows if r['odd_origem'] == 'estimada'),
            'drawdown_max': _drawdown(rows), 'exposicao_total': round(exposure, 2), **_runs(rows)}


def _curve(rows, points=300):
    acc, out = 0.0, []
    for r in rows:
        acc += r['lucro']
        out.append({'data': r['data'], 'acumulado': round(acc, 2)})
    if len(out) > points:
        step = len(out) / points
        out = [out[min(int(i * step), len(out) - 1)] for i in range(points)] + [out[-1]]
    return out


def _by_year(rows):
    years = defaultdict(list)
    for r in rows:
        years[r['data'][:4]].append(r)
    return [{'ano': y, **_summary(v)} for y, v in sorted(years.items())]


# ----------------------------------------------------------------------------------------
# Sugestões para lapidar o método
# ----------------------------------------------------------------------------------------
def _quantiles(values, qs):
    s = sorted(values)
    return sorted({s[min(int(q * (len(s) - 1)), len(s) - 1)] for q in qs})


def suggestions(rows, definicao):
    n = len(rows)
    if n < 40:
        return {'aviso': 'Poucos jogos para sugerir filtros com segurança (mínimo de 40).', 'itens': []}
    base_avg = sum(r['lucro'] for r in rows) / n
    half = n // 2
    labels = {f['key']: f['label'] for f in eng.condition_fields()}
    labels['entrada_odd'] = 'Odd de entrada'
    labels['entrada_minuto'] = 'Minuto da entrada'
    used = {c['field'] for c in definicao['conditions']}
    items = []
    keys = [f['key'] for f in eng.condition_fields()] + ['entrada_odd', 'entrada_minuto']
    min_n = max(30, int(n * 0.2))
    for key in keys:
        if key in used:
            continue
        vals = []
        for idx, r in enumerate(rows):
            v = r.get(key) if key in r else r['_g'].get(key)
            vals.append(v)
        present = [v for v in vals if v is not None]
        if len(present) < n * 0.8 or len(set(present)) < 4:
            continue
        for thr in _quantiles(present, [.1, .2, .3, .4, .5, .6, .7, .8, .9]):
            for op in ('<=', '>='):
                idxs = [i for i, v in enumerate(vals) if v is not None and (v <= thr if op == '<=' else v >= thr)]
                if len(idxs) < min_n or len(idxs) > n * 0.9:
                    continue
                pl = sum(rows[i]['lucro'] for i in idxs)
                avg = pl / len(idxs)
                gain = (avg - base_avg) * sqrt(len(idxs))
                if avg <= base_avg:
                    continue
                first = [rows[i]['lucro'] for i in idxs if i < half]; second = [rows[i]['lucro'] for i in idxs if i >= half]
                stable = bool(first and second and sum(first) / len(first) > base_avg and sum(second) / len(second) > base_avg)
                items.append({'campo': key, 'op': op, 'valor': round(thr, 2), 'jogos': len(idxs), 'lucro': round(pl, 2),
                              'lucro_por_jogo': round(avg, 2), 'estavel': stable, '_score': gain * (1.5 if stable else 1)})
    best, seen = [], set()
    for it in sorted(items, key=lambda x: -x['_score']):
        if it['campo'] in seen:
            continue
        seen.add(it['campo'])
        best.append(it)
        if len(best) == 6:
            break
    out = []
    for it in best:
        sign = '≤' if it['op'] == '<=' else '≥'
        out.append({'tipo': 'condicao', 'titulo': f"{labels.get(it['campo'], it['campo'])} {sign} {it['valor']}",
                    'descricao': (f"Mantém {it['jogos']} dos {n} jogos e o lucro médio por jogo passa de "
                                  f"R$ {base_avg:.2f} para R$ {it['lucro_por_jogo']:.2f}."
                                  + (' O ganho aparece nas duas metades do período.' if it['estavel']
                                     else ' Atenção: o ganho não se repete nas duas metades do período.')),
                    'jogos': it['jogos'], 'lucro': it['lucro'], 'lucro_por_jogo': it['lucro_por_jogo'],
                    'estavel': it['estavel'],
                    'condicao': {'field': it['campo'] if it['campo'] in {f['key'] for f in eng.condition_fields()} else None,
                                 'op': '<=' if it['op'] == '<=' else '>=', 'value': it['valor']}})
    # campeonatos / países que mais prejudicam
    for key, name in (('campeonato', 'Campeonato'), ('pais', 'País')):
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r['lucro'])
        bad = sorted(((k, len(v), sum(v)) for k, v in groups.items() if len(v) >= 25 and sum(v) < 0), key=lambda x: x[2])[:2]
        for k, cnt, pl in bad:
            rest = [r['lucro'] for r in rows if r[key] != k]
            out.append({'tipo': 'excluir', 'titulo': f'Excluir {name.lower()}: {k}',
                        'descricao': (f'{cnt} jogos com resultado de R$ {pl:.2f}. Sem eles o lucro por jogo passa de '
                                      f'R$ {base_avg:.2f} para R$ {sum(rest) / max(len(rest), 1):.2f}.'),
                        'jogos': cnt, 'lucro': round(pl, 2), 'lucro_por_jogo': round(pl / cnt, 2), 'estavel': None,
                        'condicao': None})
    aviso = ('Sugestões vêm do mesmo histórico testado e podem ser sorte (sobreajuste). Prefira as marcadas como '
             'estáveis e valide em outro período antes de usar dinheiro real.')
    return {'aviso': aviso, 'itens': out}


def nostradamus(method_id=None, definicao=None, stake=100.0, stake_mode='stake', commission=0.0, overrides=None):
    if method_id:
        m = get_method(method_id)
        definicao = m['definicao']; nome = m['nome']
    else:
        nome = 'Método sem nome'
    if stake <= 0:
        raise ValueError('A stake deve ser maior que zero.')
    if stake_mode not in ('stake', 'liability'):
        raise ValueError('Modo de stake inválido.')
    d, rows, stats = simulate(definicao, stake, stake_mode, commission, overrides)
    summary = _summary(rows)
    games_out = [{k: v for k, v in r.items() if k != '_g'} for r in rows]
    avisos = []
    if summary.get('entradas_estimadas'):
        avisos.append(f"{summary['entradas_estimadas']} entrada(s) usam odd ESTIMADA pelo modelo (a tabela só tem odds "
                      'iniciais reais). Saídas antecipadas também usam odds estimadas.')
    if stats.get('sem_linha_do_tempo'):
        avisos.append(f"{stats['sem_linha_do_tempo']} jogo(s) foram ignorados por não terem minutos dos gols completos.")
    return {'metodo': nome, 'definicao': d, 'resumo': summary, 'descartes': stats, 'avisos': avisos,
            'curva': _curve(rows), 'por_ano': _by_year(rows), 'sugestoes': suggestions(rows, d),
            'jogos': games_out, 'stake': stake, 'stake_mode': stake_mode}


# ----------------------------------------------------------------------------------------
# Casa de Apostas
# ----------------------------------------------------------------------------------------
def _card_odds(g, cutoff=None):
    if g.get('odd_casa_ft'):
        return {'casa': g.get('odd_casa_ft'), 'empate': g.get('odd_empate_ft'), 'fora': g.get('odd_fora_ft')}, False
    out = {}
    for k, sel in (('casa', 'home'), ('empate', 'draw'), ('fora', 'away')):
        q = eng.quote(g, 'match_odds', sel, 0, (0, 0), as_of=cutoff)
        out[k] = q['back'] if q else None
    return out, True


def _game_card(g, cutoff=None):
    card_odds, estimated = _card_odds(g, cutoff)
    return {'id': g['jogo_id'], 'data': g['data'].isoformat(), 'casa': g['casa'], 'fora': g['fora'],
            'pais': g['pais'], 'campeonato': g['campeonato'], 'formato': g.get('formato'),
            'rodada': g.get('rodada'), 'odds_reais': bool(g.get('odd_casa_ft')), 'odds_fonte': g.get('odds_fonte'),
            'linha_do_tempo': bool(g['timeline_ok']),
            'odds': card_odds, 'odds_estimadas': estimated}


def fixtures(cutoff: date, formato='Liga', window_days=14):
    """Próxima rodada de cada campeonato a partir de cutoff+1, agrupada por país."""
    start = cutoff + timedelta(days=1)
    by_comp = defaultdict(list)
    for g in eng.all_games():
        if g['data'] >= start and (formato in ('', 'Todos', None) or g.get('formato') == formato):
            by_comp[(g['pais'], g['campeonato'])].append(g)
    countries = defaultdict(list)
    for (pais, camp), lst in by_comp.items():
        lst.sort(key=lambda g: (g['data'], str(g['jogo_id'])))
        first = lst[0]
        if first['data'] > start + timedelta(days=window_days):
            continue   # sem jogo em tempo razoável: a base não cobre a próxima rodada deste campeonato
        round_name = first.get('rodada')
        limit = first['data'] + timedelta(days=7)
        taken, teams = [], set()
        for g in lst:
            if g['data'] > limit:
                break
            same_round = g.get('rodada') == round_name or not g.get('rodada') or not round_name or '-' in (g.get('rodada'), round_name)
            if not same_round or g['casa'] in teams or g['fora'] in teams:
                continue
            teams.update((g['casa'], g['fora']))
            taken.append(g)
        countries[pais].append({'campeonato': camp, 'formato': first.get('formato'),
                                'rodada': round_name, 'jogos': [_game_card(g, cutoff) for g in taken]})
    return [{'pais': p, 'campeonatos': sorted(v, key=lambda x: x['campeonato'])} for p, v in sorted(countries.items())]


def _need_game(jogo_id):
    g = eng.game_by_id(jogo_id)
    if not g:
        raise ValueError('Jogo não encontrado.')
    return g


def game_markets(jogo_id, minute: int, cutoff: date | None = None):
    g = _need_game(jogo_id)
    minute = max(0, min(int(minute), 90))
    if not g['timeline_ok'] and minute > 0:
        raise ValueError('Este jogo não tem minutos dos gols completos: só é possível operar no minuto 0.')
    score = eng.score_at(g, minute) if g['timeline_ok'] else (0, 0)
    prev_goal = max((m for m in g['goal_minutes'] if m <= minute), default=None)
    next_goal = min((m for m in g['goal_minutes'] if m > minute), default=None)
    markets = []
    any_estimated = False
    for mk in eng.BOOK_MARKETS:
        label, period, sels = eng.MARKETS[mk]
        wanted = eng.BOOK_SELECTIONS.get(mk) or list(sels)
        out = []
        for sk in wanted:
            q = eng.quote(g, mk, sk, minute, score, as_of=cutoff)
            if q and q['source'] == 'estimada':
                any_estimated = True
            lay = None if mk in getattr(eng, 'BOOK_BACK_ONLY', ()) else (q['lay'] if q else None)
            out.append({'key': sk, 'label': sels[sk][0], 'back': q['back'] if q else None,
                        'lay': lay, 'fonte': q['source'] if q else None})
        status = 'SUSPENSO' if all(o['back'] is None for o in out) else 'ABERTO'
        if period == 'ht' and minute >= 45:
            status = 'ENCERRADO'
        markets.append({'key': mk, 'label': label, 'status': status, 'selecoes': out,
                        'back_only': mk in getattr(eng, 'BOOK_BACK_ONLY', ())})
    lh, la, src, info = eng.fit_lambdas(g, cutoff)
    return {'jogo': _game_card(g, cutoff), 'minuto': minute, 'placar': f'{score[0]}-{score[1]}',
            'gol_anterior': prev_goal, 'proximo_gol': next_goal, 'mercados': markets,
            'odds_estimadas': any_estimated,
            'aviso_odds': ('Odds reais da tabela odds no minuto 0. Em outros minutos (ou mercados sem odd real, como '
                           'Goleada) as odds são ESTIMADAS pelo modelo a partir das odds iniciais e do placar.'
                           if g.get('odd_casa_ft') and g.get('odds_fonte') != 'historico_odds' else
                           'Odds reais da tabela historico_odds no minuto 0 (sem correct score nem odds de 1º tempo, estimados). '
                           'Em outros minutos as odds são ESTIMADAS pelo modelo a partir das odds iniciais e do placar.'
                           if g.get('odd_casa_ft') else
                           'Jogo sem odds cadastradas: todas as odds são ESTIMADAS pela força dos clubes (Elo desde 2012) e pela '
                           'média de gols do campeonato, usando apenas jogos até a data limite.'),
            'lay_aviso': 'As odds Lay são derivadas das odds Back (a tabela não tem Lay real).',
            'modelo': {'gols_esperados_casa': round(lh, 2), 'gols_esperados_fora': round(la, 2), 'base': src,
                       'detalhes': info}}


def _venue_summary(rows):
    n = len(rows)
    if not n:
        return {'jogos': 0}
    gf = sum(r['gf'] for r in rows); ga = sum(r['ga'] for r in rows)
    pct = lambda k: round(100 * k / n, 1)
    return {'jogos': n, 'vitorias': sum(r['gf'] > r['ga'] for r in rows), 'empates': sum(r['gf'] == r['ga'] for r in rows),
            'derrotas': sum(r['gf'] < r['ga'] for r in rows), 'gols_pro': round(gf / n, 2), 'gols_contra': round(ga / n, 2),
            'over05': pct(sum(r['gf'] + r['ga'] > 0 for r in rows)), 'over15': pct(sum(r['gf'] + r['ga'] > 1 for r in rows)),
            'over25': pct(sum(r['gf'] + r['ga'] > 2 for r in rows)), 'under35': pct(sum(r['gf'] + r['ga'] < 4 for r in rows)),
            'btts': pct(sum(r['gf'] > 0 and r['ga'] > 0 for r in rows)),
            'sem_sofrer': pct(sum(r['ga'] == 0 for r in rows)), 'sem_marcar': pct(sum(r['gf'] == 0 for r in rows)),
            'goleadas_pro': sum(r['gf'] >= 4 and r['gf'] > r['ga'] for r in rows),
            'goleadas_contra': sum(r['ga'] >= 4 and r['ga'] > r['gf'] for r in rows)}


def _team_aliases(team, current):
    """Nomes conhecidos do clube (padrão, original do jogo e vínculos confirmados)."""
    from . import bet_reconcile as recon
    aliases = {recon.norm(team)}
    if current.get('casa') == team and current.get('casa_original'):
        aliases.add(recon.norm(current['casa_original']))
    if current.get('fora') == team and current.get('fora_original'):
        aliases.add(recon.norm(current['fora_original']))
    team_n = recon.norm(team)
    for link in recon.links().values():
        if link.get('status') == 'vinculado' and link.get('padrao') and recon.norm(link['padrao']) == team_n:
            aliases.add(recon.norm(link['nome_fonte']))
            aliases.add(team_n)
    return aliases


def _side_names(g, home: bool):
    from . import bet_reconcile as recon
    if home:
        return {recon.norm(g['casa']), recon.norm(g.get('casa_original') or g['casa'])}
    return {recon.norm(g['fora']), recon.norm(g.get('fora_original') or g['fora'])}


def _team_block(team, cutoff, current):
    """Histórico do time: últimos 20 jogos em qualquer competição (sem filtrar país/campeonato)."""
    current_ids = {str(i) for i in current.get('ids', [current['jogo_id']])}
    aliases = _team_aliases(team, current)
    rows = []
    for g in eng.all_games():
        if g['data'] > cutoff or g['gh'] is None:
            continue
        g_ids = {str(i) for i in g.get('ids', [g['jogo_id']])}
        if current_ids & g_ids:
            continue
        if aliases & _side_names(g, True):
            rows.append({'data': g['data'], 'casa': True, 'gf': g['gh'], 'ga': g['ga'], 'g': g, 'opp': g['fora']})
        elif aliases & _side_names(g, False):
            rows.append({'data': g['data'], 'casa': False, 'gf': g['ga'], 'ga': g['gh'], 'g': g, 'opp': g['casa']})
    rows.sort(key=lambda r: (r['data'], r['opp']))
    recent = rows[-20:]
    scores = defaultdict(int)
    for r in recent:
        scores[f"{r['gf']}-{r['ga']}"] += 1
    top_scores = sorted(scores.items(), key=lambda kv: -kv[1])[:6]
    # primeiro tempo / quem abre o placar (só jogos com linha do tempo)
    tl = [r for r in recent if r['g']['timeline_ok']]
    first_half = total_goals = opened = open_win = 0
    for r in tl:
        mine = 'h' if r['casa'] else 'a'
        for m, side in r['g']['goals']:
            total_goals += 1
            if m <= 45:
                first_half += 1
        if r['g']['goals']:
            if r['g']['goals'][0][1] == mine:
                opened += 1
                open_win += r['gf'] > r['ga']
    return {'time': team,
            'geral': _venue_summary(recent),
            'casa': _venue_summary([r for r in recent if r['casa']]),
            'fora': _venue_summary([r for r in recent if not r['casa']]),
            'ultimos5': _venue_summary(recent[-5:]), 'ultimos10': _venue_summary(recent[-10:]),
            'forma': ''.join('V' if r['gf'] > r['ga'] else 'E' if r['gf'] == r['ga'] else 'D' for r in recent[-8:]),
            'placares_mais_comuns': [{'placar': k, 'jogos': v} for k, v in top_scores],
            'gols_1t_pct': round(100 * first_half / total_goals, 1) if total_goals else None,
            'abriu_placar_pct': round(100 * opened / len(tl), 1) if tl else None,
            'venceu_apos_abrir_pct': round(100 * open_win / opened, 1) if opened else None,
            'ultimos_jogos': [{'data': r['data'].isoformat(), 'adversario': r['opp'], 'mando': 'C' if r['casa'] else 'F',
                               'placar': f"{r['gf']}-{r['ga']}"} for r in reversed(recent[-8:])]}


def game_statistics(jogo_id, cutoff: date):
    g = _need_game(jogo_id)
    if g['data'] <= cutoff:
        raise ValueError('O jogo precisa ser posterior à data limite.')
    h2h = [{'data': x['data'].isoformat(), 'jogo': f"{x['casa']} x {x['fora']}", 'placar': f"{x['gh']}-{x['ga']}"}
           for x in eng.all_games() if x['data'] <= cutoff and x['gh'] is not None and
           {x['casa'], x['fora']} == {g['casa'], g['fora']}][-6:]
    odds = {k: g.get(k) for k in ('odd_casa_ft', 'odd_empate_ft', 'odd_fora_ft', 'over_2_5_ft', 'under_2_5_ft',
                                  'ambos_marcam_sim')}
    return {'cutoff': cutoff.isoformat(), 'jogo': _game_card(g), 'odds_iniciais': odds,
            'casa': _team_block(g['casa'], cutoff, g), 'fora': _team_block(g['fora'], cutoff, g),
            'confrontos_diretos': list(reversed(h2h)),
            'aviso': (f'Todas as estatísticas usam os últimos 20 jogos de cada time '
                      f'(qualquer competição) até {cutoff.strftime("%d/%m/%Y")}.')}


# ----------------------------------------------------------------------------------------
# Banca e apostas
# ----------------------------------------------------------------------------------------
def get_config():
    ensure()
    with app_engine.connect() as c:
        r = dict(c.execute(text(f'SELECT * FROM {S}.bet_config WHERE id=1')).mappings().one())
        pl = c.execute(text(f'SELECT COALESCE(SUM(lucro),0) FROM {S}.bet_apostas WHERE resultado IS NOT NULL')).scalar()
    return {'banca_inicial': float(r['banca_inicial']), 'banca_atual': round(float(r['banca_inicial']) + float(pl), 2),
            'stake_fixa': float(r['stake_fixa']) if r['stake_fixa'] is not None else None,
            'stake_travada': bool(r['stake_travada']),
            'data_limite': r['data_limite'].isoformat() if r['data_limite'] else None}


def _pending_exposure(conn=None):
    sql = text(f'''SELECT COALESCE(SUM(CASE WHEN lado='back' THEN stake ELSE stake*(odd-1) END),0)
                   FROM {S}.bet_apostas WHERE resultado IS NULL''')
    if conn is not None:
        return float(conn.execute(sql).scalar() or 0)
    with app_engine.connect() as c:
        return float(c.execute(sql).scalar() or 0)


def _bet_public(r: dict, *, reveal: bool):
    out = {k: r[k] for k in ('id', 'jogo_id', 'data_jogo', 'jogo', 'pais', 'campeonato', 'mercado', 'mercado_nome',
                             'selecao', 'selecao_nome', 'lado', 'odd', 'stake', 'minuto', 'placar_entrada', 'odd_origem')}
    out['odd'] = float(out['odd']); out['stake'] = float(out['stake'])
    out['data_jogo'] = out['data_jogo'].isoformat() if hasattr(out['data_jogo'], 'isoformat') else out['data_jogo']
    out['status'] = 'finalizada' if r.get('resultado') else 'pendente'
    out['exposicao'] = round(out['stake'] if out['lado'] == 'back' else out['stake'] * (out['odd'] - 1), 2)
    if reveal and r.get('resultado'):
        out['resultado'] = r['resultado']
        out['lucro'] = float(r['lucro']) if r.get('lucro') is not None else None
        out['placar_final'] = r.get('placar_final')
    else:
        out['resultado'] = None
        out['lucro'] = None
        out['placar_final'] = None
    return out


def update_config(payload: dict):
    ensure()
    sets, params = [], {}
    if 'stake_fixa' in payload:
        v = payload['stake_fixa']
        if v not in (None, ''):
            v = float(v)
            if v <= 0:
                raise ValueError('A stake fixa deve ser maior que zero.')
        else:
            v = None
        sets.append('stake_fixa=:sf'); params['sf'] = v
    if 'stake_travada' in payload:
        sets.append('stake_travada=:st'); params['st'] = bool(payload['stake_travada'])
    if 'data_limite' in payload:
        sets.append('data_limite=:dl'); params['dl'] = date.fromisoformat(payload['data_limite']) if payload['data_limite'] else None
    if 'banca_inicial' in payload:
        v = float(payload['banca_inicial'])
        if v <= 0:
            raise ValueError('A banca inicial deve ser maior que zero.')
        sets.append('banca_inicial=:bi'); params['bi'] = v
    if sets:
        with app_engine.begin() as c:
            c.execute(text(f'UPDATE {S}.bet_config SET {", ".join(sets)} WHERE id=1'), params)
    return get_config()


def reset_bankroll(password: str):
    """Apaga as apostas e volta a banca para R$ 1.000,00, mediante senha."""
    ensure()
    with app_engine.begin() as c:
        stored = c.execute(text(f'SELECT senha_hash FROM {S}.bet_config WHERE id=1')).scalar()
        given = hashlib.sha256((password or '').encode()).hexdigest()
        if not stored or not hmac.compare_digest(stored, given):
            raise PermissionError('Senha incorreta.')
        removed = c.execute(text(f'DELETE FROM {S}.bet_apostas')).rowcount
        c.execute(text(f'UPDATE {S}.bet_config SET banca_inicial=:b WHERE id=1'), {'b': BANKROLL_START})
    return {'apostas_removidas': removed, 'config': get_config()}


def place_bet(p: dict):
    """Abre a aposta como pendente — o resultado só é revelado em finalize_bet."""
    ensure()
    g = _need_game(p.get('jogo_id'))
    cutoff = date.fromisoformat(p['data_limite'])
    if g['data'] <= cutoff:
        raise ValueError('Só é possível apostar em jogos posteriores à data limite.')
    market, sel, side = p.get('mercado'), p.get('selecao'), p.get('lado')
    if market not in eng.MARKETS or sel not in eng.MARKETS[market][2] or side not in ('back', 'lay'):
        raise ValueError('Mercado, seleção ou tipo da aposta inválido.')
    minute = max(0, min(int(p.get('minuto', 0)), 90))
    if not g['timeline_ok'] and minute > 0:
        raise ValueError('Jogo sem minutos dos gols completos: aposte no minuto 0.')
    stake = float(p.get('stake') or 0)
    if stake <= 0:
        raise ValueError('Informe um valor positivo para a aposta.')
    score = eng.score_at(g, minute) if g['timeline_ok'] else (0, 0)
    q = eng.quote(g, market, sel, minute, score, as_of=cutoff)
    if q is None:
        raise ValueError('Mercado suspenso nesse minuto.')
    # Garante que dá para liquidar depois, sem revelar o resultado agora.
    if eng.settle_win(g, market, sel) is None:
        raise ValueError('Não foi possível liquidar este mercado (sem minutos dos gols).')
    odd = q[side]
    liability = stake if side == 'back' else stake * (odd - 1)
    if side == 'back' and stake < 0.10:
        raise ValueError('A stake mínima é R$ 0,10.')
    if side == 'lay' and liability < 0.10:
        raise ValueError('O risco mínimo (responsabilidade) é R$ 0,10.')
    cfg = get_config()
    reserved = _pending_exposure()
    livre = cfg['banca_atual'] - reserved
    if liability > livre + 1e-9:
        raise ValueError(f"Banca insuficiente: risco R$ {liability:.2f}, livre R$ {livre:.2f} "
                         f"(já há R$ {reserved:.2f} em entradas pendentes).")
    label, _per, sels = eng.MARKETS[market]
    with app_engine.begin() as c:
        new_id = c.execute(text(f'''INSERT INTO {S}.bet_apostas
            (data_limite, jogo_id, data_jogo, jogo, pais, campeonato, mercado, mercado_nome, selecao, selecao_nome, lado,
             odd, stake, minuto, placar_entrada, odd_origem, placar_final, resultado, lucro)
            VALUES (:dl,:jid,:dj,:jg,:pa,:ca,:mk,:mn,:sk,:sn,:ld,:od,:st,:mi,:pe,:oo,NULL,NULL,NULL) RETURNING id'''), {
            'dl': cutoff, 'jid': g['jogo_id'], 'dj': g['data'], 'jg': f"{g['casa']} x {g['fora']}", 'pa': g['pais'],
            'ca': g['campeonato'], 'mk': market, 'mn': label, 'sk': sel, 'sn': sels[sel][0], 'ld': side, 'od': odd,
            'st': stake, 'mi': minute, 'pe': f'{score[0]}-{score[1]}', 'oo': q['source']}).scalar()
        row = dict(c.execute(text(f'SELECT * FROM {S}.bet_apostas WHERE id=:i'), {'i': new_id}).mappings().one())
    return {**_bet_public(row, reveal=False), 'fonte': q['source'], 'banca': cfg['banca_atual'],
            'mensagem': 'Entrada aberta. Finalize para ver se foi green ou red.'}


def _settle_row(r, g):
    """Calcula placar/resultado/lucro. Corrige Lay em Under (aba Back-only) para Back com stake = risco."""
    side, stake, odd = r['lado'], float(r['stake']), float(r['odd'])
    sel, market = r['selecao'], r['mercado']
    if market in getattr(eng, 'BOOK_BACK_ONLY', ()) and side == 'lay' and odd > 1:
        # Usuário entrou na aba Under via Lay por engano: risco informado vira stake de Back.
        stake = round(stake * (odd - 1), 2)
        side = 'back'
    won = eng.settle_win(g, market, sel)
    if won is None:
        raise ValueError('Não foi possível liquidar este mercado.')
    pl = eng.pnl_settle(side, stake, odd, won)
    return side, stake, f"{g['gh']}-{g['ga']}", ('green' if pl > 0 else 'red'), round(pl, 2)


def finalize_bet(bet_id: int):
    ensure()
    with app_engine.begin() as c:
        r = c.execute(text(f'SELECT * FROM {S}.bet_apostas WHERE id=:i FOR UPDATE'), {'i': bet_id}).mappings().first()
        if not r:
            raise ValueError('Aposta não encontrada.')
        if r['resultado'] is not None:
            return {**_bet_public(dict(r), reveal=True), 'banca': get_config()['banca_atual'],
                    'mensagem': 'Esta aposta já estava finalizada.'}
        g = eng.game_by_id(r['jogo_id'])
        if not g:
            raise ValueError('Jogo da aposta não encontrado na base.')
        side, stake, placar, resultado, pl = _settle_row(dict(r), g)
        c.execute(text(f'''UPDATE {S}.bet_apostas
            SET lado=:ld, stake=:st, placar_final=:pf, resultado=:rs, lucro=:lu WHERE id=:i'''),
                  {'ld': side, 'st': stake, 'pf': placar, 'rs': resultado, 'lu': pl, 'i': bet_id})
        r = dict(c.execute(text(f'SELECT * FROM {S}.bet_apostas WHERE id=:i'), {'i': bet_id}).mappings().one())
    cfg = get_config()
    return {**_bet_public(r, reveal=True), 'banca': cfg['banca_atual'],
            'mensagem': f"{'GREEN' if r['resultado'] == 'green' else 'RED'} · placar {r['placar_final']} · {round(float(r['lucro']), 2):+.2f}"}


def repair_settlements():
    """Reliquida apostas finalizadas; corrige Lay indevido em mercados Back-only (ex.: Under 3,5)."""
    ensure()
    fixed = 0
    with app_engine.begin() as c:
        rows = [dict(r) for r in c.execute(
            text(f'SELECT * FROM {S}.bet_apostas WHERE resultado IS NOT NULL ORDER BY id')).mappings()]
        for r in rows:
            g = eng.game_by_id(r['jogo_id'])
            if not g or g.get('gh') is None:
                continue
            try:
                side, stake, placar, resultado, pl = _settle_row(r, g)
            except ValueError:
                continue
            if (side, float(stake), placar, resultado, float(pl)) == (
                    r['lado'], float(r['stake']), r['placar_final'], r['resultado'], float(r['lucro'])):
                continue
            c.execute(text(f'''UPDATE {S}.bet_apostas
                SET lado=:ld, stake=:st, placar_final=:pf, resultado=:rs, lucro=:lu WHERE id=:i'''),
                      {'ld': side, 'st': stake, 'pf': placar, 'rs': resultado, 'lu': pl, 'i': r['id']})
            fixed += 1
    return {'corrigidas': fixed, 'config': get_config()}


def list_pending_bets():
    ensure()
    with app_engine.connect() as c:
        rows = [dict(r) for r in c.execute(
            text(f'SELECT * FROM {S}.bet_apostas WHERE resultado IS NULL ORDER BY id DESC')).mappings()]
    return [_bet_public(r, reveal=False) for r in rows]


def list_bets():
    ensure()
    with app_engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(f'SELECT * FROM {S}.bet_apostas ORDER BY id DESC')).mappings()]
    out = []
    for r in rows:
        item = _bet_public(r, reveal=True)
        item['data_limite'] = r['data_limite'].isoformat() if r['data_limite'] else None
        item['criado_em'] = r['criado_em'].isoformat()
        out.append(item)
    return out


def reset_bets():
    ensure()
    with app_engine.begin() as c:
        return c.execute(text(f'DELETE FROM {S}.bet_apostas')).rowcount


def report():
    repair_settlements()
    cfg = get_config()
    bets = [b for b in list_bets() if b.get('resultado')]
    bets_sorted = sorted(bets, key=lambda r: (r['data_jogo'], r['id']))
    months = defaultdict(lambda: {'lucro': 0.0, 'apostas': 0, 'green': 0, 'red': 0})
    for b in bets_sorted:
        m = months[b['data_jogo'][:7]]
        m['lucro'] += b['lucro']; m['apostas'] += 1; m[b['resultado']] += 1
    bank = cfg['banca_inicial']; out = []
    for key in sorted(months):
        bank += months[key]['lucro']
        out.append({'mes': key, 'lucro': round(months[key]['lucro'], 2), 'apostas': months[key]['apostas'],
                    'green': months[key]['green'], 'red': months[key]['red'], 'banca': round(bank, 2)})
    acc = cfg['banca_inicial']; curve = [{'ordem': 0, 'banca': acc, 'data': None}]
    for i, b in enumerate(bets_sorted, 1):
        acc += b['lucro']
        curve.append({'ordem': i, 'banca': round(acc, 2), 'data': b['data_jogo']})
    total = sum(b['lucro'] for b in bets_sorted)
    return {'config': cfg, 'apostas': list(reversed(bets_sorted)), 'meses': out, 'curva': curve,
            'totais': {'apostas': len(bets_sorted), 'lucro': round(total, 2),
                       'green': sum(b['resultado'] == 'green' for b in bets_sorted),
                       'red': sum(b['resultado'] == 'red' for b in bets_sorted),
                       'stake_total': round(sum(b['stake'] for b in bets_sorted), 2),
                       'roi_stake': round(100 * total / sum(b['stake'] for b in bets_sorted), 2) if bets_sorted else None}}


# ----------------------------------------------------------------------------------------
# Conciliação de clubes entre as fontes
# ----------------------------------------------------------------------------------------
def reconciliation(pais: str | None = None):
    from . import bet_reconcile as recon
    j, o, h, a = eng.reconciliation_sources()
    items = recon.suggestions(j, o, h, a)
    if pais:
        items = [s for s in items if s['pais'] == pais]
    saved = [{'pais': k[0], 'fonte': k[1], 'nome_fonte': v['nome_fonte'], 'nome_padrao': v['padrao'], 'status': v['status']}
             for k, v in recon.links().items()]
    return {'cobertura': recon.coverage(eng.all_games()), 'sugestoes': items[:400], 'total_sugestoes': len(items),
            'vinculos': sorted(saved, key=lambda x: (x['pais'], x['nome_fonte'])),
            'paises': sorted({s['pais'] for s in recon.suggestions(j, o, h, a)})}


def save_reconciliation(pais, fonte, nome_fonte, nome_padrao, status='vinculado'):
    from . import bet_reconcile as recon
    if status not in ('vinculado', 'ignorado'):
        raise ValueError('Status inválido.')
    recon.save_link(pais, fonte, nome_fonte, nome_padrao, status)
    eng.all_games()
    return {'ok': True}


def delete_reconciliation(pais, fonte, nome_fonte):
    from . import bet_reconcile as recon
    return recon.delete_link(pais, fonte, nome_fonte)


def api_import(pais, liga, temporada):
    from . import bet_api, bet_reconcile as recon
    result = bet_api.import_season(pais, liga, temporada)
    recon.invalidate()
    eng.all_games()
    return result


def api_list():
    from . import bet_api
    return bet_api.imported()


def api_remove(pais, liga, temporada):
    from . import bet_api, bet_reconcile as recon
    ok = bet_api.remove(pais, liga, temporada)
    recon.invalidate()
    return ok
