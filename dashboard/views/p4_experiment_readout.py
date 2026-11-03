"""Page 4 · Experiment readout: ad vs PSA (Marketing A/B).

Laid out like a standard experiment readout: hypothesis and design -> metrics
-> result -> power -> business value -> risks -> decision.

Headline numbers are read from reports/results.json. The controls recompute
intervals, power and breakeven from the same counts with src/stats.py; the
bootstrap interval reuses the cached draws (boot_ad_lift) and only re-takes
percentiles when alpha changes.
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
BZ = AD["business"]
INC = BZ["incremental_conversions"]
IMPRESSIONS = int(BZ["impressions_ad_group"])
CAT = load_catalog_takeaways()
BOOT = load_cache("boot_ad_lift")

ALPHA0 = float(CFG["alpha"])
POWER0 = float(CFG["power"])
SHARE0 = float(CFG["intended_ad_share"])
VALUE0 = float(CFG["value_per_conversion_usd"])
N_TOTAL = int(T["n_t"] + T["n_c"])
N_BOOT = len(BOOT)
# exact rates from counts (results.json rounds rates to 6 decimals)
P_T = T["conv_t"] / T["n_t"]
P_C = T["conv_c"] / T["n_c"]

ALPHAS = [0.10, 0.05, 0.01, 0.001]
ALPHA_LABELS = {0.10: "0.10", 0.05: "0.05", 0.01: "0.01", 0.001: "0.001"}
METHODS = {"newcombe": "Newcombe (score)", "wald": "Wald", "bootstrap": "Bootstrap percentile"}
POWERS = [0.70, 0.80, 0.90, 0.95]


# ------------------------------------------------------------------ helpers
def conf(alpha: float) -> str:
    """Confidence level for an alpha: 0.05 -> '95%'."""
    return f"{(1 - alpha) * 100:g}%"


def pp_range(lo: float, hi: float) -> str:
    return f"{lo * 100:+.2f} to {hi * 100:+.2f} pp"


def ci_short(lo: float, hi: float) -> str:
    """Interval in pp without the unit, for the small metric notes."""
    return f"{lo * 100:+.2f} to {hi * 100:+.2f}"


def p_text(p: float) -> str:
    return "< 0.0001" if p < 1e-4 else f"{p:.4f}"


def md_usd(x: float, nd: int = 2) -> str:
    """Dollar amount for st.markdown / st.metric, where a bare $ starts LaTeX."""
    return f"\\${x:,.{nd}f}"


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


@st.cache_data(show_spinner=False)
def mde_figure(share: float, alpha: float, power: float):
    return F.fig_mde_by_split(P_C, N_TOTAL, share, T["abs_lift"], alpha, power,
                              "Minimum detectable lift by treatment share (pp)", height=380)


@st.cache_data(show_spinner=False)
def power_figure(n_t: int, n_c: int, alpha: float, power: float):
    return F.fig_power_curve(P_C, n_t, n_c, alpha, T["abs_lift"], "Power to detect a true lift (%)",
                             target_power=power, height=380)


def relabel_percentiles(fig, alpha: float):
    """fig_bootstrap labels its interval lines '2.5%' / '97.5%'; match them to the chosen alpha."""
    lo_lab, hi_lab = f"{alpha / 2 * 100:g}%:", f"{(1 - alpha / 2) * 100:g}%:"
    for ann in fig.layout.annotations:
        if ann.text and ann.text.startswith("2.5%:"):
            ann.text = ann.text.replace("2.5%:", lo_lab, 1)
        elif ann.text and ann.text.startswith("97.5%:"):
            ann.text = ann.text.replace("97.5%:", hi_lab, 1)
    return fig


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

with st.container(border=True):
    st.markdown(
        f"**Readout in one line.** Ads lifted conversion from {fmt_pct(T['rate_c'])} (PSA) to "
        f"{fmt_pct(T['rate_t'])}: {fmt_pp(T['abs_lift'])} (95% CI {pp_range(T['abs_ci_low'], T['abs_ci_high'])}), "
        f"{T['rel_lift']:+.0%} relative, ≈{INC['point']:,.0f} incremental conversions. "
        "**Keep the campaign at its current budget; test a bigger budget before doubling it.**")

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
        "- Decision rule: keep the campaign if the 95% CI for the lift excludes 0 **and** the sanity checks pass.")
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
srm = AD["srm"]
srm_status = srm.get("status") or ("FAIL" if srm["flag"] else "PASS")
g_ad, g_psa = AD["groups"]["ad"], AD["groups"]["psa"]
st.markdown(
    "| Role | Metric | Definition | Result |\n"
    "|---|---|---|---|\n"
    f"| **Primary** | Conversion rate | Users with `converted = True` ÷ users assigned to the arm "
    f"| Ad {fmt_pct(T['rate_t'])} vs PSA {fmt_pct(T['rate_c'])} |\n"
    f"| Secondary | Relative lift | Ad rate ÷ PSA rate − 1 "
    f"| {T['rel_lift']:+.0%} (95% CI {T['rel_ci_low']:+.0%} to {T['rel_ci_high']:+.0%}) |\n"
    f"| Secondary | Incremental conversions | Absolute lift × users in the ad arm "
    f"| ≈{INC['point']:,.0f} (95% CI {INC['ci_low']:,.0f} to {INC['ci_high']:,.0f}) |\n"
    f"| Guardrail (trust) | Sample ratio (SRM) | Observed vs intended {SHARE0 * 100:.0f}/{(1 - SHARE0) * 100:.0f} split, "
    f"chi-square test | p = {srm['p_value']:.4f}: {srm_status.lower()} (weak check, see risks) |\n"
    f"| Guardrail (trust) | Exposure parity | Mean ads seen per user, ad vs PSA "
    f"| {g_ad['mean_ads']:.1f} vs {g_psa['mean_ads']:.1f}: pass |\n"
    "| Guardrails we lack | Unsubscribe / hide-ad rate, complaint rate, cost per acquisition (CPA) "
    "| Not in this dataset | Cannot be checked here; add them to the next test (R4) |")

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
kpi(k4, "p-value (z-test)", p_text(test.p_value), f"{n_le0:,} of {N_BOOT:,} draws ≤ 0",
    help="Two-sided pooled two-proportion z-test. The note counts bootstrap resamples with a lift at or below zero.")

g1, g2 = st.columns(2)
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
    b_ci = (float(cis.loc["bootstrap", "abs_low"]), float(cis.loc["bootstrap", "abs_high"]))
    fig_b = F.fig_bootstrap(BOOT["abs_lift"].to_numpy(), b_ci, T["abs_lift"],
                            f"Bootstrap distribution of the lift (pp, {N_BOOT:,} resamples)", height=400)
    fig_b.update_traces(nbinsx=60, selector=dict(type="histogram"))  # half-width chart: fewer, wider bins
    fig_b.update_layout(bargap=0.04)  # the shared layout's bar gap makes a histogram look like a comb
    show(relabel_percentiles(fig_b, alpha), key="p4_bootstrap")
    if alpha == ALPHA0:
        takeaway(CAT["ad_bootstrap"])
    else:
        tail = alpha / 2 * N_BOOT
        note = (f" Each tail now rests on only {tail:g} draws, so treat the bootstrap bounds as approximate."
                if tail < 50 else "")
        takeaway(f"The middle {conf(alpha)} of the {N_BOOT:,} resampled lifts runs from {b_ci[0] * 100:.2f} to "
                 f"{b_ci[1] * 100:.2f} pp, and {n_le0:,} resamples show a lift ≤ 0.{note}")

view = pd.DataFrame({
    "Interval method": [METHODS[m] + ("  ← selected" if m == method else "") for m in cis.index],
    "Lower (pp)": cis["abs_low"].to_numpy() * 100,
    "Upper (pp)": cis["abs_high"].to_numpy() * 100,
    "Width (pp)": (cis["abs_high"] - cis["abs_low"]).to_numpy() * 100,
    "Excludes 0": np.where((cis["abs_low"] > 0) | (cis["abs_high"] < 0), "Yes", "No"),
})
st.markdown(f"**All three interval methods at {conf(alpha)} confidence**")
st.dataframe(view, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.3f") for c in ("Lower (pp)", "Upper (pp)")}
             | {"Width (pp)": st.column_config.NumberColumn(format="%.3f")})

# ---------------------------------------------------------------- 4. power
st.subheader("4 · Power: what could this test detect?")
q1, q2, q3, q4 = st.columns([1.4, 1, 1.1, 1])
share = q1.slider("Share of users in treatment (ad)", 50, 99, int(round(SHARE0 * 100)), step=1, format="%d%%",
                  key="p4_share", help=f"This test ran at {SHARE0:.0%}. Same total users, different split.") / 100
PW_ALPHAS = [0.10, 0.05, 0.01]
pw_alpha = q2.radio("α", PW_ALPHAS, index=PW_ALPHAS.index(ALPHA0) if ALPHA0 in PW_ALPHAS else 1,
                    format_func=lambda a: f"{a:.2f}", horizontal=True, key="p4_pw_alpha")
power = q3.select_slider("Power (1 − β)", POWERS, value=POWER0 if POWER0 in POWERS else 0.80,
                         format_func=lambda x: f"{x:.0%}", key="p4_power")
rel_target = q4.number_input("Lift worth detecting (relative %)", min_value=1.0, max_value=100.0, value=10.0,
                             step=1.0, format="%.0f", key="p4_rel_target",
                             help="Smallest relative lift the business would act on; used for the required sample.") / 100

n_t = int(round(N_TOTAL * share))
n_c = N_TOTAL - n_t
split = f"{share * 100:.0f}/{(1 - share) * 100:.0f}"
mde_sel = S.mde(P_C, n_t, n_c, pw_alpha, power)
mde_half = S.mde(P_C, N_TOTAL // 2, N_TOTAL // 2, pw_alpha, power)
need_sel = S.required_total_n(P_C, rel_target * P_C, share, pw_alpha, power)
need_half = S.required_total_n(P_C, rel_target * P_C, 0.5, pw_alpha, power)
achieved = S.achieved_power(P_C, P_T, n_t, n_c, pw_alpha)

m1, m2, m3, m4 = st.columns(4)
kpi(m1, f"MDE at {split}", f"{mde_sel['mde_abs'] * 100:.2f} pp", f"{mde_sel['mde_rel']:+.0%} relative · {N_TOTAL:,} users")
kpi(m2, "MDE at 50/50, same users", f"{mde_half['mde_abs'] * 100:.2f} pp", f"{mde_half['mde_rel']:+.0%} relative")
kpi(m3, f"Users needed for a {rel_target:.0%} lift at {split}", f"{need_sel:,}",
    f"{need_sel / N_TOTAL:.1f}× this test's sample")
kpi(m4, f"Users needed for a {rel_target:.0%} lift at 50/50", f"{need_half:,}",
    f"{need_sel / need_half:.1f}× fewer than at {split}")

is_default_power = (share == SHARE0 and pw_alpha == ALPHA0 and power == POWER0)
pc1, pc2 = st.columns(2)
with pc1:
    show(mde_figure(share, pw_alpha, power), key="p4_mde")
    if is_default_power:
        takeaway(CAT["ad_mde_split"])
    else:
        clears = "clears" if T["abs_lift"] >= mde_sel["mde_abs"] else "does not clear"
        takeaway(f"At a {split} split these {N_TOTAL:,} users can detect a lift of {mde_sel['mde_abs'] * 100:.2f} pp "
                 f"with {power:.0%} power at α = {pw_alpha:.2f}; a 50/50 split of the same users gets to "
                 f"{mde_half['mde_abs'] * 100:.2f} pp. The observed {T['abs_lift'] * 100:.2f} pp {clears} the "
                 f"{split} bar.")
with pc2:
    show(power_figure(n_t, n_c, pw_alpha, power), key="p4_power_curve")
    if is_default_power:
        takeaway(CAT["ad_power_curve"])
    else:
        takeaway(f"With {n_t:,} ad and {n_c:,} PSA users, a true lift of {mde_sel['mde_abs'] * 100:.2f} pp is caught "
                 f"{power:.0%} of the time; a lift the size of the observed {T['abs_lift'] * 100:.2f} pp would be "
                 f"caught {achieved:.0%} of the time.")
st.caption(f"Sizing the next test: detecting a {rel_target:.0%} relative lift needs {need_half:,} users at 50/50 "
           f"but {need_sel:,} at {split}. Unequal splits pay for a small control group with a lot of extra traffic. "
           "The sample-size calculator on page 7 turns this into days of traffic.")

# ---------------------------------------------------------------- 5. business
st.subheader("5 · Is it worth the money?")
st.caption("The data has no revenue or cost fields: value per conversion is an explicit assumption and the CPM "
           "must come from Finance. Incremental conversions are the number to quote; the dollar figures move "
           "with the assumption.")
i1, i2, _ = st.columns([1, 1, 1])
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
kpi(n2, "Incremental value", f"{md_usd(val['point'] / 1e3, 0)}K",
    f"95% CI {md_usd(val['ci_low'] / 1e3, 0)}K to {md_usd(val['ci_high'] / 1e3, 0)}K",
    help="Incremental conversions × the assumed value per conversion.")
kpi(n3, "Breakeven CPM", md_usd(be["point"]), f"95% CI {md_usd(be['ci_low'])} to {md_usd(be['ci_high'])}",
    help="The most you can pay per 1,000 ad impressions and still get back at least the incremental value.")
kpi(n4, "Caused by the ads", f"{BZ['share_of_ad_conversions_incremental']:.0%}",
    f"of {T['conv_t']:,} ad-arm conversions",
    help="Lift ÷ ad conversion rate: the share of the ad arm's conversions that would not have happened without "
         f"the ads. That is ≈{BZ['impressions_per_incremental_conversion']:,.0f} impressions per incremental "
         "conversion.")

bc1, bc2 = st.columns([2, 1])
with bc1:
    fig_be = F.fig_breakeven(INC["point"], INC["ci_low"], INC["ci_high"], IMPRESSIONS, value, cpm,
                             "Breakeven CPM by value per conversion (USD)", value_max=max(150.0, value * 1.5))
    show(fig_be, key="p4_breakeven")
    if value == VALUE0 and cpm is None:
        takeaway(CAT["ad_breakeven"])
    else:
        text = (f"At ${value:,.2f} per conversion (assumed), the ≈{INC['point']:,.0f} incremental conversions are "
                f"worth ≈${val['point'] / 1e3:,.0f}K, so the campaign breaks even at a CPM of ${be['point']:.2f} "
                f"(95% CI ${be['ci_low']:.2f} to ${be['ci_high']:.2f}).")
        if cpm is not None:
            cost = IMPRESSIONS * cpm / 1000
            text += (f" At ${cpm:.2f} CPM the {IMPRESSIONS / 1e6:.1f}M ad impressions cost ≈${cost / 1e3:,.0f}K, "
                     f"about ${cost / INC['point']:,.2f} per incremental conversion: "
                     f"{payback_verdict(cpm, be)[0].lower()}.")
        takeaway(text)
with bc2:
    with st.container(border=True):
        st.markdown("**Pays-back verdict**")
        if cpm is None:
            st.markdown(f"Enter the CPM you actually paid to get a verdict. At {md_usd(value)} per conversion the "
                        f"campaign breaks even below **{md_usd(be['point'])}** per 1,000 impressions "
                        f"(95% CI {md_usd(be['ci_low'])} to {md_usd(be['ci_high'])}).")
        else:
            label, color, reason = payback_verdict(cpm, be)
            cost = IMPRESSIONS * cpm / 1000
            st.badge(label, color=color)
            st.markdown(
                f"- Media cost: **{md_usd(cost / 1e3, 0)}K** for {IMPRESSIONS / 1e6:.1f}M ad impressions\n"
                f"- Cost per incremental conversion: **{md_usd(cost / INC['point'])}** "
                f"(95% CI {md_usd(cost / INC['ci_high'])} to {md_usd(cost / INC['ci_low'])})\n"
                f"- Incremental return on ad spend: **{val['point'] / cost:.2f}×** "
                f"(95% CI {val['ci_low'] / cost:.2f}× to {val['ci_high'] / cost:.2f}×)\n\n"
                f"Why: {reason}.")
        st.caption("Counts only conversions the ads caused (ad rate minus PSA rate), not every conversion "
                   "in the ad arm.")

# ---------------------------------------------------------------- 6. risks
st.subheader("6 · Risks and caveats")
wilson_w = [hi - lo for lo, hi in (S.wilson_ci(T["conv_t"], T["n_t"]), S.wilson_ci(T["conv_c"], T["n_c"]))]
cramers = [b["cramers_v"] for b in AD["balance"]]
risks = [
    "<b>No timestamps, so no novelty-effect or duration check.</b> The file has one row per user and no dates, only "
    "the weekday and hour when each user saw the most ads. We cannot tell how long the test ran, whether the lift "
    "faded as users got used to the ads (novelty effect) or whether it held across full weekly cycles. Treat the "
    "lift as an average over an unknown window; logging assignment timestamps is part of R4.",
    f"<b>The SRM pass is weak evidence.</b> The intended {SHARE0 * 100:.0f}/{(1 - SHARE0) * 100:.0f} split is not "
    f"documented; it is inferred from the round number of the observed split, so p = {srm['p_value']:.4f} says "
    f"little. Exposure parity (mean {g_ad['mean_ads']:.1f} vs {g_psa['mean_ads']:.1f} ads per user) is the stronger "
    "sanity check.",
    "<b>Total ads, peak day and peak hour are post-assignment.</b> They are recorded after randomization and differ "
    f"slightly by arm (Cramér's V {min(cramers):.3f} to {max(cramers):.3f}), so they are never used as covariates "
    "and the segment results on page 5 are exploratory.",
    f"<b>The control group sets the noise.</b> With only {T['n_c'] / N_TOTAL:.0%} of users in PSA, the PSA rate's "
    f"95% interval is {wilson_w[1] / wilson_w[0]:.1f}× wider than the ad rate's; that is what limits the precision "
    "of the lift.",
    "<b>Dollar figures rest on assumptions.</b> Value per conversion and CPM are not in the data. The decision to "
    "keep the campaign rests on the incremental conversions; whether it pays back needs Finance's numbers.",
]
caveat("<b>Read the result with these limits in mind.</b><ul style='margin:.35rem 0 .1rem 0; padding-left:1.25rem'>"
       + "".join(f"<li style='margin-bottom:.3rem'>{r}</li>" for r in risks) + "</ul>")

# ---------------------------------------------------------------- 7. decision
robust = all(bool((lift_intervals(a)["abs_low"] > 0).all()) for a in ALPHAS)
st.subheader("7 · Decision and next steps")
with st.container(border=True):
    st.markdown(
        "**Decision: keep the campaign running at the current budget (R1, Growth PM).** "
        f"The lift is {fmt_pp(T['abs_lift'])} (95% CI {pp_range(T['abs_ci_low'], T['abs_ci_high'])})"
        + (", and its interval excludes 0 under every method and confidence level on this page" if robust else "")
        + f": ≈{INC['point']:,.0f} incremental conversions per comparable flight.\n\n"
        "- **R1 · Growth PM:** keep an always-on 5–10% PSA holdout; track the incremental conversion rate and the "
        "cost per incremental conversion. Confirm with Finance that the CPM we pay is below breakeven "
        f"(≈{md_usd(BZ['breakeven_cpm_usd']['point'])} at an assumed {md_usd(VALUE0, 0)} per conversion).\n"
        "- **R2 · Growth PM + media buyer:** do not double the budget on this evidence. The test did not vary spend. "
        "Run randomized 2× budget or frequency-cap arms (50/50 or 80/20 split, sized with the page-7 calculator) "
        f"and read out marginal incremental conversions per extra {md_usd(1000, 0)} (marginal iROAS).\n"
        "- **R4 · Analytics + Eng:** next time use a 50/50 or 80/20 split instead of 96/4, log assignment "
        "timestamps, and pre-register the primary metric and guardrails (unsubscribe / complaint rate, CPA).")

split0 = f"{SHARE0 * 100:.0f}/{(1 - SHARE0) * 100:.0f}"
mde_ratio = AD["power"]["mde_current"]["mde_abs"] / AD["power"]["mde_if_5050_same_total"]["mde_abs"]
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

**Power and MDE.** Power is the chance the test catches an effect of a given size if it is real. The MDE (minimum
detectable effect) is the smallest effect it catches with the chosen power, {POWER0:.0%} by default. With a
{split0} split the small PSA group sets the noise level; the same users split 50/50 could detect an effect about
{mde_ratio:.1f}× smaller. Use this to size a test *before* running it, not to explain away a null result afterwards.

**Breakeven CPM.** CPM is the cost of 1,000 ad impressions. Breakeven CPM is the most you can pay per 1,000
impressions and still get back at least the value of the conversions the ads *caused*. Value per conversion is an
assumption (there is no revenue in the data), so change it and watch the line move. If the CPM you actually pay is
below the line, the campaign pays back.

**Common misreadings.**
- "A {T['rel_lift']:.0%} lift means {T['rel_lift']:.0%} more revenue." No: it is relative to a small base rate, and
  the value per conversion is assumed.
- "All {T['conv_t']:,} ad-arm conversions came from the ads." No: the PSA rate says about
  {1 - BZ['share_of_ad_conversions_incremental']:.0%} would have happened anyway.
- "Significant, so double the budget." This test compared ads with no ads at one spend level. It says nothing about
  what the next dollar buys, which is what R2's budget test is for.
- "p ≈ 0 means a big effect." It means the effect is very unlikely to be zero. The interval shows how big it is.
- "The effect will last." With no timestamps we cannot check whether it fades over time (novelty effect).
""")
