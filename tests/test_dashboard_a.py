"""Smoke and interaction tests for dashboard pages 1, 2, 3 and 7 (Streamlit AppTest).

Each page is run on its own (dashboard/ and the repo root on sys.path, like
`streamlit run dashboard/app.py` sets up), must raise no exception, must show the
key numbers in reports/results.json (and reports/tables/), must recompute its
output when an interactive control changes, and must not repeat wording withdrawn
in v2, v3 and v3.1. Pages only read the caches in data/processed/ and
reports/results.json, so build those first (`python run.py --only analysis`).

Run:  .venv/bin/python tests/test_dashboard_a.py      (pytest also collects the test_* functions)
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
for _p in (str(DASH), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import stats as S  # noqa: E402

TIMEOUT = 120          # seconds per script run (cold imports + catalog build on the first run)
P1_FIRST_PAINT_MAX = 10.0
RESULTS = json.loads((ROOT / "reports" / "results.json").read_text())
AD, CK = RESULTS["ad"], RESULTS["cookie"]
GATE = CK["gate"]
EARLY = CK["early_churn_segment"]
RETEST = GATE["retest_sizing"]
DAY_TABLE = pd.read_csv(ROOT / "reports" / "tables" / "ad_lift_by_most_ads_day.csv").set_index("most_ads_day")

# Wording withdrawn in v2 / v3 / v3.1; none may come back on these pages.
STALE = {
    # still withdrawn from v2
    "saturation claim": re.compile(r"saturat", re.I),
    "'8 of 24 hours' argument": re.compile(r"\b8 of 24\b"),
    "post-hoc power": re.compile(r"achieved power|power at the observed effect is \d", re.I),
    "'barely matters'": re.compile(r"barely matters", re.I),
    "'370 D7 players' figure": re.compile(r"\b370\b"),
    "status label WARN": re.compile(r"\bWARN\b"),
    "p-value printed as 0": re.compile(r"\bp\s*=\s*0(?:\.0+)?(?!\.?\d)"),
    "bare dollar sign": re.compile(re.escape("\N{DOLLAR SIGN}")),
    "install-date cohorts": re.compile(r"\bcohorts\b", re.I),
    # v3: gate claims
    "'worst case' for the best-case bound": re.compile(r"worst[ -]case", re.I),
    "'no engagement difference'": re.compile(r"no engagement difference", re.I),
    "'no sign of (any) benefit' (write: no sign of a retention benefit)": re.compile(r"no sign of (?:any|a) benefit",
                                                                                   re.I),
    "'best estimate' of the gate effect": re.compile(r"best estimate", re.I),
    "'explains about 60%' attributed to the extra installs": re.compile(r"explains? (?:about |~|≈)?60\s*%", re.I),
    "'Every cut points the same way'": re.compile(r"every cut points", re.I),
    "'762 of the 790' (implies identified players)": re.compile(r"\b762 of (?:the |its )?(?:789|790)\b"),
    "causal wording on the uncertified gate gap": re.compile(
        r"costs 0\.8|gate_40 costs?\b|\blowered\b|loses D7 players|lost D7 players", re.I),
    # v3: re-test / R6 sizing, gate scaling, D1
    "withdrawn re-test sizes": re.compile(r"276K|276,092|101,852|\b102K\b|102,000"),
    "R6 sized at 14,250": re.compile(r"14,250"),
    "'145 per 45K' scaling": re.compile(r"\b145 (?:fewer Day-7 players )?per 45", re.I),
    "'A D1 drop of up to 1.2 pp'": re.compile(r"D1 drop of up to", re.I),
    # v3: labels and stale numbers
    "'6 night hours'": re.compile(r"\b\d+ night hours|night hours have zero", re.I),
    "'100% at 50/50' (write ≈100%)": re.compile(r"(?<![≈~\d.])100% (?:power )?at 50/50"),
    "old segment-vs-rest points": re.compile(r"\+0\.92 pp|[−-]0\.76 pp|\+0\.3[23] pp"),
    # v3: R3, threshold and MDE wording
    "daypart / time-of-day test as R3": re.compile(r"daypart test|time-of-day test", re.I),
    "'set by the business before the test'": re.compile(r"set by the business", re.I),
    "MDE-vs-estimate comparison": re.compile(r"well below (?:that|the MDE)|less than half the D7 MDE|"
                                             r"not powered to measure", re.I),
    # v3 persona: the game is the company's other product, not a stand-in
    "persona: 'not our app' / 'standing in'": re.compile(r"not our app|standing in for our app", re.I),
    # v3.1 (precision of wording; delta rows a-n, plus "by Day 7")
    "(a) 'the same −0.87 pp gap' (write: a similar gap)": re.compile(r"\bsame (?:[−-]0\.87 pp )?gap\b", re.I),
    "(b) 'the gap sits with … not with the extra installs'": re.compile(r"gap sits with|not with the extra", re.I),
    "(c) negative control 'points the same way'": re.compile(r"points the same way", re.I),
    "(d) cause of the imbalance stated as fact": re.compile(
        r"something added|received (?:≈?[\d,]+ )?extra low-engagement|an assignment or logging problem|"
        r"comes from assignment or logging|the assignment / logging problem", re.I),
    "(e) D1 guardrail quoted from the 30+ band": re.compile(r"where the gate can act[^.]{0,40}\bD1\b|\bD1 \+0\.08 pp"),
    "(f) 'the plausible gate effect'": re.compile(r"plausible gate effect", re.I),
    "(g) 'cannot have reached level 30' (write: got past)": re.compile(r"cannot have reached level 30", re.I),
    "(h) 29-round edge case 'pushes in the opposite direction'": re.compile(r"opposite direction", re.I),
    "(j) '≤ 20 ads: a lift above … would have shown'": re.compile(r"would have shown", re.I),
    "(k) daypart 'entirely' / 'alone' from Night": re.compile(r"entirely (?:by|from) Night|from Night alone", re.I),
    "(l) 'no hour effect'": re.compile(r"\bno hour effect", re.I),
    "(m) gate gap attributed to the assignment problem": re.compile(
        r"mostly reflects unbalanced|is the assignment problem|most of the gate gap", re.I),
    "(n) 'extra low-engagement installs' / 'a net 762 of them'": re.compile(
        r"\d+ extra low-engagement installs|a net 762 of them", re.I),
    "'back by Day 7' (classic D7 is play on Day 7)": re.compile(r"\b(?:back|retained|returned|played) by Day 7",
                                                                re.I),
}
# p-value of the gate SRM on cleaned counts: allowed once, as a labelled footnote (page 2)
CLEANED_P = f"{S.srm_check(GATE['players']['gate_40'], GATE['players']['gate_30'], 0.5)['p_value']:.4f}"


# ------------------------------------------------------------------ helpers
def run_page(name: str) -> AppTest:
    at = AppTest.from_file(str(DASH / "views" / name), default_timeout=TIMEOUT)
    at.run()
    assert_ok(at, name)
    return at


def assert_ok(at: AppTest, where: str) -> None:
    assert not at.exception, f"{where}: " + "; ".join(str(e.value) for e in at.exception)


def metric_el(at: AppTest, label_start: str):
    hits = [m for m in at.metric if m.label.startswith(label_start)]
    assert hits, f"no metric starting with {label_start!r}: {[m.label for m in at.metric]}"
    return hits[0]


def metric(at: AppTest, label_start: str) -> str:
    return metric_el(at, label_start).value


def takeaways(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown if "class='takeaway'" in m.value]


def chart_titles(at: AppTest) -> list[str]:
    return [json.loads(c.proto.spec)["layout"]["title"]["text"] for c in at.get("plotly_chart")]


def rendered_text(at: AppTest) -> str:
    """Every piece of text the page shows: markdown, captions, alerts, metrics (incl. help), tables, charts."""
    parts = [m.value for m in at.markdown if not m.value.lstrip().startswith("<style>")]
    parts += [c.value for c in at.caption]
    for kind in ("success", "info", "warning", "error"):
        parts += [x.value for x in getattr(at, kind)]
    parts += [f"{m.label} {m.value} {m.proto.delta} {m.help or ''}" for m in at.metric]
    parts += [t.value.to_string() for t in at.table] + [d.value.to_string() for d in at.dataframe]
    parts += [" ".join(map(str, t.value.to_numpy().ravel())) for t in at.table]  # full cells (to_string truncates)
    parts += chart_titles(at) + [e.label for e in at.expander]
    return "\n".join(parts)


def flat_text(at: AppTest) -> str:
    """rendered_text with every run of whitespace collapsed to one space (markdown wraps long sentences)."""
    return " ".join(rendered_text(at).split())


def assert_no_stale_claims(at: AppTest, where: str) -> None:
    text = flat_text(at)
    for name, rx in STALE.items():
        hits = rx.findall(text)
        assert not hits, f"{where}: withdrawn wording ({name}): {hits}"


def assert_one_count_basis_per_sentence(at: AppTest, where: str) -> None:
    """gate_40's excess is 789 in the raw log and 790 after cleaning: never both in one sentence."""
    for sentence in re.split(r"(?<=[.;])\s+", flat_text(at)):
        assert not ("789" in sentence and "790" in sentence), f"{where}: two count bases in one sentence: {sentence}"


