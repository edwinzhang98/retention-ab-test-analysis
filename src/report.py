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
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

from . import config as C
from . import figures as F
from . import retention as R
from . import stats as S
from .analysis import load_results
from .catalog import Fig, build_catalog, load_caches

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

LOW_ROUNDS = ("0", "1-4", "5-14")          # "fewer than 15 rounds" (same buckets as the catalog)
PEAK_EXPOSURE = ("51-100", "101-200")       # buckets where the exploratory ad lift peaks
TOP_EXPOSURE = C.EXPOSURE_LABELS[-1]        # "200+"
GATE_LEVEL = 30                             # first gate in the control version (gate_30)
CURVE_MAX_ROUNDS = 200                      # x-range of the catalog's engagement curve

MINUS, NDASH = "−", "–"
esc = html.escape


# ====================================================================== number formatting
def _plain(v: float, nd: int) -> str:
    """Fixed decimals, Unicode minus for negatives, no plus sign."""
    s = f"{abs(v):,.{nd}f}"
    return MINUS + s if round(v, nd) < 0 else s


def _signed(v: float, nd: int) -> str:
    s = f"{abs(v):,.{nd}f}"
    r = round(v, nd)
    return ("+" + s) if r > 0 else (MINUS + s) if r < 0 else s


def _bound(v: float, nd: int) -> str:
    """CI bound: add a decimal when a non-zero bound would otherwise print as 0.00."""
    while nd < 3 and v != 0 and round(v, nd) == 0:
        nd += 1
    return _plain(v, nd)


def pct(x: float, nd: int = 1) -> str:
    return f"{_plain(x * 100, nd)}%"


def spct(x: float, nd: int = 0) -> str:
    return f"{_signed(x * 100, nd)}%"


def pp(x: float, nd: int = 2, sign: bool = False) -> str:
    return f"{(_signed if sign else _plain)(x * 100, nd)} pp"


def ci_pp(lo: float, hi: float, nd: int = 2) -> str:
    return f"{_bound(lo * 100, nd)} to {_bound(hi * 100, nd)} pp"


def ci_pct(lo: float, hi: float, nd: int = 0) -> str:
    return f"{spct(lo, nd)} to {spct(hi, nd)}"


def num(x: float, nd: int = 0) -> str:
    return _plain(float(x), nd)


def approx(x: float, step: int) -> str:
    """Round to a friendly step for the non-technical memo (4,343 -> 4,300)."""
    return f"{round(x / step) * step:,.0f}"


def usd(x: float, nd: int = 2, md: bool = False) -> str:
    # GitHub renders $...$ in Markdown as math, so the memo spells out USD.
    return f"USD {x:,.{nd}f}" if md else f"${x:,.{nd}f}"


def usd_k(x: float) -> str:
    return f"${x / 1000:,.0f}K"


def millions(x: float, nd: int = 1) -> str:
    return f"{x / 1e6:.{nd}f}M"


def pval(p: float, prefix: bool = True) -> str:
    if p < 0.001:
        s = "< 0.001"
        return f"p {s}" if prefix else s
    if p >= 1:
        s = "1.00"
    elif p > 0.99:
        s = f"{p:.4f}"
    elif p >= 0.1:
        s = f"{p:.2f}"
    elif p >= 0.01:
        s = f"{p:.3f}"
    else:
        s = f"{p:.4f}"
    return f"p = {s}" if prefix else s


def evidence(p: float) -> str:
    return "strong evidence" if p < 0.001 else "weak evidence" if p < 0.05 else "no evidence"


