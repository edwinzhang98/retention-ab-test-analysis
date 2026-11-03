"""Page 5 · Heterogeneity: does the ad lift differ by peak day, peak hour, daypart or exposure?

Two questions are kept apart:
  1. Does a segment's lift differ from the other segments'? The heterogeneity
     question: one interaction likelihood-ratio test per dimension (results.json,
     odds scale), then segment-vs-rest contrasts (percentage-point scale: the raw
     difference Lift - Lift, rest, with an Agresti-Caffo CI and p). Primary view.
  2. Is there a lift inside a segment? Mostly a question of sample size, because
     the overall lift is real. Secondary view.
The correction and alpha controls recompute the contrasts live with
src.stats.segment_lifts. Every dimension is recorded after assignment, so the
page is exploratory; the Mantel-Haenszel lift is shown only as a sensitivity check.
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
N_DIMS = int(HET["n_dimensions_explored"])

DIMS = {
    "most_ads_day": dict(label="Peak ad day", noun="day", a_noun="a day", plural="days", prose="days",
                         by="peak day", title="peak ad day", axis="Day with most ads", order=C.DAY_ORDER,
                         catalog="het_day", balance="most_ads_day"),
    "most_ads_hour": dict(label="Peak ad hour", noun="hour", a_noun="an hour", plural="hours", prose="hours",
                          by="peak hour", title="peak ad hour", axis="Hour with most ads (0–23)",
                          order=list(range(24)), catalog="het_hour", balance="most_ads_hour"),
    "daypart": dict(label="Daypart (peak hour, grouped)", noun="daypart", a_noun="a daypart", plural="dayparts",
                    prose="dayparts", by="daypart", title="daypart of peak exposure",
                    axis="Daypart (hour with most ads)", order=C.DAYPART_ORDER, catalog="het_daypart",
                    balance="most_ads_hour"),
    "exposure_bucket": dict(label="Total ads seen (exposure bucket)", noun="bucket", a_noun="a bucket",
                            plural="buckets", prose="exposure buckets", by="exposure", title="total ads seen",
                            axis="Total ads seen (bucket)", order=C.EXPOSURE_LABELS,
                            catalog="het_exposure_forest", balance="exposure_bucket"),
}
CORRECTIONS = {"none": "None (unadjusted)", "bonferroni": "Bonferroni", "holm": "Holm",
               "fdr_bh": "Benjamini–Hochberg (FDR)"}
CORR_SHORT = {"none": "unadjusted", "bonferroni": "Bonferroni", "holm": "Holm", "fdr_bh": "BH"}
DEFAULT_CORRECTION = "holm"
ALPHAS = [0.10, 0.05, 0.01]
QUESTIONS = {"differs": "Does its lift differ from the other segments'? (heterogeneity)",
             "lift": "Is there a lift inside the segment?"}
SMALL_CONTROL = 100  # PSA users per segment below which intervals get very wide


@st.cache_data(show_spinner=False)
def segment_table(dim: str, method: str, alpha: float) -> pd.DataFrame:
    """Per-segment lift, segment-vs-rest contrast and both sets of adjusted p-values (src.stats.segment_lifts)."""
    return S.segment_lifts(load_cache("agg_ad_cells"), dim, "ad", "psa", alpha=alpha, method=method,
                           order=DIMS[dim]["order"])


def conf(alpha: float) -> str:
    return f"{(1 - alpha) * 100:g}%"


def p_text(p: float) -> str:
    """p-value for display: never prints 0, two significant digits above 0.001."""
    if p < 1e-4:
        return "< 0.0001"
    return f"{p:.4f}" if (p < 1e-3 or p > 0.99) else f"{p:.2g}"


def p_eq(p: float) -> str:
    s = p_text(p)
    return f"p {s}" if s.startswith("<") else f"p = {s}"


def seg_name(dim: str, seg) -> str:
    """Segment name for prose (en dash in ranges: '36–50 ads', 'Night (0–5)')."""
    if dim == "most_ads_hour":
        return f"hour {seg}"
    if dim == "exposure_bucket":
        return f"{str(seg).replace('-', '–')} ads"
    return str(seg).replace("-", "–")


def strength(p: float) -> str:
    """Plain-language strength of one interaction test."""
    if p >= 0.10:
        return "no evidence"
    if p >= 0.05:
        return "weak, not significant at 0.05"
    if p >= 0.01:
        return "modest evidence"
    return "evidence" if p >= 0.001 else "strong evidence"


def verb(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def count_out_of(n: int, total: int, cfg: dict) -> str:
    """'8 hours (out of 24)': the count leads, so a bare 'N of 24' (withdrawn wording) never renders."""
    return f"{n} {verb(n, cfg['prose'][:-1], cfg['prose'])} (out of {total})"


def sgn(x: float, nd: int = 2) -> str:
    """Signed number with a true minus sign for prose: +0.95 / −0.74."""
    return f"{x:+.{nd}f}".replace("-", "−")


def hour_ranges(hours) -> str:
    """[0, 1, 2, 4, 5, 6] -> '0–2 and 4–6'."""
    hours = sorted(int(h) for h in hours)
    runs, start = [], None
    for i, h in enumerate(hours):
        start = h if start is None else start
        if i == len(hours) - 1 or hours[i + 1] != h + 1:
            runs.append(f"{start}–{h}" if h != start else f"{h}")
            start = None
    return runs[0] if len(runs) == 1 else ", ".join(runs[:-1]) + " and " + runs[-1]


def kpi(col, label: str, value: str, note: str | None = None, help: str | None = None) -> None:
    col.metric(label, value, delta=note, delta_color="off", delta_arrow="off", help=help)


# ------------------------------------------------------------------ what the interaction tests say
day_holm = segment_table("most_ads_day", DEFAULT_CORRECTION, ALPHA0).set_index("most_ads_day")
hour_holm = segment_table("most_ads_hour", DEFAULT_CORRECTION, ALPHA0)
hd, hh, hp, he = (HET[d] for d in DIMS)
night = hp["night_counts"]["psa"]
day_parts = [f"{s}-peak users {abs(r['diff_vs_rest']) * 100:.2f} pp {'above' if r['diff_vs_rest'] > 0 else 'below'} "
             f"(95% CI {sgn(r['diff_vs_rest_ci_low'] * 100)} to {sgn(r['diff_vs_rest_ci_high'] * 100)})"
             for s, r in ((s, day_holm.loc[s]) for s in hd["segments_differing_holm"])]
# hours whose PSA arm has no conversion at all (0-2 and 4-6: mostly night, but hour 6 is Morning)
zero_hours = hour_holm.loc[hour_holm["conv_c"] == 0, "most_ads_hour"].astype(int).tolist()
ZERO_HOURS = (f"{len(zero_hours)} {verb(len(zero_hours), 'hour', 'hours')} ({hour_ranges(zero_hours)}"
              + (", mostly night)" if sum(h < 6 for h in zero_hours) > len(zero_hours) / 2 else ")")
              if zero_hours else "no hour")
# the day with the largest lift has one of the week's lowest PSA rates: part of its lift is a low control rate
top_day = hd["max_lift_segment"]
top_c = day_holm.loc[top_day]
TOP_DAY_LOW_CONTROL = int((day_holm["rate_c"] < top_c["rate_c"]).sum()) <= 1
TOP_DAY_NOTE = (f"{top_day}'s PSA arm has {int(top_c['n_c']):,} users and {int(top_c['conv_c'])} conversions "
                f"({top_c['rate_c']:.2%}, one of the lowest control rates of the week), so part of {top_day}'s lift "
                "is a low control rate" if TOP_DAY_LOW_CONTROL else "")
TOP_DAY_LOW = f"part of {top_day}'s lift is a low PSA rate ({top_c['rate_c']:.2%})" if TOP_DAY_LOW_CONTROL else ""
# dimension-specific caveats, used in the Step 1 table and in the live takeaways
NIGHT_NOTE = (f"driven by Night (0–5), where PSA has {night['conversions']} conversion among "
              f"{night['users']:,} users; excluding Night, {p_eq(hp['lrt_excluding_night']['p_value'])}")
EXPOSURE_NOTE = ("exposure is recorded after assignment and tracks how active a user is: heavy users respond "
                 "differently, which does not show that more ads cause more lift")
R3_TEST = ("pre-register a test that randomizes the delivery schedule (weekday and time slot, e.g. Tuesday vs. "
           "Thursday delivery)")


def reading_cell(key: str) -> str:
    """The 'Reading' column of the Step 1 table."""
    h = HET[key]
    p = h["lrt"]["p_value"]
    s = strength(p)
    head = s[0].upper() + s[1:]
    if key == "most_ads_day":
        if not day_parts:
            return f"{head}. No day differs from the others after Holm."
        survive = {1: "survives Holm", 2: "both survive Holm"}.get(len(day_parts), "all survive Holm")
        low = (f" {top_day}'s PSA rate is low ({top_c['rate_c']:.2%})." if TOP_DAY_LOW_CONTROL else "")
        return (f"{head}. Lift vs the other days: {', '.join(day_parts)}; {survive}.{low} 'Peak day' describes "
                "the user's habits, not a day we can buy.")
    if key == "most_ads_hour":
        return (f"{head}. No hour differs from the others after correction; {ZERO_HOURS} "
                f"{verb(len(zero_hours), 'has', 'have')} zero PSA conversions. Excluding the Night daypart "
                f"(hours 0–5): {p_eq(h['lrt_excluding_night']['p_value'])}.")
    if key == "daypart":
        lead = f"Looks like {s}, but it is" if p < 0.05 else f"{head};"
        return f"{lead} {NIGHT_NOTE}: no reliable time-of-day pattern."
    return f"{head}, but {EXPOSURE_NOTE}."


def live_reading(key: str, alpha: float) -> str:
    """Reading of the selected dimension's interaction test at the chosen alpha."""
    p = HET[key]["lrt"]["p_value"]
    if p >= alpha:
        return f"not significant at α = {alpha:.2f}"
    text = f"{strength(p)} that the lift differs by {DIMS[key]['by']}"
    if key == "daypart":
        text += f", {NIGHT_NOTE}"
    elif key == "exposure_bucket":
        text += f", but {EXPOSURE_NOTE}"
    return text


