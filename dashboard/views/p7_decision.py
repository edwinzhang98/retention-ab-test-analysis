"""Page 7 · Decision & Recommendations: what to do, who owns it, how we will know it
worked, and a sample-size calculator for the next experiment (src.stats power functions).

The R1–R6 table follows the project's canonical recommendations (README, readout,
report and executive summary say the same); its numbers are read from results.json.
The calculator presets reproduce the sample sizes stored in results.json: the ad
test (10% lift), the onboarding test (R6) and the gate re-test (R5).
"""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from common import (C, F, S, approx, caveat, ci_text, how_to_read, load_cache, load_results, p_text,
                    page_header, sgn, sgn_pp, show, takeaway)

res = load_results()
ad, ck = res["ad"], res["cookie"]
t, bz, pw = ad["test"], ad["business"], ad["power"]
inc, be, hold = bz["incremental_conversions"], bz["breakeven_cpm_usd"], bz["always_on_holdout_cost"]
lt_x, lt_ci = bz["last_touch_overstatement_x"], bz["last_touch_overstatement_ci"]
het = ad["heterogeneity"]
h_day, h_hour, h_dp, h_exp = het["most_ads_day"], het["most_ads_hour"], het["daypart"], het["exposure_bucket"]
con = h_exp["concentration"]
le20 = con["le_20_ads_pooled"]
gate = ck["gate"]
g7, gsrm, sbs = gate["retention_7"], gate["srm"], gate["srm_by_stratum"]
dec, retest = gate["d7_decomposition"], gate["retest_sizing"]
# The re-test is sized for a drop; a rise of the same size needs a little more (on Cohen's h, a change towards 50% is
# a smaller effect): +2% install-level, +0.7% for the analysis among players who reach level 30. Quote the larger.
rise_extra = max(retest["installs_needed_install_level_5050_if_rise"] / retest["installs_needed_install_level_5050"],
                 retest["installs_needed_reacher_analysis_5050_if_rise"]
                 / retest["installs_needed_reacher_analysis_5050"]) - 1
gate_eff, gate_ci = dec["install_level_effect_if_only_reachers"], dec["install_level_effect_ci_if_only_reachers"]
not_gate = (dec["composition"] + dec["within_never_reached_30"]) / dec["naive_diff"]
nc7 = gate["negative_control"]["never_reached_30"]["retention_7"]
band = gate["retention_by_rounds_band"]
d7_30 = band["rounds_ge_30"]["retention_7"]
# D1 guardrail: the part of the D1 gap the gate could explain, per install (the 30+ band figure is diluted)
d1_dec = gate["d1_decomposition"]
d1_eff, d1_ci = d1_dec["install_level_effect_if_only_reachers"], d1_dec["install_level_effect_ci_if_only_reachers"]
rr = gate["rounds_among_reachers"]
excess = gate["best_case_for_gate_40"]["excess_players_gate_40"]  # cleaned data: ≈790
net_lt15 = sbs["rounds_lt_15"]["net_excess_t"]
ov, early = ck["overall"], ck["early_churn_segment"]
r6 = early["onboarding_test_sizing"]
d7_yes, d7_no = early["d7_if_returned_day1"], early["d7_if_not_returned_day1"]
n10 = pw["total_n_for_10pct_rel_lift"]
sesoi = pw["smallest_lift_of_interest_rel"]
pw_ses = pw["power_at_relative_lift"][str(sesoi)]
value = bz["value_per_conversion_usd"]
plan = ad["srm"]["intended_share_t"]            # the ad test's (inferred, most likely quota) 96/4 design
split_now = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
n_users = t["n_t"] + t["n_c"]
p_psa = t["conv_c"] / t["n_c"]
std_lifts = [het[d]["sensitivity_stratified"]["mh_risk_diff"] * 100
             for d in ("most_ads_day", "most_ads_hour", "daypart", "exposure_bucket")]
PER = 10_000  # installs, to scale a per-install effect into players


def pct_power(x: float) -> str:
    return "≈100%" if x >= 0.995 else f"{x * 100:.0f}%"


def k(n: float) -> str:
    """113,669 -> '114K' (prefix '≈' at the call site)."""
    return f"{n / 1e3:,.0f}K"


@st.cache_data(show_spinner=False)
def segment_table(dim: str, order: tuple) -> pd.DataFrame:
    """Per-segment lift and segment-vs-rest contrast (Holm), same call as the report's charts."""
    return S.segment_lifts(load_cache("agg_ad_cells"), dim, "ad", "psa", alpha=C.ALPHA, method="holm",
                           order=list(order)).set_index(dim)