def _split(share_t: float) -> str:
    return f"{share_t * 100:.0f}/{(1 - share_t) * 100:.0f}"


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
        self.conf = f"{(1 - self.alpha) * 100:.0f}%"
        self.today = dt.date.today().isoformat()
        self.dq = res["data_quality"]
        self.ad, self.ck = res["ad"], res["cookie"]
        self.t, self.gate = self.ad["test"], self.ck["gate"]
        self.g1, self.g7 = self.gate["retention_1"], self.gate["retention_7"]
        self.pw, self.bz, self.het = self.ad["power"], self.ad["business"], self.ad["heterogeneity"]
        self._derive(caches)

    # ------------------------------------------------------------------ derived numbers
    def _derive(self, caches: dict[str, pd.DataFrame]) -> None:
        t, a = self.t, self.alpha
        self.arms = F.arm_table(t["conv_t"], t["n_t"], t["conv_c"], t["n_c"], alpha=a).set_index("arm")
        self.n_total = t["n_t"] + t["n_c"]
        self.split = _split(self.ad["srm"]["intended_share_t"])

        cells = caches["cells"]
        orders = {"most_ads_day": C.DAY_ORDER, "most_ads_hour": list(range(24)),
                  "exposure_bucket": C.EXPOSURE_LABELS}
        self.seg = {d: S.segment_lifts(cells, d, "ad", "psa", alpha=a, method="holm", order=o)
                    for d, o in orders.items()}
        users_by_bucket = cells.groupby("exposure_bucket")["users"].sum()
        self.expo_low = [lab for lab, hi in zip(C.EXPOSURE_LABELS, C.EXPOSURE_BINS[1:]) if hi <= 20]
        self.expo_low_max = max(hi for hi in C.EXPOSURE_BINS[1:] if hi <= 20)
        self.share_expo_low = float(users_by_bucket.reindex(self.expo_low).sum() / users_by_bucket.sum())
        self.expo = self.seg["exposure_bucket"].set_index("exposure_bucket")
        lo_lab, hi_lab = PEAK_EXPOSURE
        self.peak_range = f"{lo_lab.split('-')[0]}{NDASH}{hi_lab.split('-')[1]}"
        self.top_cut = TOP_EXPOSURE.rstrip("+")
        self.hour_holm = [int(h) for h in self.seg["most_ads_hour"].loc[
            self.seg["most_ads_hour"]["significant_adj"], "most_ads_hour"]]

        rb = pd.DataFrame(self.ck["by_rounds_bucket"]).set_index("rounds_bucket")
        self.rb = rb
        low = rb.loc[list(LOW_ROUNDS)]
        self.low_share, self.low_n = float(low["share_of_players"].sum()), int(low["players"].sum())
        self.low_d7_max = float(low["retention_7"].max())
        self.low_cut = C.ROUNDS_BINS[C.ROUNDS_LABELS.index(LOW_ROUNDS[-1]) + 1] + 1
        d1 = pd.DataFrame(self.ck["by_d1_status"]).set_index("d1_status")
        self.d7_yes = float(d1.loc["Returned Day 1", "retention_7"])
        self.d7_no = float(d1.loc["Did not return Day 1", "retention_7"])
        self.funnel = pd.DataFrame(self.ck["funnel"]).set_index("step")
        self.gaps = pd.DataFrame(self.ck["gap_by_dimension"])

        players = caches["players"]
        curve =R.engagement_curve(players, CURVE_MAX_ROUNDS, by="version").pivot(
            index="rounds_at_least", columns="group", values="share_of_players")
        self.curve_gap_pp = float((curve["gate_40"] - curve["gate_30"]).abs().max() * 100)
        grp = players.groupby(["reached_gate_30", "version"])["retention_7"].agg(["sum", "size"])
        self.by_reach = {}
        for reached in (True, False):
            tr, co = grp.loc[(reached, "gate_40")], grp.loc[(reached, "gate_30")]
            self.by_reach[reached] = S.two_prop_test(tr["sum"], tr["size"], co["sum"], co["size"], alpha=a)

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
        t, bz, o, g7 = self.t, self.bz, self.ck["overall"], self.g7
        inc, be = bz["incremental_conversions"], bz["breakeven_cpm_usd"]
        c = self.conf
        bottom = (
            f"The ad campaign drove conversions. In a randomized test with {num(self.n_total)} users, people shown "
            f"the campaign's ads converted at {pct(t['rate_t'], 2)} versus {pct(t['rate_c'], 2)} for a control group "
            f"shown a public-service announcement (PSA) in the same ad slots: {pp(t['abs_lift'], sign=True)} "
            f"({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), a {spct(t['rel_lift'])} relative lift, or about "
            f"{num(inc['point'])} incremental conversions from {millions(bz['impressions_ad_group'])} impressions. "
            f"<strong>Keep it running at the current budget.</strong> Whether to double the budget is something this "
            f"test cannot answer, because budget was never varied, and exploratory cuts hint that the effect "
            f"saturates at high ad frequency: <strong>test a higher budget before committing to it.</strong> "
            f"On retention, {pct(1 - o['retention_1'])} of new players do not return on Day 1 and only "
            f"{pct(o['retention_7'])} are back on Day 7; the loss is concentrated among the "
            f"{pct(self.low_share, 0)} of installs who play fewer than {self.low_cut} rounds, so "
            f"<strong>retention work should start with the first session and Day 1.</strong> Finally, "
            f"<strong>keep the first gate at level {GATE_LEVEL}</strong>: moving it to level 40 lowered D7 retention by "
            f"{pp(-g7['abs_lift'])} ({c} CI {ci_pp(-g7['abs_ci_high'], -g7['abs_ci_low'])}), although a "
            f"sample-ratio warning means that estimate is not yet certified."
        )
        kpis = [
            ("Ad lift (absolute)", pp(t["abs_lift"], sign=True), f"{c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}"),
            ("Relative lift", spct(t["rel_lift"]), f"{c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'])}"),
            ("Incremental conversions", f"&asymp;{num(inc['point'])}",
             f"{c} CI {num(inc['ci_low'])}{NDASH}{num(inc['ci_high'])}"),
            ("Breakeven CPM", usd(be["point"]), f"at an <b>assumed</b> {usd(self.value, 0)} per conversion"),
            ("D7 retention, new players", pct(o["retention_7"]),
             f"D1 {pct(o['retention_1'])} &middot; {num(o['players'])} players"),
            ("gate_40 effect on D7", pp(g7["abs_lift"], sign=True),
             f"{c} CI {ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])} &middot; SRM warning"),
        ]
        tiles = "".join(f'<div class="kpi"><div class="kpi-label">{lab}</div><div class="kpi-value">{val}</div>'
                        f'<div class="kpi-sub">{sub}</div></div>' for lab, val, sub in kpis)
        return f"""
<header class="masthead" id="top">
  <div class="eyebrow">Growth &middot; Product Analytics &middot; Experiment readout</div>
  <h1>Ad campaign and new-player retention</h1>
  <p class="meta">Prepared by the Product Analyst, Growth, for the Growth PM &middot; Generated {self.today} from
  <code>reports/results.json</code> &middot; Data: two public experiment datasets standing in for our logs
  (<a href="#s1-data">Section 1</a>)</p>
  <section class="bottom-line" id="summary" aria-label="Summary"><p><strong>Bottom line.</strong> {bottom}</p></section>
  <div class="kpis">{tiles}</div>
  <p class="conventions">Conventions: rates in %; differences in percentage points (pp); intervals are {c}
  confidence intervals (CI); &ldquo;treatment&rdquo; = ad / gate_40, &ldquo;control&rdquo; = PSA / gate_30.
  Methods are explained in plain English in the <a href="#appendix">appendix</a>.</p>
</header>"""

    # ------------------------------------------------------------------ answers for the PM
    def answers(self) -> str:
        t, bz, c = self.t, self.bz, self.conf
        inc, be, g = bz["incremental_conversions"], bz["breakeven_cpm_usd"], self.ad["groups"]
        o, g1, g7, srm = self.ck["overall"], self.g1, self.g7, self.gate["srm"]
        e, gaps = self.expo, self.gaps
        cards = [
            ("Q1 &middot; Did last quarter's ad campaign drive conversions?", _chip("good", "Yes &middot; keep it running (R1)"),
             f"Ad {pct(t['rate_t'], 2)} vs PSA {pct(t['rate_c'], 2)} conversion: <b>{pp(t['abs_lift'], sign=True)}</b> "
             f"({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), <b>{spct(t['rel_lift'])}</b> relative "
             f"({c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'])}). That is &asymp;{num(inc['point'])} incremental "
             f"conversions ({c} CI {num(inc['ci_low'])}{NDASH}{num(inc['ci_high'])}) from "
             f"{millions(bz['impressions_ad_group'])} impressions, about {pct(bz['share_of_ad_conversions_incremental'], 0)} "
             f"of the ad group's conversions; the rest would have happened anyway. Sanity checks pass: both arms were "
             f"served the same ad volume ({num(g['ad']['mean_ads'], 1)} vs {num(g['psa']['mean_ads'], 1)} ads per "
             f"user) and arm sizes match the assumed {self.split} split.", "#s4", "Section 4"),
            ("Q2 &middot; Is it worth doubling the budget?", _chip("warn", "Not answerable yet &middot; test first (R2)"),
             f"The test ran at one budget level, so it cannot say what extra spend buys. At an <b>assumed</b> "
             f"{usd(self.value, 0)} per conversion (there is no revenue in the data), the current flight pays back if "
             f"CPM is below <b>{usd(be['point'])}</b> ({c} CI {usd(be['ci_low'])}{NDASH}{usd(be['ci_high'])}). "
             f"Exploratory: no detectable lift for the {pct(self.share_expo_low, 0)} of users who saw "
             f"&le; {self.expo_low_max} ads, {_plain(e.loc[PEAK_EXPOSURE[0], 'abs_lift'] * 100, 1)}{NDASH}"
             f"{pp(e.loc[PEAK_EXPOSURE[1], 'abs_lift'], 1)} at {self.peak_range} ads, and indistinguishable from 0 above "
             f"{self.top_cut}: a saturation pattern to test, not a result, because ad exposure is a post-assignment "
             f"variable. Re-timing spend by day or hour is not supported either.", "#s4-business", "Sections 4.6 and 5"),
            ("Q3 &middot; Which new users leave first?", _chip("info", "The least engaged, before Day 1 &middot; R6"),
             f"{pct(1 - o['retention_1'])} of new players never return on Day 1; {pct(o['retention_7'])} are back on "
             f"Day 7. Players with fewer than {self.low_cut} rounds are <b>{pct(self.low_share, 0)} of installs</b> and "
             f"at most {pct(self.low_d7_max)} of them are back on Day 7. Day-1 returners are "
             f"<b>{self.d7_yes / self.d7_no:.1f}&times;</b> as likely to be retained on Day 7 ({pct(self.d7_yes)} vs "
             f"{pct(self.d7_no)}). Engagement depth separates D7 by {gaps.iloc[0]['gap_pp']:.0f} pp, the experiment "
             f"version by {gaps.iloc[-1]['gap_pp']:.1f} pp. These are correlations: rounds are counted over 14 days, "
             f"which overlaps the D7 window.", "#s3", "Section 3"),
            (f"Gate &middot; Should the first gate move from level {GATE_LEVEL} to 40?",
             _chip("stop", f"No &middot; keep gate {GATE_LEVEL} (R5)"),
             f"gate_40 D7 {pct(g7['rate_t'], 2)} vs {pct(g7['rate_c'], 2)}: <b>{pp(g7['abs_lift'], sign=True)}</b> "
             f"({c} CI {ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])}); D1 {pp(g1['abs_lift'], sign=True)} is not "
             f"conclusive ({pval(g1['p_value'])}). Arm sizes {num(srm['n_t'])} vs {num(srm['n_c'])} deviate from 50/50 "
             f"(SRM {pval(srm['p_value'])}): a warning that blocks certification of the effect size. Keeping gate "
             f"{GATE_LEVEL} is the safe default either way; audit assignment before any re-test.", "#s6", "Section 6"),
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
        t, bz, pw, c = self.t, self.bz, self.pw, self.conf
        inc, be = bz["incremental_conversions"], bz["breakeven_cpm_usd"]
        hd, hh = self.het["most_ads_day"], self.het["most_ads_hour"]
        n10 = pw["total_n_for_10pct_rel_lift"]
        mde_now, mde_5050 = pw["mde_current"]["mde_abs"], pw["mde_if_5050_same_total"]["mde_abs"]
        g7 = self.g7
        return [
            dict(id="R1", owner="Growth PM", chip=_chip("good", "Keep"),
                 what="Keep the ad campaign running at the current budget.",
                 impact=f"&asymp;{num(inc['point'])} incremental conversions per comparable flight ({c} CI "
                        f"{num(inc['ci_low'])}{NDASH}{num(inc['ci_high'])}; {millions(bz['impressions_ad_group'])} impressions).",
                 measure="Keep an always-on 5&ndash;10% PSA holdout; track the incremental conversion rate and the cost "
                         f"per incremental conversion (= CPM &times; {bz['impressions_per_incremental_conversion'] / 1000:.2f}).",
                 risk=f"Value per conversion and actual CPM are unknown: confirm with Finance that the actual CPM is "
                      f"below breakeven ({usd(be['point'])} at an assumed {usd(self.value, 0)} per conversion)."),
            dict(id="R2", owner="Growth PM + media buyer", chip=_chip("warn", "Test first"),
                 what="Do not double the budget blindly. First run a randomized budget / frequency test: 2&times;-budget "
                      "or frequency-cap arms vs the current plan, 50/50 or 80/20, sized with the MDE calculator.",
                 impact="Learn what the extra spend buys before committing it; exploratory data suggest lift saturates "
                        f"above {self.top_cut} ads per user.",
                 measure="Marginal incremental conversions per extra $1K spent (marginal iROAS).",
                 risk="Saturation and ad fatigue at high frequency; the 2&times; arm spends money while the test runs."),
            dict(id="R3", owner="Media buyer", chip=_chip("stop", "Don't (yet)"),
                 what="Do not re-plan spend by day or hour yet. If daypart matters, run a pre-registered daypart test "
                      f"(e.g. {hd['max_lift_segment']} vs {hd['min_lift_segment']}).",
                 impact=f"Avoids moving budget on noise: {hh['n_sig_unadjusted']} of {hh['n_segments']} hours look "
                        f"significant before correction, {hh['n_sig_holm']} after Holm; day interaction "
                        f"{pval(hd['lrt']['p_value'])} is weak evidence.",
                 measure="Difference in lift between the dayparts, with its CI, from the pre-registered test.",
                 risk="Chasing noise; peak day / hour are post-assignment summaries, not a schedule we controlled."),
            dict(id="R4", owner="Analytics + Eng", chip=_chip("info", "Fix design"),
                 what="Fix the next experiment's design: 50/50 or 80/20 instead of 96/4; log assignment timestamps; "
                      "pre-register the primary metric and guardrails this dataset lacks (unsubscribe / complaint "
                      "rate, CPA).",
                 impact=f"The same {num(self.n_total)} users at 50/50 detect {pp(mde_5050)} instead of {pp(mde_now)} "
                        f"({mde_now / mde_5050:.1f}&times; more sensitive); a 10% relative lift needs "
                        f"&asymp;{num(n10['0.5'])} users at 50/50 vs &asymp;{num(n10['0.96'])} at {self.split}.",
                 measure="Pre-registration written before launch; SRM, exposure parity and guardrails reported in "
                         "every readout.",
                 risk=f"A larger control group forgoes conversions during the test (at the observed lift, "
                      f"&asymp;{t['abs_lift'] * 10000:.0f} per 10,000 control users)."),
            dict(id="R5", owner="Game PM", chip=_chip("stop", "Don't ship"),
                 what=f"Keep the progression gate at level {GATE_LEVEL}; do not ship gate_40. Investigate the SRM "
                      "before any re-test.",
                 impact=f"Avoids a &asymp;{pp(-g7['abs_lift'])} D7 drop ({c} CI "
                        f"{ci_pp(-g7['abs_ci_high'], -g7['abs_ci_low'])}): &asymp;{-g7['abs_lift'] * 10000:.0f} fewer "
                        f"D7-retained players per 10,000 installs (&asymp;{-g7['abs_lift'] * g7['n_t']:.0f} per "
                        f"{num(g7['n_t'])} installs, the size of one arm).",
                 measure=f"D7 retention stays at the gate_30 level ({pct(g7['rate_c'])}); an assignment audit or "
                         "A/A test shows a clean 50/50 split before re-testing.",
                 risk="The effect size is not certified (SRM warning); if assignment was biased, the true effect "
                      "could be smaller or larger."),
            dict(id="R6", owner="Onboarding PM", chip=_chip("info", "Act"),
                 what=f"Focus retention work on the first session &rarr; Day 1: run a Day-1 re-engagement / onboarding "
                      f"experiment for new players with fewer than {self.low_cut} rounds, D7 retention as the primary "
                      "metric.",
                 impact=f"Targets the largest at-risk group: {pct(self.low_share, 0)} of installs "
                        f"({num(self.low_n)} players) and at most {pct(self.low_d7_max)} of them retained on D7; "
                        f"Day-1 returners are {self.d7_yes / self.d7_no:.1f}&times; as likely to be retained on D7.",
                 measure="D7 retention (primary) and D1 retention (secondary) against a randomized holdout.",
                 risk="The rounds&ndash;retention link is correlational (rounds over 14 days overlap the D7 window); "
                      "only the experiment can show the effect."),
        ]

    def recs_section(self) -> str:
        rows = [[f'<b>{r["id"]}</b>', f'{r["owner"]}<br>{r["chip"]}', r["what"], r["impact"], r["measure"], r["risk"]]
                for r in self.recommendations()]
        table = _table(["#", "Owner", "What", "Expected impact", "How we'll measure it", "Risk"], rows,
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
             "At what CPM does the campaign break even under an explicit value-per-conversion assumption? Does lift "
             "keep growing with exposure or saturate? What can this test <i>not</i> say about 2&times;?",
             "Scale to 2&times;, hold, or test 2&times; first", "Growth PM + budget owner"],
            ["Q3", "(implicit) Where should the money go?",
             "Does lift differ reliably by peak ad day / hour after an interaction test and multiple-comparison "
             "correction?", "Day-parting / reallocation", "Growth PM + media buyer"],
            ["Q4", "Which new users leave first?",
             "How do D1 / D7 retention differ by engagement depth, Day-1 return and version, and where is the largest "
             "drop?", "Which onboarding segment to target first", "Game / Onboarding PM"],
            ["Q5", f"(second experiment) Move the first gate from level {GATE_LEVEL} to 40?",
             "Does gate_40 change D7 (primary) or D1 retention? Is the experiment trustworthy (SRM)?",
             f"Ship gate_40 or keep gate_{GATE_LEVEL}", "Game PM"],
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
    "<b>Q1:</b> a confidence interval that includes 0, or failed sanity checks (SRM, exposure parity): we could "
    "not claim the campaign works.",
    "<b>Q2:</b> a breakeven CPM below what we actually pay means the campaign loses money despite a real lift; "
    "lift that saturates with frequency means extra spend mostly buys wasted impressions.",
    "<b>Q3:</b> reallocation is justified only if heterogeneity survives a formal interaction test <i>and</i> "
    "multiple-comparison correction; otherwise &ldquo;Tuesday looks best&rdquo; is noise.",
    "<b>Q4 / Q5:</b> a D7 drop whose interval excludes 0 means &ldquo;don't ship&rdquo;; a failed SRM means the "
    "readout cannot be certified until assignment is investigated.",
])}
<h3 id="s1-data">Data</h3>
<p>Real user-level experiment data is rarely public, so two public Kaggle datasets stand in for our logs:</p>
{_ul([
    f"<b>Marketing A/B test (2021)</b>: {num(m['rows_raw'])} users randomized to see the campaign's ads "
    "(<code>ad</code>) or a public-service announcement in the same slots (<code>psa</code>). Fields: test group, "
    "converted, total ads seen, and the day and hour the user saw the most ads. No dates, no revenue, no retention.",
    f"<b>Cookie Cats (2017)</b>: {num(ck['rows_raw'])} new players of a mobile puzzle game randomized to the "
    f"first progression gate at level {GATE_LEVEL} (<code>gate_30</code>) or level 40 (<code>gate_40</code>). "
    "Fields: version, game rounds played in the first 14 days, and whether the player came back on Day 1 and Day 7. "
    "Used for the retention analysis and as a second experiment.",
])}
<p>The two datasets are different products with no shared users, so ad conversion and retention cannot be linked.</p>
<h3>Out of scope (not answerable with this data)</h3>
{_ul([
    "<b>Revenue and ROI</b>: there are no revenue or cost fields; dollar figures use an explicit, adjustable "
    "assumption.",
    "<b>Time trends and novelty effects</b>: there are no dates, only the weekday and hour of peak ad exposure.",
    "<b>Long-term value of converters</b>: the datasets cannot be joined.",
])}
</section>"""

    # ------------------------------------------------------------------ 2 data quality
    def s2_data(self) -> str:
        m, ck = self.dq["marketing"], self.dq["cookie"]
        out = ck["outliers_dropped"][0] if ck["outliers_dropped"] else None
        srm_ad, srm_g = self.ad["srm"], self.gate["srm"]
        g = self.ad["groups"]
        bal = self.ad["balance"]
        v_lo, v_hi = min(b["cramers_v"] for b in bal), max(b["cramers_v"] for b in bal)
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
             ["Players with 0 rounds", num(ck["zero_round_players"]),
              "Kept: they installed but never played, which is part of the funnel."],
             ["Back on Day 7 but not Day 1", num(ck["d7_without_d1"]),
              "Kept: D7 is recorded independently of D1."]])
        rr, rc = ck["retention_raw"], ck["retention_clean"]
        moved = max(abs(rr["d1"] - rc["d1"]), abs(rr["d7"] - rc["d7"])) * 100
        sens = _table(["Metric", "With the outlier", "Without (used)"],
                      [["D1 retention", pct(rr["d1"], 3), pct(rc["d1"], 3)],
                       ["D7 retention", pct(rr["d7"], 3), pct(rc["d7"], 3)],
                       ["Mean rounds per player", num(ck["mean_rounds_raw"], 2), num(ck["mean_rounds_clean"], 2)]],
                      num_cols={1, 2})
        ok, warn, lim = _chip("good", "Pass"), _chip("warn", "Warning"), _chip("muted", "Limitation")
        glance = _table(
            ["Check", "Result", "Verdict"],
            [["Row reconciliation", f"Marketing {num(m['rows_raw'])} raw = {num(m['rows_clean'])} analysed; Cookie Cats "
              f"{num(ck['rows_raw'])} &rarr; {num(ck['rows_clean'])} (one documented outlier)", ok],
             ["Primary keys unique", f"{num(m['duplicate_user_id'] + ck['duplicate_user_id'])} duplicate IDs", ok],
             ["Missing values", f"{num(sum(m['nulls'].values()) + sum(ck['nulls'].values()))} in all columns", ok],
             ["Value domains", "Arms, booleans, hours 0&ndash;23 and 7 weekdays as expected", ok],
             [f"Ad test: SRM vs intended {self.split}",
              f"{pval(srm_ad['p_value'])}; weak check because the intended split is inferred, not documented",
              _chip("good", "Pass (weak)")],
             ["Ad test: exposure parity", f"mean ads per user {num(g['ad']['mean_ads'], 2)} vs "
              f"{num(g['psa']['mean_ads'], 2)}; median {num(g['ad']['median_ads'])} vs {num(g['psa']['median_ads'])}", ok],
             ["Ad test: day / hour / exposure balance",
              f"Cram&eacute;r's V {v_lo:.3f}&ndash;{v_hi:.3f} (tiny, but post-assignment)",
              _chip("muted", "Exploratory only")],
             ["Gate test: SRM vs 50/50",
              f"{num(srm_g['n_t'])} vs {num(srm_g['n_c'])}, {pval(srm_g['p_value'])}: below 0.01, above the "
              f"{srm_g['threshold']:g} auto-flag threshold", warn],
             ["Time coverage", "No timestamps in either dataset", lim]],
            stack=True)
        return f"""
