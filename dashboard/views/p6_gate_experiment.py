"""Page 6 · Gate experiment (Cookie Cats): should the first gate move from level 30 to 40?

The page follows the analysis chain, in this order:
  1. the naive D1 / D7 comparison (not certified);
  2. the sample-ratio WARNING on the raw assignment counts, the net excess by rounds band
     (bands chosen after seeing the warning, so their p-values are descriptive) and the
     pre-gate play (the same imbalance seen as a distribution);
  3. how much of the D7 gap the gate could explain: the negative control, the decomposition
     and the best case for gate_40;
  4. the guardrails among players who could meet the gate (30+ rounds): Day 1 (quoted per install, because the
     30+ band is a diluted read for Day 1) and rounds played;
  5. a live sensitivity panel on the naive comparison;
  6. the re-test sizing (a change fixed in advance, never the observed effect) and
  7. the decision (R5).
"30+ rounds" means "could have reached level 30" (rounds >= levels; the data has no
level field). Headline numbers come from reports/results.json; the sensitivity panel
re-runs the naive comparison on subsets of fct_game_players. Every "lower /
inconclusive" statement is read off the confidence interval it sits next to.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from common import (C, F, R, S, caveat, fmt_pct, how_to_read, load_cache, load_catalog_takeaways, load_results,
                    page_header, show, takeaway)

RES = load_results()
G = RES["cookie"]["gate"]
SRM = G["srm"]                        # raw assignment counts
SBS = G["srm_by_stratum"]             # net excess by rounds band (descriptive: no status labels)
NC = G["negative_control"]
BAND = G["retention_by_rounds_band"]
BGD = G["d7_band_gap_difference_15_29_vs_lt_15"]   # D7 gap at 15–29 minus the gap at < 15 rounds
DEC = G["d7_decomposition"]
DEC1 = G["d1_decomposition"]
BEST = G["best_case_for_gate_40"]
PG = G["pre_gate_engagement"]
RT = G["retest_sizing"]
RD = G["rounds"]                      # all players: carries the imbalance
RR = G["rounds_among_reachers"]       # 30+ rounds: where the gate can act
DROPPED = RES["data_quality"]["cookie"]["outliers_dropped"]
CAT = load_catalog_takeaways()
BOOT = load_cache("boot_gate_lift")
ALPHA0 = float(RES["config"]["alpha"])
POWER0 = float(RES["config"]["power"])

T_ARM, C_ARM = "gate_40", "gate_30"
NO_CAP = C.GAMEROUNDS_OUTLIER_MAX          # the project's outlier rule; above the cleaned max
CAPS = [100, 250, 500, 1000, 2000, NO_CAP]
ALPHAS = [0.10, 0.05, 0.01]
BANDS = {"rounds_lt_15": "< 15 rounds",
         "rounds_15_29": "15–29 rounds",
         "rounds_lt_30": "< 30 rounds (never met a gate)",
         "rounds_ge_30": "30+ rounds (could have reached level 30)"}


# ------------------------------------------------------------------ helpers
def conf(alpha: float) -> str:
    return f"{(1 - alpha) * 100:g}%"


def sgn(x: float, nd: int = 2) -> str:
    """Always signed, with a true minus sign for prose: +0.08 / −0.82."""
    return f"{x:+.{nd}f}".replace("-", "−")


def pp(x: float, nd: int = 2) -> str:
    """A proportion as signed percentage points: -0.0082 -> '−0.82 pp'."""
    return f"{sgn(x * 100, nd)} pp"


def bound(x: float, nd: int = 2) -> str:
    """One end of an interval in pp (no unit). An end that would round to 0 keeps its side: 'just below 0'."""
    if x != 0 and abs(x * 100) < 0.5 * 10 ** -nd:
        return "just below 0" if x < 0 else "just above 0"
    return sgn(x * 100, nd)


def ci(lo: float, hi: float, nd: int = 2) -> str:
    """Interval of two proportions in pp, without the unit: '−1.33 to −0.31'."""
    return f"{bound(lo, nd)} to {bound(hi, nd)}"


def p_text(p: float) -> str:
    """p-value for display: never prints 0, two significant digits above 0.001."""
    if p < 1e-4:
        return "< 0.0001"
    return f"{p:.4f}" if (p < 1e-3 or p > 0.99) else f"{p:.2g}"


def p_eq(p: float) -> str:
    s = p_text(p)
    return f"p {s}" if s.startswith("<") else f"p = {s}"


def players(x: float) -> str:
    """Day-7 players per install base, as words: -32.1 -> '32 fewer', 7.2 -> '7 more'."""
    return f"{abs(x):,.0f} fewer" if x < 0 else f"{x:,.0f} more"


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


def two_lines(label: str) -> str:
    """A long category label on two lines (after ':' or before '('), so a phone keeps a usable plot area."""
    if ": " in label:
        return label.replace(": ", ":<br>", 1)
    return re.sub(r"\s+\(", "<br>(", label, count=1)


def ci_verdict(m: dict, name: str, level: str) -> str:
    """Plain-language reading of one gate_40 − gate_30 difference, taken from its CI only."""
    lo, hi = m["abs_ci_low"], m["abs_ci_high"]
    if hi < 0:
        return f"gate_40 shows lower {name} (the {level} CI excludes 0)"
    if lo > 0:
        return f"gate_40 shows higher {name} (the {level} CI excludes 0)"
    return f"{name} is inconclusive (the {level} CI includes 0)"


@st.cache_data(show_spinner=False)
def gate_compare(exclude_zero: bool, cap: int, alpha: float) -> dict:
    """D1 / D7 two-proportion tests and MDEs on a subset of players (the naive comparison)."""
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
    return out


@st.cache_data(show_spinner=False)
def zero_round_flags() -> dict:
    """Zero-round players and how many of them carry a return flag (data note for the toggle)."""
    p = load_cache("fct_game_players")
    z = p[p["sum_gamerounds"] == 0]
    return {"n": len(z), "d1": int(z["retention_1"].sum()), "d7": int(z["retention_7"].sum())}


@st.cache_data(show_spinner=False)
def version_curve() -> pd.DataFrame:
    """Engagement curve by version up to 60 rounds (same input as the catalog's gate_engagement_gap)."""
    return R.engagement_curve(load_cache("fct_game_players"), 60, by="version")


def forest_rows(cur: dict, cur_label: str) -> pd.DataFrame:
    """Headline (results.json) and current-check rows in the shape fig_lift_forest expects."""
    keys = ("n_t", "n_c", "rate_t", "rate_c", "abs_lift", "abs_ci_low", "abs_ci_high", "p_value")
    rows = []
    for metric, name in (("retention_7", "D7"), ("retention_1", "D1")):
        for label, src in (("headline", G), (cur_label, cur)):
            r = {k: src[metric][k] for k in keys}
            r["row"] = f"{name} · {label}"
            r["p_adj"] = r["p_value"]
            r["excludes_0"] = bool(r["abs_ci_low"] > 0 or r["abs_ci_high"] < 0)
            rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ numbers used across sections
g7, g1 = G["retention_7"], G["retention_1"]
n_t, n_c = SRM["n_t"], SRM["n_c"]                     # raw assignment counts
raw_excess = int(G["excess_players_raw"])               # 789 in the raw log
extra = int(BEST["excess_players_gate_40"])             # 790 after the one-outlier drop
extra_round = int(round(extra, -1))                     # "≈790"
lt15, b1529, ge30 = SBS["rounds_lt_15"], SBS["rounds_15_29"], SBS["rounds_ge_30"]
ncr = NC["never_reached_30"]["retention_7"]
ncx = NC["never_reached_30_excess_removed"]
band7 = {k: v["retention_7"] for k, v in BAND.items()}
band1 = {k: v["retention_1"] for k, v in BAND.items()}
b1529_7, b30_7 = band7["rounds_15_29"], band7["rounds_ge_30"]
b1528, b29 = band7["rounds_15_28"], band7["rounds_29"]   # at 29 rounds a perfect gate_30 player can face the gate
# "similar gap", never "the same": the two bands match to two decimals by coincidence, so both CIs are shown
similar_gap = (f"15–29 rounds: {pp(b1529_7['abs_lift'])}, 95% CI {ci(b1529_7['abs_ci_low'], b1529_7['abs_ci_high'])}; "
               f"30+ rounds: {pp(b30_7['abs_lift'])}, 95% CI {ci(b30_7['abs_ci_low'], b30_7['abs_ci_high'])}")
dec_ci = DEC["install_level_effect_ci_if_only_reachers"]
dec1_ci = DEC1["install_level_effect_ci_if_only_reachers"]
per10k = [x * 10_000 for x in (DEC["within_reached_30"], *dec_ci)]
not_gate_share = (DEC["composition"] + DEC["within_never_reached_30"]) / DEC["naive_diff"]
sp40 = RR["share_past_40_rounds"]
sesoi = RT["smallest_d7_change_per_install"]
need_reach = RT["installs_needed_reacher_analysis_5050"]
need_all = RT["installs_needed_install_level_5050"]
status = SRM["status"]

# ---------------------------------------------------------------- page
page_header("Gate Experiment (Cookie Cats)", "Should the first gate move from level 30 to level 40?")

with st.container(border=True):
    st.markdown(
        f"**Readout in one line.** In the naive comparison gate_40 shows {abs(g7['abs_lift']) * 100:.2f} pp lower D7 "
        f"retention than gate_30 ({fmt_pct(g7['rate_t'])} vs {fmt_pct(g7['rate_c'])}; 95% CI "
        f"{ci(g7['abs_ci_low'], g7['abs_ci_high'])} pp), but the split triggered a sample-ratio {status}, so the "
        f"result is not certified. The part of the gap the gate could explain is {pp(DEC['within_reached_30'])} per "
        f"install (95% CI {ci(*dec_ci)}), possibly zero, and there is no sign of a retention benefit. **Keep gate_30 "
        "(R5); fix assignment before any re-test.**")

# ---------------------------------------------------------------- 1. naive result
st.subheader("1 · Naive result: D1 and D7 retention (not certified)")
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "D7 retention, gate_40", fmt_pct(g7["rate_t"]), f"gate_30: {fmt_pct(g7['rate_c'])}")
kpi(k2, "D7 difference (naive)", pp(g7["abs_lift"]), f"95% CI {ci(g7['abs_ci_low'], g7['abs_ci_high'])}",
    help=f"gate_40 − gate_30, all {g7['n_t'] + g7['n_c']:,} players in the analysis table, {p_eq(g7['p_value'])}. It "
         "carries the assignment imbalance (section 2), so quoting it as the gate's effect would overstate it.")
