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

from common import (C, F, S, approx, ci_text, fmt_pct, how_to_read, load_cache, load_catalog_takeaways, load_results,
                    p_text, page_header, sgn, sgn_pp, show, takeaway)

res = load_results()
dq = res["data_quality"]
ad, ck = res["ad"], res["cookie"]
t, bz = ad["test"], ad["business"]
inc, hold = bz["incremental_conversions"], bz["always_on_holdout_cost"]
lt_x, lt_ci = bz["last_touch_overstatement_x"], bz["last_touch_overstatement_ci"]
het = ad["heterogeneity"]
h_day, h_hour, h_dp = het["most_ads_day"], het["most_ads_hour"], het["daypart"]
con = het["exposure_bucket"]["concentration"]
le20 = con["le_20_ads_pooled"]
ov, early = ck["overall"], ck["early_churn_segment"]
r6 = early["onboarding_test_sizing"]
gate = ck["gate"]
gsrm, dec, retest = gate["srm"], gate["d7_decomposition"], gate["retest_sizing"]
g7 = gate["retention_7"]
gate_eff, gate_ci = dec["install_level_effect_if_only_reachers"], dec["install_level_effect_ci_if_only_reachers"]
excess = gate["best_case_for_gate_40"]["excess_players_gate_40"]  # cleaned data: ≈790
excess_raw = gsrm["n_t"] - gsrm["n_c"]                             # raw assignment log: 789
net_lt15 = gate["srm_by_stratum"]["rounds_lt_15"]["net_excess_t"]
# share of the naive gap that sits where the gate cannot act (player mix + players who never met a gate)
not_gate = (dec["composition"] + dec["within_never_reached_30"]) / dec["naive_diff"]
plan = ad["srm"]["intended_share_t"]
split = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
n_users = t["n_t"] + t["n_c"]
psa_share = t["n_c"] / n_users
steps = [s["share_of_installs"] for s in ck["funnel"]]


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
    day_diffs = " and ".join(f"{d}-peak users {sgn_pp(dd.loc[d, 'diff_vs_rest'])}" for d in differing)
    day_diffs += f" vs the other days, {survive}"
else:
    day_diffs = "no day differs from the others after Holm correction"
# Tuesday caveat: part of its lift is a low control (PSA) conversion rate
low_ctrl = dd["rate_c"].rank().loc["Tuesday"] <= 3
tue = dd.loc["Tuesday"]
tue_note = (f" Part of Tuesday's lift is a low control rate (its PSA arm: {int(tue['conv_c'])} conversions among "
            f"{int(tue['n_c']):,} users, {fmt_pct(tue['rate_c'])}, one of the lowest of the week)."
            if "Tuesday" in differing and low_ctrl else "")
night = h_dp["night_counts"]["psa"]

# ------------------------------------------------------------------ header
page_header("Overview", "What did we find, and what should we do?")

intro, assumption = st.columns([3, 1], gap="large", vertical_alignment="bottom")
intro.markdown(
    "The Growth PM asked three things: *did last quarter's ad campaign drive conversions, is it worth doubling "
    "the budget, and which new users leave in their first 7 days?* The evidence is a randomized ad vs PSA test "
    f"({dq['marketing']['rows_clean']:,} users) and new-player data from the company's mobile game, Cookie Cats "
    f"({dq['cookie']['rows_clean']:,} players, one 2017 install cohort), a different product from the app the ads "
    "ran in. The game data also contains a second experiment: moving the first progression gate from level 30 to "
    "level 40."
)
value = assumption.number_input(
    "Value per conversion (USD, assumed)", min_value=1.0, max_value=1000.0,
    value=float(bz["value_per_conversion_usd"]), step=5.0, format="%.0f", key="p1_value_per_conversion",
    help="The data has no revenue or cost. The default is an illustrative assumption; enter Finance's number "
         "to update the breakeven CPM and the holdout cost on this page.")
breakeven = {k: x * value / bz["impressions_ad_group"] * 1000 for k, x in inc.items()}
holdout_usd = hold["conversions_forgone"] * value