<section id="s2">
<h2><span class="sec-num">2</span>Data and quality checks</h2>
<p class="lede">Can we trust the data and the experiment setup? Before any test: reconcile rows, check keys, missing
values, value domains, outliers and time coverage.</p>
<h3>2.1 Datasets and row reconciliation</h3>
{overview}
<h3>2.2 Value ranges and outliers</h3>
{ranges}
<h3>2.3 Does dropping the outlier change anything?</h3>
<p>Retention moves by at most {moved:.4f} pp; only the mean of rounds moves, which is why rounds are summarised
with medians and rank-based tests.</p>
{sens}
<h3>2.4 Sanity checks at a glance</h3>
{glance}
<p>Details: the ad experiment's checks are in <a href="#s4-design">Section 4.3</a>, the gate experiment's SRM in
<a href="#s6">Section 6</a>.</p>
</section>"""

    # ------------------------------------------------------------------ 3 retention
    def s3_retention(self) -> str:
        o, f, ck, gaps = self.ck["overall"], self.funnel, self.dq["cookie"], self.gaps
        played = f.loc["Played at least 1 round", "share_of_installs"]
        d1_share = f.loc["Returned on Day 1", "share_of_installs"]
        both = f.loc["Returned on Day 1 and Day 7"]
        c = self.conf
        rb = self.rb
        rows = [[esc(str(b)), num(r["players"]), pct(r["share_of_players"]), pct(r["retention_1"]),
                 pct(r["retention_7"]), f"{_bound(r['retention_7_ci_low'] * 100, 1)}&ndash;"
                 f"{_bound(r['retention_7_ci_high'] * 100, 1)}%"] for b, r in rb.iterrows()]
        bucket_table = _table(["Rounds in first 14 days", "Players", "Share of installs", "D1", "D7", f"D7 {c} CI"],
                              rows, num_cols={1, 2, 3, 4, 5})
        top_bucket = rb.index[-1]
        return f"""
<section id="s3">
<h2><span class="sec-num">3</span>Retention analysis (Cookie Cats)</h2>
<p class="lede">Which new players leave first, and where is the biggest drop?</p>
{_callout("info", "Definitions",
    f"<b>D1 retention</b> = share of installs who came back one day after installing (<code>retention_1</code>); "
    f"<b>D7</b> = share who came back on day 7 (<code>retention_7</code>). D7 is recorded independently of D1: "
    f"{num(ck['d7_without_d1'])} players were back on Day 7 without returning on Day 1. <b>Rounds</b> = game rounds "
    f"played in the first 14 days. Overall: D1 {pct(o['retention_1'])} ({c} CI {pct(o['retention_1_ci_low'])}"
    f"&ndash;{pct(o['retention_1_ci_high'])}), D7 {pct(o['retention_7'])} ({pct(o['retention_7_ci_low'])}&ndash;"
    f"{pct(o['retention_7_ci_high'])}), {num(o['players'])} players.")}
