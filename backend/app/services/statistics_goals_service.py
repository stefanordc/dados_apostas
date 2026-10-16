"""Agregados de gols para a aba Estatísticas · Gols e Resultado.

Usa `jogos` + `minutos_gols` (mesma validação de sequência do SofaScore).
Indicadores são na ótica do mando da partida (mandante/visitante), não por clube.
"""
from __future__ import annotations

from sqlalchemy import text

from ..config import settings
from ..db import history_connection
from . import goal_timeline_service as timeline
from .continent_service import CONTINENTS, for_country

JOGOS = f'{settings.history_schema}.jogos'
HISTORICO = f'{settings.history_schema}.{settings.history_table}'
STAT_BANDS = ('0-15', '16-30', '31-45', '46-60', '61-75', '76-90', '90+')
MAX_GAMES = 40_000


def _map_band(label: str | None) -> str | None:
    if not label:
        return None
    if label == '45+':
        return '31-45'
    return label if label in STAT_BANDS else None


def _rate(count: int, total: int) -> dict:
    return {
        'value': round(count * 100 / total, 2) if total else None,
        'count': count,
        'total': total,
    }


def _load_games(continent: str | None, country: str | None, competition: str | None,
                year_from: int | None, year_to: int | None,
                divisao: str | None = None, formato: str | None = None) -> tuple[list[dict], str | None]:
    rules = [
        'j.data < CURRENT_DATE',
        'j.gols_casa IS NOT NULL',
        'j.gols_fora IS NOT NULL',
        "NULLIF(BTRIM(j.mandante::text), '') IS NOT NULL",
        "NULLIF(BTRIM(j.visitante::text), '') IS NOT NULL",
    ]
    params: dict = {'cap': MAX_GAMES}
    if country:
        rules.append('j.pais = :country')
        params['country'] = country
    if competition:
        rules.append('j.campeonato = :competition')
        params['competition'] = competition
    if year_from is not None:
        rules.append('EXTRACT(YEAR FROM j.data)::int >= :year_from')
        params['year_from'] = year_from
    if year_to is not None:
        rules.append('EXTRACT(YEAR FROM j.data)::int <= :year_to')
        params['year_to'] = year_to
    join_sql = ''
    if divisao or formato:
        # jogos não tem divisão/formato; concilia com historico_jogos pela chave do jogo.
        join_sql = f'''INNER JOIN {HISTORICO} h ON h.data = j.data
            AND BTRIM(h.pais::text) = BTRIM(j.pais::text)
            AND BTRIM(h.campeonato::text) = BTRIM(j.campeonato::text)
            AND BTRIM(h.casa::text) = BTRIM(j.mandante::text)
            AND BTRIM(h.fora::text) = BTRIM(j.visitante::text)'''
        if divisao:
            rules.append("BTRIM(h.divisao::text) = :divisao")
            params['divisao'] = divisao
        if formato:
            rules.append("BTRIM(h.formato::text) = :formato")
            params['formato'] = formato
    sql = f'''SELECT DISTINCT j.id_jogo, j.data, j.pais, j.campeonato,
                     j.mandante AS casa, j.visitante AS fora,
                     j.gols_casa AS gh, j.gols_fora AS ga
              FROM {JOGOS} j
              {join_sql}
              WHERE {' AND '.join(rules)}
              ORDER BY j.data DESC, j.id_jogo DESC
              LIMIT :cap'''
    try:
        with history_connection() as conn:
            rows = [dict(r) for r in conn.execute(text(sql), params).mappings()]
    except Exception as exc:
        return [], f'Não foi possível consultar jogos ({type(exc).__name__}).'
    if continent:
        rows = [g for g in rows if for_country(g.get('pais')) == continent]
    return rows, None


