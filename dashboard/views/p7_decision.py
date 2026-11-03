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
inc, be, hold = bz["incremental_conversions"], bz["breakeven_cpm_usd"], bz["always_on_holdout_cost"]
het = ad["heterogeneity"]
h_day, h_hour, h_dp, h_exp = het["most_ads_day"], het["most_ads_hour"], het["daypart"], het["exposure_bucket"]
con = h_exp["concentration"]
gate = ck["gate"]
g1, g7, gsrm, rounds = gate["retention_1"], gate["retention_7"], gate["srm"], gate["rounds"]
dec, retest, sbs = gate["d7_decomposition"], gate["retest_sizing"], gate["srm_by_stratum"]
gate_eff, gate_ci = dec["install_level_effect_if_only_reachers"], dec["install_level_effect_ci_if_only_reachers"]
nc7 = gate["negative_control"]["never_reached_30"]["retention_7"]
reach7 = gate["negative_control"]["reached_30"]["retention_7"]
excess = gate["worst_case_bound"]["excess_players_gate_40"]
ov = ck["overall"]
by_d1 = {r["d1_status"]: r for r in ck["by_d1_status"]}
low = [r for r in ck["by_rounds_bucket"] if r["rounds_bucket"] in ("0", "1-4", "5-14")]  # < 15 rounds
low_n, low_share = sum(r["players"] for r in low), sum(r["share_of_players"] for r in low)
low_d7_max = max(r["retention_7"] for r in low)
d1_ratio = by_d1["Returned Day 1"]["retention_7"] / by_d1["Did not return Day 1"]["retention_7"]
n10 = pw["total_n_for_10pct_rel_lift"]
sesoi = pw["smallest_lift_of_interest_rel"]
pw_ses, pw_5 = pw["power_at_relative_lift"][str(sesoi)], pw["power_at_relative_lift"]["0.05"]
value = bz["value_per_conversion_usd"]
plan = ad["srm"]["intended_share_t"]            # the ad test's (inferred, quota-exact) 96/4 design
split_now = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
p_psa = t["conv_c"] / t["n_c"]
n10_now = n10.get(str(plan)) or S.required_total_n(p_psa, sesoi * p_psa, plan, C.ALPHA, C.POWER)
std_lifts = [het[d]["sensitivity_stratified"]["mh_risk_diff"] * 100
             for d in ("most_ads_day", "most_ads_hour", "daypart", "exposure_bucket")]
PER = 10_000  # installs, for a per-install effect in players


def p_txt(p: float) -> str:
    """p-value for sentences: never 0, two significant digits ('p = 0.0086', 'p = 0.18')."""
    if p < 1e-4:
        return "p < 0.0001"
    if p < 1e-3 or p >= 0.995:
        return f"p = {p:.4f}"
    return f"p = {p:.2g}"


def pct_power(x: float) -> str:
    return "about 100%" if x >= 0.995 else f"{x * 100:.0f}%"


@st.cache_data(show_spinner=False)
def segment_table(dim: str, order: tuple) -> pd.DataFrame:
    """Per-segment lift and segment-vs-rest contrast (Holm), same call as the report's charts."""
    return S.segment_lifts(load_cache("agg_ad_cells"), dim, "ad", "psa", alpha=C.ALPHA, method="holm",
                           order=list(order)).set_index(dim)


expo = segment_table("exposure_bucket", tuple(C.EXPOSURE_LABELS))
days = segment_table("most_ads_day", tuple(C.DAY_ORDER))
differing = h_day["segments_differing_holm"]
day_diffs = " and ".join(f"{d}-peak users {days.loc[d, 'diff_vs_rest'] * 100:+.2f} pp" for d in differing) \
    or "no peak day"
survive = {0: "none survives Holm", 1: "survives Holm", 2: "both survive Holm"}.get(len(differing),
                                                                                   "all survive Holm")
night = h_dp["night_counts"]["psa"]

# ------------------------------------------------------------------ header
page_header("Decision & Recommendations", "What should we do, who owns it, and how will we know it worked?")

