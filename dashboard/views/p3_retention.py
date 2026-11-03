"""Page 3 · Retention Analysis: which new players leave first, and where the biggest drop is.

Segment rates and the engagement curve are recomputed live from the cached player
table (fct_game_players, 90K rows) with src.retention; the default views reuse the
catalog's takeaway sentences so the app and the report say the same thing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from common import (C, F, R, caveat, fmt_pct, how_to_read, load_cache, load_catalog_takeaways, load_results,
                    page_header, show, takeaway)

res = load_results()
ck = res["cookie"]
ov = ck["overall"]
no_d1 = next(r for r in ck["by_d1_status"] if r["d1_status"] == "Did not return Day 1")
TK = load_catalog_takeaways()

DIMS = {  # radio label -> (column, axis title, phrase used in chart titles)
    "Rounds played (first 14 days)": ("rounds_bucket", "Rounds played (bucket)", "rounds played in first 14 days"),
    "Came back on Day 1": ("d1_status", "Day-1 status", "whether the player returned on Day 1"),
    "Experiment version": ("version", "Version", "experiment version"),
}
METRICS = {"D1 and D7": ("retention_1", "retention_7"), "D7 only": ("retention_7",), "D1 only": ("retention_1",)}
LOW_BUCKETS = ("0", "1-4", "5-14")  # fewer than 15 rounds
BIN_ROUNDS, BINNED_UP_TO = 5, 150   # retention-by-rounds curve: 5-round bins up to 150, then one open bin


@st.cache_data(show_spinner=False)
def players() -> pd.DataFrame:
    p = load_cache("fct_game_players").copy()
    p["rounds_bucket"] = pd.Categorical(p["rounds_bucket"], C.ROUNDS_LABELS, ordered=True)
    return p


@st.cache_data(show_spinner=False)
def rates_by(dim: str) -> pd.DataFrame:
    return R.retention_rates(players(), dim)


@st.cache_data(show_spinner=False)
def curve(max_rounds: int, by_version: bool) -> pd.DataFrame:
    return R.engagement_curve(players(), max_rounds, by="version" if by_version else None)


def seg_name(dim: str, value) -> str:
    return f"{value} rounds" if dim == "rounds_bucket" else str(value)


def segment_takeaway(rates: pd.DataFrame, dim: str, metrics: tuple[str, ...]) -> str:
    parts = []
    for m in metrics:
        r = rates.sort_values(m)
        lo, hi = r.iloc[0], r.iloc[-1]
        parts.append(
            f"{F.METRIC_NAMES[m]} ranges from {lo[m] * 100:.1f}% ({seg_name(dim, lo[dim])}, "
            f"{lo['share_of_players'] * 100:.0f}% of players) to {hi[m] * 100:.1f}% ({seg_name(dim, hi[dim])}, "
            f"{hi['share_of_players'] * 100:.0f}% of players), a {(hi[m] - lo[m]) * 100:.1f} pp gap")
    return "; ".join(parts) + "."


# ------------------------------------------------------------------ header + KPIs
page_header("Retention Analysis", "Which new players leave first, and where is the biggest drop?")

by_rounds = rates_by("rounds_bucket")
low = by_rounds[by_rounds["rounds_bucket"].astype(str).isin(LOW_BUCKETS)]
k = st.columns(4)
k[0].metric("D1 retention", fmt_pct(ov["retention_1"], 1),
            f"95% CI {fmt_pct(ov['retention_1_ci_low'], 1)} to {fmt_pct(ov['retention_1_ci_high'], 1)}",
            delta_color="off", delta_arrow="off",
            help="Share of installs who played again on the day after install (Cookie Cats `retention_1`).")
k[1].metric("D7 retention", fmt_pct(ov["retention_7"], 1),
            f"95% CI {fmt_pct(ov['retention_7_ci_low'], 1)} to {fmt_pct(ov['retention_7_ci_high'], 1)}",
            delta_color="off", delta_arrow="off",
            help="Share of installs who played on day 7 after install (`retention_7`), whether or not they "
                 "played on Day 1.")
k[2].metric("Never back on Day 1", fmt_pct(1 - ov["retention_1"], 1),
            f"{no_d1['players']:,} players",
            delta_color="off", delta_arrow="off", help="Installs with no play on the day after install.")
k[3].metric("Installs with fewer than 15 rounds", fmt_pct(low["players"].sum() / len(players()), 0),
            f"D7 at most {fmt_pct(low['retention_7'].max(), 1)}", delta_color="off", delta_arrow="off",
            help="Share of installs with 0-14 rounds in their first 14 days, and the highest D7 retention among "
                 "those three buckets (0, 1-4, 5-14 rounds).")

# ------------------------------------------------------------------ where is the biggest drop?
st.subheader("Where is the biggest drop?")
show(F.fig_funnel(pd.DataFrame(ck["funnel"]), "New-player retention funnel (% of installs)",
                  "Each bar is the share of all installs that reached the step."))
takeaway(TK["ret_funnel"])

# ------------------------------------------------------------------ who leaves first? (live segmentation)
st.subheader("Who leaves first? Retention by segment")
c1, c2 = st.columns([2, 1], gap="large")
dim_label = c1.radio("Split new players by", list(DIMS), horizontal=True, key="p3_dimension")
met_label = c2.radio("Metric", list(METRICS), horizontal=True, key="p3_metric")
dim, seg_title, phrase = DIMS[dim_label]
metrics = METRICS[met_label]
if dim == "d1_status" and "retention_1" in metrics:
    metrics = ("retention_7",)
    st.caption("D1 retention is 0% or 100% by definition when players are split by Day-1 status, so only D7 is shown.")

rates = rates_by(dim)
title = f"{' and '.join(F.METRIC_NAMES[m].replace(' retention', '') for m in metrics)} retention by {phrase} (%)"
show(F.fig_retention_by_segment(rates, dim, title, "Bars: share of the segment's players retained; whiskers: 95% "
                                "Wilson interval; n under each label.", metrics=metrics, seg_title=seg_title))
if dim == "rounds_bucket" and metrics == ("retention_1", "retention_7"):
    takeaway(TK["ret_by_rounds_bucket"])
elif dim == "d1_status" and metrics == ("retention_7",):
    takeaway(TK["ret_by_d1"])
else:
    takeaway(segment_takeaway(rates, dim, metrics))

with st.expander("Show the numbers"):
    pct_cols = [c for c in rates.columns if c.startswith("retention") or c == "share_of_players"]
    tbl = rates.assign(**{c: rates[c] * 100 for c in pct_cols})
    tbl[dim] = tbl[dim].astype(str)
    pct = {"format": "%.1f%%"}
    st.dataframe(tbl, hide_index=True, width="stretch", column_config={
        dim: st.column_config.TextColumn(seg_title),
        "players": st.column_config.NumberColumn("Players", format="localized"),
        "share_of_players": st.column_config.NumberColumn("Share of players", **pct),
        "retention_1": st.column_config.NumberColumn("D1", **pct),
        "retention_1_ci_low": st.column_config.NumberColumn("D1 CI low", **pct),
        "retention_1_ci_high": st.column_config.NumberColumn("D1 CI high", **pct),
        "retention_7": st.column_config.NumberColumn("D7", **pct),
        "retention_7_ci_low": st.column_config.NumberColumn("D7 CI low", **pct),
        "retention_7_ci_high": st.column_config.NumberColumn("D7 CI high", **pct),
    })

show(F.fig_gap_by_dimension(pd.DataFrame(ck["gap_by_dimension"]),
                            "Which dimension separates D7 retention the most? (pp)",
                            "Best minus worst segment within each dimension."))
takeaway(TK["ret_gap_by_dimension"])

# ------------------------------------------------------------------ how far do players get?
st.subheader("How far do players get?")
s1, s2 = st.columns([3, 1], gap="large", vertical_alignment="bottom")
max_rounds = s1.slider("Show the curve up to N rounds", min_value=50, max_value=1000, value=200, step=50,
                       key="p3_max_rounds")
by_version = s2.toggle("Split by version", value=True, key="p3_split_version")
cv = curve(max_rounds, by_version)
show(F.fig_engagement_curve(cv, "Share of players reaching at least N rounds (%)",
                            "Read like a survival curve over game progress, not calendar time. Dotted lines: "
                            "the two gate positions."))
if (max_rounds, by_version) == (200, True):
    takeaway(TK["ret_engagement_curve"])
else:
    pl = players()["sum_gamerounds"]
    text = (f"Half of players stop before {int(pl.median())} rounds; {(pl >= 30).mean() * 100:.0f}% reach round 30, "
            f"{(pl >= 40).mean() * 100:.0f}% reach round 40 and {(pl >= max_rounds).mean() * 100:.1f}% reach round "
            f"{max_rounds}.")
    if by_version:
        wide = cv.pivot(index="rounds_at_least", columns="group", values="share_of_players")
        gap = (wide["gate_40"] - wide["gate_30"]).abs().max() * 100
        text += f" The two versions' curves are never more than {gap:.1f} pp apart up to {max_rounds} rounds."
    takeaway(text)

show(F.fig_retention_by_rounds(R.retention_by_rounds(players(), BINNED_UP_TO, BIN_ROUNDS),
                               f"Retention by rounds played (%, {BIN_ROUNDS}-round bins)",
                               f"Each point is a {BIN_ROUNDS}-round bin of players, placed at the bin's median round "
                               f"count; the last point pools everyone with {BINNED_UP_TO}+ rounds."))
takeaway(TK["ret_by_rounds_curve"])

caveat("Rounds are counted over each player's first 14 days, which overlaps the Day-7 window: a player who comes back "
       "on Day 7 has more days in which to play rounds. So 'more rounds, more retention' is correlation, not cause, "
       "and it cannot tell us that pushing players to play more would keep them. An experiment has to show that.")

st.markdown(
    f"**What we recommend (R6).** Focus retention work on the first session and Day 1: players with fewer than 15 "
    f"rounds are {low['players'].sum() / len(players()) * 100:.0f}% of installs and almost none of them come back. "
    "The Onboarding PM should run a Day-1 re-engagement or onboarding experiment aimed at them, with D7 retention as "
    "the primary metric, and size it with the calculator on page 7.")
try:
    st.page_link("views/p7_decision.py", label="Decision & Recommendations", icon=":material/arrow_forward:")
except StreamlitPageNotFoundError:  # page run on its own, outside the multipage app
    pass

how_to_read(f"""
**What this page is.** Retention for {int(ov['players']):,} new players of a mobile puzzle game (Cookie Cats):
how many come back the day after install (**D1**) and a week later (**D7**), and which kinds of players are lost
first.

