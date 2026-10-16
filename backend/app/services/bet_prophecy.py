"""Profecia: cola estatísticas (mandante | indicador | visitante) e acha clubes com perfil parecido."""
from __future__ import annotations

import re
import threading
import time
from collections import Counter, defaultdict

from . import bet_engine as eng

WINDOW = 20
MIN_GAMES = 15
TOP_N = 12

LABELS = {
    'jogos': 'jogos',
    'v - e - d': 'ved',
    'v-e-d': 'ved',
    'gols marcados / jogo': 'gf',
    'gols marcados/jogo': 'gf',
    'gols sofridos / jogo': 'ga',
    'gols sofridos/jogo': 'ga',
    'over 0,5': 'over05',
    'over 0.5': 'over05',
    'over 1,5': 'over15',
    'over 1.5': 'over15',
    'over 2,5': 'over25',
    'over 2.5': 'over25',
    'under 3,5': 'under35',
    'under 3.5': 'under35',
    'ambos marcam': 'btts',
    'sem sofrer gol': 'sem_sofrer',
    'sem marcar gol': 'sem_marcar',
    'goleadas a favor / contra': 'goleadas',
    'goleadas a favor/contra': 'goleadas',
    'gols no 1º tempo': 'gols_1t',
    'gols no 1o tempo': 'gols_1t',
    'abriu o placar': 'abriu',
    'venceu após abrir o placar': 'venceu_abrir',
    'venceu apos abrir o placar': 'venceu_abrir',
}

_profiles = {'built_at': 0.0, 'items': []}
_lock = threading.Lock()


def _num(raw: str):
    s = (raw or '').strip().replace('%', '').replace(',', '.')
    if not s or s == '—':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_ved(raw: str):
    parts = re.split(r'\s*[-–]\s*', (raw or '').strip())
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _parse_goleadas(raw: str):
    parts = re.split(r'\s*/\s*', (raw or '').strip())
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def parse_paste(text: str):
    """Extrai perfis mandante (esquerda) e visitante (direita) do texto colado."""
    home, away = {}, {}
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'\t+|\s{2,}', line)
        if len(parts) < 3:
            # fallback: valor label valor com um espaço em labels compostos
            m = re.match(r'^(.+?)\s{1,}(.+?)\s{1,}(.+)$', line)
            if not m:
                continue
            parts = [m.group(1), m.group(2), m.group(3)]
        left, label, right = parts[0].strip(), parts[1].strip(), parts[2].strip()
        key = LABELS.get(label.lower())
        if not key:
            # tenta achar label conhecido dentro da linha
            low = line.lower()
            for lab, k in LABELS.items():
                if lab in low:
                    key = k
                    # re-split around label
                    idx = low.index(lab)
                    left = line[:idx].strip()
                    right = line[idx + len(lab):].strip()
                    break
        if not key:
            continue
        if key == 'ved':
            hv, av = _parse_ved(left), _parse_ved(right)
            if hv:
                home['v'], home['e'], home['d'] = hv
            if av:
                away['v'], away['e'], away['d'] = av
        elif key == 'goleadas':
            hg, ag = _parse_goleadas(left), _parse_goleadas(right)
            if hg:
                home['goleadas_pro'], home['goleadas_contra'] = hg
            if ag:
                away['goleadas_pro'], away['goleadas_contra'] = ag
        elif key == 'jogos':
            hj, aj = _num(left), _num(right)
            if hj is not None:
                home['jogos'] = int(hj)
            if aj is not None:
                away['jogos'] = int(aj)
        else:
            hl, ar = _num(left), _num(right)
            if hl is not None:
                home[key] = hl
            if ar is not None:
                away[key] = ar
    if len(home) < 4 and len(away) < 4:
        raise ValueError(
            'Não consegui ler o texto. Cole no formato: valor_mandante + indicador + valor_visitante '
            '(como na tabela da Casa de Apostas).'
        )
    return {'mandante': home, 'visitante': away}


