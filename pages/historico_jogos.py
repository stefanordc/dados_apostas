from __future__ import annotations

import math

import streamlit as st

from src.repositories.history_repository import (
    HistoryFilters,
    aggregate,
    club_options,
    detect_history_schema,
    distinct_options,
    filtered_games,
    winner_options,
)
from src.ui import section_title
from src.utils import format_number_br

st.title("Histórico de jogos")
st.caption("Fonte externa em modo somente leitura. Os filtros são encadeados e atualizam as opções disponíveis.")

try:
    detect_history_schema()
except Exception as exc:
    st.error(str(exc))
    st.info(
        "O projeto tenta identificar automaticamente nomes como país, temporada, campeonato, rodada, "
        "mandante, visitante, gols_casa e gols_fora. Se sua tabela usar nomes diferentes, execute "
        "scripts/inspect_history_schema.py e ajuste COLUMN_ALIASES em src/repositories/history_repository.py."
    )
    st.stop()


def pick(label: str, options: list[str], key: str, disabled: bool = False) -> str | None:
    return st.selectbox(
        label,
        options=[None] + options,
        index=0,
        format_func=lambda value: "Todos" if value is None else str(value),
        placeholder="Digite para buscar",
        key=key,
        disabled=disabled,
    )


# Encadeamento: cada seleção restringe os campos seguintes.
filters = HistoryFilters()

section_title("Filtros")
row1 = st.columns(4)
with row1[0]:
    country = pick("País", distinct_options("pais", filters), "hist_country")
filters = HistoryFilters(country=country)
with row1[1]:
    season = pick("Temporada", distinct_options("temporada", filters), "hist_season")
filters = HistoryFilters(country=country, season=season)
with row1[2]:
    championship = pick("Campeonato", distinct_options("campeonato", filters), "hist_championship")
filters = HistoryFilters(country=country, season=season, championship=championship)
with row1[3]:
    phase = pick("Fase (rodada)", distinct_options("rodada", filters), "hist_phase")
filters = HistoryFilters(country=country, season=season, championship=championship, phase=phase)

row2 = st.columns(4)
with row2[0]:
    club = pick("Clube", club_options(filters), "hist_club")
filters = HistoryFilters(country=country, season=season, championship=championship, phase=phase, club=club)
with row2[1]:
    home = pick("Mandante", distinct_options("mandante", filters), "hist_home")
filters = HistoryFilters(country=country, season=season, championship=championship, phase=phase, club=club, home=home)
with row2[2]:
    away = pick("Visitante", distinct_options("visitante", filters), "hist_away")
filters = HistoryFilters(
    country=country, season=season, championship=championship, phase=phase, club=club, home=home, away=away
)
with row2[3]:
    winner = pick("Vencedor", winner_options(filters), "hist_winner")

row3 = st.columns(3)
with row3[0]:
    st.markdown("**Gols Casa**")
    gh1, gh2 = st.columns(2)
    with gh1:
        goals_home_min = st.number_input("Mínimo", min_value=0, value=None, step=1, key="gh_min", label_visibility="collapsed", placeholder="Mín.")
    with gh2:
        goals_home_max = st.number_input("Máximo", min_value=0, value=None, step=1, key="gh_max", label_visibility="collapsed", placeholder="Máx.")
with row3[1]:
    st.markdown("**Gols Fora**")
    ga1, ga2 = st.columns(2)
    with ga1:
        goals_away_min = st.number_input("Mínimo", min_value=0, value=None, step=1, key="ga_min", label_visibility="collapsed", placeholder="Mín.")
    with ga2:
        goals_away_max = st.number_input("Máximo", min_value=0, value=None, step=1, key="ga_max", label_visibility="collapsed", placeholder="Máx.")
