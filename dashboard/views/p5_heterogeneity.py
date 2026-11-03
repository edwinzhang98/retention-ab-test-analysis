"""Page 5 · Heterogeneity: does the ad lift differ by peak day, peak hour or exposure?

Per-segment two-proportion tests with a live multiple-comparison correction,
one interaction likelihood-ratio test per dimension (from results.json), and
the exposure dose-response view behind recommendation R2. All three
dimensions are recorded after assignment, so everything here is exploratory.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from common import (C, F, S, caveat, how_to_read, load_cache, load_catalog_takeaways, load_results, page_header,
                    show, takeaway)

RES = load_results()
AD = RES["ad"]
T = AD["test"]
HET = AD["heterogeneity"]
BALANCE = {b["variable"]: b for b in AD["balance"]}
CAT = load_catalog_takeaways()
ALPHA0 = float(RES["config"]["alpha"])

DIMS = {
    "most_ads_day": {"label": "Peak ad day", "noun": "day", "plural": "days", "title": "peak ad day",
                     "axis": "Day with most ads", "order": C.DAY_ORDER, "catalog": "het_day"},
    "most_ads_hour": {"label": "Peak ad hour", "noun": "hour", "plural": "hours", "title": "peak ad hour",
                      "axis": "Hour with most ads (0–23)", "order": list(range(24)), "catalog": "het_hour"},
    "exposure_bucket": {"label": "Total ads seen (exposure bucket)", "noun": "exposure bucket",
                        "plural": "exposure buckets", "title": "total ads seen", "axis": "Total ads seen (bucket)",
                        "order": C.EXPOSURE_LABELS, "catalog": "het_exposure_forest"},
}
CORRECTIONS = {"none": "None (unadjusted)", "bonferroni": "Bonferroni", "holm": "Holm",
               "fdr_bh": "Benjamini–Hochberg (FDR)"}
DEFAULT_CORRECTION = "holm"
ALPHAS = [0.10, 0.05, 0.01]
SMALL_CONTROL = 100  # control users per segment below which intervals get very wide


@st.cache_data(show_spinner=False)
def segment_table(dim: str, method: str, alpha: float) -> pd.DataFrame:
    """Per-segment lift, CI at alpha, raw and adjusted p-values (src.stats.segment_lifts)."""
    return S.segment_lifts(load_cache("agg_ad_cells"), dim, "ad", "psa", alpha=alpha, method=method,
                           order=DIMS[dim]["order"])


def conf(alpha: float) -> str:
    return f"{(1 - alpha) * 100:g}%"


def p_text(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def p_eq(p: float) -> str:
    """'p = 0.013' or 'p < 0.001', for use inside sentences."""
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def seg_name(dim: str, seg) -> str:
    if dim == "most_ads_hour":
        return f"hour {seg}"
    if dim == "exposure_bucket":
        return f"{seg} ads"
    return str(seg)


def evidence(p: float, alpha: float, dim: str) -> str:
    """Plain-language reading of the interaction test."""
    noun = DIMS[dim]["noun"]
    if p >= alpha:
        return f"no evidence that the lift differs by {noun}"
    strength = "weak evidence" if p >= 0.01 else ("evidence" if p >= 0.001 else "strong evidence")
    text = f"{strength} that the lift differs by {noun}"
    if dim == "exposure_bucket":
        text += (", but exposure is post-assignment, so this mostly says heavy and light users respond "
                 "differently, not that more ads cause more lift")
    return text


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


# ------------------------------------------------------------------ page
page_header("Heterogeneity by Day / Hour",
            "Does the ad work better on some days or hours, and is that real or noise?")

c1, c2, c3 = st.columns([1.2, 1.2, 1])
dim = c1.selectbox("Split the lift by", list(DIMS), format_func=lambda d: DIMS[d]["label"], key="p5_dim")
method = c2.selectbox("Multiple-comparison correction", list(CORRECTIONS), format_func=CORRECTIONS.get,
                      index=list(CORRECTIONS).index(DEFAULT_CORRECTION), key="p5_corr",
                      help="How to adjust p-values when testing many segments at once.")
alpha = c3.radio("Significance level α", ALPHAS, index=ALPHAS.index(ALPHA0) if ALPHA0 in ALPHAS else 1,
                 format_func=lambda a: f"{a:.2f}", horizontal=True, key="p5_alpha")

d = DIMS[dim]
tab = segment_table(dim, method, alpha)
het = HET[dim]
lrt = het["lrt"]
n_seg = len(tab)
n_raw = int((tab["p_value"] < alpha).sum())
n_adj = int(tab["significant_adj"].sum())
expected_fp = n_seg * alpha
survivors = [seg_name(dim, x) for x in tab.loc[tab["significant_adj"], dim]]

k1, k2, k3, k4, k5 = st.columns(5)
kpi(k1, "Segments tested", f"{n_seg}", d["plural"])
kpi(k2, "Significant, raw p", f"{n_raw}", f"p < {alpha:.2f}",
    help="Segments with an unadjusted p-value below α.")
kpi(k3, "After correction", f"{n_adj}", CORRECTIONS[method].split(" (")[0],
    help="Segments still significant after the selected multiple-comparison correction.")
kpi(k4, "Expected by chance", f"{expected_fp:.1f}", f"{n_seg} × α {alpha:.2f}")  # false positives if no real differences
kpi(k5, "Interaction p", p_text(lrt["p_value"]), f"LRT, all {d['plural']}",
    help="Likelihood-ratio test of ad × segment: does the lift differ across segments at all? One test, no "
         "correction needed.")

adj_label = "unadjusted significance" if method == "none" else f"{CORRECTIONS[method]}-adjusted significance"
fig = F.fig_lift_forest(tab, dim, f"Ad lift by {d['title']} (pp, {conf(alpha)} CI, {adj_label})",
                        overall_lift=T["abs_lift"], seg_title=d["axis"])
fig.update_yaxes(automargin=True)
show(fig, key="p5_forest")

if method == DEFAULT_CORRECTION and alpha == ALPHA0:
    takeaway(CAT[d["catalog"]])
else:
    names = f" ({', '.join(survivors)})" if 0 < len(survivors) <= 3 else ""
    if method == "none":
        lead = (f"{n_raw} of {n_seg} {d['plural']} are 'significant' at α = {alpha:.2f} with no correction, "
                f"against ≈{expected_fp:.1f} expected by chance if nothing differed")
    else:
        verb = "survives" if n_adj == 1 else "survive"
        lead = (f"{n_raw} of {n_seg} {d['plural']} look 'significant' before correction and {n_adj} {verb} "
                f"{CORRECTIONS[method]}{names} at α = {alpha:.2f}")
    takeaway(f"{lead}. Interaction test {p_eq(lrt['p_value'])}: {evidence(lrt['p_value'], alpha, dim)}.")

b1, b2 = st.columns(2)
with b1.container(border=True, height="stretch"):
    st.markdown(f"**One test for the whole dimension (interaction LRT)**  \n"
                f"Likelihood-ratio χ² = {lrt['lr_stat']:.1f} on {lrt['df']} df, {p_eq(lrt['p_value'])}: "
                f"{evidence(lrt['p_value'], alpha, dim)}. Because it is a single test, it needs no "
                "multiple-comparison correction; it is the number to quote before any per-segment result.")
with b2.container(border=True, height="stretch"):
    mh = het["stratified"]["mh_risk_diff"]
    st.markdown(f"**Robustness: the lift pooled within {d['plural']}**  \n"
                f"Mantel–Haenszel lift {mh * 100:+.2f} pp vs {T['abs_lift'] * 100:+.2f} pp overall: the headline "
                f"result is not an artifact of how users happen to be spread across {d['plural']}.")

small = tab[(tab["n_c"] < SMALL_CONTROL) | (tab["conv_c"] == 0)]
v = BALANCE[dim]["cramers_v"]
note_small = ""
if len(small):
    seg_list = ", ".join(small[dim].astype(str))
    note_small = (f" {len(small)} of {n_seg} {d['plural']} ({seg_list}) have fewer than {SMALL_CONTROL} PSA users or "
                  "no PSA conversions at all, so their intervals are very wide and their relative lift is undefined.")
caveat(f"<b>Exploratory, not a randomized comparison.</b> {d['label']} is recorded after assignment and its mix "
       f"differs slightly between arms (Cramér's V {v:.3f}). It describes how users behaved, not a slot we "
       f"bought, so a pattern here is a hypothesis for a pre-registered test, not a reason to move budget."
       f"{note_small}")

with st.expander(f"Segment table: all {n_seg} {d['plural']} ({CORRECTIONS[method]}, α = {alpha:.2f})"):
    show_tab = pd.DataFrame({
        d["axis"]: tab[dim].astype(str),
        "Ad users": tab["n_t"], "PSA users": tab["n_c"],
        "Ad rate (%)": tab["rate_t"] * 100, "PSA rate (%)": tab["rate_c"] * 100,
        "Lift (pp)": tab["abs_lift"] * 100,
        f"{conf(alpha)} CI low (pp)": tab["abs_ci_low"] * 100, f"{conf(alpha)} CI high (pp)": tab["abs_ci_high"] * 100,
        "p-value": tab["p_value"], "Adjusted p": tab["p_adj"],
        "Significant": np.where(tab["significant_adj"], "Yes", "No"),
    })
    fmt2 = st.column_config.NumberColumn(format="%.2f")
    st.dataframe(show_tab, hide_index=True, width="stretch",
                 column_config={"Ad users": st.column_config.NumberColumn(format="localized"),
                                "PSA users": st.column_config.NumberColumn(format="localized"),
                                "Ad rate (%)": fmt2, "PSA rate (%)": fmt2,
                                "Lift (pp)": st.column_config.NumberColumn(format="%+.2f"),
                                f"{conf(alpha)} CI low (pp)": st.column_config.NumberColumn(format="%+.2f"),
                                f"{conf(alpha)} CI high (pp)": st.column_config.NumberColumn(format="%+.2f"),
                                "p-value": st.column_config.NumberColumn(format="%.4f"),
                                "Adjusted p": st.column_config.NumberColumn(format="%.4f")})

# ---------------------------------------------------------------- dose-response
st.subheader("Exposure dose-response: the clue behind “double the budget?”")
expo = segment_table("exposure_bucket", DEFAULT_CORRECTION, ALPHA0)
show(F.fig_dose_response(expo, "Conversion rate by total ads seen, ad vs PSA (%)"), key="p5_dose")
takeaway(CAT["het_exposure"])
caveat("<b>Total ads seen is a post-assignment variable.</b> Users who are more active see more ads <i>and</i> "
       "convert more, in both arms, so this chart mixes the kind of user with the effect of the ads. It suggests a "
       "frequency sweet spot (no lift for light exposure, saturation past 200 ads) but cannot tell us what a "
       "bigger budget would buy. Only a randomized budget or frequency test can.")

hd, hh = HET["most_ads_day"], HET["most_ads_hour"]
with st.container(border=True):
    st.markdown(
        "**What this means for the plan**\n\n"
        f"- **R3 · Media buyer:** do not re-plan spend by day or hour yet. The day effect is weak (interaction "
        f"p = {hd['lrt']['p_value']:.3f}; lift from {hd['min_lift_pp']:.2f} pp on {hd['min_lift_segment']} to "
        f"{hd['max_lift_pp']:.2f} pp on {hd['max_lift_segment']}) and there is no evidence of an hour effect "
        f"(p = {hh['lrt']['p_value']:.2f}; {hh['n_sig_unadjusted']} of {hh['n_segments']} hours 'significant' "
        f"unadjusted, {hh['n_sig_holm']} after Holm). If daypart matters to the team, run a pre-registered daypart "
        f"test (e.g. {hd['max_lift_segment']} vs {hd['min_lift_segment']}) with the day as the randomized factor.\n"
        "- **R2 · Growth PM + media buyer:** before doubling the budget, run randomized 2× budget or frequency-cap "
        "arms and measure marginal incremental conversions per extra \\$1,000. The dose-response pattern above "
        "is the hypothesis that test checks: is there a frequency sweet spot, and does extra spend land past it?")

hour_holm = segment_table("most_ads_hour", DEFAULT_CORRECTION, ALPHA0)
hour_survivors = [str(h) for h in hour_holm.loc[hour_holm["significant_adj"], "most_ads_hour"]]
top_bucket = C.EXPOSURE_LABELS[-1]
n_top_c = int(expo.loc[expo["exposure_bucket"].astype(str) == top_bucket, "n_c"].iloc[0])
survivor_bullet = (f'- "Hour {hour_survivors[0]} is significant." It is the only one of {hh["n_segments"]} hours that '
                   f'survives Holm, and about {hh["n_segments"] * ALPHA0:.1f} false positives are expected by chance.\n'
                   if len(hour_survivors) == 1 else "")
how_to_read(f"""
**Forest plot (the main chart).** One row per segment, e.g. each weekday. The dot is the lift in that segment, the
horizontal line through it is its confidence interval, the solid vertical line at 0 means "no effect" and the dotted
blue line is the overall lift. A **filled** dot survives the selected multiple-comparison correction; a **hollow**
dot does not.