def assert_page_frame(at: AppTest, title: str, question_start: str) -> None:
    """Every page: title, the one-sentence question, a takeaway under each chart, 'How to read this'."""
    assert at.title[0].value == title
    assert any("page-question" in m.value and question_start in m.value for m in at.markdown), "question line missing"
    assert "How to read this" in [e.label for e in at.expander]
    assert len(takeaways(at)) >= len(at.get("plotly_chart")) > 0, "every chart needs a takeaway"


def sgn(x: float, nd: int = 2) -> str:
    return f"{x:+.{nd}f}".replace("-", "−")


def pp(x: float, nd: int = 2) -> str:
    """Signed percentage points with a true minus, as the pages print them: −0.82 pp."""
    return f"{sgn(x * 100, nd)} pp"


def ci(lo: float, hi: float, unit: str = " pp") -> str:
    return f"95% CI {sgn(lo * 100)} to {sgn(hi * 100)}{unit}"


def thousands(n: float) -> str:
    return f"{n / 1e3:,.0f}K"


# ------------------------------------------------------------------ page 1
def test_p1_overview() -> None:
    t0 = time.perf_counter()
    at = run_page("p1_overview.py")
    elapsed = time.perf_counter() - t0
    assert elapsed < P1_FIRST_PAINT_MAX, f"Overview took {elapsed:.1f}s on a cold start"
    assert_page_frame(at, "Overview", "What did we find")
    assert_no_stale_claims(at, "p1")
    assert_one_count_basis_per_sentence(at, "p1")
    text = flat_text(at)

    t, bz = AD["test"], AD["business"]
    dec = GATE["d7_decomposition"]
    assert len(at.metric) == 8
    assert metric(at, "Conversion lift") == pp(t["abs_lift"])
    assert metric(at, "Incremental conversions") == f"{bz['incremental_conversions']['point']:,.0f}"
    share = metric_el(at, "Incremental share")
    assert share.value == f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}%"
    assert f"{bz['last_touch_overstatement_x']:.1f}×" in share.proto.delta
    lt = bz["last_touch_overstatement_ci"]
    assert f"95% CI {lt[0]:.1f}–{lt[1]:.1f}×" in share.help
    be = bz["breakeven_cpm_usd"]["point"]
    assert metric(at, "Breakeven CPM") == f"USD {be:.2f}"
    # early-churn KPI: 47% of installs, 2.3% back on Day 7 (cookie.early_churn_segment)
    early_m = metric_el(at, "Installs with < 15 rounds")
    assert early_m.value == f"{EARLY['share_of_installs'] * 100:.0f}%" == "47%"
    assert f"{EARLY['retention_7'] * 100:.1f}%" in early_m.proto.delta and "2.3%" in early_m.proto.delta
    # gate card: the part the gate could explain (not the naive gap), with its CI, not certified
    gate_m = metric_el(at, "D7 gap the gate could explain")
    assert gate_m.value == pp(dec["install_level_effect_if_only_reachers"]) == "−0.32 pp"
    lo, hi = dec["install_level_effect_ci_if_only_reachers"]
    assert gate_m.proto.delta == ci(lo, hi) == "95% CI −0.71 to +0.07 pp"
    srm = GATE["srm"]
    assert "Not certified" in gate_m.help and "not an estimate of its effect" in gate_m.help
    assert f"{srm['n_t']:,} vs {srm['n_c']:,}, {srm['n_t'] - srm['n_c']} more in gate_40" in gate_m.help
    assert srm["n_t"] - srm["n_c"] == GATE["excess_players_raw"] == 789
    assert any(f"naive gap is {pp(dec['naive_diff'])}" in c.value and "Not certified" in c.value
               for c in at.caption)

    badges = [m.value for m in at.markdown if "-badge[" in m.value]
    assert len(badges) == 5, badges
    assert any("keep gate_30" in b and "not certified" in b for b in badges)
    # Q1: incremental conversions in round numbers, attribution with its CI, holdout cost with the as-run 4% arm
    hold = bz["always_on_holdout_cost"]
    assert "≈4,300** incremental conversions (95% CI 3,300–5,300)" in text
    assert f"≈{hold['conversions_forgone']:,.0f} conversions per 588K-user flight" in text
    assert f"{hold['as_run_control_share'] * 100:.0f}% PSA arm already forgoes " \
           f"≈{hold['as_run_control_conversions_forgone']:,.0f}" in text
    assert "most likely a fixed quota" in text
    # Q2: heavy users
    con = AD["heterogeneity"]["exposure_bucket"]["concentration"]
    assert "lift lives in heavy users" in text and f"{con['share_users_le_20_ads'] * 100:.0f}%" in text
    assert f"{con['share_incremental_conversions_36_200'] * 100:.0f}%** of the bucket-by-bucket" in text
    # ≤ 20 ads: the pooled estimate with its CI, no MDE comparison (v3.1 row j)
    le20 = con["le_20_ads_pooled"]
    assert f"≤ 20 ads show no lift we could measure ({pp(le20['abs_lift'])}, " \
           f"{ci(le20['abs_ci_low'], le20['abs_ci_high'], unit='')})" in text
    assert "(−0.02 pp, 95% CI −0.14 to +0.09)" in text
    # Q3: day contrasts recomputed live = the committed table (raw differences), with the Tuesday caveat
    for day in AD["heterogeneity"]["most_ads_day"]["segments_differing_holm"]:
        assert f"{day}-peak users {pp(DAY_TABLE.loc[day, 'diff_vs_rest'])}" in text
    assert "Tuesday-peak users +0.95 pp" in text and "Thursday-peak users −0.74 pp" in text
    tue = DAY_TABLE.loc["Tuesday"]
    assert f"{int(tue['conv_c'])} conversions among {int(tue['n_c']):,} users, {tue['rate_c'] * 100:.2f}%" in text
    assert "randomizes the delivery schedule" in text
    # hour: no evidence (row l); daypart: driven by Night, not "entirely" (row k)
    assert "**Hour:** no evidence the lift differs (interaction p = 0.18)" in text
    assert "**Daypart:** p = 0.013 is driven by Night (0–5), where the control arm has 1 conversion among 735 users" \
        in text
    # Q4 / R6: early-churn segment and the onboarding test size
    r6 = EARLY["onboarding_test_sizing"]
    assert f"≈{thousands(r6['players_needed_5050'])} target players (≈{thousands(r6['installs_needed_5050'])} " \
           "installs)" in text
    # Q5 / R5: ≈790 extra installs, net excess, raw-count WARNING, the part the gate could explain, new re-test size
    assert f"≈{GATE['best_case_for_gate_40']['excess_players_gate_40']} extra installs" in text
    assert f"extra installs**, with a net excess of {GATE['srm_by_stratum']['rounds_lt_15']['net_excess_t']} among " \
           "players with < 15 rounds" in text
    assert f"p = {srm['p_value']:.4f}" in text and srm["status"] == "WARNING" and "**WARNING**" in text
    assert "**−0.32 pp per install** (95% CI −0.71 to +0.07)" in text
    assert "About 60% of the naive gap sits where the gate cannot act" in text
    assert "The groups were unbalanced, and about 60% of the gap sits where the gate cannot act" in text  # row m
    assert "No sign of a retention benefit" in text
    assert f"≈{thousands(RETEST['installs_needed_reacher_analysis_5050'])} installs at 50/50" in text
    assert f"≈{thousands(RETEST['reachers_needed_5050'])} of them" in text
    assert f"≈{thousands(RETEST['installs_needed_install_level_5050'])} if analysed over all installs" in text
    assert "company's mobile game" in text and "different product" in text
    assert any("Users shown ads converted at" in x for x in takeaways(at))

    # interactive: the value-per-conversion assumption drives the breakeven CPM and the holdout cost (linear)
    at.number_input(key="p1_value_per_conversion").set_value(100.0).run()
    assert_ok(at, "p1 after value change")
    ratio = 100 / RESULTS["config"]["value_per_conversion_usd"]
    assert metric(at, "Breakeven CPM at USD 100") == f"USD {be * ratio:.2f}"
    holdout_usd = hold["value_forgone_usd"] * ratio
    assert f"USD {holdout_usd / 1e3:,.1f}K at USD 100" in flat_text(at)


