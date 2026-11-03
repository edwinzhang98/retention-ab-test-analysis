"""Builds notebooks/02_retention.ipynb: Cookie Cats new-player retention (D1/D7, funnel, segments).

How it works
  1. The notebook is declared below as a list of markdown and code cells.
  2. Quoted numbers are kept in one table (Q), substituted into the markdown, and re-checked
     against results.json and the clean data by the appendix cell when the notebook runs.
  3. A final appendix cell re-checks every quoted number when the notebook runs and fails if
     any of them has drifted from reports/results.json or the clean data.
  4. The notebook is written with deterministic cell ids, so rebuilds give readable git diffs.

This script only writes the .ipynb. Execute it and export HTML with
`python run.py --only notebooks` (or run everything with `make notebooks`).

Usage (from anywhere): .venv/bin/python scripts/notebooks/build_02_retention.py
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO = Path(__file__).resolve().parents[2]  # scripts/notebooks/ -> repo root
OUT = REPO / "notebooks" / "02_retention.ipynb"
NB_TITLE = "02 · New-player retention"

# Every number quoted in prose. Values typed from reports/results.json and the clean
# player table; the appendix cell re-derives each one at execution time.
Q = {
    # retention
    "n_clean": "90,188",
    "played_n": "86,194",
    "played": "95.6%",
    "d1": "44.5%",
    "no_d1_share": "55.5%",
    "first_drop": "55.5 pp",
    "d7": "18.6%",
    "d7_ci": "18.4–18.9%",
    "funnel_last": "14.6%",
    "drop_d1d7": "29.9 pp",
    "low_share": "47%",
    "low_n": "42,326",
    "low_d7": "2.3%",
    "low_d7_n": "962",
    "low_d7_max": "3.4%",
    "d7_100": "71.1%",
    "low_lost_share": "56%",
    "low_no_d1_share": "72%",
    "d1_ratio": "4.6×",
    "d7_yes": "32.8%",
    "d7_no": "7.2%",
    "gap_d1_overall": "25.6 pp",
    "scenario": "0.26",
    "within_min": "−2.7",
    "within_max": "+5.1",
    "gap_rounds": "70 pp",
    "gap_d1": "26 pp",
    "gap_version": "0.8 pp",
    "could_be_gate": "0.3 pp",
    "n_target_05": "31K",
    "installs_05": "66K",
    "n_target_05_exact": "30,809",
    "installs_05_exact": "65,648",
    "rel_05pp": "+22%",
    "rel_1pp": "+44%",
    "outlier_rounds": "49,854",
    "outlier_per_day": "3,561",
    "median_rounds": "16",
    "reach30": "37%",
    "reach40": "30%",
    "curve_gap": "1.0 pp",
    "curve_gap_at": "23",
    "rc_low": "1.2%",
    "rc_high": "62.6%",
    "skipped_share": "21%",
    "skipped_n": "3,598",
    "d7_active_n": "16,780",
    "zero_d1": "87",
    "zero_d7": "29",
    "zero_flag_share": "0.1%",
    "n30": "44,700",
    "n40": "45,489",
    "srm_p": "0.0086",
    "srm_warn": "0.01",
    "srm_fail": "0.001",
    "alpha": "0.05",
    "power": "80%",
    # gate experiment (R5 and its evidence chain), from reports/results.json -> cookie.gate
    "excess_raw": "789",
    "excess_clean": "790",
    "excess_lt15": "762",
    "ex15_s": "+762",
    "ex1529_s": "+70",
    "ex30_s": "−43",
    "p15": "0.0002",
    "p1529": "0.56",
    "p30": "0.81",
    "pregate_p": "0.004",
    "pregate_lt30_p": "0.07",
    "g40_d7": "18.20%",
    "g30_d7": "19.02%",
    "gate_naive": "−0.82 pp",
    "gate_naive_abs": "0.82 pp",
    "naive_ci": "−1.33 to −0.31",
    "nc_abs": "0.33 pp",
    "nc_lo": "−0.65",
    "nc_p": "0.049",
    "b1529_d7": "−0.87",
    "b1529_ci": "−1.82 to +0.07",
    "b1529_p": "0.071",
    "b15_d7": "−0.09",
    "b15_p": "0.53",
    "band_diff_p": "0.12",
    "n29_t": "311",
    "n29_c": "302",
    "b1528_d7": "−0.68",
    "b1528_ci": "−1.64 to +0.28",
    "nc_rm": "−0.22",
    "nc_rm_p": "0.19",
    "dec_mix": "−0.29",
    "dec_never": "−0.21",
    "dec_reach": "−0.32",
    "dec_reach_1dp": "−0.3",
    "dec_ci": "−0.71 to +0.07",
    "share_not_gate": "60%",
    "per10k": "32",
    "per10k_lo": "71",
    "per10k_hi": "7",
    "b30_d7": "−0.87",
    "b30_ci": "−1.94 to +0.20",
    "bc": "−0.50",
    "bc_ci": "−1.01 to +0.02",
    "bc_p": "0.057",
    "d1_naive": "−0.59",
    "d1_ci": "−1.24 to +0.06",
    "d1_mix": "−0.42",
    "d1_30": "+0.08",
    "d1_30_ci": "−0.78 to +0.94",
    "d1_could": "+0.03",
    "d1_could_ci": "−0.29 to +0.35",
    "rounds_all": "−0.04",
    "rounds_all_ci": "−1.4 to +1.3",
    "med_t": "75",
    "med_c": "72",
    "med_p": "0.0001",
    "past40_t": "83.2%",
    "past40_c": "81.4%",
    "past40_diff": "+1.8 pp",
    "past40_ci": "+1.0 to +2.6",
    "mean30_diff": "+2.4",
    "mean30_ci": "−0.7 to +5.3",
    "sesoi": "0.5 pp",
    "sesoi_rel": "2.6%",
    "g30_d7_1dp": "19.0%",
    "retest_reachers": "42K",
    "retest_reach_installs": "114K",
    "retest_all": "191K",
    "rise_more": "2%",
    "retest_all_rise": "195K",
    "retest_reach_rise": "114.4K",
    "share_reached": "36.9%",
}

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def fill(text: str, used: set[str]) -> str:
    def sub(m: re.Match) -> str:
        used.add(m.group(1))
        return Q[m.group(1)]
    return PLACEHOLDER.sub(sub, text)


def md(text: str) -> tuple[str, str]:
    return "md", textwrap.dedent(text).strip("\n")


def code(text: str) -> tuple[str, str]:
    return "code", textwrap.dedent(text).strip("\n")


CELLS = [
    # ------------------------------------------------------------------ title
    md("""
    # 02 · New-player retention: who leaves first, and where is the biggest drop?

    **Growth · Product Analytics** · Cookie Cats, the company's mobile game (Kaggle, 2017 install cohort), {{n_clean}}
    players after cleaning. Companion notebooks: `01_eda` (data quality) and `03_ab_test` (experiment readouts). The
    same charts appear on dashboard page *3 · Retention Analysis* and in `reports/report.html`.

    *Charts are interactive Plotly figures that load plotly.js from a CDN, so they need an internet connection
    (GitHub's notebook preview does not show them). `reports/report.html` is the fully offline version of the
    analysis, with plotly.js embedded.*
    """),
    md("""
    ## TL;DR

    - **{{no_d1_share}} of installs don't return on Day 1: the biggest drop.** A further {{drop_d1d7}} of installs
      return on Day 1 but not on Day 7 ({{funnel_last}} return on both). {{d1}} return on Day 1 and {{d7}} play on
      Day 7 (95% CI {{d7_ci}}). {{played}} of installs ({{played_n}} players) play at least one round at some point
      in their first 14 days (rounds are 14-day totals, so this is not a first-session measure).
    - **Shallow players leave first.** Players with fewer than 15 rounds in their first 14 days are {{low_share}} of
      installs, and only {{low_d7}} of them are back on Day 7 (at most {{low_d7_max}} in any single rounds bucket),
      against {{d7_100}} of players with 100+ rounds. They make up {{low_lost_share}} of everyone not back on Day 7.
      Rounds are counted over 14 days, so this sizes the early-churn segment; it is not a Day-0 targeting rule.
    - **Day-1 return is the earliest strong signal of who stays.** Day-1 returners are {{d1_ratio}} as likely to play
      on Day 7 ({{d7_yes}} vs {{d7_no}}). Within the same engagement bucket, though, the gap is only {{within_min}} to
      {{within_max}} pp: Day-1 return and early engagement largely describe the same players. This is association, not
      cause, so a Day-1 nudge has to be judged on D7.
    - **Engagement depth is the dimension that separates players.** It splits D7 retention by {{gap_rounds}} (partly
      by construction) and Day-1 status by {{gap_d1}}. The two gate versions differ by {{gap_version}} raw, of which
      only about {{could_be_gate}} could be the gate (not certified). Engagement separates retention far more than
      the gate version does; this compares associations and does not rank what changing each would achieve.
    - **Recommendation R6: focus retention work on the Day-1 return, and test it.** The Onboarding PM (with CRM)
      runs a randomized Day-1 re-engagement test for new players who play little on their first day, with D7 as the
      primary metric. Detecting +0.5 pp of D7 on their {{low_d7}} base (a placeholder target) needs about
      {{n_target_05}} target players (≈{{installs_05}} installs) at 50/50.
    - **R5, informed by this notebook: keep the first gate at level 30.** gate_40 shows no sign of a retention benefit:
      the part of the D7 gap the gate could explain is about {{dec_reach_1dp}} pp per install (95% CI {{dec_ci}}),
      possibly zero, and the gate readout is not certified (sample-ratio WARNING).
    """),
    code("""
    # Setup: make `src` importable from any working directory by walking up to the repo root
    # (the folder that holds config.yaml).
    import sys
    from pathlib import Path

    ROOT = next((p for p in (Path.cwd(), *Path.cwd().parents) if (p / "config.yaml").exists()), None)
    if ROOT is None:
        raise FileNotFoundError("config.yaml not found above the working directory: run this notebook inside the repo.")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import plotly.io as pio

    from src import config as C
    from src import data as D
    from src import figures as F
    from src import retention as R
    from src import stats as S
    from src.analysis import load_results
    from src.catalog import build_catalog, load_caches, pct, sgn

    # plotly.js loads from a CDN, so the notebook and its HTML export stay small;
    # reports/report.html is the offline version (plotly.js embedded once).
    pio.renderers.default = "notebook_connected"
    pio.renderers["notebook_connected"].config = {"displaylogo": False,
                                                  "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    pd.set_option("display.max_colwidth", None)   # show long cells in full
    """),
    # ------------------------------------------------------------------ question
    md("""
    ## 1. Question

    > "Also, we're losing a lot of new users in their first 7 days. Which users leave first?"
    > (Growth PM, weekly sync. The full request is in `docs/01_request_and_scope.md`.)

    - **Analysis question (Q4):** among new players, how do Day-1 and Day-7 retention differ by engagement depth (rounds
      played), by whether the player came back on Day 1, and by experiment version? Where is the largest drop?
    - **Decision it informs:** which new-player segment, and which return day (Day 1 or later), onboarding work
      should target first.
    - **Decision owner:** Growth PM with the Game PM and the Onboarding PM.
    - **What would change the answer:** if retention were flat across segments, or the at-risk segment were small,
      onboarding would not be the first place to invest. If the version gap were as large as the engagement gap, the
      gate position would be the main lever.
    """),
    # ------------------------------------------------------------------ data
    md("""
    ## 2. Data

    - **Source:** Cookie Cats (Kaggle, 2017), the company's mobile game, a different product from the app the ads ran
      in. One row per new player who installed during a gate-position experiment: `userid`, `version` (gate_30 /
      gate_40), `sum_gamerounds` (rounds played in the first 14 days after install), `retention_1` and `retention_7`
      (came back to the game on day 1 / day 7 after install). The ad-campaign data has no retention field, so the
      retention question is answered with the game's data. The two datasets share no users, and segment sizes will
      not transfer one-for-one to the app.
    - **Table:** `fct_game_players`, the parquet cache built by `src/data.py`, with three derived columns:
      `rounds_bucket`, `d1_status` and `reached_gate_30`.
    - **Cleaning:** one player with {{outlier_rounds}} rounds in 14 days (about {{outlier_per_day}} rounds a day) is
      treated as a logging error and dropped. Retention rates do not change at the precision reported here. Nothing
      else is removed: 0-round players stay in every denominator because they are real installs.
    - **Not in the data:** install dates or timestamps (so the file is a single install cohort), activity on any day
      other than Day 1 and Day 7, acquisition channel, platform, country and revenue (see Limitations).

    The check below re-derives the key counts from the clean cache (the version counts also from the raw file) and
    compares them with `reports/results.json`, which the pipeline wrote.
    """),
    code("""
    res = load_results()                  # reports/results.json: every headline number in one place
    ck = res["cookie"]
    caches = load_caches()                # data/processed/*.parquet, written by `python run.py --only analysis`
    cat = build_catalog(res, caches)      # the same charts and takeaways as the dashboard and report.html

    players = caches["players"].copy()    # fct_game_players: one row per player, outlier already removed
    players["rounds_bucket"] = pd.Categorical(players["rounds_bucket"], C.ROUNDS_LABELS, ordered=True)
    print(f"{len(players):,} players x {players.shape[1]} columns")
    players.head()
    """),
    code("""
    dq = res["data_quality"]["cookie"]
    gate = ck["gate"]
    early = ck["early_churn_segment"]     # the < 15-rounds segment that R6 targets, as the pipeline stored it
    outlier = dq["outliers_dropped"][0]
    rounds = players["sum_gamerounds"]
    zero = players[rounds == 0]
    shallow = players[rounds < 15]
    n30, n40 = (players["version"] == "gate_30").sum(), (players["version"] == "gate_40").sum()
    # SRM uses raw assignment counts: assignment happens before any cleaning
    raw_version = D.load_cookie_raw()["version"].value_counts()
    n30_raw, n40_raw = raw_version["gate_30"], raw_version["gate_40"]
    srm = S.srm_check(n40_raw, n30_raw, C.INTENDED_GATE40_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)  # FAIL < 0.001 <= WARNING < 0.01

    pd.DataFrame(
        [
            ("Rows", f"{dq['rows_raw']:,} raw → {dq['rows_clean']:,} clean", f"{len(players):,}"),
            ("Duplicate player ids", f"{dq['duplicate_user_id']:,}", f"{players['user_id'].duplicated().sum():,}"),
            ("Null values, all columns", f"{sum(dq['nulls'].values()):,}", f"{players.isna().sum().sum():,}"),
            ("Version values", ", ".join(dq["version_values"]), ", ".join(sorted(players["version"].unique()))),
            ("Rounds: min / median / max", f"{dq['rounds_min']} / {dq['rounds_p50']:.0f} / {dq['rounds_max_raw']:,} (raw)",
             f"{rounds.min()} / {rounds.median():.0f} / {rounds.max():,}"),
            ("Dropped as a logging error",
             f"player {outlier['user_id']} ({outlier['version']}): {outlier['sum_gamerounds']:,} rounds, "
             f"≈{outlier['sum_gamerounds'] / 14:,.0f} a day",
             "absent" if outlier["user_id"] not in set(players["user_id"]) else "STILL PRESENT"),
            ("D1 retention, raw → clean", f"{pct(dq['retention_raw']['d1'], 2)} → {pct(dq['retention_clean']['d1'], 2)}",
             pct(players["retention_1"].mean(), 2)),
            ("D7 retention, raw → clean", f"{pct(dq['retention_raw']['d7'], 2)} → {pct(dq['retention_clean']['d7'], 2)}",
             pct(players["retention_7"].mean(), 2)),
            ("Players with 0 rounds", f"{dq['zero_round_players']:,}", f"{len(zero):,} ({pct(len(zero) / len(players))})"),
            ("0-round players flagged as returning, D1 / D7", "–",
             f"{zero['retention_1'].sum():,} / {zero['retention_7'].sum():,}"),
            ("Active on Day 7 without a Day-1 return", f"{dq['d7_without_d1']:,} (raw file)",
             f"{(players['retention_7'] & ~players['retention_1']).sum():,}"),
            ("Early-churn segment (< 15 rounds): players / share of installs / D7 / back on Day 7",
             f"{early['players']:,} / {pct(early['share_of_installs'], 2)} / {pct(early['retention_7'], 2)} / "
             f"{early['d7_players']:,}",
             f"{len(shallow):,} / {pct(len(shallow) / len(players), 2)} / {pct(shallow['retention_7'].mean(), 2)} / "
             f"{shallow['retention_7'].sum():,}"),
            ("Players by version (analysed), gate_30 / gate_40",
             f"{gate['players']['gate_30']:,} / {gate['players']['gate_40']:,}", f"{n30:,} / {n40:,}"),
            ("Players by version (raw file), gate_30 / gate_40",
             f"{gate['players_raw']['gate_30']:,} / {gate['players_raw']['gate_40']:,}", f"{n30_raw:,} / {n40_raw:,}"),
            ("SRM vs the intended 50/50 (raw counts)", f"p = {gate['srm']['p_value']:.4f} ({gate['srm']['status']})",
             f"p = {srm['p_value']:.4f} ({srm['status']})"),
        ],
        columns=["Check", "results.json (pipeline)", "Recomputed here"],
    ).set_index("Check")
    """),
    md("""
    **Reading the checks.** The cache reconciles with `results.json`. Three details matter later:

    1. The dropped player (gate_30) was active on Day 7 but not on Day 1. That is why "Day 7 without a Day-1 return" is
       one lower in the clean table than in the raw file.
    2. {{zero_d1}} players with 0 rounds are flagged as back on Day 1 ({{zero_d7}} on Day 7), about {{zero_flag_share}}
       of players. The flags mean "came back to the game", not "finished a round" (or round logging is incomplete). We
       keep the dataset's definition; no conclusion depends on these players.
    3. On raw assignment counts ({{n30}} gate_30 vs {{n40}} gate_40) the version split gives an SRM p-value of
       {{srm_p}} against the intended 50/50: below the {{srm_warn}} warning line (this project's convention) and above
       the {{srm_fail}} failure line (the usual SRM convention, after Kohavi et al.), so it is a **WARNING**. gate_40
       has {{excess_raw}} more installs in the raw log, with a net excess of {{excess_lt15}} among players with fewer
       than 15 rounds (`01_eda`, section 8), so the gate readout is not certified (`03_ab_test`). In this notebook
       `version` is only a descriptive segment.
    """),
    # ------------------------------------------------------------------ method
    md("""
    ## 3. Method

    **Metric definitions** (as in `docs/02_metric_definitions.md`)

    | Metric | Definition | Denominator |
    |---|---|---|
    | D1 retention | Share of players flagged as coming back to the game the day after install (`retention_1`) | All players in the clean table, including 0-round installs |
    | D7 retention | Share of players flagged as coming back on day 7 after install (`retention_7`): classic day-7 retention ("played on Day 7"), not rolling ("at any time in days 1–7"), so it is not a subset of D1 | Same |
    | Rounds played | `sum_gamerounds`: game rounds played in the first 14 days after install, a window that includes Day 1 and Day 7 | – |
    | Retention gap | Best minus worst segment D7 within one dimension (segments with at least 500 players; none is smaller here) | – |

    **Uncertainty.** Every rate comes with a 95% Wilson score interval (`src.stats.wilson_ci`). It stays inside 0–100%
    and behaves well for small segments and for rates near 0, where the textbook ±1.96 × SE interval does not. The
    segments are not randomized groups, so there are no significance tests between them: an interval says how precisely
    a rate is measured, not whether belonging to a segment *causes* different retention.

    **Segmentation dimensions.** Each one was chosen because someone can act on it.

    | Dimension | Segments | Business meaning | Who can act |
    |---|---|---|---|
    | Engagement depth: rounds played in the first 14 days | 0 · 1–4 · 5–14 · 15–29 · 30–39 · 40–99 · 100+ | 0 = no recorded rounds in 14 days; 1–4 = barely started in 14 days; 5–14 = tried it, did not stick; 15–29 = engaged but cannot yet have got past level 30, up to which the two versions are identical; 30–39 = could have got past gate 30 but not gate 40; 40–99 = could be past both gate positions; 100+ = core players | Onboarding, level design |
    | Day-1 return | Returned on Day 1 · did not | The first re-engagement moment, reachable with a better first-day experience or a Day-1 reminder or reward | Onboarding PM, CRM |
    | Version | gate_30 · gate_40 | The experiment arm: where the first progression gate sits, a lever the product controls. The arms are unbalanced (sample-ratio warning), so here it is a descriptive segment only | Game PM |

    Rounds are not levels. A player can replay a level, so 30 rounds is necessary but not sufficient to get past
    level 30 (a flawless gate_30 player can already face the gate at exactly 29 rounds). The buckets therefore
    separate players who *could not yet* have got past a gate from those who *could* have: "30+ rounds" means "could
    have reached level 30" (rounds ≥ levels; the data has no level field).

    **Why rounds vs retention is partly definitional.** `sum_gamerounds` is counted over the first 14 days, a window
    that contains Day 1 and Day 7. A player who comes back on Day 7 has more days on which to play, so part of the
    rounds–retention link is built into the two definitions. Players who like the game also both play more and come
    back (self-selection). The rounds buckets therefore **size the early-churn segment** and describe who churns. They
    are **not a Day-0 targeting rule** (the 14-day count is not known on Day 0), and they cannot say what would happen
    if we got players to play more. Only an experiment can (Recommendation R6).
    """),
    # ------------------------------------------------------------------ results
    md("""
    ## 4. Results

    ### 4.1 Where is the biggest drop?

    Each bar is a share of all installs. The last step needs a return on Day 1 *and* on Day 7, so it is lower
    ({{funnel_last}}) than overall D7 ({{d7}}): some players skip Day 1 and come back later (section 4.8).
    """),
    code("""
    cat["ret_funnel"].fig.show()
    """),
    code("""
    funnel = pd.DataFrame(ck["funnel"])
    pd.DataFrame({
        "Step": funnel["step"],
        "Players": funnel["players"].map("{:,}".format),
        "Share of installs": funnel["share_of_installs"].map(pct),
        "Of previous step": funnel["step_conversion"].map(lambda x: "–" if pd.isna(x) else pct(x)),
        "Drop vs previous step": (-funnel["share_of_installs"].diff() * 100).map(
            lambda x: "–" if pd.isna(x) else f"{x:.1f} pp"),
    }).set_index("Step")
    """),
    md("""
    **Conclusion:** {{no_d1_share}} of installs don't return on Day 1: the biggest drop ({{first_drop}} of installs).
    A further {{drop_d1d7}} of installs return on Day 1 but not on Day 7 ({{funnel_last}} return on both).
    The next-day return is the focus for retention work.
    """),
    md("""
    ### 4.2 Who leaves first? Retention by engagement depth

    D1 and D7 retention by rounds played in the first 14 days, bucketed around the two gate positions. Whiskers are 95%
    Wilson intervals; the number of players is under each bucket.
    """),
    code("""
    cat["ret_by_rounds_bucket"].fig.show()
    """),
    code("""
    def rates_table(rates: pd.DataFrame, col: str, label: str, metrics=("retention_1", "retention_7")) -> pd.DataFrame:
        \"\"\"Readable version of a retention_rates() table: counts, shares and rates with 95% Wilson CIs.\"\"\"
        out = pd.DataFrame({label: rates[col].astype(str),
                            "Players": rates["players"].map("{:,}".format),
                            "Share of installs": rates["share_of_players"].map(pct)})
        for m in metrics:
            out[f"{R.METRICS[m]} (95% CI)"] = [
                f"{r[m] * 100:.1f}% ({r[m + '_ci_low'] * 100:.1f}–{r[m + '_ci_high'] * 100:.1f})"
                for _, r in rates.iterrows()]
        return out.set_index(label)


    rates_table(R.retention_rates(players, "rounds_bucket"), "rounds_bucket", "Rounds played (first 14 days)")
    """),
    md("""
    **Conclusion:** players with fewer than 15 rounds, {{low_share}} of installs ({{low_n}} players), are almost all
    absent on Day 7: only {{low_d7}} of them play on Day 7 ({{low_d7_n}} players; at most {{low_d7_max}} in any single bucket),
    while {{d7_100}} of players with 100+ rounds still do. A shallow start is the clearest marker of who leaves first.
    Rounds are counted through day 14, so the buckets size this early-churn segment; they are not a rule we could apply
    on Day 0.
    """),
    md("""
    ### 4.3 Does coming back on Day 1 matter?

    D7 retention for players who did and did not come back on Day 1.
    """),
    code("""
    cat["ret_by_d1"].fig.show()
    rates_table(R.retention_rates(players, "d1_status"), "d1_status", "Day-1 status", metrics=("retention_7",))
    """),
    md("""
    **Conclusion:** {{no_d1_share}} of new players do not come back on Day 1, and those who do are {{d1_ratio}} as likely
    to play on Day 7 ({{d7_yes}} vs {{d7_no}}): Day-1 return is the earliest strong signal of who stays. It is an
    association, not proof that prompting a Day-1 visit would lift D7; section 4.7 checks how much of it is engagement
    depth in disguise.
    """),
    md("""
    ### 4.4 How far do players get? Engagement curve by version

    The share of players who played at least N rounds in their first 14 days, by experiment version. Read it like a
    survival curve over game progress, not over calendar time. The dotted lines mark the two gate positions (these are
    levels; see the note on rounds vs levels in section 3).
    """),
    code("""
    cat["ret_engagement_curve"].fig.show()
    """),
    code("""
    curve = R.engagement_curve(players, 200, by="version").pivot(
        index="rounds_at_least", columns="group", values="share_of_players")
    gap = (curve["gate_40"] - curve["gate_30"]) * 100      # pp, gate_40 minus gate_30
    gap_at = int(gap.abs().idxmax())
    print(f"Median rounds played in the first 14 days: {rounds.median():.0f}")
    print(f"Played at least 30 rounds: {pct((rounds >= 30).mean())}; at least 40 rounds: {pct((rounds >= 40).mean())}")
    print(f"Largest gap between the gate_30 and gate_40 curves (0-200 rounds): {gap.abs().max():.1f} pp at "
          f"{gap_at} rounds ({sgn(gap[gap_at])} pp, gate_40 minus gate_30)")
    """),
    md("""
    **Conclusion:** half of players play {{median_rounds}} rounds or fewer and only {{reach30}} reach 30 rounds
    ({{reach40}} reach 40), so at most ~{{reach30}} of installs could have met the level-30 gate: most players are lost
    long before either gate position. The version curves are never more than {{curve_gap}} apart, and the largest gap
    (at {{curve_gap_at}} rounds) comes before either gate, where both versions offer the same game: it is the
    assignment imbalance seen as a distribution (`01_eda`, section 8), not an effect of the gate.
    """),
    md("""
    ### 4.5 Retention by rounds played, in 5-round bins

    The same data as 4.2 at a finer grain. Each point is a 5-round bin plotted at the bin's median; the last point pools
    everyone with 150 or more rounds.
    """),
    code("""
    cat["ret_by_rounds_curve"].fig.show()
    """),
    code("""
    by_bin = R.retention_by_rounds(players, 150, 5)    # the chart's bins: 0-4, 5-9, ..., 145-149, then 150+
    print(f"D7 retention: {pct(by_bin['retention_7'].iloc[0])} at 0-4 rounds, "
          f"{pct(by_bin['retention_7'].iloc[150 // 5 - 1])} at 145-149 rounds, "
          f"{pct(by_bin['retention_7'].iloc[-1])} at 150+ rounds")
    """),
    md("""
    **Conclusion:** D7 retention climbs steadily from {{rc_low}} (0–4 rounds) to {{rc_high}} (145–149 rounds) with no
    visible step at round 30 or 40, so engagement depth behaves like a continuous marker of how well the game fits a
    player rather than one "cliff" level. Because rounds overlap the D7 window, part of the climb is built into the
    definitions: descriptive, not causal.
    """),
    md("""
    ### 4.6 Which dimension separates D7 retention the most?

    For each dimension, the D7 gap between its best and its worst segment (hover for the segments).
    """),
    code("""
    cat["ret_gap_by_dimension"].fig.show()
    gaps = pd.DataFrame(ck["gap_by_dimension"])
    pd.DataFrame({
        "Dimension": gaps["dimension"],
        "Best segment (D7)": [f"{r.best_segment} ({pct(r.best_rate)})" for r in gaps.itertuples()],
        "Worst segment (D7)": [f"{r.worst_segment} ({pct(r.worst_rate)})" for r in gaps.itertuples()],
        "Gap": gaps["gap_pp"].map(lambda x: f"{x:.1f} pp"),
    }).set_index("Dimension")
    """),
    md("""
    **Conclusion:** engagement depth ({{gap_rounds}}, partly by construction) and Day-1 status ({{gap_d1}}) separate D7
    retention far more than the gate version ({{gap_version}} raw), so the 7-day churn problem sits in early engagement.

    *Caution:* the bars compare different kinds of gap. The version gap compares the two experiment arms, but the arms
    are unbalanced (sample-ratio warning). About {{share_not_gate}} of the naive {{gate_naive}} D7 gap (player mix
    {{dec_mix}} pp plus players who never met a gate {{dec_never}} pp) sits where the gate cannot act; the remaining
    {{dec_reach}} pp per install is the part the gate could explain, not an estimate of its effect (R5 below and
    `03_ab_test`). The other two gaps compare different kinds of players and say nothing about cause.
    """),
    md("""
    ### 4.7 Extra: is Day-1 return just a proxy for engagement depth?

    Day-1 returners are also the players who go on to play more, so the ratio in 4.3 mixes two things. Splitting each
    rounds bucket by Day-1 status (computed here; not part of `results.json`) shows how much of the Day-1 gap is left
    when engagement depth is held roughly fixed. The gap and its 95% Newcombe interval come from
    `src.stats.two_prop_test`, with "returned on Day 1" in the place of the treatment arm.
    """),
    code("""
    segments = [("All players", players)] + [(str(b), g) for b, g in players.groupby("rounds_bucket", observed=True)]
    rows = []
    for name, g in segments:
        back, gone = g[g["retention_1"]], g[~g["retention_1"]]
        t = S.two_prop_test(back["retention_7"].sum(), len(back), gone["retention_7"].sum(), len(gone))
        rows.append({"rounds_bucket": name, "returned_players": t.n_t, "returned_d7": t.rate_t,
                     "not_returned_players": t.n_c, "not_returned_d7": t.rate_c, "gap_pp": t.abs_lift * 100,
                     "gap_ci_low_pp": t.abs_ci_low * 100, "gap_ci_high_pp": t.abs_ci_high * 100})
    d1_gap = pd.DataFrame(rows)

    pd.DataFrame({
        "Rounds played": d1_gap["rounds_bucket"],
        "Returned Day 1: players": d1_gap["returned_players"].map("{:,}".format),
        "Returned Day 1: D7": d1_gap["returned_d7"].map(pct),
        "Did not return: players": d1_gap["not_returned_players"].map("{:,}".format),
        "Did not return: D7": d1_gap["not_returned_d7"].map(pct),
        "D7 gap, pp (95% CI)": [f"{sgn(r.gap_pp, 1)} ({sgn(r.gap_ci_low_pp, 1)} to {sgn(r.gap_ci_high_pp, 1)})"
                                for r in d1_gap.itertuples()],
    }).set_index("Rounds played")
    """),
    code("""
    cross = pd.concat([
        R.retention_rates(players, "d1_status").assign(rounds_bucket="All players"),
        R.retention_rates(players, ["rounds_bucket", "d1_status"]).assign(
            rounds_bucket=lambda d: d["rounds_bucket"].astype(str)),
    ], ignore_index=True)

    fig = go.Figure()
    for status, color in (("Did not return Day 1", F.GREY), ("Returned Day 1", F.BLUE)):
        r = cross[cross["d1_status"] == status]
        y = r["retention_7"] * 100
        fig.add_bar(
            x=r["rounds_bucket"], y=y, name=status, marker=dict(color=color, cornerradius=3),
            error_y=dict(type="data", symmetric=False, array=r["retention_7_ci_high"] * 100 - y,
                         arrayminus=y - r["retention_7_ci_low"] * 100, color=F.INK_2, thickness=1.2, width=3),
            customdata=np.stack([r["players"], r["retention_7_ci_low"] * 100, r["retention_7_ci_high"] * 100], axis=1),
            hovertemplate="%{x} · " + status + "<br>D7 retention %{y:.1f}% (95% CI %{customdata[1]:.1f} to "
                          "%{customdata[2]:.1f})<br>Players %{customdata[0]:,}<extra></extra>",
        )
    overall, within = d1_gap.iloc[0], d1_gap.iloc[1:]
    subtitle = (f"Overall, Day-1 returners are {overall.returned_d7 / overall.not_returned_d7:.1f}× as likely to "
                f"play on Day 7, but within a rounds bucket the gap is only {sgn(within.gap_pp.min(), 1)} to "
                f"{sgn(within.gap_pp.max(), 1)} pp: the two dimensions largely describe the same players.")
    F.apply_layout(fig, "D7 retention by rounds played, split by Day-1 return (%, 95% CI)", subtitle, height=440,
                   xaxis_title="Rounds played in first 14 days (bucket)", yaxis_title="Players retained on Day 7 (%)")
    fig.add_vline(x=0.5, line=dict(color=F.INK_2, width=1, dash="dot"))   # overall pair | per-bucket pairs
    fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero")
    fig.show()
    """),
    md("""
    **Conclusion:** with engagement depth held roughly fixed, the Day-1 gap in D7 shrinks from {{gap_d1_overall}} to
    between {{within_min}} and {{within_max}} pp (it is even negative for 30–99 rounds, although only the 40–99 interval
    excludes zero), so Day-1 return and early engagement largely describe the same players: bringing someone back on
    Day 1 without deepening their play may not move D7, which is why R6 is judged on D7.

    *Caution:* holding rounds fixed is itself imperfect. A player who skipped Day 1 but still reached 40+ rounds must
    have played on other days, which on its own predicts Day-7 activity. Read this as "the two dimensions overlap", not
    as "Day 1 does not matter". The largest within-bucket gap ({{within_max}} pp) is in the 0-round bucket, which has
    only {{zero_d1}} Day-1 returners and a wide interval.
    """),
    md("""
    ### 4.8 Extra: where do the lost players sit?

    Rates say who is most at risk; volumes say where the lost players actually are. "Not back on Day 7" means not
    active on Day 7 itself, the complement of D7.
    """),
    code("""
    volume = (players.assign(no_d1=~players["retention_1"], lost_d7=~players["retention_7"])
              .groupby("rounds_bucket", observed=True)
              .agg(players=("user_id", "size"), no_d1=("no_d1", "sum"), lost_d7=("lost_d7", "sum")))
    volume.index = volume.index.astype(str)
    volume.loc["Fewer than 15 rounds (0-14)"] = volume.loc[["0", "1-4", "5-14"]].sum()
    volume.loc["All players"] = volume.loc[C.ROUNDS_LABELS].sum()
    total = volume.loc["All players"]

    pd.DataFrame({
        "Players": volume["players"].map("{:,}".format),
        "Share of installs": (volume["players"] / total["players"]).map(pct),
        "Did not return on Day 1": volume["no_d1"].map("{:,}".format),
        "Share of all Day-1 non-returners": (volume["no_d1"] / total["no_d1"]).map(pct),
        "Not back on Day 7": volume["lost_d7"].map("{:,}".format),
        "Share of all not back on Day 7": (volume["lost_d7"] / total["lost_d7"]).map(pct),
    }).rename_axis("Rounds played (first 14 days)")
    """),
    code("""
    active_d7 = players["retention_7"]
    skipped_d1 = active_d7 & ~players["retention_1"]
    print(f"{skipped_d1.sum():,} of the {active_d7.sum():,} players active on Day 7 "
          f"({pct(skipped_d1.sum() / active_d7.sum())}) did not come back on Day 1.")
    """),
    md("""
    **Conclusion:** players with fewer than 15 rounds are {{low_share}} of installs but {{low_lost_share}} of everyone
    not back on Day 7 and {{low_no_d1_share}} of Day-1 non-returners, so they are both the highest-risk and the largest group
    to target; separately, {{skipped_share}} of Day-7 actives ({{skipped_n}} of {{d7_active_n}}) skipped Day 1, so a
    missed Day 1 is not final.
    """),
    # ------------------------------------------------------------------ limitations
    md("""
    ## 5. Limitations

    - **Association, not cause.** Rounds are counted over 14 days that include Day 1 and Day 7, so the rounds–retention
      link is partly definitional, and players self-select into playing more. The segment gaps describe *who* churns;
      they do not say what would happen if we changed behaviour.
    - **No dates and no event log.** Without install dates the file is a single install cohort: no seasonality or
      novelty checks and no retention on days other than 1 and 7 (no D2–D6, D14 or D30 decay curve). The curve in 4.4
      is over game progress, not calendar time.
    - **The 14-day rounds count is not known on Day 0.** The engagement buckets size the early-churn segment; a live
      targeting rule needs a first-session signal (for example rounds played on the install day), which this dataset
      does not contain.
    - **Retention-flag definition.** {{zero_d1}} players with 0 rounds are flagged as back on Day 1 ({{zero_d7}} on
      Day 7), so the flags mean "came back to the game", not "played a round". This affects about {{zero_flag_share}} of
      players and no conclusion depends on it.
    - **Missing growth dimensions.** There is no acquisition channel, platform, country or spend, so we cannot tell
      whether shallow players are an onboarding problem or an acquisition-quality problem (one channel sending
      low-intent installs, for example).
    - **A different product, 2017.** The retention data comes from the company's mobile game (Cookie Cats, 2017 install
      cohort), a different product from the app the ads ran in, so segment sizes and D1 / D7 levels will not transfer
      one-for-one. The transferable part is the pattern (early engagement separates retention far more than anything
      else); re-check it on the app's own new installs before relying on exact numbers.
    - **Version caveat.** The gate experiment carries a sample-ratio warning (p = {{srm_p}} on raw assignment counts),
      with a net excess of low-engagement installs in gate_40, so even the version comparison is not certified
      (`03_ab_test`).
    """),
    # ------------------------------------------------------------------ recommendations
    md("""
    ## 6. Recommendations

    These match the project-wide decision list (R1–R6 in `docs/readout.md` and dashboard page 7). R6 comes from this
    notebook; R5 is informed by it.

    **R6 · Focus retention work on the Day-1 return**
    - **Owner:** Onboarding PM (with CRM).
    - **What:** a randomized Day-1 re-engagement test for new players who play little on their first day, with D7 as
      the primary metric: for example a simpler first-session flow, or a Day-1 reminder or reward. Target with
      first-day play (such as rounds played on the install day), because the 14-day count used here is not known on
      Day 0.
    - **Expected impact:** it targets the biggest drop: {{no_d1_share}} of installs don't return on Day 1, and
      {{low_share}} play fewer than 15 rounds in 14 days, of whom only {{low_d7}} play on Day 7. Illustrative scenario,
      not a forecast or an upper bound: shifting 1 pp of installs from the non-returners' {{d7_no}} D7 to the Day-1
      returners' {{d7_yes}} would add about {{scenario}} pp of D7; R6's real impact must be measured.
    - **How we'll measure:** D7 among the targeted players against a randomized holdout (primary); D1 (secondary).
      D1 is not the primary metric because section 4.7 suggests D1 can move without D7 following. Guardrails:
      uninstall rate and notification opt-out rate. Sizing: +0.5 pp of D7 on the {{low_d7}} base (a placeholder
      target) needs ≈{{n_target_05}} target players (≈{{installs_05}} installs) at 50/50; see the table below.
    - **Main risk:** rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use
      first-day play; the play–retention link may not be causal, so the treatment may raise rounds or D1 without moving
      D7; notification fatigue.

    **R5 · Keep the first gate at level 30 (no change); fix assignment first**
    - **Owner:** Game PM (Eng + Analytics fix assignment).
    - **What:** keep gate_30, the status quo, and don't ship gate_40. Fix assignment / logging first (gate_40 has
      ≈{{excess_clean}} extra installs, with a net excess of {{excess_lt15}} among players with fewer than 15 rounds; `01_eda`, section 8).
      Re-test only if the gate position matters commercially. The gate readout is not certified.
    - **Expected impact:** avoids a change with no sign of a retention benefit. The part of the D7 gap the gate could
      explain is ≈{{dec_reach_1dp}} pp per install (95% CI {{dec_ci}}; ≈{{per10k}} fewer Day-7 players per 10,000
      installs), and even that may not be the gate. Among players with 30+ rounds (who could have reached level 30),
      gate_40 players played a little more (descriptive)
      (median {{med_t}} vs {{med_c}} rounds). Assignment is uncertified and the group is defined by rounds played,
      so it does not show that gate_40 causes more play. If the Game PM values that, a clean re-test is the way to decide.
    - **How we'll measure (any re-test):** pre-register a {{sesoi}} D7 change per install as the smallest change worth
      acting on (a placeholder to agree with the Game PM, ≈{{sesoi_rel}} of gate_30's {{g30_d7_1dp}}). With the primary
      analysis among players who reach level 30 (30+ rounds here; who gets there is settled before the gate, so the
      group can be pre-registered), that needs ≈{{retest_reach_installs}} installs at 50/50 (≈{{retest_reachers}} of
      them reach level 30); analysed over all installs, ≈{{retest_all}}. These are sized to detect a {{sesoi}} drop; a
      rise of the same size needs up to ≈{{rise_more}} more (≈{{retest_all_rise}} install-level, ≈{{retest_reach_rise}}
      reacher analysis). The reacher figure uses this cohort's {{share_reached}} reaching level 30; re-check with the
      new cohort's share before launch. Add a daily 50/50 group-size check. The test is sized at that pre-registered
      change, never at the observed gap: if the true effect is smaller than {{sesoi}}, it would not change the
      decision.
    - **Main risk:** quoting the raw {{gate_naive}} would overstate the effect; missing a small real effect either way.

    **Why R5: the gate evidence, in order** (charts and details in `03_ab_test`). Throughout, "30+ rounds" means
    "could have reached level 30": rounds ≥ levels, and the data has no level field.

    1. **Naive result (not certified).** gate_40's D7 is {{g40_d7}} vs {{g30_d7}} for gate_30: gate_40 shows
       {{gate_naive_abs}} lower D7 (95% CI {{naive_ci}}).
    2. **Sample ratio.** WARNING on raw assignment counts (p = {{srm_p}}). gate_40 has {{excess_raw}} more installs in
       the raw log; by rounds band the net excess is {{ex15_s}} among players with fewer than 15 rounds (p = {{p15}}),
       {{ex1529_s}} at 15–29 rounds (p = {{p1529}}) and {{ex30_s}} at 30+ (p = {{p30}}). The bands were chosen after
       seeing the warning, so these p-values are descriptive. Most likely assignment or logging added low-engagement
       installs to gate_40 (or dropped them from gate_30); Engineering confirms the cause.
    3. **Pre-gate play.** Rounds capped at 29 are lower in gate_40 (p = {{pregate_p}}). This is the same imbalance seen
       as a distribution, not independent evidence: within players with fewer than 30 rounds it is p =
       {{pregate_lt30_p}}.
    4. **Negative control.** Players with fewer than 30 rounds never met a gate, yet their D7 is {{nc_abs}} lower in
       gate_40 (95% CI {{nc_lo}} to just below 0, p = {{nc_p}}). That is borderline on its own; it carries weight only
       because the sample-ratio warning independently says the arms are not comparable. Such gap as there is comes
       from the 15–29 band ({{b1529_d7}} pp, p = {{b1529_p}}, balanced in number) rather than the band with fewer than
       15 rounds, where the net excess sits ({{b15_d7}} pp, p = {{b15_p}}), though the two bands' gaps are not
       distinguishable from each other (p = {{band_diff_p}}). Removing the net {{excess_lt15}} extra installs with fewer than 15
       rounds moves it only to {{nc_rm}} pp (p = {{nc_rm_p}}). So the extra installs explain the SRM and the player-mix
       part of the gap, but not this one.
    5. **Decomposition.** The naive {{gate_naive}} = player mix {{dec_mix}} + players who never met a gate
       {{dec_never}} + players who could meet the gate {{dec_reach}} pp per install (95% CI {{dec_ci}}); the split is
       exact. About {{share_not_gate}} of the naive gap (player mix plus players who never met a gate) sits where the
       gate cannot act. The {{dec_reach}} pp is the part the gate could explain, not an estimate of its effect: players
       with 15–29 rounds, almost none of whom can have met a gate, show a similar D7 gap ({{b1529_d7}} pp, 95% CI {{b1529_ci}}) to players
       with 30+ rounds ({{b30_d7}} pp, 95% CI {{b30_ci}}), so even this part may not be the gate. Per 10,000 installs it is ≈{{per10k}} fewer Day-7
       players (95% CI {{per10k_lo}} fewer to {{per10k_hi}} more).
    6. **Best case for gate_40.** Even if every one of the ≈{{excess_clean}} extra installs never returned, the D7 gap
       would still be {{bc}} pp (95% CI {{bc_ci}}, p = {{bc_p}}); its interval includes 0.
    7. **D1 guardrail.** The naive D1 gap, {{d1_naive}} pp (95% CI {{d1_ci}}), carries the same imbalance (player mix
       {{d1_mix}} pp). The part the gate could explain is {{d1_could}} pp per install (95% CI {{d1_could_ci}}): no sign
       of a D1 effect. The 30+ band's own D1 gap ({{d1_30}} pp, 95% CI {{d1_30_ci}}) is diluted, because the gate can
       change Day 1 only for players who reached level 30 on the install day, and the data cannot single them out.
    8. **Engagement guardrail.** The all-player mean ({{rounds_all}} rounds, 95% CI {{rounds_all_ci}}) carries the same
       imbalance, so it is not a clean guardrail. Among players with 30+ rounds, gate_40 players play a little more:
       median {{med_t}} vs {{med_c}} rounds (Mann-Whitney p = {{med_p}}), and {{past40_t}} vs {{past40_c}} played at least 40
       rounds ({{past40_diff}}, 95% CI {{past40_ci}}). It is a descriptive difference: assignment is uncertified and
       the group is defined by rounds played, so it does not show that gate_40 causes more play. The mean difference
       ({{mean30_diff}} rounds, 95% CI {{mean30_ci}}) is too noisy to read. These players' D7 is not
       higher ({{b30_d7}} pp, 95% CI {{b30_ci}}): no sign of a retention benefit.
    9. **Why splitting by rounds is allowed here, when splitting the ad test by ads seen is not.** Ads can change how
       long a user stays from the first impression, so exposure can be caused by the treatment. Below level 30 both
       game versions are identical, and a player with fewer than 30 rounds cannot have got past level 30 (rounds ≥
       levels), so whether a player ever plays 30 rounds can depend on the gate only in an edge case, and it behaves
       like a trait fixed before treatment. The edge case is a flawless gate_30 player, who can already face the gate
       at exactly 29 rounds. Such players are few (no pile-up at 29 rounds: {{n29_t}} players in gate_40 vs {{n29_c}}
       in gate_30), and excluding 29-round players, the 15–28 band still shows {{b1528_d7}} pp D7 (95% CI
       {{b1528_ci}}). The strata are close to, not exactly, gate-free, which is why {{dec_reach}} pp is called the part
       the gate could explain.

    **Sizing R6.** Players needed in the target group (fewer than 15 rounds) to detect a D7 lift with a 50/50 split,
    two-sided α = {{alpha}} and {{power}} power (both from `config.yaml`). The pipeline stores the +0.5 pp case in
    `reports/results.json` (`cookie.early_churn_segment.onboarding_test_sizing`); the cell recomputes it and stops if
    the two disagree.
    """),
    code("""
    target = players["sum_gamerounds"] < 15
    base_d7 = players.loc[target, "retention_7"].mean()
    lifts = (C.ONBOARD_LIFT_ABS, 0.01)            # config.yaml onboarding_target_lift_pp (placeholder), and +1 pp
    n_needed = {lift: S.required_total_n(base_d7, lift, 0.5, C.ALPHA, C.POWER) for lift in lifts}
    installs_needed = {lift: int(np.ceil(n / target.mean())) for lift, n in n_needed.items()}
    sizing = early["onboarding_test_sizing"]
    assert abs(sizing["target_lift_abs"] - C.ONBOARD_LIFT_ABS) < 1e-12
    assert (n_needed[C.ONBOARD_LIFT_ABS], installs_needed[C.ONBOARD_LIFT_ABS]) == (
        sizing["players_needed_5050"], sizing["installs_needed_5050"]), "R6 sizing differs from reports/results.json"

    print(f"Target group: {target.sum():,} players ({pct(target.mean(), 0)} of installs), base D7 {pct(base_d7)}; "
          f"alpha = {C.ALPHA}, power = {C.POWER:.0%}")
    pd.DataFrame({
        "Relative to base D7": [f"+{lift / base_d7:.0%}" for lift in lifts],
        "Target-group players needed (both arms)": [f"{n_needed[lift]:,}" for lift in lifts],
        "Installs needed at the current mix (approx.)": [f"{installs_needed[lift]:,}" for lift in lifts],
    }, index=pd.Index([f"+{lift * 100:.1f} pp" for lift in lifts], name="Detectable D7 lift"))
    """),
    md("""
    A +1 pp lift would be {{rel_1pp}} relative for a group whose D7 is {{low_d7}}, which is a lot to expect from a
    nudge. Sizing for +0.5 pp ({{rel_05pp}} relative; a placeholder target in `config.yaml` →
    `onboarding_target_lift_pp`) needs {{n_target_05_exact}} target players across both arms, about
    {{installs_05_exact}} installs at the current mix: the ≈{{n_target_05}} and ≈{{installs_05}} quoted in R6. The
    sample-size calculator on dashboard page 7 redoes this for other baselines and splits.

    **Data I would ask for next**
    - Install date and a daily activity log (Day 2 to Day 30), to track retention by install week, draw a real retention
      curve and check novelty or seasonality.
    - Rounds played and level reached on the install day, for a live targeting rule and a direct measure of who
      actually hits a gate.
    - Acquisition channel, platform and country, to tell an onboarding problem from an acquisition-quality problem.
    - Revenue per player, to put a value on a retained player and turn R6's sizing into money.
    """),
    # ------------------------------------------------------------------ appendix
    md("""
    ## Appendix: number check

    Every number quoted in the text above is recomputed here from `results.json` and the clean player table. The cell
    fails if any of them drifts (for example after the pipeline is re-run on new data), so the prose cannot go stale
    silently.
    """),
    code("""
    f = pd.DataFrame(ck["funnel"]).set_index("step")["share_of_installs"]
    played_14d = players["sum_gamerounds"] > 0
    assert ck["overall"]["played_any_round_14d"] == int(played_14d.sum())
    assert np.isclose(ck["overall"]["share_played_any_round_14d"], played_14d.mean(), atol=5e-9, rtol=0)
    expected_funnel = R.funnel(players)
    assert pd.DataFrame(ck["funnel"])[["step", "players"]].equals(expected_funnel[["step", "players"]])
    gap_dim = pd.DataFrame(ck["gap_by_dimension"]).set_index("column")["gap_pp"]
    rb = R.retention_rates(players, "rounds_bucket").set_index("rounds_bucket")
    d1s = R.retention_rates(players, "d1_status").set_index("d1_status")
    d7_back, d7_gone = d1s.loc["Returned Day 1", "retention_7"], d1s.loc["Did not return Day 1", "retention_7"]
    d7_lo, d7_hi = S.wilson_ci(players["retention_7"].sum(), len(players))
    low, all_ = volume.loc["Fewer than 15 rounds (0-14)"], volume.loc["All players"]
    # gate experiment (R5 chain): reports/results.json -> cookie.gate
    g7, g1 = gate["retention_7"], gate["retention_1"]
    sbs, band, nc = gate["srm_by_stratum"], gate["retention_by_rounds_band"], gate["negative_control"]
    nc7, nc_rm = nc["never_reached_30"]["retention_7"], nc["never_reached_30_excess_removed"]["retention_7"]
    b15, b1529, b30 = (band[k]["retention_7"] for k in ("rounds_lt_15", "rounds_15_29", "rounds_ge_30"))
    b30_d1 = band["rounds_ge_30"]["retention_1"]
    dec, dec1 = gate["d7_decomposition"], gate["d1_decomposition"]
    dec_ci, dec1_ci = dec["install_level_effect_ci_if_only_reachers"], dec1["install_level_effect_ci_if_only_reachers"]
    bc, ra = gate["best_case_for_gate_40"], gate["rounds_among_reachers"]
    rs, pg = gate["retest_sizing"], gate["pre_gate_engagement"]
    past40 = ra["share_past_40_rounds"]
    b1528, b29 = band["rounds_15_28"]["retention_7"], band["rounds_29"]["retention_7"]
    n29 = players.loc[rounds == 29, "version"].value_counts()    # 29-round players, recounted from the clean table
    assert (n29["gate_40"], n29["gate_30"]) == (b29["n_t"], b29["n_c"]), "29-round counts differ from results.json"
    rise = max(rs["installs_needed_install_level_5050_if_rise"] / rs["installs_needed_install_level_5050"],
               rs["installs_needed_reacher_analysis_5050_if_rise"] / rs["installs_needed_reacher_analysis_5050"])


    def ci_pp(lo: float, hi: float, nd: int = 2) -> str:    # a 95% CI in pp from proportions, true minus
        return f"{sgn(lo * 100, nd)} to {sgn(hi * 100, nd)}"


    def thousands(x: float) -> str:
        return f"{x / 1000:.0f}K"


    quoted = [
        ("Players after cleaning", "{{n_clean}}", f"{len(players):,}"),
        ("Played at least one round in 14 days", "{{played}}", pct((players["sum_gamerounds"] > 0).mean())),
        ("Players with at least one round in 14 days", "{{played_n}}", f"{(players['sum_gamerounds'] > 0).sum():,}"),
        ("D1 retention", "{{d1}}", pct(players["retention_1"].mean())),
        ("Did not return on Day 1", "{{no_d1_share}}", pct(1 - players["retention_1"].mean())),
        ("Drop, install to Day 1", "{{first_drop}}",
         f"{(f['Installed'] - f['Returned on Day 1']) * 100:.1f} pp"),
        ("D7 retention", "{{d7}}", pct(players["retention_7"].mean())),
        ("D7 retention, 95% CI", "{{d7_ci}}", f"{d7_lo * 100:.1f}–{d7_hi * 100:.1f}%"),
        ("Returned on Day 1 and Day 7", "{{funnel_last}}", pct(f["Returned on Day 1 and Day 7"])),
        ("Drop, Day 1 to Day 1 and Day 7", "{{drop_d1d7}}",
         f"{(f['Returned on Day 1'] - f['Returned on Day 1 and Day 7']) * 100:.1f} pp"),
        ("Share of installs with < 15 rounds", "{{low_share}}", pct(target.mean(), 0)),
        ("Players with < 15 rounds", "{{low_n}}", f"{target.sum():,}"),
        ("D7 of players with < 15 rounds", "{{low_d7}}", pct(base_d7)),
        ("Players with < 15 rounds back on Day 7", "{{low_d7_n}}", f"{players.loc[target, 'retention_7'].sum():,}"),
        ("Max D7 among < 15-round buckets", "{{low_d7_max}}", pct(rb.loc[["0", "1-4", "5-14"], "retention_7"].max())),
        ("D7, 100+ rounds", "{{d7_100}}", pct(rb.loc["100+", "retention_7"])),
        ("< 15 rounds: share of all not back on Day 7", "{{low_lost_share}}", pct(low["lost_d7"] / all_["lost_d7"], 0)),
        ("< 15 rounds: share of D1 non-returners", "{{low_no_d1_share}}", pct(low["no_d1"] / all_["no_d1"], 0)),
        ("D7 ratio, returned vs not on Day 1", "{{d1_ratio}}", f"{d7_back / d7_gone:.1f}×"),
        ("D7, returned on Day 1", "{{d7_yes}}", pct(d7_back)),
        ("D7, did not return on Day 1", "{{d7_no}}", pct(d7_gone)),
        ("D7 gap by Day-1 status, overall", "{{gap_d1_overall}}", f"{(d7_back - d7_gone) * 100:.1f} pp"),
        ("R6 illustrative scenario: pp of D7 per 1 pp of installs shifted between observed groups", "{{scenario}}", f"{d7_back - d7_gone:.2f}"),
        ("Smallest within-bucket Day-1 gap", "{{within_min}}", sgn(d1_gap.iloc[1:]["gap_pp"].min(), 1)),
        ("Largest within-bucket Day-1 gap", "{{within_max}}", sgn(d1_gap.iloc[1:]["gap_pp"].max(), 1)),
        ("D7 gap, engagement depth", "{{gap_rounds}}", f"{gap_dim['rounds_bucket']:.0f} pp"),
        ("D7 gap, Day-1 status", "{{gap_d1}}", f"{gap_dim['d1_status']:.0f} pp"),
        ("D7 gap, version (raw)", "{{gap_version}}", f"{gap_dim['version']:.1f} pp"),
        ("Part of the version gap the gate could explain (size)", "{{could_be_gate}}",
         f"{abs(dec['within_reached_30']) * 100:.1f} pp"),
        ("R6 sample, +0.5 pp: target players (rounded)", "{{n_target_05}}", thousands(n_needed[C.ONBOARD_LIFT_ABS])),
        ("R6 sample, +0.5 pp: installs (rounded)", "{{installs_05}}", thousands(installs_needed[C.ONBOARD_LIFT_ABS])),
        ("R6 sample, +0.5 pp: target players", "{{n_target_05_exact}}", f"{n_needed[C.ONBOARD_LIFT_ABS]:,}"),
        ("R6 sample, +0.5 pp: installs", "{{installs_05_exact}}", f"{installs_needed[C.ONBOARD_LIFT_ABS]:,}"),
        ("+0.5 pp as a relative lift", "{{rel_05pp}}", f"+{C.ONBOARD_LIFT_ABS / base_d7:.0%}"),
        ("+1 pp as a relative lift", "{{rel_1pp}}", f"+{0.01 / base_d7:.0%}"),
        ("Dropped player's rounds", "{{outlier_rounds}}", f"{outlier['sum_gamerounds']:,}"),
        ("Dropped player's rounds per day", "{{outlier_per_day}}", f"{outlier['sum_gamerounds'] / 14:,.0f}"),
        ("Median rounds", "{{median_rounds}}", f"{rounds.median():.0f}"),
        ("Reached 30 rounds", "{{reach30}}", pct((rounds >= 30).mean(), 0)),
        ("Reached 40 rounds", "{{reach40}}", pct((rounds >= 40).mean(), 0)),
        ("Max gap between version curves", "{{curve_gap}}", f"{gap.abs().max():.1f} pp"),
        ("Rounds at the max gap", "{{curve_gap_at}}", f"{gap_at}"),
        ("D7, 0-4 rounds", "{{rc_low}}", pct(by_bin["retention_7"].iloc[0])),
        ("D7, 145-149 rounds", "{{rc_high}}", pct(by_bin["retention_7"].iloc[150 // 5 - 1])),
        ("D7 actives who skipped Day 1, share", "{{skipped_share}}", pct(skipped_d1.sum() / active_d7.sum(), 0)),
        ("D7 actives who skipped Day 1", "{{skipped_n}}", f"{skipped_d1.sum():,}"),
        ("Players active on Day 7", "{{d7_active_n}}", f"{active_d7.sum():,}"),
        ("0-round players flagged D1", "{{zero_d1}}", f"{zero['retention_1'].sum():,}"),
        ("0-round players flagged D7", "{{zero_d7}}", f"{zero['retention_7'].sum():,}"),
        ("0-round D1 flags, share of players", "{{zero_flag_share}}", pct(zero["retention_1"].sum() / len(players))),
        ("gate_30 players, raw file", "{{n30}}", f"{n30_raw:,}"),
        ("gate_40 players, raw file", "{{n40}}", f"{n40_raw:,}"),
        ("Gate SRM p-value, raw counts", "{{srm_p}}", f"{srm['p_value']:.4f}"),
        ("SRM warning threshold", "{{srm_warn}}", f"{srm['warn_threshold']:g}"),
        ("SRM failure threshold", "{{srm_fail}}", f"{srm['threshold']:g}"),
        ("Alpha (config.yaml)", "{{alpha}}", f"{C.ALPHA:g}"),
        ("Power (config.yaml)", "{{power}}", f"{C.POWER:.0%}"),
        ("Gate: extra gate_40 installs, raw log", "{{excess_raw}}", f"{n40_raw - n30_raw:,}"),
        ("Gate: extra gate_40 installs, analysed table", "{{excess_clean}}", f"{bc['excess_players_gate_40']:,}"),
        ("Gate: net excess, < 15 rounds", "{{excess_lt15}}", f"{sbs['rounds_lt_15']['net_excess_t']:,}"),
        ("Gate: net excess, < 15 rounds (signed)", "{{ex15_s}}", sgn(sbs["rounds_lt_15"]["net_excess_t"], 0)),
        ("Gate: net excess, 15–29 rounds (signed)", "{{ex1529_s}}", sgn(sbs["rounds_15_29"]["net_excess_t"], 0)),
        ("Gate: net excess, 30+ rounds (signed)", "{{ex30_s}}", sgn(sbs["rounds_ge_30"]["net_excess_t"], 0)),
        ("Gate: p vs 50/50, < 15 rounds (descriptive)", "{{p15}}", f"{sbs['rounds_lt_15']['p_value']:.4f}"),
        ("Gate: p vs 50/50, 15–29 rounds (descriptive)", "{{p1529}}", f"{sbs['rounds_15_29']['p_value']:.2f}"),
        ("Gate: p vs 50/50, 30+ rounds (descriptive)", "{{p30}}", f"{sbs['rounds_ge_30']['p_value']:.2f}"),
        ("Gate: pre-gate rounds, Mann-Whitney p", "{{pregate_p}}", f"{pg['mannwhitney_p']:.3f}"),
        ("Gate: pre-gate rounds within < 30 rounds, Mann-Whitney p", "{{pregate_lt30_p}}",
         f"{pg['mannwhitney_p_within_lt_30']:.2f}"),
        ("Gate: D7, gate_40", "{{g40_d7}}", pct(g7["rate_t"], 2)),
        ("Gate: D7, gate_30", "{{g30_d7}}", pct(g7["rate_c"], 2)),
        ("Gate: naive D7 gap", "{{gate_naive}}", f"{sgn(g7['abs_lift'] * 100)} pp"),
        ("Gate: naive D7 gap, size", "{{gate_naive_abs}}", f"{abs(g7['abs_lift']) * 100:.2f} pp"),
        ("Gate: naive D7 gap, 95% CI", "{{naive_ci}}", ci_pp(g7["abs_ci_low"], g7["abs_ci_high"])),
        ("Gate: negative control (< 30 rounds), D7 gap size", "{{nc_abs}}", f"{abs(nc7['abs_lift']) * 100:.2f} pp"),
        ("Gate: negative control, CI low", "{{nc_lo}}", sgn(nc7["abs_ci_low"] * 100)),
        ("Gate: negative control, CI high", "just below 0",
         "just below 0" if -0.005 < nc7["abs_ci_high"] * 100 < 0 else sgn(nc7["abs_ci_high"] * 100)),
        ("Gate: negative control, p", "{{nc_p}}", f"{nc7['p_value']:.3f}"),
        ("Gate: D7 gap, 15–29 rounds", "{{b1529_d7}}", sgn(b1529["abs_lift"] * 100)),
        ("Gate: D7 gap, 15–29 rounds, 95% CI", "{{b1529_ci}}", ci_pp(b1529["abs_ci_low"], b1529["abs_ci_high"])),
        ("Gate: D7 gap, 15–29 rounds, p", "{{b1529_p}}", f"{b1529['p_value']:.2g}"),
        ("Gate: D7 gap, < 15 rounds", "{{b15_d7}}", sgn(b15["abs_lift"] * 100)),
        ("Gate: D7 gap, < 15 rounds, p", "{{b15_p}}", f"{b15['p_value']:.2f}"),
        ("Gate: D7 gaps of the 15–29 and < 15 bands, p for their difference", "{{band_diff_p}}",
         f"{gate['d7_band_gap_difference_15_29_vs_lt_15']['p_value']:.2g}"),
        ("Gate: negative control without the net < 15 excess", "{{nc_rm}}", sgn(nc_rm["abs_lift"] * 100)),
        ("Gate: negative control without the net < 15 excess, p", "{{nc_rm_p}}", f"{nc_rm['p_value']:.2f}"),
        ("Gate: decomposition, player mix (pp)", "{{dec_mix}}", sgn(dec["composition"] * 100)),
        ("Gate: decomposition, never met a gate (pp)", "{{dec_never}}", sgn(dec["within_never_reached_30"] * 100)),
        ("Gate: decomposition, could meet the gate (pp per install)", "{{dec_reach}}",
         sgn(dec["within_reached_30"] * 100)),
        ("Gate: could meet the gate, 1 decimal", "{{dec_reach_1dp}}", sgn(dec["within_reached_30"] * 100, 1)),
        ("Gate: could meet the gate, 95% CI", "{{dec_ci}}", ci_pp(*dec_ci)),
        ("Gate: share of the naive gap where the gate cannot act (nearest 10%)", "{{share_not_gate}}",
         f"{round((dec['composition'] + dec['within_never_reached_30']) / dec['naive_diff'], 1):.0%}"),
        ("Gate: fewer Day-7 players per 10,000 installs", "{{per10k}}", f"{-dec['within_reached_30'] * 10_000:.0f}"),
        ("Gate: per 10,000, 95% CI (fewer)", "{{per10k_lo}}", f"{-dec_ci[0] * 10_000:.0f}"),
        ("Gate: per 10,000, 95% CI (more)", "{{per10k_hi}}", f"{dec_ci[1] * 10_000:.0f}"),
        ("Gate: D7 gap, 30+ rounds", "{{b30_d7}}", sgn(b30["abs_lift"] * 100)),
        ("Gate: D7 gap, 30+ rounds, 95% CI", "{{b30_ci}}", ci_pp(b30["abs_ci_low"], b30["abs_ci_high"])),
        ("Gate: best case for gate_40, D7 gap", "{{bc}}", sgn(bc["d7_diff_if_excess_removed"] * 100)),
        ("Gate: best case for gate_40, 95% CI", "{{bc_ci}}", ci_pp(*bc["ci"])),
        ("Gate: best case for gate_40, p", "{{bc_p}}", f"{bc['p_value']:.3f}"),
        ("Gate: naive D1 gap", "{{d1_naive}}", sgn(g1["abs_lift"] * 100)),
        ("Gate: naive D1 gap, 95% CI", "{{d1_ci}}", ci_pp(g1["abs_ci_low"], g1["abs_ci_high"])),
        ("Gate: D1 decomposition, player mix", "{{d1_mix}}", sgn(dec1["composition"] * 100)),
        ("Gate: D1 gap, 30+ rounds", "{{d1_30}}", sgn(b30_d1["abs_lift"] * 100)),
        ("Gate: D1 gap, 30+ rounds, 95% CI", "{{d1_30_ci}}", ci_pp(b30_d1["abs_ci_low"], b30_d1["abs_ci_high"])),
        ("Gate: D1, could meet the gate (pp per install)", "{{d1_could}}", sgn(dec1["within_reached_30"] * 100)),
        ("Gate: D1, could meet the gate, 95% CI", "{{d1_could_ci}}", ci_pp(*dec1_ci)),
        ("Gate: players with exactly 29 rounds, gate_40", "{{n29_t}}", f"{n29['gate_40']:,}"),
        ("Gate: players with exactly 29 rounds, gate_30", "{{n29_c}}", f"{n29['gate_30']:,}"),
        ("Gate: D7 gap, 15–28 rounds", "{{b1528_d7}}", sgn(b1528["abs_lift"] * 100)),
        ("Gate: D7 gap, 15–28 rounds, 95% CI", "{{b1528_ci}}", ci_pp(b1528["abs_ci_low"], b1528["abs_ci_high"])),
        ("Gate: rounds, all players, mean difference", "{{rounds_all}}", sgn(gate["rounds"]["mean_diff"])),
        ("Gate: rounds, all players, 95% CI", "{{rounds_all_ci}}",
         " to ".join(sgn(x, 1) for x in gate["rounds"]["mean_diff_boot_ci"])),
        ("Gate: rounds among 30+ players, median gate_40", "{{med_t}}", f"{ra['median_t']:.0f}"),
        ("Gate: rounds among 30+ players, median gate_30", "{{med_c}}", f"{ra['median_c']:.0f}"),
        ("Gate: rounds among 30+ players, Mann-Whitney p", "{{med_p}}", f"{ra['mannwhitney_p']:.4f}"),
        ("Gate: at least 40 rounds among 30+ players, gate_40", "{{past40_t}}", pct(past40["rate_t"])),
        ("Gate: at least 40 rounds among 30+ players, gate_30", "{{past40_c}}", pct(past40["rate_c"])),
        ("Gate: at least 40 rounds, difference", "{{past40_diff}}", f"{sgn(past40['abs_lift'] * 100, 1)} pp"),
        ("Gate: at least 40 rounds, 95% CI", "{{past40_ci}}", ci_pp(past40["abs_ci_low"], past40["abs_ci_high"], 1)),
        ("Gate: rounds among 30+ players, mean difference", "{{mean30_diff}}", sgn(ra["mean_diff"], 1)),
        ("Gate: rounds among 30+ players, mean difference 95% CI", "{{mean30_ci}}",
         " to ".join(sgn(x, 1) for x in ra["mean_diff_boot_ci"])),
        ("Re-test: smallest D7 change per install", "{{sesoi}}", f"{rs['smallest_d7_change_per_install'] * 100:.1f} pp"),
        ("Re-test: that change relative to gate_30's D7", "{{sesoi_rel}}",
         pct(rs["smallest_d7_change_per_install"] / rs["baseline_d7_install"])),
        ("Re-test: gate_30's D7", "{{g30_d7_1dp}}", pct(rs["baseline_d7_install"])),
        ("Re-test: players who reach level 30 needed (50/50)", "{{retest_reachers}}",
         thousands(rs["reachers_needed_5050"])),
        ("Re-test: installs, primary analysis among them (50/50)", "{{retest_reach_installs}}",
         thousands(rs["installs_needed_reacher_analysis_5050"])),
        ("Re-test: installs, analysed over all installs (50/50)", "{{retest_all}}",
         thousands(rs["installs_needed_install_level_5050"])),
        ("Re-test: extra sample a rise needs, at most (larger of the two analyses)", "{{rise_more}}", f"{rise - 1:.0%}"),
        ("Re-test: installs for a rise, analysed over all installs (50/50)", "{{retest_all_rise}}",
         thousands(rs["installs_needed_install_level_5050_if_rise"])),
        ("Re-test: installs for a rise, primary analysis among reachers (50/50)", "{{retest_reach_rise}}",
         f"{rs['installs_needed_reacher_analysis_5050_if_rise'] / 1000:.1f}K"),
        ("Re-test: share of installs reaching level 30 (this cohort)", "{{share_reached}}", pct(rs["share_reached_30"])),
    ]
    check = pd.DataFrame(quoted, columns=["Number", "Quoted in text", "Recomputed"]).set_index("Number")
    assert check.index.is_unique, "each quoted number needs its own label"
    check["Match"] = check["Quoted in text"] == check["Recomputed"]
    assert check["Match"].all(), f"Text and data disagree:\\n{check[~check['Match']].to_string()}"
    print(f"All {len(check)} numbers quoted in the text match the data.")
    with pd.option_context("display.max_rows", None):    # show every row, not pandas' truncated view
        display(check)
    """),
]


def build() -> None:
    used_md: set[str] = set()
    used_code: set[str] = set()
    cells = []
    for kind, text in CELLS:
        if kind == "md":
            cells.append(new_markdown_cell(fill(text, used_md)))
        else:
            cells.append(new_code_cell(fill(text, used_code)))
    missing = used_md - used_code
    assert not missing, f"Quoted in text but never checked: {sorted(missing)}"
    unused = set(Q) - used_md
    assert not unused, f"Defined but never quoted: {sorted(unused)}"
    for i, c in enumerate(cells):
        assert "{{" not in c.source, c.source[:200]
        c["id"] = f"ret-{i:02d}"  # deterministic ids keep git diffs readable across rebuilds
    nb = new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "title": NB_TITLE,
    })
    nbformat.validate(nb)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, OUT)
    print(f"wrote {OUT} ({len(cells)} cells)")


if __name__ == "__main__":
    build()