def adjusted_for_dims(dim: str) -> str:
    """The interaction p-value allowing for the 3 dimensions explored (Bonferroni over dimensions)."""
    if dim == "daypart":
        return "regroups hour"
    h = HET[dim]
    p = h.get("lrt_p_bonferroni_3_dims", min(1.0, h["lrt"]["p_value"] * N_DIMS))
    return p_text(p)


# ------------------------------------------------------------------ page
page_header("Heterogeneity by Day / Hour",
            "Does the ad work better on some days, hours or exposure levels, and is that real or noise?")

with st.container(border=True):
    st.markdown(
        "**Two different questions, kept apart.**\n\n"
        "1. **Does a segment's lift differ from the other segments'?** This is the heterogeneity question, the one "
        "that could justify re-planning spend. It is answered by one interaction test per dimension, then by "
        "segment-vs-rest contrasts. Main view below.\n"
        f"2. **Is there a lift inside a segment?** The overall lift is real ({T['abs_lift'] * 100:+.2f} pp, "
        f"{p_eq(T['p_value'])}), so this mostly depends on how many users a segment has: it measures sample size, "
        "not heterogeneity. Secondary view.")

c1, c2, c3 = st.columns([1.2, 1.2, 1])
dim = c1.selectbox("Split the lift by", list(DIMS), format_func=lambda d: DIMS[d]["label"], key="p5_dim")
method = c2.selectbox("Multiple-comparison correction", list(CORRECTIONS), format_func=CORRECTIONS.get,
                      index=list(CORRECTIONS).index(DEFAULT_CORRECTION), key="p5_corr",
                      help="How the segment p-values are adjusted for testing many segments at once.")
