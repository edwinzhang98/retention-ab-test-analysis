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


def num(x: float, nd: int = 2) -> str:
    """Fixed decimals with a true minus sign (matches the report text)."""
    return f"{x:.{nd}f}".replace("-", "−")


def sgn(x: float, nd: int = 2) -> str:
    """Always signed, true minus: +0.77 / −0.82."""
    return f"{x:+.{nd}f}".replace("-", "−")


def fmt_p(p: float) -> str:
    """Human-readable p-value, two significant digits (0.18, 0.0086, 0.013); never prints 0."""
    if p < 0.0001:
        return "p < 0.0001"
    if p < 0.001:
        return f"p = {p:.4f}"
    if p > 0.99:
        return "p > 0.99"
    return f"p = {p:.2g}"


def pct_power(x: float) -> str:
    """Power as a percentage; values that round to 100 are shown as ≈100%."""
    return "≈100%" if x >= 0.995 else pct(x, 0)


def hour_ranges(hours: list[int]) -> str:
    """[0, 1, 2, 4, 5, 6] -> '0–2 and 4–6'."""
    hours = sorted(int(h) for h in hours)
    runs, start = [], None
    for i, h in enumerate(hours):
        if start is None:
            start = h
        if i == len(hours) - 1 or hours[i + 1] != h + 1:
            runs.append(f"{start}–{h}" if h != start else f"{h}")
            start = None
    return runs[0] if len(runs) == 1 else ", ".join(runs[:-1]) + " and " + runs[-1]