days = segment_table("most_ads_day", tuple(C.DAY_ORDER))
differing = h_day["segments_differing_holm"]
day_diffs = " and ".join(f"{d}-peak users {sgn_pp(days.loc[d, 'diff_vs_rest'])}" for d in differing) \
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
     f"Keep the campaign at the current budget, with an always-on {hold['share'] * 100:.0f}% PSA holdout (R1).",
     f"{sgn_pp(t['abs_lift'])} conversion ({ci_text(t['abs_ci_low'], t['abs_ci_high'], signed=False)}; "
     f"{p_text(t['p_value'])}), ≈{approx(inc['point'])} incremental conversions (95% CI {approx(inc['ci_low'])}–"
     f"{approx(inc['ci_high'])}). Only {bz['share_of_ad_conversions_incremental'] * 100:.0f}% of the ad arm's "
     f"conversions are incremental: last-touch attribution would overstate the campaign {lt_x:.1f}× (95% CI "
     f"{lt_ci[0]:.1f}–{lt_ci[1]:.1f}×). Exposure parity holds ({ad['groups']['ad']['mean_ads']:.1f} vs "
     f"{ad['groups']['psa']['mean_ads']:.1f} ads per user); the {split_now} split is most likely a fixed quota, so its "
     "SRM check is uninformative.",
     "strong (randomized test, interval well above zero)."),
    ("Is it worth doubling the budget?", "TEST FIRST", "orange",
     "Don't double blindly; test it with up to 2× impressions per user or a frequency cap (R2).",
     "The test compared ads with no ads at the current spend, not 1× with 2×. The lift lives in heavy users: the "
     f"{con['share_users_le_20_ads'] * 100:.0f}% of users who saw ≤ 20 ads show no lift we could measure "
     f"({sgn_pp(le20['abs_lift'])}, {ci_text(le20['abs_ci_low'], le20['abs_ci_high'], unit='')}), while the "
     f"{con['share_ad_users_36_200'] * 100:.0f}% of ad users who saw 36–200 ads hold "
     f"{con['share_incremental_conversions_36_200'] * 100:.0f}% of the bucket-by-bucket incremental conversions. "
     "Exposure tracks how active a user is, so this is not a frequency curve.",
     "not answerable with this data."),
    ("Should spend move to the best day or hour?", "DON'T (YET)", "gray",
     "Don't re-plan spend by day or hour; if timing matters, pre-register a test that randomizes the delivery "
     "schedule (R3).",
     f"Hour: no evidence (interaction {p_text(h_hour['lrt']['p_value'])}). Daypart: "
     f"{p_text(h_dp['lrt']['p_value'])} is driven by Night (0–5), where the control arm has {night['conversions']} "
     f"conversion among {night['users']:,} users; without it {p_text(h_dp['lrt_excluding_night']['p_value'])}. Day: "
     f"{day_diffs} vs "
     f"the other days (interaction {p_text(h_day['lrt']['p_value'])}, {h_day['lrt_p_bonferroni_3_dims']:.2g} allowing "
     f"for {het['n_dimensions_explored']} dimensions; {survive}), but part of Tuesday's lift is a low control rate "
     f"({days.loc['Tuesday', 'rate_c'] * 100:.2f}% in its PSA arm), and peak day is a user habit recorded after "
     "assignment, not a slot we buy.",
     "modest for day, and not a lever we can buy; none for hour; daypart rests on one control conversion at night."),
    ("Which new users leave first?", "TEST", "blue",
     "Focus on the Day-1 return; test a randomized Day-1 re-engagement nudge (R6).",
     f"{(1 - ov['retention_1']) * 100:.1f}% of installs don't come back on Day 1, the largest drop. Players with "
     f"< 15 rounds are {early['share_of_installs'] * 100:.0f}% of installs and only "
     f"{early['retention_7'] * 100:.1f}% of them play on Day 7; Day-1 returners are {d7_yes / d7_no:.1f}× as likely "
     f"to play on Day 7 ({d7_yes * 100:.1f}% vs {d7_no * 100:.1f}%).",
     "descriptive and correlational (rounds overlap the D7 window)."),
    ("Should the first gate move from level 30 to 40?", "DON'T SHIP", "red",
     "Keep gate_30 (status quo); fix assignment and logging before any re-test (R5).",
     f"The naive comparison shows gate_40's D7 {abs(dec['naive_diff']) * 100:.2f} pp lower "
     f"({ci_text(g7['abs_ci_low'], g7['abs_ci_high'], unit='')}), but it is not certified: gate_40 received "
     f"≈{excess} extra installs (SRM WARNING, {p_text(gsrm['p_value'])}), with a net excess of "
     f"{net_lt15} among players with < 15 rounds. About {round(not_gate * 10) * 10:.0f}% of the naive gap sits where "
     f"the gate cannot act; the part the gate could explain is {sgn_pp(gate_eff)} per install "
     f"({ci_text(gate_ci[0], gate_ci[1], unit='')}), not an estimate of its effect and possibly zero. No sign of a "
     f"retention benefit, and no sign of a D1 effect: the part of the D1 gap the gate could explain is "
     f"{sgn_pp(d1_eff)} per install ({ci_text(d1_ci[0], d1_ci[1], unit='')}). Among players with 30+ rounds, "
     f"gate_40 players played a little more (median {rr['median_t']:.0f} vs {rr['median_c']:.0f} rounds; descriptive). "
     "Assignment is uncertified and the group is defined by rounds played, so it does not show that gate_40 causes "
     f"more play. Their D7 "
     f"is not higher ({sgn_pp(d7_30['abs_lift'])}, {ci_text(d7_30['abs_ci_low'], d7_30['abs_ci_high'], unit='')}).",
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

# ------------------------------------------------------------------ recommendations (canonical R1–R6)
st.subheader("Recommendations")
st.caption("Each item: who owns it, what to do, the expected impact (from this analysis), how we will measure it, "
           "and the main risk. Impact numbers are point estimates with 95% intervals where they exist.")
RECS = pd.DataFrame([
    {"ID": "R1", "Owner": "Growth PM",
     "What": f"Keep the campaign at the current budget, with an always-on {hold['share'] * 100:.0f}% PSA holdout.",
     "Expected impact": f"≈{approx(inc['point'])} incremental conversions per comparable flight (95% CI "
                        f"{approx(inc['ci_low'])}–{approx(inc['ci_high'])}). The holdout forgoes "
                        f"≈{hold['conversions_forgone']:,.0f} conversions per {k(n_users)}-user flight "
                        f"(≈USD {hold['value_forgone_usd'] / 1e3:,.1f}K at USD {value:,.0f}) vs. no holdout; this "
                        f"test's {hold['as_run_control_share'] * 100:.0f}% PSA arm already forgoes "
                        f"≈{hold['as_run_control_conversions_forgone']:,.0f}. Keeps the real effect measured: "
                        f"last-touch would overstate it {lt_x:.1f}× (95% CI {lt_ci[0]:.1f}–{lt_ci[1]:.1f}×).",
     "How we'll measure": "Incremental conversions and cost per incremental conversion vs. the holdout, per flight "
                          "and at least quarterly.",
     "Main risk": f"Value per conversion and CPM are unknown: Finance confirms actual CPM < USD {be['point']:.2f} "
                  f"(USD {be['ci_low']:.2f} at the pessimistic end). One flight's holdout read is about as precise "
                  "as this test; judge trends over several flights."},
    {"ID": "R2", "Owner": "Growth PM + media buyer",
     "What": "Don't double blindly; test it. A user-level test where one arm gets up to 2× today's impressions per "
             "user (the closest stand-in for 2× budget) or a frequency cap; 50/50 or 80/20; users tiered by activity "
             "measured before the test. A true budget test needs a geo split.",
     "Expected impact": f"Learn the marginal return before committing ≈2× spend. Today's lift sits in the "
                        f"{con['share_ad_users_36_200'] * 100:.0f}% of ad users who saw 36–200 ads, so the average "
                        "return may not hold at 2×.",
     "How we'll measure": "Incremental conversions per extra USD 1K spent.",
     "Main risk": "The marginal lift of extra impressions may be smaller than the ad-vs-PSA lift. Size this test "
                  "on a pre-agreed smallest marginal lift worth paying for; the "
                  f"{k(n10['0.5'])} users of the ad-vs-PSA design is a benchmark, not this test's sample size. Heavy users may "
                  "tire of more ads (not measurable here)."},
    {"ID": "R3", "Owner": "Media buyer",
     "What": "Don't re-plan spend by day or hour. If timing matters, pre-register a test that randomizes the "
             "delivery schedule (weekday and time slot, e.g. Tuesday vs. Thursday delivery).",
     "Expected impact": "Avoids moving money on a pattern that describes users' habits, not slots we buy.",
     "How we'll measure": "Difference in lift between randomized delivery slots, with its 95% CI.",
     "Main risk": "Missing a small real timing effect."},
    {"ID": "R4", "Owner": "Analytics + Eng",
     "What": f"Fix the next test's design: 50/50 or 80/20 split ({split_now} had "
             f"{pct_power(pw_ses['power_current_split'])} power for a {sesoi * 100:.0f}% lift); log assignment "
             "timestamps; pre-register the primary metric, the smallest lift worth acting on, and guardrails "
             "(unsubscribe / complaint rate, cost per acquisition); automatic daily SRM check.",
     "Expected impact": f"The same users at 50/50 have {pct_power(pw_ses['power_5050_same_total'])} power for a "
                        f"{sesoi * 100:.0f}% lift and an MDE of {pw['mde_if_5050_same_total']['mde_abs'] * 100:.2f} pp "
                        f"instead of {pw['mde_current']['mde_abs'] * 100:.2f} pp; timestamps show whether the effect "
                        "fades.",
     "How we'll measure": "Power / MDE reviewed at design time; daily SRM check.",
     "Main risk": "A bigger control group means more users miss the ads during the test; logging work for Eng."},
    {"ID": "R5", "Owner": "Game PM (Eng + Analytics fix assignment)",
     "What": f"Keep the first gate at level 30 (no change). Fix assignment / logging first (gate_40 received "
             f"≈{excess} extra installs, with a net excess of {net_lt15} among players with < 15 rounds). Re-test only "
             "if the gate position matters commercially.",
     "Expected impact": f"Avoids a change with no sign of a retention benefit. The part of the D7 gap the gate could "
                        f"explain is ≈{sgn(gate_eff * 100, 1)} pp per install "
                        f"({ci_text(gate_ci[0], gate_ci[1], unit='')}; ≈{abs(gate_eff) * PER:,.0f} fewer Day-7 "
                        f"players per {PER:,} installs), and even that may not be the gate. Among players with "
                        f"30+ rounds (who could have reached level 30), gate_40 players played a little more "
                        f"(median {rr['median_t']:.0f} vs. {rr['median_c']:.0f} rounds; descriptive). Assignment is "
                        "uncertified and the group is defined by rounds played, so it does not show that gate_40 causes more play.",
     "How we'll measure": f"Any re-test: pre-register a "
                          f"{retest['smallest_d7_change_per_install'] * 100:.1f} pp D7 change per install as the "
                          "smallest change worth acting on (agree with the Game PM); "
                          f"≈{k(retest['installs_needed_reacher_analysis_5050'])} installs at 50/50 with the primary "
                          "analysis among players who reach level 30 "
                          f"(≈{k(retest['reachers_needed_5050'])} of them), "
                          f"≈{k(retest['installs_needed_install_level_5050'])} if analysed over all installs; daily "
                          "50/50 group-size check.",
     "Main risk": f"Quoting the raw {sgn_pp(dec['naive_diff'])} would overstate the effect; missing a small real "
                  "effect either way."},
    {"ID": "R6", "Owner": "Onboarding PM (with CRM)",
     "What": "Focus retention work on the Day-1 return: a randomized Day-1 re-engagement test for new players "
             "who play little on their first day, D7 primary.",
     "Expected impact": f"Targets the biggest drop: {(1 - ov['retention_1']) * 100:.1f}% of installs don't return on "
                        f"Day 1; {early['share_of_installs'] * 100:.0f}% play < 15 rounds and only "
                        f"{early['retention_7'] * 100:.1f}% of them play on Day 7. Illustrative scenario, not a forecast "
                        f"or an upper bound: shifting 1 pp of installs from the non-returners' {d7_no * 100:.1f}% D7 "
                        f"to the Day-1 returners' {d7_yes * 100:.1f}% would add about {d7_yes - d7_no:.2f} pp of D7; "
                        "R6's real impact must be measured.",
     "How we'll measure": f"D7 among targeted players (primary), D1 (secondary). Sizing: "
                          f"+{r6['target_lift_abs'] * 100:.1f} pp D7 on the {early['retention_7'] * 100:.1f}% base "
                          f"(placeholder target) needs ≈{k(r6['players_needed_5050'])} target players "
                          f"(≈{k(r6['installs_needed_5050'])} installs) at 50/50.",
     "Main risk": "Rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use "
                  "first-day play; the play–retention link may not be causal; notification fatigue."},
]).set_index("ID")
# On a phone the five text columns do not fit side by side, so each recommendation is stacked as a block with
# its column names (CSS scoped to this page; the names come from the table so they stay in sync).
stack_labels = "\n".join(f'  [data-testid="stTable"] td:nth-of-type({i})::before {{content: "{c}";}}'
                         for i, c in enumerate(RECS.columns, 1))
st.markdown(f"""<style>
@media (max-width: 640px) {{
  [data-testid="stTable"] thead {{display: none;}}
  [data-testid="stTable"] table, [data-testid="stTable"] tbody, [data-testid="stTable"] tr,
  [data-testid="stTable"] tbody th, [data-testid="stTable"] td {{display: block; width: auto !important;}}
  [data-testid="stTable"] tr {{border-top: 2px solid #d9d8d4; padding: .3rem 0 .6rem 0;}}
  [data-testid="stTable"] tbody th, [data-testid="stTable"] td {{border: none !important; padding: .15rem .5rem;}}
  [data-testid="stTable"] td::before {{display: block; font-size: .75rem; font-weight: 600; color: #6b6a66;}}
{stack_labels}
}}
</style>""", unsafe_allow_html=True)
st.table(RECS)
st.download_button("Download recommendations (CSV)", RECS.to_csv().encode("utf-8"), file_name="recommendations.csv",
                   mime="text/csv", key="p7_download_recs")

# ------------------------------------------------------------------ sample-size calculator
st.subheader("Sizing the next experiment")
st.markdown("How many users does the next test need? Two-sided test of two proportions (normal approximation with "
            "Cohen's h), the same method as the power numbers on page 4. Size a test at the smallest change worth "
            "acting on, fixed before launch, never at an effect observed in an earlier test.")
MIN_WEEKS = 2  # minimum test length: every weekday covered at least twice
# Each preset reproduces a sample size stored in results.json (same src.stats function, same inputs).
PRESETS = {
    f"Ad test ({sesoi * 100:.0f}% lift)": {"baseline": p_psa, "change": sesoi * p_psa, "reach": 1.0},
    "Onboarding test (R6)": {"baseline": early["retention_7"], "change": r6["target_lift_abs"],
                             "reach": early["share_of_installs"]},
    "Gate re-test (R5)": {"baseline": retest["baseline_d7_reachers"],
                          "change": -retest["equivalent_change_among_reachers"], "reach": retest["share_reached_30"]},
}
AD_PRESET, R6_PRESET, GATE_PRESET = PRESETS


def apply_preset() -> None:
    p = PRESETS[st.session_state["p7_preset"]]
    st.session_state["p7_baseline"] = p["baseline"] * 100
    st.session_state["p7_change"] = p["change"] * 100
    st.session_state["p7_reach"] = p["reach"] * 100
    st.session_state["p7_share"] = 50


preset = st.radio(
    "Start from", list(PRESETS), horizontal=True, key="p7_preset", on_change=apply_preset,
    help=f"Ad test: the PSA (control) conversion rate, {p_psa * 100:.2f}%, and the smallest lift worth acting on, "
         f"{sesoi * 100:.0f}% relative = {sesoi * p_psa * 100:.2f} pp (a placeholder in config.yaml). Onboarding test "
         f"(R6): D7 of players with < 15 rounds ({early['retention_7'] * 100:.2f}%), a "
         f"+{r6['target_lift_abs'] * 100:.1f} pp target (placeholder) and their "
         f"{early['share_of_installs'] * 100:.1f}% share of installs. Gate re-test (R5): D7 among gate_30 players who "
         f"reach level 30 ({retest['baseline_d7_reachers'] * 100:.2f}%), the "
         f"{sgn(-retest['equivalent_change_among_reachers'] * 100)} pp change among them that equals "
         f"{retest['smallest_d7_change_per_install'] * 100:.1f} pp per install (fixed in advance), and the "
         f"{retest['share_reached_30'] * 100:.1f}% of installs who reach level 30.")
if "p7_baseline" not in st.session_state:
    apply_preset()

r1 = st.columns(4, gap="medium", vertical_alignment="bottom")
baseline = r1[0].number_input("Baseline rate in control (%)", min_value=0.01, max_value=99.0, step=0.1,
                              format="%.2f", key="p7_baseline",
                              help="Expected rate without the change: conversion rate, retention rate, etc.")
change = r1[1].number_input("Smallest change worth acting on (pp)", min_value=-50.0, max_value=50.0,
                            step=0.05, format="%.2f", key="p7_change",
                            help="The minimum detectable effect (MDE) in percentage points: the smallest true change "
                                 "that would change the decision, agreed before launch. Negative for a drop (e.g. a "
                                 "retention loss). Smaller changes need many more users.")
share = r1[2].slider("Users in treatment (%)", min_value=50, max_value=99, step=1, key="p7_share",
                     help="50 = an even split. Uneven splits keep more users on the new experience but need a "
                          "larger total sample.")
reach = r1[3].number_input("Reach of the change (%)", min_value=1.0, max_value=100.0, step=1.0,
                           format="%.1f", key="p7_reach",
                           help="Share of entrants who reach the changed experience or the target segment; the test "
                                "is analysed on them (for example, the installs who get to level 30). Entrants "
                                "needed = users needed ÷ this share.")
r2 = st.columns(4, gap="medium", vertical_alignment="bottom")
alpha = r2[0].select_slider("Significance level (alpha)", options=[0.01, 0.05, 0.10], value=C.ALPHA,
                            format_func=lambda a: f"{a:g}", key="p7_alpha",
                            help="Chance of a false positive we accept when there is no real effect.")
power = r2[1].select_slider("Power", options=[0.70, 0.80, 0.90, 0.95], value=C.POWER,
                            format_func=lambda p: f"{p:.0%}", key="p7_power",
                            help="Chance of detecting the change if it is really there at the MDE size.")
daily = r2[2].number_input("Entrants per day", min_value=100, max_value=10_000_000, value=20_000, step=1_000,
                           key="p7_daily",
                           help="Illustrative default: the datasets have no dates, so traffic is unknown. Enter the "
                                "number of users per day who could enter the test.")

p_c = baseline / 100
eff = change / 100
p_t = p_c + eff
if abs(change) < 1e-4:
    st.warning("Enter a non-zero change to detect.")
elif not 0 < p_t < 1:
    st.warning("Baseline + change must stay between 0% and 100%. Change the baseline or the change.")
else:
    rel = eff / p_c

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
                       "rounded up. For a change only some entrants reach (a level-30 gate, a target segment), "
                       "these are the users who reach it.")
    out[1].metric("Entrants needed", f"{sel['entrants']:,}", f"{reach:.3g}% reach the change", delta_color="off",
                  delta_arrow="off", help="Users who must enter the test so that enough of them reach the change: "
                                          "total users needed ÷ the share who reach it.")
    out[2].metric(f"Days at {daily:,} entrants/day", f"{sel['days']:,}",
                  f"plan {max(MIN_WEEKS, math.ceil(sel['days'] / 7))} full weeks", delta_color="off",
                  delta_arrow="off",
                  help=f"Entrants needed ÷ entrants per day, rounded up. The plan rounds up to whole weeks, with "
                       f"a minimum of {MIN_WEEKS} (see the note below the table).")
    out[3].metric("Change to detect", f"{sgn(change)} pp",
                  f"{baseline:.2f}% → {p_t * 100:.2f}% ({sgn(rel * 100, 0)}%)",
                  delta_color="off", delta_arrow="off",
                  help=f"Baseline + change, in percentage points: {baseline:.2f}% to {p_t * 100:.2f}%. In brackets, "
                       f"the relative change (change ÷ baseline): {sgn(rel * 100, 1)}%.")

    splits = sorted({0.5, 0.8, 0.9, plan, share / 100})
    base_5050 = size(0.5)["total"]
    rows = []
    for s in splits:
        z = size(s)
        label = f"{s * 100:.0f}/{(1 - s) * 100:.0f}" + (" (selected)" if math.isclose(s, share / 100) else "")
        rows.append({"Split": label, "Users": z["total"], "vs 50/50": z["total"] / base_5050,
                     "Days": z["days"], "Cost if real": z["cost"]})
    scen = pd.DataFrame(rows)
    gain = eff > 0
    chart_col, table_col = st.columns(2, gap="large")
    with chart_col:
        # Power for a drop of x from p_c equals power for a rise of x from 1 - p_c (Cohen's h is symmetric).
        p_plot = p_c if gain else 1 - p_c
        max_pp = max(min(abs(eff) * 100 * 2.5, (0.999 - p_plot) * 100), 0.1)
        fig = F.fig_power_curve(
            p_plot, sel["n_t"], sel["n_c"], alpha, abs(eff), "Power of the planned test by true change (%)",
            f"{sel['n_t']:,} treatment and {sel['n_c']:,} control users, alpha {alpha:g}.",
            max_lift_pp=max_pp, target_power=power, reference_label="change to detect")
        word = "rise" if gain else "drop"
        fig.update_xaxes(title_text=f"True {word} in the metric (pp)")
        fig.update_traces(hovertemplate=f"True {word} %{{x:.2f}} pp<br>Power %{{y:.0f}}%<extra></extra>",
                          selector=dict(name="Power"))
        show(fig)
    with table_col:
        st.markdown("**The same test with other splits**")
        st.dataframe(scen, hide_index=True, width="stretch", column_config={
            # widths sum to ~350 px so the table fits a phone screen without sideways scrolling
            "Split": st.column_config.TextColumn("Split", width=112, help="Share of users in treatment / control."),
            "Users": st.column_config.NumberColumn(format="localized", width=75,
                                                   help="Total users needed at this split."),
            "vs 50/50": st.column_config.NumberColumn(format="%.1fx", width=62,
                                                      help="Total sample relative to an even split."),
            "Days": st.column_config.NumberColumn("Days", format="localized", width=46,
                                                  help="Days to reach the sample at the traffic entered above."),
            "Cost if real": st.column_config.NumberColumn(
                "Cost", format="localized", width=55,
                help="If the true change equals the one entered: for a gain, the conversions (or retained players) "
                     "the control group misses during the test (control users × change); for a drop, those the "
                     "treatment group loses (treatment users × change)."),
        })
        st.caption("Cost: what the test itself gives up if the change is real. For a gain the control group "
                   "pays it, for a drop the treatment group does. Uneven splits move that cost around but need far "
                   "more users in total.")
    n_now = size(plan)["total"]
    text = (f"To detect a {sgn(change)} pp change on a {baseline:.2f}% baseline ({sgn(rel * 100, 0)}% relative) with "
            f"{power:.0%} power at alpha {alpha:g}, a {share}/{100 - share} split needs {sel['total']:,} users "
            f"({sel['n_t']:,} treatment / {sel['n_c']:,} control)")
    if reach < 100:
        text += f", i.e. {sel['entrants']:,} entrants when {reach:.3g}% of them reach the change"
    text += (f": about {sel['days']:,} days at {daily:,} entrants a day. The power curve crosses {power:.0%} at that "
             "change; smaller true changes would often be missed.")
    if preset == AD_PRESET and not math.isclose(share / 100, plan):
        text += (f" The same test at {split_now}, the ad test's design, needs {n_now:,} users "
                 f"({n_now / base_5050:.1f}× the 50/50 sample).")
    takeaway(text)
    if preset == R6_PRESET:
        st.caption(f"Onboarding test (R6): +{r6['target_lift_abs'] * 100:.1f} pp D7 (a placeholder target in "
                   f"config.yaml) on the {early['retention_7'] * 100:.2f}% D7 of players with < 15 rounds, who are "
                   f"{early['share_of_installs'] * 100:.1f}% of installs; results.json: "
                   f"{r6['players_needed_5050']:,} target players ≈ {r6['installs_needed_5050']:,} installs at "
                   "50/50. The real test must pick its targets from first-day play, not the 14-day round count.")
    elif preset == GATE_PRESET:
        # The same smallest change, analysed per install over everyone (baseline: gate_30's D7 over all installs).
        n_all = S.required_total_n(retest["baseline_d7_install"], eff * reach / 100, share / 100, alpha, power)
        st.caption(f"Gate re-test (R5): sized at a change fixed in advance, "
                   f"{retest['smallest_d7_change_per_install'] * 100:.1f} pp D7 per install (a placeholder to agree "
                   "with the Game PM), never at the observed gap. Primary "
                   f"analysis among players who reach level 30 (membership is pre-gate); analysed over all installs "
                   f"instead (a {sgn(eff * reach)} pp change on gate_30's {retest['baseline_d7_install'] * 100:.2f}% "
                   f"D7), the same test needs {n_all:,} installs at a {share}/{100 - share} split. At 50/50 the preset "
                   f"is sized to detect a {retest['smallest_d7_change_per_install'] * 100:.1f} pp drop; a rise of the "
                   f"same size needs up to ≈{rise_extra * 100:.0f}% more "
                   f"(≈{k(retest['installs_needed_install_level_5050_if_rise'])} installs analysed over all installs, "
                   f"≈{retest['installs_needed_reacher_analysis_5050_if_rise'] / 1e3:,.1f}K with the analysis among "
                   f"players who reach level 30). The reacher figure uses this cohort's "
                   f"{retest['share_reached_30'] * 100:.1f}% reaching level 30; re-check with the new cohort's share "
                   "before launch. Run it only after Engineering has found and fixed the cause of the imbalance, "
                   "with a daily 50/50 group-size check.")
    caveat(f"Plan in whole weeks, at least {MIN_WEEKS}, even if the sample is reached sooner: weekly habits matter "
           f"(in the ad test, users with different peak days responded differently, interaction "
           f"{p_text(h_day['lrt']['p_value'])}) and, without timestamps, this data cannot show whether an effect fades "
           "after a novelty period. Decide the sample size before launch and do not stop early on a good-looking "
           "p-value.")