with row3[2]:
    st.markdown("**Saldo de Gols**")
    gd1, gd2 = st.columns(2)
    with gd1:
        goal_diff_min = st.number_input("Mínimo", min_value=0, value=None, step=1, key="gd_min", label_visibility="collapsed", placeholder="Mín.")
    with gd2:
        goal_diff_max = st.number_input("Máximo", min_value=0, value=None, step=1, key="gd_max", label_visibility="collapsed", placeholder="Máx.")

row4 = st.columns(2)
with row4[0]:
    home_winner = st.selectbox("Vencedor Casa", ["Todos", "Sim", "Não"], key="home_winner")
with row4[1]:
    away_winner = st.selectbox("Vencedor Fora", ["Todos", "Sim", "Não"], key="away_winner")

if goals_home_min is not None and goals_home_max is not None and goals_home_min > goals_home_max:
    st.error("Em Gols Casa, o mínimo não pode ser maior que o máximo.")
    st.stop()
if goals_away_min is not None and goals_away_max is not None and goals_away_min > goals_away_max:
    st.error("Em Gols Fora, o mínimo não pode ser maior que o máximo.")
    st.stop()
if goal_diff_min is not None and goal_diff_max is not None and goal_diff_min > goal_diff_max:
    st.error("Em Saldo de Gols, o mínimo não pode ser maior que o máximo.")
    st.stop()

filters = HistoryFilters(
    country=country,
    season=season,
    championship=championship,
    phase=phase,
    club=club,
    home=home,
    away=away,
    goals_home_min=goals_home_min,
    goals_home_max=goals_home_max,
    goals_away_min=goals_away_min,
    goals_away_max=goals_away_max,
    goal_diff_min=goal_diff_min,
    goal_diff_max=goal_diff_max,
    winner=winner,
    home_winner=None if home_winner == "Todos" else home_winner,
    away_winner=None if away_winner == "Todos" else away_winner,
)

try:
    metrics = aggregate(filters)
except Exception as exc:
    st.error(f"Erro ao consultar o histórico: {exc}")
    st.stop()

st.divider()
section_title("Resumo dinâmico")

cards1 = st.columns(6)
cards1[0].metric("Total de Jogos", format_number_br(metrics["total_jogos"]))
cards1[1].metric("Vitórias Casa", format_number_br(metrics["vitorias_casa"]))
cards1[2].metric("Vitórias Fora", format_number_br(metrics["vitorias_fora"]))
cards1[3].metric("% Vitórias Casa", f"{metrics['pct_vitorias_casa']:.2f}%".replace(".", ","))
cards1[4].metric("% Vitórias Fora", f"{metrics['pct_vitorias_fora']:.2f}%".replace(".", ","))
cards1[5].metric("Total de Gols", format_number_br(metrics["total_gols"]))

cards2 = st.columns(5)
cards2[0].metric("Gols Marcados Casa", format_number_br(metrics["gols_casa"]))
cards2[1].metric("Gols Marcados Fora", format_number_br(metrics["gols_fora"]))
cards2[2].metric("Média de Gols Casa", format_number_br(metrics["media_gols_casa"], 2))
cards2[3].metric("Média de Gols Fora", format_number_br(metrics["media_gols_fora"], 2))
cards2[4].metric("Média Geral de Gols", format_number_br(metrics["media_gols_geral"], 2))

st.divider()
section_title("Jogos filtrados")

page_size = st.selectbox("Linhas por página", [100, 250, 500], index=1, key="hist_page_size")
total_rows = int(metrics["total_jogos"])
total_pages = max(1, math.ceil(total_rows / page_size))
page = st.number_input("Página", min_value=1, max_value=total_pages, value=1, step=1, key="hist_page")
offset = (int(page) - 1) * page_size

try:
    df = filtered_games(filters, limit=page_size, offset=offset)
    st.caption(f"Exibindo página {int(page)} de {total_pages} — {total_rows:,} jogo(s).".replace(",", "."))
    st.dataframe(df, use_container_width=True, hide_index=True, height=560)
except Exception as exc:
    st.error(f"Erro ao carregar os jogos filtrados: {exc}")