def usd(x: float, nd: int = 2) -> str:
    return f"USD {x:,.{nd}f}"


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
    tk = (f"{pct(1 - d1)} of new players don't come back on Day 1; {pct(d7)} play on Day 7 "
          f"({pct(f_.iloc[3])} on both Day 1 and Day 7). The largest absolute loss "
          f"({(f_.iloc[1] - f_.iloc[2])*100:.0f} pp of installs) is between the first session and Day 1.")
    out["ret_funnel"] = Fig("ret_funnel", "retention", F.fig_funnel(
        funnel, "New-player retention funnel (% of installs)", tk), tk)

    by_rounds = R.retention_rates(players, "rounds_bucket")
    early = ck["early_churn_segment"]
    tk = (f"Players with < 15 rounds in 14 days are {pct(early['share_of_installs'], 0)} of installs and only "
          f"{pct(early['retention_7'])} of them are back on Day 7. Rounds are counted through day 14, so this sizes the "
          f"early-churn segment; it is not a Day-0 targeting rule.")
    out["ret_by_rounds_bucket"] = Fig("ret_by_rounds_bucket", "retention", F.fig_retention_by_segment(
        by_rounds, "rounds_bucket", "D1 and D7 retention by rounds played in first 14 days (%)", tk,
        seg_title="Rounds played (bucket)"), tk)

    by_d1 = R.retention_rates(players, "d1_status")
    r_yes = by_d1.loc[by_d1.d1_status == "Returned Day 1", "retention_7"].iloc[0]
    r_no = by_d1.loc[by_d1.d1_status == "Did not return Day 1", "retention_7"].iloc[0]
    tk = (f"Players who return on Day 1 are {r_yes / r_no:.1f}× as likely to play on Day 7 ({pct(r_yes)} vs {pct(r_no)}). "
          f"Day-1 return is the earliest strong signal of who stays; it does not prove that prompting a Day-1 visit would lift D7.")
    out["ret_by_d1"] = Fig("ret_by_d1", "retention", F.fig_retention_by_segment(
        by_d1, "d1_status", "D7 retention by whether the player returned on Day 1 (%)", tk,
        metrics=("retention_7",), seg_title="Day-1 status"), tk)

    curve = R.engagement_curve(players, 200, by="version")
    share30 = (players["sum_gamerounds"] >= 30).mean()
    tk = (f"Half of players play {int(players['sum_gamerounds'].median())} rounds or fewer; only {pct(share30, 0)} played "
          f"≥ 30 rounds, so at most ~{pct(share30, 0)} of installs could have met the level-30 gate.")
    out["ret_engagement_curve"] = Fig("ret_engagement_curve", "retention", F.fig_engagement_curve(
        curve, "Share of players reaching at least N rounds (%)", tk), tk)

    by_r = R.retention_by_rounds(players, 150, 5)
    tk = ("D7 retention rises steadily with rounds played up to ~100 rounds. Rounds are counted over 14 days, so players "
          "who come back on day 7 mechanically log more rounds: descriptive, not causal.")
    out["ret_by_rounds_curve"] = Fig("ret_by_rounds_curve", "retention", F.fig_retention_by_rounds(
        by_r, "Retention by rounds played (%, 5-round bins)", tk), tk)

    gaps = pd.DataFrame(ck["gap_by_dimension"])
    top, ver = gaps.iloc[0], gaps[gaps["column"] == "version"].iloc[0]
    could_be_gate = abs(ck["gate"]["d7_decomposition"]["within_reached_30"]) * 100
    tk = (f"Engagement depth separates D7 most ({top['gap_pp']:.0f} pp across {int(top['n_segments'])} buckets, partly by "
          f"construction). The two gate versions differ by {ver['gap_pp']:.1f} pp raw, of which only about "
          f"{could_be_gate:.1f} pp could be the gate (not certified): a minor lever next to engagement.")
    out["ret_gap_by_dimension"] = Fig("ret_gap_by_dimension", "retention", F.fig_gap_by_dimension(
        gaps, "Which dimension separates D7 retention the most? (pp, best − worst segment)", tk), tk)

    # ------------------------------------------------------------ ad experiment
    arms = F.arm_table(t["conv_t"], t["n_t"], t["conv_c"], t["n_c"])
    tk = (f"Users shown ads converted at {pct(t['rate_t'], 2)} vs {pct(t['rate_c'], 2)} for PSA: "
          f"+{pp(t['abs_lift'])} (95% CI {pp(t['abs_ci_low'])} to {pp(t['abs_ci_high'])}), "
          f"a {pct(t['rel_lift'], 0)} relative lift ({fmt_p(t['p_value'])}).")
    out["ad_rates"] = Fig("ad_rates", "experiment", F.fig_arm_rates(
        arms, "Conversion rate by experiment arm (%, 95% CI)", tk), tk)

    b = ad["bootstrap"]
    tk = (f"The bootstrap interval ({pp(b['abs_ci'][0])} to {pp(b['abs_ci'][1])}) matches the analytic interval "
          f"({pp(t['abs_ci_low'])} to {pp(t['abs_ci_high'])}): with this many users the normal approximation is fine.")
    out["ad_bootstrap"] = Fig("ad_bootstrap", "experiment", F.fig_bootstrap(
        caches["boot_ad"]["abs_lift"].to_numpy(), tuple(b["abs_ci"]), t["abs_lift"],
        f"Bootstrap distribution of the ad lift (pp, {b['n_boot']:,} resamples)", tk), tk)

    pw = ad["power"]
    ses = pw["power_at_relative_lift"][str(pw["smallest_lift_of_interest_rel"])]
    tk = (f"At 96/4 the test had 80% power only for lifts ≥ {pp(pw['mde_current']['mde_abs'])} "
          f"({pct(pw['mde_current']['mde_rel'], 0)} relative); the same {(t['n_t'] + t['n_c'])/1000:,.0f}K users split 50/50 "
          f"would detect {pp(pw['mde_if_5050_same_total']['mde_abs'])}. For the smallest lift worth acting on "
          f"({pct(ses['rel'], 0)} relative = {pp(ses['abs'])}), power was {pct(ses['power_current_split'], 0)} at 96/4 vs "
          f"{pct_power(ses['power_5050_same_total'])} at 50/50.")
    out["ad_mde_split"] = Fig("ad_mde_split", "experiment", F.fig_mde_by_split(
        t["rate_c"], t["n_t"] + t["n_c"], C.INTENDED_AD_SHARE, ses["abs"], C.ALPHA, C.POWER,
        "Minimum detectable lift vs. share of users in treatment (pp)", tk), tk)

    tk = (f"80% power for a true lift ≥ {pp(pw['mde_current']['mde_abs'])}; for the smallest lift we'd act on "
          f"({pct(ses['rel'], 0)} relative = {pp(ses['abs'])}) this design had only {pct(ses['power_current_split'], 0)} power. "
          f"Power describes the design; it is not evaluated at the observed effect.")
    out["ad_power_curve"] = Fig("ad_power_curve", "experiment", F.fig_power_curve(
        t["rate_c"], t["n_t"], t["n_c"], C.ALPHA, ses["abs"], "Power to detect a true lift, current sample (%)",
        tk, max_lift_pp=0.6), tk)

    bz = ad["business"]
    inc = bz["incremental_conversions"]
    r100 = lambda x: f"{round(x, -2):,.0f}"
    tk = (f"≈{r100(inc['point'])} incremental conversions (95% CI {r100(inc['ci_low'])}–{r100(inc['ci_high'])}), only "
          f"{pct(bz['share_of_ad_conversions_incremental'], 0)} of ad-arm conversions, so last-touch attribution would "
          f"overstate the campaign {bz['last_touch_overstatement_x']:.1f}× (95% CI {bz['last_touch_overstatement_ci'][0]:.1f}–"
          f"{bz['last_touch_overstatement_ci'][1]:.1f}×). At {usd(bz['value_per_conversion_usd'], 0)} per "
          f"conversion (assumed) it breaks even below {usd(bz['breakeven_cpm_usd']['point'])} CPM.")
    out["ad_breakeven"] = Fig("ad_breakeven", "experiment", F.fig_breakeven(
        inc["point"], inc["ci_low"], inc["ci_high"], bz["impressions_ad_group"], bz["value_per_conversion_usd"],
        None, "Breakeven CPM by value per conversion (USD)", tk), tk)

    users = caches["users"]
    bal = {x["variable"]: x for x in ad["balance"]}
    tk = (f"Arms differ slightly in peak ad day (Cramér's V {bal['most_ads_day']['cramers_v']:.3f}); peak day/hour are "
          f"recorded after assignment, so segment results are exploratory.")
    out["ad_balance_day"] = Fig("ad_balance_day", "sanity", F.fig_balance(
        users, "most_ads_day", "Peak ad day: share of each arm's users (%)", tk, order=C.DAY_ORDER), tk)
    sh = ad["heterogeneity"]["exposure_bucket"]["arm_shares"]
    tk = (f"Mean ads per user match ({ad['groups']['ad']['mean_ads']:.1f} vs {ad['groups']['psa']['mean_ads']:.1f}) but the "
          f"shapes differ: {pct(sh['1-5']['psa'], 0)} of PSA users vs {pct(sh['1-5']['ad'], 0)} of ad users saw 1–5 ads; "
          f"{pct(sh['11-20']['psa'], 0)} vs {pct(sh['11-20']['ad'], 0)} saw 11–20. Exposure is shaped after assignment, "
          f"so it stays an exploratory cut, never a covariate.")
    out["ad_balance_exposure"] = Fig("ad_balance_exposure", "sanity", F.fig_balance(
        users, "exposure_bucket", "Total ads seen: share of each arm's users (%)", tk,
        order=C.EXPOSURE_LABELS, xtitle="Total ads seen (bucket)"), tk)

    # ------------------------------------------------------------ heterogeneity
    cells = caches["cells"]
    het = ad["heterogeneity"]
    day = S.segment_lifts(cells, "most_ads_day", "ad", "psa", alpha=C.ALPHA, method="holm", order=C.DAY_ORDER)
    hd = het["most_ads_day"]
    dd = day.set_index("most_ads_day")
    tk = (f"Lift differs by peak day (interaction {fmt_p(hd['lrt']['p_value'])}; {fmt_p(hd['lrt_p_bonferroni_3_dims'])} after "
          f"allowing for 3 dimensions explored): Tuesday-peak users {sgn(dd.loc['Tuesday', 'abs_lift']*100)} pp "
          f"({sgn(dd.loc['Tuesday', 'diff_vs_rest']*100)} pp vs other days), Thursday-peak users "
          f"{sgn(dd.loc['Thursday', 'abs_lift']*100)} pp ({sgn(dd.loc['Thursday', 'diff_vs_rest']*100)} pp); both survive "
          f"Holm. 'Peak day' describes the user, not a slot we can buy, so this motivates a randomized delivery-schedule "
          f"test, not a reallocation.")
    out["het_day"] = Fig("het_day", "heterogeneity", F.fig_lift_forest(
        day, "most_ads_day", "Ad lift by peak ad day (pp, 95% CI; filled = differs from other days, Holm)", tk,
        overall_lift=t["abs_lift"], seg_title="Day with most ads"), tk)

    hour = S.segment_lifts(cells, "most_ads_hour", "ad", "psa", alpha=C.ALPHA, method="holm", order=list(range(24)))
    hh = het["most_ads_hour"]
    zero_h = hour.loc[hour["conv_c"] == 0, "most_ads_hour"].astype(int).tolist()
    tk = (f"No evidence that lift differs by hour (interaction {fmt_p(hh['lrt']['p_value'])}); no hour differs from "
          f"the others after correction. {len(zero_h)} hours ({hour_ranges(zero_h)}, mostly night) have zero control "
          f"conversions, so hourly estimates there are unreliable.")
    out["het_hour"] = Fig("het_hour", "heterogeneity", F.fig_lift_forest(
        hour, "most_ads_hour", "Ad lift by peak ad hour (pp, 95% CI; filled = differs from other hours, Holm)", tk,
        overall_lift=t["abs_lift"], seg_title="Hour with most ads (0–23)"), tk)

    dp = S.segment_lifts(cells, "daypart", "ad", "psa", alpha=C.ALPHA, method="holm", order=C.DAYPART_ORDER)
    hp = het["daypart"]
    nc_ = hp["night_counts"]["psa"]
    tk = (f"Grouped into dayparts the interaction test gives {fmt_p(hp['lrt']['p_value'])}, driven entirely by Night (0–5), "
          f"where the control arm has {nc_['conversions']} conversion among {nc_['users']:,} users; without it, "
          f"{fmt_p(hp['lrt_excluding_night']['p_value'])}. No reliable time-of-day pattern.")
    out["het_daypart"] = Fig("het_daypart", "heterogeneity", F.fig_lift_forest(
        dp, "daypart", "Ad lift by daypart of peak exposure (pp, 95% CI; filled = differs from other dayparts, Holm)", tk,
        overall_lift=t["abs_lift"], seg_title="Daypart (hour with most ads)"), tk)

    expo = S.segment_lifts(cells, "exposure_bucket", "ad", "psa", alpha=C.ALPHA, method="holm",
                           order=C.EXPOSURE_LABELS)
    e = expo.set_index("exposure_bucket")
    con = het["exposure_bucket"]["concentration"]
    le20 = con["le_20_ads_pooled"]
    tk = (f"The {pct(con['share_users_le_20_ads'], 0)} of users who saw ≤ 20 ads show no lift we could measure "
          f"({sgn(le20['abs_lift']*100)} pp; a lift above {num(le20['mde_abs']*100)} pp would have shown). At 36–200 ads the "
          f"lift is {e.loc['36-50', 'abs_lift']*100:.1f}–{e.loc['101-200', 'abs_lift']*100:.1f} pp: these buckets hold "
          f"{pct(con['share_ad_users_36_200'], 0)} of ad users and {pct(con['share_incremental_conversions_36_200'], 0)} of the "
          f"bucket-by-bucket incremental conversions. No usable estimate past 200 ads (CI {num(con['top_bucket_ci_pp'][0], 1)} "
          f"to {sgn(con['top_bucket_ci_pp'][1], 1)} pp, {con['top_bucket_control_users']} control users). Exposure tracks how "
          f"active a user is (control conversion rises from {pct(con['control_rate_lowest_bucket'])} to "
          f"{pct(con['control_rate_highest_bucket'])}): the lift lives in heavy users; this is not a frequency curve.")
    out["het_exposure"] = Fig("het_exposure", "heterogeneity", F.fig_dose_response(
        expo, "Conversion rate by total ads seen, ad vs PSA (%)", tk), tk)
    tk = (f"Seen as lifts: buckets up to 35 ads sit near 0 and 36–200 well above the overall {pp(t['abs_lift'])}; "
          f"{het['exposure_bucket']['differs_from_rest']['holm']} of 8 buckets differ from the rest after Holm. "
          f"Exploratory: exposure is recorded after assignment.")
    out["het_exposure_forest"] = Fig("het_exposure_forest", "heterogeneity", F.fig_lift_forest(
        expo, "exposure_bucket", "Ad lift by total ads seen (pp, 95% CI; filled = differs from other buckets, Holm)", tk,
        overall_lift=t["abs_lift"], seg_title="Total ads seen (bucket)"), tk)

    # ------------------------------------------------------------ gate experiment
    g = ck["gate"]
    g7, g1 = g["retention_7"], g["retention_1"]
    tk = (f"Naive comparison: gate_40 D7 {pct(g7['rate_t'], 2)} vs {pct(g7['rate_c'], 2)} "
          f"({sgn(g7['abs_lift']*100)} pp, 95% CI {num(g7['abs_ci_low']*100)} to {num(g7['abs_ci_high']*100)}); "
          f"D1 (guardrail) {sgn(g1['abs_lift']*100)} pp (CI {num(g1['abs_ci_low']*100)} to {sgn(g1['abs_ci_high']*100)}). "
          f"Not certified: the arms are unbalanced (SRM warning), see the integrity checks.")
    out["gate_rates"] = Fig("gate_rates", "gate", F.fig_gate_rates(
        g, "D1 and D7 retention by gate version (%, 95% CI)", tk), tk)
    tk = (f"The bootstrap agrees with the analytic intervals: D7 {sgn(g7['abs_lift']*100)} pp (95% CI "
          f"{num(g7['boot_abs_ci'][0]*100)} to {num(g7['boot_abs_ci'][1]*100)}); D1 {sgn(g1['abs_lift']*100)} pp "
          f"(CI {num(g1['boot_abs_ci'][0]*100)} to {sgn(g1['boot_abs_ci'][1]*100)}). Both are the naive comparison.")
    out["gate_bootstrap"] = Fig("gate_bootstrap", "gate", F.fig_gate_bootstrap(
        caches["boot_gate"], g, "Bootstrap distribution of gate_40 − gate_30 retention (pp)", tk), tk)

    nc = g["negative_control"]
    band = g["retention_by_rounds_band"]
    rows = pd.DataFrame([
        {"label": "All players (naive result)", "role": "main", **g7},
        {"label": "Never met a gate: < 30 rounds", "role": "control", **nc["never_reached_30"]["retention_7"]},
        {"label": "of which < 15 rounds (extra installs sit here)", "role": "control", **band["rounds_lt_15"]["retention_7"]},
        {"label": "of which 15–29 rounds (balanced in number)", "role": "control", **band["rounds_15_29"]["retention_7"]},
        {"label": "Could meet the gate: 30+ rounds", "role": "other", **band["rounds_ge_30"]["retention_7"]},
    ])
    ncr = nc["never_reached_30"]["retention_7"]
    b15, b1529, b30 = (band[k]["retention_7"] for k in ("rounds_lt_15", "rounds_15_29", "rounds_ge_30"))
    hi_txt = "just below 0" if -0.005 < ncr["abs_ci_high"] * 100 < 0 else num(ncr["abs_ci_high"] * 100)
    tk = (f"Players with < 30 rounds met no gate in either version, yet gate_40 shows {sgn(ncr['abs_lift']*100)} pp D7 "
          f"(CI {num(ncr['abs_ci_low']*100)} to {hi_txt}, {fmt_p(ncr['p_value'])}: borderline on its own). The gap sits with "
          f"players who played 15–29 rounds ({sgn(b1529['abs_lift']*100)} pp, {fmt_p(b1529['p_value'])}), not with the extra "
          f"< 15-round installs ({sgn(b15['abs_lift']*100)} pp), and players who could meet the gate show the same "
          f"{sgn(b30['abs_lift']*100)} pp. So even their gap may not be the gate.")
    out["gate_negative_control"] = Fig("gate_negative_control", "gate", F.fig_effect_by_stratum(
        rows, "D7 retention difference by rounds played: a negative-control check (pp, 95% CI)", tk, height=380), tk)

    curve_v = R.engagement_curve(players, 60, by="version")
    pg = g["pre_gate_engagement"]
    sbs = g["srm_by_stratum"]
    tk = (f"Before round 30 the two versions are identical, yet gate_40's curve already sits below gate_30's: the same "
          f"imbalance seen as a distribution (pre-gate rounds {fmt_p(pg['mannwhitney_p'])}). gate_40 has "
          f"{g['excess_players_raw']} more installs in the raw log; the net excess is {sgn(sbs['rounds_lt_15']['net_excess_t'], 0)} "
          f"among players with < 15 rounds ({fmt_p(sbs['rounds_lt_15']['p_value'])}, a subset chosen after seeing the "
          f"warning), {sgn(sbs['rounds_15_29']['net_excess_t'], 0)} at 15–29 and {sgn(sbs['rounds_ge_30']['net_excess_t'], 0)} "
          f"at 30+ ({fmt_p(sbs['rounds_ge_30']['p_value'])}).")
    out["gate_engagement_gap"] = Fig("gate_engagement_gap", "gate", F.fig_engagement_gap(
        curve_v, g["players"]["gate_40"], g["players"]["gate_30"],
        "Engagement curve gap, gate_40 − gate_30 (pp of players, pointwise 95% CI)", tk), tk)

    dec = g["d7_decomposition"]
    parts = pd.DataFrame([
        {"label": "Naive gap (all players)", "value": dec["naive_diff"], "role": "total"},
        {"label": "Player mix (extra low-engagement players)", "value": dec["composition"], "role": "not_gate"},
        {"label": "Players who never met a gate", "value": dec["within_never_reached_30"], "role": "not_gate"},
        {"label": "Players who could meet the gate", "value": dec["within_reached_30"], "role": "could_be_gate",
         "ci_low": dec["install_level_effect_ci_if_only_reachers"][0],
         "ci_high": dec["install_level_effect_ci_if_only_reachers"][1]},
    ])
    ci = dec["install_level_effect_ci_if_only_reachers"]
    tk = (f"Of the naive {sgn(dec['naive_diff']*100)} pp, {sgn(dec['composition']*100)} pp comes from the player mix and "
          f"{sgn(dec['within_never_reached_30']*100)} pp from players who never met a gate; neither can be the gate "
          f"(imbalance or chance). The rest, {sgn(dec['within_reached_30']*100)} pp per install (95% CI {num(ci[0]*100)} to "
          f"{sgn(ci[1]*100)}), is the part the gate could explain, not an estimate of its effect: players with 15–29 "
          f"rounds, who never met a gate, show the same gap as those who could. No sign of a retention benefit.")
    out["gate_decomposition"] = Fig("gate_decomposition", "gate", F.fig_gap_decomposition(
        parts, "Where the naive D7 gap comes from (pp of installs)", tk), tk)

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