# ------------------------------------------------------------------ risks + data asks
st.subheader("Risks, limitations and what I would ask for next")
risk_col, ask_col = st.columns(2, gap="large")
with risk_col:
    st.markdown("**Risks and limitations**")
    st.markdown(f"""
- **No revenue or cost.** USD figures rest on an assumed USD {value:,.0f} per conversion and on a CPM we do not
  have; the headline business number is incremental conversions.
- **No timestamps.** We cannot check novelty effects, how long the lift lasts, or when users were assigned.
- **Most likely a quota.** {ad['srm']['n_t']:,} is the nearest whole number to {plan * 100:.0f}% of
  {n_users:,} users ({ad['srm']['deviation_users']:.2f} users off, against a chance gap of about
  {ad['srm']['sd_users_under_random_assignment']:,.0f}). Fixed arm sizes are a valid design, but the ad test's SRM
  check then passes by construction. Exposure parity ({ad['groups']['ad']['mean_ads']:.1f} vs
  {ad['groups']['psa']['mean_ads']:.1f} ads per user) is the meaningful check; the shapes differ a little (KS
  distance {ad['total_ads_ks']['stat']:.3f}).
- **Post-assignment segments.** Day, hour and exposure are recorded after assignment, so segment results are
  exploratory and never used as covariates. As a sensitivity check, lift standardized over these strata is
  {min(std_lifts):.2f} to {max(std_lifts):.2f} pp vs {t['abs_lift'] * 100:.2f} pp crude: no reversal.
- **Multiple comparisons.** One interaction test per dimension ({het['n_dimensions_explored']} explored: day, hour,
  exposure), then segment-vs-rest contrasts with Holm correction. Bonferroni (p × 3) covers those original interaction
  tests. Daypart and Night-exclusion are later descriptive diagnostics and are not covered by this adjustment. Per-segment "lift ≠ 0"
  tests measure power, not heterogeneity, so they are not used as evidence.
- **Gate experiment.** SRM WARNING on raw assignment counts ({p_text(gsrm['p_value'])}). The net excess sits among
  players with fewer than 15 rounds ({sgn(net_lt15, 0)}, {p_text(sbs['rounds_lt_15']['p_value'])}, a subset chosen
  after seeing the warning). Players who never met a gate show D7 {abs(nc7['abs_lift']) * 100:.2f} pp lower in
  gate_40 ({p_text(nc7['p_value'])}, borderline on its own). The result is not certified.
- **Retention data.** One install cohort (no install dates); D1 / D7 mean "played on day 1 / day 7"; rounds are
  counted over 14 days and overlap the D7 window, so rounds vs retention is partly definitional; there is no level
  field, so "30+ rounds" stands in for "could have reached level 30".
- **Two products.** The ads ran in one of the company's apps; the retention data comes from its mobile game, Cookie
  Cats (2017 install cohort). They share no users, so we cannot link ad conversions to later retention, and segment
  sizes will not transfer one-for-one.
""")
with ask_col:
    st.markdown("**Data I would ask for next**")
    st.markdown(f"""
- **Assignment logs with timestamps and the documented split** (Engineering): a real SRM check, novelty and
  duration analysis, and where gate_40's ≈{excess} extra installs came from.
- **Actual CPM / spend by day** (media buying) and **value per conversion** (Finance): real ROI instead of a
  breakeven against an assumed value.
- **Impression-level logs** (time and frequency per user): to design the frequency-cap arms in R2.
- **Guardrail metrics** (unsubscribes, complaints, uninstalls, CPA): to pre-register them in R4.
- **For the game:** install date, platform / country, first-session rounds (not 14-day totals) and level reached:
  to target R6 on first-day play and to define "reached level 30" exactly in a gate re-test.
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
acting on (in percentage points; negative for a drop), how users are split, how many entrants actually reach the
change, and how strict the test should be (alpha, power). It returns how many users the test needs and how long that
takes at your traffic. The presets reproduce the numbers in this analysis: the ad test ({n10['0.5']:,} users at
50/50 for a {sesoi * 100:.0f}% lift), the onboarding test in R6 ({r6['players_needed_5050']:,} target players, i.e.
{r6['installs_needed_5050']:,} installs) and the gate re-test in R5 ({retest['reachers_needed_5050']:,} players who
reach level 30, i.e. {retest['installs_needed_reacher_analysis_5050']:,} installs;
{retest['installs_needed_install_level_5050']:,} if analysed over all installs). The table compares splits: an uneven
split like {split_now} shows the new experience to more users but needs far more users in total, because the small
group is measured imprecisely.

**Words used.**
- **MDE (minimum detectable effect):** the smallest true effect the test would detect most of the time (as often as
  the power says). It is a property of the design, not the effect we expect, and it is never compared with an
  observed estimate.
- **Alpha:** the false-alarm rate we accept ({C.ALPHA:.0%} in this project).
- **Power:** the chance of catching a real effect of MDE size ({C.POWER:.0%} in this project). It describes the
  design; it is never computed at the observed effect.
- **Holdout:** a share of users kept on the PSA so the campaign's incremental effect can be measured every flight.

**Common misreadings.**
- "The calculator gives a number of days, so we can stop earlier if it already looks good." Decide the length
  first and do not peek-and-stop; stopping on a good-looking day inflates false positives.
- "A smaller MDE is always better." It needs more users and time; pick the smallest change that would change the
  decision.
- "Size the gate re-test at the gap we saw." A re-test is sized at a change fixed in advance
  ({retest['smallest_d7_change_per_install'] * 100:.1f} pp D7 per install here), never at an observed effect.
- Reading the naive {sgn_pp(dec['naive_diff'])} D7 gap as the effect of the gate. It is the gap between unbalanced
  arms; the part the gate could explain is about {sgn(gate_eff * 100, 1)} pp per install and may be zero.
- The USD numbers in R1 assume a value per conversion; the incremental conversions do not.
""")