# ------------------------------------------------------------------ decision summary
st.subheader("Decision per question")
DECISIONS = [
    ("Did the ad campaign drive conversions?", "KEEP", "green",
     f"Keep the campaign running with an always-on {hold['share'] * 100:.0f}% PSA holdout (R1).",
     f"{t['abs_lift'] * 100:+.2f} pp conversion (95% CI {t['abs_ci_low'] * 100:.2f} to {t['abs_ci_high'] * 100:.2f}; "
     f"{p_txt(t['p_value'])}), about {inc['point']:,.0f} incremental conversions, only "
     f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}% of the ad arm's conversions: last-touch attribution "
     f"would overstate the campaign {bz['last_touch_overstatement_x']:.1f}×. Exposure parity holds "
     f"({ad['groups']['ad']['mean_ads']:.1f} vs {ad['groups']['psa']['mean_ads']:.1f} ads per user); the "
     f"{split_now} split is quota-exact, so its SRM check is uninformative.",
     "strong (randomized test, interval well above zero)."),
    ("Is it worth doubling the budget?", "TEST FIRST", "orange",
     "Don't double blindly; run a randomized 2x-budget / frequency-cap test (R2).",
     "The test compared ads with no ads at the current spend, not 1x with 2x. The lift lives in heavy users: none "
     f"detectable for the {con['share_users_le_20_ads'] * 100:.0f}% of users who saw 20 ads or fewer, while "
     f"{con['share_incremental_conversions_36_200'] * 100:.0f}% of incremental conversions come from the "
     f"{con['share_ad_users_36_200'] * 100:.0f}% of ad users who saw 36-200 ads; exposure tracks how active a user "
     "is, so this is not a frequency curve.",
     "not answerable with this data."),
    ("Should spend move to the best day or hour?", "DON'T (YET)", "gray",
     "Keep the current schedule; pre-register a daypart test if timing matters (R3).",
     f"Hour: no evidence (interaction {p_txt(h_hour['lrt']['p_value'])}). Daypart: "
     f"{p_txt(h_dp['lrt']['p_value'])} comes from Night alone ({night['conversions']} control conversion among "
     f"{night['users']:,} users); without it {p_txt(h_dp['lrt_excluding_night']['p_value'])}. Day: {day_diffs} vs "
     f"the other days (interaction {p_txt(h_day['lrt']['p_value'])}, {h_day['lrt_p_bonferroni_3_dims']:.2f} across "
     f"{het['n_dimensions_explored']} dimensions; {survive}), but peak day is the user's habit, not a day we can buy.",
     "modest for day, and not a lever we can buy; none for hour or daypart."),
    ("Which new users leave first?", "TEST", "blue",
     "Focus on the first session and Day 1; validate with a Day-1 re-engagement experiment (R6).",
     f"{(1 - ov['retention_1']) * 100:.1f}% of installs don't come back on Day 1. Players with fewer than 15 rounds "
     f"are {low_share * 100:.0f}% of installs, with D7 of at most {low_d7_max * 100:.1f}%; Day-1 returners are "
     f"{d1_ratio:.1f}× as likely to play on Day 7.",
     "descriptive and correlational (rounds overlap the D7 window)."),
    ("Should the first gate move from level 30 to 40?", "DON'T SHIP", "red",
     "Keep gate_30 (status quo); fix assignment and logging before any re-test (R5).",
     f"Naive D7 gap {dec['naive_diff'] * 100:+.2f} pp, but gate_40 received about {excess} extra low-engagement "
     f"installs (SRM WARNING, {p_txt(gsrm['p_value'])}). The part the gate could cause is about "
     f"{gate_eff * 100:+.1f} pp per install (95% CI {gate_ci[0] * 100:+.2f} to {gate_ci[1] * 100:+.2f}): probably "
     f"small, possibly zero, no sign of a benefit. D1 guardrail {g1['abs_lift'] * 100:+.2f} pp (95% CI "
     f"{g1['abs_ci_low'] * 100:+.2f} to {g1['abs_ci_high'] * 100:+.2f}); rounds played unchanged (mean "
     f"difference {rounds['mean_diff']:+.2f} rounds, 95% CI {rounds['mean_diff_boot_ci'][0]:+.2f} to "
     f"{rounds['mean_diff_boot_ci'][1]:+.2f}).",
     "weak on the size of the effect (not certified); enough for 'don't ship', because gate_30 is the status quo."),
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
share_ci = bz["share_of_ad_conversions_incremental_ci"]
RECS = pd.DataFrame([
    {"ID": "R1", "Who": "Growth PM",
     "What": f"Keep the ad campaign running at the current budget with an always-on {hold['share'] * 100:.0f}% PSA "
             "holdout, and report incremental (holdout-based) conversions instead of last-touch.",
     "Expected impact": f"About {inc['point']:,.0f} incremental conversions per comparable flight (95% CI "
                        f"{inc['ci_low']:,.0f} to {inc['ci_high']:,.0f}). Only "
                        f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}% (95% CI {share_ci[0] * 100:.0f}% to "
                        f"{share_ci[1] * 100:.0f}%) of ad-arm conversions are incremental: last-touch attribution "
                        f"would credit all {t['conv_t']:,}, overstating the campaign "
                        f"{bz['last_touch_overstatement_x']:.1f}×.",
     "How to measure": "Incremental conversion rate (ad minus holdout) and cost per incremental conversion, "
                       "reported every flight.",
     "Risk": f"The holdout costs about {hold['conversions_forgone']:,.0f} conversions per "
             f"{(t['n_t'] + t['n_c']) / 1e3:,.0f}K-user flight ({hold['users_per_588k_flight']:,.0f} users without "
             f"ads; USD {hold['value_forgone_usd'] / 1e3:,.1f}K at an assumed USD {value:,.0f}). Value and cost are "
             f"not in the data: confirm with Finance that the real CPM is below the breakeven (USD {be['point']:.2f} "
             f"at USD {value:,.0f} per conversion; 95% CI {be['ci_low']:.2f} to {be['ci_high']:.2f})."},
    {"ID": "R2", "Who": "Growth PM + media buyer",
     "What": "Don't double the budget blindly: this experiment compared ads with no ads at the current spend and "
             "cannot say what extra spend buys. Run a randomized 2x-budget / frequency-cap test first (50/50 or "
             "80/20), sized with the calculator below.",
     "Expected impact": f"Learns the marginal return before paying for it. Today's evidence: the lift lives in heavy "
                        f"users. No detectable lift for the {con['share_users_le_20_ads'] * 100:.0f}% of users who saw "
                        f"20 ads or fewer; {expo.loc['36-50', 'abs_lift'] * 100:.1f} to "
                        f"{expo.loc['101-200', 'abs_lift'] * 100:.1f} pp at 36-200 ads, the "
                        f"{con['share_ad_users_36_200'] * 100:.0f}% of ad users behind "
                        f"{con['share_incremental_conversions_36_200'] * 100:.0f}% of incremental conversions; 200+ "
                        f"ads unusable (95% CI {con['top_bucket_ci_pp'][0]:+.1f} to {con['top_bucket_ci_pp'][1]:+.1f} "
                        f"pp, {con['top_bucket_control_users']} control users).",
     "How to measure": "Marginal incremental conversions per extra USD 1K of spend (marginal iROAS), 2x arm vs 1x "
                       "arm.",
     "Risk": f"Exposure was not randomized and tracks how active a user is (control conversion rises from "
             f"{con['control_rate_lowest_bucket'] * 100:.1f}% to {con['control_rate_highest_bucket'] * 100:.1f}% "
             "across exposure buckets), so the pattern is a hypothesis for the frequency-cap arms, not a "
             "dose-response curve. Ad fatigue at high frequency is untested."},
    {"ID": "R3", "Who": "Media buyer",
     "What": "Don't re-plan spend by day or hour. If timing matters, pre-register a daypart test that randomizes the "
             "schedule (not the user's peak day).",
     "Expected impact": f"Avoids moving budget on a signal that is not a lever. Day: {day_diffs} vs the other days "
                        f"({survive}; interaction {p_txt(h_day['lrt']['p_value'])}, "
                        f"{h_day['lrt_p_bonferroni_3_dims']:.2f} across the {het['n_dimensions_explored']} dimensions "
                        f"explored), but peak day is a user habit. Hour ({p_txt(h_hour['lrt']['p_value'])}) and "
                        f"daypart without the sparse Night cell ({p_txt(h_dp['lrt_excluding_night']['p_value'])}) "
                        "show nothing.",
     "How to measure": "Pre-registered difference in lift between dayparts, with its 95% CI, in a test powered for "
                       "that difference.",
     "Risk": f"Day and hour are recorded after assignment and describe users, not a randomized schedule. Hourly "
             f"estimates rest on few control conversions ({h_hour['segments_with_zero_control_conversions']} night "
             "hours have none)."},
    {"ID": "R4", "Who": "Analytics + Engineering",
     "What": f"Fix the next experiment's design: 50/50 or 80/20 instead of {split_now}; log assignment timestamps; "
             "pre-register the primary metric and guardrails (unsubscribe / complaint rate, CPA); monitor SRM from "
             "day one against a documented split.",
     "Expected impact": f"At {split_now} the test had {pct_power(pw_ses['power_current_split'])} power for the "
                        f"smallest lift worth acting on ({sesoi * 100:.0f}% relative = {pw_ses['abs'] * 100:.2f} pp); "
                        f"the same {t['n_t'] + t['n_c']:,} users split 50/50 would have had "
                        f"{pct_power(pw_ses['power_5050_same_total'])} (for a 5% lift: "
                        f"{pct_power(pw_5['power_current_split'])} vs {pct_power(pw_5['power_5050_same_total'])}). "
                        f"A {sesoi * 100:.0f}% relative lift needs about {n10['0.5'] / 1e3:,.0f}K users at 50/50 vs "
                        f"{n10_now / 1e6:.2f}M at {split_now}.",
     "How to measure": "Power, metrics and guardrails written down before launch; a daily SRM check against the "
                       "documented split; novelty checked with the timestamps.",
     "Risk": "A bigger control group means more users without the ad during the test (see the cost column in the "
             "calculator)."},
    {"ID": "R5", "Who": "Game PM",
     "What": f"Keep gate_30 (status quo). Fix assignment and logging first (gate_40 received about {excess} extra "
             "low-engagement installs); re-test gate_40 only if the gate placement matters commercially.",
     "Expected impact": f"No sign of any benefit from gate_40. The naive {dec['naive_diff'] * 100:+.2f} pp D7 "
                        f"overstates the likely effect: the part the gate could cause is about "
                        f"{gate_eff * 100:+.2f} pp per install (95% CI {gate_ci[0] * 100:+.2f} to "
                        f"{gate_ci[1] * 100:+.2f}), about {abs(gate_eff) * PER:,.0f} fewer D7 players per "
                        f"{PER:,} installs (95% CI {abs(gate_ci[0]) * PER:,.0f} fewer to {gate_ci[1] * PER:,.0f} "
                        "more), possibly zero.",
     "How to measure": f"First an SRM check within strata of pre-gate play (today: fewer than 15 rounds "
                       f"{p_txt(sbs['rounds_lt_15']['p_value'])}, 30+ rounds {p_txt(sbs['rounds_ge_30']['p_value'])}). "
                       f"In a re-test: D7 among players who reach level 30 (primary), D1 and rounds as guardrails; "
                       f"about {retest['reachers_needed_total_5050']:,} players who reach the gate, i.e. "
                       f"{retest['installs_needed_total_5050']:,} installs at 50/50, to detect "
                       f"{retest['target_effect_reachers'] * 100:+.2f} pp among them (calculator preset).",
     "Risk": f"Not certified: SRM WARNING ({p_txt(gsrm['p_value'])}) and a negative control that moved (players who "
             f"never met a gate: {nc7['abs_lift'] * 100:+.2f} pp D7, {p_txt(nc7['p_value'])}). D1 guardrail "
             f"{g1['abs_lift'] * 100:+.2f} pp (95% CI {g1['abs_ci_low'] * 100:+.2f} to "
             f"{g1['abs_ci_high'] * 100:+.2f}): a D1 drop of up to {abs(g1['abs_ci_low']) * 100:.1f} pp cannot be "
             "ruled out."},
    {"ID": "R6", "Who": "Onboarding PM",
     "What": "Focus retention work on the first session and Day 1: a Day-1 re-engagement experiment for new players "
             "who stall early, with D7 retention as the primary metric.",
     "Expected impact": f"Targets the biggest drop: {(1 - ov['retention_1']) * 100:.1f}% of installs don't come back "
                        f"on Day 1, and the {low_share * 100:.0f}% who play fewer than 15 rounds ({low_n:,} players) "
                        f"have D7 of at most {low_d7_max * 100:.1f}%. Day-1 returners are {d1_ratio:.1f}× as likely "
                        "to play on Day 7: the earliest strong signal of who stays.",
     "How to measure": "Randomized test: D7 retention primary, D1 secondary; size it with the calculator "
                       "(Onboarding preset).",
     "Risk": "The evidence is correlational. Day-1 return is an association, and rounds are counted over 14 days "
             "(overlapping D7), so the rounds-retention link is partly definitional and 'fewer than 15 rounds' is "
             "not a Day-0 targeting rule. Only the experiment shows whether a Day-1 nudge lifts D7."},
]).set_index("ID")
st.table(RECS)
st.download_button("Download recommendations (CSV)", RECS.to_csv().encode("utf-8"), file_name="recommendations.csv",
                   mime="text/csv", key="p7_download_recs")

