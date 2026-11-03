"""Page 7 · Decision & Recommendations: what to do, who owns it, how we will know it
worked, and a sample-size calculator for the next experiment (src.stats power functions).
"""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from common import C, F, S, caveat, how_to_read, load_cache, load_results, page_header, show, takeaway

res = load_results()
ad, ck = res["ad"], res["cookie"]
t, bz, pw = ad["test"], ad["business"], ad["power"]
inc, be = bz["incremental_conversions"], bz["breakeven_cpm_usd"]
het = ad["heterogeneity"]
h_day, h_hour = het["most_ads_day"], het["most_ads_hour"]
gate = ck["gate"]
g1, g7, gsrm = gate["retention_1"], gate["retention_7"], gate["srm"]
by_d1 = {r["d1_status"]: r for r in ck["by_d1_status"]}
low = [r for r in ck["by_rounds_bucket"] if r["rounds_bucket"] in ("0", "1-4", "5-14")]  # < 15 rounds
low_n, low_share = sum(r["players"] for r in low), sum(r["share_of_players"] for r in low)
low_d7_max = max(r["retention_7"] for r in low)
d1_ratio = by_d1["Returned Day 1"]["retention_7"] / by_d1["Did not return Day 1"]["retention_7"]
n10 = pw["total_n_for_10pct_rel_lift"]
value = bz["value_per_conversion_usd"]
plan = ad["srm"]["intended_share_t"]            # the ad test's (inferred) 96/4 design
split_now = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
p_psa = t["conv_c"] / t["n_c"]
n10_now = n10.get(str(plan)) or S.required_total_n(p_psa, 0.10 * p_psa, plan, C.ALPHA, C.POWER)


@st.cache_data(show_spinner=False)
def exposure_lifts() -> pd.DataFrame:
    return S.segment_lifts(load_cache("agg_ad_cells"), "exposure_bucket", "ad", "psa", alpha=C.ALPHA,
                           method="holm", order=C.EXPOSURE_LABELS).set_index("exposure_bucket")


expo = exposure_lifts()
# D7-retained players lost per gate_40 cohort (the CI bound closest to zero gives the low end)
d7_cost = {k: abs(g7[c]) * g7["n_t"]
           for k, c in (("point", "abs_lift"), ("low", "abs_ci_high"), ("high", "abs_ci_low"))}

# ------------------------------------------------------------------ header
page_header("Decision & Recommendations", "What should we do, who owns it, and how will we know it worked?")

# ------------------------------------------------------------------ decision summary
st.subheader("Decision per question")
DECISIONS = [
    ("Did the ad campaign drive conversions?", "KEEP", "green",
     "Keep the campaign running at the current budget (R1).",
     f"{t['abs_lift'] * 100:+.2f} pp conversion (95% CI {t['abs_ci_low'] * 100:.2f} to {t['abs_ci_high'] * 100:.2f}), "
     f"about {inc['point']:,.0f} incremental conversions; arm sizes and ad exposure match across arms.",
     "strong (randomized test, interval well above zero)."),
    ("Is it worth doubling the budget?", "TEST FIRST", "orange",
     "Do not double blindly; run a budget / frequency test (R2).",
     "The experiment did not vary budget. Lift looks flat beyond 200 ads per user (exploratory), and the dollar "
     f"value depends on an assumed USD {value:,.0f} per conversion.",
     "not answerable with this data."),
    ("Should spend move to the best day or hour?", "DON'T (YET)", "gray",
     "Keep the current schedule; pre-register a daypart test if it matters (R3).",
     f"Day interaction p = {h_day['lrt']['p_value']:.3f} (weak), hour p = {h_hour['lrt']['p_value']:.2f} (none); "
     f"{h_hour['n_sig_unadjusted']} of {h_hour['n_segments']} hours look significant before correction, "
     f"{h_hour['n_sig_holm']} after.",
     "weak for day, none for hour."),
    ("Which new users leave first?", "TEST", "blue",
     "Run a Day-1 onboarding / re-engagement experiment for players who stall early (R6).",
     f"Players with fewer than 15 rounds are {low_share * 100:.0f}% of installs with D7 at most "
     f"{low_d7_max * 100:.1f}%; Day-1 returners are {d1_ratio:.1f}× as likely to be back on Day 7.",
     "descriptive and correlational."),
    ("Should the first gate move from level 30 to 40?", "DON'T SHIP", "red",
     "Keep the gate at level 30; debug assignment before any re-test (R5).",
     f"D7 {g7['abs_lift'] * 100:+.2f} pp (95% CI {g7['abs_ci_low'] * 100:.2f} to {g7['abs_ci_high'] * 100:.2f}); "
     f"D1 {g1['abs_lift'] * 100:+.2f} pp (p = {g1['p_value']:.3f}, not conclusive); sample-ratio warning "
     f"(p = {gsrm['p_value']:.4f}).",
     "moderate (interval excludes zero, but the sample-ratio warning blocks certification)."),
]
for question, verdict, color, action, evidence, strength in DECISIONS:
    with st.container(border=True):
        q, v, w = st.columns([2.3, 1.2, 5.5], gap="medium", vertical_alignment="center")
        q.markdown(f"**{question}**")
        with v:
            st.badge(verdict, color=color)
        w.markdown(f"**{action}** {evidence}")
        w.caption(f"Strength of evidence: {strength}")

