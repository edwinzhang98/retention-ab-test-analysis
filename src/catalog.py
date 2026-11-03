"""The figure catalog: every chart in the project with its default parameters
and a one-sentence takeaway computed from results.json.

Used by: reports/report.html (src/report.py), README PNGs (run.py), notebooks,
and as the default view of each Streamlit page. Dashboards re-call the same
builders in src/figures.py with user-chosen parameters.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from . import config as C
from . import figures as F
from . import retention as R
from . import stats as S


@dataclass
class Fig:
    key: str
    section: str
    fig: go.Figure
    takeaway: str


def load_caches() -> dict[str, pd.DataFrame]:
    p = C.PROCESSED_DIR
    return {
        "cells": pd.read_parquet(p / "agg_ad_cells.parquet"),
        "users": pd.read_parquet(p / "fct_ad_exposure_users.parquet"),
        "players": pd.read_parquet(p / "fct_game_players.parquet"),
        "boot_ad": pd.read_parquet(p / "boot_ad_lift.parquet"),
        "boot_gate": pd.read_parquet(p / "boot_gate_lift.parquet"),
    }


def pp(x: float, nd: int = 2) -> str:
    return f"{x*100:.{nd}f} pp"


def pct(x: float, nd: int = 1) -> str:
    return f"{x*100:.{nd}f}%"


def build_catalog(res: dict, caches: dict[str, pd.DataFrame]) -> dict[str, Fig]:
    out: dict[str, Fig] = {}
    ad, ck = res["ad"], res["cookie"]
    t = ad["test"]
    players = caches["players"].copy()
    players["rounds_bucket"] = pd.Categorical(players["rounds_bucket"], C.ROUNDS_LABELS, ordered=True)

    # ------------------------------------------------------------ retention
    funnel = pd.DataFrame(ck["funnel"])
    d1, d7 = ck["overall"]["retention_1"], ck["overall"]["retention_7"]
    f_ = funnel.set_index("step")["share_of_installs"]
    tk = (f"{pct(1 - d1)} of new players don't come back on Day 1 and only {pct(d7)} are back on Day 7; "
          f"the largest absolute loss ({(f_.iloc[1] - f_.iloc[2])*100:.0f} pp of installs) is between the first session and Day 1.")
    out["ret_funnel"] = Fig("ret_funnel", "retention", F.fig_funnel(
        funnel, "New-player retention funnel (% of installs)", tk), tk)

    by_rounds = R.retention_rates(players, "rounds_bucket")
    low = by_rounds[by_rounds["rounds_bucket"].astype(str).isin(["0", "1-4", "5-14"])]
    share_low = low["players"].sum() / len(players)
    tk = (f"Players with < 15 rounds are {pct(share_low, 0)} of installs and almost none are back on Day 7 "
          f"(≤ {pct(low['retention_7'].max())}); retention climbs steeply with engagement depth.")
    out["ret_by_rounds_bucket"] = Fig("ret_by_rounds_bucket", "retention", F.fig_retention_by_segment(
        by_rounds, "rounds_bucket", "D1 and D7 retention by rounds played in first 14 days (%)", tk,
        seg_title="Rounds played (bucket)"), tk)

    by_d1 = R.retention_rates(players, "d1_status")
    r_yes = by_d1.loc[by_d1.d1_status == "Returned Day 1", "retention_7"].iloc[0]
    r_no = by_d1.loc[by_d1.d1_status == "Did not return Day 1", "retention_7"].iloc[0]
    tk = (f"Players who return on Day 1 are {r_yes / r_no:.1f}× as likely to be back on Day 7 "
          f"({pct(r_yes)} vs {pct(r_no)}): Day 1 is the first moment to win.")
    out["ret_by_d1"] = Fig("ret_by_d1", "retention", F.fig_retention_by_segment(
        by_d1, "d1_status", "D7 retention by whether the player returned on Day 1 (%)", tk,
        metrics=("retention_7",), seg_title="Day-1 status"), tk)

    curve = R.engagement_curve(players, 200, by="version")
    share30 = (players["sum_gamerounds"] >= 30).mean()
    tk = (f"Half of players stop before {int(players['sum_gamerounds'].median())} rounds and only "
          f"{pct(share30, 0)} reach round 30, so the gate only touches a minority of installs.")
    out["ret_engagement_curve"] = Fig("ret_engagement_curve", "retention", F.fig_engagement_curve(
        curve, "Share of players reaching at least N rounds (%)", tk), tk)

    by_r = R.retention_by_rounds(players, 150, 5)
    tk = "D7 retention rises almost linearly with play depth up to ~100 rounds; this is correlation, not cause."
    out["ret_by_rounds_curve"] = Fig("ret_by_rounds_curve", "retention", F.fig_retention_by_rounds(
        by_r, "Retention by rounds played (%, 5-round bins)", tk), tk)

    gaps = pd.DataFrame(ck["gap_by_dimension"])
    top = gaps.iloc[0]
    tk = (f"{top['dimension']} separates players most ({top['gap_pp']:.0f} pp D7 gap); "
          f"the experiment version barely matters ({gaps.iloc[-1]['gap_pp']:.1f} pp).")
    out["ret_gap_by_dimension"] = Fig("ret_gap_by_dimension", "retention", F.fig_gap_by_dimension(
        gaps, "Which dimension separates D7 retention the most? (pp)", tk), tk)

    # ------------------------------------------------------------ ad experiment
    arms = F.arm_table(t["conv_t"], t["n_t"], t["conv_c"], t["n_c"])
    tk = (f"Users shown ads converted at {pct(t['rate_t'], 2)} vs {pct(t['rate_c'], 2)} for PSA: "
          f"+{pp(t['abs_lift'])} (95% CI {pp(t['abs_ci_low'])} to {pp(t['abs_ci_high'])}), "
          f"a {pct(t['rel_lift'], 0)} relative lift.")
    out["ad_rates"] = Fig("ad_rates", "experiment", F.fig_arm_rates(
        arms, "Conversion rate by experiment arm (%, 95% CI)", tk), tk)

    b = ad["bootstrap"]
    tk = (f"None of {b['n_boot']:,} bootstrap resamples shows a lift ≤ 0; the 95% interval is "
          f"{pp(b['abs_ci'][0])} to {pp(b['abs_ci'][1])}, matching the analytic CI.")
    out["ad_bootstrap"] = Fig("ad_bootstrap", "experiment", F.fig_bootstrap(
        caches["boot_ad"]["abs_lift"].to_numpy(), tuple(b["abs_ci"]), t["abs_lift"],
        "Bootstrap distribution of the ad lift (pp, 10,000 resamples)", tk), tk)

    pw = ad["power"]
    tk = (f"With a 96/4 split we could only detect lifts ≥ {pp(pw['mde_current']['mde_abs'])}; the same "
          f"588K users split 50/50 would detect {pp(pw['mde_if_5050_same_total']['mde_abs'])}. "
          f"The observed {pp(t['abs_lift'])} clears both.")
    out["ad_mde_split"] = Fig("ad_mde_split", "experiment", F.fig_mde_by_split(
        t["rate_c"], t["n_t"] + t["n_c"], C.INTENDED_AD_SHARE, t["abs_lift"], C.ALPHA, C.POWER,
        "Minimum detectable lift vs. share of users in treatment (pp)", tk), tk)

    tk = (f"This sample has 80% power for a true lift of {pp(pw['mde_current']['mde_abs'])}; a lift the size "
          f"of the observed {pp(t['abs_lift'])} would be detected essentially every time "
          f"(power {pct(pw['achieved_power_at_observed'], 0)}).")
    out["ad_power_curve"] = Fig("ad_power_curve", "experiment", F.fig_power_curve(
        t["rate_c"], t["n_t"], t["n_c"], C.ALPHA, t["abs_lift"], "Power to detect a true lift, current sample (%)",
        tk), tk)

    bz = ad["business"]
    inc = bz["incremental_conversions"]
    tk = (f"≈{inc['point']:,.0f} incremental conversions (95% CI {inc['ci_low']:,.0f}–{inc['ci_high']:,.0f}) over "
          f"{bz['impressions_ad_group']/1e6:.1f}M impressions: at ${bz['value_per_conversion_usd']:.0f} per conversion "
          f"(assumed) the campaign breaks even below ${bz['breakeven_cpm_usd']['point']:.2f} CPM.")
    out["ad_breakeven"] = Fig("ad_breakeven", "experiment", F.fig_breakeven(
        inc["point"], inc["ci_low"], inc["ci_high"], bz["impressions_ad_group"], bz["value_per_conversion_usd"],
        None, "Breakeven CPM by value per conversion (USD)", tk), tk)

    users = caches["users"]
    bal = {x["variable"]: x for x in ad["balance"]}
    tk = (f"Arms differ slightly in peak ad day (Cramér's V {bal['most_ads_day']['cramers_v']:.3f}); "
          f"these are post-assignment fields, so segment results are exploratory.")
    out["ad_balance_day"] = Fig("ad_balance_day", "sanity", F.fig_balance(
        users, "most_ads_day", "Peak ad day: share of each arm's users (%)", tk, order=C.DAY_ORDER), tk)
    tk = (f"Ad volume per user is near-identical (mean {ad['groups']['ad']['mean_ads']:.1f} vs "
          f"{ad['groups']['psa']['mean_ads']:.1f}), though the shape differs a little (Cramér's V "
          f"{bal['exposure_bucket']['cramers_v']:.3f}).")
    out["ad_balance_exposure"] = Fig("ad_balance_exposure", "sanity", F.fig_balance(
        users, "exposure_bucket", "Total ads seen: share of each arm's users (%)", tk,
        order=C.EXPOSURE_LABELS, xtitle="Total ads seen (bucket)"), tk)

    # ------------------------------------------------------------ heterogeneity
    cells = caches["cells"]
    het = ad["heterogeneity"]
    day = S.segment_lifts(cells, "most_ads_day", "ad", "psa", alpha=C.ALPHA, method="holm", order=C.DAY_ORDER)
    hd = het["most_ads_day"]
    tk = (f"Lift ranges from {hd['min_lift_pp']:.2f} pp ({hd['min_lift_segment']}) to {hd['max_lift_pp']:.2f} pp "
          f"({hd['max_lift_segment']}); interaction test p = {hd['lrt']['p_value']:.3f}: weak evidence of a real "
          f"day effect, not enough to re-plan spend.")
    out["het_day"] = Fig("het_day", "heterogeneity", F.fig_lift_forest(
        day, "most_ads_day", "Ad lift by peak ad day (pp, 95% CI, Holm-adjusted significance)", tk,
        overall_lift=t["abs_lift"], seg_title="Day with most ads"), tk)

    hour = S.segment_lifts(cells, "most_ads_hour", "ad", "psa", alpha=C.ALPHA, method="holm", order=list(range(24)))
    hh = het["most_ads_hour"]
    tk = (f"{hh['n_sig_unadjusted']} of 24 hours look 'significant' unadjusted but only {hh['n_sig_holm']} "
          f"{'survives' if hh['n_sig_holm'] == 1 else 'survive'} Holm correction; interaction test p = {hh['lrt']['p_value']:.2f}: no evidence lift differs by hour.")
    out["het_hour"] = Fig("het_hour", "heterogeneity", F.fig_lift_forest(
        hour, "most_ads_hour", "Ad lift by peak ad hour (pp, 95% CI, Holm-adjusted significance)", tk,
        overall_lift=t["abs_lift"], seg_title="Hour with most ads (0–23)"), tk)

    expo = S.segment_lifts(cells, "exposure_bucket", "ad", "psa", alpha=C.ALPHA, method="holm",
                           order=C.EXPOSURE_LABELS)
    e = expo.set_index("exposure_bucket")
    tk = (f"Lift is ~0 for users who saw ≤ 20 ads, reaches {e.loc['51-100', 'abs_lift']*100:.1f}–"
          f"{e.loc['101-200', 'abs_lift']*100:.1f} pp at 51–200 ads, and is indistinguishable from 0 past 200 "
          f"(only {int(e.loc['200+', 'n_c'])} control users). Exposure is post-assignment: a hypothesis, not a result.")
    out["het_exposure"] = Fig("het_exposure", "heterogeneity", F.fig_dose_response(
        expo, "Conversion rate by total ads seen, ad vs PSA (%)", tk), tk)
    out["het_exposure_forest"] = Fig("het_exposure_forest", "heterogeneity", F.fig_lift_forest(
        expo, "exposure_bucket", "Ad lift by total ads seen (pp, 95% CI, Holm-adjusted significance)", tk,
        overall_lift=t["abs_lift"], seg_title="Total ads seen (bucket)"), tk)

    # ------------------------------------------------------------ gate experiment
    g = ck["gate"]
    g7, g1 = g["retention_7"], g["retention_1"]
    tk = (f"gate_40 has lower D7 retention ({pct(g7['rate_t'], 2)} vs {pct(g7['rate_c'], 2)}, "
          f"{g7['abs_lift']*100:+.2f} pp, 95% CI {pp(g7['abs_ci_low'])} to {pp(g7['abs_ci_high'])}); "
          f"D1 is directionally lower too.")
    out["gate_rates"] = Fig("gate_rates", "gate", F.fig_gate_rates(
        g, "D1 and D7 retention by gate version (%, 95% CI)", tk), tk)
    tk = (f"{pct(1 - g7['boot_share_ge_0'], 1)} of bootstrap draws put gate_40's D7 below gate_30; for D1 it is "
          f"{pct(1 - g1['boot_share_ge_0'], 1)}. The D7 drop is consistent, the D1 drop is not conclusive.")
    out["gate_bootstrap"] = Fig("gate_bootstrap", "gate", F.fig_gate_bootstrap(
        caches["boot_gate"], g, "Bootstrap distribution of gate_40 − gate_30 retention (pp)", tk), tk)

    return out


def save_pngs(cat: dict[str, Fig], scale: float = 2.0) -> list[str]:
    """Static PNGs for README / markdown docs."""
    C.FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, f in cat.items():
        p = C.FIG_DIR / f"{k}.png"
        f.fig.write_image(p, width=1000, height=int(f.fig.layout.height or 420), scale=scale)
        paths.append(str(p))
    return paths
