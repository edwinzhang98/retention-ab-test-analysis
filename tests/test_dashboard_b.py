"""Tests for dashboard pages 4-6: experiment readout, heterogeneity, gate experiment.

Each page runs headless with Streamlit's AppTest. The tests check that there is
no exception or error box, that the default view shows the numbers in
reports/results.json, and that the interactive controls change the computed
output the way the statistics say they should (a lower alpha widens the CI, a
stricter correction leaves fewer significant hours, and so on).

Run:   .venv/bin/python tests/test_dashboard_b.py
pytest also collects the test_* functions if it is installed.
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
for _p in (str(ROOT), str(DASHBOARD)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from streamlit.testing.v1 import AppTest  # noqa: E402

VIEWS = DASHBOARD / "views"
TIMEOUT = 120
RESULTS = json.loads((ROOT / "reports" / "results.json").read_text())
AD, GATE = RESULTS["ad"], RESULTS["cookie"]["gate"]
NUMBER = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")

P4, P5, P6 = "p4_experiment_readout.py", "p5_heterogeneity.py", "p6_gate_experiment.py"
LIFT = "Absolute lift"


# ------------------------------------------------------------------ helpers
def numbers(text: str) -> list[float]:
    return [float(x.replace(",", "").replace("−", "-")) for x in NUMBER.findall(text)]


def assert_clean(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def run_page(name: str) -> AppTest:
    at = AppTest.from_file(str(VIEWS / name), default_timeout=TIMEOUT)
    at.run()
    assert_clean(at)
    return at


def rerun(at: AppTest) -> AppTest:
    at.run()
    assert_clean(at)
    return at


def metric(at: AppTest, label: str):
    """Metric by exact label, else the first whose label starts with `label`."""
    for m in at.metric:
        if m.label == label:
            return m
    for m in at.metric:
        if m.label.startswith(label):
            return m
    raise AssertionError(f"metric {label!r} not found; have {[m.label for m in at.metric]}")


def ci_from_note(m) -> tuple[float, float]:
    """'95% CI +0.59 to +0.94' (optionally followed by ' pp') -> (0.59, 0.94)."""
    lo, hi = numbers(m.proto.delta.split("CI", 1)[1])[:2]
    return lo, hi


def page_text(at: AppTest) -> str:
    return "\n".join(md.value for md in at.markdown)


# ------------------------------------------------------------------ page 4
def test_p4_default_view_matches_results():
    t, pw = AD["test"], AD["power"]
    at = run_page(P4)
    lift = metric(at, LIFT)
    assert lift.value == f"{t['abs_lift'] * 100:+.2f} pp"
    assert ci_from_note(lift) == (round(t["abs_ci_low"] * 100, 2), round(t["abs_ci_high"] * 100, 2))
    assert metric(at, "MDE at 96/4").value == f"{pw['mde_current']['mde_abs'] * 100:.2f} pp"
    assert metric(at, "Users needed for a 10% lift at 96/4").value == f"{pw['total_n_for_10pct_rel_lift']['0.96']:,}"
    assert metric(at, "Users needed for a 10% lift at 50/50").value == f"{pw['total_n_for_10pct_rel_lift']['0.5']:,}"
    be = AD["business"]["breakeven_cpm_usd"]["point"]
    assert numbers(metric(at, "Breakeven CPM").value)[0] == round(be, 2)
    assert len(at.get("plotly_chart")) >= 5


def test_p4_lower_alpha_widens_ci():
    at = run_page(P4)
    lo5, hi5 = ci_from_note(metric(at, LIFT))
    at.radio(key="p4_alpha").set_value(0.01)
    rerun(at)
    m = metric(at, LIFT)
    lo1, hi1 = ci_from_note(m)
    assert m.proto.delta.startswith("99% CI")
    assert hi1 - lo1 > hi5 - lo5
    assert lo1 < lo5 and hi1 > hi5


def test_p4_ci_method_changes_interval():
    at = run_page(P4)
    newcombe = ci_from_note(metric(at, LIFT))
    for method in ("wald", "bootstrap"):
        at.radio(key="p4_ci_method").set_value(method)
        rerun(at)
        ci = ci_from_note(metric(at, LIFT))
        assert ci != newcombe, method
        assert ci[0] > 0, f"{method} CI should still exclude 0"


def test_p4_power_panel_recomputes_mde():
    at = run_page(P4)
    mde_96 = numbers(metric(at, "MDE at 96/4").value)[0]
    at.slider(key="p4_share").set_value(50)
    rerun(at)
    mde_50 = numbers(metric(at, "MDE at 50/50").value)[0]
    assert mde_50 < mde_96
    assert mde_50 == round(AD["power"]["mde_if_5050_same_total"]["mde_abs"] * 100, 2)
    at.select_slider(key="p4_power").set_value(0.90)
    rerun(at)
    assert numbers(metric(at, "MDE at 50/50").value)[0] > mde_50


def test_p4_business_panel_breakeven_and_verdict():
    at = run_page(P4)
    be50 = numbers(metric(at, "Breakeven CPM").value)[0]
    at.number_input(key="p4_value").set_value(100.0)
    rerun(at)
    be100 = numbers(metric(at, "Breakeven CPM").value)[0]
    assert abs(be100 - 2 * be50) < 0.02
    at.number_input(key="p4_value").set_value(50.0)
    expected = {5.0: "Pays back", 15.0: "Too close to call", 30.0: "Does not pay back"}
    for cpm, verdict in expected.items():
        at.number_input(key="p4_cpm").set_value(cpm)
        rerun(at)
        assert f"badge[{verdict}]" in page_text(at), (cpm, verdict)


# ------------------------------------------------------------------ page 5
def test_p5_correction_lowers_significant_hours():
    hour = AD["heterogeneity"]["most_ads_hour"]
    at = run_page(P5)
    at.selectbox(key="p5_dim").set_value("most_ads_hour")
    at.selectbox(key="p5_corr").set_value("none")
    rerun(at)
    n_none = int(metric(at, "After correction").value)
    at.selectbox(key="p5_corr").set_value("bonferroni")
    rerun(at)
    n_bonf = int(metric(at, "After correction").value)
    assert n_bonf < n_none
    assert (n_none, n_bonf) == (hour["n_sig_unadjusted"], hour["n_sig_bonferroni"])
    assert int(metric(at, "Segments tested").value) == 24


def test_p5_alpha_changes_expected_false_positives():
    at = run_page(P5)
    at.selectbox(key="p5_dim").set_value("most_ads_hour")
    rerun(at)
    assert metric(at, "Expected by chance").value == "1.2"
    at.radio(key="p5_alpha").set_value(0.10)
    rerun(at)
    assert metric(at, "Expected by chance").value == "2.4"


def test_p5_default_view_matches_results():
    day = AD["heterogeneity"]["most_ads_day"]
    at = run_page(P5)
    assert int(metric(at, "After correction").value) == day["n_sig_holm"]
    assert metric(at, "Interaction p").value == f"{day['lrt']['p_value']:.3f}"


def test_p5_every_dimension_and_correction_runs():
    at = run_page(P5)
    for dim in ("most_ads_day", "most_ads_hour", "exposure_bucket"):
        for corr in ("none", "bonferroni", "holm", "fdr_bh"):
            at.selectbox(key="p5_dim").set_value(dim)
            at.selectbox(key="p5_corr").set_value(corr)
            rerun(at)


# ------------------------------------------------------------------ page 6
def test_p6_srm_warning_first_and_headline_matches_results():
    g7 = GATE["retention_7"]
    at = run_page(P6)
    assert "Sample ratio mismatch" in at.markdown[1].value  # right after the page question
    d7 = metric(at, "D7 difference")
    assert d7.value == f"{g7['abs_lift'] * 100:+.2f} pp"
    assert ci_from_note(d7) == (round(g7["abs_ci_low"] * 100, 2), round(g7["abs_ci_high"] * 100, 2))
    assert metric(at, "D7 · this check").value == d7.value


def test_p6_exclude_zero_round_players_changes_d7():
    at = run_page(P6)
    before = metric(at, "D7 · this check")
    at.toggle(key="p6_excl0").set_value(True)
    rerun(at)
    after = metric(at, "D7 · this check")
    assert (after.value, after.proto.delta) != (before.value, before.proto.delta)
    n_zero = RESULTS["data_quality"]["cookie"]["zero_round_players"]
    assert metric(at, "Players in this check").proto.delta == f"{n_zero:,} excluded"


def test_p6_rounds_cap_and_alpha_recompute():
    at = run_page(P6)
    base = ci_from_note(metric(at, "D7 · this check"))
    at.radio(key="p6_alpha").set_value(0.01)
    rerun(at)
    strict = ci_from_note(metric(at, "D7 · this check"))
    assert strict[1] - strict[0] > base[1] - base[0]
    at.select_slider(key="p6_cap").set_value(100)
    rerun(at)
    assert int(numbers(metric(at, "Players in this check").value)[0]) < GATE["players"]["gate_30"] + GATE["players"]["gate_40"]
    assert metric(at, "D7 change vs headline").value != "+0.00 pp"


# ------------------------------------------------------------------ routing
def test_pages_route_through_app():
    """Through app.py navigation, as a user would click. Skipped until every routed page exists."""
    routed = re.findall(r'st\.Page\("([^"]+)"', (DASHBOARD / "app.py").read_text())
    if not all((DASHBOARD / p).exists() for p in routed):
        print("    (skipped: not every page routed in app.py exists yet)")
        return
    at = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=TIMEOUT)
    at.run()
    titles = {P4: "Experiment Readout: Ad vs PSA", P5: "Heterogeneity by Day / Hour",
              P6: "Gate Experiment (Cookie Cats)"}
    for page, title in titles.items():
        at.switch_page(f"views/{page}")
        rerun(at)
        assert at.title[0].value == title


# ------------------------------------------------------------------ runner
if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failed = 0
    t_all = time.time()
    for name, fn in tests:
        t0 = time.time()
        try:
            fn()
            print(f"PASS  {name}  ({time.time() - t0:.1f}s)")
        except Exception:  # noqa: BLE001 - report every failure, keep going
            failed += 1
            print(f"FAIL  {name}\n{traceback.format_exc()}")
    print(f"{len(tests) - failed}/{len(tests)} passed in {time.time() - t_all:.1f}s")
    sys.exit(1 if failed else 0)