# ------------------------------------------------------------------ recommendations
st.subheader("Recommendations")
st.caption("Each item: who owns it, what to do, the expected impact (from this analysis), how we will measure it, "
           "and the main risk. Impact numbers are point estimates with 95% intervals where they exist.")
RECS = pd.DataFrame([
    {"ID": "R1", "Who": "Growth PM",
     "What": "Keep the ad campaign running at the current budget, with an always-on 5-10% PSA holdout.",
     "Expected impact": f"About {inc['point']:,.0f} incremental conversions per comparable flight (95% CI "
                        f"{inc['ci_low']:,.0f} to {inc['ci_high']:,.0f}); "
                        f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}% of ad-arm conversions are "
                        "incremental.",
     "How to measure": "Incremental conversion rate (ad minus holdout) and cost per incremental conversion, "
                       "reported every flight.",
     "Risk": f"Value and cost are not in the data. Confirm with Finance that the real CPM is below the breakeven "
             f"(USD {be['point']:.2f} at an assumed USD {value:,.0f} per conversion; 95% CI {be['ci_low']:.2f} to "
             f"{be['ci_high']:.2f})."},
    {"ID": "R2", "Who": "Growth PM + media buyer",
     "What": "Do not double the budget blindly. Run a randomized budget / frequency test first: 2x-budget or "
             "frequency-cap arms, 50/50 or 80/20 split, sized with the calculator below.",
     "Expected impact": f"Avoids paying for saturated impressions: lift was about zero for users with 20 ads or "
                        f"fewer, {expo.loc['51-100', 'abs_lift'] * 100:.1f} to "
                        f"{expo.loc['101-200', 'abs_lift'] * 100:.1f} pp at 51-200 ads, and indistinguishable from "
                        f"zero above 200 (only {int(expo.loc['200+', 'n_c'])} control users; exploratory).",
     "How to measure": "Marginal incremental conversions per extra USD 1K of spend (marginal iROAS) against the "
                       "current flight.",
     "Risk": "Saturation and ad fatigue at high frequency. Exposure was not randomized, so the dose-response "
             "pattern may reflect who uses the app most rather than the ads."},
    {"ID": "R3", "Who": "Media buyer",
     "What": "Do not re-plan spend by day or hour yet. If dayparting matters, pre-register a daypart test "
             f"(for example {h_day['max_lift_segment']} vs {h_day['min_lift_segment']}).",
     "Expected impact": f"Avoids moving budget on noise: lift ranged from {h_day['min_lift_pp']:.2f} pp "
                        f"({h_day['min_lift_segment']}) to {h_day['max_lift_pp']:.2f} pp ({h_day['max_lift_segment']}) "
                        f"but the day interaction test gives only p = {h_day['lrt']['p_value']:.3f}, and hour "
                        f"p = {h_hour['lrt']['p_value']:.2f}.",
     "How to measure": "Pre-registered difference in lift between the dayparts, with its 95% CI, in a test powered "
                       "for that difference.",
     "Risk": "Chasing noise. Day and hour are the user's peak-ad day and hour, recorded after assignment, not a "
             "randomized schedule."},
    {"ID": "R4", "Who": "Analytics + Engineering",
     "What": f"Fix the next experiment's design: 50/50 or 80/20 instead of {split_now}; log assignment "
             "timestamps; pre-register the primary metric and guardrails (unsubscribe / complaint rate, CPA).",
     "Expected impact": f"The same {t['n_t'] + t['n_c']:,} users split 50/50 detect "
                        f"{pw['mde_if_5050_same_total']['mde_abs'] * 100:.2f} pp instead of "
                        f"{pw['mde_current']['mde_abs'] * 100:.2f} pp. A 10% relative lift needs about "
                        f"{n10['0.5'] / 1e3:,.0f}K users at 50/50 vs {n10_now / 1e6:.2f}M at {split_now}.",
     "How to measure": "MDE and guardrails written down before launch; SRM passes against a documented split; "
                       "novelty checked with the timestamps.",
     "Risk": "A bigger control group means more users do not see the ad during the test (see the holdout cost in "
             "the calculator)."},
    {"ID": "R5", "Who": "Game PM",
     "What": "Keep the first progression gate at level 30. Investigate the sample-ratio warning (assignment logs) "
             "before any re-test of gate_40.",
     "Expected impact": f"Avoids a {abs(g7['abs_lift']) * 100:.1f} pp D7 drop: about {d7_cost['point']:,.0f} fewer "
                        f"D7-retained players per {g7['n_t']:,} installs (95% CI {d7_cost['low']:,.0f} to "
                        f"{d7_cost['high']:,.0f}).",
     "How to measure": "D7 retention (primary) and D1 (guardrail) in any re-test, reported only after the SRM "
                       "check passes.",
     "Risk": f"The SRM warning (p = {gsrm['p_value']:.4f}) means assignment may be biased, so the size of the effect "
             "is uncertain; keeping level 30 is the no-change default."},
    {"ID": "R6", "Who": "Onboarding PM",
     "What": "Focus retention work on the first session and Day 1: a Day-1 re-engagement / onboarding experiment "
             "for players who stall early (fewer than 15 rounds), with D7 retention as the primary metric.",
     "Expected impact": f"Targets {low_share * 100:.0f}% of installs ({low_n:,} players) whose D7 retention is at "
                        f"most {low_d7_max * 100:.1f}%. Day-1 returners are {d1_ratio:.1f}× as likely to be "
                        "retained on Day 7.",
     "How to measure": "Randomized test with D7 retention as primary and D1 as secondary metric; size it with the "
                       "calculator (D7 preset).",
     "Risk": "The rounds-retention link is correlational (rounds are counted over 14 days, overlapping Day 7); "
             "only the experiment can show that early engagement causes retention."},
]).set_index("ID")
st.table(RECS)
st.download_button("Download recommendations (CSV)", RECS.to_csv().encode("utf-8"), file_name="recommendations.csv",
                   mime="text/csv", key="p7_download_recs")