<h3>3.1 The biggest drop happens before Day 1</h3>
<p>{pct(played)} of installs play at least one round, but only {pct(d1_share)} return on Day 1, so the largest
absolute loss ({(played - d1_share) * 100:.0f} pp of installs) happens between the first session and Day 1. Of the
players who return on Day 1, {pct(both['step_conversion'])} are back on Day 7 ({pct(both['share_of_installs'])} of
all installs).</p>
{self.fig("ret_funnel", "each bar is the share of all installs that reached the step; hover a bar for the "
          "conversion from the previous step.")}
<h3>3.2 Day 1 predicts Day 7</h3>
<p>Coming back on Day 1 is the first signal that a player will stay: Day-1 returners are
{self.d7_yes / self.d7_no:.1f}&times; as likely to be back on Day 7 ({pct(self.d7_yes)} vs {pct(self.d7_no)}).</p>
{self.fig("ret_by_d1", "bars are D7 retention for players who did and did not come back on Day 1; whiskers are "
          f"{c} confidence intervals (tiny here because both groups are large).")}
<h3>3.3 Engagement depth separates players most</h3>
<p>Players with fewer than {self.low_cut} rounds are {pct(self.low_share, 0)} of installs ({num(self.low_n)}
players), and at most {pct(self.low_d7_max)} of them are back on Day 7. Retention climbs with every bucket; at
{esc(str(top_bucket))} rounds D7 reaches {pct(rb.loc[top_bucket, 'retention_7'])}. Buckets are cut around the two gate
positions (level {GATE_LEVEL} and 40).</p>
{self.fig("ret_by_rounds_bucket", "blue = D1, orange = D7 retention for each rounds bucket; n under each label is "
          "the number of players; whiskers are confidence intervals.")}
{bucket_table}
{self.fig("ret_engagement_curve", "read it like a survival curve over game progress: the height at N is the share "
          "of players who played at least N rounds. Dotted lines mark the two gate positions.")}
{self.fig("ret_by_rounds_curve", "each point is a 5-round bin. Players who come back on Day 7 also have more days "
          "in which to play, so the curve cannot show cause and effect.")}
<h3>3.4 Which dimension separates players most?</h3>
<p>Engagement depth separates D7 retention by {gaps.iloc[0]['gap_pp']:.0f} pp, Day-1 return by
{gaps.iloc[1]['gap_pp']:.0f} pp, and the experiment version by only {gaps.iloc[-1]['gap_pp']:.1f} pp: who the player
is matters far more than which gate they got.</p>
{self.fig("ret_gap_by_dimension", "for each way of splitting players, the bar is the D7 gap between its best and "
          "worst segment. A longer bar means the dimension tells players apart better.")}
{_callout("warn", "Correlation, not cause",
    "Rounds are counted over the first 14 days, which overlaps the D7 window: players who come back on Day 7 also "
    "have more days in which to play. &ldquo;More rounds, higher retention&rdquo; may therefore run the other way "
    "round. The pattern says <i>whom</i> to target, not that making people play more will keep them; that needs an "
    "experiment (R6).")}
<p class="so-what"><b>So what.</b> The first session and Day 1 are where most new players are lost, and the
least-engaged {pct(self.low_share, 0)} of installs are almost never retained. That is the segment for the
Onboarding PM's next experiment (<a href="#recommendations">R6</a>), with D7 as the primary metric.</p>
</section>"""

    # ------------------------------------------------------------------ 4 ad experiment
    def s4_ad(self) -> str:
        t, ad, c = self.t, self.ad, self.conf
        g, srm, b, pw, bz = ad["groups"], ad["srm"], ad["bootstrap"], self.pw, self.bz
        arms = self.arms
        inc, val, be = bz["incremental_conversions"], bz["incremental_value_usd"], bz["breakeven_cpm_usd"]
        bal = {x["variable"]: x for x in ad["balance"]}
        bal_names = {"most_ads_day": "Peak ad day", "most_ads_hour": "Peak ad hour",
                     "exposure_bucket": "Total ads seen (bucket)"}
        bal_table = _table(["Variable", "Chi-square", "df", "p", "Cram&eacute;r's V"],
                           [[bal_names[k], num(v["chi2"], 1), num(v["df"]), pval(v["p_value"], prefix=False),
                             f"{v['cramers_v']:.3f}"] for k, v in bal.items()], num_cols={1, 2, 3, 4})
        v_lo, v_hi = min(x["cramers_v"] for x in ad["balance"]), max(x["cramers_v"] for x in ad["balance"])

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
             [_chip("good", "Guardrail"), "Sample ratio (SRM)", f"Observed vs intended {self.split} split, chi-square",
              "Detects broken assignment, which would invalidate everything else."],
             [_chip("good", "Guardrail"), "Exposure parity", "Mean / median ads served per user, by arm",
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
        power_table = _table(
            ["Split (ad / PSA)", f"Smallest detectable lift with {num(self.n_total)} users",
             f"Users needed to detect a 10% relative lift ({pp(0.1 * t['rate_c'])})"],
            [[f"{self.split} (as run)", f"{pp(mde_now['mde_abs'])} ({pct(mde_now['mde_rel'])} relative)", num(n10["0.96"])],
             ["80/20", f"{pp(mde_8020['mde_abs'])} ({pct(mde_8020['mde_rel'])} relative)", num(n10["0.8"])],
             ["50/50", f"{pp(mde_5050['mde_abs'])} ({pct(mde_5050['mde_rel'])} relative)", num(n10["0.5"])]],
            num_cols={1, 2})
        n_match = pw["total_n_for_current_mde_at_5050"]

        biz_table = _table(
            ["Quantity", "Value", "How it is computed"],
            [["Incremental conversions", f"&asymp;{num(inc['point'])} ({c} CI {num(inc['ci_low'])}&ndash;{num(inc['ci_high'])})",
              f"absolute lift &times; {num(t['n_t'])} ad-arm users"],
             ["Ad impressions (ad arm)", num(bz["impressions_ad_group"]), "sum of ads served"],
             ["Impressions per incremental conversion", num(bz["impressions_per_incremental_conversion"]),
              "impressions &divide; incremental conversions"],
             ["Share of ad-arm conversions that are incremental", pct(bz["share_of_ad_conversions_incremental"]),
              "lift &divide; ad-arm conversion rate"],
             [f"Incremental value <b>(assumed {usd(self.value, 0)} per conversion)</b>",
              f"&asymp;{usd_k(val['point'])} ({c} CI {usd_k(val['ci_low'])}&ndash;{usd_k(val['ci_high'])})",
              "incremental conversions &times; assumed value"],
             [f"Breakeven CPM <b>(assumed {usd(self.value, 0)} per conversion)</b>",
              f"{usd(be['point'])} ({c} CI {usd(be['ci_low'])}&ndash;{usd(be['ci_high'])})",
              "incremental value &divide; impressions &times; 1,000"]],
            num_cols={1})
        cost_per_cpm = bz["impressions_per_incremental_conversion"] / 1000
        over = 1 / bz["share_of_ad_conversions_incremental"]

        return f"""
<section id="s4">
<h2><span class="sec-num">4</span>Ad experiment readout (ad vs PSA)</h2>
<p class="lede">Did ads increase conversion, by how much, and is it worth the money?</p>
<h3 id="s4-hypothesis">4.1 Hypothesis</h3>
<p>Showing the campaign's ads, instead of a public-service announcement in the same ad slots, increases the share of
users who convert. Null hypothesis: no difference in conversion rate between the arms. Two-sided test,
&alpha; = {self.alpha:g}.</p>
<h3 id="s4-metrics">4.2 Metrics</h3>
{metrics}
<h3 id="s4-design">4.3 Design, sample and sanity checks</h3>
<p>Users were randomized individually: {num(t['n_t'])} saw ads and {num(t['n_c'])} saw PSAs
({pct(srm['observed_share_t'], 2)} / {pct(1 - srm['observed_share_t'], 2)}).</p>
{_ul([
    f"<b>SRM check:</b> against an intended {self.split} split the chi-square test gives {pval(srm['p_value'])}, so "
    "the observed split matches. <i>Caveat:</i> the intended allocation is not documented; we inferred it from the "
    "round number, so this check is weak (almost any split near the observed one would pass).",
    f"<b>Exposure parity</b> is the stronger check: both arms were served ad slots at the same rate, mean "
    f"{num(g['ad']['mean_ads'], 2)} vs {num(g['psa']['mean_ads'], 2)} ads per user (median "
    f"{num(g['ad']['median_ads'])} vs {num(g['psa']['median_ads'])}).",
    f"<b>Balance of day, hour and exposure:</b> the distributions differ slightly between arms. The chi-square tests "
    f"are &ldquo;significant&rdquo; only because n is huge; the effect sizes are tiny (Cram&eacute;r's V "
    f"{v_lo:.3f}&ndash;{v_hi:.3f}, where 0 = identical and 1 = completely different). The shape of total ads differs a "
    f"little too (KS statistic {ad['total_ads_ks']['stat']:.3f}).",
])}
{bal_table}
{_callout("warn", "Post-assignment variables",
    "Total ads, peak ad day and peak ad hour were recorded <i>after</i> users were assigned, and they partly "
    "reflect how users in each arm behaved (for example, how long they kept browsing). They are therefore never used "
    "as covariates, and every cut by them (<a href='#s5'>Section 5</a>) is exploratory.")}
{self.fig("ad_balance_day", "bars show how each arm's users are spread across their peak ad day. Similar heights "
          "mean the arms look alike on this variable.")}
{self.fig("ad_balance_exposure", "the same comparison for the number of ads a user saw. Both arms were served the "
          "same slots, so their exposure should match, and it nearly does.")}
<h3 id="s4-results">4.4 Results</h3>
<p>The ad arm converted at {pct(t['rate_t'], 3)} vs {pct(t['rate_c'], 3)} for PSA. <b>Absolute lift
{pp(t['abs_lift'], sign=True)}</b> ({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}), <b>relative lift
{spct(t['rel_lift'], 1)}</b> ({c} CI {ci_pct(t['rel_ci_low'], t['rel_ci_high'], 1)}); z = {t['z']:.2f},
{pval(t['p_value'])}. Three interval methods agree, so the conclusion does not hinge on a method choice, and none of
the {num(b['n_boot'])} bootstrap resamples shows a lift &le; 0.</p>
{arm_table}
{ci_table}
{self.fig("ad_rates", f"bars are conversion rates and whiskers {c} confidence intervals. The PSA interval is wider "
          "because that arm is much smaller.")}
{self.fig("ad_bootstrap", "each bar counts re-sampled versions of the experiment with a given lift. The shaded band "
          "holds the middle 95% of them; the grey line marks no effect.")}
