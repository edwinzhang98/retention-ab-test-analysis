"""Page 6 · Gate experiment (Cookie Cats): should the first gate move from level 30 to 40?

Order: the sample-ratio check first (raw assignment counts), then the integrity
checks that locate the imbalance and size how much of the naive D7 gap it
explains, then the naive D1 / D7 result (not certified), the guardrails, a live
sensitivity panel and the decision. Headline numbers come from
reports/results.json; the sensitivity panel re-runs the comparison on subsets of
fct_game_players. Every "significant / not significant" statement on the page is
read off the confidence interval it sits next to.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (C, F, R, S, caveat, fmt_pct, fmt_pp, how_to_read, load_cache, load_catalog_takeaways,
                    load_results, page_header, show, takeaway)

RES = load_results()
G = RES["cookie"]["gate"]
SRM = G["srm"]
SBS = G["srm_by_stratum"]
NC = G["negative_control"]
DEC = G["d7_decomposition"]
WC = G["worst_case_bound"]
PG = G["pre_gate_engagement"]
RT = G["retest_sizing"]
RD = G["rounds"]
DROPPED = RES["data_quality"]["cookie"]["outliers_dropped"]
CAT = load_catalog_takeaways()
BOOT = load_cache("boot_gate_lift")
ALPHA0 = float(RES["config"]["alpha"])
POWER0 = float(RES["config"]["power"])

T_ARM, C_ARM = "gate_40", "gate_30"
NO_CAP = C.GAMEROUNDS_OUTLIER_MAX          # the project's outlier rule; above the cleaned max
CAPS = [100, 250, 500, 1000, 2000, NO_CAP]
ALPHAS = [0.10, 0.05, 0.01]
STRATA = {"rounds_lt_15": "Fewer than 15 rounds",
          "rounds_lt_30": "Fewer than 30 rounds (never met a gate)",
          "rounds_ge_30": "30 or more rounds (could meet the gate)"}


# ------------------------------------------------------------------ helpers
def conf(alpha: float) -> str:
    return f"{(1 - alpha) * 100:g}%"


def pp_range(lo: float, hi: float) -> str:
    return f"{lo * 100:+.2f} to {hi * 100:+.2f} pp"


def ci_short(lo: float, hi: float) -> str:
    """Interval in pp without the unit, for the small metric notes."""
    return f"{lo * 100:+.2f} to {hi * 100:+.2f}"


def p_text(p: float) -> str:
    """p-value for display: never prints 0, two significant digits above 0.001."""
    if p < 1e-4:
        return "< 0.0001"
    return f"{p:.4f}" if (p < 1e-3 or p > 0.99) else f"{p:.2g}"


def p_eq(p: float) -> str:
    s = p_text(p)
    return f"p {s}" if s.startswith("<") else f"p = {s}"


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


def ci_verdict(m: dict, name: str, level: str) -> str:
    """Plain-language reading of one gate_40 − gate_30 difference, taken from its CI only."""
    lo, hi = m["abs_ci_low"], m["abs_ci_high"]
    if hi < 0:
        return f"{name} is lower in gate_40 (the {level} CI excludes 0)"
    if lo > 0:
        return f"{name} is higher in gate_40 (the {level} CI excludes 0)"
    return (f"{name} is inconclusive (the {level} CI includes 0): a drop of up to {abs(lo) * 100:.1f} pp is "
            "not ruled out")


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


# ------------------------------------------------------------------ page
page_header("Gate Experiment (Cookie Cats)", "Should the first gate move from level 30 to level 40?")

# ---------------------------------------------------------------- SRM first (raw assignment counts)
status = SRM["status"]
n_t, n_c = SRM["n_t"], SRM["n_c"]
share_i = SRM["intended_share_t"]
srm_line = (f"The split was meant to be {(1 - share_i) * 100:.0f}/{share_i * 100:.0f} but the raw assignment "
            f"counts are {n_c:,} gate_30 vs {n_t:,} gate_40 ({SRM['observed_share_t']:.2%} in gate_40 instead of "
            f"{share_i:.0%}). Chi-square {p_eq(SRM['p_value'])}")
warn_line = f"the {SRM['warn_threshold']:g} warning line (project convention)"
fail_line = f"the {SRM['threshold']:g} hard-fail line (Kohavi et al. convention)"
if status == "WARNING":
    caveat(f"<b>Sample ratio mismatch: WARNING.</b> {srm_line}: between {warn_line} and {fail_line}. A warning "
           "blocks certification: the comparisons below show the direction of the result, not a size we can sign "
           "off. The integrity checks locate the imbalance and estimate how much of the D7 gap it explains.")
elif status == "FAIL":
    caveat(f"<b>Sample ratio mismatch: FAIL.</b> {srm_line}: below {fail_line}. Treat every number on this page as "
           "untrustworthy until the assignment is fixed.")
else:
    st.caption(f"Sample ratio check passed. {srm_line}.")

ncr = NC["never_reached_30"]["retention_7"]
dec_ci = DEC["install_level_effect_ci_if_only_reachers"]
g7, g1 = G["retention_7"], G["retention_1"]
with st.container(border=True):
    st.markdown(
        f"**Readout in one line.** The naive comparison says gate_40 lowers D7 retention by "
        f"{abs(g7['abs_lift']) * 100:.2f} pp, but the arms are unbalanced. Once that is separated out, the part the "
        f"gate could cause is {fmt_pp(DEC['within_reached_30'])} per install (95% CI {pp_range(*dec_ci)}): "
        "probably small, possibly zero, with no sign of a benefit. **Keep gate_30; fix assignment before any "
        "re-test. The result is not certified.**")

# ---------------------------------------------------------------- integrity checks
st.subheader("1 · Integrity checks: where does the imbalance come from?")
i1, i2, i3, i4 = st.columns(4)
kpi(i1, "Extra players", f"{WC['excess_players_gate_40']:,}",
    f"{G['excess_players_with_lt_15_rounds']:,} with < 15 rounds",
    help="gate_40 minus gate_30 players in the analysis table; the second number comes from the raw counts of "
         "players with fewer than 15 rounds.")
kpi(i2, "Negative control", fmt_pp(ncr["abs_lift"]), f"D7, {p_eq(ncr['p_value'])}",
    help="D7 difference among players with fewer than 30 rounds, who never reached either gate, so their retention "
         f"should not differ by version. 95% CI {pp_range(ncr['abs_ci_low'], ncr['abs_ci_high'])}.")
kpi(i3, "Gate could cause", fmt_pp(DEC["within_reached_30"]), f"CI {ci_short(*dec_ci)}",
    help="The part of the naive D7 gap that sits with players who reached level 30, in pp per install, with its "
         "95% CI.")
kpi(i4, "Worst case", fmt_pp(WC["d7_diff_if_excess_removed"]),
    f"if {WC['excess_players_gate_40']:,} never returned",
    help=f"The naive D7 gap if all {WC['excess_players_gate_40']:,} extra gate_40 players had never come back on "
         "Day 7 (removed from gate_40 with no retained players).")

st.markdown("**Where are gate_40's extra players?** Sample ratio within groups defined by play before any gate")
srm_rows = [(label, SBS[key]) for key, label in STRATA.items()] + [("All players", SRM)]
status_text = {"FAIL": "**FAIL-level**", "WARNING": "**WARNING**", "PASS": "Balanced"}
table = ["| Players with | gate_30 | gate_40 | gate_40 − gate_30 | Share in gate_40 | Chi-square p | Status |",
         "|---|---:|---:|---:|---:|---:|---|"]
for label, s in srm_rows:
    table.append(f"| {label} | {s['n_c']:,} | {s['n_t']:,} | {s['n_t'] - s['n_c']:+,} | {s['observed_share_t']:.2%} "
                 f"| {p_text(s['p_value'])} | {status_text.get(s['status'], s['status'])} |")
st.markdown("\n".join(table))
lt15, lt30, ge30 = SBS["rounds_lt_15"], SBS["rounds_lt_30"], SBS["rounds_ge_30"]
takeaway(f"The imbalance sits with players who never reached level 30: gate_40 has {lt30['n_t'] - lt30['n_c']:,} more "
         f"of them ({p_eq(lt30['p_value'])}), {lt15['n_t'] - lt15['n_c']:,} of whom played fewer than 15 rounds "
         f"({p_eq(lt15['p_value'])}). Players with 30+ rounds are balanced ({p_eq(ge30['p_value'])}). Play below level "
         "30 happens before either gate, so the gate cannot have caused this: something added low-engagement "
         "installs to gate_40 (assignment or logging).")
dropped = ", ".join(f"{o['version']}, {o['sum_gamerounds']:,} rounds" for o in DROPPED)
st.caption(f"Raw assignment counts, before {len(DROPPED)} logging-error player ({dropped}) was dropped, so the total "
           f"gap here is {n_t - n_c:,} and {WC['excess_players_gate_40']:,} in the analysis table. The < 15 rows are "
           "a subset of the < 30 rows.")

curve = version_curve()
show(F.fig_engagement_gap(curve, G["players"][T_ARM], G["players"][C_ARM],
                          "Engagement curve gap, gate_40 − gate_30 (pp of players, pointwise 95% CI)"),
     key="p6_gap")
takeaway(CAT["gate_engagement_gap"])

nc_rows = pd.DataFrame([
    {"label": "All players (primary result)", "role": "main", **g7},
    {"label": "Never reached level 30 (negative control)", "role": "control", **ncr},
    {"label": "Reached level 30", "role": "other", **NC["reached_30"]["retention_7"]},
])
show(F.fig_effect_by_stratum(nc_rows, "D7 retention difference by stratum: a negative-control check (pp, 95% CI)"),
     key="p6_negative_control")
takeaway(CAT["gate_negative_control"])

parts = pd.DataFrame([
    {"label": "Naive gap (all players)", "value": DEC["naive_diff"], "role": "total"},
    {"label": "Player mix (extra low-engagement players)", "value": DEC["composition"], "role": "artifact"},
    {"label": "Players who never met a gate", "value": DEC["within_never_reached_30"], "role": "artifact"},
    {"label": "Players who could meet the gate", "value": DEC["within_reached_30"], "role": "effect",
     "ci_low": dec_ci[0], "ci_high": dec_ci[1]},
])
show(F.fig_gap_decomposition(parts, "Where the naive D7 gap comes from (pp of installs)"), key="p6_decomposition")
takeaway(CAT["gate_decomposition"])

# ---------------------------------------------------------------- naive result
st.subheader("2 · Result: D1 and D7 retention (naive comparison, not certified)")
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "D7 retention, gate_40", fmt_pct(g7["rate_t"]), f"gate_30: {fmt_pct(g7['rate_c'])}")
kpi(k2, "D7 difference (naive)", fmt_pp(g7["abs_lift"]), f"95% CI {ci_short(g7['abs_ci_low'], g7['abs_ci_high'])}",
    help=f"gate_40 − gate_30, all {g7['n_t'] + g7['n_c']:,} players, {p_eq(g7['p_value'])}. Includes the imbalance "
         "shown above, so it overstates what the gate itself did.")
kpi(k3, "D1 retention, gate_40", fmt_pct(g1["rate_t"]), f"gate_30: {fmt_pct(g1['rate_c'])}")
kpi(k4, "D1 difference (naive)", fmt_pp(g1["abs_lift"]), f"95% CI {ci_short(g1['abs_ci_low'], g1['abs_ci_high'])}",
    help=f"gate_40 − gate_30, {p_eq(g1['p_value'])}.")
show(F.fig_gate_rates(G, "D1 and D7 retention by gate version (%, 95% CI)"), key="p6_rates")
takeaway(CAT["gate_rates"])
show(F.fig_gate_bootstrap(BOOT, G, "Bootstrap distribution of gate_40 − gate_30 retention (pp)"), key="p6_boot")
takeaway(CAT["gate_bootstrap"])

# ---------------------------------------------------------------- guardrails
st.subheader("3 · Guardrails: Day 1 and rounds played")
w1, w2, w3, w4 = st.columns(4)
kpi(w1, "D1 drop not ruled out", f"{abs(g1['abs_ci_low']) * 100:.1f} pp",
    f"95% CI {ci_short(g1['abs_ci_low'], g1['abs_ci_high'])}",
    help="The low end of the D1 confidence interval: the largest D1 drop (gate_40 vs gate_30) the data still "
         "allows.")
kpi(w2, "Mean rounds diff.", f"{RD['mean_diff']:+.2f}",
    f"95% CI {RD['mean_diff_boot_ci'][0]:+.2f} to {RD['mean_diff_boot_ci'][1]:+.2f}",
    help=f"gate_40 − gate_30 mean rounds in the first 14 days ({RD['mean_t']:.2f} vs {RD['mean_c']:.2f}); "
         f"user-level bootstrap with {RD['n_boot']:,} resamples, because rounds are heavy-tailed.")
kpi(w3, "Median rounds", f"{RD['median_c']:.0f} vs {RD['median_t']:.0f}",
    f"Mann–Whitney {p_eq(RD['mannwhitney_p'])}",
    help="gate_30 vs gate_40. The rank test compares the whole distribution of rounds played, not just the median.")
kpi(w4, f"D7 MDE, {POWER0:.0%} power", f"±{g7['mde']['mde_abs'] * 100:.2f} pp",
    f"D1: ±{g1['mde']['mde_abs'] * 100:.2f} pp",
    help=f"The smallest true difference this sample detects with {POWER0:.0%} power at α = {ALPHA0:.2f}: a property "
         "of the design, not a verdict on the observed gap.")
takeaway(f"No engagement difference: mean rounds played differ by {RD['mean_diff']:+.2f} (gate_40 − gate_30; "
         f"bootstrap 95% CI {RD['mean_diff_boot_ci'][0]:+.2f} to {RD['mean_diff_boot_ci'][1]:+.2f}, {RD['n_boot']:,} "
         f"resamples) and the medians are {RD['median_c']:.0f} vs {RD['median_t']:.0f} ({p_eq(RD['mannwhitney_p'])}). "
         f"The case for a later gate was more play before the gate, and it does not show up. D1 is "
         f"{fmt_pp(g1['abs_lift'])} (95% CI "
         f"{pp_range(g1['abs_ci_low'], g1['abs_ci_high'])}): a D1 drop of up to "
         f"{abs(g1['abs_ci_low']) * 100:.1f} pp cannot be ruled out.")

# ---------------------------------------------------------------- sensitivity
st.subheader("4 · Sensitivity: does the naive result move?")
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
                        sig_col="excludes_0", sig_label="CI excludes 0", nonsig_label="CI includes 0",
                        xtitle="gate_40 − gate_30 retention (pp)")
# the forest's default hover describes segment contrasts; this chart compares checks of one experiment
fig.update_traces(hovertemplate="<b>%{y}</b><br>Difference %{x:.2f} pp (CI %{customdata[7]:.2f} to "
                                "%{customdata[8]:.2f})<br>gate_40 %{customdata[0]:.2f}% (n=%{customdata[2]:,.0f})"
                                "<br>gate_30 %{customdata[1]:.2f}% (n=%{customdata[3]:,.0f})"
                                "<br>p = %{customdata[4]:.4f}<extra></extra>")
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
d1_text = ci_verdict(c1, "D1", level)
if c1["abs_ci_high"] < 0 and not is_headline:
    d1_text += ("; this is one of several cuts tried, so read it as consistent with a D1 drop rather than proof "
                "of one")
takeaway(f"{scope}: D7 {fmt_pp(c7['abs_lift'])} ({level} CI {pp_range(c7['abs_ci_low'], c7['abs_ci_high'])}) and D1 "
         f"{fmt_pp(c1['abs_lift'])} ({level} CI {pp_range(c1['abs_ci_low'], c1['abs_ci_high'])}). {d7_text}; "
         f"{d1_text}. None of these cuts fixes the imbalance, so even a CI that excludes 0 here is not a certified "
         "gate effect.")
st.caption(f"For reference, at {POWER0:.0%} power and α = {alpha:.2f} this subset can reliably detect D7 changes of "
           f"about ±{c7['mde_abs'] * 100:.2f} pp and D1 changes of about ±{c1['mde_abs'] * 100:.2f} pp. The MDE "
           "describes the design; whether a difference is distinguishable from 0 is read off its interval above.")

# ---------------------------------------------------------------- decision
st.subheader("5 · Decision")
reach = NC["reached_30"]["retention_7"]
with st.container(border=True):
    st.markdown(
        "**Keep the first gate at level 30 (R5, Game PM). The result is not certified.**\n\n"
        f"- **No sign of any benefit from gate_40.** Both retention estimates point down (naive D7 "
        f"{fmt_pp(g7['abs_lift'])}, D1 {fmt_pp(g1['abs_lift'])}) and rounds played are unchanged "
        f"({RD['mean_diff']:+.2f} on average). Keeping gate_30 is the status quo and costs nothing.\n"
        f"- **The naive {fmt_pp(g7['abs_lift'])} overstates the likely effect.** gate_40 received about "
        f"{WC['excess_players_gate_40']:,} extra low-engagement installs ({p_eq(SRM['p_value'])} on the split), and "
        f"even players who never met a gate differ ({fmt_pp(ncr['abs_lift'])} D7). The part the gate could cause "
        f"is about {fmt_pp(DEC['within_reached_30'])} per install (95% CI {pp_range(*dec_ci)}) and may be zero.\n"
        "- **Next · Eng + Analytics:** fix assignment and logging first: bucketing code, how each version was "
        "rolled out, install and crash logs by version.\n"
        "- **Re-test only if the gate placement matters commercially.** Detecting the "
        f"{fmt_pp(reach['abs_lift'])} seen among players who reach level 30 needs about "
        f"{RT['reachers_needed_total_5050'] / 1e3:,.0f}K such players, roughly "
        f"{RT['installs_needed_total_5050'] / 1e3:,.0f}K installs at 50/50, with D7 as the primary metric and D1 and "
        "rounds played as guardrails (calculator on page 7).")

n_boot = int(RES["config"]["n_bootstrap"])
how_to_read(f"""
**Why the sample-ratio check comes first.** A test set to split users 50/50 should end up very close to 50/50.
An imbalance bigger than chance allows means something in assignment or logging went wrong, for example one
version gaining installs that were never really in the test. That can bias every metric on the page, so it is
checked before anything else, on the raw assignment counts. Here the imbalance ({p_eq(SRM['p_value'])}) is past
the {SRM['warn_threshold']:g} warning line but not the {SRM['threshold']:g} hard-fail line: the direction of the
result is informative; its size is not certified.