kpi(k3, "D1 retention, gate_40", fmt_pct(g1["rate_t"]), f"gate_30: {fmt_pct(g1['rate_c'])}")
kpi(k4, "D1 difference (naive)", pp(g1["abs_lift"]), f"95% CI {ci(g1['abs_ci_low'], g1['abs_ci_high'])}",
    help=f"gate_40 − gate_30, {p_eq(g1['p_value'])}. D1 is a guardrail; section 4 reads the part the gate could "
         "explain.")
show(F.fig_gate_rates(G, "D1 and D7 retention by gate version (%, 95% CI)"), key="p6_rates")
takeaway(CAT["gate_rates"])
show(F.fig_gate_bootstrap(BOOT, G, "Bootstrap distribution of gate_40 − gate_30 retention (pp)"), key="p6_boot")
takeaway(CAT["gate_bootstrap"])

# ---------------------------------------------------------------- 2. sample ratio on raw counts
st.subheader("2 · Can the split be trusted? Sample ratio on the raw assignment counts")
share_i = SRM["intended_share_t"]
srm_line = (f"The split was meant to be {(1 - share_i) * 100:.0f}/{share_i * 100:.0f}, but the raw assignment counts "
            f"are {n_c:,} gate_30 vs {n_t:,} gate_40 ({n_t - n_c:+,} in gate_40, {SRM['observed_share_t']:.2%} instead "
            f"of {share_i:.0%}). Chi-square {p_eq(SRM['p_value'])}")
