from __future__ import annotations

from decimal import Decimal

import streamlit as st

from src.countries import CONTINENTS
from src.db import initialize_database
from src.repositories import cadastro_repository as repo
from src.ui import section_title
from src.utils import normalize_season

st.title("Cadastros")
st.caption("Cadastre a base estrutural utilizada pelos modelos e backtests.")

try:
    initialize_database()
except Exception as exc:
    st.error(f"Não foi possível inicializar o banco principal: {exc}")
    st.stop()

countries = repo.list_countries()
country_by_name = {row["nome"]: row for row in countries}
country_names = list(country_by_name)

tab_market, tab_clubs, tab_champs, tab_countries = st.tabs(
    ["Valor de Mercado", "Clubes", "Campeonatos", "Países"]
)

with tab_market:
    section_title("Valor de Mercado", "Todos os campos são obrigatórios.")
    col1, col2, col3 = st.columns(3)
    with col1:
        season_raw = st.text_input("Temporada *", placeholder="Ex.: 2026 ou 2025/2026", key="mv_season")
        country_name = st.selectbox(
            "País *",
            options=country_names,
            index=None,
            placeholder="Digite para buscar um país",
            key="mv_country",
        )
    country_id = int(country_by_name[country_name]["id"]) if country_name else None
    championships = repo.list_championships(country_id) if country_id else []
    championship_names = [row["nome"] for row in championships]
    champ_by_name = {row["nome"]: row for row in championships}

    with col2:
        championship_name = st.selectbox(
            "Campeonato *",
            options=championship_names,
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            disabled=country_id is None,
            key="mv_championship",
        )

    normalized_season: str | None = None
    if season_raw.strip():
        try:
            normalized_season = normalize_season(season_raw)
        except ValueError:
            normalized_season = None

    championship_id = None
    if championship_name and championship_name in champ_by_name:
        championship_id = int(champ_by_name[championship_name]["id"])

    clubs = (
        repo.list_clubs(country_id, championship_id, normalized_season)
        if country_id
        else []
    )
    # Se o campeonato ainda é novo ou não há vínculos na temporada, permita localizar clubes do país.
    if country_id and not clubs:
        clubs = repo.list_clubs(country_id)
    club_names = [row["nome"] for row in clubs]

    with col3:
        club_name = st.selectbox(
            "Clube *",
            options=club_names,
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            disabled=country_id is None,
            key="mv_club",
        )

    col4, col5 = st.columns([1, 2])
    with col4:
        currency = st.selectbox(
            "Moeda *",
            options=["EUR", "USD", "BRL"],
            format_func=lambda x: {"EUR": "Euro (EUR)", "USD": "Dólar (USD)", "BRL": "Real (BRL)"}[x],
            key="mv_currency",
        )
    with col5:
        value = st.number_input(
            "Valor de mercado *",
            min_value=0.0,
            value=None,
            step=100000.0,
            format="%.2f",
            placeholder="Ex.: 562550000",
            key="mv_value",
        )

    if st.button("Salvar valor de mercado", type="primary", use_container_width=True):
        errors: list[str] = []
        try:
            season = normalize_season(season_raw)
        except ValueError as exc:
            errors.append(str(exc))
            season = ""
        if not country_id:
            errors.append("Selecione o país.")
        if not championship_name:
            errors.append("Informe o campeonato.")
        if not club_name:
            errors.append("Informe o clube.")
        if value is None:
            errors.append("Informe o valor de mercado.")
        if errors:
            st.error(" ".join(errors))
        else:
            try:
                champ_id = repo.get_or_create_championship(country_id, championship_name)
                club_id = repo.get_or_create_club(country_id, club_name)
                repo.save_market_value(
                    season=season,
                    country_id=country_id,
                    championship_id=champ_id,
                    club_id=club_id,
                    currency=currency,
                    value=Decimal(str(value)),
                )
                st.success("Valor de mercado salvo.")
                st.rerun()
            except Exception as exc:
                st.error(f"Erro ao salvar: {exc}")

    st.divider()
    section_title("Últimos valores cadastrados")
    st.dataframe(repo.market_values_dataframe(), use_container_width=True, hide_index=True)

