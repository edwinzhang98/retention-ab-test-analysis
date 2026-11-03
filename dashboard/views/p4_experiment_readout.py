"""Page 4 · Experiment readout: ad vs PSA (Marketing A/B).

Laid out like a standard experiment readout: hypothesis and design -> metrics
-> result -> power -> business value -> risks -> decision.

Headline numbers are read from reports/results.json. The controls recompute
intervals, power, breakeven and the holdout cost from the same counts with
src/stats.py; the bootstrap interval reuses the cached draws (boot_ad_lift)
and only re-takes percentiles when alpha changes. Power is always evaluated at
the smallest lift worth acting on (a design property), never at the observed
effect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from common import (F, S, caveat, fmt_pct, fmt_pp, how_to_read, load_cache, load_catalog_takeaways,
                    load_results, page_header, show, takeaway)

RES = load_results()
AD = RES["ad"]
T = AD["test"]
CFG = RES["config"]
PW = AD["power"]
BZ = AD["business"]
INC = BZ["incremental_conversions"]
HOLD = BZ["always_on_holdout_cost"]
SRM = AD["srm"]
IMPRESSIONS = int(BZ["impressions_ad_group"])
CAT = load_catalog_takeaways()
BOOT = load_cache("boot_ad_lift")

ALPHA0 = float(CFG["alpha"])
POWER0 = float(CFG["power"])
SHARE0 = float(CFG["intended_ad_share"])
VALUE0 = float(CFG["value_per_conversion_usd"])
SESOI0 = float(PW["smallest_lift_of_interest_rel"])   # smallest relative lift worth acting on
HOLDOUT0 = float(HOLD["share"])
N_TOTAL = int(T["n_t"] + T["n_c"])
N_BOOT = len(BOOT)
# exact rates from counts (results.json rounds rates to 6 decimals)
P_T = T["conv_t"] / T["n_t"]
P_C = T["conv_c"] / T["n_c"]
SPLIT0 = f"{SHARE0 * 100:.0f}/{(1 - SHARE0) * 100:.0f}"

ALPHAS = [0.10, 0.05, 0.01, 0.001]
ALPHA_LABELS = {0.10: "0.10", 0.05: "0.05", 0.01: "0.01", 0.001: "0.001"}
METHODS = {"newcombe": "Newcombe (score)", "wald": "Wald", "bootstrap": "Bootstrap percentile"}
PW_ALPHAS = [0.10, 0.05, 0.01]
POWERS = [0.70, 0.80, 0.90, 0.95]
SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


# ------------------------------------------------------------------ helpers
def conf(alpha: float) -> str:
    """Confidence level for an alpha: 0.05 -> '95%'."""
    return f"{(1 - alpha) * 100:g}%"


def pp_range(lo: float, hi: float) -> str:
    return f"{lo * 100:+.2f} to {hi * 100:+.2f} pp".replace("-", "−")


def ci_short(lo: float, hi: float) -> str:
    """Interval in pp without the unit, for the small metric notes (true minus sign)."""
    return f"{lo * 100:+.2f} to {hi * 100:+.2f}".replace("-", "−")


def approx(x: float) -> str:
    """A rough count for prose, two significant figures: 1,008 -> '1,000'."""
    return f"{float(f'{x:.2g}'):,.0f}"


def p_text(p: float) -> str:
    """Headline p-value: never prints 0."""
    if p < 1e-4:
        return "< 0.0001"
    return f"{p:.4f}" if (p < 1e-3 or p > 0.99) else f"{p:.2g}"


def sci(x: float) -> str:
    """1.71e-13 -> '1.7 × 10⁻¹³' (technical text only; headline text says p < 0.0001)."""
    mant, exp = f"{x:.1e}".split("e")
    return f"{mant} × 10{str(int(exp)).translate(SUPERSCRIPT)}"


def usd(x: float, nd: int = 2) -> str:
    """Money as 'USD 15.49': a bare dollar sign starts LaTeX in Streamlit markdown."""
    return f"USD {x:,.{nd}f}"


def usd_input(x: float) -> str:
    """An entered amount: 'USD 50' for whole numbers, 'USD 52.50' otherwise."""
    return usd(x, 0 if float(x).is_integer() else 2)


def usd_k(x: float, nd: int = 0) -> str:
    return f"USD {x / 1e3:,.{nd}f}K"


def fmt_power(p: float) -> str:
    return "≈100%" if p >= 0.995 else f"{p:.0%}"


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    """st.metric with a neutral grey note instead of a red/green delta arrow."""
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


@st.cache_data(show_spinner=False)
def lift_intervals(alpha: float) -> pd.DataFrame:
    """CI of the absolute lift by method, with the matching relative-lift CI
    (log risk ratio for the analytic methods, percentiles for the bootstrap)."""
    counts = (T["conv_t"], T["n_t"], T["conv_c"], T["n_c"])
    res = S.two_prop_test(*counts, alpha=alpha)
    wald = S.wald_diff_ci(*counts, alpha=alpha)
    boot = load_cache("boot_ad_lift")
    b_abs = S.percentile_ci(boot["abs_lift"], alpha)
    b_rel = S.percentile_ci(boot["rel_lift"], alpha)
    return pd.DataFrame(
        {"abs_low": [res.abs_ci_low, wald[0], b_abs[0]], "abs_high": [res.abs_ci_high, wald[1], b_abs[1]],
         "rel_low": [res.rel_ci_low, res.rel_ci_low, b_rel[0]],
         "rel_high": [res.rel_ci_high, res.rel_ci_high, b_rel[1]]},
        index=list(METHODS))


def design(share: float) -> tuple[int, int]:
    """(ad users, PSA users) for a split of the same total. The as-run split uses the real
    arm sizes and 50/50 halves the total, as in results.json."""
    if abs(share - SHARE0) < 1e-9:
        return int(T["n_t"]), int(T["n_c"])
    if abs(share - 0.5) < 1e-9:
        return N_TOTAL // 2, N_TOTAL // 2
    n_t = int(round(N_TOTAL * share))
    return n_t, N_TOTAL - n_t


def split_label(share: float) -> str:
    return f"{share * 100:.0f}/{(1 - share) * 100:.0f}"


@st.cache_data(show_spinner=False)
def design_numbers(share: float, alpha: float, power: float, rel: float) -> dict:
    """MDE, power at the smallest lift worth acting on, and users needed for it, for one split."""
    n_t, n_c = design(share)
    sesoi = rel * P_C
    return {"n_t": n_t, "n_c": n_c,
            "mde": S.mde(P_C, n_t, n_c, alpha, power)["mde_abs"],
            "power_at_sesoi": S.power_at_lift(P_C, P_C + sesoi, n_t, n_c, alpha),
            "users_needed": S.required_total_n(P_C, sesoi, share, alpha, power)}


@st.cache_data(show_spinner=False)
def mde_figure(share: float, alpha: float, power: float, sesoi: float):
    fig = F.fig_mde_by_split(P_C, N_TOTAL, share, sesoi, alpha, power,
                             "Minimum detectable lift vs. share of users in treatment (pp)")
    if abs(share - 0.5) < 1e-9:   # the selected split is the 50/50 reference: keep one label, not two
        fig.update_traces(mode="markers", selector=dict(name="Selected split"))
    return fig


@st.cache_data(show_spinner=False)
def power_figure(n_t: int, n_c: int, alpha: float, power: float, sesoi: float, title: str, max_lift_pp: float):
    return F.fig_power_curve(P_C, n_t, n_c, alpha, sesoi, title, target_power=power, max_lift_pp=max_lift_pp)


def payback_verdict(cpm: float, be: dict) -> tuple[str, str, str]:
    """(label, badge colour, reason) comparing the CPM paid with the breakeven CPM interval."""
    if cpm < be["ci_low"]:
        return ("Pays back", "green",
                "even at the low end of the lift's 95% CI, the incremental value covers the media cost")
    if cpm <= be["ci_high"]:
        return ("Too close to call", "orange",
                "the CPM sits inside the breakeven range, so the answer depends on where the true lift lies")
    return ("Does not pay back", "red",
            "even at the high end of the lift's 95% CI, the incremental value does not cover the media cost")


# ------------------------------------------------------------------ page
page_header("Experiment Readout: Ad vs PSA",
            "Did ads increase conversion, by how much, and is it worth the money?")

share_inc = BZ["share_of_ad_conversions_incremental"]
share_inc_ci = BZ["share_of_ad_conversions_incremental_ci"]
overstate = BZ["last_touch_overstatement_x"]
over_ci = BZ["last_touch_overstatement_ci"]
over_txt = f"{overstate:.1f}× (95% CI {over_ci[0]:.1f}–{over_ci[1]:.1f}×)"
# the smallest lift worth acting on, in conversions per ad flight (as-run ad arm) and USD at the assumed value
SESOI_CONV0 = SESOI0 * P_C * T["n_t"]
with st.container(border=True):
    st.markdown(
        f"**Readout in one line.** Ads lifted conversion from {fmt_pct(T['rate_c'])} (PSA) to "
        f"{fmt_pct(T['rate_t'])}: {fmt_pp(T['abs_lift'])} (95% CI {pp_range(T['abs_ci_low'], T['abs_ci_high'])}), "
        f"{T['rel_lift']:+.0%} relative, ≈{INC['point']:,.0f} incremental conversions. That is only "
        f"{share_inc:.0%} of the ad arm's conversions, so last-touch (any-touch) attribution, which would credit "
        f"every ad-group conversion to the ads, would overstate the campaign {over_txt}. **Keep the campaign with "
        f"an always-on {HOLDOUT0:.0%} holdout; test a bigger budget before doubling it.**")

# ---------------------------------------------------------------- 1. hypothesis & design
st.subheader("1 · Hypothesis and design")
h1, h2 = st.columns(2)
with h1.container(border=True, height="stretch"):
    st.markdown(
        "**Hypothesis**  \n"
        "Showing the campaign's ads, instead of a public-service announcement (PSA) in the same placements, "
        "increases the share of users who convert.\n\n"
        "- H₀: conversion rate (ad) = conversion rate (PSA)\n"
        f"- H₁: the rates differ (two-sided test, α = {ALPHA0:g})\n"
        "- Decision rule: keep the campaign if the 95% CI for the lift excludes 0 **and** the trust checks "
        "(sample ratio, exposure parity) raise no red flag. Whether it pays back is a separate cost question "
        "(section 5).")
with h2.container(border=True, height="stretch"):
    st.markdown(
        "**Design and sample**\n\n"
        f"- Randomization unit: user. {N_TOTAL:,} users, {T['n_t'] / N_TOTAL:.0%} ad ({T['n_t']:,}) / "
        f"{T['n_c'] / N_TOTAL:.0%} PSA ({T['n_c']:,}).\n"
        "- Control is a placebo: PSA users saw a public-service ad in the same slots, so the lift isolates "
        "the campaign's message rather than the act of showing an ad.\n"
        "- One row per user: converted (yes/no), total ads seen, peak ad day and peak ad hour. "
        "No timestamps, no cost, no revenue.\n"
        "- Analysis population: every user in the file (each saw at least one ad or PSA), "
        "counted in the arm they were assigned to.")

# ---------------------------------------------------------------- 2. metrics
st.subheader("2 · Metrics")
g_ad, g_psa = AD["groups"]["ad"], AD["groups"]["psa"]
ks_d = AD["total_ads_ks"]["stat"]
st.markdown(
    "| Role | Metric | Definition | Result |\n"
    "|---|---|---|---|\n"
    f"| **Primary** | Conversion rate | Users with `converted` = True ÷ users assigned to the arm "
    f"| Ad {fmt_pct(T['rate_t'])} vs PSA {fmt_pct(T['rate_c'])} |\n"
    f"| Secondary | Relative lift | Ad rate ÷ PSA rate − 1 "
    f"| {T['rel_lift']:+.0%} (95% CI {T['rel_ci_low']:+.0%} to {T['rel_ci_high']:+.0%}) |\n"
    f"| Secondary | Incremental conversions | Absolute lift × users in the ad arm "
    f"| ≈{INC['point']:,.0f} (95% CI {INC['ci_low']:,.0f} to {INC['ci_high']:,.0f}) |\n"
    f"| Secondary | Share of ad-arm conversions caused by the ads | Incremental ÷ ad-arm conversions (= 1 − 1/RR) "
    f"| {share_inc:.0%} (95% CI {share_inc_ci[0]:.0%} to {share_inc_ci[1]:.0%}) |\n"
    f"| Trust check | Sample ratio (SRM) | Observed vs intended {SPLIT0} split, chi-square test "
    f"| p = {p_text(SRM['p_value'])}, but uninformative: the ad arm is the nearest whole number to exactly "
    f"{SHARE0:.0%}, most likely a fixed quota (a valid design), so the test cannot fail (see risks) |\n"
    f"| Trust check | Exposure parity | Ads seen per user, ad vs PSA: mean and distribution "
    f"| Means {g_ad['mean_ads']:.1f} vs {g_psa['mean_ads']:.1f}; shapes differ a little (KS D = {ks_d:.3f}): "
    "exposure is an exploratory cut, never a covariate |\n"
    "| Guardrails we lack | Unsubscribe / hide-ad rate, complaint rate, cost per acquisition (CPA) "
    "| Not in this dataset | Cannot be checked here; pre-register them in the next test (R4) |")

# ---------------------------------------------------------------- 3. result
st.subheader("3 · Result")
c1, c2 = st.columns([1.15, 1])
alpha = c1.radio("Significance level α (confidence level = 1 − α)", ALPHAS,
                 index=ALPHAS.index(ALPHA0) if ALPHA0 in ALPHAS else 1,
                 format_func=ALPHA_LABELS.get, horizontal=True, key="p4_alpha",
                 help="Lower α = stricter test = wider interval. 0.05 gives a 95% CI, 0.001 a 99.9% CI.")
method = c2.radio("Confidence-interval method", list(METHODS), format_func=METHODS.get, horizontal=True,
                  key="p4_ci_method",
                  help="Newcombe is the default in this project; Wald is the textbook formula; the bootstrap "
                       f"re-uses {N_BOOT:,} cached resamples.")

cis = lift_intervals(alpha)
sel = cis.loc[method]
test = S.two_prop_test(T["conv_t"], T["n_t"], T["conv_c"], T["n_c"], alpha=alpha)
n_le0 = int((BOOT["abs_lift"] <= 0).sum())
excludes_0 = bool(sel["abs_low"] > 0 or sel["abs_high"] < 0)

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Ad conversion rate", fmt_pct(test.rate_t), f"PSA: {fmt_pct(test.rate_c)}",
    help=f"Ad: {T['conv_t']:,} of {T['n_t']:,} users converted. PSA: {T['conv_c']:,} of {T['n_c']:,}.")
kpi(k2, "Absolute lift", fmt_pp(test.abs_lift),
    f"{conf(alpha)} CI {ci_short(sel['abs_low'], sel['abs_high'])}",
    help=f"Ad rate − PSA rate, in percentage points. Interval method: {METHODS[method]}.")
kpi(k3, "Relative lift", f"{test.rel_lift:+.0%}",
    f"{conf(alpha)} CI {sel['rel_low']:+.0%} to {sel['rel_high']:+.0%}",
    help="Analytic methods use a log-risk-ratio interval; the bootstrap uses percentiles of the resampled ratio.")
kpi(k4, "p-value (z-test)", p_text(test.p_value), f"{n_le0:,} of {N_BOOT:,} resamples ≤ 0",
    help=f"Two-sided pooled two-proportion z-test: p = {sci(test.p_value)}. The note counts bootstrap "
         "resamples with a lift at or below zero.")

g1, g2 = st.columns(2, gap="medium")
with g1:
    arms = F.arm_table(T["conv_t"], T["n_t"], T["conv_c"], T["n_c"], alpha=alpha)
    show(F.fig_arm_rates(arms, f"Conversion rate by experiment arm (%, {conf(alpha)} CI)"), key="p4_arm_rates")
    if alpha == ALPHA0 and method == "newcombe":
        takeaway(CAT["ad_rates"])
    else:
        spread = float(max(cis["abs_low"].max() - cis["abs_low"].min(), cis["abs_high"].max() - cis["abs_high"].min()))
        verdict = ("it excludes 0, so the lift is not explained by chance at this level" if excludes_0
                   else "it includes 0, so at this level we cannot rule out no effect")
        takeaway(f"At {conf(alpha)} confidence the {METHODS[method]} interval for the lift is "
                 f"{pp_range(sel['abs_low'], sel['abs_high'])}: {verdict}. The three interval methods agree "
                 f"within {spread * 100:.2f} pp.")
with g2:
    view = pd.DataFrame({
        "Interval method": [METHODS[m] + (" ←" if m == method else "") for m in cis.index],
        "Lower (pp)": cis["abs_low"].to_numpy() * 100,
        "Upper (pp)": cis["abs_high"].to_numpy() * 100,
        "Excludes 0": np.where((cis["abs_low"] > 0) | (cis["abs_high"] < 0), "Yes", "No"),
    })
    st.markdown(f"**All three interval methods at {conf(alpha)} confidence**")
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.3f") for c in ("Lower (pp)", "Upper (pp)")})
    widths = (cis["abs_high"] - cis["abs_low"]) * 100
    st.caption(f"← marks the method used in the cards above. Widths: {widths.min():.3f} to {widths.max():.3f} pp. "
               "Newcombe (score) is the project default because it behaves well for small rates; the bootstrap "
               f"re-uses {N_BOOT:,} cached resamples.")

b_ci = (float(cis.loc["bootstrap", "abs_low"]), float(cis.loc["bootstrap", "abs_high"]))
show(F.fig_bootstrap(BOOT["abs_lift"].to_numpy(), b_ci, T["abs_lift"],
                     f"Bootstrap distribution of the ad lift (pp, {N_BOOT:,} resamples)", alpha=alpha),
     key="p4_bootstrap")
if alpha == ALPHA0:
    takeaway(CAT["ad_bootstrap"])
else:
    tail = alpha / 2 * N_BOOT
    note = (f" Each tail now rests on only {tail:g} draws, so treat the bootstrap bounds as approximate."
            if tail < 50 else "")
    takeaway(f"The middle {conf(alpha)} of the {N_BOOT:,} resampled lifts runs from {b_ci[0] * 100:.2f} to "
             f"{b_ci[1] * 100:.2f} pp, and {n_le0:,} resamples show a lift ≤ 0.{note}")

# ---------------------------------------------------------------- 4. power
st.subheader("4 · Power: what could this test detect?")
st.caption("Power is a property of the design: the chance of detecting a true lift of a given size. It is judged "
           "at the smallest lift worth acting on, never at the lift we happened to observe. That smallest lift "
           f"({SESOI0:.0%} relative, {SESOI0 * P_C * 100:.2f} pp) is a placeholder assumption in config.yaml; in "
           "practice the PM and Finance agree it before launch. It is "
           f"≈{approx(SESOI_CONV0)} conversions per {T['n_t'] / 1e3:,.0f}K-user ad flight, "
           f"≈{usd_k(SESOI_CONV0 * VALUE0)} at the assumed {usd(VALUE0, 0)} per conversion.")
q1, q2, q3, q4 = st.columns([1.4, 1, 1.1, 1.2])
share = q1.slider("Share of users in treatment (ad)", 50, 99, int(round(SHARE0 * 100)), step=1, format="%d%%",
                  key="p4_share", help=f"This test ran at {SHARE0:.0%}. Same total users, different split.") / 100
pw_alpha = q2.radio("α", PW_ALPHAS, index=PW_ALPHAS.index(ALPHA0) if ALPHA0 in PW_ALPHAS else 1,
                    format_func=lambda a: f"{a:.2f}", horizontal=True, key="p4_pw_alpha")
power = q3.select_slider("Power (1 − β)", POWERS, value=POWER0 if POWER0 in POWERS else 0.80,
                         format_func=lambda x: f"{x:.0%}", key="p4_power")
rel = q4.number_input("Smallest lift worth acting on (relative %)", min_value=1.0, max_value=100.0,
                      value=SESOI0 * 100, step=1.0, format="%.0f", key="p4_rel_target",
                      help=f"Project default {SESOI0:.0%}: a placeholder assumption in config.yaml, which in "
                           "practice the PM and Finance agree before launch. Marked on both charts and used for "
                           "power and sample size.") / 100

sesoi = rel * P_C
split = split_label(share)
# compare with 50/50, or with the as-run split when 50/50 is the one selected (no duplicate cards)
cmp_share = SHARE0 if abs(share - 0.5) < 1e-9 else 0.5
cmp_label = f"{SPLIT0} as run" if cmp_share == SHARE0 else "50/50"
sel_d = design_numbers(share, pw_alpha, power, rel)
cmp_d = design_numbers(cmp_share, pw_alpha, power, rel)
n_t, n_c = sel_d["n_t"], sel_d["n_c"]
same_users = f"The comparison note uses the same {N_TOTAL:,} users split {split_label(cmp_share)}."

m1, m2, m3, m4 = st.columns(4)
sesoi_conv = sesoi * T["n_t"]
kpi(m1, "Lift worth acting on", f"{sesoi * 100:.2f} pp", f"{rel:.0%} × PSA rate {fmt_pct(P_C)}",
    help=f"The smallest lift that would change the decision ({rel:.0%} relative to the PSA conversion rate). The "
         f"project default ({SESOI0:.0%}) is a placeholder assumption in config.yaml; in practice the PM and Finance "
         f"agree it before launch. {rel:.0%} is ≈{approx(sesoi_conv)} conversions per {T['n_t'] / 1e3:,.0f}K-user "
         f"ad flight, ≈{usd_k(sesoi_conv * VALUE0)} at the assumed {usd(VALUE0, 0)} per conversion.")
kpi(m2, f"MDE at {split}", f"{sel_d['mde'] * 100:.2f} pp", f"{cmp_label}: {cmp_d['mde'] * 100:.2f} pp",
    help=f"Minimum detectable effect: the smallest true lift caught {power:.0%} of the time at α = {pw_alpha:.2f}, "
         f"with {n_t:,} ad and {n_c:,} PSA users. {same_users}")
kpi(m3, f"Power at {split}", fmt_power(sel_d["power_at_sesoi"]),
    f"{cmp_label}: {fmt_power(cmp_d['power_at_sesoi'])}",
    help=f"Chance of detecting a true lift of {sesoi * 100:.2f} pp (the lift worth acting on, {rel:.0%} relative) "
         f"at α = {pw_alpha:.2f}. {same_users}")
kpi(m4, f"Users needed at {split}", f"{sel_d['users_needed']:,}", f"{cmp_label}: {cmp_d['users_needed']:,}",
    help=f"Total users for {power:.0%} power to detect the lift worth acting on ({rel:.0%} relative) at "
         f"α = {pw_alpha:.2f}.")

is_default_power = (abs(share - SHARE0) < 1e-9 and pw_alpha == ALPHA0 and power == POWER0
                    and abs(rel - SESOI0) < 1e-9)
reach = ("within what this split can reliably detect" if sesoi >= sel_d["mde"]
         else "below what this split can reliably detect")
cmp_long = f"the {SPLIT0} split as run" if cmp_share == SHARE0 else "a 50/50 split of the same users"
show(mde_figure(share, pw_alpha, power, sesoi), key="p4_mde")
if is_default_power:
    takeaway(CAT["ad_mde_split"])
else:
    takeaway(f"At a {split} split these {N_TOTAL:,} users detect lifts of {sel_d['mde'] * 100:.2f} pp or more "
             f"with {power:.0%} power at α = {pw_alpha:.2f}; {cmp_long} gets to {cmp_d['mde'] * 100:.2f} pp. "
             f"The smallest lift worth acting on ({rel:.0%} relative = {sesoi * 100:.2f} pp) is {reach}.")
max_lift = max(0.6, 1.5 * sel_d["mde"] * 100, 1.25 * sesoi * 100)
title = ("Power to detect a true lift, current sample (%)" if abs(share - SHARE0) < 1e-9
         else f"Power to detect a true lift at a {split} split of the same users (%)")
show(power_figure(n_t, n_c, pw_alpha, power, sesoi, title, max_lift), key="p4_power_curve")
if is_default_power:
    takeaway(CAT["ad_power_curve"])
else:
    takeaway(f"With {n_t:,} ad and {n_c:,} PSA users, power for the smallest lift worth acting on "
             f"({sesoi * 100:.2f} pp) is {fmt_power(sel_d['power_at_sesoi'])} ({cmp_long}: "
             f"{fmt_power(cmp_d['power_at_sesoi'])}); {power:.0%} power needs a true lift of at least "
             f"{sel_d['mde'] * 100:.2f} pp. Power describes the design; it is not evaluated at the observed effect.")
need = {s: S.required_total_n(P_C, sesoi, s, pw_alpha, power) for s in (0.5, 0.8, SHARE0)}
st.caption(f"Sizing the next test: {power:.0%} power for a {rel:.0%} relative lift ({sesoi * 100:.2f} pp) at "
           f"α = {pw_alpha:.2f} needs {need[0.5]:,} users at 50/50, {need[0.8]:,} at 80/20 and {need[SHARE0]:,} at "
           f"{SPLIT0}. A small control group is paid for with a lot of extra traffic. The sample-size calculator on "
           "page 7 turns this into days of traffic.")

# ---------------------------------------------------------------- 5. business
st.subheader("5 · Is it worth the money?")
st.caption("The data has no revenue or cost fields: value per conversion is an explicit assumption and the CPM "
           "must come from Finance. Incremental conversions are the number to quote; the USD figures move with "
           "the assumption.")
i1, i2 = st.columns(2, gap="medium")
value = i1.number_input("Value per conversion (USD, assumption)", min_value=1.0, max_value=1000.0, value=VALUE0,
                        step=5.0, format="%.2f", key="p4_value",
                        help=f"Illustrative default of {VALUE0:.0f} USD. Replace with the margin per conversion "
                             "from Finance.")
cpm = i2.number_input("CPM actually paid (USD per 1,000 impressions)", min_value=0.01, max_value=500.0, value=None,
                      step=0.5, format="%.2f", key="p4_cpm", placeholder="Not in the data: enter to compare")

be = {k: v * value / IMPRESSIONS * 1000 for k, v in INC.items()}
val = {k: v * value for k, v in INC.items()}
n1, n2, n3, n4 = st.columns(4)
kpi(n1, "Incremental conversions", f"{INC['point']:,.0f}", f"95% CI {INC['ci_low']:,.0f} to {INC['ci_high']:,.0f}")
kpi(n2, "Share caused by the ads", f"{share_inc:.0%}", f"95% CI {share_inc_ci[0]:.0%} to {share_inc_ci[1]:.0%}")
kpi(n3, "Last-touch overstatement", f"{overstate:.1f}×", f"95% CI {over_ci[0]:.1f}–{over_ci[1]:.1f}×",
    help=f"Last-touch attribution would credit all {T['conv_t']:,} ad-arm conversions to the campaign, against "
         f"≈{INC['point']:,.0f} the ads caused. Every ad-group user saw at least one ad, so last-touch and any-touch "
         "attribution coincide here.")
kpi(n4, "Breakeven CPM", usd(be["point"]), f"95% CI {be['ci_low']:.2f} to {be['ci_high']:.2f}",
    help="The most you can pay per 1,000 ad impressions (USD) and still get back at least the incremental value, "
         "at the value per conversion entered above.")
st.caption(f"Incremental conversions = absolute lift × the {T['n_t']:,} users in the ad arm: conversions that would "
           f"not have happened without the ads. They are {share_inc:.0%} of the {T['conv_t']:,} ad-arm conversions "
           "(= 1 − 1/RR); the rest would have happened anyway, as the PSA rate shows. Last-touch (any-touch) "
           f"attribution would credit all {T['conv_t']:,} to the campaign, {over_txt} what the ads caused: every "
           "ad-group user saw at least one ad, so the two rules coincide here.")

fig_be = F.fig_breakeven(INC["point"], INC["ci_low"], INC["ci_high"], IMPRESSIONS, value, cpm,
                         "Breakeven CPM by value per conversion (USD)", value_max=max(150.0, value * 1.5))
show(fig_be, key="p4_breakeven")
if value == VALUE0 and cpm is None:
    takeaway(CAT["ad_breakeven"])
else:
    text = (f"At {usd_input(value)} per conversion (assumed), the ≈{INC['point']:,.0f} incremental conversions are "
            f"worth ≈{usd_k(val['point'])}, so the campaign breaks even at a CPM of {usd(be['point'])} "
            f"(95% CI {usd(be['ci_low'])} to {usd(be['ci_high'])}).")
    if cpm is not None:
        cost = IMPRESSIONS * cpm / 1000
        text += (f" At {usd(cpm)} CPM the {IMPRESSIONS / 1e6:.1f}M ad impressions cost ≈{usd_k(cost)}, "
                 f"about {usd(cost / INC['point'])} per incremental conversion: "
                 f"{payback_verdict(cpm, be)[0].lower()}.")
    takeaway(text)
with st.container(border=True):
    if cpm is None:
        st.markdown(f"**Pays-back verdict.** Enter the CPM you actually paid to get a verdict. At {usd_input(value)} "
                    f"per conversion the ≈{INC['point']:,.0f} incremental conversions are worth "
                    f"≈{usd_k(val['point'])}, and the campaign breaks even below **{usd(be['point'])}** per 1,000 "
                    f"impressions (95% CI {usd(be['ci_low'])} to {usd(be['ci_high'])}).")
    else:
        label, color, reason = payback_verdict(cpm, be)
        cost = IMPRESSIONS * cpm / 1000
        st.markdown("**Pays-back verdict**")
        st.badge(label, color=color)
        st.markdown(
            f"- Media cost: **{usd_k(cost)}** for {IMPRESSIONS / 1e6:.1f}M ad impressions\n"
            f"- Cost per incremental conversion: **{usd(cost / INC['point'])}** "
            f"(95% CI {usd(cost / INC['ci_high'])} to {usd(cost / INC['ci_low'])})\n"
            f"- Incremental return on ad spend: **{val['point'] / cost:.2f}×** "
            f"(95% CI {val['ci_low'] / cost:.2f}× to {val['ci_high'] / cost:.2f}×)\n\n"
            f"Why: {reason}.")
    st.caption("Counts only conversions the ads caused (ad rate minus PSA rate), not every conversion in the ad arm.")

st.markdown("**The price of keeping the measurement: an always-on PSA holdout (R1)**")
o1, o2, o3, o4 = st.columns(4, vertical_alignment="center")
hold = o1.slider("PSA holdout (% of users)", 1, 20, int(round(HOLDOUT0 * 100)), step=1, format="%d%%",
                 key="p4_holdout",
                 help="Share of users who keep seeing the PSA instead of the ad, so the campaign's incremental "
                      f"effect can be measured continuously. Project proposal: {HOLDOUT0:.0%}.") / 100
users_h = N_TOTAL * hold
lost = {"point": users_h * (P_T - P_C), "ci_low": users_h * T["abs_ci_low"], "ci_high": users_h * T["abs_ci_high"]}
mde_h = S.mde(P_C, N_TOTAL - int(round(users_h)), int(round(users_h)), ALPHA0, POWER0)["mde_abs"]
# this test's own PSA arm already gives up conversions; the holdout's extra cost is the step from it
asrun_share = T["n_c"] / N_TOTAL
asrun_lost = T["n_c"] * (P_T - P_C)
step = lost["point"] - asrun_lost
asrun_label = f"this test's {asrun_share:.0%} PSA arm"
if abs(step) < 0.5:
    step_txt = f"about the same as {asrun_label} already forgoes (≈{asrun_lost:,.0f})"
elif step > 0:
    step_txt = (f"{asrun_label} already forgoes ≈{asrun_lost:,.0f}, so the step from {asrun_share:.0%} to "
                f"{hold:.0%} costs ≈{step:,.0f} more")
else:
    step_txt = f"≈{-step:,.0f} fewer than {asrun_label} already forgoes (≈{asrun_lost:,.0f})"
kpi(o2, "Users held out", f"{users_h / 1e3:,.1f}K", f"{hold:.0%} of {N_TOTAL / 1e3:,.0f}K per flight")
kpi(o3, "Conversions forgone", f"≈{lost['point']:,.0f}", f"95% CI {lost['ci_low']:,.0f} to {lost['ci_high']:,.0f}",
    help=f"Held-out users × the measured lift: conversions the ads would have caused among them, against no "
         f"holdout. For comparison, {asrun_label} already forgoes ≈{asrun_lost:,.0f}.")
kpi(o4, "Value forgone", usd_k(lost["point"] * value, 1), f"{usd_input(value)} each, assumed")
takeaway(f"A {hold:.0%} holdout keeps {users_h / 1e3:,.1f}K of every {N_TOTAL / 1e3:,.0f}K users on the PSA and gives "
         f"up ≈{lost['point']:,.0f} conversions per comparable flight versus no holdout "
         f"(≈{usd_k(lost['point'] * value, 1)} at {usd_input(value)} each); {step_txt}. In return the team keeps a "
         f"running causal read: with {POWER0:.0%} power it can detect a lift of {mde_h * 100:.2f} pp (this test's "
         f"{1 - SHARE0:.0%} PSA arm: {PW['mde_current']['mde_abs'] * 100:.2f} pp). Without a holdout, reporting falls "
         f"back on last-touch attribution, which would overstate the campaign {over_txt}.")

# ---------------------------------------------------------------- 6. risks
st.subheader("6 · Risks and caveats")
wilson_w = [hi - lo for lo, hi in (S.wilson_ci(T["conv_t"], T["n_t"]), S.wilson_ci(T["conv_c"], T["n_c"]))]
cramers = [b["cramers_v"] for b in AD["balance"]]
shares = AD["heterogeneity"]["exposure_bucket"]["arm_shares"]
risks = [
    "<b>No timestamps, so no novelty-effect or duration check.</b> The file has one row per user and no dates, only "
    "the weekday and hour when each user saw the most ads. We cannot tell how long the test ran, whether the lift "
    "faded as users got used to the ads (novelty effect) or whether it held across full weekly cycles. Treat the "
    "lift as an average over an unknown window; logging assignment timestamps is part of R4.",
    f"<b>The sample-ratio check cannot fail here.</b> The ad arm has {SRM['n_t']:,} users, the nearest whole number to "
    f"exactly {SHARE0:.0%} of {N_TOTAL:,} ({SRM['deviation_users']:.2f} users off). Random assignment would typically "
    f"miss by about ±{SRM['sd_users_under_random_assignment']:.0f} users, and landing on the nearest whole number "
    f"happens about {SRM['prob_exactly_nearest_integer']:.2%} of the time. So the split was most likely a fixed "
    "quota (or a trimmed export). Fixed arm sizes are a valid design; they just make the SRM test uninformative "
    f"(p = {p_text(SRM['p_value'])} by construction), so it is reported as uninformative, not as a pass. Exposure "
    "parity, next, is the meaningful check.",
    f"<b>Exposure parity is the meaningful check, and it is close but not exact.</b> Mean ads per user match "
    f"({g_ad['mean_ads']:.1f} vs {g_psa['mean_ads']:.1f}), but the shapes differ a little: "
    f"{shares['1-5']['psa']:.0%} of PSA vs {shares['1-5']['ad']:.0%} of ad users saw 1–5 ads, and "
    f"{shares['11-20']['psa']:.0%} vs {shares['11-20']['ad']:.0%} saw 11–20 (KS D = {ks_d:.3f}). Total ads, peak day "
    f"and peak hour are recorded after assignment (Cramér's V {min(cramers):.3f} to {max(cramers):.3f} between arms), "
    "so they are never used as covariates and the segment results on page 5 are exploratory.",
    f"<b>The control group sets the noise.</b> With only {T['n_c'] / N_TOTAL:.0%} of users in PSA, the PSA rate's "
    f"95% interval is {wilson_w[1] / wilson_w[0]:.1f}× wider than the ad rate's; that is what limits the precision "
    "of the lift.",
    "<b>USD figures rest on assumptions.</b> Value per conversion and CPM are not in the data. The decision to "
    "keep the campaign rests on the incremental conversions; whether it pays back needs Finance's numbers.",
]
caveat("<b>Read the result with these limits in mind.</b><ul style='margin:.35rem 0 .1rem 0; padding-left:1.25rem'>"
       + "".join(f"<li style='margin-bottom:.3rem'>{r}</li>" for r in risks) + "</ul>")

# ---------------------------------------------------------------- 7. decision
robust = all(bool((lift_intervals(a)["abs_low"] > 0).all()) for a in ALPHAS)
sesoi0 = PW["power_at_relative_lift"][str(SESOI0)]
st.subheader("7 · Decision and next steps")
with st.container(border=True):
    st.markdown(
        f"**Decision: keep the campaign running at the current budget, with an always-on {HOLDOUT0:.0%} PSA "
        "holdout (R1, Growth PM).** "
        f"The lift is {fmt_pp(T['abs_lift'])} (95% CI {pp_range(T['abs_ci_low'], T['abs_ci_high'])})"
        + (", and its interval excludes 0 under every method and confidence level on this page" if robust else "")
        + f": ≈{INC['point']:,.0f} incremental conversions per comparable flight.\n\n"
        f"- **R1 · Growth PM:** keep a {HOLDOUT0:.0%} PSA holdout running (≈{HOLD['conversions_forgone']:,.0f} "
        f"conversions forgone per {N_TOTAL / 1e3:,.0f}K-user flight versus no holdout, "
        f"≈{usd_k(HOLD['value_forgone_usd'], 1)} at the assumed {usd(VALUE0, 0)}; this test's "
        f"{HOLD['as_run_control_share']:.0%} PSA arm already forgoes "
        f"≈{HOLD['as_run_control_conversions_forgone']:,.0f}, so the step to {HOLDOUT0:.0%} costs "
        f"≈{HOLD['extra_conversions_vs_as_run']:,.0f} more) and report incremental "
        "conversions and cost per incremental conversion, not last-touch conversions, which would overstate the "
        f"campaign {over_txt}. Confirm with Finance that the CPM we pay is below breakeven "
        f"(≈{usd(BZ['breakeven_cpm_usd']['point'])} at an assumed {usd(VALUE0, 0)} per conversion, "
        f"{usd(BZ['breakeven_cpm_usd']['ci_low'])} at the pessimistic end). One flight's holdout read is about as "
        "precise as this test, so judge trends over several flights.\n"
        "- **R2 · Growth PM + media buyer:** don't double the budget blindly; test it. This test compared ads with "
        "PSAs at one spend level, so it cannot say what extra spend buys, and the lift lives in heavy users "
        "(page 5). Run a user-level test where one arm gets up to 2× today's impressions per user (the closest "
        "stand-in for 2× budget) or a frequency cap, split 50/50 or 80/20, with users tiered by activity measured "
        "*before* the test (a true budget test needs a geo split). Read out incremental conversions per extra "
        "USD 1K spent (marginal iROAS).\n"
        f"- **R4 · Analytics + Eng:** next time use a 50/50 or 80/20 split instead of {SPLIT0} (at {SPLIT0} this "
        f"test had only {sesoi0['power_current_split']:.0%} power for a {SESOI0:.0%} lift, against "
        f"{fmt_power(sesoi0['power_5050_same_total'])} for the same users at 50/50), log assignment timestamps, "
        "pre-register the primary metric, the smallest lift worth acting on and guardrails (unsubscribe / "
        "complaint rate, CPA), and run an automatic daily sample-ratio check.")

mde_ratio = PW["mde_current"]["mde_abs"] / PW["mde_if_5050_same_total"]["mde_abs"]
how_to_read(f"""
**What this page is.** The standard write-up of one experiment (a "readout"): what we expected, how we measured
it, what happened, and what we should do. The controls let you re-run the key calculations live.