# ------------------------------------------------------------------ sample-size calculator
st.subheader("Sizing the next experiment")
st.markdown("How many users does the next test need? Two-sided test of two proportions (normal approximation with "
            "Cohen's h), the same method as the power numbers on page 4.")
MIN_WEEKS = 2  # minimum test length: every weekday covered at least twice
# Baselines from exact counts (results.json rates are rounded), so the default reproduces results.json's power numbers.
PRESETS = {"Ad test: conversion rate": p_psa,
           "Onboarding test: D7 retention": (g7["conv_t"] + g7["conv_c"]) / (g7["n_t"] + g7["n_c"])}


def apply_preset() -> None:
    st.session_state["p7_baseline"] = PRESETS[st.session_state["p7_preset"]] * 100


preset = st.radio("Start from", list(PRESETS), horizontal=True, key="p7_preset", on_change=apply_preset,
                  help=f"Ad test: the PSA (control) conversion rate in this experiment, "
                       f"{t['rate_c'] * 100:.2f}%. Onboarding test: overall D7 retention in Cookie Cats, "
                       f"{ck['overall']['retention_7'] * 100:.2f}%.")
if "p7_baseline" not in st.session_state:
    apply_preset()

r1 = st.columns(3, gap="medium")
baseline = r1[0].number_input("Baseline rate in control (%)", min_value=0.01, max_value=99.0, step=0.1,
                              format="%.2f", key="p7_baseline",
                              help="Expected rate without the change: conversion rate, retention rate, etc.")
rel_mde = r1[1].number_input("Smallest lift worth detecting (relative, %)", min_value=1.0, max_value=200.0,
                             value=10.0, step=1.0, format="%.1f", key="p7_rel_mde",
                             help="The minimum detectable effect (MDE): the smallest relative change that would "
                                  "change the decision. Smaller effects need many more users.")
share = r1[2].slider("Users in treatment (%)", min_value=50, max_value=99, value=50, step=1, key="p7_share",
                     help="50 = an even split. Uneven splits keep more users on the new experience but need a "
                          "larger total sample.")
r2 = st.columns(3, gap="medium")
alpha = r2[0].select_slider("Significance level (alpha)", options=[0.01, 0.05, 0.10], value=C.ALPHA,
                            format_func=lambda a: f"{a:g}", key="p7_alpha",
                            help="Chance of a false positive we accept when there is no real effect.")
