"""Smoke and interaction tests for dashboard pages 1, 2, 3 and 7 (Streamlit AppTest).

Each page is run on its own (dashboard/ and the repo root on sys.path, like
`streamlit run dashboard/app.py` sets up), must raise no exception, and must
recompute its output when an interactive control changes. Pages only read the
caches in data/processed/ and reports/results.json, so build those first
(`python run.py --only analysis`).

Run:  .venv/bin/python tests/test_dashboard_a.py      (pytest also collects the test_* functions)
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
for _p in (str(DASH), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from streamlit.testing.v1 import AppTest  # noqa: E402

TIMEOUT = 120          # seconds per script run (cold imports + catalog build on the first run)
P1_FIRST_PAINT_MAX = 10.0
RESULTS = json.loads((ROOT / "reports" / "results.json").read_text())


# ------------------------------------------------------------------ helpers
def run_page(name: str) -> AppTest:
    at = AppTest.from_file(str(DASH / "views" / name), default_timeout=TIMEOUT)
    at.run()
    assert_ok(at, name)
    return at


def assert_ok(at: AppTest, where: str) -> None:
    assert not at.exception, f"{where}: " + "; ".join(str(e.value) for e in at.exception)


def metric(at: AppTest, label_start: str) -> str:
    hits = [m.value for m in at.metric if m.label.startswith(label_start)]
    assert hits, f"no metric starting with {label_start!r}: {[m.label for m in at.metric]}"
    return hits[0]


def takeaways(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown if "class='takeaway'" in m.value]


def chart_titles(at: AppTest) -> list[str]:
    return [json.loads(c.proto.spec)["layout"]["title"]["text"] for c in at.get("plotly_chart")]


def assert_page_frame(at: AppTest, title: str, question_start: str) -> None:
    """Every page: title, the one-sentence question, a takeaway under each chart, 'How to read this'."""
    assert at.title[0].value == title
    assert any("page-question" in m.value and question_start in m.value for m in at.markdown), "question line missing"
    assert "How to read this" in [e.label for e in at.expander]
    assert len(takeaways(at)) >= len(at.get("plotly_chart")) > 0, "every chart needs a takeaway"


# ------------------------------------------------------------------ page 1
def test_p1_overview() -> None:
    t0 = time.perf_counter()
    at = run_page("p1_overview.py")
    elapsed = time.perf_counter() - t0
    assert elapsed < P1_FIRST_PAINT_MAX, f"Overview took {elapsed:.1f}s on a cold start"
    assert_page_frame(at, "Overview", "What did we find")

    t = RESULTS["ad"]["test"]
    assert len(at.metric) == 8
    assert metric(at, "Conversion lift") == f"{t['abs_lift'] * 100:+.2f} pp"
    inc = RESULTS["ad"]["business"]["incremental_conversions"]["point"]
    assert metric(at, "Incremental conversions") == f"{inc:,.0f}"
    assert metric(at, "gate_40 effect") == f"{RESULTS['cookie']['gate']['retention_7']['abs_lift'] * 100:+.2f} pp"
    be = RESULTS["ad"]["business"]["breakeven_cpm_usd"]["point"]
    assert metric(at, "Breakeven CPM") == f"USD {be:.2f}"
    assert any("Users shown ads converted at" in x for x in takeaways(at))

    # interactive: the value-per-conversion assumption drives the breakeven CPM (linear in the value)
    at.number_input(key="p1_value_per_conversion").set_value(100.0).run()
    assert_ok(at, "p1 after value change")
    assert metric(at, "Breakeven CPM") == f"USD {be * 100 / RESULTS['config']['value_per_conversion_usd']:.2f}"
    assert metric(at, "Breakeven CPM") != f"USD {be:.2f}"


# ------------------------------------------------------------------ page 2
def test_p2_data_sanity() -> None:
    at = run_page("p2_data_sanity.py")
    assert_page_frame(at, "Data & Sanity Checks", "Can we trust the data")
    gate_srm = RESULTS["cookie"]["gate"]["srm"]

    # defaults: ad experiment passes, gate experiment is in the warning band (0.001 <= p < 0.01)
    assert len(at.success) == 1 and "PASS" in at.success[0].value
    assert len(at.warning) == 1 and "WARNING" in at.warning[0].value
    assert len(at.error) == 0
    assert [m.value for m in at.metric if m.label == "p-value"] == ["0.9998", f"{gate_srm['p_value']:.4f}"]

    # interactive 1: a different intended split for the ad arm is recomputed and fails
    at.number_input(key="p2_srm_share_ad").set_value(95.0).run()
    assert_ok(at, "p2 after share change")
    assert len(at.error) == 1 and "FAIL" in at.error[0].value
    assert [m.value for m in at.metric if m.label == "p-value"][0] == "< 0.0001"

    # interactive 2: a looser threshold turns the gate warning into a failure
    at.number_input(key="p2_srm_share_ad").set_value(96.0)
    at.radio(key="p2_srm_threshold").set_value(0.01).run()
    assert_ok(at, "p2 after threshold change")
    assert len(at.warning) == 0 and len(at.error) == 1 and "gate_40" in at.error[0].value

    # interactive 3: the balance chart and its statistics follow the selected field
    before = (metric(at, "Cramér's V"), chart_titles(at)[0])
    at.radio(key="p2_balance_var").set_value("Peak ad hour").run()
    assert_ok(at, "p2 after balance field change")
    hour = next(b for b in RESULTS["ad"]["balance"] if b["variable"] == "most_ads_hour")
    assert metric(at, "Cramér's V") == f"{hour['cramers_v']:.3f}"
    assert (metric(at, "Cramér's V"), chart_titles(at)[0]) != before
    assert "Peak ad hour" in chart_titles(at)[0]


# ------------------------------------------------------------------ page 3
def test_p3_retention() -> None:
    at = run_page("p3_retention.py")
    assert_page_frame(at, "Retention Analysis", "Which new players leave first")
    assert metric(at, "D7 retention") == f"{RESULTS['cookie']['overall']['retention_7'] * 100:.1f}%"
    default_tk = takeaways(at)
    assert any("Players with < 15 rounds" in x for x in default_tk)

    # interactive 1: live segmentation by experiment version, D7 only
    at.radio(key="p3_dimension").set_value("Experiment version")
    at.radio(key="p3_metric").set_value("D7 only").run()
    assert_ok(at, "p3 after segmentation change")
    seg_chart = next(c for c in chart_titles(at) if "retention by" in c)
    assert "experiment version" in seg_chart and "D1" not in seg_chart.split("<br>")[0]
    by_version = {r["version"]: r["retention_7"] for r in RESULTS["cookie"]["by_version"]}
    seg_tk = next(x for x in takeaways(at) if "D7 retention ranges from" in x)
    assert f"{min(by_version.values()) * 100:.1f}%" in seg_tk and f"{max(by_version.values()) * 100:.1f}%" in seg_tk
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
    curve_tk = next(x for x in takeaways(at) if "Half of players stop before" in x)
    assert "reach round 500" in curve_tk and "versions' curves" not in curve_tk


# ------------------------------------------------------------------ page 7
def test_p7_decision() -> None:
    at = run_page("p7_decision.py")
    assert_page_frame(at, "Decision & Recommendations", "What should we do")

    recs = at.table[0].value
    assert list(recs.index) == [f"R{i}" for i in range(1, 7)]
    assert list(recs.columns) == ["Who", "What", "Expected impact", "How to measure", "Risk"]
    assert (recs["Who"].str.len() > 0).all()
    assert (recs.drop(columns="Who").map(len) > 30).all().all(), "every recommendation needs all five fields"

    # the calculator's defaults reproduce the power numbers in results.json (same src.stats function)
    n10 = RESULTS["ad"]["power"]["total_n_for_10pct_rel_lift"]
    assert metric(at, "Total users needed") == f"{n10['0.5']:,}"

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
    assert metric(at, "Days at 5,000 users/day") == f"{math.ceil(total / 5_000):,}"

    # interactive 3: the D7 preset switches the baseline
    at.radio(key="p7_preset").set_value("Onboarding test: D7 retention").run()
    assert_ok(at, "p7 after preset change")
    assert abs(at.number_input(key="p7_baseline").value - RESULTS["cookie"]["overall"]["retention_7"] * 100) < 0.01


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
    assert len(at.page_link) >= 6, "page links should resolve inside the app"
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