# ------------------------------------------------------------------ sample-size calculator
st.subheader("Sizing the next experiment")
st.markdown("How many users does the next test need? Two-sided test of two proportions (normal approximation with "
            "Cohen's h), the same method as the power numbers on page 4.")
MIN_WEEKS = 2  # minimum test length: every weekday covered at least twice
# Presets from exact counts (results.json rates are rounded), so they reproduce results.json's sample sizes.
reach_share = (reach7["n_t"] / gate["players"]["gate_40"] + reach7["n_c"] / gate["players"]["gate_30"]) / 2
p_reach_c, p_reach_t = reach7["conv_c"] / reach7["n_c"], reach7["conv_t"] / reach7["n_t"]
PRESETS = {
    "Ad test: conversion rate": {"baseline": p_psa, "rel": sesoi, "reach": 1.0},
    "Onboarding test: D7 retention": {"baseline": (g7["conv_t"] + g7["conv_c"]) / (g7["n_t"] + g7["n_c"]),
                                      "rel": sesoi, "reach": 1.0},
    "Gate re-test: D7 of players who reach level 30": {"baseline": p_reach_c, "rel": p_reach_t / p_reach_c - 1,
                                                       "reach": reach_share},
}


def apply_preset() -> None:
    p = PRESETS[st.session_state["p7_preset"]]
    st.session_state["p7_baseline"] = p["baseline"] * 100
    st.session_state["p7_rel_mde"] = p["rel"] * 100
    st.session_state["p7_reach"] = p["reach"] * 100
    st.session_state["p7_share"] = 50