warn_line = f"the {SRM['warn_threshold']:g} warning line (project convention)"
stop_line = f"the {SRM['threshold']:g} hard stop (Kohavi et al. convention)"
if status == "WARNING":
    caveat(f"<b>Sample ratio mismatch: WARNING.</b> {srm_line}: below {warn_line} and above {stop_line}. A warning "
           "blocks certification: the naive result above shows the direction, not a size we can sign off. The rest of "
           "this section locates the imbalance; section 3 sizes how much of the D7 gap the gate could explain.")
elif status == "FAIL":
    caveat(f"<b>Sample ratio mismatch: FAIL.</b> {srm_line}: below {stop_line}. Treat every number on this page as "
           "untrustworthy until the assignment is fixed.")
else:
    st.caption(f"Sample ratio check passed. {srm_line}.")

st.markdown("**Where is gate_40's net excess?** Assignment counts by rounds played in the first 14 days (raw counts; "
            "the bands were chosen after seeing the warning, so their p-values are descriptive)")
table = ["| Installs with | gate_30 | gate_40 | Net excess in gate_40 | Share in gate_40 | Chi-square p |",
         "|---|---:|---:|---:|---:|---:|",
         f"| **All installs (the sample-ratio check)** | {n_c:,} | {n_t:,} | {n_t - n_c:+,} "
         f"| {SRM['observed_share_t']:.2%} | {p_text(SRM['p_value'])} |"]
for key, label in BANDS.items():
    s = SBS[key]
    table.append(f"| {label} | {s['n_c']:,} | {s['n_t']:,} | {sgn(s['net_excess_t'], 0)} "
                 f"| {s['observed_share_t']:.2%} | {p_text(s['p_value'])} |")
st.markdown("\n".join(table))
takeaway(f"The net excess sits with players who never met a gate: a net excess of {lt15['net_excess_t']:,} among "
         f"players with < 15 rounds ({p_eq(lt15['p_value'])}), {sgn(b1529['net_excess_t'], 0)} at 15–29 "
         f"({p_eq(b1529['p_value'])}) and {sgn(ge30['net_excess_t'], 0)} at 30+ ({p_eq(ge30['p_value'])}). Play below "
         "level 30 happens before either gate, so the gate cannot be the reason: most likely assignment or logging "
         "added low-engagement installs to gate_40 (or dropped them from gate_30); Engineering confirms the cause.")
dropped = ", ".join(f"{o['version']}, {o['sum_gamerounds']:,} rounds" for o in DROPPED)
st.caption(f"gate_40 has ≈{extra_round:,} extra installs ({raw_excess:,} in the raw log, {extra:,} after the "
           f"one-outlier drop: {dropped}). The < 30 row is the sum of the < 15 and 15–29 rows.")

st.markdown("**Pre-gate play: the same imbalance, seen as a distribution**")
show(F.fig_engagement_gap(version_curve(), G["players"][T_ARM], G["players"][C_ARM],
                          "Engagement curve gap, gate_40 − gate_30 (pp of players, pointwise 95% CI)"),
     key="p6_gap")
takeaway(CAT["gate_engagement_gap"])
st.caption(f"Rounds capped at 29 (play before any gate): mean {PG['mean_capped_29_t']:.2f} in gate_40 vs "
           f"{PG['mean_capped_29_c']:.2f} in gate_30, Mann–Whitney {p_eq(PG['mannwhitney_p'])}. This is the net "
           "excess of low-round installs seen as a distribution, not independent evidence: within players with < 30 "
           f"rounds the difference is {p_eq(PG['mannwhitney_p_within_lt_30'])}.")

# ---------------------------------------------------------------- 3. what the gate could explain
st.subheader("3 · How much of the D7 gap could the gate explain?")
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Negative control", pp(ncr["abs_lift"]), f"D7, < 30 rounds · {p_eq(ncr['p_value'])}",
    help="D7 difference among players with < 30 rounds, who never met a gate in either version, so their retention "
         f"should not differ by version. 95% CI {ci(ncr['abs_ci_low'], ncr['abs_ci_high'])}: borderline on its own.")
kpi(c2, f"Without the net {ncx['excess_removed']:,}", pp(ncx["retention_7"]["abs_lift"]),
    f"D7, < 30 rounds · {p_eq(ncx['retention_7']['p_value'])}",
    help=f"The negative control after removing the net {ncx['excess_removed']:,} extra < 15-round installs from "
         "gate_40 (none counted as back on Day 7). 95% CI "
         f"{ci(ncx['retention_7']['abs_ci_low'], ncx['retention_7']['abs_ci_high'])}.")