alpha = c3.radio("Significance level α", ALPHAS, index=ALPHAS.index(ALPHA0) if ALPHA0 in ALPHAS else 1,
                 format_func=lambda a: f"{a:.2f}", horizontal=True, key="p5_alpha")
d = DIMS[dim]
het = HET[dim]
lrt = het["lrt"]

# ---------------------------------------------------------------- step 1: one test per dimension
st.subheader("Step 1 · Does the lift vary at all? One interaction test per dimension")
rows = []
for key, cfg in DIMS.items():
    h = HET[key]
    l_ = h["lrt"]
    name = f"▸ **{cfg['label']}**" if key == dim else cfg["label"]
    rows.append(f"| {name} | {h['n_segments']} | {p_text(l_['p_value'])} | {l_['lr_stat']:.1f} ({l_['df']}) "
                f"| {adjusted_for_dims(key)} | {reading_cell(key)} |")
st.markdown(f"| Dimension | Segments | Interaction p | χ² (df) | Allowing for {N_DIMS} dimensions | Reading |\n"
            "|---|---:|---:|---:|---:|---|\n" + "\n".join(rows))
st.caption("Likelihood-ratio test of ad × segment in a binomial (logit) model, so it asks whether the lift differs "
           "on the odds scale; the segment-vs-rest contrasts in Step 2 are on the percentage-point scale, so the two "
           "need not agree exactly. ▸ marks the dimension selected above. "
           f"'Allowing for {N_DIMS} dimensions' multiplies p by the {N_DIMS} dimensions explored (Bonferroni).")