preset = st.radio(
    "Start from", list(PRESETS), horizontal=True, key="p7_preset", on_change=apply_preset,
    help=f"Ad test: the PSA (control) conversion rate, {t['rate_c'] * 100:.2f}%, and the smallest lift worth acting "
         f"on ({sesoi * 100:.0f}% relative). Onboarding test: overall D7 retention in Cookie Cats, "
         f"{ov['retention_7'] * 100:.2f}%, same {sesoi * 100:.0f}% lift. Gate re-test: D7 among players who reach "
         f"level 30 ({p_reach_c * 100:.2f}% in gate_30), the {retest['target_effect_reachers'] * 100:+.2f} pp gap "
         f"seen among them, and the {reach_share * 100:.1f}% of installs who reach the gate.")
if "p7_baseline" not in st.session_state:
    apply_preset()

r1 = st.columns(4, gap="medium", vertical_alignment="bottom")
baseline = r1[0].number_input("Baseline rate in control (%)", min_value=0.01, max_value=99.0, step=0.1,
                              format="%.2f", key="p7_baseline",
                              help="Expected rate without the change: conversion rate, retention rate, etc.")
rel_mde = r1[1].number_input("Smallest change (relative %)", min_value=-90.0, max_value=200.0,
                             step=1.0, format="%.2f", key="p7_rel_mde",
                             help="The minimum detectable effect (MDE): the smallest relative change that would "
                                  "change the decision. Negative for a drop (e.g. a retention loss). Smaller effects "
                                  "need many more users.")
