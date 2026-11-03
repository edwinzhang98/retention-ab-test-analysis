"""Page 2 · Data & Sanity Checks: data quality, sample ratio mismatch (SRM), where the
gate experiment's imbalance sits, and exposure parity in the ad experiment.

The SRM panels are recomputed live (src.stats.srm_check, src.stats.quota_exactness)
for the intended split and alarm threshold the viewer picks; the gate strata reuse
the same rule. Everything else is read from results.json or the cached tables.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from common import (C, F, S, caveat, how_to_read, load_cache, load_catalog_takeaways, load_results, page_header, show,
                    takeaway)

res = load_results()
dq_m, dq_c = res["data_quality"]["marketing"], res["data_quality"]["cookie"]
ad, gate = res["ad"], res["cookie"]["gate"]
srm_ad, srm_gate = ad["srm"], gate["srm"]   # gate SRM uses raw assignment counts (before cleaning)

# Two-level SRM rule used in the analysis: p < FAIL_DEFAULT -> FAIL; p < WARN_LINE -> WARNING; else PASS.
FAIL_DEFAULT = float(srm_gate["threshold"])
WARN_LINE = float(srm_gate["warn_threshold"])
THRESHOLDS = sorted({0.0001, FAIL_DEFAULT, WARN_LINE, 0.05})
ROUND_WINDOW_DAYS = 14  # sum_gamerounds counts rounds in each player's first 14 days

plan_ad, plan_gate = srm_ad["intended_share_t"], srm_gate["intended_share_t"]
split_ad = f"{plan_ad * 100:.0f}/{(1 - plan_ad) * 100:.0f}"
split_gate = f"{plan_gate * 100:.0f}/{(1 - plan_gate) * 100:.0f}"
n_ad_users = srm_ad["n_t"] + srm_ad["n_c"]
cramers = [b["cramers_v"] for b in ad["balance"]]


def fmt_p(p: float) -> str:
    """p-value for tables and metrics: never 0."""
    return "< 0.0001" if p < 1e-4 else f"{p:.4f}"


def p_txt(p: float) -> str:
    """p-value for sentences: never 0, two significant digits ('p = 0.0086', 'p = 0.81')."""
    if p < 1e-4:
        return "p < 0.0001"
    if p < 1e-3 or p >= 0.995:
        return f"p = {p:.4f}"
    return f"p = {p:.2g}"


def table_height(n_rows: int) -> int:
    """Pixel height that shows every row of an st.dataframe without inner scrolling."""
    return 35 * (n_rows + 1) + 3


def dq_table(rows: list[tuple[str, str, str]]) -> None:
    df = pd.DataFrame(rows, columns=["Check", "Result", "Status"])
    st.dataframe(df, hide_index=True, width="stretch", height=table_height(len(df)),
                 column_config={"Check": st.column_config.TextColumn(width=210),
                                "Result": st.column_config.TextColumn(width=640),
                                "Status": st.column_config.TextColumn(width=100)})


def page_link(page: str, label: str) -> None:
    """Link to another page of the app; nothing when this page runs on its own (e.g. in tests)."""
    try:
        st.page_link(page, label=label, icon=":material/arrow_forward:")
    except StreamlitPageNotFoundError:
        pass


@st.cache_data(show_spinner=False)
def zero_round_flags() -> dict:
    """Players with 0 rounds whose D1 / D7 flags are set (cleaned player table)."""
    p = load_cache("fct_game_players")
    z = p["sum_gamerounds"] == 0
    return {"d1": int((z & p["retention_1"]).sum()), "d7": int((z & p["retention_7"]).sum()), "players": len(p)}


# ------------------------------------------------------------------ header
page_header("Data & Sanity Checks", "Can we trust the data and the experiment setup?")

# ------------------------------------------------------------------ 1 · data quality
st.subheader("1 · Data quality")
st.caption("Checks run on the raw files before any analysis. Status: Pass = as expected; Fixed = a cleaning step "
           "was applied; Note = kept as is but worth knowing; Limitation = something the data cannot tell us.")

nulls_m, nulls_c = sum(dq_m["nulls"].values()), sum(dq_c["nulls"].values())
zf = zero_round_flags()
tab_m, tab_c = st.tabs(["Marketing A/B (ad experiment)", "Cookie Cats (retention and gate experiment)"])
with tab_m:
    dq_table([
        ("Row count", f"{dq_m['rows_raw']:,} raw rows, {dq_m['rows_clean']:,} analysed",
         "Pass" if dq_m["rows_raw"] == dq_m["rows_clean"] else "Fixed"),
        ("Primary key (user id)", f"{dq_m['unique_user_id']:,} unique ids, {dq_m['duplicate_user_id']} duplicates",
         "Pass" if dq_m["duplicate_user_id"] == 0 else "Fixed"),
        ("Nulls", f"{nulls_m} missing values across {len(dq_m['nulls'])} columns", "Pass" if nulls_m == 0 else "Note"),
        ("Arms (test group)", ", ".join(dq_m["test_group_values"]), "Pass"),
        ("Arm sizes", f"{srm_ad['n_t']:,} ad / {srm_ad['n_c']:,} PSA = {srm_ad['observed_share_t'] * 100:.3f}% / "
         f"{(1 - srm_ad['observed_share_t']) * 100:.3f}%: exactly on a {split_ad} target (section 2)", "Note"),
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
        ("Retention flags", "retention_1 / retention_7 = played on day 1 / day 7 after install (classic D1 / D7, "
         "not rolling: a player who skips day 7 counts as not retained)", "Note"),
        ("Rounds in first 14 days", f"{dq_c['rounds_min']} to {dq_c['rounds_max_raw']:,} raw (median "
         f"{dq_c['rounds_p50']:.0f}, p99 {dq_c['rounds_p99']:.0f}, p99.9 {dq_c['rounds_p999']:,.0f}); "
         f"max {dq_c['rounds_max_clean']:,} after cleaning. The 14-day window overlaps the Day-7 flag", "Fixed"),
        ("Players with 0 rounds", f"{dq_c['zero_round_players']:,} installed but never played; kept, they count "
         "as installs in every rate", "Note"),
        ("0-round players flagged as back", f"{zf['d1']} players with 0 rounds are flagged as back on Day 1 "
         f"({zf['d7']} on Day 7): the flags mean 'came back to the game', not 'played a round'. "
         f"{zf['d1'] / zf['players'] * 100:.1f}% of players; no conclusion depends on it", "Note"),
        ("Back on Day 7 but not Day 1", f"{dq_c['d7_without_d1']:,} players; possible, a player can skip Day 1 "
         "and return on Day 7", "Note"),
        ("Time coverage", "No install dates: one install cohort, with the D1 / D7 flags and a round count over the "
         "first 14 days", "Limitation"),
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

r_raw, r_clean = dq_c["retention_raw"], dq_c["retention_clean"]
sens = pd.DataFrame([
    ("D1 retention", f"{r_raw['d1'] * 100:.3f}%", f"{r_clean['d1'] * 100:.3f}%",
     f"{(r_clean['d1'] - r_raw['d1']) * 100:+.3f} pp"),
    ("D7 retention", f"{r_raw['d7'] * 100:.3f}%", f"{r_clean['d7'] * 100:.3f}%",
     f"{(r_clean['d7'] - r_raw['d7']) * 100:+.3f} pp"),
    ("Mean rounds per player", f"{dq_c['mean_rounds_raw']:.2f}", f"{dq_c['mean_rounds_clean']:.2f}",
     f"{dq_c['mean_rounds_clean'] - dq_c['mean_rounds_raw']:+.2f}"),
], columns=["Metric", f"With the player ({dq_c['rows_raw']:,})", f"Without it ({dq_c['rows_clean']:,}, used)",
            "Change"])
st.dataframe(sens, hide_index=True, width="stretch", height=table_height(len(sens)),
             column_config={"Metric": st.column_config.TextColumn(width=300)})
max_shift = max(abs(r_clean["d1"] - r_raw["d1"]), abs(r_clean["d7"] - r_raw["d7"])) * 100
shift_txt = "less than 0.01 pp" if max_shift < 0.01 else f"{max_shift:.2f} pp"
takeaway(f"Dropping the player moves D1 and D7 retention by {shift_txt}; only the mean number of rounds changes "
         f"({dq_c['mean_rounds_raw']:.1f} to {dq_c['mean_rounds_clean']:.1f}).")
cleaned = S.srm_check(gate["players"]["gate_40"], gate["players"]["gate_30"], plan_gate, FAIL_DEFAULT, WARN_LINE)
st.caption(f"The gate experiment's sample-ratio check (section 2) uses the raw assignment counts, this player "
           f"included ({srm_gate['n_c']:,} gate_30 players), because assignment happens before any cleaning. "
           f"Without the player it would be {p_txt(cleaned['p_value'])}: the same verdict.")

# ------------------------------------------------------------------ 2 · SRM
st.subheader("2 · Sample ratio mismatch (SRM)")
st.markdown(
    "If assignment works as designed, each arm's share of users matches the planned split up to chance. A "
    "chi-square test compares the observed arm sizes with the planned ones. A very small p-value means the split "
    "is off by more than chance, which usually points to a bug in assignment or logging (users lost, duplicated or "
    "moved between arms). The arms may then no longer be comparable, so the result cannot be trusted as is. The "
    "opposite can also happen: a split that lands *exactly* on target is what a quota looks like, and then the "
    "test has nothing to detect.")

thr = st.radio(
    "Fail threshold (p-value)", THRESHOLDS, index=THRESHOLDS.index(FAIL_DEFAULT), horizontal=True,
    format_func=lambda p: f"p < {p:g}" + (" (project rule)" if p == FAIL_DEFAULT else ""), key="p2_srm_threshold",
    help=f"SRM checks use a strict threshold because the test is run on every experiment and a false alarm stops "
         f"a launch. The project rule fails below {FAIL_DEFAULT:g} (the convention in Kohavi et al.) and warns "
         f"between {FAIL_DEFAULT:g} and {WARN_LINE:g} (a project convention).")
warn = max(thr, WARN_LINE)
if warn > thr:
    st.caption(f"Rule in use: p < {thr:g} = FAIL (stop, results not trustworthy); {thr:g} ≤ p < {warn:g} = WARNING "
               f"(investigate assignment, results cannot be certified); p ≥ {warn:g} = PASS.")
else:
    st.caption(f"Rule in use: p < {thr:g} = FAIL (stop, results not trustworthy); otherwise PASS. "
               "There is no warning band at this threshold.")


def srm_status(p: float) -> str:
    return "FAIL" if p < thr else ("WARNING" if p < warn else "PASS")


def srm_panel(n_t: int, n_c: int, share_t: float, name_t: str, name_c: str, unit: str) -> None:
    """Recompute the SRM test and the distance from the planned count for the chosen split and threshold."""
    r = S.srm_check(n_t, n_c, share_t, threshold=thr, warn_threshold=warn)
    q = S.quota_exactness(n_t, n_c, share_t)
    p, dev, sd = r["p_value"], q["deviation_users"], q["sd_users_under_random_assignment"]
    status = srm_status(p)
    m = st.columns(2)
    m[0].metric("Observed share", f"{r['observed_share_t'] * 100:.2f}%",
                f"in {name_t}; planned {share_t * 100:.1f}%", delta_color="off", delta_arrow="off",
                help="Share of all users in the treatment arm, against the share the experiment was set up with.")
    m[1].metric("p-value", fmt_p(p), f"chi-square {r['chi2']:.2f}", delta_color="off", delta_arrow="off",
                help="Chance of a split at least this uneven if assignment worked as planned. Chi-square: sum over "
                     "both arms of (observed - planned)² / planned; 0 = exactly as planned.")
    counts = pd.DataFrame({
        "Arm": [name_t, name_c],
        f"Observed {unit}": [f"{n_t:,}", f"{n_c:,}"],
        f"Planned {unit}": [f"{r['expected_t']:,.2f}", f"{r['expected_c']:,.2f}"],
        "Difference": [f"{n_t - r['expected_t']:+,.2f}", f"{n_c - r['expected_c']:+,.2f}"],
    })
    st.dataframe(counts, hide_index=True, width="stretch", height=table_height(2),
                 column_config={c: st.column_config.TextColumn(alignment="right") for c in counts.columns[1:]})
    st.caption(f"Typical chance gap under random assignment: ±{sd:,.0f} {unit} (one standard deviation of the "
               f"binomial count); observed gap {dev:+,.2f} ({abs(dev) / sd:.2g} SD).")
    planned = f"{share_t * 100:.1f}/{(1 - share_t) * 100:.1f}"
    if status == "PASS" and q["is_nearest_integer_to_target"]:
        st.info(
            f"**PASS, but uninformative** ({p_txt(p)}). {n_t:,} is the nearest whole number to exactly "
            f"{share_t * 100:.1f}% of {n_t + n_c:,} {unit} ({abs(dev):.2f} off). Random assignment would typically "
            f"miss the planned count by about {sd:,.0f} {unit}, and lands on the nearest whole number only "
            f"{q['prob_exactly_nearest_integer'] * 100:.2f}% of the time. So the split was set by a quota (or the "
            "export was trimmed to it): the test passes by construction and cannot detect an assignment problem.")
    elif status == "PASS":
        st.success(f"**PASS** ({p_txt(p)}): the arm sizes are consistent with a planned {planned} split "
                   f"({abs(dev) / sd:.1f} SD from the planned count).")
    elif status == "WARNING":
        st.warning(
            f"**WARNING** ({p_txt(p)}): below the {warn:g} warning line but above the {thr:g} fail line. "
            f"{name_t} has {dev:+,.1f} {unit} against the planned count, {abs(dev) / sd:.1f} times the typical chance "
            f"gap; a split at least this uneven happens by chance {p * 100:.1f}% of the time. The result cannot be "
            "certified until assignment is checked.")
    else:
        st.error(
            f"**FAIL** ({p_txt(p)}): {name_t} has {dev:+,.1f} {unit} against the planned count "
            f"({abs(dev) / sd:.1f} SD). If the plan really was {planned}, assignment or logging is broken and the "
            "results cannot be trusted until it is fixed.")


col_ad, col_gate = st.columns(2, gap="large")
with col_ad:
    st.markdown("**Ad experiment: ad vs PSA**")
    share_ad = st.number_input(
        "Intended share of users in the ad arm (%)", min_value=1.0, max_value=99.0,
        value=float(plan_ad * 100), step=0.5, format="%.1f", key="p2_srm_share_ad",
        help=f"The planned split is not documented with the data; {plan_ad * 100:.0f}% is inferred from the observed "
             f"share, which is a round number. Try {plan_ad * 100 - 1:.0f}% to see what a mismatch looks like.")
    srm_panel(srm_ad["n_t"], srm_ad["n_c"], share_ad / 100, "ad", "PSA", "users")
    caveat(f"Uninformative, not reassuring: the {split_ad} plan is inferred from the data, and the observed split "
           "hits it to the nearest user. Exposure parity (section 3) is the meaningful check for this experiment.")
with col_gate:
    st.markdown("**Gate experiment: gate_40 vs gate_30**")
    share_gate = st.number_input(
        "Intended share of players in gate_40 (%)", min_value=1.0, max_value=99.0,
        value=float(plan_gate * 100), step=0.5, format="%.1f", key="p2_srm_share_gate",
        help=f"A {split_gate} split is the standard design for this kind of test. Raw assignment counts, before "
             "the one-player cleaning step.")
    srm_panel(srm_gate["n_t"], srm_gate["n_c"], share_gate / 100, "gate_40", "gate_30", "players")
    dec = gate["d7_decomposition"]
    ci = dec["install_level_effect_ci_if_only_reachers"]
    caveat(f"What it means for the decision: the naive D7 gap ({dec['naive_diff'] * 100:+.2f} pp) is not certified. "
           f"The part the gate could cause is about {dec['install_level_effect_if_only_reachers'] * 100:+.2f} pp per "
           f"install (95% CI {ci[0] * 100:+.2f} to {ci[1] * 100:+.2f}; page 6). Keeping gate_30 is the status quo, "
           "so the decision does not depend on certifying the result; a re-test does, after assignment is fixed.")

# -------- where is the gate imbalance?
st.markdown("**Where is the gate experiment's imbalance?**")
st.markdown(
    "Players are split by how far they played. Below level 30 the two versions are identical, so players who "
    "stopped before round 30 should be split 50/50 whatever the gate does. Same counts and rule as above "
    "(raw assignment counts, threshold as selected).")
sbs = gate["srm_by_stratum"]
STRATA = (("All players", srm_gate),
          ("Fewer than 30 rounds (never reached level 30)", sbs["rounds_lt_30"]),
          ("· of which fewer than 15 rounds", sbs["rounds_lt_15"]),
          ("30 rounds or more", sbs["rounds_ge_30"]))
strata = pd.DataFrame([{
    "Players (by rounds played)": label,
    "gate_40": f"{s['n_t']:,}",
    "gate_30": f"{s['n_c']:,}",
    "gate_40 minus gate_30": f"{s['n_t'] - s['n_c']:+,}",
    "gate_40 share": f"{s['observed_share_t'] * 100:.2f}%",
    "p-value": fmt_p(s["p_value"]),
    "Status": srm_status(s["p_value"]),
} for label, s in STRATA])
st.dataframe(strata, hide_index=True, width="stretch", height=table_height(len(strata)),
             column_config={"Players (by rounds played)": st.column_config.TextColumn(width=330),
                            **{c: st.column_config.TextColumn(alignment="right")
                               for c in strata.columns[1:-1]}})
lt15, ge30 = sbs["rounds_lt_15"], sbs["rounds_ge_30"]
pre = gate["pre_gate_engagement"]
nc7 = gate["negative_control"]["never_reached_30"]["retention_7"]
takeaway(f"The imbalance sits among low-engagement installs: {gate['excess_players_with_lt_15_rounds']} of "
         f"gate_40's {srm_gate['n_t'] - srm_gate['n_c']} extra players played fewer than 15 rounds "
         f"({p_txt(lt15['p_value'])} for that split), while players with 30 or more rounds are balanced "
         f"({p_txt(ge30['p_value'])}). Play before round 30 is identical by design, yet it differs between the "
         f"versions ({p_txt(pre['mannwhitney_p'])}), and players who never met a gate retain "
         f"{abs(nc7['abs_lift']) * 100:.2f} pp less on D7 under gate_40 ({p_txt(nc7['p_value'])}): the arms differ "
         "in who was assigned or logged, not only in what the gate did.")
st.caption(f"Raw assignment counts, so gate_40's excess is {srm_gate['n_t'] - srm_gate['n_c']} here and "
           f"{gate['worst_case_bound']['excess_players_gate_40']} in the cleaned data used for the retention "
           "comparisons (the dropped player was in gate_30).")
page_link("views/p6_gate_experiment.py", "Gate experiment: what the gate could have caused")

# ------------------------------------------------------------------ 3 · exposure parity and balance
st.subheader("3 · Exposure parity: the meaningful check for the ad experiment")
ga, gp = ad["groups"]["ad"], ad["groups"]["psa"]
e = st.columns(4)
e[0].metric("Mean ads per user, ad arm", f"{ga['mean_ads']:.2f}",
            help="Total ads (ads or PSAs) served per user during the campaign.")
e[1].metric("Mean ads per user, PSA arm", f"{gp['mean_ads']:.2f}",
            help="The PSA arm was served public-service ads in the same slots.")
e[2].metric("Median ads per user", f"{ga['median_ads']:.0f} vs {gp['median_ads']:.0f}", help="Ad arm vs PSA arm.")
e[3].metric("KS distance (shape)", f"{ad['total_ads_ks']['stat']:.3f}",
            help="Kolmogorov-Smirnov distance: the biggest vertical gap between the arms' cumulative distributions "
                 "of ads seen (0 = identical, 1 = no overlap). Its p-value is tiny only because n is huge.")
st.markdown(
    f"Both arms were served about the same number of ad slots ({ga['mean_ads']:.1f} vs {gp['mean_ads']:.1f} per "
    "user), so the PSA arm is a like-for-like comparison: same slots, different content. The shapes of the two "
    f"distributions differ a little (KS distance {ad['total_ads_ks']['stat']:.3f}). The data cannot say whether that "
    "comes from PSA delivery or from ads changing how much people browse, so exposure stays an exploratory cut. The "
    "same holds for the other fields recorded *after* assignment: the weekday and hour in which a user saw the most "
    "ads.")

VARS = {
    "Total ads seen": ("exposure_bucket", tuple(C.EXPOSURE_LABELS), "Total ads seen (bucket)",
                       "Total ads seen: share of each arm's users (%)", "ad_balance_exposure"),
    "Peak ad day": ("most_ads_day", tuple(C.DAY_ORDER), "Day with most ads",
                    "Peak ad day: share of each arm's users (%)", "ad_balance_day"),
    "Peak ad hour": ("most_ads_hour", tuple(range(24)), "Hour with most ads (0-23)",
                     "Peak ad hour: share of each arm's users (%)", None),
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
    takeaway(f"Arms differ slightly in peak ad hour (Cramér's V {bal['cramers_v']:.3f}); peak hour is recorded after "
             "assignment, so hourly segment results are exploratory.")
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
count should land near the plan, but rarely *on* it: the typical gap is about one standard deviation ("chance gap").
The p-value says how surprising the observed gap would be if the coin were fair; a tiny p-value means the coin, or
the logging around it, is broken. Change the planned split or the threshold and the test is recomputed. Try
{plan_ad * 100 - 1:.0f}% for the ad arm to see a failure.

**Why the ad experiment's SRM pass is uninformative.** Nobody documented the planned split; {split_ad} is inferred
from the data, and the observed count is the nearest whole number to it. A fair coin almost never does that, so the
split was set by a quota (or the file was trimmed to it), and a test of the split has nothing left to detect. The
meaningful check is **exposure parity**: both arms were served the same number of ad slots, so the only planned
difference is what the slot showed.

**Where is the gate imbalance?** Splitting players by how far they played locates the problem. Before level 30 the
two versions are identical, so any imbalance among players who stopped early comes from assignment or logging, not
from the gate. Page 6 shows how much of the D7 gap that explains.

**Balance charts.** For the chosen field, the grey and blue bars show how each arm's users are spread across
categories. Similar bars mean the arms look alike. The p-value is tiny because the sample is huge; **Cramér's V**
measures how big the difference is, and the {min(cramers):.3f} to {max(cramers):.3f} seen here is very small.

**Common misreadings.**
- "The ad test's split is exactly {split_ad}, so assignment was perfect." The opposite: random assignment almost
  never lands exactly on target. A perfect split means a quota, and the SRM test then cannot detect anything.
- "p < 0.0001 on the balance test means randomization failed." No: with {n_ad_users:,} users any tiny difference
  is significant, and these fields are measured after assignment anyway.
- "SRM passed, so everything is fine." SRM only checks arm sizes. It cannot catch a bug that keeps sizes right
  but sends different kinds of users to each arm.
- "The gate result is wrong because of the SRM warning." Not exactly: it cannot be certified, and part of the naive
  gap comes from the imbalance rather than the gate.
""")