power = r2[1].select_slider("Power", options=[0.70, 0.80, 0.90, 0.95], value=C.POWER,
                            format_func=lambda p: f"{p:.0%}", key="p7_power",
                            help="Chance of detecting the effect if it is really there at the MDE size.")
daily = r2[2].number_input("Eligible users per day", min_value=100, max_value=10_000_000, value=20_000, step=1_000,
                           key="p7_daily",
                           help="Illustrative default: the datasets have no dates, so traffic is unknown. Enter the "
                                "number of users per day who could enter the test.")

p_c = baseline / 100
p_t = p_c * (1 + rel_mde / 100)
if p_t >= 1:
    st.warning("Baseline × (1 + lift) must stay below 100%. Lower the baseline or the lift.")
else:
    eff = p_t - p_c

    def size(s: float) -> dict:
        n = S.required_total_n(p_c, eff, s, alpha, power)
        n_t = round(n * s)
        return {"total": n, "n_t": n_t, "n_c": n - n_t, "days": math.ceil(n / daily)}

    sel = size(share / 100)
    out = st.columns(3)
    out[0].metric("Total users needed", f"{sel['total']:,}", f"{sel['n_t']:,} treatment / {sel['n_c']:,} control",
                  delta_color="off", delta_arrow="off",
                  help=f"Sum of both arms at a {share}/{100 - share} split, rounded up.")
    out[1].metric(f"Days at {daily:,} users/day", f"{sel['days']:,}",
                  f"plan {max(MIN_WEEKS, math.ceil(sel['days'] / 7))} full weeks", delta_color="off",
                  delta_arrow="off",
                  help=f"Total users ÷ eligible users per day, rounded up. The plan rounds up to whole weeks, with "
                       f"a minimum of {MIN_WEEKS} (see the note below the table).")
    out[2].metric("Effect to detect", f"+{eff * 100:.2f} pp", f"{baseline:.2f}% to {p_t * 100:.2f}%",
                  delta_color="off", delta_arrow="off", help="Baseline × relative lift, in percentage points.")

    splits = sorted({0.5, 0.8, 0.9, plan, share / 100})
    base_5050 = size(0.5)["total"]
    rows = []
    for s in splits:
        z = size(s)
        label = f"{s * 100:.0f}/{(1 - s) * 100:.0f}" + (" (selected)" if math.isclose(s, share / 100) else "")
        rows.append({"Split": label, "Total users": z["total"], "vs 50/50": z["total"] / base_5050,
                     "Days": z["days"], "Holdout cost": round(z["n_c"] * eff)})
    scen = pd.DataFrame(rows)
    chart_col, table_col = st.columns(2, gap="large")
    with chart_col:
        max_pp = max(min(eff * 100 * 2.5, (0.999 - p_c) * 100), 0.1)
        fig = F.fig_power_curve(
            p_c, sel["n_t"], sel["n_c"], alpha, None, "Power of the planned test by true lift (%)",
            f"{sel['n_t']:,} treatment and {sel['n_c']:,} control users, alpha {alpha:g}.",
            max_lift_pp=max_pp, target_power=power)
        fig.update_xaxes(title_text="True lift in the metric (pp)")
        show(fig)
    with table_col:
        st.markdown("**The same test with other splits**")
        st.dataframe(scen, hide_index=True, width="stretch", column_config={
            "Split": st.column_config.TextColumn("Split", width=125,
                                                 help="Share of users in treatment / control."),
            "Total users": st.column_config.NumberColumn(format="localized"),
            "vs 50/50": st.column_config.NumberColumn(format="%.1fx", help="Total sample relative to an even split."),
            "Days": st.column_config.NumberColumn("Days", format="localized",
                                                  help="Days to reach the sample at the traffic entered above."),
            "Holdout cost": st.column_config.NumberColumn(
                "Holdout cost", format="localized",
                help="Conversions (or retained players) the control group misses during the test if the treatment "
                     "really works at the MDE: control users × absolute effect."),
        })
        st.caption("Holdout cost: conversions (or retained players) the control group gives up during the test if "
                   "the change really works at the MDE. Uneven splits cut it but need far more users in total.")
    n_now = size(plan)["total"]
    text = (f"To detect a {rel_mde:g}% relative lift on a {baseline:.2f}% baseline (+{eff * 100:.2f} pp) with "
            f"{power:.0%} power at alpha {alpha:g}, a {share}/{100 - share} split needs {sel['total']:,} users "
            f"({sel['n_t']:,} treatment / {sel['n_c']:,} control): about {sel['days']:,} days at {daily:,} eligible "
            f"users a day. The power curve crosses {power:.0%} exactly at that effect; smaller true lifts would often "
            "be missed.")
    if not math.isclose(share / 100, plan):
        text += (f" The same test at {split_now}, the ad test's design, needs {n_now:,} users "
                 f"({n_now / base_5050:.1f}× the 50/50 sample).")
    takeaway(text)
    caveat(f"Plan in whole weeks, at least {MIN_WEEKS}, even if the sample is reached sooner: lift varied by weekday "
           f"in the ad test (interaction p = {h_day['lrt']['p_value']:.3f}) and, without timestamps, this data cannot "
           "show whether the effect fades after a novelty period. Decide the sample size before launch and do not "
           "stop early on a good-looking p-value.")

