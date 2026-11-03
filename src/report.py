"""Standalone HTML report and one-page executive summary.

    build_report() -> Path        (run.py step "report"; returns the path of report.html)

writes
    reports/report.html             the complete analysis for a reader who will not run code: one
                                    self-contained file (plotly.js inlined once), opens with a
                                    double-click, needs no server
    reports/executive_summary.md    a one-page memo for a non-technical PM

How the numbers stay honest
- Every number in the text is formatted from reports/results.json at build time, or computed from the
  parquet caches with the project's own functions (src.stats, src.figures). Nothing is typed by hand.
- Every chart is a figure from src.catalog.build_catalog(), i.e. the dashboard's default view. In the
  report the chart's title and takeaway are rendered as HTML around the plot (title above, takeaway
  below) instead of inside it, so they wrap on a phone and the takeaway is not printed twice.
- p-values are never printed as 0 (very small ones read "p < 0.0001"), and power is only evaluated at
  the smallest lift worth acting on, never at the observed effect. An MDE is never compared with an estimate.
- Gate experiment wording: the naive gap is reported, not certified; the part of the gap the gate could explain is
  not an estimate of its effect; subsets by rounds played were chosen after the SRM warning, so their p-values are
  descriptive and never carry a PASS / WARNING / FAIL label.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

from . import config as C
from . import figures as F
from . import stats as S
from .analysis import load_results
from .catalog import Fig, build_catalog, hour_ranges, load_caches

REPORT_HTML = C.REPORTS_DIR / "report.html"
SUMMARY_MD = C.REPORTS_DIR / "executive_summary.md"
NOTEBOOK_DIR = C.REPORTS_DIR / "notebooks"
DOCS_DIR = C.ROOT / "docs"

# Same modebar as the dashboard (dashboard/common.show) + responsive resizing.
PLOTLY_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"], "responsive": True}
CHART_TOP_MARGIN = 36   # px kept above each plot for annotations once the title moves out of the SVG

# Notebook exports (reports/notebooks/<stem>.html). Used when the exports don't exist yet.
NOTEBOOKS = {
    "01_eda": "Exploratory data analysis and data-quality checks",
    "02_retention": "Retention analysis (Cookie Cats)",
    "03_ab_test": "Experiment readouts: ad vs PSA and gate_30 vs gate_40",
}
DOCS = {
    "01_request_and_scope.md": "Request and scope",
    "02_metric_definitions.md": "Metric definitions",
    "03_data_quality_checks.md": "Data-quality checks",
    "assumptions.md": "Assumptions log",
    "readout.md": "Experiment readout (memo)",
}

LOW_ROUNDS = ("0", "1-4", "5-14")                 # "fewer than 15 rounds" (same buckets as the catalog)
LOW_EXPOSURE_MAX = 20                             # results.json: concentration.share_users_le_20_ads
HEAVY_EXPOSURE = ("36-50", "51-100", "101-200")   # results.json: concentration.*_36_200
TOP_EXPOSURE = C.EXPOSURE_LABELS[-1]              # "200+"
GATE_LEVEL = 30                                   # first gate in the control version (gate_30)
NIGHT = C.DAYPART_ORDER[0]                        # "Night (0-5)"

MINUS, NDASH = "−", "–"
NIGHT_HOURS = NIGHT[NIGHT.index("(") + 1:NIGHT.index(")")].replace("-", NDASH)   # "0–5"
esc = html.escape


# ====================================================================== number formatting
def _dec(v) -> Decimal:
    """Exact decimal reading of a number. results.json stores 8 decimals, so 0.00195 must print as
    0.20 pp, not 0.19 (its binary float times 100 is 0.19499999...)."""
    return v if isinstance(v, Decimal) else Decimal(repr(float(v)))


def _q(v, nd: int) -> Decimal:
    """Round half-up to nd decimals."""
    return _dec(v).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)


def _x100(x) -> Decimal:
    return _dec(x) * 100


def _plain(v, nd: int) -> str:
    """Fixed decimals, Unicode minus for negatives, no plus sign."""
    d = _q(v, nd)
    s = f"{abs(d):,.{nd}f}"
    return MINUS + s if d < 0 else s


def _signed(v, nd: int) -> str:
    d = _q(v, nd)
    s = f"{abs(d):,.{nd}f}"
    return ("+" + s) if d > 0 else (MINUS + s) if d < 0 else s


def _bound(v, nd: int) -> str:
    """Rate bound: add a decimal when a non-zero bound would otherwise print as 0.00."""
    v = _dec(v)
    while nd < 3 and v != 0 and _q(v, nd) == 0:
        nd += 1
    return _plain(v, nd)


def pct(x: float, nd: int = 1) -> str:
    return f"{_plain(_x100(x), nd)}%"


def spct(x: float, nd: int = 0) -> str:
    return f"{_signed(_x100(x), nd)}%"


def pp(x: float, nd: int = 2, sign: bool = False) -> str:
    return f"{(_signed if sign else _plain)(_x100(x), nd)} pp"


def _ci_bound(x_pp: Decimal, nd: int, plus: bool) -> str:
    if x_pp != 0 and _q(x_pp, nd) == 0:             # e.g. -0.0014 pp: say so instead of printing 0.00
        return "just below 0" if x_pp < 0 else "just above 0"
    return (_signed if plus else _plain)(x_pp, nd)


def ci_pp(lo: float, hi: float, nd: int = 2, sign: bool = False) -> str:
    """'0.59 to 0.94 pp'. The upper bound gets a '+' when the interval spans 0 ('-0.71 to +0.07 pp');
    sign=True signs both bounds (for differences and contrasts)."""
    return f"{_ci_bound(_x100(lo), nd, sign)} to {_ci_bound(_x100(hi), nd, sign or lo < 0 < hi)} pp"


def ci_pct(lo: float, hi: float, nd: int = 0) -> str:
    return f"{spct(lo, nd)} to {spct(hi, nd)}"


def num(x: float, nd: int = 0) -> str:
    return _plain(x, nd)


def kn(n: float) -> str:
    """Sample sizes in prose: 181,074 -> '181K', 1,178,866 -> '1.18M' (tables keep the exact count)."""
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1000:,.0f}K"


def approx(x: float, step: int) -> str:
    """Round to a friendly step for the non-technical memo (4,343 -> 4,300)."""
    return f"{round(x / step) * step:,.0f}"


def per10k(x: float) -> str:
    """A per-install difference as players per 10,000 installs (-0.0032 -> '32'; the caller says fewer / more)."""
    return f"{abs(x) * 10000:,.0f}"


def times(x: float) -> str:
    """Multiplier: 3.32 -> '3.3&times;'."""
    return f"{x:.1f}&times;"


def usd(x: float, nd: int = 2) -> str:
    # Spelled out everywhere: GitHub renders text between two dollar signs in Markdown as math, and the charts
    # use USD too.
    return f"USD {x:,.{nd}f}"


def usd_k(x: float, nd: int = 0) -> str:
    return f"USD {x / 1000:,.{nd}f}K"


def millions(x: float, nd: int = 1) -> str:
    return f"{x / 1e6:.{nd}f}M"


def power_pct(x: float) -> str:
    return "≈100%" if x >= 0.995 else f"{_plain(_x100(x), 0)}%"


def pval(p: float, prefix: bool = True) -> str:
    """Never prints 0: below 0.0001 the value reads 'p < 0.0001'."""
    if p < 0.0001:
        return "p &lt; 0.0001" if prefix else "&lt; 0.0001"
    if p < 0.001:
        s = f"{p:.4f}"
    elif p < 0.01:
        s = f"{p:.4f}".rstrip("0")
    elif p < 0.1:
        s = f"{p:.3f}"
    elif p <= 0.99:
        s = f"{p:.2f}"
    elif p < 1:
        s = f"{p:.4f}"
    else:
        s = "1.00"
    return f"p = {s}" if prefix else s


def pval_sci(p: float) -> str:
    """Technical text: 'p = 1.7 × 10^-13' instead of 'p < 0.0001'."""
    if p >= 0.0001:
        return pval(p)
    mant, exp = f"{p:.1e}".split("e")
    return f"p = {mant} &times; 10<sup>{MINUS}{abs(int(exp))}</sup>"


def evidence(p: float) -> str:
    return "strong evidence" if p < 0.001 else "modest evidence" if p < 0.05 else "no evidence"


def _split(share_t: float) -> str:
    return f"{share_t * 100:.0f}/{(1 - share_t) * 100:.0f}"


def _range_label(lab: str) -> str:
    return lab.replace("-", NDASH)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


# ====================================================================== HTML helpers
def _table(head: list[str], rows: list[list[str]], num_cols=(), stack: bool = False, cls: str = "") -> str:
    """Cells are trusted HTML. `stack` turns rows into labelled cards on narrow screens."""
    def cell(tag: str, i: int, content: str) -> str:
        attrs = ' class="n"' if i in num_cols else ""
        if stack and tag == "td":
            attrs += f' data-label="{esc(_strip_tags(head[i]))}"'
        return f"<{tag}{attrs}>{content}</{tag}>"

    thead = "<tr>" + "".join(cell("th", i, h) for i, h in enumerate(head)) + "</tr>"
    body = "".join("<tr>" + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    classes = " ".join(x for x in ("tbl", "stack" if stack else "", cls) if x)
    return f'<div class="tbl-wrap"><table class="{classes}"><thead>{thead}</thead><tbody>{body}</tbody></table></div>'


def _ul(items: list[str], cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<ul{c}>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _callout(kind: str, title: str, body: str) -> str:
    return f'<div class="callout {kind}"><div class="callout-title">{title}</div><div>{body}</div></div>'


def _chip(kind: str, text: str) -> str:
    return f'<span class="chip {kind}">{text}</span>'


def _status_chip(status: str, suffix: str = "") -> str:
    kind = {"PASS": "good", "WARNING": "warn", "FAIL": "stop"}.get(status, "muted")
    return _chip(kind, f"{esc(status)}{suffix}")


def _chart_title(fig: go.Figure) -> str:
    text = fig.layout.title.text or ""
    m = re.search(r"<b>(.*?)</b>", text, flags=re.S)
    return html.unescape(_strip_tags(m.group(1) if m else text)).strip()


# ====================================================================== the report
class _Report:
    def __init__(self, res: dict, caches: dict[str, pd.DataFrame], cat: dict[str, Fig]):
        self.res, self.cat = res, cat
        self.placed: list[str] = []
        cfg = res["config"]
        self.alpha, self.power, self.n_boot = cfg["alpha"], cfg["power"], cfg["n_bootstrap"]
        self.value = cfg["value_per_conversion_usd"]
        self.srm_fail, self.srm_warn = cfg["srm_fail_p"], cfg["srm_warn_p"]
        self.conf = f"{(1 - self.alpha) * 100:.0f}%"
        self.today = dt.date.today().isoformat()
        self.dq = res["data_quality"]
        self.ad, self.ck = res["ad"], res["cookie"]
        self.t, self.gate = self.ad["test"], self.ck["gate"]
        self.g1, self.g7 = self.gate["retention_1"], self.gate["retention_7"]
        self.pw, self.bz, self.het = self.ad["power"], self.ad["business"], self.ad["heterogeneity"]
        self.dec, self.dec1 = self.gate["d7_decomposition"], self.gate["d1_decomposition"]
        self.bc = self.gate["best_case_for_gate_40"]          # every extra gate_40 install treated as never returning
        self.rt = self.gate["retest_sizing"]                   # sized at a change fixed in advance (config.yaml)
        self.rr = self.gate["rounds_among_reachers"]           # engagement guardrail where the gate can act
        self.band = self.gate["retention_by_rounds_band"]
        self.sbs = self.gate["srm_by_stratum"]
        self.early = self.ck["early_churn_segment"]
        self.excess_raw = self.gate["excess_players_raw"]           # 789: raw assignment log
        self.excess_clean = self.bc["excess_players_gate_40"]       # 790: after the one-outlier drop
        self.lt = self.bz["last_touch_overstatement_ci"]
        self._derive(caches)

    # ------------------------------------------------------------------ derived numbers
    def _derive(self, caches: dict[str, pd.DataFrame]) -> None:
        t, a = self.t, self.alpha
        self.arms = F.arm_table(t["conv_t"], t["n_t"], t["conv_c"], t["n_c"], alpha=a).set_index("arm")
        self.n_total = t["n_t"] + t["n_c"]
        self.split = _split(self.ad["srm"]["intended_share_t"])

        # segment tables (same calls as the catalog), indexed by the segment label as a string
        cells = caches["cells"]
        orders = {"most_ads_day": C.DAY_ORDER, "most_ads_hour": list(range(24)),
                  "daypart": C.DAYPART_ORDER, "exposure_bucket": C.EXPOSURE_LABELS}
        self.seg = {d: S.segment_lifts(cells, d, "ad", "psa", alpha=a, method="holm", order=o)
                    for d, o in orders.items()}
        self.segi = {d: tab.assign(**{d: tab[d].astype(str)}).set_index(d) for d, tab in self.seg.items()}
        self.expo = self.segi["exposure_bucket"]
        self.con = self.het["exposure_bucket"]["concentration"]
        self.heavy_range = f"{HEAVY_EXPOSURE[0].split('-')[0]}{NDASH}{HEAVY_EXPOSURE[-1].split('-')[1]}"

        # retention
        rb = pd.DataFrame(self.ck["by_rounds_bucket"]).set_index("rounds_bucket")
        self.rb = rb
        low = rb.loc[list(LOW_ROUNDS)]
        # the early-churn segment in results.json must be exactly the < 15-round buckets of the Section 3 table
        if int(low["players"].sum()) != int(self.early["players"]):
            raise ValueError("cookie.early_churn_segment does not match the < 15-round buckets in by_rounds_bucket")
        self.low_cut = C.ROUNDS_BINS[C.ROUNDS_LABELS.index(LOW_ROUNDS[-1]) + 1] + 1
        d1 = pd.DataFrame(self.ck["by_d1_status"]).set_index("d1_status")
        self.d7_yes = float(d1.loc["Returned Day 1", "retention_7"])
        self.d7_no = float(d1.loc["Did not return Day 1", "retention_7"])
        self.funnel = pd.DataFrame(self.ck["funnel"]).set_index("step")
        self.gaps = pd.DataFrame(self.ck["gap_by_dimension"])
        players = caches["players"]
        rounds = players["sum_gamerounds"]
        self.median_rounds = float(rounds.median())
        self.share_reach = float((rounds >= GATE_LEVEL).mean())
        zero = players[rounds == 0]
        self.zero_d1, self.zero_d7 = int(zero["retention_1"].sum()), int(zero["retention_7"].sum())
        self.zero_flag_share = self.zero_d1 / len(players)
        # D7 without D1 on the analysed players (results.json data_quality counts the raw file, outlier included)
        self.d7_not_d1 = int((players["retention_7"] & ~players["retention_1"]).sum())
        # ceiling for R6: D7 gained per 1 pp of installs moved from "no Day-1 return" to "returned"
        self.d1_ceiling = self.early["d7_if_returned_day1"] - self.early["d7_if_not_returned_day1"]

        # ad: hours whose PSA arm has zero conversions, and the 10% lift in conversions per ad flight
        hours = self.segi["most_ads_hour"]
        self.zero_hours = [int(h) for h in hours.index[hours["conv_c"] == 0]]
        ses = self.pw["power_at_relative_lift"][str(self.pw["smallest_lift_of_interest_rel"])]
        self.ses = ses
        self.ses_conv = ses["abs"] * self.t["n_t"]

        # gate: share of the naive D7 gap that sits where the gate cannot act (player mix + never met a gate)
        dec = self.dec
        self.not_gate_share = (dec["composition"] + dec["within_never_reached_30"]) / dec["naive_diff"]

    # ------------------------------------------------------------------ small text helpers
    def _contrast(self, dim: str, seg: str) -> str:
        r = self.segi[dim].loc[seg]
        return (f"{pp(r['diff_vs_rest'], sign=True)} ({self.conf} CI "
                f"{ci_pp(r['diff_vs_rest_ci_low'], r['diff_vs_rest_ci_high'], sign=True)}; Holm "
                f"{pval(r['p_vs_rest_adj'])})")

    def _seg_name(self, dim: str, seg: str) -> str:
        if dim == "most_ads_hour":
            return f"hour {seg}"
        if dim == "exposure_bucket":
            return f"{_range_label(seg)} ads"
        if dim == "most_ads_day":
            return f"{seg}-peak users"
        return seg.replace("-", NDASH)

    # ------------------------------------------------------------------ charts
    def fig(self, key: str, how: str | None = None) -> str:
        if key not in self.cat:
            raise KeyError(f"report.py expects catalog figure '{key}' (see src/catalog.py)")
        item = self.cat[key]
        self.placed.append(key)
        fig = go.Figure(item.fig)
        title = _chart_title(fig)
        top_old = fig.layout.margin.t if fig.layout.margin.t is not None else 80
        height = (fig.layout.height or 420) - max(0, top_old - CHART_TOP_MARGIN)
        fig.update_layout(title_text="", margin_t=CHART_TOP_MARGIN, height=max(260, height), autosize=True)
        config = {**PLOTLY_CONFIG, "toImageButtonOptions": {"format": "png", "filename": key, "scale": 2}}
        div = pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=f"fig-{key}", config=config,
                          default_width="100%")
        how_html = f'<p class="how"><b>How to read:</b> {how}</p>' if how else ""
        return (f'<figure class="chart" id="chart-{key}"><div class="chart-title">{esc(title)}</div>'
                f'<div class="plot">{div}</div>'
                f'<figcaption><p class="takeaway">{esc(item.takeaway)}</p>{how_html}</figcaption></figure>')

    # ------------------------------------------------------------------ header
    def header(self) -> str:
        t, bz, o, c = self.t, self.bz, self.ck["overall"], self.conf
        inc, be = bz["incremental_conversions"], bz["breakeven_cpm_usd"]
        hold, dec = bz["always_on_holdout_cost"], self.dec
        eff, eff_ci = dec["install_level_effect_if_only_reachers"], dec["install_level_effect_ci_if_only_reachers"]
        bottom = (
            f"The ad campaign drove conversions. In a randomized test with {num(self.n_total)} users, people shown "
            f"the campaign's ads converted at {pct(t['rate_t'], 2)} versus {pct(t['rate_c'], 2)} for a control group "
            f"shown a public-service announcement (PSA) in the same ad slots: {pp(t['abs_lift'], sign=True)} "
            f"({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), or about {approx(inc['point'], 100)} incremental "
            f"conversions ({c} CI {approx(inc['ci_low'], 100)}{NDASH}{approx(inc['ci_high'], 100)}). That is only "
            f"{pct(bz['share_of_ad_conversions_incremental'], 0)} of the ad group's conversions, so last-touch "
            f"attribution would overstate the campaign {times(bz['last_touch_overstatement_x'])} ({c} CI "
            f"{self.lt[0]:.1f}{NDASH}{times(self.lt[1])}). <strong>Keep it running at the current budget, with a "
            f"{pct(hold['share'], 0)} always-on holdout to keep measuring it.</strong> This test cannot say whether "
            f"doubling the budget pays: budget was never varied, and the lift sits in heavy, very active users, so "
            f"<strong>test more impressions per user (or a frequency cap) before committing &asymp;2&times; "
            f"spend.</strong> Most new players of the company's mobile game are lost before Day 1 "
            f"({pct(1 - o['retention_1'])} never return), and only {pct(self.early['retention_7'])} of the "
            f"{pct(self.early['share_of_installs'], 0)} of installs who play fewer than {self.low_cut} rounds are back "
            f"on Day 7, so <strong>retention work should start with the first session and Day 1.</strong> Finally, "
            f"<strong>keep the first gate at level {GATE_LEVEL}</strong>: gate_40 shows a D7 rate "
            f"{pp(abs(dec['naive_diff']))} lower, but that naive gap is not certified because the arms are unbalanced. "
            f"The part of it the gate could explain is about {pp(eff, sign=True)} per install ({c} CI "
            f"{ci_pp(*eff_ci)}), not an estimate of the gate's effect and possibly zero; there is no sign of a "
            f"retention benefit."
        )
        kpis = [
            ("Ad lift (absolute)", pp(t["abs_lift"], sign=True), f"{c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}"),
            ("Relative lift", spct(t["rel_lift"]), f"{c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'])}"),
            ("Incremental conversions", f"&asymp;{num(inc['point'])}",
             f"{c} CI {num(inc['ci_low'])}{NDASH}{num(inc['ci_high'])} &middot; "
             f"{pct(bz['share_of_ad_conversions_incremental'], 0)} of ad-arm conversions"),
            ("Breakeven CPM", usd(be["point"]), f"at an <b>assumed</b> {usd(self.value, 0)} per conversion"),
            ("D7 retention, new players", pct(o["retention_7"]),
             f"D1 {pct(o['retention_1'])} &middot; {num(o['players'])} players"),
            ("D7 gap the gate could explain", pp(eff, sign=True),
             f"per install; {c} CI {ci_pp(*eff_ci)}; not an estimate of the gate's effect &middot; naive "
             f"{pp(dec['naive_diff'], sign=True)}, not certified"),
        ]
        tiles = "".join(f'<div class="kpi"><div class="kpi-label">{lab}</div><div class="kpi-value">{val}</div>'
                        f'<div class="kpi-sub">{sub}</div></div>' for lab, val, sub in kpis)
        return f"""
<header class="masthead" id="top">
  <div class="eyebrow">Growth &middot; Product Analytics &middot; Experiment readout</div>
  <h1>Ad campaign and new-player retention</h1>
  <p class="meta">Prepared by the Product Analyst, Growth, for the Growth PM &middot; Generated {self.today} from
  <code>reports/results.json</code> &middot; Data: the ad experiment in the company's app and an install cohort of
  its mobile game, both public datasets used as the company's data in this role-play
  (<a href="#s1-data">Section 1</a>)</p>
  <section class="bottom-line" id="summary" aria-label="Summary"><p><strong>Bottom line.</strong> {bottom}</p></section>
  <div class="kpis">{tiles}</div>
  <p class="conventions">Conventions: rates in %; differences in percentage points (pp); intervals are {c}
  confidence intervals (CI); p-values below 0.0001 are shown as &ldquo;p &lt; 0.0001&rdquo;; &ldquo;treatment&rdquo;
  = ad / gate_40, &ldquo;control&rdquo; = PSA / gate_30; money in USD at an illustrative value per conversion.
  Methods are explained in plain English in the <a href="#appendix">appendix</a>.</p>