<h3 id="s4-power">4.5 Power and minimum detectable effect</h3>
<p>Power analysis asks how small an effect this design could reliably detect. With {num(self.n_total)} users split
{self.split}, the minimum detectable effect (MDE) at {self.power * 100:.0f}% power and &alpha; = {self.alpha:g} is
{pp(mde_now['mde_abs'])} ({pct(mde_now['mde_rel'])} relative). The observed {pp(t['abs_lift'])} is
{t['abs_lift'] / mde_now['mde_abs']:.1f}&times; that, so the test was well powered for the effect it found (power
&asymp; {pct(pw['achieved_power_at_observed'], 0)}). The split was expensive, though: the same users split 50/50
could have detected {pp(mde_5050['mde_abs'])}, and matching this test's sensitivity at 50/50 would have taken only
{num(n_match)} users ({self.n_total / n_match:.1f}&times; fewer).</p>
{power_table}
<p>A {self.split} split keeps ads in front of almost everyone during the test; the price is sensitivity, which will
matter for the smaller effects we want to measure next (budget, frequency, daypart). R4 recommends 50/50 or 80/20.</p>
{self.fig("ad_mde_split", f"for the same total number of users, the curve is the smallest lift the test could "
          f"reliably detect ({self.power * 100:.0f}% power) at each treatment share. Lower is better.")}
{self.fig("ad_power_curve", "the height of the curve is the chance that this sample flags a true lift of a given "
          "size as significant.")}
<h3 id="s4-business">4.6 Business translation</h3>
<p>The lift means about {num(inc['point'])} conversions ({c} CI {num(inc['ci_low'])}&ndash;{num(inc['ci_high'])})
would not have happened without the campaign's {millions(bz['impressions_ad_group'])} ad impressions: one incremental
conversion per {num(bz['impressions_per_incremental_conversion'])} impressions. Only
{pct(bz['share_of_ad_conversions_incremental'])} of the ad arm's {num(t['conv_t'])} conversions are incremental;
crediting all of them to the campaign would overstate its effect about {over:.1f}&times;.</p>
<p>A dollar value needs two numbers the data does not have: what a conversion is worth and what we pay per 1,000
impressions (CPM). With an illustrative {usd(self.value, 0)} per conversion, the incremental value is
&asymp;{usd_k(val['point'])} ({c} CI {usd_k(val['ci_low'])}&ndash;{usd_k(val['ci_high'])}) and the campaign breaks even
at a CPM of <b>{usd(be['point'])}</b> ({c} CI {usd(be['ci_low'])}&ndash;{usd(be['ci_high'])}): if we pay less than
that, it pays back. Put differently, cost per incremental conversion = CPM &times; {cost_per_cpm:.2f}.</p>
{biz_table}
{_callout("warn", f"Assumption, not data: {usd(self.value, 0)} per conversion",
    f"The value per conversion is a placeholder, not an estimate. Breakeven CPM scales linearly with it "
    f"({usd(self.value / 2, 0)} &rarr; {usd(be['point'] / 2)}; {usd(self.value * 2, 0)} &rarr; {usd(be['point'] * 2)}). "
    "Finance should supply the real value and our actual CPM before any dollar figure is quoted.")}
{self.fig("ad_breakeven", "pick a value per conversion on the x-axis; the line gives the highest price per 1,000 "
          f"impressions at which the campaign still pays back (band = {c} CI). Paying less than the line = profitable.")}
<h3 id="s4-caveats">4.7 Caveats</h3>
{_ul([
    "<b>Novelty effect and duration:</b> the data has no timestamps, so we cannot tell whether the lift fades as users "
    "get used to the ads, how long the test ran, or whether it covered full weekly cycles. The estimate is an average "
    "over the whole flight. The always-on holdout (R1) and assignment timestamps (R4) fix this going forward.",
    "<b>What the lift measures:</b> both arms were shown something in the same slots, so the lift is the effect of "
    "the campaign's message versus a neutral PSA, not of ads versus no ads.",
    "<b>Conversion definition:</b> the dataset does not say what a conversion is or which attribution window was "
    "used; both must be confirmed before comparing with other campaigns.",
    "<b>One flight, one budget:</b> the result does not extrapolate to 2&times; spend (Section 5, R2).",
])}
</section>"""

    # ------------------------------------------------------------------ 5 heterogeneity
    def _seg_table(self, dim: str, label: str) -> str:
        tab = self.seg[dim]
        rows = []
        for _, r in tab.iterrows():
            seg = r[dim]
            seg_txt = f"hour {int(seg)}" if dim == "most_ads_hour" else esc(str(seg))
            rows.append([seg_txt, num(r["n_t"]), num(r["n_c"]), pct(r["rate_t"], 2), pct(r["rate_c"], 2),
                         f"{pp(r['abs_lift'], sign=True)}<br><span class='sub'>{ci_pp(r['abs_ci_low'], r['abs_ci_high'])}</span>",
                         pval(r["p_value"], prefix=False), pval(r["p_adj"], prefix=False),
                         "Yes" if r["significant_adj"] else "No"])
        return _table([label, "Ad users", "PSA users", "Ad rate", "PSA rate", f"Lift ({self.conf} CI)", "p",
                       "Holm p", "Significant (Holm)"], rows, num_cols={1, 2, 3, 4, 5, 6, 7})

    def s5_heterogeneity(self) -> str:
        het, t, a, c = self.het, self.t, self.alpha, self.conf
        dims = [("most_ads_day", "Peak ad day"), ("most_ads_hour", "Peak ad hour"),
                ("exposure_bucket", "Total ads seen")]

        def seg_name(dim: str, s: str) -> str:
            return f"hour {s}" if dim == "most_ads_hour" else f"{s} ads" if dim == "exposure_bucket" else s

        def col(dim: str) -> list[str]:
            h = het[dim]
            p = h["lrt"]["p_value"]
            return [num(h["n_segments"]), f"{pval(p, prefix=False)}<br><span class='sub'>{evidence(p)}</span>",
                    num(h["n_sig_unadjusted"]), num(h["n_sig_bonferroni"]), num(h["n_sig_holm"]), num(h["n_sig_bh"]),
                    f"{h['n_segments'] * a:.2f}".rstrip("0").rstrip("."),
                    f"{esc(seg_name(dim, h['min_lift_segment']))}: {_signed(h['min_lift_pp'], 2)} pp<br>"
                    f"{esc(seg_name(dim, h['max_lift_segment']))}: {_signed(h['max_lift_pp'], 2)} pp",
                    pp(h["stratified"]["mh_risk_diff"])]
        labels = ["Segments compared", "Interaction test (LRT) p: does the lift differ by segment?",
                  "&ldquo;Significant&rdquo; segments, no correction", "&hellip; Bonferroni", "&hellip; Holm",
                  "&hellip; Benjamini&ndash;Hochberg",
                  f"False positives expected by chance alone (segments &times; &alpha; {a:g})",
                  "Lowest / highest segment lift", f"Stratified (CMH) pooled lift; overall is {pp(t['abs_lift'])}"]
        cols = [col(d) for d, _ in dims]
        summary = _table(["", *[lab for _, lab in dims]], [[labels[i], *[cl[i] for cl in cols]]
                                                          for i in range(len(labels))], num_cols={1, 2, 3},
                         stack=True, cls="grid3")
        hd, hh, he = het["most_ads_day"], het["most_ads_hour"], het["exposure_bucket"]
        day = self.seg["most_ads_day"].set_index("most_ads_day")
        min_day = hd["min_lift_segment"]
        min_day_ci0 = day.loc[min_day, "abs_ci_low"] < 0 < day.loc[min_day, "abs_ci_high"]
        e = self.expo
        low_ci0 = all(e.loc[b, "abs_ci_low"] < 0 < e.loc[b, "abs_ci_high"] for b in self.expo_low)
        holm_hours = ", ".join(f"hour {h}" for h in self.hour_holm) or "none"
        return f"""
<section id="s5">
<h2><span class="sec-num">5</span>Heterogeneity: day, hour and exposure</h2>
<p class="lede">Does the ad work better on some days or hours, and is that real or noise?</p>
<h3>5.1 Why this needs care</h3>
<p>Cutting the lift by {hd['n_segments']} days and {hh['n_segments']} hours means {hd['n_segments'] + hh['n_segments']}
separate tests. At &alpha; = {a:g}, about {(hd['n_segments'] + hh['n_segments']) * a:.1f} of them would look
&ldquo;significant&rdquo; by chance even if the ad worked identically everywhere. Two tools guard against that:</p>
{_ul([
    "<b>One interaction test per dimension</b> (likelihood-ratio test, LRT): a single question, &ldquo;does the lift "
    "differ across segments at all?&rdquo;, so there is no multiple-comparison problem.",
    "<b>Multiple-comparison corrections</b> for the per-segment tests: Bonferroni and Holm control the chance of any "
    "false positive; Benjamini&ndash;Hochberg (BH) controls the share of false positives among the hits.",
])}
<p>Note the difference: a segment being &ldquo;significant&rdquo; means its lift is above 0; it does not mean that
segment differs from the others. Only the interaction test answers the second question.</p>
{summary}
<p>The stratified (Cochran&ndash;Mantel&ndash;Haenszel) pooled lifts are all close to the overall
{pp(t['abs_lift'])}, so the headline result is robust to how users are spread across days, hours and exposure.</p>
<h3>5.2 By peak ad day: weak evidence</h3>
<p>Lift ranges from {_signed(hd['min_lift_pp'], 2)} pp ({esc(min_day)}{", CI includes 0" if min_day_ci0 else ""}) to
{_signed(hd['max_lift_pp'], 2)} pp ({esc(hd['max_lift_segment'])}). The interaction test gives
{pval(hd['lrt']['p_value'])}: {evidence(hd['lrt']['p_value'])} that the lift differs by day, not enough to move budget,
especially because the peak day is a post-assignment summary of when a user happened to see most ads, not a schedule
we set. {hd['n_sig_holm']} of {hd['n_segments']} days stay significant after Holm, which says most days have a
positive lift, not that the days differ.</p>
{self.fig("het_day", f"dots are the lift within each day and lines their {c} CIs; filled = significant after Holm "
          "correction; the dotted line is the overall lift. Overlapping lines mean the days are hard to tell apart.")}
{self._seg_table("most_ads_day", "Peak ad day")}
<h3>5.3 By peak ad hour: no evidence</h3>
<p>{hh['n_sig_unadjusted']} of {hh['n_segments']} hours look significant before correction; with
{hh['n_segments']} tests about {hh['n_segments'] * a:.1f} false positives are expected by chance alone, and only
{hh['n_sig_holm']} survives Holm ({holm_hours}). The interaction test ({pval(hh['lrt']['p_value'])}) finds no evidence
that the lift differs by hour.</p>
{self.fig("het_hour", "same reading as the day chart, for 24 hours. Night hours have very few PSA users, hence very "
          "wide intervals.")}
