"""Page 1 · Overview: the answers to the Growth PM's questions on one screen.

Headline numbers are read from reports/results.json. The day contrasts come from
src.stats.segment_lifts on the cached cell table (the same call the report makes),
and the breakeven CPM and holdout cost follow the value-per-conversion assumption
the viewer types in.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from common import (C, F, S, fmt_pct, fmt_pp, how_to_read, load_cache, load_catalog_takeaways, load_results,
                    page_header, show, takeaway)

res = load_results()
dq = res["data_quality"]
ad, ck = res["ad"], res["cookie"]
t, bz = ad["test"], ad["business"]
inc, hold = bz["incremental_conversions"], bz["always_on_holdout_cost"]
het = ad["heterogeneity"]
h_day, h_hour, h_dp = het["most_ads_day"], het["most_ads_hour"], het["daypart"]
con = het["exposure_bucket"]["concentration"]
gate = ck["gate"]
gsrm, dec = gate["srm"], gate["d7_decomposition"]
gate_eff, gate_ci = dec["install_level_effect_if_only_reachers"], dec["install_level_effect_ci_if_only_reachers"]
plan = ad["srm"]["intended_share_t"]
split = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
psa_share = t["n_c"] / (t["n_t"] + t["n_c"])
by_d1 = {r["d1_status"]: r for r in ck["by_d1_status"]}

LOW_BUCKETS = ("0", "1-4", "5-14")  # fewer than 15 rounds in the first 14 days
low = [r for r in ck["by_rounds_bucket"] if r["rounds_bucket"] in LOW_BUCKETS]
low_share = sum(r["share_of_players"] for r in low)
low_d7_max = max(r["retention_7"] for r in low)
d7_yes, d7_no = by_d1["Returned Day 1"]["retention_7"], by_d1["Did not return Day 1"]["retention_7"]


def p_txt(p: float) -> str:
    """p-value for sentences: never 0, two significant digits ('p = 0.0086', 'p = 0.18')."""
    if p < 1e-4:
        return "p < 0.0001"
    if p < 1e-3 or p >= 0.995:
        return f"p = {p:.4f}"
    return f"p = {p:.2g}"


def ci_pp(lo: float, hi: float, signed: bool = False) -> str:
    f = "+.2f" if signed else ".2f"
    return f"95% CI {lo * 100:{f}} to {hi * 100:{f}} pp"


def page_link(page: str, label: str) -> None:
    """Link to another page of the app; plain text when this page runs on its own (e.g. in tests)."""
    try:
        st.page_link(page, label=label, icon=":material/arrow_forward:")
    except StreamlitPageNotFoundError:
        st.caption(label)


@st.cache_data(show_spinner=False)
def day_contrasts() -> pd.DataFrame:
    """Lift by the user's peak ad day, and each day's lift minus the other days' (Holm).
    Same call as the report's het_day chart."""
    return S.segment_lifts(load_cache("agg_ad_cells"), "most_ads_day", "ad", "psa", alpha=C.ALPHA,
                           method="holm", order=C.DAY_ORDER).set_index("most_ads_day")


dd = day_contrasts()
differing = h_day["segments_differing_holm"]
if differing:
    survive = {1: "surviving Holm", 2: "both surviving Holm"}.get(len(differing), "all surviving Holm")
    day_diffs = " and ".join(f"{d}-peak users {dd.loc[d, 'diff_vs_rest'] * 100:+.2f} pp" for d in differing)
    day_diffs += f" vs the other days, {survive}"
else:
    day_diffs = "no day differs from the others after Holm correction"
night = h_dp["night_counts"]["psa"]

# ------------------------------------------------------------------ header
page_header("Overview", "What did we find, and what should we do?")