share = r1[2].slider("Users in treatment (%)", min_value=50, max_value=99, step=1, key="p7_share",
                     help="50 = an even split. Uneven splits keep more users on the new experience but need a "
                          "larger total sample.")
reach = r1[3].number_input("Reach of the change (%)", min_value=1.0, max_value=100.0, step=1.0,
                           format="%.1f", key="p7_reach",
                           help="Share of entrants who reach the changed experience; only they can be affected "
                                "(for example, the share of installs who get to level 30). The test is analysed on "
                                "them; entrants needed = users needed ÷ this share.")
r2 = st.columns(4, gap="medium", vertical_alignment="bottom")
alpha = r2[0].select_slider("Significance level (alpha)", options=[0.01, 0.05, 0.10], value=C.ALPHA,
                            format_func=lambda a: f"{a:g}", key="p7_alpha",
                            help="Chance of a false positive we accept when there is no real effect.")
power = r2[1].select_slider("Power", options=[0.70, 0.80, 0.90, 0.95], value=C.POWER,
                            format_func=lambda p: f"{p:.0%}", key="p7_power",
                            help="Chance of detecting the effect if it is really there at the MDE size.")
daily = r2[2].number_input("Entrants per day", min_value=100, max_value=10_000_000, value=20_000, step=1_000,
                           key="p7_daily",
                           help="Illustrative default: the datasets have no dates, so traffic is unknown. Enter the "
                                "number of users per day who could enter the test.")