**Integrity checks.** Players who never reached level 30 never met either gate, and their play before level 30 cannot
depend on the version. So any difference among them is a symptom of the imbalance, not an effect of the gate:
- *Sample ratio by stratum.* The split is checked separately for players with fewer than 15, fewer than 30, and 30 or
  more rounds. Only the low-engagement groups are out of balance.
- *Engagement curve gap.* For each N, the gap between the versions in the share of players who played at least N
  rounds. In the grey zone (before any gate) the versions are identical by design, so the curve should hug 0; it sits
  below 0 (rounds capped at 29: mean {PG['mean_capped_29_c']:.2f} gate_30 vs {PG['mean_capped_29_t']:.2f} gate_40,
  Mann–Whitney {p_eq(PG['mannwhitney_p'])}).
- *Negative control.* The D7 difference among players who never met a gate. It should be 0; it isn't quite.
- *Decomposition.* The bars add up to the naive D7 gap. Grey parts cannot be caused by the gate (different player mix,
  players who never met a gate); the blue part is what the gate could have caused, with its 95% interval.
- *Worst-case bound.* Even if every extra gate_40 player had never returned, gate_40's D7 would still be
  {abs(WC['d7_diff_if_excess_removed']) * 100:.2f} pp lower: no reading of the data shows the later gate helping.

