"""Page 1 · Overview: the answers to the Growth PM's questions on one screen.

Everything here is read from reports/results.json (no recomputation), so the
page paints fast; the only live calculation is the breakeven CPM for the
value-per-conversion assumption the viewer types in.
"""
from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from common import (F, fmt_pct, fmt_pp, how_to_read, load_catalog_takeaways, load_results, page_header, show,
                    takeaway)

res = load_results()
dq = res["data_quality"]
ad, ck = res["ad"], res["cookie"]
t, bz = ad["test"], ad["business"]
inc = bz["incremental_conversions"]
gate = ck["gate"]
g7, gsrm = gate["retention_7"], gate["srm"]
plan = ad["srm"]["intended_share_t"]
split = f"{plan * 100:.0f}/{(1 - plan) * 100:.0f}"
psa_share = t["n_c"] / (t["n_t"] + t["n_c"])
p_ad = "p < 0.001" if t["p_value"] < 0.001 else f"p = {t['p_value']:.3f}"
by_rounds = ck["by_rounds_bucket"]
by_d1 = {r["d1_status"]: r for r in ck["by_d1_status"]}

LOW_BUCKETS = ("0", "1-4", "5-14")  # fewer than 15 rounds in the first 14 days
low = [r for r in by_rounds if r["rounds_bucket"] in LOW_BUCKETS]
low_share = sum(r["share_of_players"] for r in low)
low_d7_max = max(r["retention_7"] for r in low)
d7_yes, d7_no = by_d1["Returned Day 1"]["retention_7"], by_d1["Did not return Day 1"]["retention_7"]


def page_link(page: str, label: str) -> None:
    """Link to another page of the app; plain text when this page runs on its own (e.g. in tests)."""
    try:
        st.page_link(page, label=label, icon=":material/arrow_forward:")
    except StreamlitPageNotFoundError:
        st.caption(label)


def ci_pp(lo: float, hi: float) -> str:
    return f"95% CI {lo * 100:.2f} to {hi * 100:.2f} pp"


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
         "to update the breakeven CPM on this page.")
breakeven = {k: x * value / bz["impressions_ad_group"] * 1000 for k, x in inc.items()}

# ------------------------------------------------------------------ KPI rows
st.caption(f"Ad campaign · randomized ad vs PSA test, {t['n_t'] + t['n_c']:,} users")
k = st.columns(4)
k[0].metric(
    "Conversion lift, ad vs PSA", fmt_pp(t["abs_lift"]), ci_pp(t["abs_ci_low"], t["abs_ci_high"]),
    delta_color="off", delta_arrow="off",
    help=f"Conversion rate of users shown ads ({fmt_pct(t['rate_t'])}) minus users shown a public-service ad "
         f"({fmt_pct(t['rate_c'])}). Newcombe 95% interval; two-proportion z-test {p_ad}.")
k[1].metric(
    "Relative lift", f"{t['rel_lift'] * 100:+.0f}%",
    f"95% CI {t['rel_ci_low'] * 100:+.0f}% to {t['rel_ci_high'] * 100:+.0f}%", delta_color="off", delta_arrow="off",
    help="Ad rate divided by PSA rate, minus 1. It looks large because the base rate is small: "
         "the absolute gain is the lift on the left.")
k[2].metric(
    "Incremental conversions", f"{inc['point']:,.0f}", f"95% CI {inc['ci_low']:,.0f} to {inc['ci_high']:,.0f}",
    delta_color="off", delta_arrow="off",
    help=f"Lift × {t['n_t']:,} users in the ad arm: conversions that would not have happened without the ads. "
         f"That is {bz['share_of_ad_conversions_incremental'] * 100:.0f}% of all ad-arm conversions.")
k[3].metric(
    f"Breakeven CPM at USD {value:,.0f}", f"USD {breakeven['point']:,.2f}",
    f"95% CI {breakeven['ci_low']:,.2f} to {breakeven['ci_high']:,.2f}", delta_color="off", delta_arrow="off",
    help=f"Highest price per 1,000 impressions at which the campaign still pays back, if one conversion is worth "
         f"USD {value:,.0f} (an assumption). Incremental conversions × value ÷ "
         f"{bz['impressions_ad_group'] / 1e6:.1f}M impressions × 1,000.")

