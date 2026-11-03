"""Tests for dashboard pages 4-6: experiment readout, heterogeneity, gate experiment.

Each page runs headless with Streamlit's AppTest. The tests check that there is
no exception or error box, that the default view shows the numbers in
reports/results.json (and the catalog takeaways under its charts), and that the
interactive controls change the computed output the way the statistics say they
should (a lower alpha widens the CI, a stricter correction flags fewer segments,
a filter moves the gate result, and so on).

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
HET = AD["heterogeneity"]
NUMBER = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")
ZERO_P = re.compile(r"\bp\s*=\s*0(?![.\d])")

P4, P5, P6 = "p4_experiment_readout.py", "p5_heterogeneity.py", "p6_gate_experiment.py"
LIFT = "Absolute lift"
_CATALOG: dict = {}


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


def note(m) -> str:
    return m.proto.delta


def ci_from_note(m) -> tuple[float, float]:
    """'95% CI +0.59 to +0.94' (optionally followed by ' pp') -> (0.59, 0.94)."""
    lo, hi = numbers(note(m).split("CI", 1)[1])[:2]
    return lo, hi


def page_text(at: AppTest) -> str:
    return "\n".join([md.value for md in at.markdown] + [c.value for c in at.caption])


def takeaways(at: AppTest) -> list[str]:
    return [re.sub(r"^<div class='takeaway'>→ |</div>$", "", md.value)
            for md in at.markdown if "class='takeaway'" in md.value]


def charts(at: AppTest) -> list[dict]:
    return [json.loads(c.proto.spec) for c in at.get("plotly_chart")]


def chart_titles(at: AppTest) -> list[str]:
    return [re.sub(r"</?b>", "", s["layout"]["title"]["text"]).split("<br>")[0] for s in charts(at)]


def catalog() -> dict:
    """Catalog figures + takeaways (the default view of every chart), built once."""
    if not _CATALOG:
        from src.catalog import build_catalog, load_caches
        _CATALOG.update(build_catalog(RESULTS, load_caches()))
    return _CATALOG


def catalog_title(key: str) -> str:
    return re.sub(r"</?b>", "", catalog()[key].fig.layout.title.text).split("<br>")[0]


def assert_catalog_defaults(at: AppTest, keys: list[str]) -> None:
    """Default view: each catalog chart is on the page with its catalog takeaway."""
    titles, tks = chart_titles(at), takeaways(at)
    for k in keys:
        assert catalog_title(k) in titles, (k, catalog_title(k), titles)
        assert catalog()[k].takeaway in tks, (k, catalog()[k].takeaway)


def all_text(at: AppTest) -> list[str]:
    out = [md.value for md in at.markdown] + [c.value for c in at.caption]
    for m in at.metric:
        out += [m.label, m.value, m.proto.delta, m.proto.help]
    return out


def assert_house_style(at: AppTest) -> None:
    """No bare dollar sign (Streamlit would start LaTeX) and no p-value printed as 0."""
    for text in all_text(at):
        assert "$" not in text, text[:200]
        assert not ZERO_P.search(text), text[:200]


# ------------------------------------------------------------------ page 4
def test_p4_default_view_matches_results():
    t, pw, bz = AD["test"], AD["power"], AD["business"]
    at = run_page(P4)
    lift = metric(at, LIFT)
    assert lift.value == f"{t['abs_lift'] * 100:+.2f} pp"
    assert ci_from_note(lift) == (round(t["abs_ci_low"] * 100, 2), round(t["abs_ci_high"] * 100, 2))
    assert metric(at, "p-value").value == "< 0.0001"          # 1.7e-13: never printed as 0
    assert metric(at, "MDE at 96/4").value == f"{pw['mde_current']['mde_abs'] * 100:.2f} pp"
    ses = pw["power_at_relative_lift"][str(pw["smallest_lift_of_interest_rel"])]
    assert metric(at, "Lift worth acting on").value == f"{ses['abs'] * 100:.2f} pp"
    power = metric(at, "Power at 96/4")
    assert power.value == f"{ses['power_current_split']:.0%}"
    assert "50/50" in note(power) and "≈100%" in note(power)
    needed = metric(at, "Users needed at 96/4")
    assert needed.value == f"{pw['total_n_for_10pct_rel_lift']['0.96']:,}"
    assert f"{pw['total_n_for_10pct_rel_lift']['0.5']:,}" in note(needed)
    assert numbers(metric(at, "Breakeven CPM").value)[0] == round(bz["breakeven_cpm_usd"]["point"], 2)
    share = metric(at, "Share caused by the ads")
    lo, hi = bz["share_of_ad_conversions_incremental_ci"]
    assert share.value == f"{bz['share_of_ad_conversions_incremental']:.0%}"
    assert note(share) == f"95% CI {lo:.0%} to {hi:.0%}"
    assert metric(at, "Last-touch overstatement").value == f"{bz['last_touch_overstatement_x']:.1f}×"
    hold = bz["always_on_holdout_cost"]
    assert metric(at, "Conversions forgone").value == f"≈{hold['conversions_forgone']:,.0f}"
    assert metric(at, "Users held out").value == f"{hold['users_per_588k_flight'] / 1e3:,.1f}K"
    assert len(at.get("plotly_chart")) >= 5
    assert_catalog_defaults(at, ["ad_rates", "ad_bootstrap", "ad_mde_split", "ad_power_curve", "ad_breakeven"])
    assert_house_style(at)


def test_p4_power_is_judged_at_smallest_lift_not_observed():
    pw = AD["power"]
    ses = pw["power_at_relative_lift"][str(pw["smallest_lift_of_interest_rel"])]
    at = run_page(P4)
    text = page_text(at)
    assert "would be caught" not in text and "achieved" not in text.lower()
    assert not any("observed" in m.label.lower() for m in at.metric)
    power_chart = [s for s in charts(at) if s["layout"]["title"]["text"].startswith("<b>Power to detect")][0]
    marks = [a["text"] for a in power_chart["layout"]["annotations"]]
    assert any(f"smallest lift worth acting on: {ses['abs'] * 100:.2f} pp" in a for a in marks), marks
    mde_chart = [s for s in charts(at) if s["layout"]["title"]["text"].startswith("<b>Minimum detectable")][0]
    assert any("smallest lift worth acting on" in a["text"] for a in mde_chart["layout"]["annotations"])
    # a larger smallest-lift-worth-acting-on raises power at the as-run split
    at.number_input(key="p4_rel_target").set_value(20.0)
    rerun(at)
    assert metric(at, "Power at 96/4").value == f"{pw['power_at_relative_lift']['0.2']['power_current_split']:.0%}"
    assert metric(at, "Lift worth acting on").value == f"{pw['power_at_relative_lift']['0.2']['abs'] * 100:.2f} pp"


def test_p4_lower_alpha_widens_ci():
    at = run_page(P4)
    lo5, hi5 = ci_from_note(metric(at, LIFT))
    at.radio(key="p4_alpha").set_value(0.01)
    rerun(at)
    m = metric(at, LIFT)
    lo1, hi1 = ci_from_note(m)
    assert note(m).startswith("99% CI")
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


def test_p4_power_panel_recomputes_without_duplicate_cards():
    pw = AD["power"]
    ses = pw["power_at_relative_lift"]["0.1"]
    at = run_page(P4)
    mde_96 = numbers(metric(at, "MDE at 96/4").value)[0]
    at.slider(key="p4_share").set_value(50)
    rerun(at)
    labels = [m.label for m in at.metric]
    assert len(labels) == len(set(labels)), labels               # no duplicated cards at 50/50
    mde = metric(at, "MDE at 50/50")
    mde_50 = numbers(mde.value)[0]
    assert mde_50 < mde_96
    assert mde_50 == round(pw["mde_if_5050_same_total"]["mde_abs"] * 100, 2)
    assert "96/4 as run" in note(mde) and f"{mde_96:.2f}" in note(mde)
    power = metric(at, "Power at 50/50")
    assert power.value == "≈100%" and f"{ses['power_current_split']:.0%}" in note(power)
    assert metric(at, "Users needed at 50/50").value == f"{pw['total_n_for_10pct_rel_lift']['0.5']:,}"
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
    assert_house_style(at)


def test_p4_holdout_share_scales_cost():
    hold = AD["business"]["always_on_holdout_cost"]
    at = run_page(P4)
    base = numbers(metric(at, "Conversions forgone").value)[0]
    assert base == round(hold["conversions_forgone"])
    assert numbers(metric(at, "Value forgone").value)[0] == round(hold["value_forgone_usd"] / 1e3, 1)
    at.slider(key="p4_holdout").set_value(10)
    rerun(at)
    doubled = numbers(metric(at, "Conversions forgone").value)[0]
    assert abs(doubled - 2 * hold["conversions_forgone"]) <= 1, doubled
    assert metric(at, "Users held out").value == f"{hold['users_per_588k_flight'] * 2 / 1e3:,.1f}K"


# ------------------------------------------------------------------ page 5
def test_p5_default_view_matches_results():
    day = HET["most_ads_day"]
    at = run_page(P5)
    assert metric(at, "Interaction p").value == f"{day['lrt']['p_value']:.2g}"
    assert int(metric(at, "Differ from the rest").value) == day["differs_from_rest"]["holm"]
    assert int(metric(at, "Lift ≠ 0 (secondary)").value) == day["lift_positive"]["holm"]
    assert metric(at, "Expected by chance").value == f"{day['n_segments'] * 0.05:.2g}"
    assert_catalog_defaults(at, ["het_day", "het_exposure"])
    text = page_text(at)
    assert f"{day['lrt_p_bonferroni_3_dims']:.2f} allowing for" in text
    assert f"p = {HET['daypart']['lrt_excluding_night']['p_value']:.2g}" in text      # daypart without Night
    assert f"p = {HET['most_ads_hour']['lrt_excluding_night']['p_value']:.2g}" in text  # hour without night hours
    assert_house_style(at)


def test_p5_counts_match_results_for_every_dimension_and_correction():
    at = run_page(P5)
    for dim in ("most_ads_day", "most_ads_hour", "daypart", "exposure_bucket"):
        at.selectbox(key="p5_dim").set_value(dim)
        for corr in ("none", "bonferroni", "holm", "fdr_bh"):
            at.selectbox(key="p5_corr").set_value(corr)
            rerun(at)
            got = (int(metric(at, "Differ from the rest").value),
                   int(metric(at, "Lift ≠ 0 (secondary)").value))
            want = (HET[dim]["differs_from_rest"][corr], HET[dim]["lift_positive"][corr])
            assert got == want, (dim, corr, got, want)
            assert int(numbers(note(metric(at, "Differ from the rest")))[0]) == HET[dim]["n_segments"]
    assert_house_style(at)


def test_p5_correction_changes_counts():
    hour, expo, day = HET["most_ads_hour"], HET["exposure_bucket"], HET["most_ads_day"]
    at = run_page(P5)
    at.selectbox(key="p5_dim").set_value("most_ads_hour")
    at.selectbox(key="p5_corr").set_value("none")
    rerun(at)
    n_none = int(metric(at, "Lift ≠ 0 (secondary)").value)
    at.selectbox(key="p5_corr").set_value("bonferroni")
    rerun(at)
    n_bonf = int(metric(at, "Lift ≠ 0 (secondary)").value)
    assert (n_none, n_bonf) == (hour["lift_positive"]["none"], hour["lift_positive"]["bonferroni"])
    assert n_bonf < n_none
    assert int(metric(at, "Differ from the rest").value) == 0
    at.selectbox(key="p5_dim").set_value("exposure_bucket")
    at.selectbox(key="p5_corr").set_value("none")
    rerun(at)
    d_none = int(metric(at, "Differ from the rest").value)
    at.selectbox(key="p5_corr").set_value("bonferroni")
    rerun(at)
    d_bonf = int(metric(at, "Differ from the rest").value)
    assert (d_none, d_bonf) == (expo["differs_from_rest"]["none"], expo["differs_from_rest"]["bonferroni"])
    assert d_bonf < d_none
    at.selectbox(key="p5_dim").set_value("most_ads_day")
    rerun(at)
    assert int(metric(at, "Differ from the rest").value) == day["differs_from_rest"]["bonferroni"]


def test_p5_alpha_recomputes_contrasts_live():
    import pandas as pd
    from src import config as C
    from src import stats as S
    cells = pd.read_parquet(C.PROCESSED_DIR / "agg_ad_cells.parquet")
    at = run_page(P5)
    at.selectbox(key="p5_dim").set_value("most_ads_hour")
    rerun(at)
    assert metric(at, "Expected by chance").value == "1.2"
    at.radio(key="p5_alpha").set_value(0.10)
    rerun(at)
    assert metric(at, "Expected by chance").value == "2.4"
    at.selectbox(key="p5_dim").set_value("most_ads_day")
    at.radio(key="p5_alpha").set_value(0.01)
    rerun(at)
    live = S.segment_lifts(cells, "most_ads_day", "ad", "psa", alpha=0.01, method="holm", order=C.DAY_ORDER)
    assert int(metric(at, "Differ from the rest").value) == int(live["differs_adj"].sum())
    assert int(metric(at, "Lift ≠ 0 (secondary)").value) == int(live["significant_adj"].sum())
    forest = [s for s in charts(at) if s["layout"]["title"]["text"].startswith("<b>Ad lift by peak ad day")][0]
    assert "99% CI" in forest["layout"]["title"]["text"]


def test_p5_question_toggle_switches_the_fill():
    at = run_page(P5)
    names = {tr.get("name") for tr in charts(at)[0]["data"]}
    assert any("differs from other segments" in (n or "") for n in names), names
    at.radio(key="p5_question").set_value("lift")
    rerun(at)
    forest = charts(at)[0]
    assert "filled = lift ≠ 0" in forest["layout"]["title"]["text"]
    assert any("Lift ≠ 0" in (tr.get("name") or "") for tr in forest["data"])
    assert any("mostly measure sample size" in t for t in takeaways(at))


def test_p5_every_dimension_renders_with_the_story_wording():
    at = run_page(P5)
    for dim, key in (("most_ads_hour", "het_hour"), ("daypart", "het_daypart"),
                     ("exposure_bucket", "het_exposure_forest")):
        at.selectbox(key="p5_dim").set_value(dim)
        at.selectbox(key="p5_corr").set_value("holm")
        at.radio(key="p5_alpha").set_value(0.05)
        at.radio(key="p5_question").set_value("differs")
        rerun(at)
        assert_catalog_defaults(at, [key])
    text = page_text(at).lower()
    for banned in ("odds ratio", "breslow", "saturat"):       # CMH only as standardized lift; no saturation claim
        assert banned not in text, banned
    mh = [HET[d]["sensitivity_stratified"]["mh_risk_diff"] * 100 for d in ("most_ads_day", "most_ads_hour",
                                                                             "daypart", "exposure_bucket")]
    assert f"{min(mh):.2f}–{max(mh):.2f} pp" in page_text(at)


# ------------------------------------------------------------------ page 6
def test_p6_srm_warning_first_on_raw_counts():
    srm = GATE["srm"]
    at = run_page(P6)
    first = at.markdown[1].value                                  # right after the page question
    assert "Sample ratio mismatch: WARNING" in first
    assert f"{srm['n_c']:,}" in first and f"{srm['n_t']:,}" in first
    assert (srm["n_c"], srm["n_t"]) == (GATE["players_raw"]["gate_30"], GATE["players_raw"]["gate_40"])
    assert f"p = {srm['p_value']:.2g}" in first and srm["status"] == "WARNING"
    assert "0.0085" not in page_text(at)
    assert_house_style(at)


def test_p6_integrity_checks_match_results():
    wc, dec, ncr = GATE["worst_case_bound"], GATE["d7_decomposition"], GATE["negative_control"]["never_reached_30"]
    at = run_page(P6)
    assert metric(at, "Extra players").value == f"{wc['excess_players_gate_40']:,}"
    assert note(metric(at, "Extra players")).startswith(f"{GATE['excess_players_with_lt_15_rounds']:,}")
    assert metric(at, "Negative control").value == f"{ncr['retention_7']['abs_lift'] * 100:+.2f} pp"
    could = metric(at, "Gate could cause")
    assert could.value == f"{dec['within_reached_30'] * 100:+.2f} pp"
    ci = dec["install_level_effect_ci_if_only_reachers"]
    assert ci_from_note(could) == (round(ci[0] * 100, 2), round(ci[1] * 100, 2))
    assert metric(at, "Worst case").value == f"{wc['d7_diff_if_excess_removed'] * 100:+.2f} pp"
    gap_tk = [t for t in takeaways(at) if t.startswith("Before round 30")][0]
    assert f"p = {GATE['pre_gate_engagement']['mannwhitney_p']:.3f}" in gap_tk
    text = page_text(at)
    for s in GATE["srm_by_stratum"].values():
        assert f"| {s['n_c']:,} | {s['n_t']:,} |" in text, s
    assert "| 0.0002 |" in text and "| 0.81 |" in text
    assert_catalog_defaults(at, ["gate_engagement_gap", "gate_negative_control", "gate_decomposition",
                                 "gate_rates", "gate_bootstrap"])


def test_p6_naive_result_and_guardrails_match_results():
    g7, g1, rd = GATE["retention_7"], GATE["retention_1"], GATE["rounds"]
    at = run_page(P6)
    d7 = metric(at, "D7 difference")
    assert d7.value == f"{g7['abs_lift'] * 100:+.2f} pp"
    assert ci_from_note(d7) == (round(g7["abs_ci_low"] * 100, 2), round(g7["abs_ci_high"] * 100, 2))
    d1 = metric(at, "D1 difference")
    assert ci_from_note(d1) == (round(g1["abs_ci_low"] * 100, 2), round(g1["abs_ci_high"] * 100, 2))
    assert metric(at, "D7 · this check").value == d7.value
    rounds = metric(at, "Mean rounds diff.")
    assert rounds.value == f"{rd['mean_diff']:+.2f}"
    assert ci_from_note(rounds) == tuple(round(x, 2) for x in rd["mean_diff_boot_ci"])
    assert metric(at, "Median rounds").value == f"{rd['median_c']:.0f} vs {rd['median_t']:.0f}"
    assert metric(at, "D1 drop not ruled out").value == f"{abs(g1['abs_ci_low']) * 100:.1f} pp"
    assert metric(at, "D7 MDE").value == f"±{g7['mde']['mde_abs'] * 100:.2f} pp"
    text = page_text(at)
    for retired in ("Fewer D7 players", "fewer players still playing", "≈370", "barely"):
        assert retired not in text, retired
    assert not any("Fewer D7" in m.label for m in at.metric)


def test_p6_exclude_zero_round_players_changes_d7():
    at = run_page(P6)
    before = metric(at, "D7 · this check")
    at.toggle(key="p6_excl0").set_value(True)
    rerun(at)
    after = metric(at, "D7 · this check")
    assert (after.value, note(after)) != (before.value, note(before))
    n_zero = RESULTS["data_quality"]["cookie"]["zero_round_players"]
    assert note(metric(at, "Players in this check")) == f"{n_zero:,} excluded"


def test_p6_rounds_cap_and_alpha_recompute():
    at = run_page(P6)
    base = ci_from_note(metric(at, "D7 · this check"))
    at.radio(key="p6_alpha").set_value(0.01)
    rerun(at)
    strict = ci_from_note(metric(at, "D7 · this check"))
    assert strict[1] - strict[0] > base[1] - base[0]
    at.select_slider(key="p6_cap").set_value(100)
    rerun(at)
    n_all = GATE["players"]["gate_30"] + GATE["players"]["gate_40"]
    assert int(numbers(metric(at, "Players in this check").value)[0]) < n_all
    assert metric(at, "D7 change vs headline").value != "+0.00 pp"


def test_p6_d1_statements_follow_the_ci():
    """The sensitivity text and the D1 card are read off the same interval (no 'not significant' next to a CI
    that excludes 0)."""
    at = run_page(P6)
    lo, hi = ci_from_note(metric(at, "D1 · this check"))
    sens = [t for t in takeaways(at) if t.startswith("Headline")][0]
    assert lo < 0 < hi and "D1 is inconclusive" in sens
    at.select_slider(key="p6_cap").set_value(100)
    rerun(at)
    lo, hi = ci_from_note(metric(at, "D1 · this check"))
    sens = [t for t in takeaways(at) if t.startswith("This check")][0]
    assert hi < 0, (lo, hi)                                       # this cut's D1 CI excludes 0
    assert "D1 is lower in gate_40" in sens and "D1 is inconclusive" not in sens
    assert "not significant" not in page_text(at)


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