intro, assumption = st.columns([3, 1], gap="large", vertical_alignment="bottom")
intro.markdown(
    "The Growth PM asked three things: *did last quarter's ad campaign drive conversions, is it worth doubling "
    "the budget, and which new users leave in their first 7 days?* The evidence is a randomized ad vs PSA test "
    f"({dq['marketing']['rows_clean']:,} users) and the Cookie Cats new-player data "
    f"({dq['cookie']['rows_clean']:,} players), which also contains a second experiment: moving the first "
    "progression gate from level 30 to level 40."
)
value = assumption.number_input(
    "Value per conversion (USD, assumed)", min_value=1.0, max_value=1000.0,
    value=float(bz["value_per_conversion_usd"]), step=5.0, format="%.0f", key="p1_value_per_conversion",
    help="The data has no revenue or cost. The default is an illustrative assumption; enter Finance's number "
         "to update the breakeven CPM and the holdout cost on this page.")
breakeven = {k: x * value / bz["impressions_ad_group"] * 1000 for k, x in inc.items()}
holdout_usd = hold["conversions_forgone"] * value

# ------------------------------------------------------------------ KPI rows
st.caption(f"Ad campaign · randomized ad vs PSA test, {t['n_t'] + t['n_c']:,} users")
k = st.columns(4)
k[0].metric(
    "Conversion lift, ad vs PSA", fmt_pp(t["abs_lift"]), ci_pp(t["abs_ci_low"], t["abs_ci_high"]),
    delta_color="off", delta_arrow="off",
    help=f"Conversion rate of users shown ads ({fmt_pct(t['rate_t'])}) minus users shown a public-service ad "
         f"({fmt_pct(t['rate_c'])}): a {t['rel_lift'] * 100:+.0f}% relative lift (95% CI "
         f"{t['rel_ci_low'] * 100:+.0f}% to {t['rel_ci_high'] * 100:+.0f}%). Newcombe interval; two-proportion "
         f"z-test {p_txt(t['p_value'])}.")
k[1].metric(
    "Incremental conversions", f"{inc['point']:,.0f}", f"95% CI {inc['ci_low']:,.0f} to {inc['ci_high']:,.0f}",
    delta_color="off", delta_arrow="off",
    help=f"Lift × {t['n_t']:,} users in the ad arm: conversions that would not have happened without the ads.")
share_ci = bz["share_of_ad_conversions_incremental_ci"]
k[2].metric(
    "Incremental share", f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}%",
    f"last-touch overstates {bz['last_touch_overstatement_x']:.1f}×", delta_color="off", delta_arrow="off",
    help=f"Share of ad-arm conversions that are incremental: {inc['point']:,.0f} of the {t['conv_t']:,} conversions "
         f"in the ad arm would not have happened without "
         f"the ads (95% CI {share_ci[0] * 100:.0f}% to {share_ci[1] * 100:.0f}%; equals 1 − 1 / relative risk). "
         f"Last-touch attribution would credit all {t['conv_t']:,} to the campaign, "
         f"{bz['last_touch_overstatement_x']:.1f}× the incremental number.")
k[3].metric(
    f"Breakeven CPM at USD {value:,.0f}", f"USD {breakeven['point']:,.2f}",
    f"95% CI {breakeven['ci_low']:,.2f} to {breakeven['ci_high']:,.2f}", delta_color="off", delta_arrow="off",
    help=f"Highest price per 1,000 impressions at which the campaign still pays back, if one conversion is worth "
         f"USD {value:,.0f} (an assumption). Incremental conversions × value ÷ "
         f"{bz['impressions_ad_group'] / 1e6:.1f}M impressions × 1,000.")

ov = ck["overall"]
st.caption(f"New players · Cookie Cats, {dq['cookie']['rows_clean']:,} players from one install cohort")
r = st.columns(4)
r[0].metric(
    "D1 retention", fmt_pct(ov["retention_1"], 1),
    f"95% CI {fmt_pct(ov['retention_1_ci_low'], 1)} to {fmt_pct(ov['retention_1_ci_high'], 1)}",
    delta_color="off", delta_arrow="off", help="Share of installs who played on the day after install.")
r[1].metric(
    "D7 retention", fmt_pct(ov["retention_7"], 1),
    f"95% CI {fmt_pct(ov['retention_7_ci_low'], 1)} to {fmt_pct(ov['retention_7_ci_high'], 1)}",
    delta_color="off", delta_arrow="off",
    help="Share of installs who played on day 7 after install (classic D7: played on that day, whether or not "
         "they played in between).")