**Conversion rate by arm (bar chart).** Each bar is the share of users in that group who converted. The thin
whisker on each bar is its confidence interval: the range of rates that fit the data once random noise is allowed
for. The PSA whisker is much wider because only {T['n_c'] / N_TOTAL:.0%} of users were in that group.

**Lift and its interval.** Lift = ad rate − PSA rate, in *percentage points* (pp): {fmt_pp(T['abs_lift'])} means
{fmt_pct(T['rate_t'])} vs {fmt_pct(T['rate_c'])}, not "{T['abs_lift'] * 100:.2f}% more". Relative lift
({T['rel_lift']:+.0%}) divides by the small PSA rate, so it sounds bigger; quote both. If the interval does not
include 0, "ads do nothing" is not a plausible explanation at that confidence level.

**The α and method controls.** α is the false-alarm rate we accept. A lower α is stricter and gives a wider
interval. Newcombe is the default here because it behaves well for small rates. Wald is the textbook formula.
Bootstrap re-simulates the experiment {N_BOOT:,} times from the observed data. When all three agree, as they do here,
the conclusion does not hinge on a statistical choice.

**Bootstrap histogram.** Each bar counts how many of the {N_BOOT:,} simulated re-runs produced that lift. The shaded
band holds the middle 95% (or whatever level you chose). A band far from the "no effect" line means the result is not
a fluke of this particular sample.

