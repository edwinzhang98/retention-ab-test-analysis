"""Page 6 · Gate experiment (Cookie Cats): should the first gate move from level 30 to 40?

Same readout logic as page 4, applied to the second experiment. The sample
ratio check trips its warning level, so it comes first. The sensitivity panel
re-runs the D1 / D7 comparison live on subsets of fct_game_players; headline
numbers come from reports/results.json.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy import stats as sps

from common import (C, F, R, S, caveat, fmt_pct, fmt_pp, how_to_read, load_cache, load_catalog_takeaways,
                    load_results, page_header, show, takeaway)

RES = load_results()
G = RES["cookie"]["gate"]
SRM = G["srm"]
DQ = RES["data_quality"]["cookie"]
CAT = load_catalog_takeaways()
BOOT = load_cache("boot_gate_lift")
ALPHA0 = float(RES["config"]["alpha"])
POWER0 = float(RES["config"]["power"])

T_ARM, C_ARM = "gate_40", "gate_30"
NO_CAP = C.GAMEROUNDS_OUTLIER_MAX          # the project's outlier rule; above the cleaned max
CAPS = [100, 250, 500, 1000, 2000, NO_CAP]
ALPHAS = [0.10, 0.05, 0.01]
PRE_GATE_ROUNDS = 29                      # nobody can reach the level-30 gate in fewer rounds
CURVE_MAX = 100


# ------------------------------------------------------------------ helpers
def conf(alpha: float) -> str:
    return f"{(1 - alpha) * 100:g}%"


def pp_range(lo: float, hi: float) -> str:
    return f"{lo * 100:+.2f} to {hi * 100:+.2f} pp"


def p_eq(p: float) -> str:
    return "p < 0.0001" if p < 1e-4 else f"p = {p:.4f}"


def ci_short(lo: float, hi: float) -> str:
    """Interval in pp without the unit, for the small metric notes."""
    return f"{lo * 100:+.2f} to {hi * 100:+.2f}"


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


def srm_status(s: dict) -> str:
    """PASS / WARNING / FAIL. Newer results.json files carry it; older ones only have p and the threshold."""
    if s.get("status"):
        return s["status"]
    warn = s.get("warn_threshold", 0.01)
    return "FAIL" if s["p_value"] < s["threshold"] else ("WARNING" if s["p_value"] < warn else "PASS")


@st.cache_data(show_spinner=False)
def gate_compare(exclude_zero: bool, cap: int, alpha: float) -> dict:
    """D1 / D7 two-proportion tests, MDE and the rounds guardrail on a subset of players."""
    p = load_cache("fct_game_players")
    keep = p["sum_gamerounds"] <= cap
    if exclude_zero:
        keep &= p["sum_gamerounds"] > 0
    d = p[keep]
    v = d.groupby("version").agg(n=("user_id", "size"), r1=("retention_1", "sum"), r7=("retention_7", "sum"))
    n_t, n_c = int(v.loc[T_ARM, "n"]), int(v.loc[C_ARM, "n"])
    out = {"n_t": n_t, "n_c": n_c, "excluded": int(len(p) - len(d))}
    for metric, col in (("retention_1", "r1"), ("retention_7", "r7")):
        res = S.two_prop_test(v.loc[T_ARM, col], n_t, v.loc[C_ARM, col], n_c, alpha=alpha).to_dict()
        res["mde_abs"] = S.mde(res["rate_c"], n_t, n_c, alpha, POWER0)["mde_abs"]
        out[metric] = res
    rt = d.loc[d["version"] == T_ARM, "sum_gamerounds"]
    rc = d.loc[d["version"] == C_ARM, "sum_gamerounds"]
    out["rounds"] = {"median_t": float(rt.median()), "median_c": float(rc.median()), "mean_t": float(rt.mean()),
                     "mean_c": float(rc.mean()), "mw_p": float(sps.mannwhitneyu(rt, rc).pvalue)}
    return out


@st.cache_data(show_spinner=False)
def engagement() -> tuple[pd.DataFrame, dict]:
    """Engagement curve by version plus a pre-gate balance check: up to round 29 no player can
    have met either gate, so play up to that point should not differ between versions."""
    p = load_cache("fct_game_players")
    curve = R.engagement_curve(p, CURVE_MAX, by="version")
    wide = curve.pivot(index="rounds_at_least", columns="group", values="share_of_players")
    gap = (wide[T_ARM] - wide[C_ARM]) * 100
    pre, post = gap.loc[1:PRE_GATE_ROUNDS], gap.loc[41:CURVE_MAX]
    capped = {arm: np.minimum(p.loc[p["version"] == arm, "sum_gamerounds"], PRE_GATE_ROUNDS) for arm in (T_ARM, C_ARM)}
    check = {"pre_min": float(pre.min()), "pre_max": float(pre.max()), "pre_all_below": bool((pre < 0).all()),
             "post_max": float(post.max()), "post_all_above": bool((post > 0).all()),
             "pre_mw_p": float(sps.mannwhitneyu(capped[T_ARM], capped[C_ARM]).pvalue)}
    return curve, check


def forest_rows(cur: dict, cur_label: str) -> pd.DataFrame:
    """Headline (results.json) and current-check rows in the shape fig_lift_forest expects."""
    keys = ("n_t", "n_c", "rate_t", "rate_c", "abs_lift", "abs_ci_low", "abs_ci_high", "p_value", "alpha")
    rows = []
    for metric, name in (("retention_7", "D7"), ("retention_1", "D1")):
        for label, src in (("headline", G), (cur_label, cur)):
            r = {k: src[metric][k] for k in keys}
            r["row"] = f"{name} · {label}"
            r["p_adj"] = r["p_value"]
            r["excludes_0"] = bool(r["abs_ci_low"] > 0 or r["abs_ci_high"] < 0)
            rows.append(r)
    return pd.DataFrame(rows)


def separate_gate_labels(fig: go.Figure) -> go.Figure:
    """At half width the 'gate 30' / 'gate 40' labels collide; anchor them away from each other."""
    for ann in fig.layout.annotations:
        if ann.text == "gate 30":
            ann.xanchor = "right"
        elif ann.text == "gate 40":
            ann.xanchor = "left"
    return fig


def gap_figure(curve: pd.DataFrame, n_t: int, n_c: int) -> go.Figure:
    """gate_40 − gate_30 gap in the engagement curve with a pointwise 95% band, styled like src/figures.py."""
    wide = curve.pivot(index="rounds_at_least", columns="group", values="share_of_players").loc[1:]
    s_t, s_c = wide[T_ARM], wide[C_ARM]
    gap = ((s_t - s_c) * 100).to_numpy()
    half = sps.norm.ppf(0.975) * np.sqrt(s_t * (1 - s_t) / n_t + s_c * (1 - s_c) / n_c).to_numpy() * 100
    x = wide.index.to_numpy()
    fig = go.Figure()
    fig.add_vrect(x0=1, x1=PRE_GATE_ROUNDS, fillcolor=F.GREY_LIGHT, opacity=0.3, line_width=0, layer="below")
    fig.add_annotation(x=(1 + PRE_GATE_ROUNDS) / 2, y=0.98, yref="paper", text="before any gate", showarrow=False,
                       yanchor="top", font=dict(size=11, color=F.INK_2))
    fig.add_scatter(x=np.concatenate([x, x[::-1]]), y=np.concatenate([gap + half, (gap - half)[::-1]]),
                    fill="toself", fillcolor="rgba(42,120,214,0.12)", line=dict(width=0), hoverinfo="skip",
                    name="Pointwise 95% CI")
    fig.add_scatter(x=x, y=gap, mode="lines", line=dict(color=F.BLUE, width=2), name="gate_40 − gate_30",
                    customdata=np.stack([s_c * 100, s_t * 100], axis=1),
                    hovertemplate="≥ %{x} rounds: %{y:+.2f} pp<br>gate_30 %{customdata[0]:.1f}% · "
                                  "gate_40 %{customdata[1]:.1f}%<extra></extra>")
    fig.add_hline(y=0, line=dict(color=F.INK_2, width=1))
    for g, side in ((30, "right"), (40, "left")):
        fig.add_vline(x=g, line=dict(color=F.INK_2, width=1, dash="dot"))
        fig.add_annotation(x=g, y=1, yref="paper", text=f"gate {g}", showarrow=False, yanchor="bottom",
                           xanchor=side, font=dict(size=11, color=F.INK_2))
    F._layout(fig, "Gap between the versions' curves, gate_40 − gate_30 (pp)", height=400,
              xaxis_title="Game rounds played in first 14 days (at least)",
              yaxis_title="Difference in share of players (pp)", legend=False)
    return fig


# ------------------------------------------------------------------ page
page_header("Gate Experiment (Cookie Cats)", "Should the first gate move from level 30 to level 40?")

# ---------------------------------------------------------------- SRM first
status = srm_status(SRM)
warn_thr = SRM.get("warn_threshold", 0.01)
n_t, n_c = SRM["n_t"], SRM["n_c"]
excess = n_t - SRM["expected_t"]
dropped = DQ["outliers_dropped"]
raw = S.srm_check(n_t + sum(o["version"] == T_ARM for o in dropped), n_c + sum(o["version"] == C_ARM for o in dropped),
                  SRM["intended_share_t"], SRM["threshold"])
share_i = SRM["intended_share_t"]
srm_line = (f"The split was meant to be {(1 - share_i) * 100:.0f}/{share_i * 100:.0f} but came out "
            f"{n_c:,} gate_30 vs {n_t:,} gate_40 ({SRM['observed_share_t']:.2%} in gate_40, {excess:+,.0f} vs "
            f"expected). Chi-square {p_eq(SRM['p_value'])}")
raw_line = (f" (On the raw table, before dropping the one logging-error player: {raw['n_c']:,} vs {raw['n_t']:,}, "
            f"{p_eq(raw['p_value'])}.)" if dropped else "")
if status in ("WARN", "WARNING"):
    caveat(f"<b>Sample ratio mismatch: WARNING.</b> {srm_line}: below the {warn_thr:g} warning level but above the "
           f"{SRM['threshold']:g} hard-fail threshold used in this project. We treat it as a <b>warning that blocks "
           "certification</b>: the readout below shows the direction of the effect, but its size cannot be signed "
           f"off until the assignment is debugged.{raw_line}")
elif status == "FAIL":
    caveat(f"<b>Sample ratio mismatch: FAIL.</b> {srm_line}: below the {SRM['threshold']:g} hard-fail threshold. "
           f"Treat every number on this page as untrustworthy until the assignment is fixed.{raw_line}")
else:
    st.caption(f"Sample ratio check passed. {srm_line}.")

# ---------------------------------------------------------------- headline
g7, g1 = G["retention_7"], G["retention_1"]
lost = -g7["abs_lift"] * g7["n_t"]
lost_lo, lost_hi = -g7["abs_ci_high"] * g7["n_t"], -g7["abs_ci_low"] * g7["n_t"]
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "D7 retention, gate_40", fmt_pct(g7["rate_t"]), f"gate_30: {fmt_pct(g7['rate_c'])}")
kpi(k2, "D7 difference", fmt_pp(g7["abs_lift"]), f"95% CI {ci_short(g7['abs_ci_low'], g7['abs_ci_high'])}",
    help=f"gate_40 − gate_30, percentage points. {p_eq(g7['p_value'])}.")
kpi(k3, "D1 difference", fmt_pp(g1["abs_lift"]), f"95% CI {ci_short(g1['abs_ci_low'], g1['abs_ci_high'])}",
    help=f"gate_40 − gate_30, percentage points. {p_eq(g1['p_value'])}.")
kpi(k4, f"Fewer D7 players / {g7['n_t'] / 1e3:.0f}K", f"≈{round(lost, -1):,.0f}",
    f"95% CI {round(lost_lo, -1):,.0f}–{round(lost_hi, -1):,.0f}",
    help=f"D7 difference × {g7['n_t']:,} gate_40 installs: how many fewer players would still be playing on Day 7.")
st.caption(f"Two-sided two-proportion z-tests, gate_40 vs gate_30: D7 {p_eq(g7['p_value'])}, "
           f"D1 {p_eq(g1['p_value'])}. Players: {n_c:,} gate_30, {n_t:,} gate_40.")

r1, r2 = st.columns(2)
with r1:
    show(F.fig_gate_rates(G, "D1 and D7 retention by gate version (%, 95% CI)"), key="p6_rates")
    takeaway(CAT["gate_rates"])
with r2:
    fig_gb = F.fig_gate_bootstrap(BOOT, G, "Bootstrap: gate_40 − gate_30 retention (pp)", height=400)
    fig_gb.update_layout(bargap=0.04)  # the shared layout's bar gap makes a histogram look like a comb
    show(fig_gb, key="p6_boot")
    takeaway(CAT["gate_bootstrap"])

# ---------------------------------------------------------------- sensitivity
st.subheader("Sensitivity: does the result survive other reasonable choices?")
s1, s2, s3 = st.columns([1, 1, 1.4])
alpha = s1.radio("Significance level α", ALPHAS, index=ALPHAS.index(ALPHA0) if ALPHA0 in ALPHAS else 1,
                 format_func=lambda a: f"{a:.2f}", horizontal=True, key="p6_alpha")
exclude_zero = s2.toggle("Exclude 0-round players", key="p6_excl0",
                         help="Players who installed but never played a round, so they never met either gate.")
cap = s3.select_slider("Drop players with more than N rounds", CAPS, value=NO_CAP, key="p6_cap",
                       format_func=lambda c: f"no cap ({NO_CAP:,} rule)" if c == NO_CAP else f"{c:,}",
                       help=f"The project's outlier rule drops players above {NO_CAP:,} rounds (one player). "
                            "Lower caps test whether heavy players drive the result.")

cur = gate_compare(exclude_zero, cap, alpha)
is_headline = (not exclude_zero) and cap == NO_CAP and alpha == ALPHA0
c7, c1 = cur["retention_7"], cur["retention_1"]
m1, m2, m3, m4 = st.columns(4)
kpi(m1, "Players in this check", f"{cur['n_t'] + cur['n_c']:,}", f"{cur['excluded']:,} excluded")
shift = (c7["abs_lift"] - g7["abs_lift"]) * 100
shift = 0.0 if abs(shift) < 0.005 else shift   # results.json is rounded to 6 decimals
kpi(m2, "D7 · this check", fmt_pp(c7["abs_lift"]),
    f"{conf(alpha)} CI {ci_short(c7['abs_ci_low'], c7['abs_ci_high'])}", help=p_eq(c7["p_value"]))
kpi(m3, "D1 · this check", fmt_pp(c1["abs_lift"]),
    f"{conf(alpha)} CI {ci_short(c1['abs_ci_low'], c1['abs_ci_high'])}", help=p_eq(c1["p_value"]))
kpi(m4, "D7 change vs headline", f"{shift:+.2f} pp", f"headline {fmt_pp(g7['abs_lift'])}")

fig = F.fig_lift_forest(forest_rows(cur, "this check"), "row",
                        "Retention difference, gate_40 − gate_30: headline vs this check (pp)",
                        sig_col="excludes_0", seg_title="")
for tr in fig.data:
    tr.name = {"Significant after correction": "CI excludes 0",
               "Not significant after correction": "CI includes 0"}.get(tr.name, tr.name)
fig.update_xaxes(title_text="gate_40 − gate_30 retention (pp)")
fig.update_yaxes(automargin=True)
show(fig, key="p6_sensitivity")
st.caption(f"Headline = all {G['players'][C_ARM] + G['players'][T_ARM]:,} players, {conf(ALPHA0)} CI (from results.json). "
           "'This check' = the filters and α chosen above, recomputed live.")

parts = []
if exclude_zero:
    parts.append("without players who never played a round")
if cap < NO_CAP:
    parts.append(f"without players above {cap:,} rounds")
if alpha != ALPHA0:
    parts.append(f"at α = {alpha:.2f}")
scope = (f"Headline (all players, α = {ALPHA0:.2f})" if is_headline else "This check (" + ", ".join(parts) + ")")
if c7["abs_ci_high"] < 0:
    d7_verdict = "The D7 drop holds."
elif c7["abs_ci_low"] > 0:
    d7_verdict = "D7 turns positive on this cut."
else:
    d7_verdict = "On this cut the D7 drop is no longer distinguishable from 0."
if c1["abs_ci_high"] < 0:
    d1_verdict = ("D1 also comes out significantly lower here, but this is one of several cuts tried, so read it as "
                  "consistent with a D1 drop rather than proof of one.")
elif c1["abs_ci_low"] > 0:
    d1_verdict = "D1 turns positive on this cut."
else:
    d1_verdict = "D1 stays inconclusive."
takeaway(f"{scope}: D7 {fmt_pp(c7['abs_lift'])} ({conf(alpha)} CI {pp_range(c7['abs_ci_low'], c7['abs_ci_high'])}, "
         f"{p_eq(c7['p_value'])}) and D1 {fmt_pp(c1['abs_lift'])} ({conf(alpha)} CI "
         f"{pp_range(c1['abs_ci_low'], c1['abs_ci_high'])}). {d7_verdict} {d1_verdict}")

# ---------------------------------------------------------------- power + guardrail
st.subheader("Power and the engagement guardrail")
rd = cur["rounds"]
w1, w2, w3, w4 = st.columns(4)
kpi(w1, "D7 MDE", f"±{c7['mde_abs'] * 100:.2f} pp", f"observed {fmt_pp(c7['abs_lift'])}",
    help=f"Minimum detectable D7 change at {POWER0:.0%} power and α = {alpha:.2f} for this sample.")
kpi(w2, "D1 MDE", f"±{c1['mde_abs'] * 100:.2f} pp", f"observed {fmt_pp(c1['abs_lift'])}",
    help=f"Minimum detectable D1 change at {POWER0:.0%} power and α = {alpha:.2f} for this sample.")
kpi(w3, "Median rounds, 30 vs 40", f"{rd['median_c']:.0f} vs {rd['median_t']:.0f}",
    f"means {rd['mean_c']:.1f} vs {rd['mean_t']:.1f}")
kpi(w4, "Rounds, Mann–Whitney", p_eq(rd["mw_p"]), "gate_40 vs gate_30",
    help="Rank test comparing the whole distribution of rounds played, not just the median.")
d7_vs = "larger" if abs(c7["abs_lift"]) >= c7["mde_abs"] else "smaller"
d1_vs = ("larger than that" if abs(c1["abs_lift"]) >= c1["mde_abs"] else
         "smaller than that, so 'not significant' on D1 means 'too small to measure with this sample', "
         "not 'no effect'")
play = ("no sign that the later gate bought extra play in the first 14 days" if rd["mw_p"] >= alpha else
        "a small shift in how much people play, worth a look but not a reason to ship")
takeaway(f"At {POWER0:.0%} power this sample can detect a D7 change of about ±{c7['mde_abs'] * 100:.2f} pp and a D1 "
         f"change of about ±{c1['mde_abs'] * 100:.2f} pp. The D7 gap ({fmt_pp(c7['abs_lift'])}) is {d7_vs} than its "
         f"bar; the D1 gap ({fmt_pp(c1['abs_lift'])}) is {d1_vs}. Rounds played barely move (median "
         f"{rd['median_c']:.0f} vs {rd['median_t']:.0f}, {p_eq(rd['mw_p'])}): {play}.")

# ---------------------------------------------------------------- engagement curve
st.subheader("Where do players stop? Engagement by version")
curve, chk = engagement()
e1, e2 = st.columns(2)
with e1:
    show(separate_gate_labels(F.fig_engagement_curve(curve, "Share of players reaching at least N rounds (%)")),
         key="p6_curve")
    takeaway(CAT["ret_engagement_curve"])
pre_sig = chk["pre_mw_p"] < ALPHA0
if chk["pre_all_below"] and pre_sig:
    pre_text = (f"Up to round {PRE_GATE_ROUNDS} no player can have reached a gate, so pre-gate play should look the "
                f"same in both versions. It doesn't quite: gate_40's curve sits {abs(chk['pre_max']):.1f}–"
                f"{abs(chk['pre_min']):.1f} pp lower there (Mann–Whitney on rounds capped at {PRE_GATE_ROUNDS}: "
                f"{p_eq(chk['pre_mw_p'])}). The gate cannot cause that gap. Like the SRM warning, it suggests the "
                "groups differ for reasons other than the gate.")
else:
    pre_text = (f"Up to round {PRE_GATE_ROUNDS}, before anyone can reach a gate, the two curves track each other "
                f"(Mann–Whitney on rounds capped at {PRE_GATE_ROUNDS}: {p_eq(chk['pre_mw_p'])}).")
post_text = (f" From round 41 on, gate_40 is slightly higher (by up to {chk['post_max']:.1f} pp), consistent with "
             "players not being stopped at level 30." if chk["post_all_above"] else "")
with e2:
    show(gap_figure(curve, G["players"][T_ARM], G["players"][C_ARM]), key="p6_gap")
    takeaway(pre_text + post_text)

# ---------------------------------------------------------------- decision
st.subheader("Decision")
with st.container(border=True):
    why = (f"the SRM warning ({p_eq(SRM['p_value'])})"
           + (" and the pre-gate play gap" if chk["pre_all_below"] and pre_sig else "")
           + " mean the two groups may not be like-for-like")
    st.markdown(
        "**Keep the first gate at level 30 (R5, Game PM).**\n\n"
        f"- gate_40 measured {fmt_pp(g7['abs_lift'])} D7 retention (95% CI "
        f"{pp_range(g7['abs_ci_low'], g7['abs_ci_high'])}): about {round(lost, -1):,.0f} fewer players still playing "
        f"on Day 7 per {g7['n_t']:,} installs. D1 points the same way but is inconclusive ({fmt_pp(g1['abs_lift'])}, "
        f"{p_eq(g1['p_value'])}).\n"
        f"- Why the size is not certified: {why}. No change is the safe default, and nothing in the data suggests "
        "gate_40 is better.\n"
        "- **Next · Eng + Analytics:** debug assignment and logging before any re-test (bucketing code, how each "
        "version was rolled out, install and crash logs by version).\n"
        "- **If the team still wants a later gate:** re-run once assignment is fixed, with D7 as the primary metric, "
        "D1 and rounds played as guardrails, and the sample sized for the smallest D7 change worth acting on "
        "(calculator on page 7).")

n_boot = int(RES["config"]["n_bootstrap"])
both_lower = g7["abs_lift"] < 0 and g1["abs_lift"] < 0
d7_only = g7["p_value"] < ALPHA0 <= g1["p_value"]
rates_line = (("gate_40 is lower on both. " if both_lower else "")
              + ("Only the D7 gap is clearly larger than chance." if d7_only else ""))
more_play = G["rounds"]["median_t"] > G["rounds"]["median_c"]
how_to_read(f"""
**Why the sample-ratio check comes first.** A test set to split users 50/50 should end up very close to 50/50.
An imbalance bigger than chance allows means something in assignment or logging went wrong, for example one
version losing users to a crash or a tracking bug. That can bias every metric on the page, so it is checked before
anything else. Here the imbalance ({p_eq(SRM['p_value'])}) is past the {warn_thr:g} warning level but not the
{SRM['threshold']:g} hard-fail level. The direction of the result is informative; its exact size is not certified.