# ------------------------------------------------------------------ KPI rows
st.caption(f"Ad campaign · randomized ad vs PSA test, {n_users:,} users")
k = st.columns(4)
k[0].metric(
    "Conversion lift, ad vs PSA", sgn_pp(t["abs_lift"]), ci_text(t["abs_ci_low"], t["abs_ci_high"], signed=False),
    delta_color="off", delta_arrow="off",
    help=f"Conversion rate of users shown ads ({fmt_pct(t['rate_t'])}) minus users shown a public-service ad "
         f"({fmt_pct(t['rate_c'])}): a {sgn(t['rel_lift'] * 100, 0)}% relative lift (95% CI "
         f"{sgn(t['rel_ci_low'] * 100, 0)}% to {sgn(t['rel_ci_high'] * 100, 0)}%). Newcombe interval; two-proportion "
         f"z-test {p_text(t['p_value'])}.")
k[1].metric(
    "Incremental conversions", f"{inc['point']:,.0f}", f"95% CI {inc['ci_low']:,.0f} to {inc['ci_high']:,.0f}",
    delta_color="off", delta_arrow="off",
    help=f"Lift × {t['n_t']:,} users in the ad arm: conversions that would not have happened without the ads "
         f"(≈{approx(inc['point'])}, 95% CI {approx(inc['ci_low'])}–{approx(inc['ci_high'])} in round numbers).")
share_ci = bz["share_of_ad_conversions_incremental_ci"]
k[2].metric(
    "Incremental share", f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}%",
    f"last-touch overstates {lt_x:.1f}×", delta_color="off", delta_arrow="off",
    help=f"Share of ad-arm conversions that are incremental: {inc['point']:,.0f} of the {t['conv_t']:,} conversions "
         f"in the ad arm would not have happened without the ads (95% CI {share_ci[0] * 100:.0f}% to "
         f"{share_ci[1] * 100:.0f}%; equals 1 − 1 / relative risk). Every ad-arm user saw at least one ad, so "
         f"last-touch (any-touch) attribution would credit all {t['conv_t']:,} to the campaign: {lt_x:.1f}× the "
         f"incremental number (95% CI {lt_ci[0]:.1f}–{lt_ci[1]:.1f}×).")
k[3].metric(
    f"Breakeven CPM at USD {value:,.0f}", f"USD {breakeven['point']:,.2f}",
    f"95% CI {breakeven['ci_low']:,.2f} to {breakeven['ci_high']:,.2f}", delta_color="off", delta_arrow="off",
    help=f"Highest price per 1,000 impressions at which the campaign still pays back, if one conversion is worth "
         f"USD {value:,.0f} (an assumption). Incremental conversions × value ÷ "
         f"{bz['impressions_ad_group'] / 1e6:.1f}M impressions × 1,000.")

st.caption(f"New players · Cookie Cats (the company's mobile game), {dq['cookie']['rows_clean']:,} players from one "
           "install cohort")
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
    "Installs with < 15 rounds", f"{early['share_of_installs'] * 100:.0f}%",
    f"only {early['retention_7'] * 100:.1f}% back on Day 7", delta_color="off", delta_arrow="off",
    help=f"Players with 0–14 rounds in their first 14 days ({early['players']:,} players) and their D7 retention "
         f"({early['retention_7'] * 100:.2f}%; at most {early['max_bucket_retention_7'] * 100:.1f}% in any single "
         "bucket). Rounds are counted through day 14, so this sizes the early-churn segment; it is not a Day-0 "
         "targeting rule.")
r[3].metric(
    "D7 gap the gate could explain", sgn_pp(gate_eff), ci_text(gate_ci[0], gate_ci[1]),
    delta_color="off", delta_arrow="off",
    help=f"Not certified: sample-ratio WARNING on raw assignment counts ({gsrm['n_t']:,} vs {gsrm['n_c']:,}, "
         f"{excess_raw} more in gate_40; {p_text(gsrm['p_value'])}). This is the gate_40 − gate_30 D7 difference "
         "among players with 30+ rounds (who could have reached level 30), spread over all installs: the part of "
         "the gap the gate could explain, not an estimate of its effect. Players with 15–29 rounds, almost none of whom can have met a "
         f"gate, show a similar gap. The naive gap ({sgn_pp(dec['naive_diff'])}) also contains the player mix "
         f"({sgn_pp(dec['composition'])}) and players who never met a gate ({sgn_pp(dec['within_never_reached_30'])}); "
         "neither can be the gate.")
