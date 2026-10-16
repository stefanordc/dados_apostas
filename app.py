from __future__ import annotations

import streamlit as st

from src.ui import apply_global_style

st.set_page_config(
    page_title="Backtest Apostas",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_global_style()

pages = [
    st.Page("pages/cadastros.py", title="Cadastros", default=True),
    st.Page("pages/historico_jogos.py", title="Histórico de jogos"),
]

navigation = st.navigation(pages)
navigation.run()