p_c = baseline / 100
p_t = p_c * (1 + rel_mde / 100)
if abs(rel_mde) < 0.01:
    st.warning("Enter a non-zero change to detect.")
elif not 0 < p_t < 1:
    st.warning("Baseline × (1 + change) must stay between 0% and 100%. Change the baseline or the change.")
else:
    eff = p_t - p_c

    def size(s: float) -> dict:
        n = S.required_total_n(p_c, eff, s, alpha, power)
        n_t = round(n * s)
        entrants = math.ceil(n / (reach / 100))
        return {"total": n, "n_t": n_t, "n_c": n - n_t, "entrants": entrants, "days": math.ceil(entrants / daily),
                "cost": round((n - n_t) * eff) if eff > 0 else round(n_t * -eff)}

    sel = size(share / 100)
    out = st.columns(4)
    out[0].metric("Total users needed", f"{sel['total']:,}", f"{sel['n_t']:,} T / {sel['n_c']:,} C",
                  delta_color="off", delta_arrow="off",
                  help=f"Users in the analysis (T = treatment, C = control) at a {share}/{100 - share} split, "
                       "rounded up. For a change only some entrants reach (like a level-30 gate), these are the "
                       "users who reach it.")
    out[1].metric("Entrants needed", f"{sel['entrants']:,}", f"{reach:.3g}% reach the change", delta_color="off",
                  delta_arrow="off", help="Users who must enter the test so that enough of them reach the change: "
                                          "total users needed ÷ the share who reach it.")
    out[2].metric(f"Days at {daily:,} entrants/day", f"{sel['days']:,}",
                  f"plan {max(MIN_WEEKS, math.ceil(sel['days'] / 7))} full weeks", delta_color="off",
                  delta_arrow="off",
                  help=f"Entrants needed ÷ entrants per day, rounded up. The plan rounds up to whole weeks, with "
                       f"a minimum of {MIN_WEEKS} (see the note below the table).")
    out[3].metric("Effect to detect", f"{eff * 100:+.2f} pp", f"{baseline:.2f}% to {p_t * 100:.2f}%",
                  delta_color="off", delta_arrow="off", help="Baseline × relative change, in percentage points.")

    splits = sorted({0.5, 0.8, 0.9, plan, share / 100})
    base_5050 = size(0.5)["total"]
    rows = []
    for s in splits:
        z = size(s)
        label = f"{s * 100:.0f}/{(1 - s) * 100:.0f}" + (" (selected)" if math.isclose(s, share / 100) else "")
        rows.append({"Split": label, "Total users": z["total"], "vs 50/50": z["total"] / base_5050,
                     "Days": z["days"], "Cost if real": z["cost"]})
    scen = pd.DataFrame(rows)
    gain = eff > 0
    chart_col, table_col = st.columns(2, gap="large")
    with chart_col:
        # Power for a drop of x from p_c equals power for a rise of x from 1 - p_c (Cohen's h is symmetric).
        p_plot = p_c if gain else 1 - p_c
        max_pp = max(min(abs(eff) * 100 * 2.5, (0.999 - p_plot) * 100), 0.1)
        fig = F.fig_power_curve(
            p_plot, sel["n_t"], sel["n_c"], alpha, abs(eff), "Power of the planned test by true effect (%)",
            f"{sel['n_t']:,} treatment and {sel['n_c']:,} control users, alpha {alpha:g}.",
            max_lift_pp=max_pp, target_power=power, reference_label="effect to detect")
        word = "rise" if gain else "drop"
        fig.update_xaxes(title_text=f"True {word} in the metric (pp)")
        fig.update_traces(hovertemplate=f"True {word} %{{x:.2f}} pp<br>Power %{{y:.0f}}%<extra></extra>",
                          selector=dict(name="Power"))
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
            "Cost if real": st.column_config.NumberColumn(
                "Cost if real", format="localized",
                help="If the true effect equals the one entered: for a gain, the conversions (or retained players) "
                     "the control group misses during the test (control users × effect); for a drop, those the "
                     "treatment group loses (treatment users × effect)."),
        })
        st.caption("Cost if real: what the test itself gives up if the effect is real. For a gain the control group "
                   "pays it, for a drop the treatment group does. Uneven splits move that cost around but need far "
                   "more users in total.")
    n_now = size(plan)["total"]
    text = (f"To detect a {rel_mde:+.3g}% relative change on a {baseline:.2f}% baseline ({eff * 100:+.2f} pp) with "
            f"{power:.0%} power at alpha {alpha:g}, a {share}/{100 - share} split needs {sel['total']:,} users "
            f"({sel['n_t']:,} treatment / {sel['n_c']:,} control)")
    if reach < 100:
        text += f", i.e. {sel['entrants']:,} entrants when {reach:.3g}% of them reach the change"
    text += (f": about {sel['days']:,} days at {daily:,} entrants a day. The power curve crosses {power:.0%} at that "
             "effect; smaller true effects would often be missed.")
    if preset.startswith("Ad test") and not math.isclose(share / 100, plan):
        text += (f" The same test at {split_now}, the ad test's design, needs {n_now:,} users "
                 f"({n_now / base_5050:.1f}× the 50/50 sample).")
    takeaway(text)
    if preset.startswith("Gate re-test"):
        st.caption("Gate re-test: run it only after the assignment / logging problem is fixed, and check the split "
                   "within strata of pre-gate play as well as overall.")
    caveat(f"Plan in whole weeks, at least {MIN_WEEKS}, even if the sample is reached sooner: weekly habits matter "
           f"(in the ad test, users with different peak days responded differently, interaction "
           f"{p_txt(h_day['lrt']['p_value'])}) and, without timestamps, this data cannot show whether an effect fades "
           "after a novelty period. Decide the sample size before launch and do not stop early on a good-looking "
           "p-value.")