st.caption(f"Gate card: the part of gate_40's D7 gap the gate could explain, per install, not an estimate of its "
           f"effect; the naive gap is {sgn_pp(dec['naive_diff'])}. Not certified: the arms are unbalanced "
           f"(sample-ratio WARNING, {p_text(gsrm['p_value'])}).")

# ------------------------------------------------------------------ answer cards
st.subheader("Answers to the PM's questions")
row1, row2 = st.columns(3, gap="medium"), st.columns(2, gap="medium")

with row1[0].container(border=True, height="stretch"):
    st.caption("Q1 · Growth PM")
    st.markdown("**Did last quarter's ad campaign drive conversions?**")
    st.badge("Yes: keep it running", color="green")
    st.markdown(
        f"Users shown ads converted at **{fmt_pct(t['rate_t'])}** vs **{fmt_pct(t['rate_c'])}** with the PSA: "
        f"**{sgn_pp(t['abs_lift'])}** ({ci_text(t['abs_ci_low'], t['abs_ci_high'], signed=False)}; "
        f"{p_text(t['p_value'])}), **≈{approx(inc['point'])}** incremental conversions (95% CI "
        f"{approx(inc['ci_low'])}–{approx(inc['ci_high'])}). Only "
        f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}% of the ad arm's {t['conv_t']:,} conversions are "
        "incremental, so last-touch attribution would credit every one of them to the ads and overstate the campaign "
        f"**{lt_x:.1f}×** (95% CI {lt_ci[0]:.1f}–{lt_ci[1]:.1f}×). Both arms saw "
        f"{ad['groups']['ad']['mean_ads']:.1f} ads per user (exposure parity); the {split} split lands exactly on "
        "target, most likely a fixed quota, so its sample-ratio check is uninformative.")
    st.caption(f"R1: keep the campaign at the current budget, with an always-on {hold['share'] * 100:.0f}% PSA "
               f"holdout. It forgoes ≈{hold['conversions_forgone']:,.0f} conversions per {n_users / 1e3:,.0f}K-user "
               f"flight (≈USD {holdout_usd / 1e3:,.1f}K at USD {value:,.0f} each) vs. no holdout; this test's "
               f"{hold['as_run_control_share'] * 100:.0f}% PSA arm already forgoes "
               f"≈{hold['as_run_control_conversions_forgone']:,.0f}.")
    page_link("views/p4_experiment_readout.py", "Experiment readout")

with row1[1].container(border=True, height="stretch"):
    st.caption("Q2 · Growth PM")
    st.markdown("**Is it worth doubling the budget?**")
    st.badge("Not answerable yet: test first", color="orange")
    st.markdown(
        "Nobody varied the budget, so the test measures ads vs no ads at the current spend, not what extra spend "
        f"would buy. The lift lives in heavy users: the **{con['share_users_le_20_ads'] * 100:.0f}%** of users who saw "
        f"≤ 20 ads show no lift we could measure ({sgn_pp(le20['abs_lift'])}, "
        f"{ci_text(le20['abs_ci_low'], le20['abs_ci_high'], unit='')}), while the "
        f"**{con['share_ad_users_36_200'] * 100:.0f}%** of ad users who saw 36–200 ads hold "
        f"**{con['share_incremental_conversions_36_200'] * 100:.0f}%** of the bucket-by-bucket incremental "
        "conversions. Exposure tracks how active a user is, so this is not a frequency curve. At USD "
        f"{value:,.0f} per conversion (assumed) the current flight pays back below "
        f"**USD {breakeven['point']:,.2f}** CPM.")
    st.caption("R2: don't double blindly; test it. One arm gets up to 2× today's impressions per user (or a frequency "
               "cap), sized with the calculator on page 7; a true budget test needs a geo split.")
    page_link("views/p5_heterogeneity.py", "Heterogeneity and exposure")