takeaway(f"Only peak day shows a signal that holds up ({p_eq(hd['lrt']['p_value'])}; "
         f"{p_text(hd['lrt_p_bonferroni_3_dims'])} allowing for the {N_DIMS} dimensions explored). Hour shows none "
         f"({p_eq(hh['lrt']['p_value'])}); the daypart signal comes from one sparse cell "
         f"({p_eq(hp['lrt_excluding_night']['p_value'])} without Night); exposure differs strongly, but it is "
         "recorded after assignment and tracks how active a user is.")

# ---------------------------------------------------------------- step 2: segment by segment
st.subheader(f"Step 2 · Segment by segment: {d['label'].lower()}")
tab = segment_table(dim, method, alpha)
n_seg = len(tab)
n_diff = int(tab["differs_adj"].sum())
n_pos = int(tab["significant_adj"].sum())
expected_fp = n_seg * alpha
corr_phrase = "with no correction" if method == "none" else f"after {CORRECTIONS[method]}"

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Interaction p", p_text(lrt["p_value"]), f"LRT, χ² {lrt['lr_stat']:.1f} on {lrt['df']} df",
    help="Likelihood-ratio test of ad × segment: does the lift differ across segments at all? One test per "
         "dimension, so it is the number to quote before any single segment.")
kpi(k2, "Differ from the rest", f"{n_diff}", f"out of {n_seg} · {CORR_SHORT[method]}, α = {alpha:.2f}",
    help="Segment-vs-rest contrasts: is this segment's lift different from the lift in all other segments? "
         "This is the heterogeneity question.")
kpi(k3, "Expected by chance", f"{expected_fp:.2g}", f"{n_seg} contrasts × {alpha:.2f}",
    help=f"If no segment's lift truly differed from the rest, testing each of the {n_seg} contrasts at α = "
         f"{alpha:.2f} with no correction would flag about {expected_fp:.2g} by chance. Bonferroni and Holm keep "
         "the chance of even one false flag below α; Benjamini–Hochberg keeps the expected share of false flags "
         "below α.")
kpi(k4, "Lift ≠ 0 (secondary)", f"{n_pos}", f"out of {n_seg} · {CORR_SHORT[method]}, α = {alpha:.2f}",
    help="Per-segment test of ad vs PSA. Because the overall lift is real, this count mostly reflects how many "
         "users each segment has, not whether the ad works differently there.")

question = st.radio("Filled markers answer", list(QUESTIONS), format_func=QUESTIONS.get, horizontal=True,
                    key="p5_question")
is_default = method == DEFAULT_CORRECTION and alpha == ALPHA0
labels = {}
if method == "none":   # the builder's default legend says "after correction"
    labels = ({"sig_label": "Lift differs from other segments (unadjusted)"} if question == "differs"
              else {"sig_label": "Lift ≠ 0 (unadjusted)"})
if question == "differs":
    title = (f"Ad lift by {d['title']} (pp, {conf(alpha)} CI; filled = differs from other {d['plural']}, "
             f"{CORR_SHORT[method]})")
    fig = F.fig_lift_forest(tab, dim, title, overall_lift=T["abs_lift"], seg_title=d["axis"],
                            sig_col="differs_adj", **labels)
else:
    title = f"Ad lift by {d['title']} (pp, {conf(alpha)} CI; filled = lift ≠ 0, {CORR_SHORT[method]})"
    fig = F.fig_lift_forest(tab, dim, title, overall_lift=T["abs_lift"], seg_title=d["axis"],
                            sig_col="significant_adj", **labels)