with tab_clubs:
    section_title("Clubes", "Cadastre o clube e associe-o a campeonato e temporada.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        club_country = st.selectbox(
            "País *", country_names, index=None, placeholder="Digite para buscar", key="club_country"
        )
    club_country_id = int(country_by_name[club_country]["id"]) if club_country else None
    with c2:
        club_season_raw = st.text_input("Temporada *", placeholder="2026 ou 2025/2026", key="club_season")
    club_champs = repo.list_championships(club_country_id) if club_country_id else []
    with c3:
        club_champ = st.selectbox(
            "Campeonato *",
            [row["nome"] for row in club_champs],
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            disabled=club_country_id is None,
            key="club_champ",
        )
    existing_clubs = repo.list_clubs(club_country_id) if club_country_id else []
    with c4:
        club_name_new = st.selectbox(
            "Clube *",
            [row["nome"] for row in existing_clubs],
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            disabled=club_country_id is None,
            key="club_name_new",
        )
    if st.button("Salvar clube", key="save_club", type="primary"):
        try:
            season = normalize_season(club_season_raw)
            if not club_country_id or not club_champ or not club_name_new:
                raise ValueError("Preencha país, temporada, campeonato e clube.")
            champ_id = repo.get_or_create_championship(club_country_id, club_champ)
            club_id = repo.get_or_create_club(club_country_id, club_name_new)
            repo.link_club_to_championship(club_id, champ_id, season)
            st.success("Clube salvo e associado ao campeonato.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.dataframe(repo.clubs_dataframe(club_country_id), use_container_width=True, hide_index=True)

with tab_champs:
    section_title("Campeonatos")
    cc1, cc2 = st.columns(2)
    with cc1:
        champ_country = st.selectbox(
            "País *", country_names, index=None, placeholder="Digite para buscar", key="champ_country"
        )
    champ_country_id = int(country_by_name[champ_country]["id"]) if champ_country else None
    champ_options = repo.list_championships(champ_country_id) if champ_country_id else []
    with cc2:
        champ_name_new = st.selectbox(
            "Campeonato *",
            [row["nome"] for row in champ_options],
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            disabled=champ_country_id is None,
            key="champ_name_new",
        )
    if st.button("Salvar campeonato", key="save_champ", type="primary"):
        if not champ_country_id or not champ_name_new:
            st.error("Preencha país e campeonato.")
        else:
            try:
                repo.get_or_create_championship(champ_country_id, champ_name_new)
                st.success("Campeonato salvo.")
                st.rerun()
            except Exception as exc:
                st.error(f"Erro ao salvar: {exc}")
    st.dataframe(repo.championships_dataframe(champ_country_id), use_container_width=True, hide_index=True)

with tab_countries:
    section_title("Países", "Europa, Ásia, América do Sul, América do Norte e Oceania já vêm pré-cadastradas.")
    pc1, pc2 = st.columns(2)
    with pc1:
        continent = st.selectbox("Continente *", CONTINENTS, key="country_continent")
    current_names = [row["nome"] for row in countries if row["continente"] == continent]
    with pc2:
        new_country_name = st.selectbox(
            "País *",
            current_names,
            index=None,
            placeholder="Digite para buscar ou cadastrar",
            accept_new_options=True,
            key="new_country_name",
        )
    if st.button("Salvar país", key="save_country", type="primary"):
        if not new_country_name:
            st.error("Informe o país.")
        else:
            try:
                repo.create_country(new_country_name, continent)
                st.success("País salvo.")
                st.rerun()
            except Exception as exc:
                st.error(f"Erro ao salvar: {exc}")
    st.dataframe(repo.countries_dataframe(), use_container_width=True, hide_index=True)