def _profile_from_rows(team, rows):
    """rows: [{'gf','ga','goals','timeline_ok'}] últimos N, ordem cronológica."""
    n = len(rows)
    if not n:
        return None
    gf = sum(r['gf'] for r in rows)
    ga = sum(r['ga'] for r in rows)
    pct = lambda k: round(100 * k / n, 1)
    v = sum(r['gf'] > r['ga'] for r in rows)
    e = sum(r['gf'] == r['ga'] for r in rows)
    d = sum(r['gf'] < r['ga'] for r in rows)
    scores = Counter(f"{r['gf']}-{r['ga']}" for r in rows)
    top_scores = [{'placar': k, 'jogos': c} for k, c in scores.most_common(3)]
    tl = [r for r in rows if r.get('timeline_ok') and r.get('goals') is not None]
    first_half = total_goals = opened = open_win = 0
    for r in tl:
        for m, _side in r['goals']:
            total_goals += 1
            if m <= 45:
                first_half += 1
        if r['goals']:
            # primeiro gol do jogo: se foi do time (gf perspective — goals sides are h/a from match)
            # rows already store gf/ga from team perspective; goals need team side marker
            if r.get('opened'):
                opened += 1
                if r['gf'] > r['ga']:
                    open_win += 1
    return {
        'time': team,
        'pais': rows[-1].get('pais'),
        'jogos': n,
        'v': v, 'e': e, 'd': d,
        'win_pct': pct(v), 'loss_pct': pct(d),
        'gf': round(gf / n, 2), 'ga': round(ga / n, 2),
        'over05': pct(sum(r['gf'] + r['ga'] > 0 for r in rows)),
        'over15': pct(sum(r['gf'] + r['ga'] > 1 for r in rows)),
        'over25': pct(sum(r['gf'] + r['ga'] > 2 for r in rows)),
        'under35': pct(sum(r['gf'] + r['ga'] < 4 for r in rows)),
        'btts': pct(sum(r['gf'] > 0 and r['ga'] > 0 for r in rows)),
        'sem_sofrer': pct(sum(r['ga'] == 0 for r in rows)),
        'sem_marcar': pct(sum(r['gf'] == 0 for r in rows)),
        'goleadas_pro': sum(r['gf'] >= 4 and r['gf'] > r['ga'] for r in rows),
        'goleadas_contra': sum(r['ga'] >= 4 and r['ga'] > r['gf'] for r in rows),
        'gols_1t': round(100 * first_half / total_goals, 1) if total_goals else None,
        'abriu': round(100 * opened / len(tl), 1) if tl else None,
        'venceu_abrir': round(100 * open_win / opened, 1) if opened else None,
        'placares': top_scores,
    }


def _build_profiles():
    raw = eng._jogos_rows(eng.history_version())
    by_goals = defaultdict(list)
    for g in raw['goals']:
        by_goals[g['id_jogo']].append(g)
    hist = defaultdict(list)  # team -> rows chronologic
    for m in sorted(raw['matches'], key=lambda r: (r['data'], r['id'])):
        gh, ga = m['gols_casa'], m['gols_fora']
        if gh is None or ga is None:
            continue
        evs = by_goals.get(m['id_jogo'], [])
        hm = sorted(e['minuto'] for e in evs if e['lado'] == 'casa')
        am = sorted(e['minuto'] for e in evs if e['lado'] == 'fora')
        tl_ok = len(hm) == gh and len(am) == ga
        goals_h = sorted([(x, 'h') for x in hm] + [(x, 'a') for x in am]) if tl_ok else []
        goals_a = sorted([(x, 'a') for x in hm] + [(x, 'h') for x in am]) if tl_ok else []
        # opened: first goal side relative to team
        opened_h = bool(goals_h and goals_h[0][1] == 'h')
        opened_a = bool(goals_a and goals_a[0][1] == 'h')  # from away view, 'h' means own
        base = {'pais': m['pais'], 'data': m['data']}
        hist[m['mandante']].append({
            **base, 'gf': gh, 'ga': ga, 'timeline_ok': tl_ok, 'goals': goals_h, 'opened': opened_h,
        })
        hist[m['visitante']].append({
            **base, 'gf': ga, 'ga': gh, 'timeline_ok': tl_ok, 'goals': goals_a, 'opened': opened_a,
        })
    out = []
    for team, rows in hist.items():
        recent = rows[-WINDOW:]
        if len(recent) < MIN_GAMES:
            continue
        p = _profile_from_rows(team, recent)
        if p:
            out.append(p)
    return out


def club_profiles(force=False):
    with _lock:
        if not force and _profiles['items'] and time.time() - _profiles['built_at'] < 3600:
            return _profiles['items']
    items = _build_profiles()
    with _lock:
        _profiles.update(built_at=time.time(), items=items)
    return items