**Power and MDE.** Power is the chance the test catches a true effect of a given size. The MDE (minimum detectable
effect) is the smallest effect it catches with the chosen power, {POWER0:.0%} by default. Both describe the *design*,
so they are judged at the smallest lift worth acting on (the orange dotted line, {SESOI0:.0%} relative by default, a
placeholder in config.yaml that the PM and Finance would agree before launch), not at the lift we observed: "power at
the observed effect" only restates the p-value. With a {SPLIT0} split the small
PSA group sets the noise level; the same users split 50/50 could detect an effect about {mde_ratio:.1f}× smaller.
Use this to size a test *before* running it, not to explain away a result afterwards.

**Breakeven CPM.** CPM is the cost of 1,000 ad impressions. Breakeven CPM is the most you can pay per 1,000
impressions and still get back at least the value of the conversions the ads *caused*. Value per conversion is an
assumption (there is no revenue in the data), so change it and watch the line move. If the CPM you actually pay is
below the line, the campaign pays back.

**Holdout cost.** An always-on holdout keeps a small share of users on the PSA so the campaign's incremental effect
stays measurable. Its cost is the conversions those users would have gained from the ads; the slider shows how cost
and measurement precision trade off. This test already held out {T['n_c'] / N_TOTAL:.0%} of users, so only the step
beyond that is a new cost.