<details class="more-table"><summary>Per-hour table ({hh['n_segments']} rows)</summary>
{self._seg_table("most_ads_hour", "Peak ad hour")}</details>
<h3 id="s5-exposure">5.4 By total ads seen: a saturation pattern (exploratory)</h3>
<p>Lift is not detectable for users who saw &le; {self.expo_low_max} ads ({pct(self.share_expo_low, 0)} of users;
{"all their CIs include 0" if low_ci0 else "small lifts"}), rises to {pp(e.loc[PEAK_EXPOSURE[0], 'abs_lift'])} at
{esc(PEAK_EXPOSURE[0])} and {pp(e.loc[PEAK_EXPOSURE[1], 'abs_lift'])} at {esc(PEAK_EXPOSURE[1])} ads, and is
indistinguishable from 0 above {self.top_cut} ads (only {num(e.loc[TOP_EXPOSURE, 'n_c'])} PSA users there, so the CI is
wide: {ci_pp(e.loc[TOP_EXPOSURE, 'abs_ci_low'], e.loc[TOP_EXPOSURE, 'abs_ci_high'])}). The interaction test is
clear ({pval(he['lrt']['p_value'])}). But the PSA rate itself climbs from {pct(e.loc[C.EXPOSURE_LABELS[0], 'rate_c'], 2)}
({esc(C.EXPOSURE_LABELS[0])} ads) to {pct(e.loc[PEAK_EXPOSURE[1], 'rate_c'], 2)} ({esc(PEAK_EXPOSURE[1])} ads), which shows
that exposure mostly measures how active a user is: heavy users see more ads and convert more regardless.</p>
{self.fig("het_exposure", "conversion rate per arm within each exposure bucket. The PSA (grey) rate also rises "
          "steeply with exposure: heavy users convert more anyway.")}
{self.fig("het_exposure_forest", f"the same comparison as a lift per bucket with {c} CIs.")}
{self._seg_table("exposure_bucket", "Total ads seen")}
{_callout("warn", "Post-assignment: a hypothesis, not a result",
    "The number of ads a user saw was determined after assignment and reflects how active they are, so this "
    "dose-response pattern cannot be read causally. It is the hypothesis behind the budget / frequency test (R2): "
    "if extra spend mostly adds impressions for users who are already saturated, doubling the budget would buy "
    "little.")}
<p class="so-what"><b>So what.</b> Do not re-plan spend by day or hour (<a href="#recommendations">R3</a>); test a
higher budget or a frequency cap before scaling (<a href="#recommendations">R2</a>).</p>
</section>"""

    # ------------------------------------------------------------------ 6 gate experiment
    def s6_gate(self) -> str:
        g, srm, g1, g7, c = self.gate, self.gate["srm"], self.g1, self.g7, self.conf
        rounds = g["rounds"]
        res_rows = []
        for name, m in (("D1 retention", g1), ("D7 retention (primary)", g7)):
            res_rows.append([name, pct(m["rate_c"], 2), pct(m["rate_t"], 2),
                             f"{pp(m['abs_lift'], sign=True)}<br><span class='sub'>{ci_pp(m['abs_ci_low'], m['abs_ci_high'])}</span>",
                             f"{spct(m['rel_lift'], 1)}", pval(m["p_value"], prefix=False),
                             pct(1 - m["boot_share_ge_0"], 1)])
        res_table = _table(["Metric", "gate_30 (control)", "gate_40 (treatment)", f"Difference ({c} CI)", "Relative",
                            "p", "Bootstrap draws below 0"], res_rows, num_cols={1, 2, 3, 4, 5, 6})
        reach_rows = []
        for reached, label in ((True, f"Played {GATE_LEVEL}+ rounds"), (False, f"Played fewer than {GATE_LEVEL} rounds")):
            r = self.by_reach[reached]
            reach_rows.append([f"{label} ({num(r.n_t + r.n_c)})", pct(r.rate_c, 2), pct(r.rate_t, 2),
                               f"{pp(r.abs_lift, sign=True)}<br><span class='sub'>{ci_pp(r.abs_ci_low, r.abs_ci_high)}</span>",
                               pval(r.p_value, prefix=False)])
        reach_table = _table(["Players", "gate_30 D7", "gate_40 D7", f"Difference ({c} CI)", "p"], reach_rows,
                             num_cols={1, 2, 3, 4})
        rn, ry = self.by_reach[False], self.by_reach[True]
        return f"""
<section id="s6">
<h2><span class="sec-num">6</span>Gate experiment (Cookie Cats)</h2>
<p class="lede">Should the first gate move from level {GATE_LEVEL} to level 40?</p>
{_callout("warn", "Sample-ratio warning: results reported, not certified",
    f"Each version should get 50% of players. We observe {num(srm['n_t'])} in gate_40 "
    f"({pct(srm['observed_share_t'], 2)}) and {num(srm['n_c'])} in gate_30. The chi-square test gives "
    f"{pval(srm['p_value'])}: below the conventional 0.01 level, but above the stricter {srm['threshold']:g} "
    f"threshold this project uses to flag SRM automatically (so <code>srm.flag</code> in results.json is false). We "
    f"treat it as a <b>warning that blocks certification</b>: the estimates below are reported, but they cannot be "
    f"certified until assignment is debugged (bucketing bugs, players dropped after assignment, or logging loss in "
    f"one version).")}
<h3>6.1 Hypothesis and metrics</h3>
<p>Moving the first gate (a forced wait or in-app purchase) from level {GATE_LEVEL} to level 40 changes how many
players stay. Null hypothesis: no difference. <b>Primary metric:</b> D7 retention (long-term health).
<b>Secondary:</b> D1 retention. <b>Guardrail:</b> engagement, i.e. rounds played in the first 14 days. Decision rule:
ship gate_40 only if D7 is not worse.</p>
<h3>6.2 Results</h3>
<p>gate_40 retained {pct(g7['rate_t'], 2)} of players on Day 7 vs {pct(g7['rate_c'], 2)} for gate_30:
<b>{pp(g7['abs_lift'], sign=True)}</b> ({c} CI {ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])}; relative
{spct(g7['rel_lift'], 1)}; {pval(g7['p_value'])}). In {pct(1 - g7['boot_share_ge_0'], 1)} of {num(self.n_boot)}
bootstrap resamples gate_40 is lower. D1 points the same way ({pp(g1['abs_lift'], sign=True)}, {c} CI
{ci_pp(g1['abs_ci_low'], g1['abs_ci_high'])}, {pval(g1['p_value'])}) but its interval includes 0.</p>
{res_table}
{self.fig("gate_rates", f"grey = gate_30 (control), blue = gate_40 (treatment); whiskers are {c} CIs.")}
{self.fig("gate_bootstrap", f"{num(self.n_boot)} re-sampled differences each for D1 and D7. Mass to the left of 0 "
          "means gate_40 retains fewer players.")}
<h3>6.3 Power</h3>
<p>With about {num(min(srm['n_t'], srm['n_c']), 0)} players per arm the test could detect a D1 difference of
{pp(g1['mde']['mde_abs'])} or a D7 difference of {pp(g7['mde']['mde_abs'])} with {self.power * 100:.0f}% power. The D7
drop ({pp(-g7['abs_lift'])}) is just above that bar; the D1 drop ({pp(-g1['abs_lift'])}) is below it, so
&ldquo;no significant D1 change&rdquo; means &ldquo;too small to detect&rdquo;, not &ldquo;no change&rdquo;.</p>
<h3>6.4 Guardrail: engagement</h3>
<p>Median rounds in the first 14 days: {num(rounds['median_t'])} (gate_40) vs {num(rounds['median_c'])} (gate_30); mean
{num(rounds['mean_t'], 2)} vs {num(rounds['mean_c'], 2)}; Mann&ndash;Whitney {pval(rounds['mannwhitney_p'])}. No clear
difference in how much people play. In the engagement curve by version (<a href="#chart-ret_engagement_curve">Section
3.3</a>) the two versions are never more than {self.curve_gap_pp:.1f} pp apart at any point up to
{CURVE_MAX_ROUNDS} rounds.</p>
<h3>6.5 Where does the D7 gap sit? (descriptive)</h3>
{reach_table}
<p>Players with fewer than {GATE_LEVEL} rounds had almost certainly not reached level {GATE_LEVEL}, where the two
versions first differ, so we would expect no difference among them. Their D7 is nevertheless
{pp(-rn.abs_lift)} lower in gate_40 ({pval(rn.p_value)}): borderline and possibly chance, but consistent with the SRM
warning that the two arms may not be fully comparable. Among players who reached {GATE_LEVEL} rounds the gap is
larger ({pp(ry.abs_lift, sign=True)}) but less precise ({c} CI {ci_pp(ry.abs_ci_low, ry.abs_ci_high)}). Splits by
rounds are descriptive only.</p>
<div class="decision"><div class="decision-label">Decision</div>
<p><b>Do not ship gate_40; keep the gate at level {GATE_LEVEL} (R5).</b> D7 is lower with an interval that excludes
0, D1 points the same way, and no change is the safe default, so the SRM warning changes our confidence in the
<i>size</i> of the effect, not the decision. Shipping gate_40 would cost &asymp;{-g7['abs_lift'] * 10000:.0f} D7-retained
players per 10,000 installs (&asymp;{-g7['abs_lift'] * srm['n_t']:.0f} across a {num(srm['n_t'])}-player cohort).
Before any re-test: audit assignment (bucketing logs, an A/A test).</p></div>
</section>"""

    # ------------------------------------------------------------------ 7 decision
    def s7_decision(self) -> str:
        t, c, pw = self.t, self.conf, self.pw
        hd, hh = self.het["most_ads_day"], self.het["most_ads_hour"]
        g7, srm = self.g7, self.gate["srm"]
        mde_now, mde_5050 = pw["mde_current"]["mde_abs"], pw["mde_if_5050_same_total"]["mde_abs"]
        n10 = pw["total_n_for_10pct_rel_lift"]
        rows = [
            ["Did the campaign drive conversions?", _chip("good", "Keep"),
             f"{pp(t['abs_lift'], sign=True)} ({c} CI {ci_pp(t['abs_ci_low'], t['abs_ci_high'])}); SRM and exposure "
             "parity pass", "High", "R1"],
            ["Double the budget?", _chip("warn", "Test first"),
             "Budget was not varied; exposure cut hints at saturation, but exposure is post-assignment",
             "Not answerable from this data", "R2"],
            ["Re-time spend by day / hour?", _chip("stop", "Don't (yet)"),
             f"Day: {pval(hd['lrt']['p_value'])} (weak); hour: {pval(hh['lrt']['p_value'])} (none)", "Low", "R3"],
            ["How should the next test be designed?", _chip("info", "Fix design"),
             f"{self.split} split cost {mde_now / mde_5050:.1f}&times; sensitivity; no timestamps; no guardrails",
             "&ndash;", "R4"],
            [f"Move the gate from level {GATE_LEVEL} to 40?", _chip("stop", "Don't ship"),
             f"D7 {pp(g7['abs_lift'], sign=True)} ({c} CI {ci_pp(g7['abs_ci_low'], g7['abs_ci_high'])}); SRM "
             f"warning ({pval(srm['p_value'])})", "Direction clear; size not certified", "R5"],
            ["Which new users leave first?", _chip("info", "Act"),
             f"{pct(self.low_share, 0)} of installs play fewer than {self.low_cut} rounds, D7 &le; "
             f"{pct(self.low_d7_max)}; Day-1 returners {self.d7_yes / self.d7_no:.1f}&times; as likely to stay",
             "Correlational: validate by experiment", "R6"],
        ]
        table = _table(["Question", "Decision", "Evidence", "Confidence", "See"], rows, stack=True)
        return f"""
