"""Odds históricas da API futpythontrader (mesmo formato da tabela `odds`), guardadas em cache local.

Só entra no BET Teste o que o usuário importar explicitamente (país + liga + temporada). A chave fica
em `FUTPY_API_KEY` no `.env` (ignorado pelo git) e nunca é devolvida às telas.
"""
from __future__ import annotations

import csv
import io
import json
import pickle
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from ..config import settings

BASE = 'https://futpythontrader.com.br/api/download'
DIR = Path(__file__).resolve().parents[2] / '.cache' / 'api'
SLUG = re.compile(r'^[a-z0-9\-]{2,60}$')
SEASON = re.compile(r'^\d{4}(-\d{4})?$')

# país da API (inglês) -> nome usado nas tabelas do projeto
COUNTRY_PT = {'england': 'Inglaterra', 'brazil': 'Brasil', 'spain': 'Espanha', 'italy': 'Itália', 'germany': 'Alemanha',
              'france': 'França', 'portugal': 'Portugal', 'netherlands': 'Holanda', 'argentina': 'Argentina',
              'colombia': 'Colômbia', 'chile': 'Chile', 'greece': 'Grécia', 'ukraine': 'Ucrânia', 'austria': 'Áustria',
              'norway': 'Noruega', 'paraguay': 'Paraguai', 'uruguay': 'Uruguai', 'belgium': 'Bélgica', 'turkey': 'Turquia',
              'peru': 'Peru', 'usa': 'Estados Unidos', 'japan': 'Japão', 'mexico': 'México', 'croatia': 'Croácia',
              'scotland': 'Escócia', 'switzerland': 'Suíça', 'denmark': 'Dinamarca', 'sweden': 'Suécia', 'poland': 'Polônia',
              'south-america': 'América do Sul', 'europe': 'Europa'}

ODD_MAP = {'Odd_1_FT': 'odd_casa_ft', 'Odd_X_FT': 'odd_empate_ft', 'Odd_2_FT': 'odd_fora_ft',
           'Odd_1_HT': 'odd_casa_ht', 'Odd_X_HT': 'odd_empate_ht', 'Odd_2_HT': 'odd_fora_ht',
           'BTTS_Yes': 'ambos_marcam_sim', 'BTTS_No': 'ambos_marcam_nao',
           'DC_1X': 'dupla_chance_1x', 'DC_12': 'dupla_chance_12', 'DC_X2': 'dupla_chance_x2'}
for _p in ('HT', 'FT'):
    for _l in ('0_5', '1_5', '2_5', '3_5', '4_5'):
        ODD_MAP[f'Over_{_p}_{_l}'] = f'over_{_l}_{_p.lower()}'
        ODD_MAP[f'Under_{_p}_{_l}'] = f'under_{_l}_{_p.lower()}'
for _i in range(4):
    for _j in range(4):
        ODD_MAP[f'CS_{_i}_{_j}'] = f'correct_score_{_i}_{_j}'


class ApiError(ValueError):
    pass


def _file(country, league, season):
    return DIR / f'{country}__{league}__{season}.pkl'


def _float(v):
    try:
        x = float(str(v).replace(',', '.'))
        return x if x > 1 else None
    except (TypeError, ValueError):
        return None


def _minutes(raw):
    try:
        value = json.loads(raw) if raw not in (None, '') else []
        return sorted(int(x) for x in value)
    except (ValueError, TypeError):
        return None


def _parse(text_csv, country):
    pais = COUNTRY_PT.get(country, country.title())
    games = []
    for r in csv.DictReader(io.StringIO(text_csv)):
        try:
            d = datetime.strptime(r['Date'], '%d/%m/%Y').date()
        except (KeyError, ValueError):
            continue
        gh = int(r['Home_Score']) if str(r.get('Home_Score', '')).strip().lstrip('-').isdigit() else None
        ga = int(r['Away_Score']) if str(r.get('Away_Score', '')).strip().lstrip('-').isdigit() else None
        hm, am = _minutes(r.get('Min_Goals_Home')), _minutes(r.get('Min_Goals_Away'))
        ok = gh is not None and ga is not None and hm is not None and am is not None and len(hm) == gh and len(am) == ga
        g = {'fonte': 'api', 'id': r.get('Match_ID'), 'jogo_id': f"a{r.get('Match_ID')}", 'data': d, 'pais': pais,
             'campeonato': r.get('Div') or r.get('League'), 'temporada': r.get('Season'),
             'formato': 'Copa' if re.search(r'cup|copa|champions|libertadores|sudamericana', (r.get('Div') or '').lower()) else 'Liga',
             'rodada': r.get('Round'), 'casa': r['Home'], 'fora': r['Away'], 'gh': gh, 'ga': ga,
             'timeline_ok': bool(ok),
             'goals': sorted([(m, 'h') for m in hm] + [(m, 'a') for m in am]) if ok else []}
        g['goal_minutes'] = [x[0] for x in g['goals']]
        for src, dst in ODD_MAP.items():
            v = _float(r.get(src))
            if v is not None:
                g[dst] = v
        games.append(g)
    return games


def import_season(country, league, season):
    country, league, season = (country or '').strip().lower(), (league or '').strip().lower(), (season or '').strip()
    if not (SLUG.match(country) and SLUG.match(league) and SEASON.match(season)):
        raise ValueError('Use o formato da API: país e liga em minúsculas com hífen (ex.: england / premier-league) e '
                         'temporada como 2023-2024 ou 2026.')
    key = settings.futpy_api_key
    if not key:
        raise ValueError('Chave da API não configurada: defina FUTPY_API_KEY no arquivo backend/.env e reinicie o backend.')
    url = f'{BASE}/{urllib.parse.quote(country)}/{urllib.parse.quote(league)}/{urllib.parse.quote(season)}?' + \
          urllib.parse.urlencode({'api_key': key})
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            body = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError('A API recusou a chave (401). Confira FUTPY_API_KEY.') from None
        if exc.code == 404:
            raise ValueError('Dataset não encontrado na API: confira país, liga e temporada.') from None
        raise ValueError(f'A API respondeu com erro {exc.code}.') from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Não foi possível conectar à API da futpythontrader.') from None
    games = _parse(body, country)
    if not games:
        raise ValueError('A API não devolveu jogos para esse dataset.')
    DIR.mkdir(parents=True, exist_ok=True)
    _file(country, league, season).write_bytes(pickle.dumps(games))
    return {'jogos': len(games), 'com_minutos': sum(g['timeline_ok'] for g in games),
            'de': min(g['data'] for g in games).isoformat(), 'ate': max(g['data'] for g in games).isoformat()}


def imported():
    out = []
    if DIR.exists():
        for f in sorted(DIR.glob('*.pkl')):
            country, league, season = f.stem.split('__')
            try:
                games = pickle.loads(f.read_bytes())
            except Exception:
                continue
            out.append({'pais': country, 'liga': league, 'temporada': season, 'jogos': len(games),
                        'de': min(g['data'] for g in games).isoformat(), 'ate': max(g['data'] for g in games).isoformat()})
    return out


def remove(country, league, season):
    f = _file(country, league, season)
    if f.exists():
        f.unlink()
        return True
    return False


def api_games():
    games = []
    if DIR.exists():
        for f in sorted(DIR.glob('*.pkl')):
            try:
                games.extend(pickle.loads(f.read_bytes()))
            except Exception:
                continue
    return games