r[2].metric(
    "Installs with < 15 rounds", f"{low_share * 100:.0f}%", f"D7 at most {low_d7_max * 100:.1f}%",
    delta_color="off", delta_arrow="off",
    help="Players with 0-14 rounds in their first 14 days, and the highest D7 retention among them. Rounds are "
         "counted through day 14, so this sizes the early-churn segment; it is not a Day-0 targeting rule.")
r[3].metric(
    "gate_40 effect on D7", fmt_pp(gate_eff), ci_pp(gate_ci[0], gate_ci[1], signed=True),
    delta_color="off", delta_arrow="off",
    help=f"Not certified (sample-ratio WARNING, {p_txt(gsrm['p_value'])}). The part of the D7 gap the gate could "
         f"cause: the gate_40 − gate_30 difference among players who reached level 30, spread over all installs. "
         f"The naive gap ({fmt_pp(dec['naive_diff'])}) also contains the player mix "
         f"({fmt_pp(dec['composition'])}) and players who never met a gate "
         f"({fmt_pp(dec['within_never_reached_30'])}); neither can be caused by the gate.")
st.caption(f"gate_40 effect: the part of the D7 gap the gate could cause, per install; the naive gap is "
           f"{fmt_pp(dec['naive_diff'])}. Not certified: the arms are unbalanced (sample-ratio WARNING, "
           f"{p_txt(gsrm['p_value'])}).")

# ------------------------------------------------------------------ answer cards
st.subheader("Answers to the PM's questions")
row1, row2 = st.columns(3, gap="medium"), st.columns(2, gap="medium")

with row1[0].container(border=True, height="stretch"):
    st.caption("Q1 · Growth PM")
    st.markdown("**Did last quarter's ad campaign drive conversions?**")
    st.badge("Yes: keep it running", color="green")
    st.markdown(
        f"Users shown ads converted at **{fmt_pct(t['rate_t'])}** vs **{fmt_pct(t['rate_c'])}** with the PSA: "
        f"**{fmt_pp(t['abs_lift'])}** ({ci_pp(t['abs_ci_low'], t['abs_ci_high'])}; {p_txt(t['p_value'])}), "
        f"about **{inc['point']:,.0f}** incremental conversions. That is only "
        f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}% of the ad arm's {t['conv_t']:,} conversions, so "
        f"last-touch attribution would overstate the campaign **{bz['last_touch_overstatement_x']:.1f}×**. Both "
        f"arms saw {ad['groups']['ad']['mean_ads']:.1f} ads per user (exposure parity); the {split} split lands "
        "exactly on target, like a quota, so its sample-ratio check is uninformative.")
    st.caption(f"R1: keep running with an always-on {hold['share'] * 100:.0f}% PSA holdout (about "
               f"{hold['conversions_forgone']:,.0f} conversions, USD {holdout_usd / 1e3:,.1f}K at USD {value:,.0f} "
               f"each, per {(t['n_t'] + t['n_c']) / 1e3:,.0f}K-user flight).")
    page_link("views/p4_experiment_readout.py", "Experiment readout")

with row1[1].container(border=True, height="stretch"):
    st.caption("Q2 · Growth PM")
    st.markdown("**Is it worth doubling the budget?**")
    st.badge("Not answerable yet: test first", color="orange")
    st.markdown(
        "Nobody varied the budget, so the test measures ads vs no ads at the current spend, not what extra spend "
        "would buy. The lift lives in heavy users: none detectable for the "
        f"**{con['share_users_le_20_ads'] * 100:.0f}%** of users who saw 20 ads or fewer, while "
        f"**{con['share_incremental_conversions_36_200'] * 100:.0f}%** of incremental conversions come from the "
        f"**{con['share_ad_users_36_200'] * 100:.0f}%** of ad users who saw 36-200 ads. Exposure tracks how active "
        "a user is, so this is not a frequency curve. At USD "
        f"{value:,.0f} per conversion (assumed) the current flight pays back below "
        f"**USD {breakeven['point']:,.2f}** CPM.")
    st.caption("R2: before scaling, run a randomized 2x-budget / frequency-cap test, sized with the calculator on "
               "page 7.")
    page_link("views/p5_heterogeneity.py", "Heterogeneity and exposure")