**Retention and bootstrap charts.** Share of players who came back on Day 1 (D1) and Day 7 (D7) after installing, per
version, with 95% intervals, and {n_boot:,} re-simulations of each difference. Both are the naive comparison, so they
carry the imbalance with them.

**Guardrails.** The case for a later gate is that players would play more before hitting it; rounds played say they
don't. D1 is the earliest retention signal; its interval still allows a drop of about
{abs(g1['abs_ci_low']) * 100:.1f} pp.

**Sensitivity panel.** It re-runs the naive comparison under other reasonable choices: a stricter α, leaving out
players who never played, dropping heavy players. Do not hunt for the filter that gives the answer you like: that is
p-hacking. Filtering on rounds played also uses something measured after assignment, which is fine as a robustness
check but not as the main estimate. Every "lower / inconclusive" statement is read off the interval shown with it.

**Common misreadings.**
- "gate_40 costs {abs(g7['abs_lift']) * 100:.2f} pp of D7." That is the naive gap, and part of it comes from extra
  low-engagement players and from players who never met a gate. The part the gate could cause is about
  {abs(DEC['within_reached_30']) * 100:.2f} pp per install, and may be zero.
- "{p_eq(SRM['p_value'])} on the SRM is fine." For a sample-ratio check that is a warning sign, not a pass.
- "D1 isn't significant, so D1 is unaffected." The interval allows a D1 drop of up to
  {abs(g1['abs_ci_low']) * 100:.1f} pp.
- "Players who reach round 30 retain much better, so push everyone to round 30." Rounds are counted over 14 days and
  overlap the Day-7 window, so engaged players both play more and come back more: correlation, not a lever.
""")
