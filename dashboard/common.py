"""Shared helpers for every dashboard page: cached data loading and the
standard page frame (question on top, takeaway under each chart, a
"How to read this" expander at the bottom).

Pages only READ caches built by `python run.py --only analysis`; nothing is
recomputed from raw data on page load.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config as C  # noqa: E402
from src import figures as F  # noqa: E402,F401  (re-exported for pages)
from src import retention as R  # noqa: E402,F401
from src import stats as S  # noqa: E402,F401


def _require(path: Path) -> None:
    if not path.exists():
        st.error(f"Missing cache `{path.relative_to(ROOT)}`. Run `python run.py --only analysis` first "
                 "(see README → How to run).")
        st.stop()


@st.cache_data(show_spinner=False)
def load_results() -> dict:
    _require(C.RESULTS_JSON)
    with open(C.RESULTS_JSON) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_cache(name: str) -> pd.DataFrame:
    """name: agg_ad_cells | fct_ad_exposure_users | fct_game_players | boot_ad_lift | boot_gate_lift"""
    path = C.PROCESSED_DIR / f"{name}.parquet"
    _require(path)
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_catalog_takeaways() -> dict[str, str]:
    """Default takeaway sentences (same text as report.html)."""
    from src.catalog import build_catalog
    caches = {"cells": load_cache("agg_ad_cells"), "users": load_cache("fct_ad_exposure_users"),
              "players": load_cache("fct_game_players"), "boot_ad": load_cache("boot_ad_lift"),
              "boot_gate": load_cache("boot_gate_lift")}
    return {k: v.takeaway for k, v in build_catalog(load_results(), caches).items()}


# ------------------------------------------------------------------ page frame
def page_header(title: str, question: str) -> None:
    """Page title + the one-sentence question this page answers."""
    st.title(title)
    st.markdown(f"<div class='page-question'><b>Question this page answers:</b> {question}</div>",
                unsafe_allow_html=True)


def show(fig, key: str | None = None) -> None:
    """Render a Plotly figure from src/figures.py with the project styling (not Streamlit's theme)."""
    st.plotly_chart(fig, width="stretch", theme=None, key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def takeaway(text: str) -> None:
    st.markdown(f"<div class='takeaway'>→ {text}</div>", unsafe_allow_html=True)


def how_to_read(markdown_text: str) -> None:
    """Plain-language explainer at the bottom of every page."""
    st.divider()
    with st.expander("How to read this", expanded=False):
        st.markdown(markdown_text)


def fmt_pp(x: float, nd: int = 2) -> str:
    return f"{x * 100:+.{nd}f} pp"


def fmt_pct(x: float, nd: int = 2) -> str:
    return f"{x * 100:.{nd}f}%"


# ------------------------------------------------------------------ prose formatting (true minus "−")
def sgn(x: float, nd: int = 2) -> str:
    """Always signed, with a true minus for prose: +0.77 / −0.82 (fmt_pp keeps the hyphen-minus)."""
    return f"{x:+.{nd}f}".replace("-", "−")


def num(x: float, nd: int = 2) -> str:
    """Fixed decimals, true minus for negatives, no plus sign: 0.59 / −1.33."""
    return f"{x:.{nd}f}".replace("-", "−")


def sgn_pp(x: float, nd: int = 2) -> str:
    """A proportion as signed percentage points with a true minus: -0.0082 -> '−0.82 pp'."""
    return f"{sgn(x * 100, nd)} pp"


def ci_text(lo: float, hi: float, nd: int = 2, signed: bool = True, unit: str = " pp") -> str:
    """'95% CI −0.71 to +0.07 pp' from two proportions (x 100); signed=False drops the plus signs."""
    f = sgn if signed else num
    return f"95% CI {f(lo * 100, nd)} to {f(hi * 100, nd)}{unit}"


def p_text(p: float) -> str:
    """p-value for sentences: two significant digits ('p = 0.0086', 'p = 0.18'); never a zero p-value."""
    if p < 1e-4:
        return "p < 0.0001"
    if p < 1e-3 or p >= 0.995:
        return f"p = {p:.4f}"
    return f"p = {p:.2g}"


def approx(x: float, to: int = 100) -> str:
    """Rounded count for prose: 4342.98 -> '4,300' (prefix '≈' at the call site)."""
    return f"{round(x / to) * to:,.0f}"


CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1200px;}
  h1 {font-size: 1.75rem !important; font-weight: 650 !important;}
  h2, h3 {font-weight: 600 !important;}
  .page-question {background:#f6f6f4; border-left:3px solid #2a78d6; padding:.6rem .9rem;
                  margin:.2rem 0 1.1rem 0; color:#1f1f1d; font-size:0.98rem;}
  .takeaway {color:#52514e; font-size:0.93rem; margin:-.4rem 0 1.2rem 0;}
  .caveat {background:#fff8e6; border-left:3px solid #eda100; padding:.55rem .85rem; font-size:.92rem;
           margin:.4rem 0 1rem 0;}
  div[data-testid="stMetric"] {background:#fafaf9; border:1px solid #ecebe7; border-radius:6px;
                               padding:.6rem .8rem;}
  @media (max-width: 640px) {
    [data-testid="stMarkdownContainer"] table {display:block; overflow-x:auto; max-width:100%;}
  }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def caveat(text: str) -> None:
    st.markdown(f"<div class='caveat'>⚠︎ {text}</div>", unsafe_allow_html=True)