# ------------------------------------------------------------------ page 2
def test_p2_data_sanity() -> None:
    at = run_page("p2_data_sanity.py")
    assert_page_frame(at, "Data & Sanity Checks", "Can we trust the data")
    assert_no_stale_claims(at, "p2")
    assert_one_count_basis_per_sentence(at, "p2")
    text = flat_text(at)
    # the post-cleaning gate SRM p-value may appear once, as a labelled footnote
    assert text.count(CLEANED_P) == 1 and f"Footnote, cleaned counts: without the player it would be p = {CLEANED_P}" \
        in text
    srm_ad, srm_gate = AD["srm"], GATE["srm"]

    # defaults: the ad split passes but is uninformative (most likely a fixed quota); the gate is in the warning band
    assert srm_ad["status"] == "PASS" and srm_ad["is_nearest_integer_to_target"]
    assert len(at.info) == 1 and "PASS, but uninformative" in at.info[0].value
    for s in (f"{srm_ad['deviation_users']:.2f} off", f"about {srm_ad['sd_users_under_random_assignment']:,.0f}",
              f"{srm_ad['prob_exactly_nearest_integer'] * 100:.2f}%", "most likely set by a fixed quota",
              "Fixed arm sizes are a valid design"):
        assert s in at.info[0].value, (s, at.info[0].value)
    assert len(at.warning) == 1 and "WARNING" in at.warning[0].value and "gate_40" in at.warning[0].value
    assert len(at.success) == 0 and len(at.error) == 0
    assert [m.value for m in at.metric if m.label == "p-value"] == [f"{srm_ad['p_value']:.4f}",
                                                                    f"{srm_gate['p_value']:.4f}"]
    counts = next(d.value for d in at.dataframe
                  if "Planned" in d.value.columns and "gate_40" in d.value["Arm"].tolist()).set_index("Arm")
    assert counts.loc["gate_40", "Difference"] == f"{srm_gate['n_t'] - srm_gate['expected_t']:+,.2f}"
    gap_c = srm_gate["n_c"] - srm_gate["expected_c"]
    assert counts.loc["gate_30", "Difference"] == f"{gap_c:+,.2f}".replace("-", "−")
    gap_sd = (srm_gate["n_t"] - srm_gate["expected_t"]) / S.quota_exactness(
        srm_gate["n_t"], srm_gate["n_c"], srm_gate["intended_share_t"])["sd_users_under_random_assignment"]
    assert f"{gap_sd:.1f} times the typical chance gap" in at.warning[0].value
    assert (srm_gate["n_t"], srm_gate["n_c"]) == (GATE["players_raw"]["gate_40"], GATE["players_raw"]["gate_30"])

    # where is the gate imbalance? post-hoc subsets: counts, net excess, descriptive p, never a PASS/WARNING/FAIL
    def strata_table() -> pd.DataFrame:
        return next(d.value for d in at.dataframe if "Net excess" in d.value.columns)

    strata = strata_table().set_index("Players, by rounds in first 14 days")
    assert "Status" not in strata.columns
    sbs = GATE["srm_by_stratum"]
    rows = (("All players", None), ("< 30 rounds (never met a gate)", "rounds_lt_30"),
            ("· of which < 15 rounds", "rounds_lt_15"), ("· of which 15–29 rounds", "rounds_15_29"),
            ("30+ rounds (could have reached level 30)", "rounds_ge_30"))
    assert list(strata.index) == [label for label, _ in rows]
    for label, key in rows:
        s = srm_gate if key is None else sbs[key]
        row = strata.loc[label]
        assert (row["gate_40"], row["gate_30"]) == (f"{s['n_t']:,}", f"{s['n_c']:,}")
        assert row["Net excess"] == f"{s['n_t'] - s['n_c']:+,}".replace("-", "−")
        if key is not None:
            assert s["net_excess_t"] == s["n_t"] - s["n_c"]
            assert "chosen after seeing the warning" in row["What the p-value is"]
        assert row["p-value"] == ("< 0.0001" if s["p_value"] < 1e-4 else f"{s['p_value']:.4f}")
    cells = set(strata.to_numpy().ravel())
    assert not cells & {"PASS", "WARNING", "FAIL"}, "rounds-band subsets must not carry SRM status labels"
    assert strata.loc["· of which < 15 rounds", "Net excess"] == "+762"
    assert strata.loc["· of which 15–29 rounds", "Net excess"] == "+70"
    assert strata.loc["30+ rounds (could have reached level 30)", "Net excess"] == "−43"
    assert sbs["rounds_lt_15"]["net_excess_t"] == GATE["excess_players_with_lt_15_rounds"]
    tk = next(x for x in takeaways(at) if "net excess" in x)
    assert "the net excess is +762 among players with < 15 rounds" in tk
    assert "same imbalance seen as a distribution, not independent evidence" in tk
    assert f"gate_40 has {GATE['excess_players_raw']} more installs than gate_30 in the raw log" in tk
    assert "chosen after seeing the warning" in text
    # v3.1 rows g / h: < 30 rounds "cannot have got past level 30"; the 29-round edge case and the 15-28 sensitivity
    assert "a player with fewer than 30 rounds cannot have got past level 30" in text
    band = GATE["retention_by_rounds_band"]
    n29, d1528 = band["rounds_29"]["retention_7"], band["rounds_15_28"]["retention_7"]
    edge = next(c.value for c in at.caption if c.value.startswith("Edge case"))
    assert "close to, not exactly, gate-free" in edge
    assert f"no pile-up at 29 rounds ({n29['n_t']:,} in gate_40 vs {n29['n_c']:,} in gate_30)" in edge
    assert f"15–28 band still shows D7 {abs(d1528['abs_lift']) * 100:.2f} pp lower in gate_40 " \
           f"({ci(d1528['abs_ci_low'], d1528['abs_ci_high'])})" in edge
    assert "(311 in gate_40 vs 302 in gate_30)" in edge and "0.68 pp lower in gate_40 (95% CI −1.64 to +0.28 pp)" in edge
    # v3.1 row d: the cause of the imbalance is "most likely", and Engineering confirms it
    assert "most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from " \
           "gate_30); Engineering confirms the cause" in text

    # data-quality note: zero-round players flagged as back on Day 1 / Day 7
    zero = next(r for r in CK["by_rounds_bucket"] if r["rounds_bucket"] == "0")
    d1, d7 = round(zero["retention_1"] * zero["players"]), round(zero["retention_7"] * zero["players"])
    assert f"{d1} players with 0 rounds are flagged as back on Day 1 ({d7} on Day 7)" in text

    # interactive 1: a different intended split for the ad arm is recomputed and fails
    at.number_input(key="p2_srm_share_ad").set_value(95.0).run()
    assert_ok(at, "p2 after share change")
    assert len(at.error) == 1 and "FAIL" in at.error[0].value and len(at.info) == 0
    assert [m.value for m in at.metric if m.label == "p-value"][0] == "< 0.0001"

    # interactive 2: a looser threshold turns the gate warning into a failure in the panel; the band table stays
    # descriptive (same rows, still no status labels)
    before = strata_table()
    at.number_input(key="p2_srm_share_ad").set_value(96.0)
    at.radio(key="p2_srm_threshold").set_value(0.01).run()
    assert_ok(at, "p2 after threshold change")
    assert len(at.warning) == 0 and len(at.error) == 1 and "gate_40" in at.error[0].value
    after = strata_table()
    assert after.equals(before) and not set(after.to_numpy().ravel()) & {"PASS", "WARNING", "FAIL"}

    # interactive 3: the balance chart and its statistics follow the selected field (default: exposure parity)
    expo = next(b for b in AD["balance"] if b["variable"] == "exposure_bucket")
    assert metric(at, "Cramér's V") == f"{expo['cramers_v']:.3f}"
    assert any("Mean ads per user match" in x for x in takeaways(at))
    before = (metric(at, "Cramér's V"), chart_titles(at)[0])
    at.radio(key="p2_balance_var").set_value("Peak ad hour").run()
    assert_ok(at, "p2 after balance field change")
    hour = next(b for b in AD["balance"] if b["variable"] == "most_ads_hour")
    assert metric(at, "Cramér's V") == f"{hour['cramers_v']:.3f}"
    assert (metric(at, "Cramér's V"), chart_titles(at)[0]) != before
    assert "Peak ad hour" in chart_titles(at)[0]