kpi(c3, "Gate could explain", pp(DEC["within_reached_30"]), f"per install · CI {ci(*dec_ci)}",
    help="The part of the naive D7 gap that sits with players who could have reached level 30 (30+ rounds), in pp per "
         "install, with its 95% CI. Not an estimate of the gate's effect: players with 15–29 rounds, almost none of whom can have met a "
         f"gate, show a similar gap ({similar_gap}).")
kpi(c4, "Best case for gate_40", pp(BEST["d7_diff_if_excess_removed"]), f"95% CI {ci(*BEST['ci'])}",
    help=f"The naive D7 gap if all ≈{extra_round:,} extra gate_40 installs were junk installs that never came back "
         f"(removed from gate_40 with no Day-7 players): the reading most favourable to gate_40. "
         f"{p_eq(BEST['p_value'])}.")

nc_rows = pd.DataFrame([   # the catalog's gate_negative_control rows (default view = catalog chart)
    {"label": "All players (naive result)", "role": "main", **g7},
    {"label": "Never met a gate: < 30 rounds", "role": "control", **ncr},
    {"label": "of which < 15 rounds (net excess sits here)", "role": "control", **band7["rounds_lt_15"]},
    {"label": "of which 15–29 rounds (balanced in number)", "role": "control", **band7["rounds_15_29"]},
    {"label": "Could meet the gate: 30+ rounds", "role": "other", **band7["rounds_ge_30"]},
])
nc_rows["label"] = nc_rows["label"].map(two_lines)
show(F.fig_effect_by_stratum(nc_rows, "D7 retention difference by rounds played: a negative-control check (pp, 95% CI)",
                             height=380), key="p6_negative_control")
takeaway(CAT["gate_negative_control"])
st.markdown(
    f"**Reading the negative control.** Borderline on its own ({p_eq(ncr['p_value'])}); it carries weight only because "
    "the sample-ratio warning independently says the arms are not comparable. Such gap as there is comes from the "
    f"15–29 band ({pp(band7['rounds_15_29']['abs_lift'])}, {p_eq(band7['rounds_15_29']['p_value'])}, balanced in "
    f"number) rather than the < 15 band where the net excess sits ({pp(band7['rounds_lt_15']['abs_lift'])}, "
    f"{p_eq(band7['rounds_lt_15']['p_value'])}), though the two bands' gaps are not distinguishable from each other "
    f"({p_eq(BGD['p_value'])}). Removing the net {ncx['excess_removed']:,} extra < 15-round installs "
    f"moves it only to {pp(ncx['retention_7']['abs_lift'])} ({p_eq(ncx['retention_7']['p_value'])}). So the extra "
    "installs explain the sample-ratio warning and the player-mix part of the gap, but not this gap.")

parts = pd.DataFrame([   # the catalog's gate_decomposition bars, labels on two lines
    {"label": "Naive gap<br>(all players)", "value": DEC["naive_diff"], "role": "total"},
    {"label": "Player mix (extra<br>low-engagement players)", "value": DEC["composition"], "role": "not_gate"},
    {"label": "Players who never<br>met a gate", "value": DEC["within_never_reached_30"], "role": "not_gate"},
    {"label": "Players who could<br>meet the gate", "value": DEC["within_reached_30"], "role": "could_be_gate",
     "ci_low": dec_ci[0], "ci_high": dec_ci[1]},
])
dec_fig = F.fig_gap_decomposition(parts, "Where the naive D7 gap comes from (pp of installs)")
# phones: the builder now sizes the margin from the labels (automargin), but at 390 px its x-range still puts the
# "−0.82 pp" and "−0.32 pp" value labels on top of the y labels; widen the left end a little more (checked at 1400
# and 390 px).
x0, x1 = dec_fig.layout.xaxis.range
dec_fig.update_xaxes(range=[x0 * 1.25, x1])
show(dec_fig, key="p6_decomposition")
takeaway(CAT["gate_decomposition"])
st.markdown(
    f"**Reading the decomposition.** About {round(not_gate_share * 10) * 10:.0f}% of the naive gap (player mix "
    f"{pp(DEC['composition'])}, players who never met a gate {pp(DEC['within_never_reached_30'])}) sits where the gate "
    f"cannot act. The remaining {pp(DEC['within_reached_30'])} per install is the part the gate could explain, not an "
    "estimate of the gate's effect: players with 15–29 rounds, almost none of whom can have met a gate, show a similar D7 gap to "
    f"players with 30+ rounds ({similar_gap}), so even this part may not be the gate. Per 10,000 "
    "installs it is "
    f"≈{players(per10k[0])} Day-7 players (95% CI {players(per10k[1])} to {players(per10k[2])}).")
st.markdown(
    f"**Best case for gate_40.** Even if every one of the ≈{extra_round:,} extra installs never returned, the D7 gap "
    f"would still be {pp(BEST['d7_diff_if_excess_removed'])} (95% CI {ci(*BEST['ci'])} pp, {p_eq(BEST['p_value'])}). "
    "Its interval includes 0.")

# ---------------------------------------------------------------- 4. guardrails
st.subheader("4 · Guardrails: Day 1 and rounds played, among players who could meet the gate")
d1b, d7b = band1["rounds_ge_30"], band7["rounds_ge_30"]
D1_DILUTED = ("the gate can change Day 1 only for players who reached level 30 on the install day, and the data "
              "cannot single them out")