with row1[2].container(border=True, height="stretch"):
    st.caption("Q3 · Growth PM + media buyer")
    st.markdown("**Should spend move to the best day or hour?**")
    st.badge("No: test dayparts first", color="gray")
    st.markdown(
        f"**Hour:** no evidence the lift differs (interaction {p_txt(h_hour['lrt']['p_value'])}). "
        f"**Daypart:** {p_txt(h_dp['lrt']['p_value'])} comes entirely from Night (0-5), where the control arm has "
        f"{night['conversions']} conversion among {night['users']:,} users; without it "
        f"{p_txt(h_dp['lrt_excluding_night']['p_value'])}. "
        f"**Day:** modest evidence ({p_txt(h_day['lrt']['p_value'])}; {h_day['lrt_p_bonferroni_3_dims']:.2f} after "
        f"allowing for the {het['n_dimensions_explored']} dimensions explored): {day_diffs}. But 'peak day' "
        "describes the user's habits, not a day we can buy.")
    st.caption("R3: keep the current schedule; pre-register a daypart test if timing matters.")
    page_link("views/p5_heterogeneity.py", "Heterogeneity by day / hour")

with row2[0].container(border=True, height="stretch"):
    st.caption("Q4 · Growth PM")
    st.markdown("**Which new users leave first?**")
    st.badge("Players who barely start", color="blue")
    st.markdown(
        f"**{low_share * 100:.0f}%** of installs play fewer than 15 rounds in their first 14 days, and at most "
        f"**{low_d7_max * 100:.1f}%** of them play on Day 7. **{(1 - ov['retention_1']) * 100:.1f}%** of players "
        f"don't come back on Day 1; those who do are **{d7_yes / d7_no:.1f}×** as likely to play on Day 7 "
        f"({fmt_pct(d7_yes, 1)} vs {fmt_pct(d7_no, 1)}). Day-1 return is the earliest strong signal of who stays: "
        "an association, not a cause. Rounds are counted through day 14, so the "
        f"{low_share * 100:.0f}% sizes the early-churn segment; it is not a Day-0 targeting rule.")
    st.caption("R6: focus retention work on the first session and Day 1; validate with a Day-1 re-engagement "
               "experiment, D7 retention as the primary metric.")
    page_link("views/p3_retention.py", "Retention analysis")

with row2[1].container(border=True, height="stretch"):
    st.caption("Q5 · Game PM (second experiment)")
    st.markdown("**Should the first gate move from level 30 to level 40?**")
    st.badge("No: keep gate_30 (result not certified)", color="red")
    st.markdown(
        f"The naive comparison shows **{fmt_pp(dec['naive_diff'])}** D7 retention for gate_40, but the arms are "
        f"unbalanced: a sample-ratio **WARNING** ({p_txt(gsrm['p_value'])}; {gsrm['n_t']:,} vs {gsrm['n_c']:,} "
        f"installs), with {gate['excess_players_with_lt_15_rounds']} of gate_40's "
        f"{gate['worst_case_bound']['excess_players_gate_40']} extra installs among players with fewer than 15 "
        "rounds. Removing what the gate cannot cause leaves about "
        f"**{gate_eff * 100:+.1f} pp per install** ({ci_pp(gate_ci[0], gate_ci[1], signed=True)}): probably small, "
        "possibly zero, and no sign of a benefit. Keeping gate_30 is the status quo, so the decision does not "
        "need a certified result.")
    st.caption(f"R5: keep gate_30; fix assignment and logging first; re-test (about "
               f"{gate['retest_sizing']['installs_needed_total_5050'] / 1e3:,.0f}K installs at 50/50) only if the "
               "gate placement matters commercially.")
    page_link("views/p6_gate_experiment.py", "Gate experiment")

# ------------------------------------------------------------------ headline chart + map of the app
st.subheader("The headline result")
chart_col, nav_col = st.columns([3, 2], gap="large")
with chart_col:
    arms = F.arm_table(t["conv_t"], t["n_t"], t["conv_c"], t["n_c"])
    show(F.fig_arm_rates(
        arms, "Conversion rate by experiment arm (%, 95% CI)",
        f"{t['n_t']:,} ad users vs {t['n_c']:,} PSA users. Whiskers: 95% Wilson interval."))
    takeaway(load_catalog_takeaways()["ad_rates"])