</header>"""

    # ------------------------------------------------------------------ answers for the PM
    def answers(self) -> str:
        t, bz, c = self.t, self.bz, self.conf
        inc, be, g = bz["incremental_conversions"], bz["breakeven_cpm_usd"], self.ad["groups"]
        o, g7, srm, dec = self.ck["overall"], self.g7, self.gate["srm"], self.dec
        sh_ci = bz["share_of_ad_conversions_incremental_ci"]
        con = self.con
        le20 = con["le_20_ads_pooled"]
        eff_ci = dec["install_level_effect_ci_if_only_reachers"]
        early = self.early
        cards = [
            ("Q1 &middot; Did last quarter's ad campaign drive conversions?",
             _chip("good", "Yes &middot; keep it running (R1)"),
             f"Ad {pct(t['rate_t'], 2)} vs PSA {pct(t['rate_c'], 2)} conversion: <b>{pp(t['abs_lift'], sign=True)}</b> "
             f"({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), <b>{spct(t['rel_lift'])}</b> relative "
             f"({c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'])}). That is &asymp;{num(inc['point'])} incremental "
             f"conversions ({c} CI {num(inc['ci_low'])}{NDASH}{num(inc['ci_high'])}), only "
             f"{pct(bz['share_of_ad_conversions_incremental'], 0)} ({c} CI {pct(sh_ci[0], 0)}{NDASH}"
             f"{pct(sh_ci[1], 0)}) of the ad arm's {num(t['conv_t'])} conversions: last-touch (any-touch) attribution "
             f"would overstate the campaign {times(bz['last_touch_overstatement_x'])} ({c} CI {self.lt[0]:.1f}"
             f"{NDASH}{times(self.lt[1])}). Integrity: both arms saw the same ad volume on average "
             f"({num(g['ad']['mean_ads'], 1)} vs {num(g['psa']['mean_ads'], 1)} per user); the split lands "
             f"{num(self.ad['srm']['deviation_users'], 2)} users from exactly {self.split}, most likely a fixed quota, "
             f"so the sample-ratio test is uninformative rather than a pass.",
             "#s4", "Section 4"),
            ("Q2 &middot; Is it worth doubling the budget?", _chip("warn", "Not answerable yet &middot; test first (R2)"),
             f"The test ran at one budget level: it measures the average effect of today's spend, not what extra "
             f"spend buys. At an <b>assumed</b> {usd(self.value, 0)} per conversion (there is no revenue in the data) "
             f"the current flight pays back if CPM is below <b>{usd(be['point'])}</b> ({c} CI "
             f"{usd(be['ci_low'])}{NDASH}{be['ci_high']:.2f}). Exploratory: the "
             f"{pct(con['share_users_le_20_ads'], 0)} of users who saw &le; {LOW_EXPOSURE_MAX} ads show no lift we could "
             f"measure ({pp(le20['abs_lift'], sign=True)}, {c} CI "
             f"{ci_pp(le20['abs_ci_low'], le20['abs_ci_high'], sign=True)}); the "
             f"{pct(con['share_ad_users_36_200'], 0)} of ad users who saw {self.heavy_range} ads hold "
             f"{pct(con['share_incremental_conversions_36_200'], 0)} of the bucket-by-bucket incremental conversions. "
             f"Exposure tracks how active a user is, so the lift lives in heavy users; this is not a frequency curve.",
             "#s5-exposure", "Sections 4.6 and 5.5"),
            ("Q3 &middot; Which new users leave first?", _chip("info", "The least engaged, before Day 1 &middot; R6"),
             f"In the company's mobile game, {pct(1 - o['retention_1'])} of new players do not return on Day 1 and "
             f"{pct(o['retention_7'])} play on Day 7. Players with fewer than {self.low_cut} rounds in their first 14 "
             f"days are <b>{pct(early['share_of_installs'], 0)} of installs</b> and only "
             f"<b>{pct(early['retention_7'])}</b> of them are back on Day 7. Day-1 returners are "
             f"<b>{self.d7_yes / self.d7_no:.1f}&times;</b> as likely to play on Day 7 ({pct(self.d7_yes)} vs "
             f"{pct(self.d7_no)}): the earliest strong signal of who stays, not proof that a Day-1 nudge works. Rounds "
             f"are counted through day 14, which overlaps Day 7, so the rounds pattern sizes the early-churn segment; "
             f"it is not a Day-0 targeting rule.", "#s3", "Section 3"),
            (f"Gate &middot; Should the first gate move from level {GATE_LEVEL} to 40?",
             _chip("stop", f"No &middot; keep gate {GATE_LEVEL} (R5)"),
             f"Naive comparison (not certified): gate_40 D7 {pct(g7['rate_t'], 2)} vs {pct(g7['rate_c'], 2)}, "
             f"{pp(g7['abs_lift'], sign=True)} ({c} CI {ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])}). The arms are "
             f"unbalanced ({num(srm['n_t'])} vs {num(srm['n_c'])} assigned, {pval(srm['p_value'])}, "
             f"{esc(srm['status'])}): gate_40 has &asymp;{num(self.excess_clean)} extra installs, with a net excess of "
             f"{num(self.sbs['rounds_lt_15']['net_excess_t'])} among players with fewer than 15 rounds. The part of the "
             f"gap the gate could explain is <b>{pp(dec['within_reached_30'], sign=True)} per install</b> ({c} CI "
             f"{ci_pp(*eff_ci)}): not an estimate of its effect, and possibly zero. There is no sign of a retention "
             f"benefit. Keep gate {GATE_LEVEL}, fix assignment, re-test only if the gate position matters "
             f"commercially.",
             "#s6", "Section 6"),
        ]
        html_cards = "".join(
            f'<article class="answer"><div class="q">{q}</div><div class="verdict">{chip}</div><p>{body}</p>'
            f'<a class="more" href="{href}">Evidence: {label} &rarr;</a></article>'
            for q, chip, body, href, label in cards)
        return (f'<section id="answers"><h2>Answers for the PM</h2>'
                f'<p class="lede">The PM asked three questions; a fourth answer covers the gate experiment that ran '
                f'alongside.</p><div class="answers">{html_cards}</div></section>')

    # ------------------------------------------------------------------ recommendations
    def recommendations(self) -> list[dict]:
        bz, pw, c = self.bz, self.pw, self.conf
        inc, be, hold = bz["incremental_conversions"], bz["breakeven_cpm_usd"], bz["always_on_holdout_cost"]
        hd, hh, hp = self.het["most_ads_day"], self.het["most_ads_hour"], self.het["daypart"]
        con, dec, o = self.con, self.dec, self.ck["overall"]
        n10, ses, rt, early = pw["total_n_for_10pct_rel_lift"], self.ses, self.rt, self.early
        eff_ci = dec["install_level_effect_ci_if_only_reachers"]
        sizing = early["onboarding_test_sizing"]
        return [
            dict(id="R1", owner="Growth PM", chip=_chip("good", "Keep"),
                 what=f"Keep the campaign at the current budget, with an always-on {pct(hold['share'], 0)} PSA "
                      "holdout.",
                 impact=f"&asymp;{approx(inc['point'], 100)} incremental conversions per comparable flight ({c} CI "
                        f"{approx(inc['ci_low'], 100)}{NDASH}{approx(inc['ci_high'], 100)}). The holdout forgoes "
                        f"&asymp;{num(hold['conversions_forgone'])} conversions per {kn(self.n_total)}-user flight "
                        f"(&asymp;{usd_k(hold['value_forgone_usd'], 1)} at {usd(self.value, 0)}) vs. no holdout; this "
                        f"test's {pct(hold['as_run_control_share'], 0)} PSA arm already forgoes "
                        f"&asymp;{num(hold['as_run_control_conversions_forgone'])}. Keeps the real effect measured: "
                        f"last-touch would overstate it {times(bz['last_touch_overstatement_x'])} ({c} CI "
                        f"{self.lt[0]:.1f}{NDASH}{times(self.lt[1])}).",
                 measure="Incremental conversions and cost per incremental conversion vs. the holdout, per flight and "
                         "at least quarterly.",
                 risk=f"Value per conversion and CPM are unknown: Finance confirms actual CPM &lt; {usd(be['point'])} "
                      f"({usd(be['ci_low'])} at the pessimistic end). One flight's holdout read is about as precise as "
                      f"this test; judge trends over several flights."),
            dict(id="R2", owner="Growth PM + media buyer", chip=_chip("warn", "Test first"),
                 what="Don't double blindly; test it. A user-level test where one arm gets up to 2&times; today's "
                      "impressions per user (the closest stand-in for 2&times; budget) or a frequency cap; 50/50 or "
                      "80/20; users tiered by activity measured <i>before</i> the test. A true budget test needs a geo "
                      "split.",
                 impact=f"Learn the marginal return before committing &asymp;2&times; spend. Today's lift sits in the "
                        f"{pct(con['share_ad_users_36_200'], 0)} of ad users who saw {self.heavy_range} ads, so the "
                        f"average return may not hold at 2&times;.",
                 measure="Incremental conversions per extra USD 1K spent (marginal iROAS).",
                 risk=f"The 2&times;-vs-1&times; difference will be smaller than ad-vs-PSA, so expect to need more than "
                      f"the {kn(n10['0.5'])} users (50/50) that a {pct(ses['rel'], 0)} ad-vs-PSA lift needs. Heavy "
                      f"users may tire of more ads (not measurable here)."),
            dict(id="R3", owner="Media buyer", chip=_chip("stop", "Don't (yet)"),
                 what="Don't re-plan spend by day or hour. If timing matters, pre-register a test that randomizes the "
                      "delivery schedule (weekday and time slot, e.g. Tuesday vs. Thursday delivery).",
                 impact=f"Avoids moving money on a pattern that describes users' habits, not slots we buy (peak day: "
                        f"interaction {pval(hd['lrt']['p_value'])}, "
                        f"{pval(hd['lrt_p_bonferroni_3_dims'], prefix=False)} allowing for "
                        f"{self.het['n_dimensions_explored']} dimensions; hour {pval(hh['lrt']['p_value'])}; daypart "
                        f"without night {pval(hp['lrt_excluding_night']['p_value'])}).",
                 measure=f"Difference in lift between randomized delivery slots, with its {c} CI.",
                 risk="Missing a small real timing effect."),
            dict(id="R4", owner="Analytics + Eng", chip=_chip("info", "Fix design"),
                 what=f"Fix the next test's design: 50/50 or 80/20 split ({self.split} had "
                      f"{power_pct(ses['power_current_split'])} power for a {pct(ses['rel'], 0)} lift); log assignment "
                      "timestamps; pre-register the primary metric, the smallest lift worth acting on, and guardrails "
                      "(unsubscribe / complaint rate, cost per acquisition); automatic daily SRM check.",
                 impact=f"The same users at 50/50 have {power_pct(ses['power_5050_same_total'])} power for a "
                        f"{pct(ses['rel'], 0)} lift and an MDE of {pp(pw['mde_if_5050_same_total']['mde_abs'])} instead "
                        f"of {pp(pw['mde_current']['mde_abs'])}; timestamps show whether the effect fades.",
                 measure="Power / MDE reviewed at design time; daily SRM check.",
                 risk="A bigger control group means more users miss the ads during the test; logging work for Eng."),
            dict(id="R5", owner="Game PM (Eng + Analytics fix assignment)", chip=_chip("stop", "Don't ship"),
                 what=f"Keep the first gate at level {GATE_LEVEL} (no change). Fix assignment / logging first "
                      f"(gate_40 received &asymp;{num(self.excess_clean)} extra installs, with a net excess of "
                      f"{num(self.sbs['rounds_lt_15']['net_excess_t'])} among players with &lt; 15 rounds). Re-test "
                      "only if the gate position matters commercially.",
                 impact=f"Avoids a change with no sign of a retention benefit. The part of the D7 gap the gate could "
                        f"explain is &asymp;{pp(dec['within_reached_30'], 1, sign=True)} per install ({c} CI "
                        f"{ci_pp(*eff_ci)}; &asymp;{per10k(dec['within_reached_30'])} fewer Day-7 players per 10,000 "
                        f"installs), and even that may not be the gate. gate_40 does let players who reach level "
                        f"{GATE_LEVEL} play a little more (median {num(self.rr['median_t'])} vs. "
                        f"{num(self.rr['median_c'])} rounds).",
                 measure=f"Any re-test: pre-register a {pp(rt['smallest_d7_change_per_install'], 1)} D7 change per "
                         f"install as the smallest change worth acting on (agree with the Game PM); "
                         f"&asymp;{kn(rt['installs_needed_reacher_analysis_5050'])} installs at 50/50 with the primary "
                         f"analysis among players who reach level {GATE_LEVEL} "
                         f"(&asymp;{kn(rt['reachers_needed_5050'])} of them), "
                         f"&asymp;{kn(rt['installs_needed_install_level_5050'])} if analysed over all installs; daily "
                         f"50/50 group-size check.",
                 risk=f"Quoting the raw {pp(dec['naive_diff'], sign=True)} would overstate the effect; missing a small "
                      f"real effect either way."),
            dict(id="R6", owner="Onboarding PM (with CRM)", chip=_chip("info", "Act"),
                 what="Focus retention work on first session &rarr; Day 1: a randomized Day-1 re-engagement test for "
                      "new players who play little on their first day, D7 primary.",
                 impact=f"Targets the biggest drop: {pct(1 - o['retention_1'])} of installs don't return on Day 1; "
                        f"{pct(early['share_of_installs'], 0)} play &lt; {self.low_cut} rounds and only "
                        f"{pct(early['retention_7'])} of them play on Day 7. Ceiling, not a forecast: each 1 pp of "
                        f"installs moved from &ldquo;no Day-1 return&rdquo; to &ldquo;returned&rdquo; is worth at most "
                        f"&asymp;{pp(self.d1_ceiling / 100)} of D7 ({pct(early['d7_if_returned_day1'])} vs. "
                        f"{pct(early['d7_if_not_returned_day1'])}), if they then behaved like today's Day-1 returners.",
                 measure=f"D7 among targeted players (primary), D1 (secondary). Sizing: "
                         f"{pp(sizing['target_lift_abs'], 1, sign=True)} D7 on the {pct(early['retention_7'])} base "
                         f"(placeholder target) needs &asymp;{kn(sizing['players_needed_5050'])} target players "
                         f"(&asymp;{kn(sizing['installs_needed_5050'])} installs) at 50/50.",
                 risk="Rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use "
                      "first-day play; the play&ndash;retention link may not be causal; notification fatigue."),
        ]

    def recs_section(self) -> str:
        rows = [[f'<b>{r["id"]}</b>', f'{r["owner"]}<br>{r["chip"]}', r["what"], r["impact"], r["measure"], r["risk"]]
                for r in self.recommendations()]
        table = _table(["#", "Owner", "What", "Expected impact", "How we'll measure it", "Main risk"], rows,
                       stack=True, cls="recs")
        return (f'<section id="recommendations"><h2>Recommendations</h2>'
                f'<p class="lede">Each recommendation names an owner, the expected impact, how we will know it worked, '
                f'and the main risk. <a href="#s7">Section 7</a> maps them to the decisions.</p>{table}</section>')

    # ------------------------------------------------------------------ 1 scope
    def s1_scope(self) -> str:
        m, ck = self.dq["marketing"], self.dq["cookie"]
        q_rows = [
            ["Q1", "Did the campaign drive conversions?",
             f"In the randomized ad-vs-PSA test, is user-level conversion higher with ads, by how much (pp and %, "
             f"with a {self.conf} CI), and how many incremental conversions is that?", "Keep or stop the campaign",
             "Growth PM"],
            ["Q2", "Is it worth doubling the budget?",
             "At what CPM does the campaign break even under an explicit value-per-conversion assumption? Where does "
             "the lift come from? What can this test <i>not</i> say about 2&times;?",
             "Scale to 2&times;, hold, or test 2&times; first", "Growth PM + budget owner"],
            ["Q3", "(implicit) Where should the money go?",
             "Does the lift differ reliably by peak ad day, hour or daypart (interaction test, then segment-vs-rest "
             "contrasts with multiple-comparison correction), and is the segment something we can buy?",
             "Day-parting / reallocation", "Growth PM + media buyer"],
            ["Q4", "Which new users leave first?",
             "How do D1 / D7 retention differ by engagement depth, Day-1 return and version, and where is the largest "
             "drop?", "Which onboarding segment to target first", "Game / Onboarding PM"],
            ["Q5", f"(second experiment) Move the first gate from level {GATE_LEVEL} to 40?",
             "Does gate_40 change D7 (primary), D1 or engagement (guardrails)? Is the experiment trustworthy (sample "
             "ratio, negative control)?", f"Ship gate_40 or keep gate_{GATE_LEVEL}", "Game PM"],
        ]
        return f"""