w1, w2, w3, w4 = st.columns(4)
kpi(w1, "D1 · gate could explain", pp(DEC1["within_reached_30"]), f"per install · CI {ci(*dec1_ci)}",
    help="The D1 number to quote: the part of the naive D1 gap the gate could explain, in pp per install, with its 95% "
         f"CI. The D1 decomposition, like D7's: naive {pp(DEC1['naive_diff'])} = player mix "
         f"{pp(DEC1['composition'])} + players who never met a gate {pp(DEC1['within_never_reached_30'])} + players "
         f"who could meet the gate {pp(DEC1['within_reached_30'])} per install.")
kpi(w2, "D1 · 30+ rounds", pp(d1b["abs_lift"]), f"95% CI {ci(d1b['abs_ci_low'], d1b['abs_ci_high'])}",
    help="D1 difference (gate_40 − gate_30) among players with 30+ rounds (could have reached level 30); "
         f"{p_eq(d1b['p_value'])}. A diluted read for Day 1: {D1_DILUTED}, so the per-install figure is the D1 number "
         f"to quote. The naive all-player D1 ({pp(g1['abs_lift'])}) carries the player-mix imbalance.")
kpi(w3, "Median rounds · 30+ rounds", f"{RR['median_t']:.0f} vs {RR['median_c']:.0f}",
    f"gate_40 vs gate_30 · {p_eq(RR['mannwhitney_p'])}",
    help=f"Rounds in the first 14 days among players with 30+ rounds ({RR['n_t']:,} gate_40, {RR['n_c']:,} gate_30); "
         "Mann–Whitney test on the whole distribution. The mean difference "
         f"({sgn(RR['mean_diff'], 1)} rounds, bootstrap 95% CI {sgn(RR['mean_diff_boot_ci'][0], 1)} to "
         f"{sgn(RR['mean_diff_boot_ci'][1], 1)}) is too noisy to read.")
kpi(w4, "At least 40 rounds · 30+ rounds", pp(sp40["abs_lift"], 1),
    f"{sp40['rate_t']:.1%} vs {sp40['rate_c']:.1%} · CI {ci(sp40['abs_ci_low'], sp40['abs_ci_high'], 1)}",
    help="Difference (gate_40 − gate_30) in the share of players with 30+ rounds who played at least 40 rounds: "
         f"{sp40['rate_t']:.1%} vs {sp40['rate_c']:.1%}, with the 95% CI of the difference.")
takeaway(f"Day 1: the naive {pp(g1['abs_lift'])} (95% CI {ci(g1['abs_ci_low'], g1['abs_ci_high'])}) carries the same "
         f"imbalance (player mix {pp(DEC1['composition'])}). The part the gate could explain is "
         f"{pp(DEC1['within_reached_30'])} per install (95% CI {ci(*dec1_ci)}): no sign of a D1 effect. The band of "
         f"players with 30+ rounds (could have reached level 30; {pp(d1b['abs_lift'])}) is a diluted read for Day 1: "
         f"{D1_DILUTED}.")
takeaway(f"Rounds played: the all-player mean difference ({sgn(RD['mean_diff'])} rounds, 95% CI "
         f"{sgn(RD['mean_diff_boot_ci'][0], 1)} to {sgn(RD['mean_diff_boot_ci'][1], 1)}) carries the same imbalance, "
         "so it is not a clean guardrail. Among players with 30+ rounds, gate_40 players play a little more: median "
         f"{RR['median_t']:.0f} vs {RR['median_c']:.0f} rounds (Mann–Whitney {p_eq(RR['mannwhitney_p'])}), and "
         f"{sp40['rate_t']:.1%} vs {sp40['rate_c']:.1%} played at least 40 rounds ({pp(sp40['abs_lift'], 1)}, 95% CI "
         f"{ci(sp40['abs_ci_low'], sp40['abs_ci_high'], 1)}); the mean difference ({sgn(RR['mean_diff'], 1)} rounds, "
         f"95% CI {sgn(RR['mean_diff_boot_ci'][0], 1)} to {sgn(RR['mean_diff_boot_ci'][1], 1)}) is too noisy to read. "
         f"Yet their D7 is not higher ({pp(d7b['abs_lift'])}, 95% CI {ci(d7b['abs_ci_low'], d7b['abs_ci_high'])}): no "
         "sign of a retention benefit. This is a descriptive difference: assignment is uncertified and the group "
         "is defined by rounds played, so it does not show that gate_40 causes more play.")

# ---------------------------------------------------------------- 5. sensitivity (live)
st.subheader("5 · Sensitivity: does the naive result move?")
zr = zero_round_flags()
s1, s2, s3 = st.columns([1, 1, 1.4])
alpha = s1.radio("Significance level α", ALPHAS, index=ALPHAS.index(ALPHA0) if ALPHA0 in ALPHAS else 1,
                 format_func=lambda a: f"{a:.2f}", horizontal=True, key="p6_alpha")
exclude_zero = s2.toggle("Exclude 0-round players", key="p6_excl0",
                         help=f"{zr['n']:,} players installed but never played a round, so they never met either "
                              f"gate. {zr['d1']} of them are flagged as back on Day 1 ({zr['d7']} on Day 7): the "
                              "flags mean 'came back to the game', not 'played a round'.")
