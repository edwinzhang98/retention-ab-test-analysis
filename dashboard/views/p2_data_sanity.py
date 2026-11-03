"""Page 2 · Data & Sanity Checks: data quality, sample ratio mismatch (SRM) and the
balance of post-assignment fields across the ad experiment's arms.

The SRM panel is recomputed live (src.stats.srm_check) for the intended split and
alarm threshold the viewer picks; everything else is read from results.json.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (C, F, S, caveat, how_to_read, load_cache, load_catalog_takeaways, load_results, page_header, show,
                    takeaway)

res = load_results()
dq_m, dq_c = res["data_quality"]["marketing"], res["data_quality"]["cookie"]
ad, gate = res["ad"], res["cookie"]["gate"]
srm_ad, srm_gate = ad["srm"], gate["srm"]

# Two-level SRM rule used in the analysis: p < FAIL_DEFAULT -> FAIL; p < WARN_LINE -> WARNING; else PASS.
FAIL_DEFAULT = float(srm_gate["threshold"])
WARN_LINE = float(srm_gate.get("warn_threshold", 0.01))
THRESHOLDS = sorted({0.0001, FAIL_DEFAULT, 0.01, 0.05})
ROUND_WINDOW_DAYS = 14  # sum_gamerounds counts rounds in each player's first 14 days

plan_ad, plan_gate = srm_ad["intended_share_t"], srm_gate["intended_share_t"]
split_ad = f"{plan_ad * 100:.0f}/{(1 - plan_ad) * 100:.0f}"
split_gate = f"{plan_gate * 100:.0f}/{(1 - plan_gate) * 100:.0f}"
n_ad_users = srm_ad["n_t"] + srm_ad["n_c"]
cramers = [b["cramers_v"] for b in ad["balance"]]


def fmt_p(p: float) -> str:
    return "< 0.0001" if p < 1e-4 else f"{p:.4f}"


def p_is(p: float) -> str:
    """'p = 0.0085' or 'p < 0.0001', for sentences."""
    return "p < 0.0001" if p < 1e-4 else f"p = {p:.4f}"


def table_height(n_rows: int) -> int:
    """Pixel height that shows every row of an st.dataframe without inner scrolling."""
    return 35 * (n_rows + 1) + 3


def dq_table(rows: list[tuple[str, str, str]]) -> None:
    df = pd.DataFrame(rows, columns=["Check", "Result", "Status"])
    st.dataframe(df, hide_index=True, width="stretch", height=table_height(len(df)),
                 column_config={"Check": st.column_config.TextColumn(width=200),
                                "Result": st.column_config.TextColumn(width=620),
                                "Status": st.column_config.TextColumn(width=110)})


# ------------------------------------------------------------------ header
page_header("Data & Sanity Checks", "Can we trust the data and the experiment setup?")

# ------------------------------------------------------------------ 1 · data quality
st.subheader("1 · Data quality")
st.caption("Checks run on the raw files before any analysis. Status: Pass = as expected; Fixed = a cleaning step "
           "was applied; Note = kept as is but worth knowing; Limitation = something the data cannot tell us.")

nulls_m, nulls_c = sum(dq_m["nulls"].values()), sum(dq_c["nulls"].values())
tab_m, tab_c = st.tabs(["Marketing A/B (ad experiment)", "Cookie Cats (retention and gate experiment)"])
with tab_m:
    dq_table([
        ("Row count", f"{dq_m['rows_raw']:,} raw rows, {dq_m['rows_clean']:,} analysed",
         "Pass" if dq_m["rows_raw"] == dq_m["rows_clean"] else "Fixed"),
        ("Primary key (user id)", f"{dq_m['unique_user_id']:,} unique ids, {dq_m['duplicate_user_id']} duplicates",
         "Pass" if dq_m["duplicate_user_id"] == 0 else "Fixed"),
        ("Nulls", f"{nulls_m} missing values across {len(dq_m['nulls'])} columns", "Pass" if nulls_m == 0 else "Note"),
        ("Arms (test group)", ", ".join(dq_m["test_group_values"]), "Pass"),
        ("Converted", ", ".join(dq_m["converted_values"]), "Pass"),
        ("Total ads per user", f"{dq_m['total_ads_min']} to {dq_m['total_ads_max']:,} (median "
         f"{dq_m['total_ads_p50']:.0f}, p99 {dq_m['total_ads_p99']:.0f}, p99.9 {dq_m['total_ads_p999']:,.1f}); "
         f"{dq_m['users_over_1000_ads']} users above 1,000 ads kept", "Note"),
        ("Hour with most ads", f"{dq_m['most_ads_hour_range'][0]} to {dq_m['most_ads_hour_range'][1]}", "Pass"),
        ("Day with most ads", f"{dq_m['most_ads_day_values']} distinct weekdays", "Pass"),
        ("Index column", f"'{', '.join(dq_m['index_column_dropped'])}' (CSV row number) dropped", "Fixed"),
        ("Time coverage", "No dates or timestamps: only the weekday and hour in which a user saw the most ads",
         "Limitation"),
    ])
with tab_c:
    dq_table([
        ("Row count", f"{dq_c['rows_raw']:,} raw rows, {dq_c['rows_clean']:,} analysed "
         f"({dq_c['rows_raw'] - dq_c['rows_clean']} dropped, see below)",
         "Pass" if dq_c["rows_raw"] == dq_c["rows_clean"] else "Fixed"),
        ("Primary key (userid)", f"{dq_c['unique_user_id']:,} unique ids, {dq_c['duplicate_user_id']} duplicates",
         "Pass" if dq_c["duplicate_user_id"] == 0 else "Fixed"),
        ("Nulls", f"{nulls_c} missing values across {len(dq_c['nulls'])} columns", "Pass" if nulls_c == 0 else "Note"),
        ("Arms (version)", ", ".join(dq_c["version_values"]), "Pass"),
        ("Rounds in first 14 days", f"{dq_c['rounds_min']} to {dq_c['rounds_max_raw']:,} raw (median "
         f"{dq_c['rounds_p50']:.0f}, p99 {dq_c['rounds_p99']:.0f}, p99.9 {dq_c['rounds_p999']:,.0f}); "
         f"max {dq_c['rounds_max_clean']:,} after cleaning", "Fixed"),
        ("Players with 0 rounds", f"{dq_c['zero_round_players']:,} installed but never played; kept, they count "
         "as installs in every rate", "Note"),
        ("Back on Day 7 but not Day 1", f"{dq_c['d7_without_d1']:,} players; possible, a player can skip Day 1 "
         "and return on Day 7", "Note"),
        ("Time coverage", "No install dates: only the D1 / D7 flags and a round count over the first 14 days",
         "Limitation"),
    ])

# -------- the one cleaning decision and its sensitivity
st.markdown("**Cleaning decision: one player dropped**")
outliers = dq_c["outliers_dropped"]
top = max(outliers, key=lambda o: o["sum_gamerounds"])
st.markdown(
    f"Player {top['user_id']} ({top['version']}) logged **{top['sum_gamerounds']:,} rounds** in "
    f"{ROUND_WINDOW_DAYS} days, about {top['sum_gamerounds'] / ROUND_WINDOW_DAYS:,.0f} a day; the next-highest player "
    f"has {dq_c['rounds_max_clean']:,}. "
    f"We treat it as a logging error and drop players above {C.GAMEROUNDS_OUTLIER_MAX:,} rounds "
    f"({len(outliers)} {'player' if len(outliers) == 1 else 'players'}). Does that change anything?")

add_t = sum(o["version"] == "gate_40" for o in outliers)
add_c = sum(o["version"] == "gate_30" for o in outliers)
srm_raw = S.srm_check(srm_gate["n_t"] + add_t, srm_gate["n_c"] + add_c, srm_gate["intended_share_t"],
                      threshold=FAIL_DEFAULT)
r_raw, r_clean = dq_c["retention_raw"], dq_c["retention_clean"]
sens = pd.DataFrame([
    ("D1 retention", f"{r_raw['d1'] * 100:.3f}%", f"{r_clean['d1'] * 100:.3f}%",
     f"{(r_clean['d1'] - r_raw['d1']) * 100:+.3f} pp"),
    ("D7 retention", f"{r_raw['d7'] * 100:.3f}%", f"{r_clean['d7'] * 100:.3f}%",
     f"{(r_clean['d7'] - r_raw['d7']) * 100:+.3f} pp"),
    ("Mean rounds per player", f"{dq_c['mean_rounds_raw']:.2f}", f"{dq_c['mean_rounds_clean']:.2f}",
     f"{dq_c['mean_rounds_clean'] - dq_c['mean_rounds_raw']:+.2f}"),
    ("Gate SRM p-value (gate_40 vs gate_30)",
     f"{fmt_p(srm_raw['p_value'])} ({srm_raw['n_t']:,} vs {srm_raw['n_c']:,})",
     f"{fmt_p(srm_gate['p_value'])} ({srm_gate['n_t']:,} vs {srm_gate['n_c']:,})", "same verdict"),
], columns=["Metric", f"With the player ({dq_c['rows_raw']:,})", f"Without it ({dq_c['rows_clean']:,}, used)",
            "Change"])
st.dataframe(sens, hide_index=True, width="stretch", height=table_height(len(sens)),
             column_config={"Metric": st.column_config.TextColumn(width=300)})
max_shift = max(abs(r_clean["d1"] - r_raw["d1"]), abs(r_clean["d7"] - r_raw["d7"])) * 100
shift_txt = "less than 0.01 pp" if max_shift < 0.01 else f"{max_shift:.2f} pp"
takeaway(f"Dropping the player moves D1 and D7 retention by {shift_txt}; only the mean number of rounds changes "
         f"({dq_c['mean_rounds_raw']:.1f} to {dq_c['mean_rounds_clean']:.1f}). The gate's sample-ratio warning holds "
         f"either way ({p_is(srm_raw['p_value'])} with the player, {p_is(srm_gate['p_value'])} without).")

# ------------------------------------------------------------------ 2 · SRM
st.subheader("2 · Sample ratio mismatch (SRM)")
st.markdown(
    "If assignment works as designed, each arm's share of users matches the planned split up to chance. A "
    "chi-square test compares the observed arm sizes with the expected ones. A very small p-value means the split "
    "is off by more than chance, which usually points to a bug in assignment or logging (users lost, duplicated or "
    "moved between arms). The arms may then no longer be comparable, so the result cannot be trusted as is.")

thr = st.radio(
    "Fail threshold (p-value)", THRESHOLDS, index=THRESHOLDS.index(FAIL_DEFAULT), horizontal=True,
    format_func=lambda p: f"p < {p:g}" + (" (project rule)" if p == FAIL_DEFAULT else ""), key="p2_srm_threshold",
    help=f"SRM checks use a strict threshold because the test is run on every experiment and a false alarm stops "
         f"a launch. The project rule fails below {FAIL_DEFAULT:g} and warns between {FAIL_DEFAULT:g} and "
         f"{WARN_LINE:g}.")
warn = max(thr, WARN_LINE)
if warn > thr:
    st.caption(f"Rule in use: p < {thr:g} = FAIL (stop, results not trustworthy); {thr:g} ≤ p < {warn:g} = WARNING "
               f"(investigate assignment, results cannot be certified); p ≥ {warn:g} = PASS.")
else:
    st.caption(f"Rule in use: p < {thr:g} = FAIL (stop, results not trustworthy); otherwise PASS. "
               "There is no warning band at this threshold.")


def srm_panel(n_t: int, n_c: int, share_t: float, name_t: str, name_c: str) -> None:
    """Recompute the SRM test for the chosen split and threshold and render the result."""
    r = S.srm_check(n_t, n_c, share_t, threshold=thr)
    p = r["p_value"]
    status = "FAIL" if p < thr else ("WARNING" if p < warn else "PASS")
    m = st.columns(2)
    m[0].metric("Observed share", f"{r['observed_share_t'] * 100:.2f}%",
                f"in {name_t}; planned {share_t * 100:.1f}%", delta_color="off", delta_arrow="off",
                help="Share of all users in the treatment arm, against the share the experiment was set up with.")
    m[1].metric("p-value", fmt_p(p), f"chi-square {r['chi2']:.2f}", delta_color="off", delta_arrow="off",
                help="Chance of a split at least this uneven if assignment worked as planned. Chi-square: sum over "
                     "both arms of (observed - expected)² / expected; 0 = exactly as planned.")
    counts = pd.DataFrame({"Arm": [name_t, name_c], "Observed users": [n_t, n_c],
                           "Expected users": [round(r["expected_t"]), round(r["expected_c"])]})
    counts["Difference"] = counts["Observed users"] - counts["Expected users"]
    st.dataframe(counts, hide_index=True, width="stretch", height=table_height(2),
                 column_config={c: st.column_config.NumberColumn(format="localized")
                                for c in ("Observed users", "Expected users", "Difference")})
    diff = n_t - round(r["expected_t"])
    planned = f"{share_t * 100:.1f}/{(1 - share_t) * 100:.1f}"
    if status == "PASS":
        st.success(f"**PASS** ({p_is(p)}): the arm sizes are consistent with a planned {planned} split.")
    elif status == "WARNING":
        st.warning(
            f"**WARNING** ({p_is(p)}): below the {warn:g} warning line but above the {thr:g} fail line. "
            f"{name_t} has {diff:+,} users against expectation; a split this uneven would happen by chance only "
            f"{p * 100:.1f}% of the time. This blocks certification: the result stays directional until "
            "assignment is debugged.")
    else:
        st.error(
            f"**FAIL** ({p_is(p)}): {name_t} has {diff:+,} users against expectation. If the plan really was "
            f"{planned}, assignment or logging is broken and the results cannot be trusted until it is fixed.")


col_ad, col_gate = st.columns(2, gap="large")
with col_ad:
    st.markdown("**Ad experiment: ad vs PSA**")
    share_ad = st.number_input(
        "Intended share of users in the ad arm (%)", min_value=1.0, max_value=99.0,
        value=float(srm_ad["intended_share_t"] * 100), step=0.5, format="%.1f", key="p2_srm_share_ad",
        help=f"The planned split is not documented with the data. {plan_ad * 100:.0f}% is inferred from the observed "
             f"share, which is a round number. Try {plan_ad * 100 - 1:.0f}% to see what a mismatch looks like.")
    srm_panel(srm_ad["n_t"], srm_ad["n_c"], share_ad / 100, "ad", "PSA")
    caveat(f"The {split_ad} plan is inferred from the observed split itself, so this check can hardly fail and is "
           "weak evidence. Exposure parity (section 3) is the stronger check for this experiment.")
with col_gate:
    st.markdown("**Gate experiment: gate_40 vs gate_30**")
    share_gate = st.number_input(
        "Intended share of players in gate_40 (%)", min_value=1.0, max_value=99.0,
        value=float(srm_gate["intended_share_t"] * 100), step=0.5, format="%.1f", key="p2_srm_share_gate",
        help=f"A {split_gate} split is the standard design for this kind of test.")
    srm_panel(srm_gate["n_t"], srm_gate["n_c"], share_gate / 100, "gate_40", "gate_30")
    caveat(f"What it means for the decision: the D7 drop under gate_40 "
           f"({gate['retention_7']['abs_lift'] * 100:+.2f} pp) is reported as directional. Keeping gate_30 is the "
           "no-change default, so the recommendation does not depend on certifying it; a re-test does.")

# ------------------------------------------------------------------ 3 · balance
st.subheader("3 · Exposure parity and balance of post-assignment fields")
ga, gp = ad["groups"]["ad"], ad["groups"]["psa"]
e = st.columns(4)
e[0].metric("Mean ads per user, ad arm", f"{ga['mean_ads']:.2f}",
            help="Total ads (ads or PSAs) served per user during the campaign.")
e[1].metric("Mean ads per user, PSA arm", f"{gp['mean_ads']:.2f}",
            help="The PSA arm was served public-service ads in the same slots.")
e[2].metric("Median ads per user", f"{ga['median_ads']:.0f} vs {gp['median_ads']:.0f}", help="Ad arm vs PSA arm.")
e[3].metric("KS distance", f"{ad['total_ads_ks']['stat']:.3f}",
            help="Kolmogorov-Smirnov distance: the biggest vertical gap between the arms' cumulative distributions "
                 "of ads seen (0 = identical, 1 = no overlap). Its p-value is tiny only because n is huge.")
takeaway(f"Both arms were served about the same number of ad slots ({ga['mean_ads']:.1f} vs {gp['mean_ads']:.1f} per "
         "user), so the PSA arm is a like-for-like comparison: same slots, different content. This exposure parity "
         "is the main reason to trust the ad experiment's setup.")

st.markdown("The fields below are recorded *after* assignment: the weekday and hour in which a user saw the most "
            "ads, and how many ads they saw. Their distributions differ slightly between the arms.")

VARS = {
    "Peak ad day": ("most_ads_day", tuple(C.DAY_ORDER), "Day with most ads",
                    "Peak ad day: share of each arm's users (%)", "ad_balance_day"),
    "Peak ad hour": ("most_ads_hour", tuple(range(24)), "Hour with most ads (0-23)",
                     "Peak ad hour: share of each arm's users (%)", None),
    "Total ads seen": ("exposure_bucket", tuple(C.EXPOSURE_LABELS), "Total ads seen (bucket)",
                       "Total ads seen: share of each arm's users (%)", "ad_balance_exposure"),
}


@st.cache_data(show_spinner=False)
def balance_fig(col: str, order: tuple, xtitle: str, title: str):
    users = load_cache("fct_ad_exposure_users")
    return F.fig_balance(users, col, title, "Bars: share of each arm's users in each category. Matching bars mean "
                         "the arms look alike on this field.", order=list(order), xtitle=xtitle)


choice = st.radio("Field", list(VARS), horizontal=True, key="p2_balance_var")
col, order, xtitle, title, catalog_key = VARS[choice]
bal = next(b for b in ad["balance"] if b["variable"] == col)
chart, stats = st.columns([4, 1], gap="medium")
with chart:
    show(balance_fig(col, order, xtitle, title))
with stats:
    st.metric("Cramér's V", f"{bal['cramers_v']:.3f}",
              help="Size of the difference between the arms' distributions: 0 = identical, 1 = completely "
                   "different. Below 0.1 is usually read as negligible.")
    st.metric("Chi-square p-value", fmt_p(bal["p_value"]),
              help=f"Chi-square = {bal['chi2']:.1f} on {bal['df']} degrees of freedom. With {n_ad_users:,} users "
                   "even a tiny difference is 'significant', so read Cramér's V for the size.")
if catalog_key:
    takeaway(load_catalog_takeaways()[catalog_key])
else:
    takeaway(f"Arms differ slightly in peak ad hour (Cramér's V {bal['cramers_v']:.3f}); these are post-assignment "
             "fields, so segment results are exploratory.")
caveat("Post-assignment fields can be shaped by the treatment itself (what a user is shown can change how much and "
       "when they browse). So they are never used as covariates to 'adjust' the lift, the small imbalances are not "
       "evidence of broken randomization, and lift by day, hour or exposure (page 5) is exploratory.")

how_to_read(f"""
**What this page is.** The checks an analyst runs *before* believing any result: is the data complete and clean,
and was the experiment run the way it was designed? If these fail, the later pages do not matter.