<section id="s1">
<h2><span class="sec-num">1</span>Business question and scope</h2>
<p>In the Growth weekly sync the Growth PM asked:</p>
<blockquote>&ldquo;Did last quarter's ad campaign actually drive conversions? If so, is it worth doubling the budget?
Also, we're losing a lot of new users in their first 7 days &mdash; which users leave first?&rdquo;</blockquote>
<p>Each part maps to a decision with an owner:</p>
{_table(["#", "PM's question", "What we analysed", "Decision it informs", "Owner"], q_rows, stack=True)}
<h3>What would change the decision</h3>
{_ul([
    "<b>Q1:</b> a confidence interval that includes 0, or failed integrity checks (assignment, exposure parity): we "
    "could not claim the campaign works.",
    "<b>Q2:</b> a breakeven CPM below what we actually pay means the campaign loses money despite a real lift. "
    "Whether extra spend buys more conversions is a marginal question that only a randomized budget test answers.",
    "<b>Q3:</b> reallocation is justified only if the difference survives a formal interaction test <i>and</i> "
    "corrected segment-vs-rest contrasts, <i>and</i> the segment is something we can buy; otherwise &ldquo;Tuesday "
    "looks best&rdquo; is noise or a property of the users.",
    "<b>Q4:</b> the retention segments only choose where to test; a randomized experiment decides what ships.",
    "<b>Q5:</b> a sample-ratio warning or a gap in the negative control means the readout cannot be certified until "
    "assignment is explained. With the status quo as the default, an uncertified result means &ldquo;don't "
    "ship&rdquo;.",
])}
<h3 id="s1-data">Data</h3>
<p>Public user-level experiment data is rare, so this role-play uses two public Kaggle datasets as the company's
data:</p>
{_ul([
    f"<b>Marketing A/B test (2021)</b>, the ad experiment in the company's app: {num(m['rows_raw'])} users randomized "
    "to see the campaign's ads (<code>ad</code>) or a public-service announcement in the same slots "
    "(<code>psa</code>). Fields: test group, converted, total ads seen, and the day and hour the user saw the most "
    "ads. No dates, no revenue, no retention.",
    f"<b>Cookie Cats (2017)</b>, the company's mobile puzzle game: {num(ck['rows_raw'])} new players randomized to "
    f"the first progression gate at level {GATE_LEVEL} (<code>gate_30</code>) or level 40 (<code>gate_40</code>). "
    "Fields: version, game rounds played in the first 14 days, and whether the player came back on Day 1 and on "
    "Day 7. One install cohort without install dates. Used for the retention analysis and as a second experiment; "
    "its Game PM and Onboarding PM are colleagues of the Growth PM.",
])}
<p>The app and the game are different products with no shared users, so ad conversion and retention cannot be
linked, and the game's segment sizes will not transfer one-for-one to the app.</p>
<h3>Out of scope (not answerable with this data)</h3>
{_ul([
    "<b>Revenue and ROI</b>: there are no revenue or cost fields; money figures use an explicit, adjustable "
    "assumption.",
    "<b>Time trends, novelty effects and comparisons by install date</b>: there are no dates, only the weekday and "
    "hour of peak ad exposure.",
    "<b>Long-term value of converters</b>: the datasets cannot be joined.",
])}
</section>"""

    # ------------------------------------------------------------------ 2 data quality + integrity
    def s2_data(self) -> str:
        m, ck = self.dq["marketing"], self.dq["cookie"]
        out = ck["outliers_dropped"][0] if ck["outliers_dropped"] else None
        srm_ad, gsrm = self.ad["srm"], self.gate["srm"]
        g, ks = self.ad["groups"], self.ad["total_ads_ks"]
        bal = self.ad["balance"]
        v_lo, v_hi = min(b["cramers_v"] for b in bal), max(b["cramers_v"] for b in bal)
        sh = self.het["exposure_bucket"]["arm_shares"]
        nc7 = self.gate["negative_control"]["never_reached_30"]["retention_7"]
        sbs = self.sbs
        b15, b1529 = (self.band[k]["retention_7"] for k in ("rounds_lt_15", "rounds_15_29"))
        bgap = self.gate["d7_band_gap_difference_15_29_vs_lt_15"]     # are the two bands' D7 gaps different?
        ok, lim = _chip("good", "Pass"), _chip("muted", "Limitation")

        glance = _table(
            ["Check", "Result", "Verdict"],
            [["Row reconciliation", f"Marketing {num(m['rows_raw'])} raw = {num(m['rows_clean'])} analysed; Cookie Cats "
              f"{num(ck['rows_raw'])} &rarr; {num(ck['rows_clean'])} (one documented outlier)", ok],
             ["Primary keys unique", f"{num(m['duplicate_user_id'] + ck['duplicate_user_id'])} duplicate IDs", ok],
             ["Missing values", f"{num(sum(m['nulls'].values()) + sum(ck['nulls'].values()))} in all columns", ok],
             ["Value domains", f"Arms, booleans, hours 0&ndash;23 and 7 weekdays as expected; {num(self.zero_d1)} "
              f"zero-round players are flagged as back on Day 1 ({pct(self.zero_flag_share)} of players)",
              _chip("good", "Pass (noted)")],
             [f"Ad test: sample ratio vs {self.split}",
              f"{num(srm_ad['n_t'])} / {num(srm_ad['n_c'])} is the nearest whole number to exactly "
              f"{pct(srm_ad['intended_share_t'], 0)} ({num(srm_ad['deviation_users'], 2)} users off; random assignment "
              f"typically misses by &asymp;{num(srm_ad['sd_users_under_random_assignment'])}): most likely a fixed "
              f"quota, so the SRM test ({pval(srm_ad['p_value'])}) passes by construction",
              _chip("muted", "Uninformative")],
             ["Ad test: exposure parity", f"Mean ads per user {num(g['ad']['mean_ads'], 2)} vs "
              f"{num(g['psa']['mean_ads'], 2)}; distribution shapes differ a little (KS D = {ks['stat']:.3f})",
              _chip("warn", "Means match; shape differs")],
             ["Ad test: day / hour / exposure balance",
              f"Cram&eacute;r's V {v_lo:.3f}&ndash;{v_hi:.3f} (tiny, but these are post-assignment variables)",
              _chip("muted", "Exploratory only")],
             ["Gate test: sample ratio vs 50/50 (raw assignment counts)",
              f"{num(gsrm['n_t'])} vs {num(gsrm['n_c'])}, {pval(gsrm['p_value'])}; a net excess of "
              f"{num(sbs['rounds_lt_15']['net_excess_t'])} gate_40 installs among players with fewer than 15 rounds "
              f"({pval(sbs['rounds_lt_15']['p_value'])}, descriptive: a subset chosen after seeing the warning)",
              _status_chip(gsrm["status"])],
             ["Gate test: negative control", f"Players with fewer than {GATE_LEVEL} rounds (met no gate) still differ "
              f"on D7: {pp(nc7['abs_lift'], sign=True)}, {pval(nc7['p_value'])}, borderline on its own. Such gap as "
              f"there is comes from the 15&ndash;{GATE_LEVEL - 1} band ({pp(b1529['abs_lift'], sign=True)}) rather than "
              f"the &lt; 15 band where the net excess sits ({pp(b15['abs_lift'], sign=True)}), though the two bands' "
              f"gaps are not distinguishable from each other ({pval(bgap['p_value'])})", _chip("warn", "Borderline")],
             ["Time coverage", "No timestamps in either dataset; the game data is one install cohort", lim]],
            stack=True)

        overview = _table(
            ["", "Marketing A/B (ad vs PSA)", "Cookie Cats (gate_30 vs gate_40)"],
            [["One row =", "one user", "one new player"],
             ["Rows: raw &rarr; analysed", f"{num(m['rows_raw'])} &rarr; {num(m['rows_clean'])}",
              f"{num(ck['rows_raw'])} &rarr; {num(ck['rows_clean'])} "
              f"({num(ck['rows_raw'] - ck['rows_clean'])} outlier dropped)"],
             ["Unique IDs / duplicates", f"{num(m['unique_user_id'])} / {num(m['duplicate_user_id'])}",
              f"{num(ck['unique_user_id'])} / {num(ck['duplicate_user_id'])}"],
             ["Missing values (all columns)", num(sum(m["nulls"].values())), num(sum(ck["nulls"].values()))],
             ["Arms found", ", ".join(f"<code>{esc(v)}</code>" for v in m["test_group_values"]),
              ", ".join(f"<code>{esc(v)}</code>" for v in ck["version_values"])],
             ["Outcome", f"<code>converted</code>: {', '.join(esc(v) for v in m['converted_values'])}",
              "<code>retention_1</code>, <code>retention_7</code>: True / False"],
             ["Time coverage", "No dates; only the weekday and hour with the most ads per user",
              "No dates; rounds are summed over each player's first 14 days"]])
        ranges = _table(
            ["Field", "Result", "Handling"],
            [["<code>total ads</code>",
              f"min {num(m['total_ads_min'])} &middot; median {num(m['total_ads_p50'])} &middot; p99 "
              f"{num(m['total_ads_p99'])} &middot; p99.9 {num(m['total_ads_p999'])} &middot; max {num(m['total_ads_max'])}",
              f"Kept. {num(m['users_over_1000_ads'])} users saw more than 1,000 ads; conversion is one yes/no per "
              "user, so heavy users cannot dominate the metric."],
             ["<code>most ads hour</code> / <code>day</code>",
              f"hours {m['most_ads_hour_range'][0]}&ndash;{m['most_ads_hour_range'][1]}; "
              f"{m['most_ads_day_values']} weekdays", "As expected."],
             ["CSV index column", ", ".join(f"<code>{esc(c)}</code>" for c in m["index_column_dropped"]),
              "Dropped (row number, not data)."],
             ["<code>sum_gamerounds</code>",
              f"min {num(ck['rounds_min'])} &middot; median {num(ck['rounds_p50'])} &middot; p99 {num(ck['rounds_p99'])} "
              f"&middot; p99.9 {num(ck['rounds_p999'])} &middot; max {num(ck['rounds_max_raw'])}",
              (f"Dropped 1 player ({esc(out['version'])}) with {num(out['sum_gamerounds'])} rounds "
               f"(&asymp;{out['sum_gamerounds'] / 14:,.0f} per day for 14 days: a logging error). "
               f"Next-highest: {num(ck['rounds_max_clean'])}.") if out else "No outlier dropped."],
             ["Players with 0 rounds",
              f"{num(ck['zero_round_players'])}; {num(self.zero_d1)} of them are flagged as back on Day 1 and "
              f"{num(self.zero_d7)} on Day 7",
              f"Kept: installed but never played, part of the funnel. The retention flags therefore mean &ldquo;came "
              f"back to the game&rdquo;, not &ldquo;played a round&rdquo;; {pct(self.zero_flag_share)} of players, no "
              f"conclusion depends on it."],
             ["Back on Day 7 but not Day 1",
              f"{num(ck['d7_without_d1'])} in the raw file; {num(self.d7_not_d1)} of the {num(ck['rows_clean'])} "
              "analysed players" + (" (the dropped outlier is one of them)"
                                    if out and out["retention_7"] and not out["retention_1"] else ""),
              "Kept: D7 is recorded independently of D1."]])
        rr, rc = ck["retention_raw"], ck["retention_clean"]
        moved = max(abs(rr["d1"] - rc["d1"]), abs(rr["d7"] - rc["d7"])) * 100
        sens = _table(["Metric", "With the outlier", "Without (used)"],
                      [["D1 retention", pct(rr["d1"], 3), pct(rc["d1"], 3)],
                       ["D7 retention", pct(rr["d7"], 3), pct(rc["d7"], 3)],
                       ["Mean rounds per player", num(ck["mean_rounds_raw"], 2), num(ck["mean_rounds_clean"], 2)]],
                      num_cols={1, 2})

        quota = _table(
            ["Quantity", "Value"],
            [["Observed split (ad / PSA)", f"{num(srm_ad['n_t'])} / {num(srm_ad['n_c'])} "
              f"({pct(srm_ad['observed_share_t'], 3)} / {pct(1 - srm_ad['observed_share_t'], 3)})"],
             [f"Expected at exactly {self.split}", f"{num(srm_ad['expected_t'], 2)} / {num(srm_ad['expected_c'], 2)}"],
             ["Deviation from the target", f"{num(srm_ad['deviation_users'], 2)} users"],
             ["Typical deviation under random assignment (1 SD)",
              f"&asymp;{num(srm_ad['sd_users_under_random_assignment'])} users"],
             ["Chance of landing on the nearest whole number by luck", pct(srm_ad["prob_exactly_nearest_integer"], 2)],
             ["SRM chi-square test", f"{pval(srm_ad['p_value'])}: passes by construction"]])
        bal_names = {"most_ads_day": "Peak ad day", "most_ads_hour": "Peak ad hour",
                     "exposure_bucket": "Total ads seen (bucket)"}
        bal_table = _table(["Variable", "Chi-square", "df", "p", "Cram&eacute;r's V"],
                           [[bal_names[b["variable"]], num(b["chi2"], 1), num(b["df"]),
                             pval(b["p_value"], prefix=False), f"{b['cramers_v']:.3f}"] for b in bal],
                           num_cols={1, 2, 3, 4})

        # Subsets by rounds played were chosen after seeing the warning: descriptive p-values, no status label.
        strata = [("rounds_lt_15", "Fewer than 15 rounds"),
                  ("rounds_15_29", f"15&ndash;{GATE_LEVEL - 1} rounds"),
                  ("rounds_lt_30", f"Fewer than {GATE_LEVEL} rounds (the two rows above: never met a gate)"),
                  ("rounds_ge_30", f"{GATE_LEVEL}+ rounds (could have reached level {GATE_LEVEL})")]
        srm_rows = [[label, num(s["n_t"]), num(s["n_c"]), _signed(s["net_excess_t"], 0),
                     pct(s["observed_share_t"], 2), pval(s["p_value"], prefix=False)]
                    for key, label in strata for s in [sbs[key]]]
        srm_rows.append(["<b>All players (the SRM test)</b>", num(gsrm["n_t"]), num(gsrm["n_c"]),
                         _signed(self.excess_raw, 0), pct(gsrm["observed_share_t"], 2),
                         f"{pval(gsrm['p_value'], prefix=False)} {_status_chip(gsrm['status'])}"])
        srm_table = _table(["Players (by rounds played)", "gate_40", "gate_30", "Net excess in gate_40",
                            "gate_40 share", "p vs 50/50"], srm_rows, num_cols={1, 2, 3, 4, 5})
        clean_excess = self.excess_clean
        out_txt = (f"a {esc(out['version'])} player with {num(out['sum_gamerounds'])} rounds" if out
                   else "none in this build")
        return f"""
<section id="s2">
<h2><span class="sec-num">2</span>Data quality and experiment integrity</h2>
<p class="lede">Can we trust the data and the experiment setup? Before any test: reconcile rows, check keys, missing
values, value domains, outliers and time coverage, then check that each experiment's arms are comparable.</p>
<h3>2.1 Checks at a glance</h3>
{glance}
<h3>2.2 Datasets and row reconciliation</h3>
{overview}
<h3>2.3 Value ranges and outliers</h3>
{ranges}
<p>Dropping the outlier moves retention by at most {moved:.4f} pp; only the mean of rounds moves, which is why rounds
are summarised with medians, rank-based tests and a bootstrap.</p>
{sens}
<h3 id="s2-ad">2.4 Ad experiment: most likely a fixed quota, so exposure parity carries the weight</h3>
<p>The ad arm has {num(srm_ad['n_t'])} users and the PSA arm {num(srm_ad['n_c'])}. Against an intended {self.split}
split (not documented; read off the data) the sample-ratio-mismatch (SRM) test gives {pval(srm_ad['p_value'])}, but
that &ldquo;pass&rdquo; carries no information: {num(srm_ad['n_t'])} is the nearest whole number to exactly
{pct(srm_ad['intended_share_t'], 0)} of {num(self.n_total)}, {num(srm_ad['deviation_users'], 2)} users away. Under
independent random assignment the ad arm would typically miss the target by about
&plusmn;{num(srm_ad['sd_users_under_random_assignment'])} users, and landing on the nearest whole number would happen
only {pct(srm_ad['prob_exactly_nearest_integer'], 2)} of the time. Users were therefore most likely allocated to a
fixed quota (or the public file was trimmed to it), and an SRM test cannot detect anything in that situation. Fixed
arm sizes are a valid design if users were randomized within them; nothing in the data contradicts that, but nothing
can confirm it either (R4 asks for the allocation config and assignment logs).</p>
{quota}
<p>The check that carries weight is <b>exposure parity</b>: both arms were served the same ad slots (campaign ads or
PSAs), so their exposure should match. On average it does ({num(g['ad']['mean_ads'], 2)} vs
{num(g['psa']['mean_ads'], 2)} ads per user; median {num(g['ad']['median_ads'])} vs {num(g['psa']['median_ads'])}), but
the shapes differ a little: {pct(sh['1-5']['psa'], 0)} of PSA users vs {pct(sh['1-5']['ad'], 0)} of ad users saw
1&ndash;5 ads, and {pct(sh['11-20']['psa'], 0)} vs {pct(sh['11-20']['ad'], 0)} saw 11&ndash;20 (Kolmogorov&ndash;Smirnov
D = {ks['stat']:.3f}). We cannot tell whether that comes from how PSAs were delivered or from ads changing how long
people browsed. Peak day and peak hour differ slightly by arm too; the chi-square tests are &ldquo;significant&rdquo;
only because n is huge, and the effect sizes are tiny (Cram&eacute;r's V {v_lo:.3f}&ndash;{v_hi:.3f}, where 0 =
identical and 1 = completely different).</p>
{bal_table}
{_callout("warn", "Post-assignment variables",
    "Total ads, peak ad day and peak ad hour were recorded <i>after</i> users were assigned and partly reflect how "
    "users in each arm behaved. They are never used as covariates, and every cut by them "
    "(<a href='#s5'>Section 5</a>) is exploratory. The headline comparison needs only that assignment was random.")}
{self.fig("ad_balance_day", "bars show how each arm's users are spread across their peak ad day. Similar heights "
          "mean the arms look alike on this variable.")}
{self.fig("ad_balance_exposure", "the same comparison for the number of ads a user saw. Matching means hide the small "
          "shift of PSA users toward the lowest bucket.")}
<h3 id="s2-gate">2.5 Gate experiment: a sample-ratio warning; the net excess sits among low-engagement installs</h3>
<p>Assignment happens before any cleaning, so the gate experiment's SRM test uses raw assignment counts:
{num(gsrm['n_t'])} players in gate_40 vs {num(gsrm['n_c'])} in gate_30 ({pct(gsrm['observed_share_t'], 2)} vs an
intended {pct(gsrm['intended_share_t'], 0)}), {pval(gsrm['p_value'])}. The project's rule has two levels: p &lt;
{self.srm_fail:g} is a <b>FAIL</b> (the hard-stop line conventional for large online experiments, e.g. Kohavi et al.)
and p &lt; {self.srm_warn:g} a <b>WARNING</b> (project convention: do not certify, investigate assignment). This test
is a <b>{esc(gsrm['status'])}</b>: below the {self.srm_warn:g} warning line and above the {self.srm_fail:g} hard stop.
gate_40 has &asymp;{num(clean_excess)} extra installs ({num(self.excess_raw)} in the raw log, {num(clean_excess)} after
the one-outlier drop).</p>
<p>To see where the imbalance sits, the raw counts are split by how far players got. Below level {GATE_LEVEL} the two
versions are identical, and a round is one attempt at a level, so rounds &ge; levels (the data has no level field).
Whether a player ever plays {GATE_LEVEL} rounds therefore cannot depend on the gate, and each band should split 50/50
too. The net excess is
{_signed(sbs['rounds_lt_15']['net_excess_t'], 0)} among players with fewer than 15 rounds
({pval(sbs['rounds_lt_15']['p_value'])}), {_signed(sbs['rounds_15_29']['net_excess_t'], 0)} at 15&ndash;{GATE_LEVEL - 1}
rounds ({pval(sbs['rounds_15_29']['p_value'])}) and {_signed(sbs['rounds_ge_30']['net_excess_t'], 0)} at
{GATE_LEVEL}+ rounds ({pval(sbs['rounds_ge_30']['p_value'])}). These bands were chosen after seeing the warning, so
their p-values are descriptive, not a verdict. Most likely assignment or logging added low-engagement installs to
gate_40 (or dropped them from gate_30); Engineering confirms the cause. <a href="#s6-integrity">Section 6.3</a> follows
this through to the retention result.</p>
{srm_table}
<p class="note">Raw assignment counts, before the one outlier ({out_txt}) was dropped; the cleaned analysis sample has
{num(clean_excess)} more gate_40 players. The &ldquo;fewer than {GATE_LEVEL}&rdquo; row adds up the two rows above
it.</p>
</section>"""

    # ------------------------------------------------------------------ 3 retention
    def s3_retention(self) -> str:
        o, f, gaps = self.ck["overall"], self.funnel, self.gaps
        played = f.loc["Played at least 1 round", "share_of_installs"]
        d1_share = f.loc["Returned on Day 1", "share_of_installs"]
        both = f.loc["Returned on Day 1 and Day 7"]
        c = self.conf
        rb = self.rb
        rows = [[esc(_range_label(str(b))), num(r["players"]), pct(r["share_of_players"]), pct(r["retention_1"]),
                 pct(r["retention_7"]), f"{_bound(r['retention_7_ci_low'] * 100, 1)}&ndash;"
                 f"{_bound(r['retention_7_ci_high'] * 100, 1)}%"] for b, r in rb.iterrows()]
        bucket_table = _table(["Rounds in first 14 days", "Players", "Share of installs", "D1", "D7", f"D7 {c} CI"],
                              rows, num_cols={1, 2, 3, 4, 5})
        top_bucket = rb.index[-1]
        ver = gaps[gaps["column"] == "version"].iloc[0]
        eng = gaps[gaps["column"] == "rounds_bucket"].iloc[0]
        d1g = gaps[gaps["column"] == "d1_status"].iloc[0]
        early, sizing = self.early, self.early["onboarding_test_sizing"]
        return f"""
<section id="s3">
<h2><span class="sec-num">3</span>Retention analysis (Cookie Cats)</h2>
<p class="lede">Which new players leave first, and where is the biggest drop?</p>
<p>The retention data comes from the company's mobile game (Cookie Cats, one 2017 install cohort), a different product
from the app the ads ran in. The questions carry over to the app's new users; the segment sizes will not transfer
one-for-one.</p>
{_callout("info", "Definitions",
    f"<b>D1 retention</b> = share of installs who came back and played the day after installing "
    f"(<code>retention_1</code>). <b>D7</b> = share who came back and played on day 7 after installing "
    f"(<code>retention_7</code>): classic Day-7 retention, not &ldquo;any day from day 7 on&rdquo;. A few players "
    f"with zero rounds carry these flags, so strictly they mean &ldquo;came back to the game&rdquo; (Section 2.3). "
    f"D7 is recorded independently of D1: {num(self.d7_not_d1)} of the {num(o['players'])} analysed players were back "
    f"on Day 7 without returning on Day 1. "
    f"<b>Rounds</b> = game rounds played in the first 14 days, a window that includes Day 7. All "
    f"{num(o['players'])} players form a single install cohort (the data has no install dates). Overall: D1 "
    f"{pct(o['retention_1'])} ({c} CI {pct(o['retention_1_ci_low'])}&ndash;{pct(o['retention_1_ci_high'])}), D7 "
    f"{pct(o['retention_7'])} ({pct(o['retention_7_ci_low'])}&ndash;{pct(o['retention_7_ci_high'])}).")}
<h3>3.1 The biggest drop happens before Day 1</h3>
<p>{pct(1 - o['retention_1'])} of installs don't return on Day 1. {pct(played)} play at least one round, but only
{pct(d1_share)} return on Day 1, so the largest absolute loss ({(played - d1_share) * 100:.0f} pp of installs) happens
between the first session and Day 1. {pct(o['retention_7'])} play on Day 7, and {pct(both['share_of_installs'])} of
installs play on both Day 1 and Day 7 ({pct(both['step_conversion'])} of the Day-1 returners).</p>
{self.fig("ret_funnel", "each bar is the share of all installs that reached the step; hover a bar for the "
          "conversion from the previous step.")}
<h3>3.2 Day 1 is the earliest strong signal of who stays</h3>
<p>Day-1 returners are {self.d7_yes / self.d7_no:.1f}&times; as likely to play on Day 7 ({pct(self.d7_yes)} vs
{pct(self.d7_no)}). This is an association: it identifies who stays, it does not show that prompting a Day-1 visit
would lift D7. That is what the experiment in R6 would test. It also sets a ceiling, not a forecast: each 1 pp of
installs moved from &ldquo;no Day-1 return&rdquo; to &ldquo;returned&rdquo; is worth at most
&asymp;{pp(self.d1_ceiling / 100)} of D7, and only if those players then behaved like today's Day-1 returners.</p>
{self.fig("ret_by_d1", "bars are D7 retention for players who did and did not come back on Day 1; whiskers are "
          f"{c} confidence intervals (tiny here because both groups are large).")}
<h3>3.3 Engagement depth separates players most</h3>
<p>Half of players play {num(self.median_rounds)} rounds or fewer in their first 14 days. Players with fewer than
{self.low_cut} rounds are {pct(early['share_of_installs'], 0)} of installs ({num(early['players'])} players), and only
{pct(early['retention_7'])} of them ({num(early['d7_players'])} players) are back on Day 7, at most
{pct(early['max_bucket_retention_7'])} in any single bucket. Retention climbs with every bucket; at
{esc(str(top_bucket))} rounds D7 reaches {pct(rb.loc[top_bucket, 'retention_7'])}. Only {pct(self.share_reach, 0)} of
players played {GATE_LEVEL}+ rounds, so at most about {pct(self.share_reach, 0)} of installs could have met the
level-{GATE_LEVEL} gate, which matters for the gate experiment in <a href="#s6">Section 6</a>. Buckets are cut around
the two gate positions (level {GATE_LEVEL} and 40).</p>
{self.fig("ret_by_rounds_bucket", "blue = D1, orange = D7 retention for each rounds bucket; n under each label is "
          "the number of players; whiskers are confidence intervals.")}
{bucket_table}
{self.fig("ret_engagement_curve", "read it like a survival curve over game progress: the height at N is the share "
          "of players who played at least N rounds. Dotted lines mark the two gate positions.")}
{self.fig("ret_by_rounds_curve", "each point is a 5-round bin. Players who come back on Day 7 also have more days "
          "in which to play, so the curve cannot show cause and effect.")}