show(fig, key="p5_forest")

reading = live_reading(dim, alpha)
if question == "differs" and is_default:
    takeaway(CAT[d["catalog"]])
elif question == "differs":
    diff = tab[tab["differs_adj"]]
    if diff.empty:
        head = f"No {d['noun']} differs from the other {d['prose']} {corr_phrase} at α = {alpha:.2f}"
    else:
        head = (f"{count_out_of(len(diff), n_seg, d)} {verb(len(diff), 'differs', 'differ')} from the others "
                f"{corr_phrase} at α = {alpha:.2f}")
        if len(diff) <= 3:
            head += ": " + ", ".join(f"{seg_name(dim, s)} ({sgn(x * 100)} pp vs the rest)"
                                     for s, x in zip(diff[dim], diff["diff_vs_rest"]))
    takeaway(f"{head}. With no correction about {expected_fp:.2g} of {n_seg} contrasts would be flagged by chance if "
             f"none truly differed. Interaction test {p_eq(lrt['p_value'])}: {reading}.")
else:
    takeaway(f"{count_out_of(n_pos, n_seg, d)} {verb(n_pos, 'shows', 'show')} a lift ≠ 0 {corr_phrase} at "
             f"α = {alpha:.2f}. Because the overall lift is real, these per-segment tests mostly measure sample size: "
             f"{d['a_noun']} without a significant lift is often just a small one, and a significant one need not "
             f"differ from the rest. Whether {d['prose']} differ is the other view ({n_diff} out of {n_seg} "
             f"{corr_phrase}).")

small = tab[(tab["n_c"] < SMALL_CONTROL) | (tab["conv_c"] == 0)]
v = BALANCE[d["balance"]]["cramers_v"]
v_note = f"Cramér's V {v:.3f}" + (" for the hour it is built from" if dim == "daypart" else "")
note_small = ""
if len(small):
    seg_list = ", ".join(seg_name(dim, s) for s in small[dim])
    note_small = (f" {len(small)} of {n_seg} {d['prose']} ({seg_list}) have fewer than {SMALL_CONTROL} PSA users or no "
                  "PSA conversions at all, so their intervals are very wide. The contrasts' intervals and p-values use "
                  "Agresti–Caffo adjusted rates (+1 conversion and +1 non-conversion per group), so an empty cell "
                  "cannot create a false difference; their point estimate is the raw difference, so in these cells "
                  "the interval is not centred on it.")
day_note = f" {TOP_DAY_NOTE}." if dim == "most_ads_day" and TOP_DAY_NOTE else ""
caveat(f"<b>Exploratory, not a randomized comparison.</b> {d['label']} is recorded after assignment and its mix "
       f"differs slightly between arms ({v_note}). It describes how users behaved, not a slot we bought, so a "
       f"pattern here is a hypothesis for a pre-registered test, not a reason to move budget.{day_note}{note_small}")

