"""Tests for dashboard pages 4-6: experiment readout, heterogeneity, gate experiment (analysis core v3).

Each page runs headless with Streamlit's AppTest. The tests check that there is
no exception or error box; that the default view shows the numbers in
reports/results.json and reports/tables/ (and the catalog takeaways under its
charts); that the interactive controls change the computed output the way the
statistics say they should (a lower alpha widens the CI, a stricter correction
flags fewer segments, a filter moves the gate result, and so on); that page 6
follows the v3 chain in order; and that no withdrawn wording comes back, on the
rendered pages or anywhere in their source.

Run:   .venv/bin/python tests/test_dashboard_b.py
pytest also collects the test_* functions if it is installed.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
for _p in (str(ROOT), str(DASHBOARD)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from streamlit.testing.v1 import AppTest  # noqa: E402

VIEWS = DASHBOARD / "views"
TABLES = ROOT / "reports" / "tables"
TIMEOUT = 120
RESULTS = json.loads((ROOT / "reports" / "results.json").read_text())
AD, GATE = RESULTS["ad"], RESULTS["cookie"]["gate"]
HET = AD["heterogeneity"]
NUMBER = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")

P4, P5, P6 = "p4_experiment_readout.py", "p5_heterogeneity.py", "p6_gate_experiment.py"
LIFT = "Absolute lift"
_CATALOG: dict = {}

# Wording withdrawn in v3 (plus what v2 already withdrew). Regexes, so a line break or a variant spelling
# cannot slip through. Checked on every rendered text element and on the page sources (which also covers branches
# a default run does not render).
WITHDRAWN = {
    "worst-case wording (it is the best case for gate_40)": r"worst[\s_-]*case",
    "'no engagement difference'": r"no engagement\s+difference",
    "'no sign of any / a benefit' (write: a retention benefit)": r"no sign of (?:any|a)\s+benefit",
    "'best estimate' of the gate effect": r"best\s+estimate",
    "'explains about 60%' for the extra installs": r"explains?\s+(?:about\s+|~\s?)60",
    "'every cut points the same way'": r"every\s+cut\s+points",
    "'762 of the 790' (implies identified players)": r"762\s+of\s+(?:the\s+|its\s+)?7(?:89|90)",
    "causal gate wording": r"costs\s+0\.8|gate_40\s+costs|\blowered\b|loses\s+D7",
    "retired re-test sizes": r"276K|276,092|101,852|\b102K\b|102,000",
    "retired R6 sizing": r"\b14,250\b",
    "'145 per 45K' scaling": r"\b145\s+(?:per|fewer)",
    "'a D1 drop of up to'": r"drop\s+of\s+up\s+to",
    "'N night hours'": r"\d+\s+night\s+hours|night\s+hours\s+have\s+zero",
    "'100% at 50/50' (write ≈100%)": r"(?<!≈)\b100%\s+at\s+50/50",
    "old contrast points": r"\+0\.92\s+pp|[−-]0\.76\s+pp|\+0\.3[23]\s+pp\s+vs|0\.92\s+pp\s+above|0\.76\s+pp\s+below",
    "daypart / time-of-day test as R3": r"daypart\s+test|time-of-day\s+test",
    "'set by the business'": r"set\s+by\s+the\s+business",
    "MDE-vs-estimate comparison": r"well\s+below\s+(?:that|the)|less\s+than\s+half\s+the\s+D7|not\s+powered\s+to",
    "buying a day": r"buying\s+\w*day\b",
    "saturation claim": r"saturat",
    "'8 of 24'": r"\b8\s+of\s+24\b",
    "'barely matters'": r"\bbarely\b",
    "'370'": r"\b370\b",
    "status 'WARN'": r"\bWARN\b",
    "p printed as 0": r"\bp\s*=\s*0(?:\.0+)?(?![.\d])",
    "bare dollar sign": r"\$",
    "'cohorts'": r"\bcohorts\b",
    "post-hoc power": r"post-hoc\s+power|achieved\s+power|power\s+at\s+the\s+observed\s+effect\s+is\s+\d",
    "'0.0085' (cleaned-count SRM p)": r"0\.0085",
    "persona wording": r"not\s+our\s+app|standing\s+in\s+for",
}
CASE_SENSITIVE = {"status 'WARN'"}
# page 6 compares versions under an SRM warning: no causal verbs at all
P6_CAUSAL = re.compile(r"\b(?:costs?|caused|lowers|lowered|loses)\b", re.I)


# ------------------------------------------------------------------ helpers
def numbers(text: str) -> list[float]:
    return [float(x.replace(",", "").replace("−", "-")) for x in NUMBER.findall(text)]


def norm(text: str) -> str:
    """Compare signed numbers whatever the minus sign: pages print a true minus, f-strings a hyphen."""
    return text.replace("−", "-")


def pp(x: float, nd: int = 2) -> str:
    """Expected metric text for a proportion, in signed pp (hyphen-minus; compare with norm())."""
    return f"{x * 100:+.{nd}f} pp"


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


def r2(x: float) -> float:
    return round(x * 100, 2)


def page_text(at: AppTest) -> str:
    """Markdown and captions, whitespace collapsed (the explainers wrap lines in the source)."""
    return re.sub(r"\s+", " ", " ".join([md.value for md in at.markdown] + [c.value for c in at.caption]))


def takeaways(at: AppTest) -> list[str]:
    return [re.sub(r"^<div class='takeaway'>→ |</div>$", "", md.value)
            for md in at.markdown if "class='takeaway'" in md.value]


def charts(at: AppTest) -> list[dict]:
    return [json.loads(c.proto.spec) for c in at.get("plotly_chart")]


def title_of(spec: dict) -> str:
    return re.sub(r"</?b>", "", spec["layout"]["title"]["text"]).split("<br>")[0]


def chart_titles(at: AppTest) -> list[str]:
    return [title_of(s) for s in charts(at)]


def chart(at: AppTest, title: str) -> dict:
    hits = [s for s in charts(at) if title_of(s) == title]
    assert hits, (title, chart_titles(at))
    return hits[0]


def decode(arr) -> np.ndarray:
    """Plotly JSON arrays: a plain list or a typed array {'dtype', 'bdata', 'shape'}."""
    if isinstance(arr, dict):
        out = np.frombuffer(base64.b64decode(arr["bdata"]), dtype=np.dtype(arr["dtype"]))
        if "shape" in arr:
            out = out.reshape([int(x) for x in str(arr["shape"]).split(",")])
        return out
    return np.asarray(arr)


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


def flat(at: AppTest) -> list[tuple[str, str]]:
    """Every text element and chart title, in document order: [(kind, text)]."""
    out: list[tuple[str, str]] = []

    def walk(node) -> None:
        for c in getattr(node, "children", {}).values():
            kind = type(c).__name__
            if kind == "Metric":
                out.append(("metric", c.label))
            elif kind in ("Markdown", "Caption", "Subheader", "Title"):
                out.append((kind.lower(), c.value))
            elif kind == "UnknownElement" and getattr(c, "type", "") == "plotly_chart":
                out.append(("chart", title_of(json.loads(c.proto.spec))))
            walk(c)

    walk(at.main)
    return out


def all_text(at: AppTest) -> list[str]:
    """Markdown, captions, subheaders, metric labels / values / notes / help, and chart titles, axes, legends and
    annotations."""
    out = [md.value for md in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader]
    for m in at.metric:
        out += [m.label, m.value, m.proto.delta, m.proto.help]
    for s in charts(at):
        lay = s["layout"]
        out.append(lay["title"]["text"])
        out += [a.get("text", "") for a in lay.get("annotations", [])]
        for ax in ("xaxis", "yaxis"):
            t = lay.get(ax, {}).get("title", {})
            out.append(t.get("text", "") if isinstance(t, dict) else str(t))
        out += [tr.get("name") or "" for tr in s["data"]]
    return out


def withdrawn_hits(texts: list[str]) -> list[tuple[str, str]]:
    hits = []
    for name, pat in WITHDRAWN.items():
        rx = re.compile(pat) if name in CASE_SENSITIVE else re.compile(pat, re.I)
        hits += [(name, t[:160]) for t in texts if t and rx.search(t)]
    return hits


def assert_no_withdrawn(at: AppTest, where: str) -> None:
    hits = withdrawn_hits(all_text(at))
    assert not hits, (where, hits)


# ------------------------------------------------------------------ page 4
def test_p4_default_view_matches_results():
    t, pw, bz = AD["test"], AD["power"], AD["business"]
    at = run_page(P4)
    lift = metric(at, LIFT)
    assert lift.value == f"{t['abs_lift'] * 100:+.2f} pp"
    assert ci_from_note(lift) == (r2(t["abs_ci_low"]), r2(t["abs_ci_high"]))
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
    hold = bz["always_on_holdout_cost"]
    assert metric(at, "Conversions forgone").value == f"≈{hold['conversions_forgone']:,.0f}"
    assert metric(at, "Users held out").value == f"{hold['users_per_588k_flight'] / 1e3:,.1f}K"
    assert len(at.get("plotly_chart")) >= 5
    assert_catalog_defaults(at, ["ad_rates", "ad_bootstrap", "ad_mde_split", "ad_power_curve", "ad_breakeven"])
    assert_no_withdrawn(at, "p4 default")


def test_p4_last_touch_overstatement_carries_its_ci():
    bz = AD["business"]
    lo, hi = bz["last_touch_overstatement_ci"]
    ci_txt = f"{bz['last_touch_overstatement_x']:.1f}× (95% CI {lo:.1f}–{hi:.1f}×)"   # 3.3× (95% CI 2.7–4.3×)
    at = run_page(P4)
    lt = metric(at, "Last-touch overstatement")
    assert lt.value == f"{bz['last_touch_overstatement_x']:.1f}×"
    assert note(lt) == f"95% CI {lo:.1f}–{hi:.1f}×"
    assert "any-touch" in lt.proto.help and "saw at least one ad" in lt.proto.help
    readout = [md.value for md in at.markdown if md.value.startswith("**Readout in one line.**")][0]
    assert "any-touch" in readout and ci_txt in readout
    decision = [md.value for md in at.markdown if "**R1 · Growth PM:**" in md.value][0]
    assert ci_txt in decision


def test_p4_smallest_lift_is_a_config_placeholder():
    """Provenance: a placeholder in config.yaml that the PM and Finance agree in practice, sized in conversions and
    USD per flight (the WITHDRAWN guard rejects the v2 provenance wording)."""
    t, pw = AD["test"], AD["power"]
    rel = pw["smallest_lift_of_interest_rel"]
    conv = rel * t["conv_c"] / t["n_c"] * t["n_t"]                 # ≈1,008 conversions per ad flight
    usd_k = conv * AD["business"]["value_per_conversion_usd"] / 1e3
    at = run_page(P4)
    help_ = metric(at, "Lift worth acting on").proto.help
    for text in (help_, page_text(at)):
        assert "placeholder assumption in config.yaml" in text
        assert "PM and Finance" in text
        assert f"≈{float(f'{conv:.2g}'):,.0f} conversions per {t['n_t'] / 1e3:,.0f}K-user ad flight" in text
        assert f"≈USD {usd_k:,.0f}K" in text
    at.number_input(key="p4_rel_target").set_value(20.0)
    rerun(at)
    assert f"≈{float(f'{2 * conv:.2g}'):,.0f} conversions" in metric(at, "Lift worth acting on").proto.help


def test_p4_srm_is_most_likely_a_fixed_quota():
    srm = AD["srm"]
    at = run_page(P4)
    text = page_text(at)
    assert "most likely a fixed quota" in text and "valid design" in text
    assert f"{srm['prob_exactly_nearest_integer']:.2%}" in text                                  # 0.27%
    assert f"±{srm['sd_users_under_random_assignment']:.0f}" in text                              # ±150
    assert "so the split was set by a quota" not in text.lower()


def test_p4_power_is_judged_at_smallest_lift_not_observed():
    pw = AD["power"]
    ses = pw["power_at_relative_lift"][str(pw["smallest_lift_of_interest_rel"])]
    at = run_page(P4)
    text = page_text(at)
    assert "would be caught" not in text and "achieved" not in text.lower()
    assert not any("observed" in m.label.lower() for m in at.metric)
    power_chart = [s for s in charts(at) if s["layout"]["title"]["text"].startswith("<b>Power to detect")][0]
    marks = [a["text"].replace("<br>", " ") for a in power_chart["layout"]["annotations"]]
    assert any(f"smallest lift worth acting on: {ses['abs'] * 100:.2f} pp" in a for a in marks), marks
    mde_chart = [s for s in charts(at) if s["layout"]["title"]["text"].startswith("<b>Minimum detectable")][0]
    assert any("smallest lift worth acting on" in a["text"] for a in mde_chart["layout"]["annotations"])
    decision = [md.value for md in at.markdown if "**R4 · Analytics + Eng:**" in md.value][0]
    assert f"{ses['power_current_split']:.0%} power" in decision and "≈100%" in decision
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
    assert mde_50 == r2(pw["mde_if_5050_same_total"]["mde_abs"])
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
    assert_no_withdrawn(at, "p4 with a CPM entered")


def test_p4_holdout_cost_is_read_against_the_as_run_psa_arm():
    hold = AD["business"]["always_on_holdout_cost"]
    t = AD["test"]
    per_user = t["conv_t"] / t["n_t"] - t["conv_c"] / t["n_c"]
    n_total = t["n_t"] + t["n_c"]
    at = run_page(P4)
    base = numbers(metric(at, "Conversions forgone").value)[0]
    assert base == round(hold["conversions_forgone"])
    assert numbers(metric(at, "Value forgone").value)[0] == round(hold["value_forgone_usd"] / 1e3, 1)
    tk = [x for x in takeaways(at) if x.startswith(f"A {hold['share']:.0%} holdout")][0]
    assert (f"this test's {hold['as_run_control_share']:.0%} PSA arm already forgoes "
            f"≈{hold['as_run_control_conversions_forgone']:,.0f}") in tk                    # ≈181
    assert f"costs ≈{hold['extra_conversions_vs_as_run']:,.0f} more" in tk                  # ≈45
    assert f"≈{hold['as_run_control_conversions_forgone']:,.0f}" in metric(at, "Conversions forgone").proto.help
    at.slider(key="p4_holdout").set_value(10)
    rerun(at)
    doubled = numbers(metric(at, "Conversions forgone").value)[0]
    assert abs(doubled - 2 * hold["conversions_forgone"]) <= 1, doubled
    assert metric(at, "Users held out").value == f"{hold['users_per_588k_flight'] * 2 / 1e3:,.1f}K"
    step10 = 0.10 * n_total * per_user - hold["as_run_control_conversions_forgone"]
    assert f"costs ≈{step10:,.0f} more" in [x for x in takeaways(at) if x.startswith("A 10% holdout")][0]
    at.slider(key="p4_holdout").set_value(2)
    rerun(at)
    assert "fewer than this test's 4% PSA arm" in [x for x in takeaways(at) if x.startswith("A 2% holdout")][0]


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
    assert f"{day['lrt_p_bonferroni_3_dims']:.2g} allowing for" in text                    # 0.038
    assert f"p = {HET['daypart']['lrt_excluding_night']['p_value']:.2g}" in text      # daypart without Night
    assert f"p = {HET['most_ads_hour']['lrt_excluding_night']['p_value']:.2g}" in text  # hours without Night
    assert "odds scale" in text and "percentage-point scale" in text
    assert_no_withdrawn(at, "p5 default")


def test_p5_contrast_is_the_raw_difference_with_an_agresti_caffo_ci():
    """diff_vs_rest is Lift − Lift, rest (v3); the CI and p stay Agresti–Caffo, so sparse cells are off-centre."""
    day = pd.read_csv(TABLES / "ad_lift_by_most_ads_day.csv").set_index("most_ads_day")
    assert np.allclose(day["diff_vs_rest"], day["abs_lift"] - day["lift_rest"])
    at = run_page(P5)
    seg = at.dataframe[0].value.set_index("Day")                              # the segment table, Holm, α = 0.05
    assert np.allclose(seg["Diff. vs rest"], seg["Lift"] - seg["Lift, rest"])
    for col, src in (("Diff. vs rest", "diff_vs_rest"), ("CI low", "diff_vs_rest_ci_low"),
                     ("CI high", "diff_vs_rest_ci_high"), ("Adj. p", "p_vs_rest_adj")):
        scale = 1 if col == "Adj. p" else 100
        assert np.allclose(seg.loc[day.index, col].to_numpy(), day[src].to_numpy() * scale), col
    cap = [c.value for c in at.caption if "Diff. vs rest" in c.value][0]
    for phrase in ("raw difference", "Lift − Lift, rest", "Agresti–Caffo", "+1 conversion and +1 non-conversion",
                   "not centred on the point", "odds scale"):
        assert phrase in cap, phrase
    tue, thu = day.loc["Tuesday"], day.loc["Thursday"]
    text = page_text(at)
    assert f"Tuesday-peak users {tue['diff_vs_rest'] * 100:.2f} pp above" in text           # 0.95
    assert f"Thursday-peak users {abs(thu['diff_vs_rest']) * 100:.2f} pp below" in text     # 0.74
    # the forest's hover carries the same raw contrast, and its p-values never print as 0.0000
    for tr in charts(at)[0]["data"]:
        cd = decode(tr["customdata"])
        for name, row in zip(tr["y"], cd):
            assert abs(float(row[5]) - day.loc[name, "diff_vs_rest"] * 100) < 1e-9, name   # mixed row: numbers + p text
            assert not str(row[4]).strip().startswith("= 0.0000") and not str(row[6]).startswith("= 0.0000")
        assert ":.4f}" not in tr["hovertemplate"], tr["hovertemplate"]
    # Night, live on the daypart view
    night = pd.read_csv(TABLES / "ad_lift_by_daypart.csv").set_index("daypart").loc["Night (0-5)"]
    at.selectbox(key="p5_dim").set_value("daypart")
    rerun(at)
    dp = at.dataframe[0].value.set_index("Daypart")
    assert abs(dp.loc["Night (0-5)", "Diff. vs rest"] - night["diff_vs_rest"] * 100) < 1e-9   # +0.45
    assert dp.loc["Night (0-5)", "Differs"] == "No"


def test_p5_tuesday_caveat_zero_hours_and_canonical_r3():
    day = pd.read_csv(TABLES / "ad_lift_by_most_ads_day.csv").set_index("most_ads_day")
    hour = pd.read_csv(TABLES / "ad_lift_by_most_ads_hour.csv")
    tue = day.loc["Tuesday"]
    assert (day["rate_c"] < tue["rate_c"]).sum() <= 1                       # one of the lowest PSA rates of the week
    at = run_page(P5)
    text = page_text(at)
    assert (f"Tuesday's PSA arm has {int(tue['n_c']):,} users and {int(tue['conv_c'])} conversions "
            f"({tue['rate_c']:.2%}, one of the lowest control rates of the week)") in text   # 2,907 / 42 / 1.44%
    zero = hour.loc[hour["conv_c"] == 0, "most_ads_hour"].tolist()
    assert len(zero) == HET["most_ads_hour"]["segments_with_zero_control_conversions"]
    assert "6 hours (0–2 and 4–6, mostly night)" in text and zero == [0, 1, 2, 4, 5, 6]
    assert "randomizes the delivery schedule" in text and "Tuesday vs. Thursday delivery" in text
    assert "user habit recorded after assignment" in text


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
        assert_no_withdrawn(at, f"p5 {dim}")


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
    seg = at.dataframe[0].value.set_index("Day")                 # the live table at α = 0.01: wider contrast CIs
    live = live.set_index("most_ads_day")
    assert np.allclose(seg.loc[live.index, "CI low"].to_numpy(), live["diff_vs_rest_ci_low"].to_numpy() * 100)
    assert np.allclose(seg["Diff. vs rest"], seg["Lift"] - seg["Lift, rest"])        # the point does not move


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
    for banned in ("odds ratio", "breslow"):       # CMH only as standardized lift (saturation: WITHDRAWN guard)
        assert banned not in text, banned
    assert_no_withdrawn(at, "p5 exposure forest")
    mh = [HET[d]["sensitivity_stratified"]["mh_risk_diff"] * 100 for d in ("most_ads_day", "most_ads_hour",
                                                                             "daypart", "exposure_bucket")]
    assert f"{min(mh):.2f}–{max(mh):.2f} pp" in page_text(at)


def test_p5_exposure_cards_use_the_v3_concentration():
    con = HET["exposure_bucket"]["concentration"]
    le20, b2135 = con["le_20_ads_pooled"], con["bucket_21_35"]
    at = run_page(P5)
    m = metric(at, "Users with ≤ 20 ads")
    assert m.value == f"{con['share_users_le_20_ads']:.0%}"
    assert norm(note(m)).startswith(f"lift {le20['abs_lift'] * 100:+.2f} pp")              # −0.02 pp
    assert f"{le20['mde_abs'] * 100:.2f} pp ({le20['mde_rel']:+.0%}" in m.proto.help     # 0.18 pp (+35%
    m = metric(at, "21–35 ads: inconclusive")
    assert norm(m.value) == pp(b2135["abs_lift"])
    assert ci_from_note(m) == (r2(b2135["abs_ci_low"]), r2(b2135["abs_ci_high"]))
    m = metric(at, "Lift share, 36–200 ads")
    assert m.value == f"{con['share_incremental_conversions_36_200']:.0%}"
    assert (f"{con['incremental_conversions_36_200']:,.0f} of {con['incremental_conversions_bucketwise_total']:,.0f}"
            in m.proto.help)                                                                  # 4,396 of 4,465
    assert f"{AD['business']['incremental_conversions']['point']:,.0f}" in m.proto.help       # headline 4,343


# ------------------------------------------------------------------ page 6
def test_p6_follows_the_v3_chain_in_order():
    """naive (not certified) -> SRM WARNING -> net excess by band -> pre-gate play -> negative control -> decomposition
    -> best case for gate_40 -> guardrails -> re-test sizing -> decision."""
    ncx = GATE["negative_control"]["never_reached_30_excess_removed"]
    at = run_page(P6)
    seq = flat(at)
    steps = [
        ("naive, not certified", lambda k, t: k == "subheader" and "Naive result" in t and "not certified" in t),
        ("SRM WARNING", lambda k, t: k == "markdown" and "Sample ratio mismatch: WARNING" in t),
        ("net excess by band", lambda k, t: k == "markdown" and "Net excess in gate_40" in t),
        ("pre-gate play", lambda k, t: k == "chart" and t == catalog_title("gate_engagement_gap")),
        ("negative control", lambda k, t: k == "chart" and t == catalog_title("gate_negative_control")),
        ("negative control without the net excess",
         lambda k, t: k == "markdown" and f"Removing the net {ncx['excess_removed']:,}" in t),
        ("decomposition", lambda k, t: k == "chart" and t == catalog_title("gate_decomposition")),
        ("best case for gate_40", lambda k, t: k == "markdown" and t.startswith("**Best case for gate_40.**")),
        ("guardrails", lambda k, t: k == "subheader" and "Guardrails" in t),
        ("re-test sizing", lambda k, t: k == "subheader" and "Re-test sizing" in t),
        ("decision", lambda k, t: k == "subheader" and "Decision" in t),
    ]
    idx = []
    for name, pred in steps:
        hits = [i for i, (k, t) in enumerate(seq) if pred(k, t)]
        assert hits, name
        idx.append(hits[0])
    assert idx == sorted(idx), list(zip([s[0] for s in steps], idx))


def test_p6_srm_warning_on_raw_counts_and_descriptive_bands():
    srm, sbs = GATE["srm"], GATE["srm_by_stratum"]
    at = run_page(P6)
    warn = [md.value for md in at.markdown if "Sample ratio mismatch" in md.value]
    assert len(warn) == 1 and srm["status"] == "WARNING" and "Sample ratio mismatch: WARNING" in warn[0]
    assert f"{srm['n_c']:,} gate_30 vs {srm['n_t']:,} gate_40" in warn[0]
    assert (srm["n_c"], srm["n_t"]) == (GATE["players_raw"]["gate_30"], GATE["players_raw"]["gate_40"])
    assert f"p = {srm['p_value']:.2g}" in warn[0]                                            # 0.0086
    assert "0.01 warning line" in warn[0] and "0.001 hard stop" in warn[0]
    table = [md.value for md in at.markdown if "Net excess in gate_40" in md.value][0]
    rows = [r for r in table.splitlines() if "rounds" in r]
    assert len(rows) == len(sbs) == 4
    for key, s in sbs.items():
        row = [r for r in rows if f"| {s['n_c']:,} | {s['n_t']:,} |" in r]
        assert len(row) == 1, key
        assert f"| {s['net_excess_t']:+,} |" in norm(row[0]), (key, row)
        assert not re.search(r"\b(?:PASS|FAIL|WARNING|Balanced)\b", row[0], re.I), row   # post-hoc: no labels
    assert "| 0.0002 |" in table and "| 0.56 |" in table and "| 0.81 |" in table
    text = page_text(at)
    assert "chosen after seeing the warning" in text and "descriptive" in text
    assert f"a net excess of {sbs['rounds_lt_15']['net_excess_t']:,} among players with < 15 rounds" in text
    extra = GATE["best_case_for_gate_40"]["excess_players_gate_40"]
    assert (f"≈{round(extra, -1):,} extra installs ({GATE['excess_players_raw']:,} in the raw log, {extra:,} after "
            "the one-outlier drop") in text
    pg = GATE["pre_gate_engagement"]
    assert f"p = {pg['mannwhitney_p']:.1g}" in text and f"p = {pg['mannwhitney_p_within_lt_30']:.2g}" in text
    assert "not independent evidence" in text


def test_p6_what_the_gate_could_explain_matches_results():
    nc, band = GATE["negative_control"], GATE["retention_by_rounds_band"]
    dec, best = GATE["d7_decomposition"], GATE["best_case_for_gate_40"]
    ncr, ncx = nc["never_reached_30"]["retention_7"], nc["never_reached_30_excess_removed"]
    at = run_page(P6)
    m = metric(at, "Negative control")
    assert norm(m.value) == pp(ncr["abs_lift"]) and f"p = {ncr['p_value']:.2g}" in note(m)       # −0.33, 0.049
    assert "just below 0" in m.proto.help and "borderline" in m.proto.help
    m = metric(at, f"Without the net {ncx['excess_removed']:,}")
    assert norm(m.value) == pp(ncx["retention_7"]["abs_lift"])                                    # −0.22 pp
    assert f"p = {ncx['retention_7']['p_value']:.2g}" in note(m)                                  # 0.19
    ci = dec["install_level_effect_ci_if_only_reachers"]
    m = metric(at, "Gate could explain")
    assert norm(m.value) == pp(dec["within_reached_30"]) and ci_from_note(m) == (r2(ci[0]), r2(ci[1]))
    m = metric(at, "Best case for gate_40")
    assert norm(m.value) == pp(best["d7_diff_if_excess_removed"])                                 # −0.50 pp
    assert ci_from_note(m) == (r2(best["ci"][0]), r2(best["ci"][1]))                              # −1.01 to +0.02
    # the negative-control and decomposition charts carry the catalog's rows (labels broken onto two lines for phones)
    for key in ("gate_negative_control", "gate_decomposition"):
        page_fig = chart(at, catalog_title(key))
        rows = [tr["y"][0].replace("<br>", " ") for tr in page_fig["data"]]
        assert rows == [tr.y[0] for tr in catalog()[key].fig.data], (key, rows)
        assert len(rows) == (5 if key == "gate_negative_control" else 4)
        assert page_fig["layout"]["yaxis"].get("automargin"), key        # labels size the margin, not a fixed 330 px
    assert chart(at, catalog_title("gate_decomposition"))["layout"]["margin"]["l"] < 100
    assert_catalog_defaults(at, ["gate_engagement_gap", "gate_negative_control", "gate_decomposition",
                                 "gate_rates", "gate_bootstrap"])
    text = norm(page_text(at))
    b15, b1529, b30 = (band[k]["retention_7"] for k in ("rounds_lt_15", "rounds_15_29", "rounds_ge_30"))
    assert f"moves it only to {pp(ncx['retention_7']['abs_lift'])}" in text
    assert f"15–29 rounds ({pp(b1529['abs_lift'])}" in text and f"< 15-round installs ({pp(b15['abs_lift'])}" in text
    assert f"same D7 gap ({pp(b1529['abs_lift'])}) as players with 30+ rounds ({pp(b30['abs_lift'])})" in text
    share = (dec["composition"] + dec["within_never_reached_30"]) / dec["naive_diff"]
    assert f"About {round(share * 10) * 10:.0f}% of the naive gap" in text                     # about 60%
    per = [x * 1e4 for x in (dec["within_reached_30"], *ci)]
    assert f"≈{abs(per[0]):.0f} fewer Day-7 players (95% CI {abs(per[1]):.0f} fewer to {per[2]:.0f} more)" in text
    assert "not an estimate of the gate's effect" in text and "Its interval includes 0" in text


def test_p6_naive_result_matches_results():
    g7, g1 = GATE["retention_7"], GATE["retention_1"]
    at = run_page(P6)
    d7 = metric(at, "D7 difference")
    assert norm(d7.value) == pp(g7["abs_lift"])
    assert ci_from_note(d7) == (r2(g7["abs_ci_low"]), r2(g7["abs_ci_high"]))
    d1 = metric(at, "D1 difference")
    assert norm(d1.value) == pp(g1["abs_lift"])
    assert ci_from_note(d1) == (r2(g1["abs_ci_low"]), r2(g1["abs_ci_high"]))
    assert metric(at, "D7 · this check").value == d7.value
    readout = [md.value for md in at.markdown if md.value.startswith("**Readout in one line.**")][0]
    assert f"shows {abs(g7['abs_lift']) * 100:.2f} pp lower D7" in readout and "not certified" in readout
    assert "no sign of a retention benefit" in readout
    text = page_text(at)
    for retired in ("Fewer D7 players", "fewer players still playing"):          # '370' / 'barely': WITHDRAWN guard
        assert retired not in text, retired
    assert not any("Fewer D7" in m.label for m in at.metric)


def test_p6_guardrails_are_read_where_the_gate_can_act():
    band, dec1, rr, rd = (GATE["retention_by_rounds_band"], GATE["d1_decomposition"], GATE["rounds_among_reachers"],
                          GATE["rounds"])
    d1b = band["rounds_ge_30"]["retention_1"]
    at = run_page(P6)
    m = metric(at, "D1 · 30+ rounds")
    assert norm(m.value) == pp(d1b["abs_lift"]) and ci_from_note(m) == (r2(d1b["abs_ci_low"]), r2(d1b["abs_ci_high"]))
    ci1 = dec1["install_level_effect_ci_if_only_reachers"]
    m = metric(at, "D1 · gate could explain")
    assert norm(m.value) == pp(dec1["within_reached_30"]) and ci_from_note(m) == (r2(ci1[0]), r2(ci1[1]))
    assert metric(at, "Median rounds · 30+ rounds").value == f"{rr['median_t']:.0f} vs {rr['median_c']:.0f}"   # 75/72
    sp = rr["share_past_40_rounds"]
    m = metric(at, "Past 40 rounds · 30+ rounds")
    assert norm(m.value) == pp(sp["abs_lift"], 1)                                                 # +1.8 pp
    assert note(m).startswith(f"{sp['rate_t']:.1%} vs {sp['rate_c']:.1%}")                       # 83.2% vs 81.4%
    assert ci_from_note(m) == (round(sp["abs_ci_low"] * 100, 1), round(sp["abs_ci_high"] * 100, 1))
    text = norm(page_text(at))
    assert f"player mix {pp(dec1['composition'])}" in text                                        # −0.42 pp
    assert f"mean difference ({rd['mean_diff']:+.2f} rounds" in text and "not a clean guardrail" in text
    assert "could have reached level 30" in text and "no sign of a retention benefit" in text
    labels = [m.label for m in at.metric]
    assert not any(lb.startswith(("D1 drop", "Mean rounds diff", "Worst")) for lb in labels), labels


def test_p6_retest_sizing_is_fixed_in_advance():
    rt, g7, g1 = GATE["retest_sizing"], GATE["retention_7"], GATE["retention_1"]
    assert rt["smallest_d7_change_per_install"] == RESULTS["config"]["gate_smallest_d7_change"]
    at = run_page(P6)
    assert metric(at, "Smallest D7 change").value == f"{rt['smallest_d7_change_per_install'] * 100:.1f} pp"
    m = metric(at, "Installs needed · 30+")
    assert m.value == f"≈{rt['installs_needed_reacher_analysis_5050'] / 1e3:,.0f}K"                # ≈114K
    assert f"≈{rt['reachers_needed_5050'] / 1e3:,.0f}K" in note(m)                                 # ≈42K
    assert metric(at, "Installs needed · all").value == f"≈{rt['installs_needed_install_level_5050'] / 1e3:,.0f}K"
    m = metric(at, "MDE as run")
    assert m.value == f"D7 {g7['mde']['mde_abs'] * 100:.2f} pp" and f"D1 {g1['mde']['mde_abs'] * 100:.2f} pp" in note(m)
    tk = [t for t in takeaways(at) if t.startswith("Sized at a change fixed in advance")][0]
    assert "never at the observed effect" in tk and "daily 50/50 group-size check" in tk


def test_p6_decision_is_canonical_r5():
    sbs, rt, rr = GATE["srm_by_stratum"], GATE["retest_sizing"], GATE["rounds_among_reachers"]
    dec = GATE["d7_decomposition"]
    extra = round(GATE["best_case_for_gate_40"]["excess_players_gate_40"], -1)
    at = run_page(P6)
    box = [md.value for md in at.markdown if md.value.startswith("**Keep the first gate at level 30")][0]
    for phrase in ("don't ship gate_40", "not certified", "no sign of a retention benefit",
                   f"≈{extra:,} extra installs, a net {sbs['rounds_lt_15']['net_excess_t']:,} of them with "
                   "< 15 rounds",
                   f"≈{rt['installs_needed_reacher_analysis_5050'] / 1e3:,.0f}K installs at 50/50",
                   f"≈{rt['reachers_needed_5050'] / 1e3:,.0f}K of them",
                   f"≈{rt['installs_needed_install_level_5050'] / 1e3:,.0f}K if analysed over all installs",
                   f"≈{abs(dec['within_reached_30']) * 1e4:.0f} fewer Day-7 players per 10,000 installs",
                   f"median {rr['median_t']:.0f} vs {rr['median_c']:.0f} rounds", "a clean re-test",
                   "daily 50/50 group-size check", "would overstate the effect"):
        assert phrase in box, phrase


def test_p6_no_causal_wording_and_no_withdrawn_labels():
    at = run_page(P6)
    hits = [t[:160] for t in all_text(at) if t and P6_CAUSAL.search(t)]
    assert not hits, hits
    assert_no_withdrawn(at, "p6 default")
    assert "worst_case_bound" not in (VIEWS / P6).read_text()


def test_p6_exclude_zero_round_players_changes_d7():
    at = run_page(P6)
    before = metric(at, "D7 · this check")
    at.toggle(key="p6_excl0").set_value(True)
    rerun(at)
    after = metric(at, "D7 · this check")
    assert (after.value, note(after)) != (before.value, note(before))
    n_zero = RESULTS["data_quality"]["cookie"]["zero_round_players"]
    assert note(metric(at, "Players in this check")) == f"{n_zero:,} excluded"
    assert_no_withdrawn(at, "p6 without 0-round players")


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
    assert norm(metric(at, "D7 change vs headline").value) != "+0.00 pp"
    forest = chart(at, "Retention difference, gate_40 − gate_30: headline vs this check (pp)")
    for tr in forest["data"]:                       # gate labels, unadjusted p, never 0.0000, no NaN contrast line
        ht = tr["hovertemplate"]
        assert "gate_40" in ht and "adjusted" not in ht and "vs other segments" not in ht and ":.4f}" not in ht


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
    assert "gate_40 shows lower D1" in sens and "D1 is inconclusive" not in sens
    assert "not evidence of a D1 effect" in sens
    assert "not significant" not in page_text(at)
    assert_no_withdrawn(at, "p6 cap 100")


# ------------------------------------------------------------------ withdrawn wording in the page sources
def test_page_sources_have_no_withdrawn_wording():
    """Covers text in branches the default runs do not render (other SRM states, other control values)."""
    for page in (P4, P5, P6):
        lines = (VIEWS / page).read_text().splitlines()
        hits = withdrawn_hits(lines)
        assert not hits, (page, hits)


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