ov = ck["overall"]
st.caption(f"New players · Cookie Cats, {dq['cookie']['rows_clean']:,} players")
r = st.columns(4)
r[0].metric(
    "D1 retention", fmt_pct(ov["retention_1"], 1),
    f"95% CI {fmt_pct(ov['retention_1_ci_low'], 1)} to {fmt_pct(ov['retention_1_ci_high'], 1)}",
    delta_color="off", delta_arrow="off", help="Share of installs who played again on the day after install.")
r[1].metric(
    "D7 retention", fmt_pct(ov["retention_7"], 1),
    f"95% CI {fmt_pct(ov['retention_7_ci_low'], 1)} to {fmt_pct(ov['retention_7_ci_high'], 1)}",
    delta_color="off", delta_arrow="off", help="Share of installs who played on day 7 after install.")
r[2].metric(
    "Installs with fewer than 15 rounds", f"{low_share * 100:.0f}%", f"D7 at most {low_d7_max * 100:.1f}%",
    delta_color="off", delta_arrow="off",
    help="Players with 0-14 rounds in their first 14 days, and the highest D7 retention among them.")
r[3].metric(
    "gate_40 effect on D7", fmt_pp(g7["abs_lift"]), ci_pp(g7["abs_ci_low"], g7["abs_ci_high"]),
    delta_color="off", delta_arrow="off",
    help=f"D7 retention with the first gate at level 40 minus level 30 ({fmt_pct(g7['rate_t'])} vs "
         f"{fmt_pct(g7['rate_c'])}). Sample-ratio warning (p = {gsrm['p_value']:.4f}): directional until "
         "assignment is checked.")

# ------------------------------------------------------------------ answer cards
st.subheader("Answers to the PM's questions")
row1, row2 = st.columns(2, gap="medium"), st.columns(2, gap="medium")

with row1[0].container(border=True, height="stretch"):
    st.caption("Q1 · Growth PM")
    st.markdown("**Did last quarter's ad campaign drive conversions?**")
    st.badge("Yes: keep it running", color="green")
    st.markdown(
        f"Users shown ads converted at **{fmt_pct(t['rate_t'])}** vs **{fmt_pct(t['rate_c'])}** with the PSA: "
        f"**{fmt_pp(t['abs_lift'])}** ({ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), about "
        f"**{inc['point']:,.0f}** incremental conversions. The arm sizes match the {split} split and both arms saw "
        f"the same number of ads ({ad['groups']['ad']['mean_ads']:.1f} vs {ad['groups']['psa']['mean_ads']:.1f} "
        "per user).")
    st.caption("R1: keep running at the current budget with an always-on 5-10% PSA holdout.")
    page_link("views/p4_experiment_readout.py", "Experiment readout")

with row1[1].container(border=True, height="stretch"):
    st.caption("Q2 · Growth PM")
    st.markdown("**Is it worth doubling the budget?**")
    st.badge("Not answerable yet: test first", color="orange")
    st.markdown(
        "The experiment did not vary budget, so it cannot say what the extra spend would buy. If a conversion is "
        f"worth USD {value:,.0f} (assumed), the current flight pays back below **USD {breakeven['point']:,.2f}** "
        f"CPM. Lift is near zero for users who saw 20 ads or fewer and indistinguishable from zero above 200 "
        f"(exploratory), which hints at saturation.")
    st.caption("R2: run a randomized 2x-budget or frequency-cap test before scaling.")
    page_link("views/p5_heterogeneity.py", "Heterogeneity and exposure")

with row2[0].container(border=True, height="stretch"):
    st.caption("Q3 · Growth PM")
    st.markdown("**Which new users leave first?**")
    st.badge("Players who barely start", color="blue")
    st.markdown(
        f"**{low_share * 100:.0f}%** of installs play fewer than 15 rounds in their first 14 days, and at most "
        f"**{low_d7_max * 100:.1f}%** of them are back on Day 7. "
        f"**{(1 - ck['overall']['retention_1']) * 100:.1f}%** of players never return on Day 1; those who do are "
        f"**{d7_yes / d7_no:.1f}×** as likely to be back on Day 7 ({fmt_pct(d7_yes, 1)} vs {fmt_pct(d7_no, 1)}). "
        "This is correlation, not cause.")
    st.caption("R6: Day-1 onboarding / re-engagement experiment, D7 retention as the primary metric.")
    page_link("views/p3_retention.py", "Retention analysis")