# ------------------------------------------------------------------ risks + data asks
st.subheader("Risks, limitations and what I would ask for next")
risk_col, ask_col = st.columns(2, gap="large")
with risk_col:
    st.markdown("**Risks and limitations**")
    st.markdown(f"""
- **No revenue or cost.** Dollar figures rest on an assumed USD {value:,.0f} per conversion and on a CPM we do not
  have; the headline business number is incremental conversions.
- **No timestamps.** We cannot check novelty effects, how long the lift lasts, or when users were assigned.
- **Quota-exact split.** {ad['srm']['n_t']:,} is the nearest whole number to {plan * 100:.0f}% of
  {t['n_t'] + t['n_c']:,} users ({ad['srm']['deviation_users']:.2f} users off, against a chance gap of about
  {ad['srm']['sd_users_under_random_assignment']:,.0f}), so the ad test's SRM check passes by construction. Exposure
  parity ({ad['groups']['ad']['mean_ads']:.1f} vs {ad['groups']['psa']['mean_ads']:.1f} ads per user) is the
  meaningful check; the shapes differ a little (KS distance {ad['total_ads_ks']['stat']:.3f}).
- **Post-assignment segments.** Day, hour and exposure are recorded after assignment, so segment results are
  exploratory and never used as covariates. As a sensitivity check, lift standardized over these strata is
  {min(std_lifts):.2f} to {max(std_lifts):.2f} pp vs {t['abs_lift'] * 100:.2f} pp crude: no reversal.
- **Multiple comparisons.** One interaction test per dimension ({het['n_dimensions_explored']} explored: day, hour,
  exposure; dayparts regroup hours), then segment-vs-rest contrasts with Holm correction. Per-segment "lift ≠ 0"
  tests measure power, not heterogeneity, so they are not used as evidence.
- **Gate experiment.** SRM WARNING on raw counts ({p_txt(gsrm['p_value'])}), concentrated among players with fewer
  than 15 rounds ({p_txt(sbs['rounds_lt_15']['p_value'])}), and a negative control that moved
  ({p_txt(nc7['p_value'])}): the result is not certified.
- **Retention data.** One install cohort (no install dates); D1 / D7 mean "played on day 1 / day 7"; rounds are
  counted over 14 days and overlap the D7 window, so rounds vs retention is partly definitional.
- **Two unrelated products.** The ad campaign (2021) and Cookie Cats (2017) share no users, so we cannot link ad
  conversions to later retention.
""")
with ask_col:
    st.markdown("**Data I would ask for next**")
    st.markdown(f"""
- **Assignment logs with timestamps and the documented split** (Engineering): a real SRM check, novelty and
  duration analysis, and where gate_40's {excess} extra low-engagement installs came from.
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

**Sample-size calculator.** Fill in the rate you expect without the change (baseline), the smallest change worth
acting on (relative; negative for a drop), how users are split, how many entrants actually reach the change, and how
strict the test should be (alpha, power). It returns how many users the test needs and how long that takes at your
traffic. The presets reproduce the numbers in this analysis: the ad test, an onboarding test on D7, and the gate
re-test ({retest['reachers_needed_total_5050']:,} players who reach level 30, i.e.
{retest['installs_needed_total_5050']:,} installs). The table compares splits: an uneven split like {split_now} shows
the new experience to more users but needs far more users in total, because the small group is measured
imprecisely.

**Words used.**
- **MDE (minimum detectable effect):** the smallest true effect the test would detect most of the time (as often as
  the power says). It is not the effect we expect.
- **Alpha:** the false-alarm rate we accept ({C.ALPHA:.0%} in this project).
- **Power:** the chance of catching a real effect of MDE size ({C.POWER:.0%} in this project). It describes the
  design; it is never computed at the observed effect.
- **Holdout:** a share of users kept on the PSA so the campaign's incremental effect can be measured every flight.

**Common misreadings.**
- "The calculator gives a number of days, so we can stop earlier if it already looks good." Decide the length
  first and do not peek-and-stop; stopping on a good-looking day inflates false positives.
- "A smaller MDE is always better." It costs users and time; pick the smallest effect that would change the
  decision.
- "gate_40 costs {abs(dec['naive_diff']) * 100:.2f} pp of D7." That is the naive gap between unbalanced arms; the
  part the gate could cause is about {abs(gate_eff) * 100:.1f} pp per install and may be zero.
- The dollar numbers in R1 assume a value per conversion; the incremental conversions do not.
""")