def _target_vector(paste: dict):
    """Normaliza o perfil colado para comparação (sem mando)."""
    n = float(paste.get('jogos') or WINDOW)
    v = paste.get('v')
    e = paste.get('e')
    d = paste.get('d')
    if v is not None and e is not None and d is not None and n:
        win = 100 * v / n
        loss = 100 * d / n
        draw = 100 * e / n
    else:
        win = loss = draw = None
    gp = paste.get('goleadas_pro')
    gc = paste.get('goleadas_contra')
    return {
        'win': win, 'draw': draw, 'loss': loss,
        'gf': paste.get('gf'), 'ga': paste.get('ga'),
        'over05': paste.get('over05'), 'over15': paste.get('over15'),
        'over25': paste.get('over25'), 'under35': paste.get('under35'),
        'btts': paste.get('btts'),
        'sem_sofrer': paste.get('sem_sofrer'), 'sem_marcar': paste.get('sem_marcar'),
        'goleadas_pro_pct': (100 * gp / n) if gp is not None and n else None,
        'goleadas_contra_pct': (100 * gc / n) if gc is not None and n else None,
        'gols_1t': paste.get('gols_1t'), 'abriu': paste.get('abriu'),
        'venceu_abrir': paste.get('venceu_abrir'),
    }


def _club_vector(p):
    n = p['jogos'] or 1
    return {
        'win': p['win_pct'], 'draw': round(100 * p['e'] / n, 1), 'loss': p['loss_pct'],
        'gf': p['gf'], 'ga': p['ga'],
        'over05': p['over05'], 'over15': p['over15'], 'over25': p['over25'], 'under35': p['under35'],
        'btts': p['btts'], 'sem_sofrer': p['sem_sofrer'], 'sem_marcar': p['sem_marcar'],
        'goleadas_pro_pct': round(100 * p['goleadas_pro'] / n, 1),
        'goleadas_contra_pct': round(100 * p['goleadas_contra'] / n, 1),
        'gols_1t': p['gols_1t'], 'abriu': p['abriu'], 'venceu_abrir': p['venceu_abrir'],
    }


WEIGHTS = {
    'win': 1.2, 'draw': 0.8, 'loss': 1.2,
    'gf': 2.0, 'ga': 2.0,
    'over05': 0.6, 'over15': 0.9, 'over25': 1.1, 'under35': 0.8,
    'btts': 1.0, 'sem_sofrer': 0.7, 'sem_marcar': 0.7,
    'goleadas_pro_pct': 1.0, 'goleadas_contra_pct': 1.0,
    'gols_1t': 0.5, 'abriu': 0.6, 'venceu_abrir': 0.5,
}


def _distance(target, club):
    total = weight = 0.0
    for k, w in WEIGHTS.items():
        a, b = target.get(k), club.get(k)
        if a is None or b is None:
            continue
        # gols em escala ~0-4; % em 0-100 — normaliza gols*25
        scale = 25.0 if k in ('gf', 'ga') else 1.0
        total += w * abs(a - b) * scale
        weight += w
    if weight <= 0:
        return 1e9
    return total / weight


def _public_match(p, dist):
    return {
        'time': p['time'],
        'pais': p.get('pais'),
        'jogos': p['jogos'],
        'proximidade': round(max(0.0, 100 - dist), 1),
        'distancia': round(dist, 2),
        'vitorias_pct': p['win_pct'],
        'derrotas_pct': p['loss_pct'],
        'over_0_5': p['over05'],
        'over_1_5': p['over15'],
        'over_2_5': p['over25'],
        'ambos_marcam': p['btts'],
        'goleadas_aplicadas': p['goleadas_pro'],
        'goleadas_sofridas': p['goleadas_contra'],
        'placares_mais_frequentes': p['placares'],
    }


def find_similar(paste_side: dict, profiles=None, top=TOP_N):
    target = _target_vector(paste_side)
    scored = []
    for p in profiles or club_profiles():
        d = _distance(target, _club_vector(p))
        scored.append((d, p))
    scored.sort(key=lambda x: x[0])
    return [_public_match(p, d) for d, p in scored[:top]]


def prophecy(text: str, top: int = TOP_N):
    parsed = parse_paste(text)
    profiles = club_profiles()
    if not profiles:
        raise ValueError('Sem clubes suficientes na base jogos para comparar.')
    return {
        'lido': parsed,
        'janela': WINDOW,
        'aviso': (f'Comparação com os últimos {WINDOW} jogos de cada clube na tabela jogos, '
                  f'sem separar mando de campo. Quanto maior a proximidade, mais parecido o perfil.'),
        'mandante': find_similar(parsed['mandante'], profiles, top),
        'visitante': find_similar(parsed['visitante'], profiles, top),
    }