<h3>3.4 Which dimension separates players most?</h3>
<p>Engagement depth separates D7 retention by {eng['gap_pp']:.0f} pp (partly by construction) and Day-1 return by
{d1g['gap_pp']:.0f} pp. The two gate versions differ by {ver['gap_pp']:.1f} pp raw (the naive comparison, examined in
Section 6), of which only about {pp(abs(self.dec['within_reached_30']), 1)} could be the gate (not certified): a minor
lever next to engagement.</p>
{self.fig("ret_gap_by_dimension", "for each way of splitting players, the bar is the D7 gap between its best and "
          "worst segment. A longer bar means the dimension tells players apart better.")}
{_callout("warn", "Association, partly by definition",
    "Rounds are counted over the first 14 days, which includes Day 7: a player who comes back on Day 7 has more days "
    "in which to play, so part of the rounds&ndash;retention link is built into the definitions. The pattern sizes "
    "the early-churn segment (whom to help); it is not a Day-0 targeting rule, because 14-day rounds are not known on "
    "Day 0, and it does not show that making people play more would keep them. That needs an experiment (R6).")}
<p class="so-what"><b>So what.</b> The first session and Day 1 are where most new players are lost, and only
{pct(early['retention_7'])} of the least-engaged {pct(early['share_of_installs'], 0)} of installs are back on Day 7.
That is the problem for the Onboarding PM's next experiment (<a href="#recommendations">R6</a>): a randomized Day-1
re-engagement test for new players who play little on their first day, with D7 as the primary metric. Detecting
{pp(sizing['target_lift_abs'], 1, sign=True)} of D7 on the {pct(early['retention_7'])} base (a placeholder target) needs
&asymp;{kn(sizing['players_needed_5050'])} target players (&asymp;{kn(sizing['installs_needed_5050'])} installs) at
50/50.</p>
</section>"""

    # ------------------------------------------------------------------ 4 ad experiment
    def s4_ad(self) -> str:
        t, ad, c = self.t, self.ad, self.conf
        b, pw, bz = ad["bootstrap"], self.pw, self.bz
        arms = self.arms
        inc, val, be = bz["incremental_conversions"], bz["incremental_value_usd"], bz["breakeven_cpm_usd"]
        hold, sh_ci = bz["always_on_holdout_cost"], bz["share_of_ad_conversions_incremental_ci"]
        ses_rel = pw["smallest_lift_of_interest_rel"]
        ses = pw["power_at_relative_lift"][str(ses_rel)]

        metrics = _table(
            ["Role", "Metric", "Definition", "Why"],
            [[_chip("info", "Primary"), "Conversion rate",
              "Converted users &divide; users assigned to the arm (user level; each user counted once)",
              "The PM's question is about conversions; it is what the campaign is meant to move."],
             [_chip("muted", "Secondary"), "Relative lift", "Ad rate &divide; PSA rate &minus; 1",
              "Comparable across campaigns with different baselines."],
             [_chip("muted", "Secondary"), "Incremental conversions",
              "(ad rate &minus; PSA rate) &times; users in the ad arm", "Turns the lift into a business count."],
             [_chip("muted", "Secondary"), "Breakeven CPM",
              "Incremental conversions &times; value per conversion &divide; impressions &times; 1,000",
              "The highest price per 1,000 impressions at which the campaign still pays back."],
             [_chip("good", "Guardrail"), "Sample ratio (SRM)",
              f"Observed vs intended {self.split} split (chi-square), plus how close the split is to an exact quota",
              f"Detects broken assignment; uninformative here because the split lands on exactly {self.split}, most "
              "likely a fixed quota (Section 2.4)."],
             [_chip("good", "Guardrail"), "Exposure parity", "Mean and distribution of ads served per user, by arm",
              "Both arms were served the same slots (ads or PSAs); a gap would mean unequal treatment."],
             [_chip("warn", "Missing"), "Unsubscribe / complaint rate, ad hides, CPA / spend, uninstalls, revenue",
              "Not in the data", "Would guard against a campaign that converts but annoys or costs too much (R4)."]],
            stack=True)

        arm_rows = [[F.ARM_NAMES[k], num(arms.loc[k, "n"]), num(arms.loc[k, "conversions"]), pct(arms.loc[k, "rate"], 3),
                     f"{pct(arms.loc[k, 'ci_low'], 3)} to {pct(arms.loc[k, 'ci_high'], 3)}"] for k in ("ad", "psa")]
        arm_table = _table(["Arm", "Users", "Conversions", "Conversion rate", f"{c} CI (Wilson)"], arm_rows,
                           num_cols={1, 2, 3, 4})
        ci_table = _table(
            ["Method", f"{c} CI, absolute lift", f"{c} CI, relative lift", "Note"],
            [["Newcombe hybrid score (primary)", ci_pp(t["abs_ci_low"], t["abs_ci_high"]),
              ci_pct(t["rel_ci_low"], t["rel_ci_high"], 1),
              "Well-behaved for proportions and unequal arms; relative CI on the log risk ratio"],
             ["Wald (normal approximation)", ci_pp(*ad["wald_ci"]), "&ndash;", "Textbook interval, for comparison"],
             [f"Bootstrap percentile ({num(b['n_boot'])} resamples)", ci_pp(*b["abs_ci"]), ci_pct(*b["rel_ci"], 1),
              f"No distributional assumption; {pct(b['share_draws_le_0'], 1)} of draws &le; 0"]],
            num_cols={1, 2})

        mde_now, mde_5050 = pw["mde_current"], pw["mde_if_5050_same_total"]
        mde_8020 = S.mde(t["rate_c"], int(self.n_total * 0.8), int(self.n_total * 0.2), self.alpha, self.power)
        n10 = pw["total_n_for_10pct_rel_lift"]
        lifts = sorted(pw["power_at_relative_lift"].values(), key=lambda r: r["rel"])
        power_table = _table(
            ["True relative lift", "Absolute", f"Power at {self.split} (as run)",
             f"Power at 50/50 (same {num(self.n_total)} users)"],
            [[f"{pct(r['rel'], 0)}" + (" <b>(smallest worth acting on)</b>" if r["rel"] == ses_rel else ""),
              pp(r["abs"]), power_pct(r["power_current_split"]), power_pct(r["power_5050_same_total"])]
             for r in lifts], num_cols={1, 2, 3})
        split_table = _table(
            ["Split (ad / PSA)", f"Lift detectable with 80% power, {num(self.n_total)} users",
             f"Users needed for a {pct(ses_rel, 0)} relative lift ({pp(ses['abs'])})"],
            [[f"{self.split} (as run)", f"{pp(mde_now['mde_abs'])} ({pct(mde_now['mde_rel'])} relative)",
              num(n10["0.96"])],
             ["80/20", f"{pp(mde_8020['mde_abs'])} ({pct(mde_8020['mde_rel'])} relative)", num(n10["0.8"])],
             ["50/50", f"{pp(mde_5050['mde_abs'])} ({pct(mde_5050['mde_rel'])} relative)", num(n10["0.5"])]],
            num_cols={1, 2})

        biz_table = _table(
            ["Quantity", "Value", "How it is computed"],
            [["Incremental conversions",
              f"&asymp;{num(inc['point'])} ({c} CI {num(inc['ci_low'])}&ndash;{num(inc['ci_high'])})",
              f"absolute lift &times; {num(t['n_t'])} ad-arm users"],
             ["Ad impressions (ad arm)", num(bz["impressions_ad_group"]), "sum of ads served"],
             ["Impressions per incremental conversion", num(bz["impressions_per_incremental_conversion"]),
              "impressions &divide; incremental conversions"],
             ["Share of ad-arm conversions that are incremental",
              f"{pct(bz['share_of_ad_conversions_incremental'])} ({c} CI {pct(sh_ci[0])}&ndash;{pct(sh_ci[1])})",
              "lift &divide; ad-arm rate = 1 &minus; 1 / risk ratio"],
             ["Last-touch (any-touch) overstatement",
              f"{times(bz['last_touch_overstatement_x'])} ({c} CI {self.lt[0]:.1f}{NDASH}{times(self.lt[1])})",
              f"{num(t['conv_t'])} ad-arm conversions &divide; {num(inc['point'])} incremental"],
             [f"Incremental value <b>(assumed {usd(self.value, 0)} per conversion)</b>",
              f"&asymp;{usd_k(val['point'])} ({c} CI {usd_k(val['ci_low'])}&ndash;{val['ci_high'] / 1000:,.0f}K)",
              "incremental conversions &times; assumed value"],
             [f"Breakeven CPM <b>(assumed {usd(self.value, 0)} per conversion)</b>",
              f"{usd(be['point'])} ({c} CI {usd(be['ci_low'])}&ndash;{be['ci_high']:.2f})",
              "incremental value &divide; impressions &times; 1,000"],
             [f"Always-on {pct(hold['share'], 0)} PSA holdout, per {kn(self.n_total)}-user flight",
              f"&asymp;{num(hold['users_per_588k_flight'])} users; &asymp;{num(hold['conversions_forgone'])} "
              f"conversions forgone vs. no holdout (&asymp;{usd_k(hold['value_forgone_usd'], 1)})",
              "holdout users &times; absolute lift (&times; assumed value)"],
             [f"Of which already forgone by this test's {pct(hold['as_run_control_share'], 0)} PSA arm",
              f"&asymp;{num(hold['as_run_control_conversions_forgone'])}; the step from "
              f"{pct(hold['as_run_control_share'], 0)} to {pct(hold['share'], 0)} costs "
              f"&asymp;{num(hold['extra_conversions_vs_as_run'])} more",
              "PSA share &times; flight users &times; absolute lift"]],
            num_cols={1})
        cost_per_cpm = bz["impressions_per_incremental_conversion"] / 1000

        return f"""