with row1[2].container(border=True, height="stretch"):
    st.caption("Q3 · Growth PM + media buyer")
    st.markdown("**Should spend move to the best day or hour?**")
    st.badge("No: keep the schedule", color="gray")
    st.markdown(
        f"**Hour:** no evidence the lift differs (interaction {p_text(h_hour['lrt']['p_value'])}). "
        f"**Daypart:** {p_text(h_dp['lrt']['p_value'])} is driven by Night (0–5), where the control arm has "
        f"{night['conversions']} conversion among {night['users']:,} users; without it "
        f"{p_text(h_dp['lrt_excluding_night']['p_value'])}. "
        f"**Day:** modest evidence ({p_text(h_day['lrt']['p_value'])}; {h_day['lrt_p_bonferroni_3_dims']:.2g} "
        f"allowing for the {het['n_dimensions_explored']} dimensions explored): {day_diffs}.{tue_note} 'Peak day' is "
        "a user habit recorded after assignment, not a slot we buy.")
    st.caption("R3: don't re-plan spend by day or hour. If timing matters, pre-register a test that randomizes the "
               "delivery schedule (e.g. Tuesday vs. Thursday delivery).")
    page_link("views/p5_heterogeneity.py", "Heterogeneity by day / hour")

with row2[0].container(border=True, height="stretch"):
    st.caption("Q4 · Growth PM")
    st.markdown("**Which new users leave first?**")
    st.badge("Players who barely start", color="blue")
    by_d1 = {x["d1_status"]: x["retention_7"] for x in ck["by_d1_status"]}
    d7_yes, d7_no = by_d1["Returned Day 1"], by_d1["Did not return Day 1"]
    st.markdown(
        f"**{(1 - ov['retention_1']) * 100:.1f}%** of installs don't come back on Day 1, the biggest drop "
        f"in the funnel. A further {(steps[1] - steps[2]) * 100:.1f} pp of installs "
        f"return on Day 1 but not on Day 7 ({steps[2] * 100:.1f}% return on both). Players with < 15 rounds in 14 days are "
        f"**{early['share_of_installs'] * 100:.0f}%** of installs, and only **{early['retention_7'] * 100:.1f}%** of "
        f"them are back on Day 7 (≤ {early['max_bucket_retention_7'] * 100:.1f}% in any single bucket). Players who "
        f"return on Day 1 are **{d7_yes / d7_no:.1f}×** as likely to play on Day 7 ({fmt_pct(d7_yes, 1)} vs "
        f"{fmt_pct(d7_no, 1)}): an association, not a cause. Rounds are counted over 14 days, so the "
        f"{early['share_of_installs'] * 100:.0f}% sizes the segment; it is not a Day-0 targeting rule.")
    st.caption(f"R6: a randomized Day-1 re-engagement test for new players who play little on their first day, D7 "
               f"primary. A +{r6['target_lift_abs'] * 100:.1f} pp D7 target on the "
               f"{early['retention_7'] * 100:.1f}% base (a placeholder) needs "
               f"≈{r6['players_needed_5050'] / 1e3:.0f}K target players "
               f"(≈{r6['installs_needed_5050'] / 1e3:.0f}K installs) at 50/50.")
    page_link("views/p3_retention.py", "Retention analysis")