with row2[1].container(border=True, height="stretch"):
    st.caption("Q4 · Game PM (second experiment)")
    st.markdown("**Should the first gate move from level 30 to level 40?**")
    st.badge("No: keep the gate at level 30", color="red")
    st.markdown(
        f"gate_40 lowered D7 retention by **{abs(g7['abs_lift']) * 100:.2f} pp** "
        f"({fmt_pct(g7['rate_t'])} vs {fmt_pct(g7['rate_c'])}; 95% CI {abs(g7['abs_ci_high']) * 100:.2f} to "
        f"{abs(g7['abs_ci_low']) * 100:.2f} pp lower). The arm sizes trigger a sample-ratio warning "
        f"(p = {gsrm['p_value']:.4f}), so the result cannot be certified until assignment is debugged; keeping "
        "level 30 is the safe default either way.")
    st.caption("R5: keep gate_30 and investigate the assignment before any re-test.")
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
         "Can we trust the data? Data quality, sample-ratio checks, balance of the arms."),
        ("views/p3_retention.py", "3 · Retention Analysis",
         "Which new players leave first? Funnel, segments, engagement depth."),
        ("views/p4_experiment_readout.py", "4 · Experiment Readout: Ad vs PSA",
         "Did ads work, by how much, and is it worth the money? CI methods, power, breakeven."),
        ("views/p5_heterogeneity.py", "5 · Heterogeneity by Day / Hour",
         "Does the lift differ by day, hour or exposure, or is it noise? Multiple-comparison corrections."),
        ("views/p6_gate_experiment.py", "6 · Gate Experiment (Cookie Cats)",
         "Should the gate move to level 40? Readout plus the sample-ratio warning."),
        ("views/p7_decision.py", "7 · Decision & Recommendations",
         "Who does what next, how we will measure it, and a sample-size calculator."),
    ):
        page_link(path, label)
        st.caption(desc)

how_to_read(f"""
**What this page is.** The one-screen summary: the headline numbers, the answer to each question the Growth PM
asked, and a link to the page with the evidence. Every number comes from the same analysis run as the report.

**The number cards.** The big number is the best estimate. The grey line under it is the **95% confidence
interval (CI)**: the range of true values that are consistent with the data. When the whole range sits on one side
of zero, the effect is very unlikely to be zero. Hover the small question mark for the exact definition.

**pp vs %.** Going from {fmt_pct(t['rate_c'])} to {fmt_pct(t['rate_t'])} is a gain of
{t['abs_lift'] * 100:.2f} **percentage points (pp)**, which is also a {t['rel_lift'] * 100:.0f}% **relative**
increase. Both are correct. Percentage points are what turn into extra conversions; the relative number looks big
only because the starting rate is small.

**Incremental conversions** are the conversions that happened *because of* the ads: the lift times the number of
users who saw ads. Most conversions in the ad arm ({100 - bz['share_of_ad_conversions_incremental'] * 100:.0f}%)
would have happened anyway, which is why we need the PSA control group at all.

**Breakeven CPM** is the most we could pay per 1,000 ad impressions and still get our money back. It depends on what
one conversion is worth, which this data does not contain, so the value is an **assumption** you can change at the
top right. Compare the breakeven with the CPM we actually pay (Finance has it).

**The bar chart** shows each group's conversion rate; the thin whiskers are the 95% interval for that rate. The PSA
whisker is wider because only {psa_share * 100:.0f}% of users were in the PSA group, so its rate is measured less
precisely.

**Common misreadings.**
- "{t['rel_lift'] * 100:.0f}% lift" does not mean {t['rel_lift'] * 100:.0f}% of users converted. It is a relative
  change on a base rate of {fmt_pct(t['rate_c'])}.
- "Statistically significant" means "unlikely to be zero", not "big" or "profitable".
- The experiment shows the campaign worked at its *current* budget. It says nothing direct about a doubled budget.
- The gate experiment is a different product (a mobile puzzle game, 2017). It is here because it has the retention
  data and a second experiment, not because it is linked to the ad campaign.
""")