**Common misreadings.**
- "A {T['rel_lift']:.0%} lift means {T['rel_lift']:.0%} more revenue." No: it is relative to a small base rate, and
  the value per conversion is assumed.
- "All {T['conv_t']:,} ad-arm conversions came from the ads." No: the PSA rate says about
  {1 - share_inc:.0%} would have happened anyway. That is why last-touch attribution would overstate the campaign
  {over_txt}.
- "Significant, so double the budget." This test compared ads with PSAs at one spend level. It says nothing about
  what the next USD 1K buys, which is what R2's test is for.
- "The SRM check passed, so assignment is fine." The split is most likely a fixed quota (a valid design), so the check
  passes by construction; exposure parity is the check that carries information.
- "p < 0.0001 means a big effect." It means the effect is very unlikely to be zero. The interval shows how big it is.
- "The effect will last." With no timestamps we cannot check whether it fades over time (novelty effect).
""")

# ---------------------------------------------------------------- phones
# A wide markdown table scrolls inside itself instead of pushing the whole page sideways; the metrics
# table's definition and result columns are prose, so they keep a readable width.
st.markdown("<style>@media (max-width: 640px) {"
            "[data-testid='stMarkdownContainer'] table {display: block; overflow-x: auto; max-width: 100%;}"
            "[data-testid='stMarkdownContainer'] th, [data-testid='stMarkdownContainer'] td {min-width: 4.5rem;}"
            "[data-testid='stMarkdownContainer'] td:nth-child(n+3) {min-width: 11rem;}"
            "}</style>", unsafe_allow_html=True)
