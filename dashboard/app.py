"""Growth experiment readout — Streamlit demo app.

Run from the repo root:  streamlit run dashboard/app.py
Pages are ordered as the presentation storyline.
"""
from __future__ import annotations

import streamlit as st

from common import inject_css

st.set_page_config(page_title="Growth Experiment Readout", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
inject_css()

pages = [
    st.Page("views/p1_overview.py", title="1 · Overview", default=True, url_path="overview"),
    st.Page("views/p2_data_sanity.py", title="2 · Data & Sanity Checks", url_path="data-sanity"),
    st.Page("views/p3_retention.py", title="3 · Retention Analysis", url_path="retention"),
    st.Page("views/p4_experiment_readout.py", title="4 · Experiment Readout: Ad vs PSA", url_path="experiment"),
    st.Page("views/p5_heterogeneity.py", title="5 · Heterogeneity by Day / Hour", url_path="heterogeneity"),
    st.Page("views/p6_gate_experiment.py", title="6 · Gate Experiment (Cookie Cats)", url_path="gate"),
    st.Page("views/p7_decision.py", title="7 · Decision & Recommendations", url_path="decision"),
]
pg = st.navigation(pages, position="sidebar")
with st.sidebar:
    st.caption("Growth · Product Analytics\n\nAd campaign experiment + new-player retention readout. "
               "Pages follow the presentation order.")
pg.run()