<section id="s7">
<h2><span class="sec-num">7</span>Decision and recommendations</h2>
<p class="lede">What should we do, who owns it, and how will we know it worked?</p>
{table}
<p>Owners, expected impact, measurement and risk for R1&ndash;R6 are in the
<a href="#recommendations">recommendations table</a> at the top.</p>
<h3>How we will know it worked</h3>
{_ul([
    "<b>Always-on holdout (R1):</b> 5&ndash;10% of users keep seeing PSAs; a monthly readout of incremental "
    "conversions and cost per incremental conversion shows whether the effect holds or fades.",
    "<b>Finance check (R1):</b> real value per conversion and actual CPM replace the placeholder; the campaign stays "
    "only while actual CPM is below breakeven.",
    "<b>Budget / frequency test (R2):</b> the go / no-go for scaling is the marginal incremental conversions per "
    "extra $1K, not the average.",
    "<b>Gate (R5):</b> D7 stays at the gate_30 level; an assignment audit precedes any re-test.",
    "<b>Onboarding (R6):</b> a randomized test with D7 as the primary metric decides whether the Day-1 change ships.",
])}
<h3>Next experiment at a glance (R2 + R4)</h3>
{_ul([
    "<b>Question:</b> what does extra spend buy?",
    "<b>Arms:</b> current plan vs 2&times; budget (or a frequency cap), randomized by user, plus the small PSA "
    "holdout to keep measuring the absolute lift.",
    "<b>Split:</b> 50/50 or 80/20 between the budget arms.",
    "<b>Metrics:</b> primary = incremental conversions per extra $1K (marginal iROAS); secondary = conversion "
    "rate; guardrails = unsubscribe / complaint rate, CPA, ads per user.",
    f"<b>Size:</b> use the sample-size calculator (dashboard page 7). For reference, detecting a 10% relative change "
    f"on a {pct(t['rate_c'], 2)} base needs &asymp;{num(n10['0.5'])} users at 50/50 or &asymp;{num(n10['0.8'])} at "
    f"80/20, vs &asymp;{num(n10['0.96'])} at {self.split}.",
    "<b>Duration and logging:</b> whole weeks, with assignment timestamps so novelty effects can be checked.",
])}
</section>"""

    # ------------------------------------------------------------------ 8 limitations
    def s8_limits(self) -> str:
        return f"""