cap = s3.select_slider("Drop players with more than N rounds", CAPS, value=NO_CAP, key="p6_cap",
                       format_func=lambda c: f"no cap ({NO_CAP:,} rule)" if c == NO_CAP else f"{c:,}",
                       help=f"The project's outlier rule drops players above {NO_CAP:,} rounds (one player). "
                            "Lower caps test whether heavy players drive the result.")

cur = gate_compare(exclude_zero, cap, alpha)
is_headline = (not exclude_zero) and cap == NO_CAP and alpha == ALPHA0
c7, c1_ = cur["retention_7"], cur["retention_1"]
m1, m2, m3, m4 = st.columns(4)
kpi(m1, "Players in this check", f"{cur['n_t'] + cur['n_c']:,}", f"{cur['excluded']:,} excluded")
shift = (c7["abs_lift"] - g7["abs_lift"]) * 100
shift = 0.0 if abs(shift) < 0.005 else shift   # results.json is rounded (8 decimals)
kpi(m2, "D7 · this check", pp(c7["abs_lift"]),
    f"{conf(alpha)} CI {ci(c7['abs_ci_low'], c7['abs_ci_high'])}", help=p_eq(c7["p_value"]))
kpi(m3, "D1 · this check", pp(c1_["abs_lift"]),
    f"{conf(alpha)} CI {ci(c1_['abs_ci_low'], c1_['abs_ci_high'])}", help=p_eq(c1_["p_value"]))
kpi(m4, "D7 change vs headline", f"{sgn(shift)} pp", f"headline {pp(g7['abs_lift'])}")

fig = F.fig_lift_forest(forest_rows(cur, "this check"), "row",
                        "Retention difference, gate_40 − gate_30: headline vs this check (pp)",
                        sig_col="excludes_0", sig_label="CI excludes 0", nonsig_label="CI includes 0",
                        xtitle="gate_40 − gate_30 retention (pp)")
# gate wording for the hover: the arms are gate_40 / gate_30 and the p-values are unadjusted (the builder's default
# hover speaks of "treatment / control" and "adjusted p"). The builder passes the p-value as text ('= 0.0016',
# '< 0.0001'), so it is inserted as is: a number format on it would print NaN, and it never shows as 0.
fig.update_traces(hovertemplate="<b>%{y}</b><br>Difference %{x:.2f} pp (CI %{customdata[7]:.2f} to "
                                "%{customdata[8]:.2f})<br>gate_40 %{customdata[0]:.2f}% (n=%{customdata[2]:,.0f})"
                                "<br>gate_30 %{customdata[1]:.2f}% (n=%{customdata[3]:,.0f})"
                                "<br>p %{customdata[4]}<extra></extra>")
show(fig, key="p6_sensitivity")
st.caption(f"Headline = all {G['players'][C_ARM] + G['players'][T_ARM]:,} players, {conf(ALPHA0)} CI (from "
           "results.json). 'This check' = the filters and α chosen above, recomputed live. Both are the naive "
           "comparison: no filter here removes the assignment imbalance.")

parts_txt = []
if exclude_zero:
    parts_txt.append("without players who never played a round")
if cap < NO_CAP:
    parts_txt.append(f"without players above {cap:,} rounds")
if alpha != ALPHA0:
    parts_txt.append(f"at α = {alpha:.2f}")
scope = (f"Headline (all players, α = {ALPHA0:.2f})" if is_headline else "This check (" + ", ".join(parts_txt) + ")")
level = conf(alpha)
d7_text = ci_verdict(c7, "D7", level)
d1_text = ci_verdict(c1_, "D1", level)
if c1_["abs_ci_high"] < 0 and not is_headline:
    d1_text += ("; this is one of several cuts of an unbalanced comparison, so it is not evidence of a D1 effect "
                "(section 4 reads the part of D1 the gate could explain)")
takeaway(f"{scope}: D7 {pp(c7['abs_lift'])} ({level} CI {ci(c7['abs_ci_low'], c7['abs_ci_high'])} pp) and D1 "
         f"{pp(c1_['abs_lift'])} ({level} CI {ci(c1_['abs_ci_low'], c1_['abs_ci_high'])} pp). {d7_text}; "
         f"{d1_text}. None of these cuts fixes the imbalance, so even a CI that excludes 0 here is not a certified "
         "gate effect.")
st.caption(f"For reference, at {POWER0:.0%} power and α = {alpha:.2f} this subset's design can reliably detect D7 "
           f"changes of about ±{c7['mde_abs'] * 100:.2f} pp and D1 changes of about ±{c1_['mde_abs'] * 100:.2f} pp. "
           "That describes the design; whether a difference is distinguishable from 0 is read off its interval above.")

# ---------------------------------------------------------------- 6. re-test sizing
st.subheader("6 · Re-test sizing, if the gate position matters commercially")
r1, r2, r3, r4 = st.columns(4)
kpi(r1, "Smallest D7 change to act on", f"{sesoi * 100:.1f} pp", "per install · placeholder",
    help="Fixed before the test and pre-registered, never taken from the observed effect: "
         f"≈{sesoi / RT['baseline_d7_install']:.1%} of gate_30's {RT['baseline_d7_install']:.1%} D7. A placeholder "
         "in config.yaml (gate_smallest_d7_change_pp) to agree with the Game PM.")