**Why corrections matter.** Test {hh['n_segments']} hours at α = {ALPHA0:.2f} and you expect about
{hh['n_segments'] * ALPHA0:.1f} hours to look "significant" even if the ad works the same every hour
({hh['n_segments']} × {ALPHA0:.2f}). The more segments you slice, the more false alarms you collect.
- *Bonferroni* divides α by the number of tests. It is the strictest.
- *Holm* gives the same guarantee as Bonferroni with a bit more power. It is the default here.
- *Benjamini–Hochberg* controls the *share* of false discoveries rather than the chance of any. It is more lenient
  and suited to screening.

Try it: on **Peak ad hour**, switch from *None* to *Bonferroni*. {hh['n_sig_unadjusted']} "significant" hours drop
to {hh['n_sig_bonferroni']}.

**Whiskers versus fill.** The whiskers are ordinary, unadjusted intervals; the correction only changes the fill.
A hollow dot whose whisker clears 0 means "looks significant on its own, but not once we account for testing many
segments".

**The interaction test (LRT).** A single test per dimension that asks whether the lift differs across segments
*at all*. Because it is one test, there is no multiple-comparison problem, so quote it first. Hour:
{p_eq(hh['lrt']['p_value'])}, {evidence(hh['lrt']['p_value'], ALPHA0, 'most_ads_hour')}. Day:
{p_eq(hd['lrt']['p_value'])}, {evidence(hd['lrt']['p_value'], ALPHA0, 'most_ads_day')}; a single test like that needs
replication before money moves.

**Post-assignment variables.** Peak day, peak hour and total ads were recorded after users were randomized and
reflect how each user behaved. Heavy users see more ads, and their peak hour is when they happen to be online. So
segments built from them are not randomized comparisons: treat any pattern as a hypothesis.

**Dose-response chart.** Conversion rate by number of ads seen, for each arm. The lift (the gap between the bars)
is about zero for light users, large at 51–200 ads, and gone past 200 ads, where there are only {n_top_c:,} PSA
users. The tempting reading is "more ads, more conversions, up to a point". But heavier users differ from light users
in many ways, so this motivates the frequency test in R2; it does not prove that buying more ads would help.

**Common misreadings.**
- "{hd['max_lift_segment']} is the best day, so move budget there." The day effect is weak, and the peak ad day is not
  a slot we bought.
{survivor_bullet}- "Segments with no significant lift don't respond." Small segments simply have wide intervals; absence
  of evidence is not evidence of absence.
""")