<section id="s8">
<h2><span class="sec-num">8</span>Limitations and what data I would ask for next</h2>
<h3>Limitations</h3>
{_ul([
    "<b>No timestamps</b> in either dataset: no novelty-effect, duration, seasonality or cohort-trend analysis.",
    f"<b>No revenue or cost:</b> every dollar figure rests on an illustrative {usd(self.value, 0)} per conversion and "
    "an unknown CPM.",
    f"<b>Intended allocation undocumented:</b> the {self.split} SRM check is weak; exposure parity carries more "
    "weight.",
    "<b>Post-assignment variables:</b> total ads, peak day and peak hour describe what happened after assignment; "
    "all segment and dose-response results are exploratory.",
    "<b>Unknown conversion definition</b> and attribution window.",
    "<b>One flight at one budget:</b> nothing in this test varies spend, so a 2&times; budget is an extrapolation.",
    "<b>Gate SRM unresolved:</b> the gate effect size is not certified.",
    "<b>Rounds overlap the D7 window:</b> engagement and retention are measured over overlapping periods, so their "
    "link may run both ways.",
    "<b>Very large samples:</b> tiny differences become &ldquo;significant&rdquo;, so effect sizes (pp, Cram&eacute;r's "
    "V) are reported next to every p-value.",
    "<b>Two different products:</b> ad conversion and game retention cannot be linked, and both datasets are public "
    "stand-ins for our own logs.",
])}
<h3>What data I would ask for next</h3>
{_ul([
    "<b>Assignment log</b>: user, arm, assignment timestamp, randomization unit and the intended split (makes the SRM "
    "check meaningful; enables novelty and duration analysis).",
    "<b>Impression-level exposure log</b> with timestamps, placement and cost (real frequency analysis, actual CPM, "
    "cost per incremental conversion).",
    "<b>Revenue or margin per conversion</b> (or LTV) from Finance.",
    "<b>The conversion event definition</b> and attribution window.",
    "<b>Guardrail events</b>: unsubscribes, ad hides / complaints, uninstalls.",
    "<b>Pre-assignment covariates</b> (prior activity, platform, country, acquisition channel) for balance checks and "
    "variance reduction (CUPED).",
    "<b>For the game</b>: install dates, platform and country, level-progress and session events (where exactly "
    "players stop), and the assignment-service logs to debug the SRM.",
])}
</section>"""

    # ------------------------------------------------------------------ appendix
    def appendix(self) -> str:
        t, c, a = self.t, self.conf, self.alpha
        pw = self.pw
        v_mid = sum(b["cramers_v"] for b in self.ad["balance"]) / len(self.ad["balance"])
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
             "the effect is; with very large samples, tiny differences get tiny p-values."),
            ("Sample ratio mismatch (SRM)",
             "A check that each arm received the share of users it was supposed to. If a 50/50 test ends up "
             "noticeably uneven, something in assignment or logging is broken, and the arms may no longer be "
             "comparable, so no result can be trusted until that is explained."),
            ("Bootstrap",
             f"Re-running the experiment {num(self.n_boot)} times on computer-generated resamples of the data and "
             "looking at the spread of results. It gives a confidence interval without assuming a bell curve, and a "
             "plain-language summary such as &ldquo;none of the resamples showed a lift &le; 0&rdquo;."),
            ("Minimum detectable effect (MDE) and power",
             f"Power is the chance a test detects an effect of a given size if it is real (the standard is "
             f"{self.power * 100:.0f}%). The MDE is the smallest effect a design can detect at that power. This test's "
             f"MDE was {pp(pw['mde_current']['mde_abs'])}; with the same users split 50/50 it would have been "
             f"{pp(pw['mde_if_5050_same_total']['mde_abs'])}. Effects smaller than the MDE can be real but go "
             "undetected."),
            ("Multiple comparisons (Bonferroni, Holm, Benjamini&ndash;Hochberg)",
             f"Running many tests at &alpha; = {a:g} produces about one false &ldquo;hit&rdquo; per "
             f"{1 / a:.0f} tests by chance. Bonferroni and Holm raise the bar so that the chance of <i>any</i> false hit "
             "stays at &alpha; (Holm is the less strict of the two); Benjamini&ndash;Hochberg controls the "
             "<i>share</i> of false hits among the results."),
            ("Interaction test (likelihood-ratio test)",
             f"One test of whether the treatment effect differs across segments (e.g. across the "
             f"{self.het['most_ads_day']['n_segments']} days), instead of comparing segments pairwise. It compares a "
             "model where the lift is the same everywhere with one where each segment has its own lift."),
            ("Stratified (Cochran&ndash;Mantel&ndash;Haenszel) estimate",
             "The overall lift computed within each segment and then averaged. If it matches the simple overall "
             "lift, the result is not an artefact of how users are spread across segments."),
            ("Post-assignment variable",
             "Something measured after users were randomized (here: number of ads seen, peak ad day and hour). Because "
             "the treatment can influence it, comparing arms within its segments no longer compares like with like; "
             "such cuts are exploratory and must not be used as controls."),
            ("Novelty effect",
             "Users react to something new more strongly at first, and the effect fades as they get used to it. "
             "Spotting it needs dates; without them, the measured lift is an average over the whole test."),
            ("Incremental conversions and breakeven CPM",
             "Incremental conversions are those that would not have happened without the ads (lift &times; users "
             "who saw ads). Breakeven CPM is the highest price per 1,000 impressions at which the value of those "
             "conversions still covers the ad cost."),
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
<p>The step-by-step analysis, exported to HTML (same folder as this report):</p>
{nb_list}
{docs_html}
<h3>Reproducibility</h3>
<p>Every number in this report is read from <code>reports/results.json</code> when the report is built, and every chart
comes from <code>src/catalog.py</code>, the same figures the Streamlit dashboard shows by default
(<code>streamlit run dashboard/app.py</code>). Rebuild everything with <code>python run.py</code> (this report alone:
<code>python run.py --only report</code>). Seed {cfg['seed']}, {num(cfg['n_bootstrap'])} bootstrap resamples,
&alpha; = {cfg['alpha']:g}, power = {cfg['power']:g}.</p>
{extra_html}
</section>"""

    # ------------------------------------------------------------------ page
    def toc(self, cls: str) -> str:
        items = [("summary", "Summary"), ("answers", "Answers for the PM"), ("recommendations", "Recommendations"),
                 ("s1", "1&nbsp; Business question and scope"), ("s2", "2&nbsp; Data and quality checks"),
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
        description = (f"Ad vs PSA experiment ({pp(t['abs_lift'], sign=True)} conversion) and new-player retention "
                       f"readout for the Growth PM.")
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
        inc, be = bz["incremental_conversions"], bz["breakeven_cpm_usd"]
        g7 = self.g7
        n10 = self.pw["total_n_for_10pct_rel_lift"]
        share_inc = bz["share_of_ad_conversions_incremental"]

        def p100(x: float, nd: int = 2) -> str:   # proportion difference -> "0.77" (per 100 people)
            return _plain(x * 100, nd)

        def users(n: float) -> str:               # 181,074 -> "181,000"; 1,178,866 -> "1.2 million"
            return f"{n / 1e6:.1f} million" if n >= 1e6 else approx(n, 1000)

        md = f"""# Executive summary: ad campaign and new-player retention

**To:** Growth PM · **From:** Product Analyst, Growth · **Date:** {self.today}

Full analysis: [report.html](report.html) (opens in any browser). Interactive version: `streamlit run dashboard/app.py`.

## Bottom line

**Keep the ad campaign running at today's budget, but test a bigger budget before doubling it.** The campaign clearly brought in extra conversions, but this test never tried a higher budget, so it can't tell us whether more spend would pay off. **Keep the game's first gate at level {GATE_LEVEL}**, and **focus retention work on bringing new players back the day after they install**, which is where most of them are lost.

## What we found

1. **The campaign worked.** {pct(t['rate_t'], 2)} of people who saw the ads converted, vs {pct(t['rate_c'], 2)} of a similar group shown a public-service ad instead: {p100(t['abs_lift'])} more conversions per 100 people ({spct(t['rel_lift'])}). We're {c} confident the true increase is between {p100(t['abs_ci_low'])} and {p100(t['abs_ci_high'])} per 100 people. That is roughly {approx(inc['point'], 100)} extra conversions (likely {approx(inc['ci_low'], 100)} to {approx(inc['ci_high'], 100)}) from {bz['impressions_ad_group'] / 1e6:.1f} million ad impressions. Only about {pct(share_inc, 0)} of the ad group's conversions were caused by the ads; the rest would have happened anyway.
2. **Whether doubling the budget pays off is still unknown.** If a conversion is worth {usd(self.value, 0, md=True)} (a placeholder; there is no revenue data), the campaign pays for itself as long as 1,000 ad impressions cost less than about {usd(be['point'], md=True)} (likely {usd(be['ci_low'], md=True)} to {be['ci_high']:.2f}). There are hints of diminishing returns: the {pct(self.share_expo_low, 0)} of users who saw {self.expo_low_max} ads or fewer show no measurable benefit, and the benefit peaks at {self.peak_range} ads and disappears above {self.top_cut}. Heavy users convert more anyway, so this needs a proper test. Shifting spend to particular days or hours isn't supported either.
3. **New players leave early, and the least engaged leave first.** {pct(1 - o['retention_1'], 0)} don't come back the day after installing; {pct(o['retention_7'], 0)} are back a week later. Almost half ({pct(self.low_share, 0)}) play fewer than {self.low_cut} rounds, and at most {pct(self.low_d7_max)} of them are back after a week. Players who return on Day 1 are {self.d7_yes / self.d7_no:.1f} times as likely to be back a week later ({pct(self.d7_yes, 0)} vs {pct(self.d7_no, 0)}). This shows who leaves, not why.
4. **Moving the first gate from level {GATE_LEVEL} to 40 made one-week retention worse**: {pct(g7['rate_t'])} vs {pct(g7['rate_c'])}, about {-g7['abs_lift'] * 10000:.0f} fewer retained players per 10,000 installs (we're {c} confident the drop is between {p100(-g7['abs_ci_high'], 1)} and {p100(-g7['abs_ci_low'], 1)} percentage points). The test groups were not split 50/50 as planned, which can signal a technical problem, so the size of the effect is not confirmed; keeping level {GATE_LEVEL} is the safe choice either way.

## What we recommend

| | Owner | Action | How we'll know it worked |
|---|---|---|---|
| R1 | Growth PM | Keep the campaign at today's budget; keep 5–10% of users seeing public-service ads instead, as an ongoing comparison group. | Extra conversions and cost per extra conversion, monthly; Finance confirms we pay less than break-even. |
| R2 | Growth PM + media buyer | Before doubling, test it: part of the audience gets twice the spend (or a cap on how often they see ads). | Extra conversions per additional USD 1,000. |
| R3 | Media buyer | Keep the current day and hour schedule; the differences are mostly noise. | A planned test, if timing still matters. |
| R4 | Analytics + Engineering | Next ad test: a 50/50 or 80/20 split instead of {self.split}, entry timestamps, success and safety metrics agreed up front. | A 10% change becomes detectable with about {users(n10['0.5'])} users instead of {users(n10['0.96'])}. |
| R5 | Game PM | Keep the gate at level {GATE_LEVEL}; find the cause of the uneven groups before any re-test. | One-week retention stays at the level-{GATE_LEVEL} baseline ({pct(g7['rate_c'])}). |
| R6 | Onboarding PM | Test a Day-1 comeback or onboarding change for players with fewer than {self.low_cut} rounds. | One-week retention in a randomized test. |

## Risks

- **Money figures rest on a placeholder** ({usd(self.value, 0, md=True)} per conversion); break-even moves in proportion to the real value.
- **No dates in the data**, so we can't see whether the ad effect wears off.
- **Retention patterns are correlations**: they show where to test, not guaranteed wins.
- **The gate test's uneven groups** leave its effect size unconfirmed (the decision is the safe default regardless).

## Next steps

1. **Finance:** the real value of a conversion and our actual cost per 1,000 impressions (confirms R1).
2. **Analytics + media buyer:** set up the comparison group (R1) and size the budget test (R2).
3. **Engineering:** audit how players were assigned in the gate test (R5).
4. **Onboarding PM + Analytics:** scope the Day-1 experiment (R6).
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
section, h3 { scroll-margin-top: 16px; }
.sec-num { display: inline-block; min-width: 30px; height: 30px; line-height: 30px; text-align: center;
           border-radius: 6px; background: var(--ink); color: #fff; font-size: 15px; margin-right: 10px;
           vertical-align: 2px; padding: 0 6px; }
p { margin: 0 0 12px; }
.lede { font-size: 17px; color: var(--ink-2); }
ul { padding-left: 22px; margin: 0 0 14px; }
li { margin: 4px 0; }
blockquote { margin: 0 0 14px; padding: 10px 16px; border-left: 3px solid var(--rule-2); background: var(--surface);
             color: var(--ink-2); font-style: italic; border-radius: 0 6px 6px 0; }
.so-what { background: var(--accent-soft); border-radius: var(--radius); padding: 12px 16px; }
.sub { color: var(--ink-3); font-size: 12.5px; }

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
  table.grid3 tr { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 12px; }
  table.grid3 td:first-child { grid-column: 1 / -1; font-weight: 600; padding-bottom: 4px; }
  table.grid3 td::before { font-size: 10.5px; letter-spacing: .02em; }
  table.tbl:not(.stack) tr > :first-child { position: sticky; left: 0; background: var(--surface);
                                             box-shadow: 1px 0 0 var(--rule); }
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
  var NARROW = 600;
  function wrapLabel(s, n) {
    var words = String(s).split(" "), lines = [], cur = "";
    words.forEach(function (w) {
      if (cur && (cur + " " + w).length > n) { lines.push(cur); cur = w; } else { cur = cur ? cur + " " + w : w; }
    });
    if (cur) lines.push(cur);
    return lines.join("<br>");
  }
  function titleText(t) { return !t ? "" : (typeof t === "string" ? t : (t.text || "")); }
  function adapt(gd) {
    var P = window.Plotly;
    if (!P || !gd || !gd.layout || !gd._fullLayout) return;
    var narrow = gd.getBoundingClientRect().width < NARROW;
    if (gd.__narrow === narrow) return;
    var data = gd.data || [];
    var hbar = data.filter(function (t) { return t.orientation === "h" && t.y; })[0];
    if (!gd.__orig) {
      var m = gd.layout.margin || {}, f = gd.layout.font || {};
      gd.__orig = { l: m.l, r: m.r, size: f.size, xtitle: titleText((gd.layout.xaxis || {}).title),
                    text: hbar && hbar.text ? Array.prototype.slice.call(hbar.text).map(String) : null,
                    pos: data.map(function (t) { return t.textposition; }) };
    }
    var o = gd.__orig, upd = {};
    if (narrow) {
      upd["margin.l"] = Math.min(o.l == null ? 80 : o.l, 40);
      upd["margin.r"] = hbar ? 20 : 12;
      upd["font.size"] = 11;
      if (o.xtitle.length > 34) upd["xaxis.title.text"] = wrapLabel(o.xtitle, 30);
      if (hbar) {
        var cats = Array.prototype.slice.call(hbar.y).map(String);
        upd["yaxis.tickmode"] = "array";
        upd["yaxis.tickvals"] = cats;
        upd["yaxis.ticktext"] = cats.map(function (c) { return wrapLabel(c, 16); });
      }
    } else {
      upd["margin.l"] = o.l; upd["margin.r"] = o.r; upd["font.size"] = o.size;
      if (o.xtitle.length > 34) upd["xaxis.title.text"] = o.xtitle;
      if (hbar) { upd["yaxis.tickmode"] = null; upd["yaxis.tickvals"] = null; upd["yaxis.ticktext"] = null; }
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
    });
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