<section id="s4">
<h2><span class="sec-num">4</span>Ad experiment readout (ad vs PSA)</h2>
<p class="lede">Did ads increase conversion, by how much, and is it worth the money?</p>
<h3 id="s4-hypothesis">4.1 Hypothesis</h3>
<p>Showing the campaign's ads, instead of a public-service announcement in the same ad slots, increases the share of
users who convert. Null hypothesis: no difference in conversion rate between the arms. Two-sided test,
&alpha; = {self.alpha:g}. The smallest lift worth acting on is {pct(ses_rel, 0)} relative ({pp(ses['abs'])} on the
control rate), &asymp;{approx(self.ses_conv, 100)} conversions per {kn(t['n_t'])}-user ad flight
(&asymp;{usd_k(self.ses_conv * self.value)} at the assumed {usd(self.value, 0)}). It is a placeholder assumption in
<code>config.yaml</code>, not derived from the result; in practice it is agreed with the PM and Finance before launch.
It is used to judge power (4.5).</p>
<h3 id="s4-metrics">4.2 Metrics</h3>
{metrics}
<h3 id="s4-design">4.3 Design and integrity</h3>
<p>Users were randomized individually: {num(t['n_t'])} saw ads and {num(t['n_c'])} saw PSAs. The integrity checks are
in <a href="#s2-ad">Section 2.4</a>: the split lands on exactly {self.split}, most likely a fixed quota, so the SRM test
is uninformative; exposure matches on average with a slightly different shape; and day, hour and exposure are
post-assignment variables used only for exploratory cuts. The headline comparison below uses no covariates.</p>
<h3 id="s4-results">4.4 Results</h3>
<p>The ad arm converted at {pct(t['rate_t'], 3)} vs {pct(t['rate_c'], 3)} for PSA. <b>Absolute lift
{pp(t['abs_lift'], sign=True)}</b> ({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), <b>relative lift
{spct(t['rel_lift'], 1)}</b> ({c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'], 1)}); z = {t['z']:.2f},
{pval_sci(t['p_value'])}. Three interval methods agree, so the conclusion does not hinge on a method choice, and none
of the {num(b['n_boot'])} bootstrap resamples shows a lift &le; 0.</p>
{arm_table}
{ci_table}
{self.fig("ad_rates", f"bars are conversion rates and whiskers {c} confidence intervals. The PSA interval is wider "
          "because that arm is much smaller.")}
{self.fig("ad_bootstrap", "each bar counts re-sampled versions of the experiment with a given lift. The shaded band "
          "holds the middle 95% of them; the grey line marks no effect.")}
<h3 id="s4-power">4.5 Power at the smallest lift worth acting on</h3>
<p>Power is a property of the design, so it is judged at the smallest lift worth acting on, {pct(ses_rel, 0)}
relative ({pp(ses['abs'])}). Power evaluated at the observed effect is not reported: it only restates the p-value.
At {self.split} the test had {self.power * 100:.0f}% power only for lifts of at least {pp(mde_now['mde_abs'])}
({pct(mde_now['mde_rel'], 0)} relative). For the smallest lift worth acting on, power was
<b>{power_pct(ses['power_current_split'])}</b>, close to a coin flip, against
{power_pct(ses['power_5050_same_total'])} had the same {num(self.n_total)} users been split 50/50.</p>
{power_table}
<p>Low power does not undo a clear result: the lift's interval excludes 0 by a wide margin ({pval_sci(t['p_value'])}),
so Q1 is answered. The cost of {self.split} falls on the next, smaller questions (budget, frequency, timing): the same
users split 50/50 could detect {pp(mde_5050['mde_abs'])}, and matching this test's sensitivity at 50/50 would have taken
only &asymp;{kn(pw['total_n_for_current_mde_at_5050'])} users instead of {kn(self.n_total)}. R4 recommends 50/50 or
80/20.</p>
{split_table}
{self.fig("ad_mde_split", "for the same total number of users, the curve is the smallest lift the test could "
          f"reliably detect ({self.power * 100:.0f}% power) at each treatment share; the orange line is the smallest "
          "lift worth acting on. Lower is better.")}
{self.fig("ad_power_curve", "the height of the curve is the chance that this sample flags a true lift of a given "
          "size as significant; the orange line marks the smallest lift worth acting on.")}
<h3 id="s4-business">4.6 Business translation</h3>
<p>The lift means about {num(inc['point'])} conversions ({c} CI {num(inc['ci_low'])}&ndash;{num(inc['ci_high'])})
would not have happened without the campaign's {millions(bz['impressions_ad_group'])} ad impressions: one incremental
conversion per {num(bz['impressions_per_incremental_conversion'])} impressions. That is only
{pct(bz['share_of_ad_conversions_incremental'])} ({c} CI {pct(sh_ci[0])}&ndash;{pct(sh_ci[1])}) of the ad arm's
{num(t['conv_t'])} conversions; the rest would have happened anyway. Last-touch (any-touch) attribution would credit
every ad-group conversion to the ads, all {num(t['conv_t'])}, and overstate the campaign
{times(bz['last_touch_overstatement_x'])} ({c} CI {self.lt[0]:.1f}{NDASH}{times(self.lt[1])}). Every ad-group user saw
at least one ad, so last-touch and any-touch coincide here. That is the case for judging the campaign by a randomized
holdout rather than by attributed conversions (R1).</p>
<p>A money value needs two numbers the data does not have: what a conversion is worth and what we pay per 1,000
impressions (CPM). With an illustrative {usd(self.value, 0)} per conversion, the incremental value is
&asymp;{usd_k(val['point'])} ({c} CI {usd_k(val['ci_low'])}&ndash;{val['ci_high'] / 1000:,.0f}K) and the campaign
breaks even at a CPM of <b>{usd(be['point'])}</b> ({c} CI {usd(be['ci_low'])}&ndash;{be['ci_high']:.2f}): if we pay
less than that, it pays back. Put differently, cost per incremental conversion = CPM &times; {cost_per_cpm:.2f}.</p>
<p>Keeping the measurement going has a price. A {pct(hold['share'], 0)} always-on PSA holdout puts
&asymp;{num(hold['users_per_588k_flight'])} users per {kn(self.n_total)}-user flight on PSAs and forgoes
&asymp;{num(hold['conversions_forgone'])} conversions versus no holdout ({num(hold['users_per_588k_flight'])} &times;
{pp(t['abs_lift'])}), about {usd_k(hold['value_forgone_usd'], 1)} at the illustrative value. This test's
{pct(hold['as_run_control_share'], 0)} PSA arm already forgoes &asymp;{num(hold['as_run_control_conversions_forgone'])},
so the step from {pct(hold['as_run_control_share'], 0)} to {pct(hold['share'], 0)} costs
&asymp;{num(hold['extra_conversions_vs_as_run'])} more: the price of continuing to know the campaign's true effect.</p>
{biz_table}
{_callout("warn", f"Assumption, not data: {usd(self.value, 0)} per conversion",
    f"The value per conversion is a placeholder, not an estimate. Breakeven CPM scales linearly with it "
    f"({usd(self.value / 2, 0)} &rarr; {usd(be['point'] / 2)}; {usd(self.value * 2, 0)} &rarr; {usd(be['point'] * 2)}). "
    "Finance should supply the real value and our actual CPM before any money figure is quoted.")}
{self.fig("ad_breakeven", "pick a value per conversion on the x-axis; the line gives the highest price per 1,000 "
          f"impressions at which the campaign still pays back (band = {c} CI). Paying less than the line = profitable.")}
<h3 id="s4-caveats">4.7 Caveats</h3>
{_ul([
    "<b>Novelty effect and duration:</b> the data has no timestamps, so we cannot tell whether the lift fades as users "
    "get used to the ads, how long the test ran, or whether it covered full weekly cycles. The estimate is an average "
    "over the whole flight. The always-on holdout (R1) and assignment timestamps (R4) fix this going forward.",
    "<b>What the lift measures:</b> both arms were shown something in the same slots, so the lift is the effect of "
    "the campaign's message versus a neutral PSA, not of ads versus no ads.",
    f"<b>Quota allocation:</b> the analysis assumes users were randomized within the {self.split} quota; the data "
    "cannot confirm it (Section 2.4).",
    "<b>Conversion definition:</b> the dataset does not say what a conversion is or which attribution window was "
    "used; both must be confirmed before comparing with other campaigns.",
    "<b>One flight, one budget:</b> the result does not extrapolate to 2&times; spend (Section 5.5, R2).",
])}
</section>"""

    # ------------------------------------------------------------------ 5 heterogeneity
    def _seg_table(self, dim: str, label: str) -> str:
        rows = []
        for seg, r in self.segi[dim].iterrows():
            seg_txt = f"hour {seg}" if dim == "most_ads_hour" else esc(_range_label(seg))
            rows.append([seg_txt, f"{num(r['n_t'])} / {num(r['n_c'])}",
                         f"{pct(r['rate_t'], 2)} / {pct(r['rate_c'], 2)}",
                         f"{pp(r['abs_lift'], sign=True)}<br><span class='sub'>{ci_pp(r['abs_ci_low'], r['abs_ci_high'])}</span>",
                         f"{pp(r['diff_vs_rest'], sign=True)}<br><span class='sub'>"
                         f"{ci_pp(r['diff_vs_rest_ci_low'], r['diff_vs_rest_ci_high'], sign=True)}</span>",
                         pp(r["diff_vs_rest_ac"], sign=True),     # centre of the Agresti-Caffo CI the test is about
                         pval(r["p_vs_rest_adj"], prefix=False),
                         _chip("info", "Yes") if r["differs_adj"] else "No"])
        return _table([label, "Users (ad / PSA)", "Conversion (ad / PSA)", f"Lift ({self.conf} CI)",
                       f"Lift vs other segments ({self.conf} CI)", "CI centre (adjusted)", "Holm p (vs others)",
                       "Differs (Holm)"],
                      rows, num_cols={1, 2, 3, 4, 5, 6})

    def s5_heterogeneity(self) -> str:
        het, t, a, c = self.het, self.t, self.alpha, self.conf
        hd, hh, hp, he = (het[k] for k in ("most_ads_day", "most_ads_hour", "daypart", "exposure_bucket"))
        n_dims = het["n_dimensions_explored"]
        dims = [("most_ads_day", "Peak ad day"), ("most_ads_hour", "Peak ad hour"), ("daypart", "Daypart"),
                ("exposure_bucket", "Total ads seen")]
        day = self.segi["most_ads_day"]
        con = self.con
        nightc = hp["night_counts"]

        def differing(dim: str) -> str:
            h = het[dim]
            segs = h["segments_differing_holm"]
            head = f"{len(segs)} of {h['n_segments']}"
            if not segs:
                return head
            tab = self.segi[dim]
            up = [s for s in segs if tab.loc[s, "diff_vs_rest"] > 0]
            down = [s for s in segs if tab.loc[s, "diff_vs_rest"] < 0]
            names = lambda ss: ", ".join(esc(_range_label(s) if dim == "exposure_bucket" else s) for s in ss)
            parts = ([f"above: {names(up)}"] if up else []) + ([f"below: {names(down)}"] if down else [])
            return f"{head}<br><span class='sub'>{'; '.join(parts)}</span>"

        def lrt_cell(dim: str) -> str:
            h = het[dim]
            p = h["lrt"]["p_value"]
            if dim == "most_ads_day":
                note = f"{pval(h['lrt_p_bonferroni_3_dims'], prefix=False)} allowing for {n_dims} dimensions"
                verdict = evidence(p)
            elif dim == "most_ads_hour":
                note = f"{pval(h['lrt_excluding_night']['p_value'], prefix=False)} without Night ({NIGHT_HOURS})"
                verdict = evidence(p)
            elif dim == "daypart":
                note = f"{pval(h['lrt_excluding_night']['p_value'], prefix=False)} without Night"
                verdict = f"driven by Night ({NIGHT_HOURS})"
            else:
                note = "post-assignment: exploratory"
                verdict = evidence(p)
            return f"{pval(p, prefix=False)} &middot; {verdict}<br><span class='sub'>{note}</span>"

        def ext(dim: str) -> str:
            h = het[dim]
            return (f"{esc(self._seg_name(dim, h['min_lift_segment']))}: {_signed(h['min_lift_pp'], 2)} pp<br>"
                    f"{esc(self._seg_name(dim, h['max_lift_segment']))}: {_signed(h['max_lift_pp'], 2)} pp")

        labels = ["Segments compared",
                  "Interaction test p: does the lift differ across segments at all?",
                  "Segments whose lift differs from the other segments' (Holm)",
                  f"Contrasts expected to be false positives by chance (segments &times; &alpha; {a:g})",
                  "Segments with a lift &ne; 0 (Holm): a different question, mostly about segment size",
                  "Lowest / highest segment lift",
                  "Smallest control group &middot; segments with 0 control conversions",
                  f"Sensitivity: lift standardized to these segments (crude {pp(t['abs_lift'])})"]
        cols = [[num(het[d]["n_segments"]), lrt_cell(d), differing(d),
                 f"{het[d]['n_segments'] * a:.2f}".rstrip("0").rstrip("."),
                 f"{het[d]['lift_positive']['holm']} of {het[d]['n_segments']}", ext(d),
                 f"{num(het[d]['min_control_users'])} &middot; {het[d]['segments_with_zero_control_conversions']}",
                 pp(het[d]["sensitivity_stratified"]["mh_risk_diff"])] for d, _ in dims]
        summary = _table(["", *[lab for _, lab in dims]],
                         [[labels[i], *[cl[i] for cl in cols]] for i in range(len(labels))],
                         stack=True, cls="grid4")

        tue, thu = hd["max_lift_segment"], hd["min_lift_segment"]
        tue_r = day.loc[tue]
        thu_ci0 = day.loc[thu, "abs_ci_low"] < 0 < day.loc[thu, "abs_ci_high"]
        le20, b2135 = con["le_20_ads_pooled"], con["bucket_21_35"]
        inc_b = con["incremental_conversions_by_bucket"]
        neg_buckets = [lab for lab in C.EXPOSURE_LABELS if inc_b.get(lab, 0) < 0]
        mh = {d: het[d]["sensitivity_stratified"]["mh_risk_diff"] for d, _ in dims}
        mh_lo, mh_hi = min(mh.values()), max(mh.values())
        sens_table = _table(["Dimension", "Lift standardized to its segments", "Crude lift (headline)"],
                            [[lab, pp(mh[d]), pp(t["abs_lift"])] for d, lab in dims], num_cols={1, 2})
        heavy = self.expo.loc[list(HEAVY_EXPOSURE)]
        return f"""
<section id="s5">
<h2><span class="sec-num">5</span>Heterogeneity: day, hour, daypart and exposure</h2>
<p class="lede">Does the ad work better for some days, hours or exposure levels, and is that real, noise, or something we
can act on?</p>
<h3>5.1 Two different questions</h3>
<ol class="qs">
<li><b>&ldquo;Is there a lift in this segment?&rdquo;</b> A test of lift &ne; 0 inside the segment. Because the
overall lift is real, most large segments will show one; how many do mostly reflects segment size (power), not
whether segments differ.</li>
<li><b>&ldquo;Is this segment's lift different from the others'?&rdquo;</b> The heterogeneity question. It is
answered first by <b>one interaction test per dimension</b> (a deviance-based likelihood-ratio test: does a model with
a separate lift per segment fit better than one common lift? It works on the odds scale), and then by
<b>segment-vs-rest contrasts</b> on the percentage-point scale: the segment's lift minus the lift in all other
segments, Holm-corrected across segments. The point estimate is that raw difference; its CI and p-value use
Agresti&ndash;Caffo adjusted proportions (one success and one failure added per group), so cells with zero control
conversions cannot create fake significance. In sparse cells the interval is therefore not centred on the point
estimate; the segment tables show its centre in a separate column, &ldquo;CI centre (adjusted)&rdquo;. With k
contrasts at &alpha; = {a:g}, about k &times; {a:g} would come out &ldquo;significant&rdquo; by
chance alone.</li>
</ol>
<p>{n_dims} dimensions were explored (day, hour and exposure; dayparts regroup the hours), so an interaction p-value
just under 0.05 is weaker than it looks. Every dimension here is a post-assignment summary of user behaviour, so all
segment results are exploratory.</p>
{summary}
<h3>5.2 By peak ad day: modest evidence, but about users, not a day we can buy</h3>
<p>Lift ranges from {_signed(hd['min_lift_pp'], 2)} pp ({esc(thu)}-peak users{", CI includes 0" if thu_ci0 else ""}) to
{_signed(hd['max_lift_pp'], 2)} pp ({esc(tue)}-peak users). The interaction test gives {pval(hd['lrt']['p_value'])}:
{evidence(hd['lrt']['p_value'])} that the lift differs by peak day, still below 0.05
({pval(hd['lrt_p_bonferroni_3_dims'], prefix=False)}) after allowing for the {n_dims} dimensions explored.
{len(hd['segments_differing_holm'])} contrasts survive Holm: {esc(tue)}-peak users' lift is
{self._contrast('most_ads_day', tue)} relative to the other days, and {esc(thu)}-peak users' is
{self._contrast('most_ads_day', thu)}. With {hd['n_segments']} contrasts about {hd['n_segments'] * a:.2f} false
positives are expected by chance, so the day pattern is probably not pure noise. Part of {esc(tue)}'s lift is a low
control rate: its PSA arm has {num(tue_r['n_c'])} users and {num(tue_r['conv_c'])} conversions
({pct(tue_r['rate_c'], 2)}, one of the lowest control rates of the week).</p>
<p>But the &ldquo;peak day&rdquo; is the weekday on which a user happened to see the most ads: a user habit recorded
after assignment, not a slot we buy. {esc(tue)}-peak users may simply be different people. Moving budget to
{esc(tue)}s is a different intervention that this data cannot evaluate, so the pattern motivates a pre-registered test
that randomizes the delivery schedule (weekday and time slot; R3), not a reallocation.</p>
{self.fig("het_day", f"dots are the lift among users whose peak ad day was that day, lines their {c} CIs; filled = "
          "the day's lift differs from the other days' after Holm correction; the dotted line is the overall lift.")}
{self._seg_table("most_ads_day", "Peak ad day")}
<h3>5.3 By peak ad hour: no evidence</h3>
<p>The interaction test gives {pval(hh['lrt']['p_value'])}: {evidence(hh['lrt']['p_value'])} that the lift differs by
peak hour, and no hour's lift differs from the other hours' after Holm correction ({hh['n_segments']} contrasts, so
about {hh['n_segments'] * a:.1f} false positives would be expected by chance). The hourly estimates are also fragile:
{len(self.zero_hours)} hours ({hour_ranges(self.zero_hours)}, mostly night) have zero control conversions, and the
smallest hour has only {num(hh['min_control_users'])} control users. Without the Night daypart's hours
({NIGHT_HOURS}) the interaction test gives {pval(hh['lrt_excluding_night']['p_value'])}.</p>
{self.fig("het_hour", f"same reading as the day chart, for 24 hours. Hours {NIGHT_HOURS} have very few PSA users, "
          "hence very wide intervals; hollow everywhere means no hour stands out from the others.")}
<details class="more-table"><summary>Per-hour table ({hh['n_segments']} rows)</summary>
{self._seg_table("most_ads_hour", "Peak ad hour")}</details>
<h3>5.4 By daypart: driven by Night, where the control arm has one conversion</h3>
<p>Grouping hours into the four dayparts a media buyer can actually buy gives an interaction
{pval(hp['lrt']['p_value'])}, but it is driven by {esc(NIGHT.replace('-', NDASH))}, where the control arm has
{num(nightc['psa']['conversions'])} conversion among {num(nightc['psa']['users'])} users (ad arm:
{num(nightc['ad']['conversions'])} among {num(nightc['ad']['users'])}). Excluding night,
{pval(hp['lrt_excluding_night']['p_value'])}, and no daypart's lift differs from the others after correction: Night's
contrast with the other dayparts is {self._contrast('daypart', NIGHT)}. There is no reliable pattern by time of day to
plan spend around.</p>
{self.fig("het_daypart", f"one dot per daypart (the hour in which the user saw the most ads), lines are {c} CIs; "
          "filled would mean the daypart differs from the others after Holm correction.")}
{self._seg_table("daypart", "Daypart")}
<h3 id="s5-exposure">5.5 By total ads seen: the lift lives in heavy users (exploratory)</h3>
<p>The {pct(con['share_users_le_20_ads'], 0)} of users who saw &le; {LOW_EXPOSURE_MAX} ads show no lift we could
measure: pooled, {pp(le20['abs_lift'], sign=True)} ({c} CI {ci_pp(le20['abs_ci_low'], le20['abs_ci_high'], sign=True)}).
The next {pct(b2135['share_ad_users'], 0)} of ad users (21&ndash;35 ads) are inconclusive:
{pp(b2135['abs_lift'], sign=True)} ({c} CI {ci_pp(b2135['abs_ci_low'], b2135['abs_ci_high'], sign=True)}). At
{self.heavy_range} ads the lift is {_plain(_x100(heavy['abs_lift'].min()), 1)}&ndash;{pp(heavy['abs_lift'].max(), 1)}:
these buckets hold {pct(con['share_ad_users_36_200'], 0)} of ad users and
{pct(con['share_incremental_conversions_36_200'], 0)} of the bucket-by-bucket incremental conversions
({num(con['incremental_conversions_36_200'])} of {num(con['incremental_conversions_bucketwise_total'])}, each bucket
against its own PSA rate; that total differs from the headline {num(self.bz['incremental_conversions']['point'])}, and
{" and ".join(_range_label(lab) for lab in neg_buckets) or "no bucket"} contribute slightly negative amounts). The
{esc(TOP_EXPOSURE)} bucket is unusable: its interval runs from
{_plain(con['top_bucket_ci_pp'][0], 1)} to {_signed(con['top_bucket_ci_pp'][1], 1)} pp, with only
{num(con['top_bucket_control_users'])} control users. The interaction test is unambiguous
({pval(he['lrt']['p_value'])}; {he['differs_from_rest']['holm']} of {he['n_segments']} buckets differ from the rest
after Holm), but exposure tracks how active a user is: even in the PSA arm, conversion rises from
{pct(con['control_rate_lowest_bucket'])} ({_range_label(C.EXPOSURE_LABELS[0])} ads) to
{pct(con['control_rate_highest_bucket'])} ({esc(TOP_EXPOSURE)}). Users who see many ads differ from users who see few
in many ways, so this says where the incremental conversions come from, not how lift responds to frequency.</p>
{self.fig("het_exposure", "conversion rate per arm within each exposure bucket. The PSA (grey) rate also rises "
          "steeply with exposure: heavy users convert more anyway.")}
{self.fig("het_exposure_forest", f"the same comparison as a lift per bucket with {c} CIs; filled = the bucket's lift "
          "differs from the other buckets' after Holm correction.")}
{self._seg_table("exposure_bucket", "Total ads seen")}
{_callout("warn", "Post-assignment: a hypothesis, not a frequency curve",
    "The number of ads a user saw was determined after assignment and reflects how active they are, so this pattern "
    "cannot be read as &ldquo;more ads, more lift&rdquo;: it shows where the incremental conversions come from "
    "(heavy users), not what an extra impression buys. It is the hypothesis behind the frequency-cap / budget test "
    "(R2), and only a randomized change in spend or frequency can answer it.")}
<h3>5.6 Sensitivity: is the headline an artefact of how users are spread across segments?</h3>
<p>Standardizing the lift to each dimension's segments (Mantel&ndash;Haenszel weights) gives {_plain(_x100(mh_lo), 2)}
to {pp(mh_hi)}, against the crude {pp(t['abs_lift'])}: no Simpson's-paradox reversal, so the slightly different mix of
days, hours and exposure in the two arms does not explain the result. This is a sensitivity analysis on
post-assignment strata, not an adjusted estimate; the headline stays the simple randomized difference.</p>
{sens_table}
<p class="so-what"><b>So what.</b> Do not re-plan spend by day or hour (<a href="#recommendations">R3</a>): the day
signal describes users' habits, not a slot we can buy, and the hour and daypart signals do not hold up. If timing
matters, only a test that randomizes the delivery schedule can show it. The lift lives in heavy users; that is the
hypothesis for a randomized test of more impressions per user (or a frequency cap) before scaling
(<a href="#recommendations">R2</a>).</p>
</section>"""

    # ------------------------------------------------------------------ 6 gate experiment
    def s6_gate(self) -> str:
        g, srm, g1, g7, c = self.gate, self.gate["srm"], self.g1, self.g7, self.conf
        rounds, dec, dec1, bc, rr, rt = g["rounds"], self.dec, self.dec1, self.bc, self.rr, self.rt
        sbs, pg, band = self.sbs, g["pre_gate_engagement"], self.band
        nc = g["negative_control"]
        nc7 = nc["never_reached_30"]["retention_7"]
        ncx = nc["never_reached_30_excess_removed"]
        b15, b1529, b30 = (band[k]["retention_7"] for k in ("rounds_lt_15", "rounds_15_29", "rounds_ge_30"))
        b1528, b29 = band["rounds_15_28"]["retention_7"], band["rounds_29"]["retention_7"]   # the 29-round edge case
        bgap = g["d7_band_gap_difference_15_29_vs_lt_15"]                 # are the two bands' D7 gaps different?
        eff, eff_ci = dec["within_reached_30"], dec["install_level_effect_ci_if_only_reachers"]
        eff1, eff1_ci = dec1["within_reached_30"], dec1["install_level_effect_ci_if_only_reachers"]
        det = dec["detail"]
        past40 = rr["share_past_40_rounds"]
        # re-test sizing is for a drop; a rise of the same size needs a little more (variance is larger nearer 50%)
        rise_inst = rt["installs_needed_install_level_5050_if_rise"] / rt["installs_needed_install_level_5050"] - 1
        rise_reach = (rt["installs_needed_reacher_analysis_5050_if_rise"]
                      / rt["installs_needed_reacher_analysis_5050"] - 1)
        lt15 = sbs["rounds_lt_15"]["net_excess_t"]
        res_rows = []
        for name, m in (("D7 retention (primary)", g7), ("D1 retention (guardrail)", g1)):
            res_rows.append([name, pct(m["rate_c"], 2), pct(m["rate_t"], 2),
                             f"{pp(m['abs_lift'], sign=True)}<br><span class='sub'>{ci_pp(m['abs_ci_low'], m['abs_ci_high'])}</span>",
                             f"{spct(m['rel_lift'], 1)}", pval(m["p_value"], prefix=False),
                             pct(1 - m["boot_share_ge_0"], 1)])
        res_table = _table(["Metric", "gate_30 (control)", "gate_40 (treatment)", f"Difference ({c} CI)", "Relative",
                            "p", "Bootstrap draws below 0"], res_rows, num_cols={1, 2, 3, 4, 5, 6})
        w_never = (det["never_reached_30"]["w_t"] + det["never_reached_30"]["w_c"]) / 2
        w_reach = dec["share_reached_30"]
        r_never = (det["never_reached_30"]["r_t"] + det["never_reached_30"]["r_c"]) / 2
        r_reach = (det["reached_30"]["r_t"] + det["reached_30"]["r_c"]) / 2
        not_gate = _chip("muted wrap", "Cannot be the gate (imbalance or chance)")
        could_be = _chip("warn wrap", "Could be the gate (not an estimate)")
        dec_table = _table(
            ["Component", "Contribution (pp of installs)", "Could it be the gate?", "Where it comes from"],
            [["Player mix", pp(dec["composition"], sign=True), not_gate,
              f"gate_40 has more players who stop before level {GATE_LEVEL} "
              f"({pct(det['never_reached_30']['w_t'], 1)} vs {pct(det['never_reached_30']['w_c'], 1)}), and they "
              f"retain far less (D7 about {pct(r_never, 0)} vs {pct(r_reach, 0)} for players who get further)"],
             [f"Players who never met a gate (fewer than {GATE_LEVEL} rounds, {pct(w_never, 0)} of installs)",
              pp(dec["within_never_reached_30"], sign=True), not_gate,
              f"their D7 difference ({pp(nc7['abs_lift'], sign=True)}) &times; their share; they met neither gate"],
             [f"Players who could meet the gate ({GATE_LEVEL}+ rounds, {pct(w_reach, 0)} of installs)",
              f"{pp(eff, sign=True)}<br><span class='sub'>{c} CI {ci_pp(*eff_ci)}</span>", could_be,
              f"their D7 difference ({pp(b30['abs_lift'], sign=True)}, {c} CI "
              f"{ci_pp(b30['abs_ci_low'], b30['abs_ci_high'])}) &times; their share. Players with 15&ndash;"
              f"{GATE_LEVEL - 1} rounds, who never met a gate, show a similar gap ({pp(b1529['abs_lift'], sign=True)}, "
              f"{c} CI {ci_pp(b1529['abs_ci_low'], b1529['abs_ci_high'])})"],
             ["<b>Naive gap (sum)</b>", f"<b>{pp(dec['naive_diff'], sign=True)}</b>", "&ndash;",
              "gate_40 &minus; gate_30, all players"]],
            num_cols={1}, stack=True)
        return f"""
<section id="s6">
<h2><span class="sec-num">6</span>Gate experiment (Cookie Cats)</h2>
<p class="lede">Should the first gate move from level {GATE_LEVEL} to level 40?</p>
{_callout("warn", f"Sample-ratio {esc(srm['status'])}: the naive result is reported, not certified",
    f"Each version should get 50% of players. On raw assignment counts gate_40 has {num(srm['n_t'])} and gate_30 "
    f"{num(srm['n_c'])} ({pct(srm['observed_share_t'], 2)} in gate_40): chi-square {pval(srm['p_value'])}, below the "
    f"{self.srm_warn:g} warning line and above the {self.srm_fail:g} hard stop. gate_40 has "
    f"&asymp;{num(self.excess_clean)} extra installs and the net excess sits among low-engagement installs, so the naive "
    f"result (6.2) is checked (6.3) and decomposed (6.4) before any decision.")}
<h3>6.1 Hypothesis and metrics</h3>
<p>Moving the first gate (a forced wait or in-app purchase) from level {GATE_LEVEL} to level 40 changes how many
players stay. Null hypothesis: no difference. <b>Primary metric:</b> D7 retention. <b>Guardrails:</b> D1 retention and
rounds played in the first 14 days. Decision rule: ship gate_40 only if D7 is not worse and the guardrails hold;
keeping gate_{GATE_LEVEL} is the default, so an uncertified result means &ldquo;keep gate_{GATE_LEVEL}&rdquo;.</p>
<p>Throughout, <b>&ldquo;{GATE_LEVEL}+ rounds&rdquo; means &ldquo;could have reached level {GATE_LEVEL}&rdquo;</b>: a
round is one attempt at a level, so rounds &ge; levels, and the data has no level field. A player with fewer than
{GATE_LEVEL} rounds cannot have got past level {GATE_LEVEL} in either version; this report says such players
&ldquo;never met a gate&rdquo;, a close approximation (at exactly {GATE_LEVEL - 1} rounds a perfect gate_{GATE_LEVEL}
player can already face the gate; 6.4).</p>
<h3>6.2 The naive result</h3>
<p>gate_40 shows a D7 rate {pp(abs(g7['abs_lift']))} lower: {pct(g7['rate_t'], 2)} of players on Day 7 vs
{pct(g7['rate_c'], 2)} for gate_30 (<b>{pp(g7['abs_lift'], sign=True)}</b>, {c} CI
{ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])}; relative {spct(g7['rel_lift'], 1)}; {pval(g7['p_value'])}); in
{pct(1 - g7['boot_share_ge_0'], 1)} of {num(self.n_boot)} bootstrap resamples gate_40 is lower. This is what a standard
readout would report. It assumes the two arms are comparable, which the integrity checks below do not support.</p>
{res_table}
{self.fig("gate_rates", f"grey = gate_30 (control), blue = gate_40 (treatment); whiskers are {c} CIs.")}
{self.fig("gate_bootstrap", f"{num(self.n_boot)} re-sampled differences each for D1 and D7. Mass to the left of 0 "
          "means gate_40 retains fewer players in that resample; it describes the naive comparison only.")}
<h3 id="s6-integrity">6.3 Integrity checks: the arms are not fully comparable</h3>
<ol class="checks">
<li><b>Sample ratio, by rounds band</b> (<a href="#s2-gate">Section 2.5</a>): gate_40 has
&asymp;{num(self.excess_clean)} extra installs ({num(self.excess_raw)} in the raw log). The net excess is
{_signed(lt15, 0)} among players with fewer than 15 rounds ({pval(sbs['rounds_lt_15']['p_value'])}),
{_signed(sbs['rounds_15_29']['net_excess_t'], 0)} at 15&ndash;{GATE_LEVEL - 1} rounds
({pval(sbs['rounds_15_29']['p_value'])}) and {_signed(sbs['rounds_ge_30']['net_excess_t'], 0)} at {GATE_LEVEL}+ rounds
({pval(sbs['rounds_ge_30']['p_value'])}). These are raw counts in bands chosen after seeing the warning, so the
p-values are descriptive.</li>
<li><b>Pre-gate play:</b> below level {GATE_LEVEL} the versions are identical, yet rounds capped at {GATE_LEVEL - 1}
average {num(pg['mean_capped_29_t'], 2)} in gate_40 vs {num(pg['mean_capped_29_c'], 2)} in gate_30
(Mann&ndash;Whitney {pval(pg['mannwhitney_p'])}), and gate_40's engagement curve sits below gate_30's before any gate.
This is the same imbalance seen as a distribution, not independent evidence: among players with fewer than
{GATE_LEVEL} rounds the difference gives {pval(pg['mannwhitney_p_within_lt_30'])}.</li>
<li><b>Negative control:</b> players with fewer than {GATE_LEVEL} rounds met no gate in either version, yet D7 is
{pp(abs(nc7['abs_lift']))} lower in gate_40 ({c} CI {ci_pp(nc7['abs_ci_low'], nc7['abs_ci_high'], sign=True)};
{pval(nc7['p_value'])}). That is borderline on its own; it carries weight only because the sample-ratio warning
independently says the arms are not comparable. Such gap as there is comes from the 15&ndash;{GATE_LEVEL - 1} band
({pp(b1529['abs_lift'], sign=True)}, {pval(b1529['p_value'])}, balanced in number) rather than the &lt; 15 band where
the net excess sits ({pp(b15['abs_lift'], sign=True)}, {pval(b15['p_value'])}), though the two bands' gaps are not
distinguishable from each other ({pval(bgap['p_value'])}). Removing the net {num(ncx['excess_removed'])} extra
&lt; 15-round installs (as if none of them came back) moves it only to
{pp(ncx['retention_7']['abs_lift'], sign=True)} ({pval(ncx['retention_7']['p_value'])}). So the extra installs explain
the SRM and the player-mix part, but not this gap.</li>
</ol>
{self.fig("gate_engagement_gap", "the line is gate_40's share of players reaching at least N rounds minus gate_30's, "
          "with a pointwise 95% band. In the shaded region (before any gate) the versions are identical, so a gap "
          "there reflects who is in each arm, not a gate effect.")}
{self.fig("gate_negative_control", "each row is the gate_40 &minus; gate_30 D7 difference within a group of players, "
          f"with its {c} CI. The grey diamonds are players who never met a gate (fewer than {GATE_LEVEL} rounds, then "
          f"split into &lt; 15 and 15&ndash;{GATE_LEVEL - 1}): they should sit on 0. The filled dot is the naive "
          f"all-player result; the hollow dot is players who could meet the gate ({GATE_LEVEL}+ rounds).")}
<p>Conclusion: most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from
gate_30); Engineering confirms the cause. The naive {pp(dec['naive_diff'], sign=True)} therefore mixes a difference in
who is in each arm with any effect of the gate.</p>
<h3 id="s6-decomp">6.4 Where does the naive gap come from?</h3>
<p>The D7 gap splits exactly into three parts (pp of installs). Two of them cannot be the gate (imbalance or chance):
the different player mix ({pp(dec['composition'], sign=True)}) and the difference among players who never met a gate
({pp(dec['within_never_reached_30'], sign=True)}). Together they are about {approx(self.not_gate_share * 100, 10)}% of
the naive gap, which therefore sits where the gate cannot act. The rest, <b>{pp(eff, sign=True)} per install</b> ({c} CI
{ci_pp(*eff_ci)}; &asymp;{per10k(eff)} fewer Day-7 players per 10,000 installs, {c} CI {per10k(eff_ci[0])} fewer to
{per10k(eff_ci[1])} more), is <b>the part the gate could explain</b>, not an estimate of the gate's effect. It comes
from a {pp(b30['abs_lift'], sign=True)} gap among the {pct(w_reach, 0)} of players with {GATE_LEVEL}+ rounds ({c} CI
{ci_pp(b30['abs_ci_low'], b30['abs_ci_high'])}; {pval(b30['p_value'])}), and players with 15&ndash;{GATE_LEVEL - 1}
rounds, who never met a gate, show a similar gap ({pp(b1529['abs_lift'], sign=True)}, {c} CI
{ci_pp(b1529['abs_ci_low'], b1529['abs_ci_high'])}), so even this part may not be the gate.</p>
{dec_table}
{self.fig("gate_decomposition", "light grey bars are the parts of the naive gap that cannot be the gate (imbalance or "
          f"chance); the blue bar, with its {c} CI, is the part the gate could explain, not an estimate of its effect. "
          "The three lower bars add up to the naive gap at the top.")}