with st.expander(f"Segment table: all {n_seg} {d['prose']} ({CORR_SHORT[method]}, α = {alpha:.2f})"):
    show_tab = pd.DataFrame({
        d["noun"].capitalize(): tab[dim].astype(str),
        "Ad users": tab["n_t"], "PSA users": tab["n_c"], "PSA conv.": tab["conv_c"],
        "Lift": tab["abs_lift"] * 100,
        "Lift, rest": tab["lift_rest"] * 100,
        "Diff. vs rest": tab["diff_vs_rest"] * 100,
        "CI centre (adjusted)": tab["diff_vs_rest_ac"] * 100,
        "CI low": tab["diff_vs_rest_ci_low"] * 100,
        "CI high": tab["diff_vs_rest_ci_high"] * 100,
        "Adj. p": tab["p_vs_rest_adj"],
        "Differs": np.where(tab["differs_adj"], "Yes", "No"),
        "Adj. p, lift ≠ 0": tab["p_adj"],
        "Lift ≠ 0": np.where(tab["significant_adj"], "Yes", "No"),
    })
    signed = st.column_config.NumberColumn(format="%+.2f")
    pcol = st.column_config.NumberColumn(format="%.4f")
    st.dataframe(show_tab, hide_index=True, width="stretch",
                 column_config={"Ad users": st.column_config.NumberColumn(format="localized"),
                                "PSA users": st.column_config.NumberColumn(format="localized"),
                                "Lift": signed, "Lift, rest": signed, "Diff. vs rest": signed,
                                "CI centre (adjusted)": signed, "CI low": signed, "CI high": signed, "Adj. p": pcol,
                                "Adj. p, lift ≠ 0": pcol})
    st.caption(f"Lift, Lift, rest and Diff. vs rest in pp. Diff. vs rest is the raw difference, Lift − Lift, rest: "
               f"this {d['noun']}'s lift minus the lift in all other {d['prose']}. Its {conf(alpha)} interval and "
               "'Adj. p' use Agresti–Caffo adjusted rates (+1 conversion and +1 non-conversion per group), so in "
               "sparse cells the interval is not centred on the point; 'CI centre (adjusted)' shows its centre (pp). "
               "These contrasts are on the percentage-point "
               "scale; the Step 1 interaction test is on the odds scale. 'Adj. p' and 'Differs' answer the "
               "heterogeneity question, the last two columns the lift ≠ 0 question. Adjusted p-values use the "
               f"selected correction across the {n_seg} {d['prose']}.")

# ---------------------------------------------------------------- sensitivity: standardized lift
st.subheader("Sensitivity check: is the headline an artifact of the segment mix?")
crude = T["abs_lift"] * 100
mh = {key: HET[key]["sensitivity_stratified"]["mh_risk_diff"] * 100 for key in DIMS}
sens = pd.DataFrame({"Lift standardized over": [DIMS[k]["label"] for k in DIMS],
                     "Standardized lift (pp)": list(mh.values()),
                     "Crude lift (pp)": [crude] * len(mh),
                     "Difference (pp)": [x - crude for x in mh.values()]})
st.dataframe(sens, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%+.2f")
                            for c in ("Standardized lift (pp)", "Crude lift (pp)", "Difference (pp)")})
takeaway(f"Re-weighting the lift within segments (Mantel–Haenszel) gives {min(mh.values()):.2f}–"
         f"{max(mh.values()):.2f} pp against {crude:.2f} pp crude: the slightly different mix of segments across arms "
         "does not explain the headline, and no split reverses it. This is a sensitivity check on post-assignment "
         "strata, not an adjusted estimate to report.")

# ---------------------------------------------------------------- exposure
st.subheader("Exposure: where the lift lives")
con = he["concentration"]
le20, b2135 = con["le_20_ads_pooled"], con["bucket_21_35"]
by_bucket = con["incremental_conversions_by_bucket"]
negative = [b.replace("-", "–") for b, x in by_bucket.items() if x < 0]
expo = segment_table("exposure_bucket", DEFAULT_CORRECTION, ALPHA0)
e1, e2, e3, e4 = st.columns(4)
kpi(e1, "Users with ≤ 20 ads", f"{con['share_users_le_20_ads']:.0%}",
    f"lift {sgn(le20['abs_lift'] * 100)} pp: none measurable",
    help=f"Share of all users who saw 20 ads or fewer. Pooled, their lift is {sgn(le20['abs_lift'] * 100)} pp "
         f"(95% CI {sgn(le20['abs_ci_low'] * 100)} to {sgn(le20['abs_ci_high'] * 100)}) on a "
         f"{le20['rate_c']:.2%} PSA base: no lift we could measure.")
kpi(e2, "21–35 ads: inconclusive", f"{sgn(b2135['abs_lift'] * 100)} pp",
    f"95% CI {sgn(b2135['abs_ci_low'] * 100)} to {sgn(b2135['abs_ci_high'] * 100)}",
    help=f"The next {b2135['share_ad_users']:.0%} of ad users. The interval is too wide to say whether they respond.")
kpi(e3, "Lift share, 36–200 ads", f"{con['share_incremental_conversions_36_200']:.0%}",
    f"from {con['share_ad_users_36_200']:.0%} of ad users",
    help=f"Bucket-by-bucket incremental conversions (each bucket's lift × its ad users, against its own PSA rate): "
         f"{con['incremental_conversions_36_200']:,.0f} of {con['incremental_conversions_bucketwise_total']:,.0f} come "
         "from the 36–50, 51–100 and 101–200 buckets. This bucket total differs from the headline "
         f"{AD['business']['incremental_conversions']['point']:,.0f}"
         + (f", and buckets {' and '.join(negative)} are slightly negative." if negative else "."))