kpi(r2, "Installs needed · 30+ analysis", f"≈{need_reach / 1e3:,.0f}K",
    f"≈{RT['reachers_needed_5050'] / 1e3:,.0f}K with 30+ rounds · 50/50",
    help=f"Primary analysis among players who reach level 30 (30+ rounds; who gets there is decided before the gate), "
         f"pre-registered: {RT['reachers_needed_5050']:,} such players at 50/50, {need_reach:,} installs at the "
         f"{RT['share_reached_30']:.1%} of installs who get there. For them, {sesoi * 100:.1f} pp per install is "
         f"{RT['equivalent_change_among_reachers'] * 100:.2f} pp on a {RT['baseline_d7_reachers']:.1%} D7 base. Sized "
         f"to detect a {sesoi * 100:.1f} pp drop; a rise of the same size needs slightly more: "
         f"≈{RT['installs_needed_reacher_analysis_5050_if_rise'] / 1e3:,.1f}K installs "
         f"({RT['reachers_needed_5050_if_rise']:,} such players). The reacher figure uses this cohort's "
         f"{RT['share_reached_30']:.1%} reaching level 30; re-check with the new cohort's share before launch.")
rise_all = RT["installs_needed_install_level_5050_if_rise"] / need_all - 1
kpi(r3, "Installs needed · all installs", f"≈{need_all / 1e3:,.0f}K", "install-level analysis · 50/50",
    help=f"{need_all:,} installs at 50/50 for {POWER0:.0%} power at α = {ALPHA0:.2f} if the same change is analysed "
         f"over all installs. Sized to detect a {sesoi * 100:.1f} pp drop; a rise of the same size needs "
         f"≈{rise_all:.0%} more (≈{RT['installs_needed_install_level_5050_if_rise'] / 1e3:,.0f}K).")
kpi(r4, "MDE as run (design)", f"D7 {g7['mde']['mde_abs'] * 100:.2f} pp",
    f"D1 {g1['mde']['mde_abs'] * 100:.2f} pp · {POWER0:.0%} power",
    help=f"The smallest true change this test's design detects with {POWER0:.0%} power at α = {ALPHA0:.2f}. It "
         "describes the design and is never compared with an estimate.")
takeaway(f"Sized at a change fixed in advance, never at the observed effect: pre-register {sesoi * 100:.1f} pp of D7 "
         f"per install as the smallest change worth acting on (a placeholder to agree with the Game PM, "
         f"≈{sesoi / RT['baseline_d7_install']:.1%} of gate_30's {RT['baseline_d7_install']:.1%}). With the primary "
         "analysis among players who reach level 30 (30+ rounds), that needs "
         f"≈{RT['reachers_needed_5050'] / 1e3:,.0f}K such players, ≈{need_reach / 1e3:,.0f}K installs at 50/50; "
         f"analysed over all installs, ≈{need_all / 1e3:,.0f}K. Add a daily 50/50 group-size check. If the true "
         f"effect is smaller than {sesoi * 100:.1f} pp, it would not change the decision.")

# ---------------------------------------------------------------- 7. decision
st.subheader("7 · Decision")
with st.container(border=True):
    st.markdown(
        "**Keep the first gate at level 30 (no change); don't ship gate_40 (R5, Game PM). The result is not "
        "certified.**\n\n"
        f"- **Why:** there is no sign of a retention benefit. The part of the D7 gap the gate could explain is "
        f"≈{sgn(DEC['within_reached_30'] * 100, 1)} pp per install (95% CI {ci(*dec_ci)}; ≈{players(per10k[0])} "
        "Day-7 players per 10,000 installs), possibly zero, and even that may not be the gate.\n"
        f"- **Descriptive engagement difference:** among players with 30+ rounds (who could have reached level 30), "
        f"gate_40 players played a little more (median {RR['median_t']:.0f} vs {RR['median_c']:.0f} rounds). "
        "Assignment is uncertified and the group is defined by rounds played, so this does not show that gate_40 "
        "causes more play. If the Game PM values that, a clean re-test is the "
        "way to decide.\n"
        f"- **First · Eng + Analytics:** fix assignment and logging (gate_40 received ≈{extra_round:,} extra "
        f"installs, with a net excess of {lt15['net_excess_t']:,} among players with < 15 rounds): bucketing code, "
        "how each version was rolled out, install and crash logs by version.\n"
        f"- **Re-test only if the gate position matters commercially:** pre-register a {sesoi * 100:.1f} pp D7 change "
        "per install as the smallest change worth acting on (agree with the Game PM); "
        f"≈{need_reach / 1e3:,.0f}K installs at 50/50 with the primary analysis among players who reach level 30 "
        f"(≈{RT['reachers_needed_5050'] / 1e3:,.0f}K of them), ≈{need_all / 1e3:,.0f}K if analysed over all "
        "installs; daily 50/50 group-size check (calculator on page 7).\n"
        f"- **Main risk:** quoting the raw {pp(g7['abs_lift'])} would overstate the effect; missing a small real "
        "effect either way.")

