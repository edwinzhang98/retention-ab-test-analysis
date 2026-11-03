"""Smoke and interaction tests for dashboard pages 1, 2, 3 and 7 (Streamlit AppTest).

Each page is run on its own (dashboard/ and the repo root on sys.path, like
`streamlit run dashboard/app.py` sets up), must raise no exception, must show the
key numbers in reports/results.json (and reports/tables/), must recompute its
output when an interactive control changes, and must not repeat claims the v2
analysis withdrew. Pages only read the caches in data/processed/ and
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
DAY_TABLE = pd.read_csv(ROOT / "reports" / "tables" / "ad_lift_by_most_ads_day.csv").set_index("most_ads_day")

# Claims and labels the v2 analysis withdrew; none may come back on these pages.
STALE = {
    "saturation claim": re.compile(r"saturat", re.I),
    "'8 of 24 hours' argument": re.compile(r"\b8 of 24\b"),
    "post-hoc power": re.compile(r"achieved power|power at the observed effect is \d", re.I),
    "'barely matters'": re.compile(r"barely matters", re.I),
    "'370 D7 players' figure": re.compile(r"\b370\b"),
    "status label WARN": re.compile(r"\bWARN\b"),
    "p-value printed as 0": re.compile(r"\bp\s*=\s*0(?:\.0+)?(?!\.?\d)"),
    "bare dollar sign": re.compile(r"\$"),
    "install-date cohorts": re.compile(r"\bcohorts\b", re.I),
}


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
    parts += chart_titles(at) + [e.label for e in at.expander]
    return "\n".join(parts)


def assert_no_stale_claims(at: AppTest, where: str, allow: dict[str, int] | None = None) -> None:
    text = rendered_text(at)
    for name, rx in STALE.items():
        hits = rx.findall(text)
        assert len(hits) <= (allow or {}).get(name, 0), f"{where}: stale v1 wording ({name}): {hits}"


def assert_page_frame(at: AppTest, title: str, question_start: str) -> None:
    """Every page: title, the one-sentence question, a takeaway under each chart, 'How to read this'."""
    assert at.title[0].value == title
    assert any("page-question" in m.value and question_start in m.value for m in at.markdown), "question line missing"
    assert "How to read this" in [e.label for e in at.expander]
    assert len(takeaways(at)) >= len(at.get("plotly_chart")) > 0, "every chart needs a takeaway"


def pp(x: float, nd: int = 2) -> str:
    return f"{x * 100:+.{nd}f} pp"


# ------------------------------------------------------------------ page 1
def test_p1_overview() -> None:
    t0 = time.perf_counter()
    at = run_page("p1_overview.py")
    elapsed = time.perf_counter() - t0
    assert elapsed < P1_FIRST_PAINT_MAX, f"Overview took {elapsed:.1f}s on a cold start"
    assert_page_frame(at, "Overview", "What did we find")
    assert_no_stale_claims(at, "p1")

    t, bz = AD["test"], AD["business"]
    dec = GATE["d7_decomposition"]
    assert len(at.metric) == 8
    assert metric(at, "Conversion lift") == pp(t["abs_lift"])
    assert metric(at, "Incremental conversions") == f"{bz['incremental_conversions']['point']:,.0f}"
    share = metric_el(at, "Incremental share")
    assert share.value == f"{bz['share_of_ad_conversions_incremental'] * 100:.0f}%"
    assert f"{bz['last_touch_overstatement_x']:.1f}×" in share.proto.delta
    be = bz["breakeven_cpm_usd"]["point"]
    assert metric(at, "Breakeven CPM") == f"USD {be:.2f}"
    # gate card: the part the gate could cause (not the naive gap), with its CI; the naive gap and the
    # certification status are spelled out right under the KPI row
    gate_m = metric_el(at, "gate_40 effect on D7")
    assert gate_m.value == pp(dec["install_level_effect_if_only_reachers"])
    lo, hi = dec["install_level_effect_ci_if_only_reachers"]
    assert gate_m.proto.delta == f"95% CI {lo * 100:+.2f} to {hi * 100:+.2f} pp"
    assert "Not certified" in gate_m.help
    assert any(f"naive gap is {pp(dec['naive_diff'])}" in c.value and "Not certified" in c.value
               for c in at.caption)

    text = rendered_text(at)
    badges = [m.value for m in at.markdown if "-badge[" in m.value]
    assert len(badges) == 5, badges
    assert any("keep gate_30" in b and "not certified" in b for b in badges)
    # Q1: attribution and holdout cost; Q2: heavy users; Q3: day contrasts recomputed live = the committed table
    assert f"{bz['always_on_holdout_cost']['conversions_forgone']:,.0f} conversions" in text
    con = AD["heterogeneity"]["exposure_bucket"]["concentration"]
    assert "lift lives in heavy users" in text and f"{con['share_users_le_20_ads'] * 100:.0f}%" in text
    for day in AD["heterogeneity"]["most_ads_day"]["segments_differing_holm"]:
        assert f"{day}-peak users {pp(DAY_TABLE.loc[day, 'diff_vs_rest'])}" in text
    # Q5: raw-count SRM warning and the gate-attributable effect
    srm = GATE["srm"]
    assert f"p = {srm['p_value']:.4f}" in text and f"{srm['n_t']:,} vs {srm['n_c']:,}" in text
    assert srm["status"] == "WARNING" and "**WARNING**" in text
    assert any("Users shown ads converted at" in x for x in takeaways(at))

    # interactive: the value-per-conversion assumption drives the breakeven CPM and the holdout cost (linear)
    at.number_input(key="p1_value_per_conversion").set_value(100.0).run()
    assert_ok(at, "p1 after value change")
    ratio = 100 / RESULTS["config"]["value_per_conversion_usd"]
    assert metric(at, "Breakeven CPM at USD 100") == f"USD {be * ratio:.2f}"
    holdout_usd = bz["always_on_holdout_cost"]["value_forgone_usd"] * ratio
    assert f"USD {holdout_usd / 1e3:,.1f}K at USD 100" in rendered_text(at)


# ------------------------------------------------------------------ page 2
def test_p2_data_sanity() -> None:
    at = run_page("p2_data_sanity.py")
    assert_page_frame(at, "Data & Sanity Checks", "Can we trust the data")
    # the post-cleaning gate SRM p-value may appear once, as a footnote
    assert_no_stale_claims(at, "p2")
    assert rendered_text(at).count("0.0085") <= 1
    srm_ad, srm_gate = AD["srm"], GATE["srm"]

    # defaults: the ad split passes but is uninformative (quota-exact); the gate is in the warning band
    assert srm_ad["status"] == "PASS" and srm_ad["is_nearest_integer_to_target"]
    assert len(at.info) == 1 and "PASS, but uninformative" in at.info[0].value
    for s in (f"{srm_ad['deviation_users']:.2f} off", f"about {srm_ad['sd_users_under_random_assignment']:,.0f}",
              f"{srm_ad['prob_exactly_nearest_integer'] * 100:.2f}%"):
        assert s in at.info[0].value, (s, at.info[0].value)
    assert len(at.warning) == 1 and "WARNING" in at.warning[0].value and "gate_40" in at.warning[0].value
    assert len(at.success) == 0 and len(at.error) == 0
    assert [m.value for m in at.metric if m.label == "p-value"] == [f"{srm_ad['p_value']:.4f}",
                                                                    f"{srm_gate['p_value']:.4f}"]
    counts = next(d.value for d in at.dataframe if "Observed players" in d.value.columns).set_index("Arm")
    assert counts.loc["gate_40", "Difference"] == f"{srm_gate['n_t'] - srm_gate['expected_t']:+,.2f}"
    gap_sd = (srm_gate["n_t"] - srm_gate["expected_t"]) / S.quota_exactness(
        srm_gate["n_t"], srm_gate["n_c"], srm_gate["intended_share_t"])["sd_users_under_random_assignment"]
    assert f"{gap_sd:.1f} times the typical chance gap" in at.warning[0].value
    assert (srm_gate["n_t"], srm_gate["n_c"]) == (GATE["players_raw"]["gate_40"], GATE["players_raw"]["gate_30"])

    # where is the gate imbalance? one row per stratum, numbers and statuses as in results.json
    strata = next(d.value for d in at.dataframe if "gate_40 minus gate_30" in d.value.columns).set_index(
        "Players (by rounds played)")
    sbs = GATE["srm_by_stratum"]
    for label, key in (("All players", None), ("Fewer than 30 rounds (never reached level 30)", "rounds_lt_30"),
                       ("· of which fewer than 15 rounds", "rounds_lt_15"), ("30 rounds or more", "rounds_ge_30")):
        s = srm_gate if key is None else sbs[key]
        row = strata.loc[label]
        assert (row["gate_40"], row["gate_30"]) == (f"{s['n_t']:,}", f"{s['n_c']:,}")
        assert row["p-value"] == ("< 0.0001" if s["p_value"] < 1e-4 else f"{s['p_value']:.4f}")
        assert row["Status"] == s["status"], (label, row["Status"], s["status"])
    assert sbs["rounds_lt_15"]["n_t"] - sbs["rounds_lt_15"]["n_c"] == GATE["excess_players_with_lt_15_rounds"]

    # data-quality note: zero-round players flagged as back on Day 1 / Day 7
    zero = next(r for r in CK["by_rounds_bucket"] if r["rounds_bucket"] == "0")
    d1, d7 = round(zero["retention_1"] * zero["players"]), round(zero["retention_7"] * zero["players"])
    assert f"{d1} players with 0 rounds are flagged as back on Day 1 ({d7} on Day 7)" in rendered_text(at)

    # interactive 1: a different intended split for the ad arm is recomputed and fails
    at.number_input(key="p2_srm_share_ad").set_value(95.0).run()
    assert_ok(at, "p2 after share change")
    assert len(at.error) == 1 and "FAIL" in at.error[0].value and len(at.info) == 0
    assert [m.value for m in at.metric if m.label == "p-value"][0] == "< 0.0001"

    # interactive 2: a looser threshold turns the gate warning into a failure, in the panel and the strata table
    at.number_input(key="p2_srm_share_ad").set_value(96.0)
    at.radio(key="p2_srm_threshold").set_value(0.01).run()
    assert_ok(at, "p2 after threshold change")
    assert len(at.warning) == 0 and len(at.error) == 1 and "gate_40" in at.error[0].value
    strata = next(d.value for d in at.dataframe if "gate_40 minus gate_30" in d.value.columns)
    assert strata["Status"].tolist() == ["FAIL", "FAIL", "FAIL", "PASS"]

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
    default_tk = takeaways(at)
    assert any("Players with < 15 rounds" in x and "not a Day-0 targeting rule" in x for x in default_tk)
    median = int(RESULTS["data_quality"]["cookie"]["rounds_p50"])
    assert any(f"Half of players play {median} rounds or fewer" in x for x in default_tk)
    text = rendered_text(at)
    assert "partly definitional" in text and "small next to engagement" in text and "one install cohort" in text

    # interactive 1: live segmentation by experiment version, D7 only
    at.radio(key="p3_dimension").set_value("Experiment version")
    at.radio(key="p3_metric").set_value("D7 only").run()
    assert_ok(at, "p3 after segmentation change")
    seg_chart = next(c for c in chart_titles(at) if "retention by" in c)
    assert "experiment version" in seg_chart and "D1" not in seg_chart.split("<br>")[0]
    by_version = {r["version"]: r["retention_7"] for r in CK["by_version"]}
    seg_tk = next(x for x in takeaways(at) if "D7 retention ranges from" in x)
    assert f"{min(by_version.values()) * 100:.1f}%" in seg_tk and f"{max(by_version.values()) * 100:.1f}%" in seg_tk
    assert "not certified" in seg_tk
    assert takeaways(at) != default_tk

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


# ------------------------------------------------------------------ page 7
def test_p7_decision() -> None:
    at = run_page("p7_decision.py")
    assert_page_frame(at, "Decision & Recommendations", "What should we do")
    assert_no_stale_claims(at, "p7")

    badges = [m.value for m in at.markdown if "-badge[" in m.value]
    assert [b.split("[", 1)[1].rstrip("]") for b in badges] == ["KEEP", "TEST FIRST", "DON'T (YET)", "TEST",
                                                               "DON'T SHIP"]
    recs = at.table[0].value
    assert list(recs.index) == [f"R{i}" for i in range(1, 7)]
    assert list(recs.columns) == ["Who", "What", "Expected impact", "How to measure", "Risk"]
    assert (recs["Who"].str.len() > 0).all()
    assert (recs.drop(columns="Who").map(len) > 30).all().all(), "every recommendation needs all five fields"
    r1, r4, r5 = (" ".join(recs.loc[r]) for r in ("R1", "R4", "R5"))
    bz, pw, dec, retest = AD["business"], AD["power"], GATE["d7_decomposition"], GATE["retest_sizing"]
    assert f"{bz['always_on_holdout_cost']['conversions_forgone']:,.0f} conversions" in r1
    assert f"{bz['last_touch_overstatement_x']:.1f}×" in r1
    assert f"{pw['power_at_relative_lift']['0.1']['power_current_split'] * 100:.0f}% power" in r4
    assert pp(dec["install_level_effect_if_only_reachers"]) in r5 and "Not certified" in r5
    assert f"{retest['installs_needed_total_5050']:,} installs" in r5

    # the calculator's defaults reproduce the power numbers in results.json (same src.stats function)
    n10 = pw["total_n_for_10pct_rel_lift"]
    assert metric(at, "Total users needed") == f"{n10['0.5']:,}"
    assert metric(at, "Entrants needed") == f"{n10['0.5']:,}"   # everyone reaches an ad test's change

    # interactive 1: treatment share
    at.slider(key="p7_share").set_value(96).run()
    assert_ok(at, "p7 after share change")
    assert metric(at, "Total users needed") == f"{n10['0.96']:,}"
    at.slider(key="p7_share").set_value(80).run()
    assert metric(at, "Total users needed") == f"{n10['0.8']:,}"

    # interactive 2: a larger MDE needs fewer users; duration follows the daily traffic entered
    before_n = int(metric(at, "Total users needed").replace(",", ""))
    at.number_input(key="p7_rel_mde").set_value(20.0)
    at.number_input(key="p7_daily").set_value(5_000).run()
    assert_ok(at, "p7 after MDE change")
    total = int(metric(at, "Total users needed").replace(",", ""))
    assert total < before_n
    assert metric(at, "Days at 5,000 entrants/day") == f"{math.ceil(total / 5_000):,}"

    # interactive 3: the D7 preset switches the baseline (and resets the split)
    at.radio(key="p7_preset").set_value("Onboarding test: D7 retention").run()
    assert_ok(at, "p7 after preset change")
    assert abs(at.number_input(key="p7_baseline").value - CK["overall"]["retention_7"] * 100) < 0.01
    assert at.slider(key="p7_share").value == 50

    # interactive 4: the gate re-test preset reproduces results.json's re-test sizing (a drop, partial reach)
    at.radio(key="p7_preset").set_value("Gate re-test: D7 of players who reach level 30").run()
    assert_ok(at, "p7 after gate preset")
    assert not at.warning
    assert metric(at, "Total users needed") == f"{retest['reachers_needed_total_5050']:,}"
    assert metric(at, "Entrants needed") == f"{retest['installs_needed_total_5050']:,}"
    assert metric(at, "Effect to detect") == pp(retest["target_effect_reachers"])
    assert "drop" in json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]["xaxis"]["title"]["text"]

    # interactive 5: any relative change, checked against src.stats directly; zero is refused
    at.number_input(key="p7_rel_mde").set_value(-5.0).run()
    assert_ok(at, "p7 after negative change")
    base = at.number_input(key="p7_baseline").value / 100
    expected = S.required_total_n(base, base * -0.05, 0.5, 0.05, 0.8)
    assert metric(at, "Total users needed") == f"{expected:,}"
    at.number_input(key="p7_rel_mde").set_value(0.0).run()
    assert_ok(at, "p7 after zero change")
    assert len(at.warning) == 1 and "non-zero" in at.warning[0].value


# ------------------------------------------------------------------ inside the multipage app
def test_pages_inside_app() -> None:
    """Run app.py and switch to each of these pages (needs every page file app.py registers)."""
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