# ------------------------------------------------------------------ page 3
def test_p3_retention() -> None:
    at = run_page("p3_retention.py")
    assert_page_frame(at, "Retention Analysis", "Which new players leave first")
    assert_no_stale_claims(at, "p3")
    assert metric(at, "D7 retention") == f"{CK['overall']['retention_7'] * 100:.1f}%"
    assert metric(at, "Not back on Day 1") == f"{(1 - CK['overall']['retention_1']) * 100:.1f}%"
    early_m = metric_el(at, "Installs with < 15 rounds")
    assert early_m.value == f"{EARLY['share_of_installs'] * 100:.0f}%"
    assert early_m.proto.delta == f"only {EARLY['retention_7'] * 100:.1f}% back on Day 7" == "only 2.3% back on Day 7"
    assert f"at most {EARLY['max_bucket_retention_7'] * 100:.1f}%" in early_m.help
    default_tk = takeaways(at)
    assert any("Players with < 15 rounds" in x and "2.3%" in x and "not a Day-0 targeting rule" in x
               for x in default_tk)
    median = int(RESULTS["data_quality"]["cookie"]["rounds_p50"])
    assert any(f"Half of players play {median} rounds or fewer" in x for x in default_tk)
    text = flat_text(at)
    assert "partly definitional" in text and "small next to engagement" in text and "one install cohort" in text
    assert "naive gap between unbalanced arms: about 60% of it sits where the gate cannot act" in text  # row m
    # persona: the company's mobile game, a different product (not a stand-in)
    assert "the company's mobile game" in text and "different product from the app the ads ran in" in text
    # R6: the early-churn segment and the onboarding test size
    r6 = EARLY["onboarding_test_sizing"]
    assert f"only {EARLY['retention_7'] * 100:.1f}% of them play on Day 7" in text
    assert f"≈{thousands(r6['players_needed_5050'])} target players (≈{thousands(r6['installs_needed_5050'])} " \
           "installs) at 50/50" in text
    # nothing reads the version gap as the gate's causal effect on D7
    assert not re.search(r"(?:gate|version)[^.]{0,60}\b(?:moves?|lowers?|reduces?|cuts?|costs?|caused?)\b[^.]{0,30}D7",
                         text, re.I)

    # interactive 1: live segmentation by experiment version, D7 only
    at.radio(key="p3_dimension").set_value("Experiment version")
    at.radio(key="p3_metric").set_value("D7 only").run()
    assert_ok(at, "p3 after segmentation change")
    seg_chart = next(c for c in chart_titles(at) if "retention by" in c)
    assert "experiment version" in seg_chart and "D1" not in seg_chart.split("<br>")[0]
    by_version = {r["version"]: r["retention_7"] for r in CK["by_version"]}
    seg_tk = next(x for x in takeaways(at) if "D7 retention ranges from" in x)
    assert f"{min(by_version.values()) * 100:.1f}%" in seg_tk and f"{max(by_version.values()) * 100:.1f}%" in seg_tk
    assert "not certified" in seg_tk and "not the gate's effect" in seg_tk
    assert "about 60% of it sits where the gate cannot act" in seg_tk
    assert takeaways(at) != default_tk
    assert_no_stale_claims(at, "p3 (version split)")

    # interactive 2: Day-1 status hides the trivially 0% / 100% D1 bars
    at.radio(key="p3_dimension").set_value("Came back on Day 1")
    at.radio(key="p3_metric").set_value("D1 and D7").run()
    assert_ok(at, "p3 after d1 split")
    assert any("Players who return on Day 1" in x for x in takeaways(at))

    # interactive 3: engagement-curve range and version split
    at.slider(key="p3_max_rounds").set_value(500)
    at.toggle(key="p3_split_version").set_value(False).run()
    assert_ok(at, "p3 after curve change")
    curve_tk = next(x for x in takeaways(at) if "rounds or fewer" in x)
    assert "reach round 500" in curve_tk and "versions' curves" not in curve_tk

    # interactive 4: with the version split, the largest curve gap sits before the first gate
    at.slider(key="p3_max_rounds").set_value(100)
    at.toggle(key="p3_split_version").set_value(True).run()
    assert_ok(at, "p3 after version split")
    curve_tk = next(x for x in takeaways(at) if "versions' curves" in x)
    assert "before the first gate" in curve_tk and "reach round 100" in curve_tk
    assert "the arms' imbalance seen as a distribution" in curve_tk and "not the gate" in curve_tk