kpi(e4, "PSA rate, 200+ vs 1–5",
    f"{con['control_rate_highest_bucket'] / con['control_rate_lowest_bucket']:.0f}×",
    f"{con['control_rate_lowest_bucket']:.1%} → {con['control_rate_highest_bucket']:.1%}",
    help="Even users who never saw the campaign convert far more often when they see many PSAs: exposure tracks "
         "how active a user is, not just ad pressure.")
show(F.fig_dose_response(expo, "Conversion rate by total ads seen, ad vs PSA (%)"), key="p5_dose")
takeaway(CAT["het_exposure"])
caveat("<b>The lift lives in heavy users; this is not a frequency curve.</b> Total ads seen is recorded after "
       "assignment and tracks how active a user is, so the chart mixes who the user is with what the ads did. It "
       "cannot say what more impressions or a bigger budget would buy, and it cannot show where extra exposure stops "
       f"paying: the 200+ bucket is too small to read ({con['top_bucket_control_users']:,} PSA users, lift CI "
       f"{sgn(con['top_bucket_ci_pp'][0], 1)} to {sgn(con['top_bucket_ci_pp'][1], 1)} pp). It is the hypothesis for "
       "R2's user-level test (up to 2× today's impressions per user, or a frequency cap).")

with st.container(border=True):
    st.markdown(
        "**What this means for the plan**\n\n"
        f"- **R3 · Media buyer:** don't re-plan spend by day or hour. The day signal is modest "
        f"({p_eq(hd['lrt']['p_value'])}; {p_text(hd['lrt_p_bonferroni_3_dims'])} allowing for {N_DIMS} dimensions) and "
        "describes users' habits, not a slot we can buy"
        + (f"; {TOP_DAY_LOW}" if TOP_DAY_LOW else "")
        + f". Hour shows no evidence ({p_eq(hh['lrt']['p_value'])}) and dayparts no reliable pattern "
        f"({p_eq(hp['lrt_excluding_night']['p_value'])} without the sparse Night cell). If timing matters, "
        f"{R3_TEST}.\n"
        "- **R2 · Growth PM + media buyer:** don't double the budget blindly; test it. This experiment did not vary "
        "spend, so it cannot say what extra budget buys, and the lift lives in heavy users "
        f"({con['share_incremental_conversions_36_200']:.0%} of the bucket-by-bucket incremental conversions come from "
        f"the {con['share_ad_users_36_200']:.0%} of ad users who saw 36–200 ads). Run a user-level test where "
        "one arm gets up to 2× today's impressions per user (the closest stand-in for 2× budget) or a frequency cap, "
        "with users tiered by activity measured *before* the test (a true budget test needs a geo split), and read "
        "out incremental conversions per extra USD 1K spent.")

day_counts, hour_counts = set(hd["differs_from_rest"].values()), set(hh["differs_from_rest"].values())
try_day = (f"on **Peak ad day**, {' and '.join(hd['segments_differing_holm'])} differ from the other days under every "
           f"correction at α = {ALPHA0:.2f}" if len(day_counts) == 1 and hd["segments_differing_holm"]
           else f"on **Peak ad day**, compare the corrections ({hd['differs_from_rest']['none']} days differ "
                f"unadjusted, {hd['differs_from_rest']['holm']} after Holm)")
try_hour = ("on **Peak ad hour**, no hour differs from the rest under any correction" if hour_counts == {0}
            else f"on **Peak ad hour**, {hh['differs_from_rest']['holm']} hours differ from the rest after Holm")