n_boot = int(RES["config"]["n_bootstrap"])
how_to_read(f"""
**Why the naive result comes first, and why it is not certified.** It is what a default dashboard would show: gate_40
vs gate_30 over every install. Before it can be signed off, the split has to pass its sample-ratio check, and here it
does not, so the rest of the page works out how much of the gap could be the gate.

**Retention and bootstrap charts.** Share of players who came back on Day 1 (D1) and Day 7 (D7) after installing, per
version, with 95% intervals, and {n_boot:,} re-simulations of each difference. Both are the naive comparison, so they
carry the imbalance with them.

**Sample ratio.** A test set to split installs 50/50 should end up very close to 50/50. An imbalance this large is unlikely
under fair 50/50 assignment (about 1 time in 100 here). Most likely assignment or logging added low-engagement installs
to gate_40 (or dropped them from gate_30); Engineering confirms the cause. It is checked on the raw assignment counts.
Here {p_eq(SRM['p_value'])} is below the
{SRM['warn_threshold']:g} warning line but above the {SRM['threshold']:g} hard stop: the direction of the result is
informative; its size is not certified. The rounds bands were chosen after seeing the warning, so their p-values
describe where the excess sits; they are not tests.

**What "30+ rounds" means.** Rounds are counted over the first 14 days and every level takes at least one round, so a
player with fewer than 30 rounds cannot have got past level 30, and up to level 30 the two versions are identical (at
exactly 29 rounds, a gate_30 player who won every round can already face the gate). "30+ rounds" therefore means
"could have reached level 30"; the data has no level field.

**Why splitting by rounds is allowed here, when splitting the ad test by ads seen is not.** Ads can change how long a
user stays from the first impression, so the number of ads seen can itself be an effect of the treatment. Below level
30 both game versions are identical, so whether a player ever plays 30 rounds cannot depend on the gate: it behaves like
a trait fixed before the gate. It is an approximation: a gate_30 player who won each of 29 rounds would already face the
gate. Such players are few (no pile-up at 29 rounds: {b29['n_t']:,} gate_40 vs {b29['n_c']:,} gate_30 players), and
without the 29-round players the 15–28 band still shows {pp(b1528['abs_lift'])} (95% CI
{ci(b1528['abs_ci_low'], b1528['abs_ci_high'])}). So the rounds bands are close to, not exactly, gate-free. This is one
reason the 30+ part of the gap is called "the part the gate could explain", not an estimate of the gate's effect.

**Engagement curve gap.** For each N, the gap between the versions in the share of players who played at least N
rounds. In the grey zone (before any gate) the versions are identical by design, so the curve should hug 0; it sits
below 0 because gate_40 has extra low-round installs. It is the same imbalance, not a second piece of evidence.

**Negative control.** Players with fewer than 30 rounds never met a gate, so their D7 should not differ by version. A
gap there points at the imbalance or at chance, not at the gate. Here it is borderline ({p_eq(ncr['p_value'])}). Such
gap as there is comes from the 15–29 band rather than the < 15 band where the net excess sits, though the two bands'
gaps are not distinguishable from each other ({p_eq(BGD['p_value'])}).

**Decomposition.** The bars add up exactly to the naive D7 gap. The grey parts sit where the gate cannot act (a
different player mix; players who never met a gate); the blue part, with its 95% interval, is what the gate could
explain.

**Best case for gate_40.** The reading most favourable to gate_40: every extra install was a junk install that never
returned. Removing them still leaves {pp(BEST['d7_diff_if_excess_removed'])}, with an interval that includes 0.

**Guardrails.** The case for a later gate is that players would play more before hitting it. All-player guardrails
carry the same imbalance as D7, so they are read among players with 30+ rounds, who could meet the gate. For Day 1
that band is a diluted read ({D1_DILUTED}), so the D1 number is the part the gate could explain per install
({pp(DEC1['within_reached_30'])}, 95% CI {ci(*dec1_ci)}).

**Sensitivity panel.** It re-runs the naive comparison under other reasonable choices: a stricter α, leaving out
players who never played, dropping heavy players. Do not hunt for the filter that gives the answer you like: that is
p-hacking. Filtering on rounds played also uses something measured after assignment, which is fine as a robustness
check but not as the main estimate. Every "lower / inconclusive" statement is read off the interval shown with it.

**Re-test sizing and the MDE.** A test is sized before it runs, at the smallest change worth acting on, agreed in
advance; never at the effect a previous test happened to show. The MDE as run (D7 {g7['mde']['mde_abs'] * 100:.2f} pp,
D1 {g1['mde']['mde_abs'] * 100:.2f} pp at {POWER0:.0%} power) describes this test's design: compare it with the change
you care about, never with an estimate.

**Common misreadings.**
- "Moving the gate to level 40 takes {abs(g7['abs_lift']) * 100:.2f} pp off D7." That is the naive gap. About
  {round(not_gate_share * 10) * 10:.0f}% of it sits where the gate cannot act, and the part the gate could explain
  (about {abs(DEC['within_reached_30']) * 100:.2f} pp per install) may be zero.
- "{p_eq(SRM['p_value'])} on the sample-ratio check is fine." For a sample-ratio check that is a warning sign.
- "The naive D1 {pp(g1['abs_lift'])} shows a Day-1 problem." It carries the same imbalance (player mix
  {pp(DEC1['composition'])}); the part the gate could explain is {pp(DEC1['within_reached_30'])} per install (95% CI
  {ci(*dec1_ci)}).
- "gate_40 players play more, so gate_40 is better." Players with 30+ rounds play a little more under gate_40, but their
  D7 is not higher: no sign of a retention benefit.
- "Players who reach round 30 retain much better, so push everyone to round 30." Rounds are counted over 14 days and
  overlap the Day-7 window, so engaged players both play more and come back more: correlation, not a lever.
""")

# ---------------------------------------------------------------- phones
# A wide markdown table scrolls inside itself instead of pushing the whole page sideways; the label
# column keeps a readable width.
st.markdown("<style>@media (max-width: 640px) {"
            "[data-testid='stMarkdownContainer'] table {display: block; overflow-x: auto; max-width: 100%;}"
            "[data-testid='stMarkdownContainer'] th, [data-testid='stMarkdownContainer'] td {min-width: 4.5rem;}"
            "[data-testid='stMarkdownContainer'] td:first-child {min-width: 9rem;}"
            "}</style>", unsafe_allow_html=True)