# ------------------------------------------------------------------ page 7
CANONICAL_OWNERS = ["Growth PM", "Growth PM + media buyer", "Media buyer", "Analytics + Eng",
                    "Game PM (Eng + Analytics fix assignment)", "Onboarding PM (with CRM)"]


def test_p7_decision() -> None:
    at = run_page("p7_decision.py")
    assert_page_frame(at, "Decision & Recommendations", "What should we do")
    assert_no_stale_claims(at, "p7")
    assert_one_count_basis_per_sentence(at, "p7")

    badges = [m.value for m in at.markdown if "-badge[" in m.value]
    assert [b.split("[", 1)[1].rstrip("]") for b in badges] == ["KEEP", "TEST FIRST", "DON'T (YET)", "TEST",
                                                               "DON'T SHIP"]
    text = flat_text(at)
    assert "No sign of a retention benefit" in text and "not an estimate of its effect" in text
    # v3.1: ≤ 20 ads with its CI (row j); daypart driven by Night (row k); D1 guardrail per install (row e); row n
    le20 = AD["heterogeneity"]["exposure_bucket"]["concentration"]["le_20_ads_pooled"]
    assert f"show no lift we could measure ({pp(le20['abs_lift'])}, " \
           f"{ci(le20['abs_ci_low'], le20['abs_ci_high'], unit='')})" in text
    assert "p = 0.013 is driven by Night (0–5), where the control arm has 1 conversion among 735 users" in text
    assert "none for hour; daypart rests on one control conversion at night" in text
    d1 = GATE["d1_decomposition"]
    assert "no sign of a D1 effect: the part of the D1 gap the gate could explain is " \
           f"{pp(d1['install_level_effect_if_only_reachers'])} per install " \
           f"({ci(*d1['install_level_effect_ci_if_only_reachers'], unit='')})" in text
    assert "+0.03 pp per install (95% CI −0.29 to +0.35)" in text
    assert "≈790 extra installs (SRM WARNING, p = 0.0086), with a net excess of 762 among players with < 15 rounds" \
        in text

    # canonical R1-R6: owners, and the numbers in each row from results.json
    recs = at.table[0].value
    assert list(recs.index) == [f"R{i}" for i in range(1, 7)]
    assert list(recs.columns) == ["Owner", "What", "Expected impact", "How we'll measure", "Main risk"]
    assert recs["Owner"].tolist() == CANONICAL_OWNERS
    assert (recs.drop(columns="Owner").map(len) > 30).all().all(), "every recommendation needs all five fields"
    r1, r2, r3, r4, r5, r6 = (" ".join(recs.loc[r]) for r in ("R1", "R2", "R3", "R4", "R5", "R6"))
    bz, pw, dec = AD["business"], AD["power"], GATE["d7_decomposition"]
    hold, be, lt = bz["always_on_holdout_cost"], bz["breakeven_cpm_usd"], bz["last_touch_overstatement_ci"]
    assert "≈4,300 incremental conversions per comparable flight (95% CI 3,300–5,300)" in r1
    assert f"≈{hold['conversions_forgone']:,.0f} conversions per 588K-user flight " \
           f"(≈USD {hold['value_forgone_usd'] / 1e3:.1f}K at USD 50)" in r1
    assert f"{hold['as_run_control_share'] * 100:.0f}% PSA arm already forgoes " \
           f"≈{hold['as_run_control_conversions_forgone']:,.0f}" in r1
    assert f"{bz['last_touch_overstatement_x']:.1f}× (95% CI {lt[0]:.1f}–{lt[1]:.1f}×)" in r1
    assert f"CPM < USD {be['point']:.2f} (USD {be['ci_low']:.2f} at the pessimistic end)" in r1
    con = AD["heterogeneity"]["exposure_bucket"]["concentration"]
    assert f"{con['share_ad_users_36_200'] * 100:.0f}% of ad users who saw 36–200 ads" in r2
    assert f"{thousands(pw['total_n_for_10pct_rel_lift']['0.5'])} users (50/50)" in r2
    assert "randomizes the delivery schedule" in r3 and recs.loc["R3", "Main risk"] == \
        "Missing a small real timing effect."
    ses = pw["power_at_relative_lift"]["0.1"]
    assert f"96/4 had {ses['power_current_split'] * 100:.0f}% power" in r4
    assert ses["power_5050_same_total"] >= 0.995 and "≈100% power" in r4
    assert f"MDE of {pw['mde_if_5050_same_total']['mde_abs'] * 100:.2f} pp instead of " \
           f"{pw['mde_current']['mde_abs'] * 100:.2f} pp" in r4
    lo, hi = dec["install_level_effect_ci_if_only_reachers"]
    assert f"≈{sgn(dec['install_level_effect_if_only_reachers'] * 100, 1)} pp per install " \
           f"({ci(lo, hi, unit='')}; ≈{abs(dec['install_level_effect_if_only_reachers']) * 1e4:.0f} fewer Day-7 " \
           "players per 10,000 installs)" in r5
    rr = GATE["rounds_among_reachers"]
    assert f"median {rr['median_t']:.0f} vs. {rr['median_c']:.0f} rounds" in r5
    assert "≈790 extra installs, with a net excess of 762 among players with < 15 rounds" in r5
    assert f"{RETEST['smallest_d7_change_per_install'] * 100:.1f} pp D7 change per install" in r5
    assert f"≈{thousands(RETEST['installs_needed_reacher_analysis_5050'])} installs at 50/50" in r5
    assert f"≈{thousands(RETEST['reachers_needed_5050'])} of them" in r5
    assert f"≈{thousands(RETEST['installs_needed_install_level_5050'])} if analysed over all installs" in r5
    assert f"Quoting the raw {pp(dec['naive_diff'])}" in r5
    r6s = EARLY["onboarding_test_sizing"]
    assert f"{EARLY['share_of_installs'] * 100:.0f}% play < 15 rounds and only {EARLY['retention_7'] * 100:.1f}%" in r6
    gap = EARLY["d7_if_returned_day1"] - EARLY["d7_if_not_returned_day1"]
    assert f"≈{gap:.2f} pp of D7 ({EARLY['d7_if_returned_day1'] * 100:.1f}% vs. " \
           f"{EARLY['d7_if_not_returned_day1'] * 100:.1f}%)" in r6
    assert f"≈{thousands(r6s['players_needed_5050'])} target players (≈{thousands(r6s['installs_needed_5050'])} " \
           "installs) at 50/50" in r6

    # the calculator's defaults (ad test) reproduce the power numbers in results.json (same src.stats function)
    n10 = pw["total_n_for_10pct_rel_lift"]
    assert metric(at, "Total users needed") == f"{n10['0.5']:,}"
    assert metric(at, "Entrants needed") == f"{n10['0.5']:,}"   # everyone reaches an ad test's change

    # interactive 1: treatment share
    at.slider(key="p7_share").set_value(96).run()
    assert_ok(at, "p7 after share change")
    assert metric(at, "Total users needed") == f"{n10['0.96']:,}"
    at.slider(key="p7_share").set_value(80).run()
    assert metric(at, "Total users needed") == f"{n10['0.8']:,}"

    # interactive 2: a larger change needs fewer users; duration follows the daily traffic entered
    before_n = int(metric(at, "Total users needed").replace(",", ""))
    at.number_input(key="p7_change").set_value(0.4)
    at.number_input(key="p7_daily").set_value(5_000).run()
    assert_ok(at, "p7 after change edit")
    total = int(metric(at, "Total users needed").replace(",", ""))
    assert total < before_n
    assert metric(at, "Days at 5,000 entrants/day") == f"{math.ceil(total / 5_000):,}"

    # interactive 3: the onboarding preset (R6) reproduces cookie.early_churn_segment.onboarding_test_sizing
    at.radio(key="p7_preset").set_value("Onboarding test (R6)").run()
    assert_ok(at, "p7 after onboarding preset")
    assert abs(at.number_input(key="p7_baseline").value - EARLY["retention_7"] * 100) < 1e-9
    assert abs(at.number_input(key="p7_change").value - RESULTS["config"]["onboarding_target_lift"] * 100) < 1e-9
    assert abs(at.number_input(key="p7_reach").value - EARLY["share_of_installs"] * 100) < 1e-9
    assert at.slider(key="p7_share").value == 50
    assert metric(at, "Total users needed") == f"{r6s['players_needed_5050']:,}" == "30,809"
    assert metric(at, "Entrants needed") == f"{r6s['installs_needed_5050']:,}" == "65,648"
    assert any("Onboarding test (R6)" in c.value and "30,809 target players ≈ 65,648 installs" in c.value
               for c in at.caption)

    # interactive 4: the gate re-test preset (R5) reproduces cookie.gate.retest_sizing (a drop, partial reach)
    at.radio(key="p7_preset").set_value("Gate re-test (R5)").run()
    assert_ok(at, "p7 after gate preset")
    assert not at.warning
    assert abs(at.number_input(key="p7_change").value + RETEST["equivalent_change_among_reachers"] * 100) < 1e-9
    assert metric(at, "Total users needed") == f"{RETEST['reachers_needed_5050']:,}" == "41,933"
    assert metric(at, "Entrants needed") == f"{RETEST['installs_needed_reacher_analysis_5050']:,}" == "113,669"
    assert metric(at, "Change to detect") == f"{sgn(-RETEST['equivalent_change_among_reachers'] * 100)} pp"
    assert any("Gate re-test (R5)" in c.value and f"{RETEST['installs_needed_install_level_5050']:,} installs"
               in c.value and "never at the observed gap" in c.value for c in at.caption)
    # v3.1 row i: sized for a drop (a rise needs up to ≈2% more) and the cohort's share reaching level 30
    gate_cap = " ".join(next(c.value for c in at.caption if c.value.startswith("Gate re-test (R5)")).split())
    rise = max(RETEST["installs_needed_install_level_5050_if_rise"] / RETEST["installs_needed_install_level_5050"],
               RETEST["installs_needed_reacher_analysis_5050_if_rise"]
               / RETEST["installs_needed_reacher_analysis_5050"]) - 1
    assert f"{rise * 100:.0f}" == "2"
    assert "sized to detect a 0.5 pp drop; a rise of the same size needs up to ≈2% more" in gate_cap
    assert f"(≈{thousands(RETEST['installs_needed_install_level_5050_if_rise'])} installs analysed over all " \
           f"installs, ≈{RETEST['installs_needed_reacher_analysis_5050_if_rise'] / 1e3:.1f}K with the analysis " \
           "among players who reach level 30)" in gate_cap
    assert "(≈195K installs analysed over all installs, ≈114.4K with the analysis" in gate_cap
    assert f"this cohort's {RETEST['share_reached_30'] * 100:.1f}% reaching level 30; re-check with the new " \
           "cohort's share before launch" in gate_cap and "36.9%" in gate_cap
    assert "Engineering has found and fixed the cause of the imbalance" in gate_cap  # row d
    assert "drop" in json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]["xaxis"]["title"]["text"]
    assert_no_stale_claims(at, "p7 (gate preset)")

    # interactive 5: any change, checked against src.stats directly; zero is refused
    at.number_input(key="p7_change").set_value(-2.0).run()
    assert_ok(at, "p7 after negative change")
    base = at.number_input(key="p7_baseline").value / 100
    expected = S.required_total_n(base, -0.02, 0.5, 0.05, 0.8)
    assert metric(at, "Total users needed") == f"{expected:,}"
    at.number_input(key="p7_change").set_value(0.0).run()
    assert_ok(at, "p7 after zero change")
    assert len(at.warning) == 1 and "non-zero" in at.warning[0].value