how_to_read(f"""
**Two questions.** "Is there a lift on Tuesday?" and "Is Tuesday's lift different from the other days'?" sound alike
but are different tests. Because the ad works overall, most segments with enough users show a lift, and small
segments don't: counting "significant" segments measures sample size, not heterogeneity. Only the second question
(does a segment differ from the rest?) can justify treating segments differently.

**Step 1, the interaction test.** One likelihood-ratio test per dimension asks whether the lift differs across its
segments *at all*. Quote it before any single segment. We explored {N_DIMS} dimensions (day, hour, exposure; daypart
only regroups hour), so a p-value near 0.05 should be read against a stricter bar: day's
{p_text(hd['lrt']['p_value'])} becomes {p_text(hd['lrt_p_bonferroni_3_dims'])} after allowing for that. The test
works on the odds scale (a logistic model), while the segment-vs-rest contrasts work in percentage points, so the
two can disagree a little at the margin.

**Step 2, the forest plot.** One row per segment. The dot is the lift in that segment, the horizontal line its
confidence interval, the solid vertical line "no effect" and the dotted blue line the overall lift. In the main view a
**filled** dot means the segment's lift differs from the other segments' after the selected correction; a **hollow**
dot means it does not. Switch "Filled markers answer" to see the secondary question instead (lift ≠ 0).

**Why corrections matter.** If no segment truly differed, testing {hh['n_segments']} hours at α = {ALPHA0:.2f} would
still flag about {hh['n_segments'] * ALPHA0:.1f} segment-vs-rest contrasts by chance ({hh['n_segments']} ×
{ALPHA0:.2f}).
- *Bonferroni* divides α by the number of tests. It is the strictest.
- *Holm* gives the same guarantee as Bonferroni with a bit more power. It is the default here.
- *Benjamini–Hochberg* controls the *share* of false discoveries rather than the chance of any. It is more lenient
  and suited to screening.

Try it: {try_day}; {try_hour}; on **Total ads seen**, {he['differs_from_rest']['none']} buckets differ with no
correction and {he['differs_from_rest']['bonferroni']} after Bonferroni.

**Whiskers versus fill.** The whiskers are the ordinary interval for the segment's own lift; the correction only
changes the fill. The difference from the other segments, with its own interval, is in the segment table: the point
is the raw difference (Lift − Lift, rest), while its interval and p-value add one conversion and one non-conversion to
each group (Agresti–Caffo), so a segment with no PSA conversions cannot look infinitely precise. In such sparse
segments the interval is therefore not centred on the point.

**Sensitivity check.** The Mantel–Haenszel lift re-weights the lift within segments. If it were far from the crude
lift (or flipped sign, Simpson's paradox), the uneven segment mix would matter. It doesn't. The segments are
post-assignment, so this is a check, not a better estimate.

**Post-assignment variables.** Peak day, peak hour and total ads were recorded after users were randomized and
reflect how each user behaved. Heavy users see more ads, and their peak hour is when they happen to be online. So
segments built from them are not randomized comparisons: treat any pattern as a hypothesis.

**Exposure chart.** Conversion rate by number of ads seen, for each arm; the lift is the gap between the bars. Even
PSA users convert more when they see more PSAs, so exposure mostly sorts users by how active they are.

**Common misreadings.**
- "{top_day} has the biggest lift, so move budget there." The peak ad day is a user habit recorded after
  assignment, not a slot we bought{', and ' + TOP_DAY_LOW if TOP_DAY_LOW else ''}.
  If timing matters, {R3_TEST}.
- "Hour X has a significant lift and hour Y doesn't, so hours differ." Both statements are about sample size; the
  contrasts (and the interaction test) say hours do not differ.
- "Night is where the ad works best." The Night estimate rests on {night['conversions']} PSA conversion among
  {night['users']:,} users.
- "Users with {he['max_lift_segment'].replace('-', '–')} ads have a {he['max_lift_pp']:.0f} pp lift, so show everyone
  more ads."
  Those users are different people (far more active), not the same people with more ads.
""")

# ---------------------------------------------------------------- phones
# A wide markdown table scrolls inside itself instead of pushing the whole page sideways; the Step 1
# table's reading column is prose, so it keeps a readable width.
st.markdown("<style>@media (max-width: 640px) {"
            "[data-testid='stMarkdownContainer'] table {display: block; overflow-x: auto; max-width: 100%;}"
            "[data-testid='stMarkdownContainer'] th, [data-testid='stMarkdownContainer'] td {min-width: 4.5rem;}"
            "[data-testid='stMarkdownContainer'] td:first-child {min-width: 8rem;}"
            "[data-testid='stMarkdownContainer'] td:last-child {min-width: 16rem;}"
            "}</style>", unsafe_allow_html=True)