**Funnel.** Each bar is the share of all installs that made it to a step. The biggest single drop is
between the first session and Day 1: {(1 - ov['retention_1']) * 100:.1f}% of new players never come back for a
second day. The last bar
counts players back on Day 1 *and* Day 7, so it is a bit lower than overall D7 retention, which also includes
players who skipped Day 1.

**Gap by dimension.** For three ways of splitting players, the bar is the difference in D7 retention
between the best and the worst group. A long bar means the split separates stayers from leavers well. Engagement
depth separates them by far the most; the experiment version barely matters.

**Segment explorer.** Choose how to split players and which metric to show. Bars are the share retained in each
group; the thin whiskers are the 95% interval (the plausible range for that group's true rate), and n is the group
size. Everything is recomputed from the player table when you change a control.

**Engagement curve.** For every round count N on the horizontal axis, the line shows the share of players who
played at least N rounds. It falls fast early on, which is where players are lost. The dotted lines mark the two
gate positions (level 30 and 40) from the experiment on page 6; the slider zooms out.

**Retention by rounds.** Players are grouped into {BIN_ROUNDS}-round bins; the lines show D1 and D7 retention per
bin.

**Common misreadings.**
- "Players who play more stay longer, so make them play more." The rounds are counted over 14 days, so players who
  stay longer *also* get more time to play. The link can run both ways; only an experiment can tell.
- "D7 retention is {ov['retention_7'] * 100:.1f}%, so {(1 - ov['retention_7']) * 100:.0f}% churned by day 7." Not
  exactly: D7 means *played on day 7*; a player can skip day 7 and come back later. The data has no later days.
- Small groups have wide whiskers; compare intervals, not just bar heights.
""")