<p><b>Best case for gate_40.</b> Even if every one of the &asymp;{num(bc['excess_players_gate_40'])} extra installs
never returned, the D7 gap would still be {pp(bc['d7_diff_if_excess_removed'], sign=True)} ({c} CI
{ci_pp(*bc['ci'])}; {pval(bc['p_value'])}). Its interval includes 0, and it shows no retention benefit for gate_40
either.</p>
<p class="note">Method: within-group differences are weighted by the two arms' average share of players in the group;
the player-mix term is the difference in shares times the group's average D7 rate, so the terms add up exactly. The
decomposition is descriptive and uses the same unbalanced data.</p>
{_callout("info", "Why splitting by rounds is allowed here when splitting by total ads was not",
    "Ads can change how long a user stays from the first impression, so the number of ads a user saw can itself be "
    "caused by the treatment; that is why Section 5 treats it as exploratory. Below level "
    f"{GATE_LEVEL} both game versions are identical and rounds &ge; levels, so whether a player ever plays "
    f"{GATE_LEVEL} rounds cannot depend on the gate: it behaves like a trait fixed before treatment. It is an "
    f"approximation: a gate_{GATE_LEVEL} player who cleared every level at the first attempt could meet the gate "
    f"after {GATE_LEVEL - 1} rounds. Such players are few: there is no pile-up at {GATE_LEVEL - 1} rounds "
    f"({num(b29['n_t'])} vs {num(b29['n_c'])} players in gate_40 vs gate_{GATE_LEVEL}), and excluding "
    f"{GATE_LEVEL - 1}-round players, the 15&ndash;{GATE_LEVEL - 2} band still shows "
    f"{pp(b1528['abs_lift'], sign=True)} ({c} CI {ci_pp(b1528['abs_ci_low'], b1528['abs_ci_high'])}). The strata are "
    f"close to, not exactly, gate-free.")}