# ------------------------------------------------------------------ risks + data asks
st.subheader("Risks, limitations and what I would ask for next")
risk_col, ask_col = st.columns(2, gap="large")
with risk_col:
    st.markdown("**Risks and limitations**")
    st.markdown(f"""
- **No revenue or cost.** Dollar figures rest on an assumed USD {value:,.0f} per conversion and on a CPM we do not
  have; the headline business number is incremental conversions.
- **No timestamps.** We cannot check novelty effects, how long the lift lasts, or when users were assigned.
- **Planned split not documented.** The {split_now} split is inferred from the data, so the ad test's SRM pass is weak;
  exposure parity ({ad['groups']['ad']['mean_ads']:.1f} vs {ad['groups']['psa']['mean_ads']:.1f} ads per user) is
  the stronger check.
- **Post-assignment segments.** Day, hour and exposure are recorded after assignment; segment lifts are
  exploratory and never used as covariates.
- **Multiple comparisons.** {h_day['n_segments'] + h_hour['n_segments'] + het['exposure_bucket']['n_segments']}
  segment tests across day, hour and exposure; we rely on one interaction test per dimension plus Holm correction.
- **Gate experiment.** Sample-ratio warning (p = {gsrm['p_value']:.4f}); rounds are counted over 14 days and overlap
  the D7 window, so rounds vs retention is correlation.
- **Two unrelated products.** The ad campaign (2021) and Cookie Cats (2017) share no users, so we cannot link ad
  conversions to later retention.
""")
with ask_col:
    st.markdown("**Data I would ask for next**")
    st.markdown("""
- **Assignment log with timestamps and the documented split** (Engineering): a proper SRM check, novelty and
  duration analysis, and the root cause of the gate experiment's warning.
- **Actual CPM / spend by day** (media buying) and **value per conversion** (Finance): real ROI instead of a
  breakeven against an assumed value.
- **Impression-level logs** (time and frequency per user): to design the frequency-cap arms in R2.
- **Guardrail metrics** (unsubscribes, complaints, uninstalls, CPA): to pre-register them in R4.
- **For the game:** install date, platform / country, first-session rounds (not 14-day totals) and level reached:
  to target R6 at players who stall in their first session.
""")

how_to_read(f"""
**What this page is.** The decisions, written so each one can be owned and checked later. Read it top to bottom:
the decision for each question, then the recommendations behind them, then the tool to size the next experiment.

**Decision labels.** KEEP = carry on as now. TEST / TEST FIRST = the data points in a direction but cannot settle
it; run a proper experiment before acting. DON'T = the evidence does not support the change. "Strength of evidence"
says how much weight each answer can carry: a randomized test with a clear interval is strong; a pattern seen
across segments that were not randomized is only a lead.

**Recommendations table.** Every row says who owns it, what to do, what we expect to gain (with the uncertainty),
the number we will watch to know whether it worked, and what could go wrong.

**Sample-size calculator.** Fill in the rate you expect without the change (baseline), the smallest improvement
worth acting on (relative lift), how users are split, and how strict the test should be (alpha, power). It returns
how many users the test needs and how long that takes at your traffic. The table compares splits: an uneven split
like {split_now} shows the new experience to more users but needs far more users in total, because the small group
is measured imprecisely. The holdout cost is what that small group gives up if the change really works.

**Words used.**
- **MDE (minimum detectable effect):** the smallest true effect the test would detect most of the time (as often as
  the power says). It is not the effect we expect.
- **Alpha:** the false-alarm rate we accept ({C.ALPHA:.0%} in this project).
- **Power:** the chance of catching a real effect of MDE size ({C.POWER:.0%} in this project).

**Common misreadings.**
- "The calculator gives a number of days, so we can stop earlier if it already looks good." Decide the length
  first and do not peek-and-stop; stopping on a good-looking day inflates false positives.
- "A smaller MDE is always better." It costs users and time; pick the smallest effect that would change the
  decision.
- The dollar numbers in R1 assume a value per conversion; the incremental conversions do not.
""")