**Retention chart.** Share of players who came back 1 day (D1) and 7 days (D7) after installing, per version, with 95%
confidence intervals. {rates_line}

**Bootstrap chart.** We re-simulated the experiment {n_boot:,} times from the observed data and plotted the
gate_40 − gate_30 difference each time. {1 - g7['boot_share_ge_0']:.1%} of the D7 draws are below 0, against
{1 - g1['boot_share_ge_0']:.1%} of the D1 draws: the D7 drop is consistent, while the D1 distribution still overlaps 0.

**Sensitivity panel.** It re-runs the comparison under other reasonable choices: a stricter α, leaving out players who
never played, dropping heavy players. If the conclusion holds across all of them, it is not an artifact of one
choice. Do not hunt for the filter that gives the answer you like: that is p-hacking. Filtering on rounds played
also uses something measured after assignment, which is fine as a robustness check but not as the main estimate.

**MDE (minimum detectable effect).** The smallest difference this sample could reliably detect. The D1 gap
({fmt_pp(g1['abs_lift'])}) is smaller than the D1 MDE (±{g1['mde']['mde_abs'] * 100:.2f} pp). "Not significant" there
means "too small to measure here", not "no effect".

**Rounds guardrail.** The case for a later gate is that players would play more before hitting it. If that were
happening, gate_40 would show more rounds played. {"It does" if more_play else "It doesn't"} (median
{G['rounds']['median_c']:.0f} rounds for gate_30 vs {G['rounds']['median_t']:.0f} for gate_40).

**Engagement curve.** For each N, the share of players who played at least N rounds. The dotted lines mark the two gate
positions. Before round 30 the two versions are identical (nobody has met a gate yet), so any gap there is a warning
sign about the groups, not an effect of the gate.

**Common misreadings.**
- "D1 isn't significant, so D1 is unaffected." The test can't see a gap that small. Look at the interval.
- "p = {SRM['p_value']:.4f} on the SRM is fine." For a sample-ratio check that is a red flag, not a pass.
- "{fmt_pp(g7['abs_lift'])} is tiny." In relative terms it is {abs(g7['rel_lift']):.1%} fewer D7-retained players,
  about {round(lost, -1):,.0f} people per {g7['n_t'] / 1e3:.0f}K installs.
- "Players who reach round 30 retain much better, so push everyone to round 30." That is correlation: engaged players
  both play more and come back more.
""")