# ------------------------------------------------------------------ inside the multipage app
def test_pages_inside_app() -> None:
    """Run app.py and switch to each of these pages (needs every page file app.py registers)."""
    src = (DASH / "app.py").read_text()
    assert 'initial_sidebar_state="auto"' in src, "the sidebar should collapse on phones and stay open on desktop"
    views = DASH / "views"
    required = ["p1_overview.py", "p2_data_sanity.py", "p3_retention.py", "p4_experiment_readout.py",
                "p5_heterogeneity.py", "p6_gate_experiment.py", "p7_decision.py"]
    missing = [p for p in required if not (views / p).exists()]
    if missing:
        print(f"    skipped: app.py needs {', '.join(missing)}")
        return
    at = AppTest.from_file(str(DASH / "app.py"), default_timeout=TIMEOUT)
    at.run()
    assert_ok(at, "app.py (overview)")
    assert at.title[0].value == "Overview"
    assert len(at.page_link) >= 11, "page links should resolve inside the app (5 answer cards + 6 pages)"
    for page, title in (("views/p2_data_sanity.py", "Data & Sanity Checks"),
                        ("views/p3_retention.py", "Retention Analysis"),
                        ("views/p7_decision.py", "Decision & Recommendations")):
        at.switch_page(page).run()
        assert_ok(at, page)
        assert at.title[0].value == title


TESTS = [test_p1_overview, test_p2_data_sanity, test_p3_retention, test_p7_decision, test_pages_inside_app]

if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        t0 = time.perf_counter()
        try:
            test()
            print(f"PASS  {test.__name__} ({time.perf_counter() - t0:.1f}s)")
        except Exception:  # report every failing test, then exit non-zero
            failed += 1
            print(f"FAIL  {test.__name__} ({time.perf_counter() - t0:.1f}s)")
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