<h3>6.5 Guardrails, read among players who could meet the gate</h3>
{_ul([
    f"<b>D1 retention:</b> the naive {pp(g1['abs_lift'], sign=True)} ({c} CI "
    f"{ci_pp(g1['abs_ci_low'], g1['abs_ci_high'])}; {pval(g1['p_value'])}) carries the same imbalance (player mix "
    f"{pp(dec1['composition'], sign=True)}). The part of the D1 gap the gate could explain is "
    f"{pp(eff1, sign=True)} per install ({c} CI {ci_pp(*eff1_ci)}): no sign of a D1 effect. It comes from players "
    f"with {GATE_LEVEL}+ rounds, a diluted group for D1: the gate can change Day 1 only for players who reached level "
    f"{GATE_LEVEL} on the install day, and the data cannot single them out.",
    f"<b>Rounds played in the first 14 days:</b> the all-player mean difference "
    f"({_signed(rounds['mean_diff'], 2)} rounds, bootstrap {c} CI {_signed(rounds['mean_diff_boot_ci'][0], 1)} to "
    f"{_signed(rounds['mean_diff_boot_ci'][1], 1)}; medians {num(rounds['median_t'])} vs "
    f"{num(rounds['median_c'])}) carries the same imbalance and is not a clean guardrail. Among players with "
    f"{GATE_LEVEL}+ rounds, gate_40 players play a little more: median {num(rr['median_t'])} vs "
    f"{num(rr['median_c'])} rounds (Mann&ndash;Whitney {pval(rr['mannwhitney_p'])}), and "
    f"{pct(past40['rate_t'])} vs {pct(past40['rate_c'])} go past 40 rounds "
    f"({pp(past40['abs_lift'], 1, sign=True)}, {c} CI {ci_pp(past40['abs_ci_low'], past40['abs_ci_high'], 1, sign=True)}). "
    f"The mean difference ({_signed(rr['mean_diff'], 1)} rounds, bootstrap {c} CI "
    f"{_signed(rr['mean_diff_boot_ci'][0], 1)} to {_signed(rr['mean_diff_boot_ci'][1], 1)}) is too noisy to read. So "
    f"the later gate does buy some extra play, but these players' D7 is not higher "
    f"({pp(b30['abs_lift'], sign=True)}, {c} CI {ci_pp(b30['abs_ci_low'], b30['abs_ci_high'])}): no sign of a "
    f"retention benefit.",
])}
<h3>6.6 Power and what a re-test would take</h3>
<p>The MDE (D7 {pp(g7['mde']['mde_abs'])}, D1 {pp(g1['mde']['mde_abs'])} at {self.power * 100:.0f}% power, with about
{num(min(srm['n_t'], srm['n_c']) / 1000)}K players per arm) describes the design; the part the gate could explain is
read off its own interval ({ci_pp(*eff_ci)} per install), never compared with the MDE.</p>
<p>A re-test is sized at a change fixed in advance, never at the observed effect. Pre-register the smallest D7 change
worth acting on: <b>{pp(rt['smallest_d7_change_per_install'], 1)} per install</b>, a placeholder in
<code>config.yaml</code> to agree with the Game PM (&asymp;{pct(rt['smallest_d7_change_per_install'] / rt['baseline_d7_install'], 1)}
of gate_{GATE_LEVEL}'s {pct(rt['baseline_d7_install'])}). With the primary analysis among players who reach level
{GATE_LEVEL}, pre-registered (membership is settled before the gate), that change is
{pp(rt['equivalent_change_among_reachers'])} among them on a {pct(rt['baseline_d7_reachers'])} base and needs
&asymp;{kn(rt['reachers_needed_5050'])} such players, &asymp;{kn(rt['installs_needed_reacher_analysis_5050'])} installs
at 50/50. Analysed over all installs it needs &asymp;{kn(rt['installs_needed_install_level_5050'])}. Both are sized to
detect a {pp(rt['smallest_d7_change_per_install'], 1)} drop; a rise of the same size needs a little more
(&asymp;{kn(rt['installs_needed_install_level_5050_if_rise'])} install-level, &asymp;{pct(rise_inst, 0)} more;
&asymp;{rt['installs_needed_reacher_analysis_5050_if_rise'] / 1000:,.1f}K for the reacher analysis,
&asymp;{pct(rise_reach, 1)} more). The reacher figure uses this cohort's {pct(rt['share_reached_30'])} reaching level
{GATE_LEVEL}; re-check with the new cohort's share before launch. Add a daily 50/50 group-size check. If the true
effect is smaller than {pp(rt['smallest_d7_change_per_install'], 1)}, it would not change the decision. A re-test only
makes sense if the gate position matters commercially.</p>
<div class="decision" id="s6-decision"><div class="decision-label">Decision</div>
<p><b>Keep the gate at level {GATE_LEVEL}; do not ship gate_40 (R5).</b> Keeping gate_{GATE_LEVEL} is the status quo.
There is no sign of a retention benefit, and the part of the gap the gate could explain is about
{pp(eff, 1, sign=True)} per install (&asymp;{per10k(eff)} fewer Day-7 players per 10,000 installs; {c} CI from
{per10k(eff_ci[0])} fewer to {per10k(eff_ci[1])} more), possibly zero. The result is <b>not certified</b>: quoting the
naive {pp(dec['naive_diff'], sign=True)} would overstate the effect. gate_40 does let players who reach level
{GATE_LEVEL} play a little more (median {num(rr['median_t'])} vs {num(rr['median_c'])} rounds), so if the Game PM
values that, a clean re-test is the way to decide. Fix assignment and logging first (gate_40 received
&asymp;{num(self.excess_clean)} extra installs, with a net excess of {num(lt15)} among players with &lt; 15 rounds), and
read any re-test only after it passes the daily 50/50 group-size check.</p></div>
</section>"""

    # ------------------------------------------------------------------ 7 decision
    def s7_decision(self) -> str:
        t, c, pw, bz = self.t, self.conf, self.pw, self.bz
        hd, hh, hp = self.het["most_ads_day"], self.het["most_ads_hour"], self.het["daypart"]
        g7, srm, dec = self.g7, self.gate["srm"], self.dec
        hold, ses, early = bz["always_on_holdout_cost"], self.ses, self.early
        n10 = pw["total_n_for_10pct_rel_lift"]
        nc7 = self.gate["negative_control"]["never_reached_30"]["retention_7"]
        eff_ci = dec["install_level_effect_ci_if_only_reachers"]
        rows = [
            ["Did the campaign drive conversions?", _chip("good", f"Keep + {pct(hold['share'], 0)} holdout"),
             f"{pp(t['abs_lift'], sign=True)} ({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}); "
             f"{pct(bz['share_of_ad_conversions_incremental'], 0)} of ad-arm conversions incremental; exposure matches "
             "on average", "High", "R1"],
            ["Double the budget?", _chip("warn", "Test first"),
             "Budget was never varied; the lift lives in heavy users (exploratory, post-assignment)",
             "Not answerable from this data", "R2"],
            ["Re-time spend by day / hour?", _chip("stop", "Don't (yet)"),
             f"Day {pval(hd['lrt']['p_value'])} ({pval(hd['lrt_p_bonferroni_3_dims'], prefix=False)} allowing for "
             f"{self.het['n_dimensions_explored']} dimensions; a user habit, not a slot we buy); hour "
             f"{pval(hh['lrt']['p_value'])}; daypart without night {pval(hp['lrt_excluding_night']['p_value'])}",
             "Low", "R3"],
            ["How should the next test be designed?", _chip("info", "Fix design"),
             f"{self.split} had {power_pct(ses['power_current_split'])} power for a {pct(ses['rel'], 0)} lift (50/50: "
             f"{power_pct(ses['power_5050_same_total'])}); the split lands on exactly {self.split} (most likely a fixed "
             "quota), so the SRM check was uninformative; no timestamps; no guardrails",
             "&ndash;", "R4"],
            [f"Move the gate from level {GATE_LEVEL} to 40?", _chip("stop", "Don't ship"),
             f"Naive D7 {pp(g7['abs_lift'], sign=True)}, not certified: sample-ratio {esc(srm['status'])} and a "
             f"borderline negative control ({pp(nc7['abs_lift'], sign=True)}); the part the gate could explain is "
             f"{pp(dec['within_reached_30'], sign=True)} per install ({c} CI {ci_pp(*eff_ci)}); no sign of a retention "
             "benefit", "Not certified; the gate's part may be zero", "R5"],
            ["Which new users leave first?", _chip("info", "Act"),
             f"{pct(early['share_of_installs'], 0)} of installs play fewer than {self.low_cut} rounds and only "
             f"{pct(early['retention_7'])} of them are back on Day 7; Day-1 returners "
             f"{self.d7_yes / self.d7_no:.1f}&times; as likely to play on Day 7",
             "Association: validate by experiment", "R6"],
        ]
        table = _table(["Question", "Decision", "Evidence", "Confidence", "See"], rows, stack=True)
        return f"""
<section id="s7">
<h2><span class="sec-num">7</span>Decision and recommendations</h2>
<p class="lede">What should we do, who owns it, and how will we know it worked?</p>
{table}
<p>Owners, expected impact, measurement and main risk for R1&ndash;R6 are in the
<a href="#recommendations">recommendations table</a> at the top.</p>
<h3>How we will know it worked</h3>
{_ul([
    f"<b>Always-on holdout (R1):</b> {pct(hold['share'], 0)} of users keep seeing PSAs; incremental conversions and "
    "cost per incremental conversion vs. the holdout, per flight and at least quarterly, show whether the effect holds "
    "or fades. One flight's read is about as precise as this test, so trends are judged over several flights.",
    "<b>Finance check (R1):</b> the real value per conversion and actual CPM replace the placeholder; the campaign "
    "stays only while the actual CPM is below breakeven.",
    "<b>Impressions / frequency test (R2):</b> the go / no-go for scaling is the marginal incremental conversions per "
    "extra USD 1K, not the average.",
    "<b>Timing (R3):</b> any re-timing waits for a pre-registered test that randomizes the delivery schedule (weekday "
    "and time slot).",
    "<b>Gate (R5):</b> Engineering closes the assignment investigation with a named cause; any re-test passes the "
    "50/50 group-size check before its result is read.",
    "<b>Onboarding (R6):</b> a randomized Day-1 re-engagement test with D7 among targeted players as the primary "
    "metric decides whether the change ships.",
])}
<h3>Next experiment at a glance (R2 + R4)</h3>
{_ul([
    "<b>Question:</b> what does extra spend buy?",
    "<b>Arms:</b> a user-level test where one arm gets up to 2&times; today's impressions per user (the closest "
    "stand-in for 2&times; budget) or a frequency cap, vs. the current plan, plus the small PSA holdout to keep "
    "measuring the absolute lift. A true budget test needs a geo split.",
    "<b>Split:</b> 50/50 or 80/20 between the arms, with users tiered by activity measured <i>before</i> the test; an "
    "automatic daily SRM check while it runs.",
    "<b>Metrics:</b> primary = incremental conversions per extra USD 1K spent (marginal iROAS); secondary = conversion "
    "rate; guardrails = unsubscribe / complaint rate, cost per acquisition, ads per user.",
    f"<b>Size:</b> use the sample-size calculator on the dashboard's Decision page (<code>/decision</code>). The "
    f"2&times;-vs-1&times; difference will be smaller than ad-vs-PSA, so expect to need more than the "
    f"&asymp;{kn(n10['0.5'])} users (50/50) that a {pct(ses['rel'], 0)} ad-vs-PSA lift on a {pct(t['rate_c'], 2)} base "
    f"needs (&asymp;{kn(n10['0.8'])} at 80/20, &asymp;{kn(n10['0.96'])} at {self.split}).",
    "<b>Duration and logging:</b> whole weeks, with assignment timestamps so novelty effects can be checked, and the "
    "allocation config archived with the readout.",
])}
</section>"""

    # ------------------------------------------------------------------ 8 limitations
    def s8_limits(self) -> str:
        hd = self.het["most_ads_day"]
        return f"""
<section id="s8">
<h2><span class="sec-num">8</span>Limitations and what data I would ask for next</h2>
<h3>Limitations</h3>
{_ul([
    "<b>No timestamps</b> in either dataset: no novelty-effect, duration or seasonality analysis, and the game data is "
    "a single install cohort without install dates.",
    f"<b>No revenue or cost:</b> every money figure rests on an illustrative {usd(self.value, 0)} per conversion and "
    "an unknown CPM.",
    f"<b>Ad split on an exact quota:</b> the {self.split} split is most likely a fixed quota, so its SRM test passes "
    "by construction and cannot detect assignment problems; exposure parity carries the weight, and it holds only "
    "approximately (the shapes differ a little).",
    "<b>Post-assignment variables:</b> total ads, peak day and peak hour describe what happened after assignment; all "
    "segment and exposure results are exploratory, and the exposure pattern is not a frequency curve.",
    f"<b>Several dimensions explored:</b> the day interaction ({pval(hd['lrt']['p_value'])}) stays below 0.05 after "
    f"allowing for the {self.het['n_dimensions_explored']} dimensions explored "
    f"({pval(hd['lrt_p_bonferroni_3_dims'], prefix=False)}), but peak day is a user habit recorded after assignment, so "
    "the day pattern is a hypothesis for a randomized test, not a finding to act on.",
    "<b>Unknown conversion definition</b> and attribution window.",
    "<b>One flight at one budget:</b> nothing in this test varies spend, so a 2&times; budget is an extrapolation.",
    f"<b>Gate experiment not certified:</b> a sample-ratio WARNING, with the net excess of gate_40 installs among "
    f"low-engagement players, and a borderline negative control. The decomposition is descriptive; its "
    f"{GATE_LEVEL}+ part is the part the gate could explain, not an estimate of the gate's effect, and "
    f"&ldquo;{GATE_LEVEL}+ rounds&rdquo; stands for &ldquo;could have reached level {GATE_LEVEL}&rdquo; (there is no "
    "level field).",
    "<b>Rounds overlap the D7 window:</b> rounds are counted through day 14, so the rounds&ndash;retention link is "
    "partly definitional and cannot be used for Day-0 targeting.",
    f"<b>Retention flags:</b> {num(self.zero_d1)} players with zero rounds are flagged as back on Day 1, so the flags "
    "mean &ldquo;came back to the game&rdquo;; too few to change any conclusion.",
    "<b>Very large samples:</b> tiny differences become &ldquo;significant&rdquo;, so effect sizes (pp, Cram&eacute;r's "
    "V) are reported next to every p-value.",
    "<b>Two different products:</b> the ads ran in the company's app and the retention data comes from its mobile "
    "game, with no shared users, so ad conversion and retention cannot be linked and the game's segment sizes will not "
    "transfer one-for-one to the app. Both are public datasets used as the company's data in this role-play.",
])}
<h3>What data I would ask for next</h3>
{_ul([
    "<b>Assignment log and allocation config</b>: user, arm, assignment timestamp, randomization unit and the intended "
    "split (makes the sample-ratio check meaningful; enables novelty and duration analysis).",
    "<b>Impression-level exposure log</b> with timestamps, placement and cost (real frequency analysis, actual CPM, "
    "cost per incremental conversion).",
    "<b>Revenue or margin per conversion</b> (or LTV) from Finance.",
    "<b>The conversion event definition</b> and attribution window.",
    "<b>Guardrail events</b>: unsubscribes, ad hides / complaints, uninstalls.",
    "<b>Pre-assignment covariates</b> (prior activity, platform, country, acquisition channel) for balance checks and "
    "variance reduction (CUPED).",
    "<b>For the game</b>: install dates, platform, country and app version (to explain gate_40's extra installs and "
    "their net excess among players with fewer than 15 rounds), level-progress and session events (where exactly "
    "players stop), and the assignment-service logs.",
])}
</section>"""

    # ------------------------------------------------------------------ appendix
    def appendix(self) -> str:
        t, c, a = self.t, self.conf, self.alpha
        pw, bz = self.pw, self.bz
        ses = pw["power_at_relative_lift"][str(pw["smallest_lift_of_interest_rel"])]
        v_mid = sum(b["cramers_v"] for b in self.ad["balance"]) / len(self.ad["balance"])
        n_hours = self.het["most_ads_hour"]["n_segments"]
        gloss = [
            ("Percentage points (pp) vs percent",
             f"Conversion went from {pct(t['rate_c'], 2)} to {pct(t['rate_t'], 2)}. The difference is "
             f"{pp(t['abs_lift'])} (percentage points, an absolute change); relative to the control rate it is "
             f"{spct(t['rel_lift'])} (a relative change). Both are correct; pp is what drives counts."),
            ("Confidence interval (CI)",
             f"The range of effect sizes that are consistent with the data. &ldquo;{pp(t['abs_lift'], sign=True)} "
             f"({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])})&rdquo; means we are {c} confident the true lift is "
             "in that range. If the interval excludes 0, the result is statistically significant. Read the interval, "
             "not just the point estimate: its low end is the cautious planning number."),
            ("p-value",
             "How surprising the observed difference would be if there were truly no effect. Small p (below "
             f"&alpha; = {a:g}) means &ldquo;unlikely to be chance&rdquo;. It says nothing about how big or important "
             "the effect is; with very large samples, tiny differences get tiny p-values. A p-value is never 0: very "
             "small ones are shown as &ldquo;p &lt; 0.0001&rdquo;."),
            ("Sample ratio mismatch (SRM)",
             "A check that each arm received the share of users it was supposed to. If a 50/50 test ends up noticeably "
             f"uneven, something in assignment or logging is broken and the arms may not be comparable. This project "
             f"uses two levels: p &lt; {self.srm_fail:g} = FAIL (stop), p &lt; {self.srm_warn:g} = WARNING (do not "
             "certify; investigate). A split that lands exactly on the target, as in the ad test, most likely means a "
             "fixed quota: the check then passes by construction and tells us nothing. Fixed arm sizes are a valid "
             "design; they just make this check uninformative."),
            ("Exposure parity",
             "In an ad-vs-PSA test both arms fill the same ad slots, so the number of slots served per user should "
             "match between arms. It is the more useful integrity check when the split itself is fixed by a quota."),
            ("Bootstrap",
             f"Re-running the experiment {num(self.n_boot)} times on computer-generated resamples of the data and "
             "looking at the spread of results. It gives a confidence interval without assuming a bell curve, and a "
             "plain-language summary such as &ldquo;none of the resamples showed a lift &le; 0&rdquo;. It earns its "
             "keep on skewed metrics such as rounds played."),
            ("Power and minimum detectable effect (MDE)",
             f"Power is the chance a test detects an effect of a given size if it is real (the standard is "
             f"{self.power * 100:.0f}%). The MDE is the smallest effect a design detects at that power. Power is a "
             f"property of the design and is judged at the smallest lift worth acting on (here "
             f"{pct(ses['rel'], 0)} relative = {pp(ses['abs'])}: {power_pct(ses['power_current_split'])} at "
             f"{self.split}, {power_pct(ses['power_5050_same_total'])} at 50/50), never at the observed effect, where "
             "it only restates the p-value. For the same reason an MDE is never compared with an estimate: an "
             "estimate is read off its own confidence interval."),
            ("Interaction test (likelihood-ratio test)",
             f"One test of whether the treatment effect differs across the segments of a dimension (e.g. the "
             f"{self.het['most_ads_day']['n_segments']} days), instead of comparing segments pairwise. It compares a "
             "model where the lift is the same everywhere with one where each segment has its own lift."),
            ("Segment-vs-rest contrast",
             "A segment's lift minus the lift in all other segments of the same dimension, in percentage points, with "
             "its own CI and p-value. It answers &ldquo;is this segment different?&rdquo;, unlike a test of the "
             "segment's lift against 0, which answers &ldquo;is there a lift here?&rdquo;. The point estimate is the "
             "raw difference; the CI and p-value add one success and one failure per group (Agresti&ndash;Caffo), so "
             "in sparse cells the interval is not centred on the point."),
            ("Multiple comparisons (Bonferroni, Holm, Benjamini&ndash;Hochberg)",
             f"Running many tests at &alpha; = {a:g} produces about one false &ldquo;hit&rdquo; per {1 / a:.0f} tests "
             f"by chance; with {n_hours} hourly contrasts that is about {n_hours * a:.1f}. Bonferroni and Holm raise "
             "the bar so that the "
             "chance of <i>any</i> false hit stays at &alpha; (Holm is the less strict of the two); "
             "Benjamini&ndash;Hochberg controls the <i>share</i> of false hits among the results."),
            ("Stratified (Mantel&ndash;Haenszel) sensitivity check",
             "The lift computed within each segment and then averaged with fixed weights. If it matches the simple "
             "overall lift, the result is not an artefact of how users are spread across segments. A sensitivity "
             "check, not a replacement for the randomized comparison."),
            ("Post-assignment variable",
             "Something measured after users were randomized (here: number of ads seen, peak ad day and hour). Because "
             "the treatment can influence it, comparing arms within its segments no longer compares like with like; "
             "such cuts are exploratory and must not be used as controls."),
            ("Negative control",
             f"A group in which the treatment cannot have had an effect, here players with fewer than {GATE_LEVEL} "
             "rounds, who never met a gate. If the arms still differ there, the difference comes from who is in each "
             "arm or from chance, not from the treatment."),
            ("Incremental conversions, last-touch attribution and holdouts",
             f"Incremental conversions are those that would not have happened without the ads (lift &times; users who "
             f"saw ads). Last-touch (here also any-touch) attribution credits every conversion of an exposed user to "
             f"the ads, here {times(bz['last_touch_overstatement_x'])} too many ({self.conf} CI {self.lt[0]:.1f}"
             f"{NDASH}{times(self.lt[1])}). An always-on holdout is a small randomized group that keeps seeing PSAs, so "
             "the incremental effect can be measured continuously."),
            ("Breakeven CPM",
             "The highest price per 1,000 impressions at which the value of the incremental conversions still covers "
             "the ad cost."),
            ("Novelty effect",
             "Users react to something new more strongly at first, and the effect fades as they get used to it. "
             "Spotting it needs dates; without them, the measured lift is an average over the whole test."),
            ("Cram&eacute;r's V",
             "An effect size for differences in a categorical distribution, from 0 (identical) to 1 (completely "
             f"different). Values around {v_mid:.2f}, as in the balance checks here, are negligible even when the "
             "p-value is tiny."),
        ]
        dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in gloss)
        found = sorted(NOTEBOOK_DIR.glob("[0-9][0-9]_*.html"))
        nbs = [(p.stem, NOTEBOOKS.get(p.stem, p.stem.replace("_", " "))) for p in found] or list(NOTEBOOKS.items())
        nb_list = _ul([f'<a href="notebooks/{esc(s)}.html">{esc(s)}.html</a> &mdash; {esc(title)}' for s, title in nbs])
        docs = [f'<a href="../docs/{esc(n)}">docs/{esc(n)}</a> &mdash; {esc(title)}'
                for n, title in DOCS.items() if (DOCS_DIR / n).exists()]
        docs_html = f"<p>Supporting documents in the repository:</p>{_ul(docs)}" if docs else ""
        extra = [k for k in self.cat if k not in self.placed]
        extra_html = ("<h3>Other charts</h3>" + "".join(self.fig(k) for k in extra)) if extra else ""
        cfg = self.res["config"]
        return f"""
<section id="appendix">
<h2><span class="sec-num">A</span>Appendix</h2>
<h3>Methods in plain English</h3>
<dl class="glossary">{dl}</dl>
<h3>Notebooks</h3>
<p>The step-by-step analysis, exported to HTML in the <code>notebooks/</code> folder next to this report
(<code>reports/notebooks/</code> in the repository):</p>
{nb_list}
{docs_html}
<h3>Reproducibility</h3>
<p>Every number in this report is read from <code>reports/results.json</code> when the report is built, or computed
from the processed caches with the project's own functions, and every chart comes from <code>src/catalog.py</code>, the
same figures the Streamlit dashboard shows by default (<code>streamlit run dashboard/app.py</code>). The key numbers are
also recomputed independently in SQL (DuckDB, <code>sql/</code>); every SQL-reproduced number matches
<code>results.json</code> (<code>reports/tables/sql_reconciliation.csv</code>). Rebuild everything
with <code>python run.py</code> (this report alone: <code>python run.py --only report</code>). Seed {cfg['seed']},
{num(cfg['n_bootstrap'])} bootstrap resamples for proportions and {num(cfg['n_bootstrap_means'])} for means,
&alpha; = {cfg['alpha']:g}, power = {cfg['power']:g}; placeholder thresholds in <code>config.yaml</code>: smallest
ad lift of interest {pct(cfg['smallest_lift_of_interest_rel'], 0)} relative, smallest gate D7 change
{pp(cfg['gate_smallest_d7_change'], 1)} per install, R6 target lift {pp(cfg['onboarding_target_lift'], 1, sign=True)}
of D7. The interactive charts are embedded with plotly.js, so the file works offline.</p>
{extra_html}
</section>"""

    # ------------------------------------------------------------------ page
    def toc(self, cls: str) -> str:
        items = [("summary", "Summary"), ("answers", "Answers for the PM"), ("recommendations", "Recommendations"),
                 ("s1", "1&nbsp; Business question and scope"), ("s2", "2&nbsp; Data quality and integrity"),
                 ("s3", "3&nbsp; Retention analysis"), ("s4", "4&nbsp; Ad experiment readout"),
                 ("s5", "5&nbsp; Heterogeneity"), ("s6", "6&nbsp; Gate experiment"),
                 ("s7", "7&nbsp; Decision and recommendations"), ("s8", "8&nbsp; Limitations and data asks"),
                 ("appendix", "Appendix: methods, notebooks")]
        lis = "".join(f'<li><a href="#{i}">{label}</a></li>' for i, label in items)
        return f'<nav class="toc {cls}" aria-label="Contents"><div class="toc-title">Contents</div><ol>{lis}</ol></nav>'

    def html(self) -> str:
        body = "".join([self.answers(), self.recs_section(), self.s1_scope(), self.s2_data(), self.s3_retention(),
                        self.s4_ad(), self.s5_heterogeneity(), self.s6_gate(), self.s7_decision(), self.s8_limits(),
                        self.appendix()])
        header = self.header()
        cfg = self.res["config"]
        footer = (f'<footer><p>Generated {self.today} by <code>src/report.py</code> from <code>reports/results.json</code> '
                  f'&middot; seed {cfg["seed"]} &middot; {len(self.placed)} charts &middot; '
                  f'<a href="#top">Back to top</a></p></footer>')
        t = self.t
        description = (f"Ad vs PSA experiment ({pp(t['abs_lift'], sign=True)} conversion), new-player retention and "
                       f"gate_30 vs gate_40 readout for the Growth PM.")
        css = CSS
        for token, value in {"__INK__": F.INK, "__INK2__": F.INK_2, "__GRID__": F.GRID, "__BLUE__": F.BLUE,
                             "__GREY__": F.GREY, "__ORANGE__": F.ORANGE, "__FONT__": F.FONT}.items():
            css = css.replace(token, value)
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Growth Experiment Readout</title>
<meta name="description" content="{esc(description)}">
<style>{css}</style>
<script>window.PlotlyConfig = {{MathJaxConfig: 'local'}};</script>
<script>{get_plotlyjs()}</script>
</head>
<body>
<div class="shell">
{self.toc("toc-side")}
<div class="page">
{header}
{self.toc("toc-inline")}
<main>{body}</main>
{footer}
</div>
</div>
<script>{APP_JS}</script>
</body>
</html>
"""

    # ------------------------------------------------------------------ executive summary (Markdown)
    def summary_md(self) -> str:
        t, bz, o, c = self.t, self.bz, self.ck["overall"], self.conf
        inc, be, hold = bz["incremental_conversions"], bz["breakeven_cpm_usd"], bz["always_on_holdout_cost"]
        g7, dec, con, early, rt, rr = self.g7, self.dec, self.con, self.early, self.rt, self.rr
        pw, ses = self.pw, self.ses
        n10 = pw["total_n_for_10pct_rel_lift"]
        eff, eff_ci = dec["within_reached_30"], dec["install_level_effect_ci_if_only_reachers"]
        le20 = con["le_20_ads_pooled"]
        sizing = early["onboarding_test_sizing"]
        share_inc = bz["share_of_ad_conversions_incremental"]
        heavy = self.heavy_range.replace(NDASH, " to ")

        def p100(x: float, nd: int = 2) -> str:   # proportion difference -> "0.77" (per 100 people)
            return _plain(x * 100, nd)

        def users(n: float) -> str:               # 181,074 -> "181,000"; 1,178,866 -> "1.2 million"
            return f"{n / 1e6:.1f} million" if n >= 1e6 else approx(n, 1000)

        recs = [
            ("R1", "Growth PM",
             f"Keep the campaign at today's budget; keep {pct(hold['share'], 0)} of users seeing public-service ads "
             "instead, as an always-on comparison group.",
             f"About {approx(inc['point'], 100)} extra conversions per comparable flight (likely "
             f"{approx(inc['ci_low'], 100)} to {approx(inc['ci_high'], 100)}). The comparison group gives up about "
             f"{approx(hold['conversions_forgone'], 1)} conversions per {approx(self.n_total, 1000)} users (about "
             f"{usd(round(hold['value_forgone_usd'], -2), 0)} at {usd(self.value, 0)} each) versus having none; this "
             f"test's {pct(hold['as_run_control_share'], 0)} group already gave up about "
             f"{approx(hold['as_run_control_conversions_forgone'], 1)}. It keeps the real effect in view: crediting the "
             f"ads with every conversion would overstate them {bz['last_touch_overstatement_x']:.1f} times.",
             "Extra conversions and cost per extra conversion against the comparison group, per flight, and at least "
             "quarterly.",
             f"The value of a conversion and our price per 1,000 impressions are unknown: Finance confirms we pay less "
             f"than {usd(be['point'])} ({usd(be['ci_low'])} at the cautious end). One flight's reading is about as "
             "precise as this test, so judge trends over several flights."),
            ("R2", "Growth PM + media buyer",
             "Don't double blindly; test it: randomly give part of the audience up to twice today's ads per person "
             "(the closest stand-in for twice the budget), or a cap on how often they see ads. A true budget test "
             "needs a split by region.",
             f"Learn what extra spend buys before committing about twice the money. Today's effect sits with the "
             f"{pct(con['share_ad_users_36_200'], 0)} of ad viewers who saw {heavy} ads, so the average return may "
             "not hold at twice the spend.",
             "Extra conversions per additional USD 1,000 spent.",
             f"The difference between twice today's ads and today's will be smaller than between the campaign and "
             f"public-service ads, so the test will need more than the {users(n10['0.5'])} users (50/50) that a "
             f"{pct(ses['rel'], 0)} lift needs; heavy users may tire of more ads."),
            ("R3", "Media buyer",
             "Don't re-plan spend by day or hour. If timing matters, run a planned test that randomly assigns the "
             "delivery schedule (weekday and time slot, e.g. Tuesday vs Thursday delivery).",
             "Avoids moving money on a pattern that describes users' habits, not time slots we buy.",
             "The difference in lift between the randomly assigned delivery slots, with its likely range.",
             "Missing a small real timing effect."),
            ("R4", "Analytics + Engineering",
             f"Next ad test: a 50/50 or 80/20 split instead of {self.split}, a timestamp for when each user entered "
             "the test, the main metric, smallest worthwhile lift and safety metrics agreed up front, and an automatic "
             "daily check that the groups stay at their planned sizes.",
             f"A {pct(ses['rel'], 0)} improvement becomes detectable with about {users(n10['0.5'])} users instead of "
             f"{users(n10['0.96'])}; the same users split 50/50 would have been almost certain "
             f"({power_pct(ses['power_5050_same_total'])}) to catch it, against a coin flip "
             f"({power_pct(ses['power_current_split'])}) in the last test. Timestamps show whether the effect fades.",
             f"The test's chance of catching a {pct(ses['rel'], 0)} lift is checked before launch; the daily "
             "group-size check runs throughout.",
             "A bigger comparison group means more users miss the ads during the test; logging work for Engineering."),
            ("R5", "Game PM (Engineering + Analytics fix assignment)",
             f"Keep the gate at level {GATE_LEVEL}. Fix how players are assigned and logged first, and re-test only "
             f"if the gate's position matters commercially.",
             f"Avoids a change with no sign of a retention benefit. The part of the day-7 gap the gate could explain "
             f"is about {p100(abs(eff), 1)} points per install (about {per10k(eff)} fewer day-7 players per 10,000 "
             f"installs, possibly none). Level 40 does let players who reach level {GATE_LEVEL} play a little more.",
             f"Any re-test: agree the smallest day-7 change worth acting on in advance (we suggest "
             f"{p100(rt['smallest_d7_change_per_install'], 1)} points per install, about "
             f"{pct(rt['smallest_d7_change_per_install'] / rt['baseline_d7_install'], 1)} of today's "
             f"{pct(rt['baseline_d7_install'])}); about {users(rt['installs_needed_reacher_analysis_5050'])} installs "
             f"at 50/50 with the main analysis among players who reach level {GATE_LEVEL} (about "
             f"{users(rt['reachers_needed_5050'])} of them), about {users(rt['installs_needed_install_level_5050'])} "
             "over all installs; a daily check that the groups stay 50/50. Engineering closes the assignment "
             "investigation with a named cause before any re-test is read.",
             f"Quoting the raw {p100(abs(dec['naive_diff']))}-point gap would overstate the effect; a small real effect "
             "could be missed either way."),
            ("R6", "Onboarding PM (with CRM)",
             "Test a Day-1 comeback message for new players who play little on their first day, with day-7 retention "
             "deciding.",
             f"Targets the biggest drop: {pct(1 - o['retention_1'])} of new players don't come back on Day 1. At most "
             f"about {_plain(self.d1_ceiling, 2)} points of day-7 retention for every 1 point of installs brought back "
             "on Day 1 (a ceiling, not a forecast).",
             f"Day-7 retention among the targeted players in a randomized test (Day 1 as a secondary check); about "
             f"{users(sizing['players_needed_5050'])} target players (about {users(sizing['installs_needed_5050'])} "
             f"installs) to detect {_signed(sizing['target_lift_abs'] * 100, 1)} points on their "
             f"{pct(early['retention_7'])} base.",
             "Rounds in this data are counted over 14 days, so the real targeting rule must use first-day play; the "
             "link between play and retention may not be causal; message fatigue."),
        ]
        table = "\n".join(f"| {i} | {own} | {what} | {imp} | {know} | {risk} |"
                          for i, own, what, imp, know, risk in recs)

        md = f"""# Executive summary: ad campaign and new-player retention

**To:** Growth PM · **From:** Product Analyst, Growth · **Date:** {self.today}

Full analysis: [report.html](report.html) (opens in any browser, works offline). Interactive version: `streamlit run dashboard/app.py`.

## Bottom line

**Keep the ad campaign running at today's budget, keep a small group of users as an always-on comparison, and test more ads per person before doubling the budget.** The campaign clearly brought in extra conversions, but this test never tried a higher budget, so it can't tell us whether more spend would pay off. **Keep the game's first gate at level {GATE_LEVEL}**: the test of level 40 showed no sign of a retention benefit, and a setup problem means we can't yet say whether it does any harm. **Focus retention work on bringing new players back the day after they install**, which is where most of them are lost.

## What we found

1. **The campaign worked.** {pct(t['rate_t'], 2)} of people who saw the ads converted, vs {pct(t['rate_c'], 2)} of a similar group shown a public-service ad instead: {p100(t['abs_lift'])} more conversions per 100 people ({pp(t['abs_lift'], sign=True)}, or {spct(t['rel_lift'])}). We're {c} confident the true increase is between {p100(t['abs_ci_low'])} and {p100(t['abs_ci_high'])} per 100 people. That is roughly {approx(inc['point'], 100)} extra conversions (likely {approx(inc['ci_low'], 100)} to {approx(inc['ci_high'], 100)}) from {bz['impressions_ad_group'] / 1e6:.1f} million ad impressions. Only about {pct(share_inc, 0)} of the ad group's conversions were extra; the rest would have happened anyway. Crediting the campaign with every conversion from people who saw an ad (last-touch) would overstate it about {bz['last_touch_overstatement_x']:.1f} times (likely {self.lt[0]:.1f} to {self.lt[1]:.1f} times).
2. **Whether doubling the budget pays off is still unknown.** If a conversion is worth {usd(self.value, 0)} (a placeholder; there is no revenue data), the campaign pays for itself as long as 1,000 ad impressions cost less than about {usd(be['point'])} (likely {usd(be['ci_low'])} to {usd(be['ci_high'])}). The {pct(con['share_users_le_20_ads'], 0)} of users who saw {LOW_EXPOSURE_MAX} ads or fewer show no lift we could measure (the {c} range runs from {ci_pp(le20['abs_ci_low'], le20['abs_ci_high'], sign=True)}). Almost all the extra conversions ({pct(con['share_incremental_conversions_36_200'], 0)}, counted bucket by bucket) came from the {pct(con['share_ad_users_36_200'], 0)} of ad viewers who saw {heavy} ads. But the people who see the most ads are also the most active and convert more anyway, so this shows where the effect sits, not what extra spend would buy. Only a proper test can answer that. Moving spend to particular days or hours isn't supported either: the one weekday pattern we found reflects users' habits, not a time slot we can buy.
3. **New players of the game leave early, and the least engaged leave first.** These numbers come from our mobile game (Cookie Cats), the company's other product, so the sizes will not carry over one-for-one to the app. {pct(1 - o['retention_1'])} of new players don't come back the day after installing, and only {pct(o['retention_7'])} play on the seventh day. Almost half ({pct(early['share_of_installs'], 0)}) play fewer than {self.low_cut} rounds in their first two weeks, and only {pct(early['retention_7'])} of them come back on day 7. Players who return on Day 1 are {self.d7_yes / self.d7_no:.1f} times as likely to come back on day 7 ({pct(self.d7_yes)} vs {pct(self.d7_no)}). This shows who leaves, not why.
4. **Moving the first gate to level 40 shows no sign of a retention benefit; whether it does harm is unclear.** The straightforward comparison shows a lower day-7 return rate with the gate at level 40: {pct(g7['rate_t'])} vs {pct(g7['rate_c'])}. But the two groups weren't split evenly: the level-40 group got about {num(self.excess_clean)} extra installs, and the surplus sits among people who played fewer than 15 rounds; even players who played too few rounds to get past the first gate came back slightly less often in that group. About {approx(self.not_gate_share * 100, 10)}% of the gap sits where the gate cannot act. The part the gate itself could explain is about {p100(abs(eff), 1)} percentage points per install (about {per10k(eff)} fewer day-7 players per 10,000 installs), and we're {c} confident it lies between a {p100(abs(eff_ci[0]))}-point drop and a {p100(abs(eff_ci[1]))}-point gain, so it may be zero; even that part may not be the gate. Players who got far enough to meet the gate did play a little more with it at level 40 (median {num(rr['median_t'])} vs {num(rr['median_c'])} rounds).

## What we recommend

| | Owner | Action | Expected impact | How we'll know it worked | Main risk |
|---|---|---|---|---|---|
{table}

## Risks

- **Money figures rest on a placeholder** ({usd(self.value, 0)} per conversion); break-even moves in proportion to the real value.
- **The budget question is open**: the campaign's effect sits with very active users, so extra spend may buy less than the average suggests.
- **No dates in the data**, so we can't see whether the ad effect wears off.
- **Retention patterns are associations**, and part of the link between rounds played and coming back is built in (both are counted over the same two weeks): they show where to test, not guaranteed wins. They come from the game, so the sizes will differ for the app.
- **The gate test's uneven groups** leave its effect unconfirmed; keeping level {GATE_LEVEL} is the safe default regardless.

## Next steps

1. **Finance:** the real value of a conversion and our actual cost per 1,000 impressions (confirms R1).
2. **Growth PM + Engineering:** set up the {pct(hold['share'], 0)} comparison group (R1).
3. **Analytics + media buyer:** design the more-ads-per-person test (R2).
4. **Engineering:** find out why the level-40 group received about {num(self.excess_clean)} extra installs, with the surplus among players who played fewer than 15 rounds (R5).
5. **Onboarding PM + CRM + Analytics:** scope the Day-1 experiment (R6).
"""
        return md


# ====================================================================== assets
CSS = """
:root {
  --bg: #f6f6f3;
  --surface: #ffffff;
  --ink: __INK__;
  --ink-2: __INK2__;
  --ink-3: #6f6e69;
  --rule: __GRID__;
  --rule-2: #d6d5cf;
  --accent: __BLUE__;
  --accent-ink: #1d5fae;
  --accent-soft: #edf4fc;
  --control: __GREY__;
  --second: __ORANGE__;
  --good: #1d6e46;
  --good-bg: #e7f4ec;
  --warn: #7a5000;
  --warn-bg: #fff6de;
  --warn-rule: #e0a000;
  --stop: #9b2f20;
  --stop-bg: #fbece8;
  --muted-bg: #efeee9;
  --radius: 8px;
  --maxw: 980px;
  --font: __FONT__;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.6 var(--font); }
a { color: var(--accent-ink); text-decoration: underline; text-decoration-color: rgba(42, 120, 214, .35);
    text-underline-offset: 2px; }
a:hover { text-decoration-color: currentColor; }
code { font-family: var(--mono); font-size: .86em; background: var(--muted-bg); padding: 1px 5px;
       border-radius: 4px; overflow-wrap: anywhere; }
b, strong { font-weight: 650; }
.shell { max-width: calc(var(--maxw) + 48px); margin: 0 auto; }
.page { padding: 36px 24px 64px; min-width: 0; }
main { min-width: 0; }

/* header */
.masthead { padding-bottom: 8px; }
.eyebrow { font-size: 12.5px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3); }
h1 { font-size: 30px; line-height: 1.2; margin: 6px 0 8px; letter-spacing: -.01em; font-weight: 700; }
.meta { color: var(--ink-2); font-size: 14px; margin: 0 0 18px; }
.bottom-line { background: var(--surface); border: 1px solid var(--rule); border-left: 4px solid var(--accent);
               border-radius: var(--radius); padding: 16px 20px; margin: 0 0 16px; }
.bottom-line p { margin: 0; font-size: 16.5px; line-height: 1.65; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(145px, 100%), 1fr)); gap: 10px; margin: 0 0 12px; }
.kpi { background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 10px 12px; }
.kpi-label { font-size: 12px; color: var(--ink-3); font-weight: 600; letter-spacing: .02em; }
.kpi-value { font-size: 23px; font-weight: 700; line-height: 1.25; margin: 2px 0; font-variant-numeric: tabular-nums;
             white-space: nowrap; }
.kpi-sub { font-size: 12px; color: var(--ink-2); line-height: 1.35; }
.conventions { font-size: 13.5px; color: var(--ink-3); margin: 8px 0 0; }

/* contents */
.toc { background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 12px 18px;
       margin: 20px 0 8px; font-size: 14.5px; }
.toc-title { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3);
             margin-bottom: 4px; }
.toc ol { list-style: none; margin: 0; padding: 0; columns: 2; column-gap: 32px; }
.toc li { break-inside: avoid; }
.toc a { display: block; padding: 3px 0 3px 10px; border-left: 2px solid transparent; color: var(--ink-2);
         text-decoration: none; }
.toc a:hover { color: var(--ink); }
.toc a.active { color: var(--ink); font-weight: 600; border-left-color: var(--accent); }
.toc-side { display: none; }

/* sections */
h2 { font-size: 23px; line-height: 1.3; margin: 56px 0 10px; padding-top: 18px; border-top: 1px solid var(--rule-2);
     letter-spacing: -.005em; }
h3 { font-size: 17.5px; line-height: 1.35; margin: 30px 0 8px; }
section, h3, .decision { scroll-margin-top: 16px; }
.sec-num { display: inline-block; min-width: 30px; height: 30px; line-height: 30px; text-align: center;
           border-radius: 6px; background: var(--ink); color: #fff; font-size: 15px; margin-right: 10px;
           vertical-align: 2px; padding: 0 6px; }
p { margin: 0 0 12px; }
.lede { font-size: 17px; color: var(--ink-2); }
ul, ol { padding-left: 22px; margin: 0 0 14px; }
li { margin: 4px 0; }
ol.qs li, ol.checks li { margin: 6px 0 8px; padding-left: 2px; }
blockquote { margin: 0 0 14px; padding: 10px 16px; border-left: 3px solid var(--rule-2); background: var(--surface);
             color: var(--ink-2); font-style: italic; border-radius: 0 6px 6px 0; }
.so-what { background: var(--accent-soft); border-radius: var(--radius); padding: 12px 16px; }
.sub { color: var(--ink-3); font-size: 12.5px; }
.note { font-size: 13.5px; color: var(--ink-3); margin: -6px 0 16px; }

/* answers */
.answers { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr)); gap: 14px; }
.answer { background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 14px 16px;
          display: flex; flex-direction: column; }
.answer .q { font-weight: 650; font-size: 15.5px; line-height: 1.4; }
.answer .verdict { margin: 8px 0 8px; }
.answer p { font-size: 15px; color: var(--ink); flex: 1; }
.answer .more { font-size: 14px; font-weight: 600; text-decoration: none; }

/* chips + callouts */
.chip { display: inline-block; font-size: 12px; font-weight: 650; line-height: 1.5; padding: 1px 9px;
        border-radius: 999px; white-space: nowrap; }
.chip.good { color: var(--good); background: var(--good-bg); }
.chip.warn { color: var(--warn); background: var(--warn-bg); }
.chip.stop { color: var(--stop); background: var(--stop-bg); }
.chip.info { color: var(--accent-ink); background: var(--accent-soft); }
.chip.muted { color: var(--ink-2); background: var(--muted-bg); }
.chip.wrap { white-space: normal; border-radius: 10px; }
.callout { border-left: 3px solid; border-radius: 0 var(--radius) var(--radius) 0; padding: 11px 16px; margin: 16px 0;
           font-size: 15px; }
.callout-title { font-weight: 650; margin-bottom: 2px; }
.callout.warn { background: var(--warn-bg); border-color: var(--warn-rule); }
.callout.info { background: var(--accent-soft); border-color: var(--accent); }
.decision { background: var(--surface); border: 1px solid var(--rule-2); border-left: 4px solid var(--good);
            border-radius: var(--radius); padding: 12px 16px; margin: 20px 0; }
.decision-label { font-size: 12px; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; color: var(--good); }
.decision p { margin: 4px 0 0; }

/* tables */
.tbl-wrap { overflow-x: auto; margin: 12px 0 18px; border: 1px solid var(--rule); border-radius: var(--radius);
            /* edge shadows appear only while a wide table can still scroll sideways */
            background:
              linear-gradient(to right, var(--surface) 30%, rgba(255, 255, 255, 0)) left center / 28px 100% no-repeat local,
              linear-gradient(to left, var(--surface) 30%, rgba(255, 255, 255, 0)) right center / 28px 100% no-repeat local,
              radial-gradient(farthest-side at 0 50%, rgba(0, 0, 0, .16), rgba(0, 0, 0, 0)) left center / 12px 100% no-repeat scroll,
              radial-gradient(farthest-side at 100% 50%, rgba(0, 0, 0, .16), rgba(0, 0, 0, 0)) right center / 12px 100% no-repeat scroll,
              var(--surface); }
table.tbl { border-collapse: collapse; width: 100%; font-size: 14px; line-height: 1.45; }
.tbl th, .tbl td { padding: 8px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--rule); }
.tbl thead th { background: #fafaf8; font-weight: 650; color: var(--ink-2); font-size: 13px; }
.tbl tbody tr:last-child td { border-bottom: 0; }
.tbl .n { text-align: right; font-variant-numeric: tabular-nums; }
.tbl td.n { white-space: nowrap; }
.tbl.recs td:nth-child(1) { white-space: nowrap; }
.tbl.recs td { font-size: 13.5px; }
.tbl.grid4 td:first-child { min-width: 190px; }
details.more-table { margin: 4px 0 18px; }
details.more-table summary { cursor: pointer; font-weight: 600; color: var(--accent-ink); font-size: 14.5px; }

/* charts */
figure.chart { margin: 18px 0 26px; padding: 14px 14px 10px; background: var(--surface); border: 1px solid var(--rule);
               border-radius: var(--radius); }
.chart-title { font-weight: 650; font-size: 15.5px; line-height: 1.4; padding: 0 4px; }
.plot { min-width: 0; }
figure.chart figcaption { border-top: 1px solid var(--rule); margin-top: 4px; padding: 8px 4px 0; }
.takeaway { margin: 0; font-size: 15px; }
.takeaway::before { content: "\\2192\\00a0"; color: var(--accent); font-weight: 700; }
.how { margin: 4px 0 2px; font-size: 13.5px; color: var(--ink-3); }

/* glossary + footer */
dl.glossary dt { font-weight: 650; margin-top: 14px; }
dl.glossary dd { margin: 2px 0 0; color: var(--ink-2); }
footer { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--rule-2); font-size: 13.5px; color: var(--ink-3); }

/* wide screens: contents become a sticky sidebar */
@media (min-width: 1300px) {
  .shell { display: grid; grid-template-columns: 210px minmax(0, var(--maxw)); column-gap: 40px; max-width: 1330px;
           padding: 0 24px; justify-content: center; }
  .page { padding-left: 0; padding-right: 0; }
  .toc-side { display: block; position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px);
              overflow-y: auto; margin: 36px 0 0; background: transparent; border: 0; padding: 0; font-size: 14px; }
  .toc-side ol { columns: 1; }
  .toc-inline { display: none; }
}

/* phones */
@media (max-width: 700px) {
  body { font-size: 15.5px; }
  .page { padding: 22px 16px 48px; }
  h1 { font-size: 24px; }
  h2 { font-size: 20px; margin-top: 44px; }
  .sec-num { min-width: 26px; height: 26px; line-height: 26px; font-size: 14px; margin-right: 8px; }
  .bottom-line { padding: 12px 14px; }
  .bottom-line p { font-size: 15.5px; }
  .kpi-value { font-size: 20px; }
  .toc ol { columns: 1; }
  figure.chart { padding: 10px 6px 8px; margin-left: 0; margin-right: 0; }
  .js-plotly-plot .modebar-container { display: none !important; }   /* always shown on touch; covers labels */
  .tbl th, .tbl td { padding: 7px 9px; }
  table.stack thead { display: none; }
  table.stack, table.stack tbody, table.stack tr, table.stack td { display: block; width: 100%; }
  table.stack tr { padding: 10px 12px; border-bottom: 1px solid var(--rule); }
  table.stack tbody tr:last-child { border-bottom: 0; }
  table.stack td { border: 0; padding: 3px 0; white-space: normal; text-align: left; }
  table.stack td::before { content: attr(data-label); display: block; font-size: 11.5px; font-weight: 650;
                           color: var(--ink-3); text-transform: uppercase; letter-spacing: .04em; }
  table.stack td.n { text-align: left; white-space: normal; }
  table.stack td[data-label=""]::before, table.recs td:first-child::before { display: none; }
  table.recs td:first-child { font-size: 16px; }
  table.grid4 tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
  table.grid4 td:first-child { grid-column: 1 / -1; font-weight: 600; padding-bottom: 4px; min-width: 0; }
  table.grid4 td::before { font-size: 10.5px; letter-spacing: .02em; }
  table.tbl:not(.stack) tr > :first-child { position: sticky; left: 0; background: var(--surface);
                                             box-shadow: 1px 0 0 var(--rule); min-width: 8.5em; }
  table.tbl:not(.stack) thead tr > :first-child { background: #fafaf8; }
}

@media print {
  body { background: #fff; }
  .toc { display: none; }
  figure.chart, .answer, .callout, .decision, tr { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""

APP_JS = r"""
(function () {
  "use strict";
  // Narrow screens: tighten chart margins and wrap long category labels so plots keep a usable width.
  var NARROW = 600, WRAP = 16, LINE_PX = 14;   // LINE_PX: height of one wrapped label line at the 11 px font
  function wrapLabel(s, n) {
    var words = String(s).split(" "), lines = [], cur = "";
    words.forEach(function (w) {
      if (cur && (cur + " " + w).length > n) { lines.push(cur); cur = w; } else { cur = cur ? cur + " " + w : w; }
    });
    if (cur) lines.push(cur);
    return lines.join("<br>");
  }
  function titleText(t) { return !t ? "" : (typeof t === "string" ? t : (t.text || "")); }
  function toArr(a) { return a ? Array.prototype.slice.call(a) : []; }
  // Category labels on the y axis (horizontal bars, forest plots): the layout's category order if it has one,
  // otherwise every category used by any trace.
  function yCategories(gd) {
    var ya = gd.layout.yaxis || {}, seen = {}, out = [];
    if (ya.categoryarray && ya.categoryarray.length) return toArr(ya.categoryarray).map(String);
    (gd.data || []).forEach(function (t) {
      var y = toArr(t.y);
      if (!y.length || (t.orientation !== "h" && typeof y[0] !== "string")) return;
      y.forEach(function (v) { v = String(v); if (!seen[v]) { seen[v] = 1; out.push(v); } });
    });
    return out;
  }
  function adapt(gd) {
    var P = window.Plotly;
    if (!P || !gd || !gd.layout || !gd._fullLayout) return;
    var narrow = gd.getBoundingClientRect().width < NARROW;
    if (gd.__narrow === narrow) return;
    var data = gd.data || [];
    var hbar = data.filter(function (t) { return t.orientation === "h" && t.y; })[0];
    if (!gd.__orig) {
      var m = gd.layout.margin || {}, f = gd.layout.font || {}, ya = gd.layout.yaxis || {};
      var xa = gd.layout.xaxis || {}, fx = gd._fullLayout.xaxis || {};
      var cats = yCategories(gd);
      gd.__orig = { l: m.l, r: m.r, size: f.size, xtitle: titleText(xa.title), height: gd.layout.height,
                    // pio.to_html wraps each plot in a div with a fixed pixel height: it must follow the chart
                    wrapH: gd.parentElement ? gd.parentElement.style.height : "",
                    cats: cats.some(function (c) { return c.length > WRAP; }) ? cats : null,
                    auto: ya.automargin, tickmode: ya.tickmode,
                    text: hbar && hbar.text ? toArr(hbar.text).map(String) : null,
                    pos: data.map(function (t) { return t.textposition; }),
                    linearX: fx.type === "linear", tickangle: xa.tickangle,
                    xrange: xa.range ? toArr(xa.range) : null, fullXRange: fx.range ? toArr(fx.range) : null,
                    // horizontal bars with labels outside negative bars: those labels need room on the left
                    negOut: data.some(function (t) {
                      return t.orientation === "h" && t.textposition === "outside" && t.text &&
                             toArr(t.x).some(function (v) { return v < 0; });
                    }),
                    ann: (gd.layout.annotations || []).map(function (a) { return { text: a.text, yanchor: a.yanchor }; }) };
    }
    var o = gd.__orig, upd = {};
    if (narrow) {
      upd["margin.l"] = Math.min(o.l == null ? 80 : o.l, 40);
      upd["margin.r"] = hbar ? 20 : 12;
      upd["font.size"] = 11;
      if (o.xtitle.length > 34) upd["xaxis.title.text"] = wrapLabel(o.xtitle, 30);
      if (o.cats) {
        upd["yaxis.tickmode"] = "array";
        upd["yaxis.tickvals"] = o.cats;
        upd["yaxis.ticktext"] = o.cats.map(function (c) { return wrapLabel(c, WRAP); });
        upd["yaxis.automargin"] = true;
        // Wrapped labels need vertical room: grow the chart so each row fits its longest label. The height
        // goes on the wrapper div and Plotly autosizes to it; relayouting "height" itself would switch
        // autosize off and pin the current width, so the chart would stop following later resizes.
        var lines = Math.max.apply(null, o.cats.map(function (c) { return wrapLabel(c, WRAP).split("<br>").length; }));
        var sz = gd._fullLayout._size || {};
        var need = o.cats.length * (lines * LINE_PX + 10) + (sz.t || 0) + (sz.b || 0);
        if (o.height && need > o.height && gd.parentElement) {
          gd.parentElement.style.height = need + "px";
          upd["autosize"] = true;
        }
      }
      if (o.linearX) upd["xaxis.tickangle"] = 0;      // numeric ticks thin out on their own; never rotate them
      if (o.negOut && o.fullXRange) {
        var span = o.fullXRange[1] - o.fullXRange[0];
        upd["xaxis.range"] = [o.fullXRange[0] - 0.3 * span, o.fullXRange[1]];
      }
    } else {
      upd["margin.l"] = o.l; upd["margin.r"] = o.r; upd["font.size"] = o.size;
      if (o.xtitle.length > 34) upd["xaxis.title.text"] = o.xtitle;
      if (o.cats) {
        upd["yaxis.tickmode"] = o.tickmode == null ? null : o.tickmode;
        upd["yaxis.tickvals"] = null; upd["yaxis.ticktext"] = null;
        upd["yaxis.automargin"] = o.auto == null ? null : o.auto;
        if (gd.parentElement && o.wrapH && gd.parentElement.style.height !== o.wrapH) {
          gd.parentElement.style.height = o.wrapH;
          upd["autosize"] = true;
        }
      }
      if (o.linearX) upd["xaxis.tickangle"] = o.tickangle == null ? null : o.tickangle;
      if (o.negOut) {
        if (o.xrange) upd["xaxis.range"] = o.xrange; else upd["xaxis.autorange"] = true;
      }
      (gd.__annFixed || []).forEach(function (i) {
        upd["annotations[" + i + "].text"] = o.ann[i].text;
        upd["annotations[" + i + "].yanchor"] = o.ann[i].yanchor == null ? null : o.ann[i].yanchor;
      });
      gd.__annFixed = [];
    }
    gd.__narrow = narrow;
    P.relayout(gd, upd).then(function () {
      // Bar labels like "95.6%  (86,194)": keep only the value on narrow screens (the count stays in the hover).
      if (hbar && o.text && o.text.some(function (s) { return s.indexOf("  (") > 0; })) {
        var txt = narrow ? o.text.map(function (s) { return s.split("  (")[0]; }) : o.text;
        P.restyle(gd, { text: [txt] }, [data.indexOf(hbar)]);
      }
      // Single-point text labels: anchor them away from the nearest plot edge so they are not clipped.
      var xr = gd._fullLayout.xaxis && gd._fullLayout.xaxis.range;
      data.forEach(function (t, i) {
        if (t.type !== "scatter" || !t.mode || t.mode.indexOf("text") < 0 || !t.x || t.x.length !== 1) return;
        var x0 = Number(t.x[0]);
        if (!xr || isNaN(x0)) return;
        var f = (x0 - xr[0]) / (xr[1] - xr[0]);
        var pos = narrow ? (f < 0.4 ? "top right" : f > 0.6 ? "top left" : "top center") : o.pos[i];
        P.restyle(gd, { textposition: pos }, [i]);
      });
      if (narrow) fitAnnotations(gd, o);
    });
  }
  // Annotations that run past the edge of a narrow chart are wrapped onto several lines (growing upward).
  function fitAnnotations(gd, o) {
    var box = gd.getBoundingClientRect(), fix = {}, fixed = [];
    gd.querySelectorAll(".infolayer .annotation").forEach(function (g) {
      var i = Number(g.getAttribute("data-index")), r = g.getBoundingClientRect();
      if (isNaN(i) || !o.ann[i] || (r.right <= box.right + 1 && r.left >= box.left - 1)) return;
      fix["annotations[" + i + "].text"] = wrapLabel(String(o.ann[i].text || "").replace(/<br>/g, " "), 26);
      if (o.ann[i].yanchor !== "top") fix["annotations[" + i + "].yanchor"] = "bottom";
      fixed.push(i);
    });
    gd.__annFixed = fixed;
    if (fixed.length) window.Plotly.relayout(gd, fix);
  }
  function adaptAll() { document.querySelectorAll(".js-plotly-plot").forEach(adapt); }
  window.addEventListener("load", function () { adaptAll(); setTimeout(adaptAll, 300); });
  var timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(adaptAll, 150); });

  // Highlight the current section in the contents.
  var sections = Array.prototype.slice.call(document.querySelectorAll("main section[id], #summary"));
  var links = Array.prototype.slice.call(document.querySelectorAll(".toc a"));
  var ticking = false;
  function mark() {
    ticking = false;
    var cur = null;
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].getBoundingClientRect().top < 140) cur = sections[i].id;
    }
    links.forEach(function (a) { a.classList.toggle("active", a.getAttribute("href") === "#" + cur); });
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(mark); }
  }, { passive: true });
  mark();
})();
"""


# ====================================================================== entry point
def build_report() -> Path:
    """Write reports/report.html and reports/executive_summary.md; return the HTML path."""
    res = load_results()
    caches = load_caches()
    rep = _Report(res, caches, build_catalog(res, caches))
    REPORT_HTML.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML.write_text(rep.html(), encoding="utf-8")
    SUMMARY_MD.write_text(rep.summary_md(), encoding="utf-8")
    return REPORT_HTML