**Data quality tables.** One row per check: how many rows, whether each user appears once (the "primary key"),
missing values, whether the values make sense (ranges), and what the data cannot tell us (no dates). "Fixed" rows
are the only places where we changed the data.

**The dropped player.** One player logged {top['sum_gamerounds']:,} rounds in two weeks, which is not humanly
plausible. The small table shows the key numbers with and without that player: retention does not move, so the
decision to drop it does not drive any conclusion.

**Sample ratio mismatch (SRM).** Think of assignment as a weighted coin that should send {plan_ad * 100:.0f}% of users
to ads (or {plan_gate * 100:.0f}% of players to gate_40). With tens or hundreds of thousands of flips, the observed
share should land very close to the plan. The p-value says how surprising the observed split would be if the coin
were fair; a tiny p-value means the coin, or the logging around it, is broken. Use the inputs to change the planned
split or the threshold and the test is recomputed. Try {plan_ad * 100 - 1:.0f}% for the ad arm to see a failure.

**Why the ad experiment's SRM pass is weak.** Nobody documented the planned split; we inferred {split_ad} from the data,
so the check is partly circular. The stronger check is **exposure parity**: both arms were served the same number
of ad slots, so the only planned difference is what the slot showed.

**Balance charts.** For the chosen field, the grey and blue bars show how each arm's users are spread across
categories. Similar bars mean the arms look alike. The p-value is tiny because the sample is huge; **Cramér's V**
measures how big the difference is, and the {min(cramers):.3f} to {max(cramers):.3f} seen here is very small.

**Common misreadings.**
- "p < 0.0001 on the balance test means randomization failed." No: with {n_ad_users:,} users any tiny difference
  is significant, and these fields are measured after assignment anyway.
- "SRM passed, so everything is fine." SRM only checks arm sizes. It cannot catch a bug that keeps sizes right
  but sends different kinds of users to each arm.
- "The gate result is wrong because of the SRM warning." Not necessarily; it means we cannot certify it yet.
""")