with row2[1].container(border=True, height="stretch"):
    st.caption("Q5 · Game PM (second experiment)")
    st.markdown("**Should the first gate move from level 30 to level 40?**")
    st.badge("No: keep gate_30 (result not certified)", color="red")
    st.markdown(
        f"The naive comparison shows gate_40's D7 **{abs(dec['naive_diff']) * 100:.2f} pp lower** "
        f"({ci_text(g7['abs_ci_low'], g7['abs_ci_high'], signed=False)}), but the arms are unbalanced: a sample-ratio "
        f"**WARNING** ({p_text(gsrm['p_value'])}). gate_40 received **≈{excess} extra installs**, with a net excess "
        f"of {net_lt15} among players with < 15 rounds. About {round(not_gate * 10) * 10:.0f}% of the naive gap sits "
        "where the gate cannot act; the part the gate could explain is "
        f"**{sgn_pp(gate_eff)} per install** ({ci_text(gate_ci[0], gate_ci[1], unit='')}), not an estimate of its "
        f"effect, and possibly zero. No sign of a retention benefit. Among players with 30+ rounds, gate_40 "
        f"players played a little more (median {gate['rounds_among_reachers']['median_t']:.0f} vs "
        f"{gate['rounds_among_reachers']['median_c']:.0f} rounds). This is descriptive: assignment is uncertified "
        "and the group is defined by rounds played, so it does not show that gate_40 causes more play. "
        "Keeping gate_30 is the status quo, so the "
        "decision does not need a certified result.")
    st.caption(f"R5: keep gate_30; fix assignment and logging first. Re-test only if the gate position matters "
               f"commercially, sized at a {retest['smallest_d7_change_per_install'] * 100:.1f} pp D7 change per "
               f"install fixed in advance: ≈{retest['installs_needed_reacher_analysis_5050'] / 1e3:.0f}K installs at "
               f"50/50 with the primary analysis among players who reach level 30 "
               f"(≈{retest['reachers_needed_5050'] / 1e3:.0f}K of them), "
               f"≈{retest['installs_needed_install_level_5050'] / 1e3:.0f}K if analysed over all installs.")
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
         "explain."),
        ("views/p7_decision.py", "7 · Decision & Recommendations",
         "Who does what next, how we will measure it, and a sample-size calculator."),
    ):
        page_link(path, label)
        st.caption(desc)

how_to_read(f"""
**What this page is.** The one-screen summary: the headline numbers, the answer to each question, and a link to
the page with the evidence. Every number comes from the same analysis run as the report.

**The number cards.** The big number is the measured value. The grey line under it shows the **95% confidence
interval (CI)**: the effect sizes compatible with the data. If ads had no effect, a difference this large
would be very unlikely. Hover the small question mark for the exact definition.

**pp vs %.** Going from {fmt_pct(t['rate_c'])} to {fmt_pct(t['rate_t'])} is a gain of
{t['abs_lift'] * 100:.2f} **percentage points (pp)**, which is also a {t['rel_lift'] * 100:.0f}% **relative**
increase. Both are correct. Percentage points are what turn into extra conversions; the relative number looks big
only because the starting rate is small.

**Incremental conversions** are the conversions that happened *because of* the ads: the lift times the number of
users who saw ads. Most conversions in the ad arm ({100 - bz['share_of_ad_conversions_incremental'] * 100:.0f}%)
would have happened anyway. Crediting all of them to the campaign, as last-touch attribution does, overstates it
{lt_x:.1f}×; that is why we keep a PSA control group.

**Breakeven CPM** is the most we could pay per 1,000 ad impressions and still get our money back. It depends on what
one conversion is worth, which this data does not contain, so the value is an **assumption** you can change at the
top right. Compare the breakeven with the CPM we actually pay (Finance has it).

**The gate card** shows the part of gate_40's D7 gap that the gate could explain, per install. It is not an estimate
of the gate's effect: players with 15–29 rounds, almost none of whom can have met a gate, show a similar gap. The naive gap
({sgn_pp(dec['naive_diff'])}) is larger because about {round(not_gate * 10) * 10:.0f}% of it sits where the gate
cannot act: the player mix and players who never met a gate. Page 6 shows the split.

**The bar chart** shows each group's conversion rate; the thin whiskers are the 95% interval for that rate. The PSA
whisker is wider because only {psa_share * 100:.0f}% of users were in the PSA group, so its rate is measured less
precisely.

**Common misreadings.**
- "{t['rel_lift'] * 100:.0f}% lift" does not mean {t['rel_lift'] * 100:.0f}% of users converted. It is a relative
  change on a base rate of {fmt_pct(t['rate_c'])}.
- If ads had no effect, a difference this large would be very unlikely; the confidence interval shows the effect
  sizes compatible with the data. Statistical significance alone does not establish size or profitability.
- The experiment shows the campaign worked at its *current* budget. It says nothing direct about a doubled budget.
- Reading the naive {sgn_pp(dec['naive_diff'])} D7 gap as the effect of the gate. The groups were unbalanced, and
  about {round(not_gate * 10) * 10:.0f}% of the gap sits where the gate cannot act.
- Reading the retention numbers as the app's own. They come from the company's mobile game (Cookie Cats, 2017
  install cohort), a different product from the app the ads ran in: segment sizes will not transfer one-for-one,
  and the two datasets share no users.
""")