def analyze(payload: dict) -> dict:
    continent = str(payload.get('continent') or payload.get('league_continent') or '').strip() or None
    country = str(payload.get('country') or payload.get('league_country') or '').strip() or None
    competition = str(payload.get('competition') or payload.get('league_competition') or '').strip() or None
    divisao = str(payload.get('divisao') or '').strip() or None
    formato = str(payload.get('formato') or '').strip() or None
    year_from = payload.get('year_from')
    year_to = payload.get('year_to')
    if continent and continent not in CONTINENTS:
        raise ValueError('Continente inválido.')
    if year_from is not None:
        year_from = int(year_from)
    if year_to is not None:
        year_to = int(year_to)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError('O ano De não pode ser maior que o ano Até.')

    games, load_error = _load_games(continent, country, competition, year_from, year_to, divisao, formato)
    meta = {
        'year_from': year_from, 'year_to': year_to,
        'continent': continent, 'country': country, 'competition': competition,
        'divisao': divisao, 'formato': formato,
    }
    if load_error:
        return {
            'games': 0, 'valid_games': 0, 'requested_games': 0, 'goals_recorded': 0,
            'truncated': True, 'cards': [], 'minute_bands': [],
            'warning': load_error,
            'denominators': '',
            **meta,
        }

    try:
        events_by_game, timeline_error = timeline.fetch([g['id_jogo'] for g in games])
    except Exception as exc:
        return {
            'games': len(games), 'valid_games': 0, 'requested_games': len(games),
            'goals_recorded': 0, 'truncated': len(games) >= MAX_GAMES, 'cards': [],
            'minute_bands': [],
            'warning': f'Não foi possível consultar minutos_gols ({type(exc).__name__}).',
            'denominators': '',
            **meta,
        }

    home_open = away_open = 0
    home_win = home_eq = home_comeback = 0
    away_win = away_eq = away_comeback = 0
    bands = dict.fromkeys(STAT_BANDS, 0)
    valid = 0
    goals_total = 0

    for game in games:
        events = timeline._sequence(game, events_by_game.get(str(game['id_jogo']), []))
        if events is None:
            continue
        valid += 1
        first = events[0]['side'] if events else None
        gh, ga = int(game['gh']), int(game['ga'])
        if first == 'h':
            home_open += 1
            equalized = any(
                ev['side'] == 'a' and ev['score'][0] == ev['score'][1] and ev['before'][0] > ev['before'][1]
                for ev in events[1:]
            )
            home_eq += int(equalized)
            home_win += int(gh > ga)
            home_comeback += int(gh < ga)
        elif first == 'a':
            away_open += 1
            equalized = any(
                ev['side'] == 'h' and ev['score'][0] == ev['score'][1] and ev['before'][1] > ev['before'][0]
                for ev in events[1:]
            )
            away_eq += int(equalized)
            away_win += int(ga > gh)
            away_comeback += int(ga < gh)
        for ev in events:
            mapped = _map_band(ev.get('band'))
            if mapped:
                bands[mapped] += 1
                goals_total += 1

    cards = [
        {'key': 'home_opens', 'label': 'Mandante abre o placar',
         'note': '% das partidas com linha do tempo válida', **_rate(home_open, valid)},
        {'key': 'home_opens_wins', 'label': 'Mandante abre o placar e vence a partida',
         'note': '% das partidas em que o mandante abriu', **_rate(home_win, home_open)},
        {'key': 'home_opens_equalized', 'label': 'Mandante abre o placar e sofre o empate',
         'note': '% das partidas em que o mandante abriu', **_rate(home_eq, home_open)},
        {'key': 'home_opens_overturned', 'label': 'Mandante abre o placar e sofre a virada',
         'note': '% das partidas em que o mandante abriu', **_rate(home_comeback, home_open)},
        {'key': 'away_opens', 'label': 'Visitante abre o placar',
         'note': '% das partidas com linha do tempo válida', **_rate(away_open, valid)},
        {'key': 'away_opens_wins', 'label': 'Visitante abre o placar e vence a partida',
         'note': '% das partidas em que o visitante abriu', **_rate(away_win, away_open)},
        {'key': 'away_opens_equalized', 'label': 'Visitante abre o placar e sofre o empate',
         'note': '% das partidas em que o visitante abriu', **_rate(away_eq, away_open)},
        {'key': 'away_opens_overturned', 'label': 'Visitante abre o placar e sofre a virada',
         'note': '% das partidas em que o visitante abriu', **_rate(away_comeback, away_open)},
    ]
    minute_bands = [
        {'label': label, **_rate(bands[label], goals_total)}
        for label in STAT_BANDS
    ]

    warning = timeline_error
    if len(games) >= MAX_GAMES:
        warning = ((warning + ' ') if warning else '') + (
            f'Amostra limitada às {MAX_GAMES:,} partidas mais recentes do recorte.'.replace(',', '.')
        )
    if valid == 0 and games and not warning:
        warning = 'Nenhuma partida com sequência completa em minutos_gols neste recorte.'

    return {
        'games': len(games),
        'valid_games': valid,
        'requested_games': len(games),
        'goals_recorded': goals_total,
        'truncated': len(games) >= MAX_GAMES,
        'cards': cards,
        'minute_bands': minute_bands,
        'warning': warning,
        'denominators': (
            'Abertura: partidas com sequência completa em minutos_gols. '
            'Venceu / sofreu empate / sofreu virada: partidas em que aquele lado abriu. '
            'Faixas de minuto: todos os gols validados (acréscimos do 1º tempo entram em 31-45).'
        ),
        **meta,
    }
