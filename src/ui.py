from __future__ import annotations

import streamlit as st


def apply_global_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 3rem;}
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.25);
            border-radius: 12px;
            padding: 14px 16px;
        }
        div[data-testid="stForm"] {
            border: 1px solid rgba(128,128,128,.25);
            border-radius: 12px;
            padding: 1rem;
        }
        .app-note {
            padding: .75rem 1rem;
            border-radius: 10px;
            border: 1px solid rgba(128,128,128,.25);
            opacity: .9;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_title(title: str, subtitle: str | None = None) -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)