with nav_col:
    st.markdown("**How this app is organised**")
    st.caption("Pages follow the order of the readout: trust the data first, then the answers, then the decision.")
    for path, label, desc in (
        ("views/p2_data_sanity.py", "2 · Data & Sanity Checks",
         "Can we trust the data? Data quality, sample-ratio checks and where the gate test's imbalance sits, "
         "exposure parity."),
        ("views/p3_retention.py", "3 · Retention Analysis",
         "Which new players leave first? Funnel, segments, engagement depth."),
        ("views/p4_experiment_readout.py", "4 · Experiment Readout: Ad vs PSA",
         "Did ads work, by how much, and is it worth the money? CI methods, power, breakeven, attribution."),
        ("views/p5_heterogeneity.py", "5 · Heterogeneity by Day / Hour",
         "Does the lift differ by day, hour, daypart or exposure, or is it noise? Interaction tests and "
         "corrected contrasts."),
        ("views/p6_gate_experiment.py", "6 · Gate Experiment (Cookie Cats)",
         "Should the gate move to level 40? Readout, integrity checks and the part of the gap the gate could "
         "cause."),
        ("views/p7_decision.py", "7 · Decision & Recommendations",
         "Who does what next, how we will measure it, and a sample-size calculator."),
    ):
        page_link(path, label)
        st.caption(desc)

how_to_read(f"""
**What this page is.** The one-screen summary: the headline numbers, the answer to each question, and a link to
the page with the evidence. Every number comes from the same analysis run as the report.

**The number cards.** The big number is the best estimate. The grey line under it is the **95% confidence
interval (CI)**: the range of true values that are consistent with the data. When the whole range sits on one side
of zero, the effect is very unlikely to be zero. Hover the small question mark for the exact definition.

**pp vs %.** Going from {fmt_pct(t['rate_c'])} to {fmt_pct(t['rate_t'])} is a gain of
{t['abs_lift'] * 100:.2f} **percentage points (pp)**, which is also a {t['rel_lift'] * 100:.0f}% **relative**
increase. Both are correct. Percentage points are what turn into extra conversions; the relative number looks big
only because the starting rate is small.

**Incremental conversions** are the conversions that happened *because of* the ads: the lift times the number of
users who saw ads. Most conversions in the ad arm ({100 - bz['share_of_ad_conversions_incremental'] * 100:.0f}%)
would have happened anyway. Crediting all of them to the campaign, as last-touch attribution does, overstates it
{bz['last_touch_overstatement_x']:.1f}×; that is why we keep a PSA control group.

**Breakeven CPM** is the most we could pay per 1,000 ad impressions and still get our money back. It depends on what
one conversion is worth, which this data does not contain, so the value is an **assumption** you can change at the
top right. Compare the breakeven with the CPM we actually pay (Finance has it).

**The gate card** shows the part of gate_40's D7 gap that the gate could have caused, per install. The naive gap
({fmt_pp(dec['naive_diff'])}) is larger because gate_40 also received extra low-engagement installs; page 6 shows
the split.

**The bar chart** shows each group's conversion rate; the thin whiskers are the 95% interval for that rate. The PSA
whisker is wider because only {psa_share * 100:.0f}% of users were in the PSA group, so its rate is measured less
precisely.

**Common misreadings.**
- "{t['rel_lift'] * 100:.0f}% lift" does not mean {t['rel_lift'] * 100:.0f}% of users converted. It is a relative
  change on a base rate of {fmt_pct(t['rate_c'])}.
- "Statistically significant" means "unlikely to be zero", not "big" or "profitable".
- The experiment shows the campaign worked at its *current* budget. It says nothing direct about a doubled budget.
- "gate_40 cost {abs(dec['naive_diff']) * 100:.2f} pp of D7." That is the naive gap between unbalanced arms, not
  the effect of the gate.
- The gate experiment is a different product (a mobile puzzle game, 2017). It is here because it has the retention
  data and a second experiment, not because it is linked to the ad campaign.
""")
