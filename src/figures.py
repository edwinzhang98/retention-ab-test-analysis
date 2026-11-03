"""Plotly figure builders shared by the Streamlit app, the notebooks and the
HTML report, so every surface shows the *same* chart.

Conventions
- Treatment (ad / gate_40) = blue, control (psa / gate_30) = grey (emphasis pattern).
- Rates are shown in %, differences in percentage points (pp).
- Every figure has a title with units and a one-sentence takeaway as subtitle.
- One y-axis per chart (no dual axes). CIs drawn as whiskers / bands.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import stats as S

# ------------------------------------------------------------------ style
BLUE = "#2a78d6"        # treatment / primary series
BLUE_LIGHT = "#86b6ef"
GREY = "#8f8e88"        # control
GREY_LIGHT = "#c9c8c2"
ORANGE = "#eb6834"      # second metric (e.g. D7 next to D1)
INK = "#1f1f1d"
INK_2 = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#ffffff"
ARM_COLORS = {"ad": BLUE, "psa": GREY, "gate_40": BLUE, "gate_30": GREY}
ARM_NAMES = {"ad": "Ad (treatment)", "psa": "PSA (control)",
             "gate_40": "gate_40 (treatment)", "gate_30": "gate_30 (control)"}
METRIC_COLORS = {"retention_1": BLUE, "retention_7": ORANGE}
METRIC_NAMES = {"retention_1": "D1 retention", "retention_7": "D7 retention"}

FONT = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"


def esc(text: str) -> str:
    """Plotly's static exporter treats $...$ as LaTeX; use the HTML entity instead."""
    return text.replace("$", "&#36;")


def wrap(text: str, width: int = 118) -> str:
    """Wrap a subtitle onto several lines at word boundaries (Plotly doesn't wrap)."""
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "<br>".join(lines)


def _layout(fig: go.Figure, title: str, subtitle: str | None = None, height: int = 420,
            xaxis_title: str | None = None, yaxis_title: str | None = None, legend: bool = True) -> go.Figure:
    t = f"<b>{esc(title)}</b>"
    n_sub_lines = 0
    if subtitle:
        sub = wrap(esc(subtitle))
        n_sub_lines = sub.count("<br>") + 1
        t += f"<br><span style='font-size:13px;color:{INK_2}'>{sub}</span>"
    top = 58 + 19 * n_sub_lines
    fig.update_layout(
        title=dict(text=t, x=0, xanchor="left", xref="container", y=1, yref="container", yanchor="top",
                   pad=dict(t=14, l=12), font=dict(size=16, color=INK)),
        font=dict(family=FONT, size=13, color=INK),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        height=height + 19 * max(0, n_sub_lines - 1), margin=dict(l=64, r=28, t=top, b=100 if legend else 60),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, size=12, color=INK), bordercolor=GRID),
        showlegend=legend,
        legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                    font=dict(size=12),
                    bgcolor="rgba(0,0,0,0)"),
        bargap=0.35, bargroupgap=0.08,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID, title=xaxis_title,
                     zeroline=False, title_font=dict(size=12, color=INK_2))
    fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=1, linecolor=GRID, zeroline=False,
                     title=yaxis_title, title_font=dict(size=12, color=INK_2))
    return fig


def _pct(x):
    return np.asarray(x, dtype=float) * 100


# ================================================================== experiments
def fig_arm_rates(arms: pd.DataFrame, title: str, subtitle: str | None = None,
                  ytitle: str = "Conversion rate (%)", height: int = 400) -> go.Figure:
    """Bar per arm with 95% Wilson CI whiskers.
    arms columns: arm, rate, ci_low, ci_high, n, conversions."""
    fig = go.Figure()
    for _, r in arms.iterrows():
        fig.add_bar(
            x=[ARM_NAMES.get(r.arm, r.arm)], y=[r.rate * 100], name=ARM_NAMES.get(r.arm, r.arm),
            marker=dict(color=ARM_COLORS.get(r.arm, BLUE), cornerradius=4),
            error_y=dict(type="data", symmetric=False, array=[(r.ci_high - r.rate) * 100],
                         arrayminus=[(r.rate - r.ci_low) * 100], color=INK_2, thickness=1.5, width=8),
            text=[f"{r.rate*100:.2f}%"], textposition="outside", textfont=dict(color=INK),
            cliponaxis=False,
            customdata=[[int(r.n), int(r.conversions), r.ci_low * 100, r.ci_high * 100]],
            hovertemplate="%{x}<br>Rate %{y:.3f}%<br>95% CI %{customdata[2]:.3f}% to %{customdata[3]:.3f}%"
                          "<br>Users %{customdata[0]:,}<br>Conversions %{customdata[1]:,}<extra></extra>",
        )
    _layout(fig, title, subtitle, height=height, yaxis_title=ytitle, legend=False)
    fig.update_yaxes(rangemode="tozero")
    return fig


def arm_table(conv_t, n_t, conv_c, n_c, t="ad", c="psa", alpha=0.05) -> pd.DataFrame:
    rows = []
    for arm, k, n in ((c, conv_c, n_c), (t, conv_t, n_t)):
        lo, hi = S.wilson_ci(k, n, alpha)
        rows.append({"arm": arm, "rate": k / n, "ci_low": lo, "ci_high": hi, "n": n, "conversions": k})
    return pd.DataFrame(rows)


def fig_bootstrap(draws: np.ndarray, ci: tuple[float, float], point: float, title: str,
                  subtitle: str | None = None, xtitle: str = "Difference in conversion rate, treatment − control (pp)",
                  height: int = 380) -> go.Figure:
    """Histogram of bootstrap differences (inputs in proportions; shown in pp)."""
    d = _pct(draws)
    fig = go.Figure()
    fig.add_histogram(x=d, nbinsx=80, marker=dict(color=BLUE_LIGHT, line=dict(color=SURFACE, width=1)),
                      name="Bootstrap draws", hovertemplate="%{x:.3f} pp<br>%{y} draws<extra></extra>")
    lo, hi = ci[0] * 100, ci[1] * 100
    fig.add_vrect(x0=lo, x1=hi, fillcolor=BLUE, opacity=0.08, line_width=0)
    for x, lab in ((lo, f"2.5%: {lo:.2f}"), (hi, f"97.5%: {hi:.2f}")):
        fig.add_vline(x=x, line=dict(color=BLUE, width=1.5))
        fig.add_annotation(x=x, y=1, yref="paper", text=lab, showarrow=False, yanchor="bottom",
                           font=dict(size=11, color=INK_2))
    fig.add_vline(x=point * 100, line=dict(color=INK, width=2))
    xmin = min(d.min(), 0)
    xmax = max(d.max(), 0)
    if xmin <= 0 <= xmax:
        fig.add_vline(x=0, line=dict(color=GREY, width=1.5))
        fig.add_annotation(x=0, y=0.92, yref="paper", text="no effect", showarrow=False, xanchor="left",
                           xshift=4, font=dict(size=11, color=INK_2))
    _layout(fig, title, subtitle, height=height, xaxis_title=xtitle, yaxis_title="Bootstrap draws (count)",
            legend=False)
    return fig


def fig_lift_forest(tab: pd.DataFrame, seg_col: str, title: str, subtitle: str | None = None,
                    overall_lift: float | None = None, sig_col: str = "differs_adj",
                    seg_title: str = "", height: int | None = None, ci_cols=("abs_ci_low", "abs_ci_high"),
                    sig_label: str | None = None, nonsig_label: str | None = None) -> go.Figure:
    """Dot + 95% CI per segment for the absolute lift (pp).
    Filled vs hollow markers encode `sig_col`:
      differs_adj      -> segment's lift differs from the other segments' (heterogeneity question; default)
      significant_adj  -> segment's lift differs from zero"""
    if sig_label is None:
        sig_label = ("Lift differs from other segments (after correction)" if sig_col == "differs_adj"
                     else "Lift ≠ 0 (after correction)")
    if nonsig_label is None:
        nonsig_label = ("Not distinguishable from other segments" if sig_col == "differs_adj"
                        else "Lift not distinguishable from 0")
    t = tab.copy()
    t["seg_label"] = t[seg_col].astype(str)
    lo, hi = _pct(t[ci_cols[0]]), _pct(t[ci_cols[1]])
    y = t["seg_label"].tolist()
    fig = go.Figure()
    sig = t[sig_col].to_numpy(dtype=bool)
    has_rest = "diff_vs_rest" in t.columns
    diff_rest = _pct(t["diff_vs_rest"]) if has_rest else np.full(len(t), np.nan)
    p_rest = t["p_vs_rest_adj"].to_numpy() if has_rest else np.full(len(t), np.nan)
    for flag, name, color, symbol in ((True, sig_label, BLUE, "circle"),
                                      (False, nonsig_label, GREY, "circle-open")):
        idx = np.where(sig == flag)[0]
        if len(idx) == 0:
            continue
        fig.add_scatter(
            x=_pct(t["abs_lift"].to_numpy()[idx]), y=[y[i] for i in idx], mode="markers", name=name,
            marker=dict(color=color, size=10, symbol=symbol, line=dict(width=2, color=color)),
            error_x=dict(type="data", symmetric=False, array=(hi - _pct(t["abs_lift"]))[idx],
                         arrayminus=(_pct(t["abs_lift"]) - lo)[idx], color=color, thickness=1.5, width=0),
            customdata=np.stack([t["rate_t"].to_numpy()[idx] * 100, t["rate_c"].to_numpy()[idx] * 100,
                                 t["n_t"].to_numpy()[idx], t["n_c"].to_numpy()[idx], t["p_adj"].to_numpy()[idx],
                                 diff_rest[idx], p_rest[idx], lo[idx], hi[idx]], axis=1),
            hovertemplate="<b>%{y}</b><br>Lift %{x:.2f} pp (95% CI %{customdata[7]:.2f} to %{customdata[8]:.2f})"
                          "<br>Treatment %{customdata[0]:.2f}% (n=%{customdata[2]:,.0f})"
                          "<br>Control %{customdata[1]:.2f}% (n=%{customdata[3]:,.0f})"
                          "<br>Lift ≠ 0: adjusted p = %{customdata[4]:.4f}"
                          "<br>vs other segments: %{customdata[5]:+.2f} pp, adjusted p = %{customdata[6]:.4f}"
                          "<extra></extra>",
        )
    fig.add_vline(x=0, line=dict(color=INK_2, width=1))
    if overall_lift is not None:
        fig.add_vline(x=overall_lift * 100, line=dict(color=BLUE, width=1, dash="dot"))
        fig.add_annotation(x=overall_lift * 100, y=1, yref="paper", text=f"overall {overall_lift*100:.2f} pp",
                           showarrow=False, yanchor="bottom", xanchor="left", xshift=4,
                           font=dict(size=11, color=BLUE))
    h = height or max(320, 26 * len(t) + 150)
    _layout(fig, title, subtitle, height=h, xaxis_title="Lift in conversion rate, treatment − control (pp)",
            yaxis_title=seg_title)
    fig.update_yaxes(categoryorder="array", categoryarray=y[::-1], showgrid=False, type="category")
    fig.update_xaxes(showgrid=True, gridcolor=GRID)
    return fig


def fig_rates_by_segment(tab: pd.DataFrame, seg_col: str, title: str, subtitle: str | None = None,
                         t="ad", c="psa", seg_title: str = "", height: int = 420,
                         ytitle: str = "Conversion rate (%)") -> go.Figure:
    """Treatment and control rates side by side per segment, with Wilson CIs."""
    fig = go.Figure()
    x = tab[seg_col].astype(str)
    for arm, rate_col, n_col, k_col in ((c, "rate_c", "n_c", "conv_c"), (t, "rate_t", "n_t", "conv_t")):
        cis = np.array([S.wilson_ci(k, n) for k, n in zip(tab[k_col], tab[n_col])])
        rate = tab[rate_col].to_numpy()
        fig.add_bar(x=x, y=rate * 100, name=ARM_NAMES[arm], marker=dict(color=ARM_COLORS[arm], cornerradius=3),
                    error_y=dict(type="data", symmetric=False, array=(cis[:, 1] - rate) * 100,
                                 arrayminus=(rate - cis[:, 0]) * 100, color=INK_2, thickness=1.2, width=3),
                    customdata=np.stack([tab[n_col], tab[k_col]], axis=1),
                    hovertemplate="%{x}<br>" + ARM_NAMES[arm] + ": %{y:.2f}%<br>Users %{customdata[0]:,}"
                                  "<br>Conversions %{customdata[1]:,}<extra></extra>")
    _layout(fig, title, subtitle, height=height, xaxis_title=seg_title, yaxis_title=ytitle)
    fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_balance(users: pd.DataFrame, col: str, title: str, subtitle: str | None = None,
                order=None, group_col: str = "test_group", t="ad", c="psa", height: int = 380,
                xtitle: str = "") -> go.Figure:
    """Share of each arm's users in each category: are the arms distributed alike?"""
    ct = pd.crosstab(users[col], users[group_col], normalize="columns")
    if order is not None:
        ct = ct.reindex([o for o in order if o in ct.index])
    fig = go.Figure()
    for arm in (c, t):
        fig.add_bar(x=ct.index.astype(str), y=ct[arm] * 100, name=ARM_NAMES[arm],
                    marker=dict(color=ARM_COLORS[arm], cornerradius=3),
                    hovertemplate="%{x}<br>" + ARM_NAMES[arm] + ": %{y:.2f}% of arm<extra></extra>")
    _layout(fig, title, subtitle, height=height, xaxis_title=xtitle, yaxis_title="Share of arm's users (%)")
    fig.update_xaxes(type="category")
    return fig


def fig_mde_by_split(p_c: float, total_n: int, current_share: float, reference_lift: float | None,
                     alpha: float, power: float, title: str, subtitle: str | None = None,
                     height: int = 400, reference_label: str = "smallest lift worth acting on") -> go.Figure:
    """Minimum detectable lift (pp) as a function of the treatment share, for a fixed total sample."""
    shares = np.round(np.linspace(0.5, 0.99, 50), 3)
    shares = np.unique(np.append(shares, [current_share, 0.5, 0.8, 0.9]))
    mdes = np.array([S.mde(p_c, int(total_n * s), int(total_n * (1 - s)), alpha, power)["mde_abs"] for s in shares])
    fig = go.Figure()
    fig.add_scatter(x=shares * 100, y=mdes * 100, mode="lines", line=dict(color=BLUE, width=2),
                    name="Minimum detectable lift",
                    hovertemplate="Treatment share %{x:.0f}%<br>MDE %{y:.3f} pp<extra></extra>")
    cur = S.mde(p_c, int(total_n * current_share), int(total_n * (1 - current_share)), alpha, power)["mde_abs"]
    half = S.mde(p_c, total_n // 2, total_n // 2, alpha, power)["mde_abs"]
    fig.add_scatter(x=[current_share * 100], y=[cur * 100], mode="markers+text", name="Selected split",
                    marker=dict(color=BLUE, size=11, line=dict(color=SURFACE, width=2)),
                    text=[f"{current_share*100:.0f}/{(1-current_share)*100:.0f}: {cur*100:.2f} pp"],
                    textposition="top left", textfont=dict(color=INK), hoverinfo="skip")
    fig.add_scatter(x=[50], y=[half * 100], mode="markers+text", name="50/50 split",
                    marker=dict(color=GREY, size=10, line=dict(color=SURFACE, width=2)),
                    text=[f"50/50: {half*100:.2f} pp"], textposition="top right", textfont=dict(color=INK_2),
                    hoverinfo="skip")
    if reference_lift is not None:
        fig.add_hline(y=reference_lift * 100, line=dict(color=ORANGE, width=1.5, dash="dot"))
        fig.add_annotation(x=52, y=reference_lift * 100, text=f"{reference_label}: {reference_lift*100:.2f} pp",
                           showarrow=False, yanchor="bottom", xanchor="left", font=dict(size=11, color=ORANGE))
    _layout(fig, title, subtitle, height=height, xaxis_title="Share of users in treatment (%)",
            yaxis_title="Minimum detectable lift (pp)", legend=False)
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_power_curve(p_c: float, n_t: int, n_c: int, alpha: float, reference_lift: float | None,
                    title: str, subtitle: str | None = None, max_lift_pp: float = 1.2,
                    target_power: float = 0.8, height: int = 380,
                    reference_label: str = "smallest lift worth acting on") -> go.Figure:
    """Probability of detecting a true lift of a given size with this sample
    (a design property; never evaluated at the observed effect)."""
    lifts = np.linspace(0.0005, max_lift_pp / 100, 120)
    pw = [S.achieved_power(p_c, p_c + l, n_t, n_c, alpha) for l in lifts]
    fig = go.Figure()
    fig.add_scatter(x=lifts * 100, y=np.array(pw) * 100, mode="lines", line=dict(color=BLUE, width=2),
                    name="Power", hovertemplate="True lift %{x:.2f} pp<br>Power %{y:.0f}%<extra></extra>")
    fig.add_hline(y=target_power * 100, line=dict(color=GREY, width=1))
    fig.add_annotation(x=max_lift_pp, y=target_power * 100, text=f"{target_power*100:.0f}% target",
                       showarrow=False, yanchor="bottom", xanchor="right", font=dict(size=11, color=INK_2))
    if reference_lift is not None and reference_lift * 100 <= max_lift_pp:
        pw_ref = S.achieved_power(p_c, p_c + reference_lift, n_t, n_c, alpha)
        fig.add_vline(x=reference_lift * 100, line=dict(color=ORANGE, width=1.5, dash="dot"))
        fig.add_annotation(x=reference_lift * 100, y=5,
                           text=f"{reference_label}: {reference_lift*100:.2f} pp → power {pw_ref*100:.0f}%",
                           showarrow=False, xanchor="left", xshift=4, font=dict(size=11, color=ORANGE))
    _layout(fig, title, subtitle, height=height, xaxis_title="True lift in conversion rate (pp)",
            yaxis_title="Power: chance of detecting it (%)", legend=False)
    fig.update_yaxes(range=[0, 102])
    return fig


def fig_breakeven(incr_point: float, incr_low: float, incr_high: float, impressions: int,
                  value_selected: float, cpm_actual: float | None, title: str, subtitle: str | None = None,
                  value_max: float = 150, height: int = 400) -> go.Figure:
    """Breakeven CPM ($ per 1,000 impressions) as a function of value per conversion.
    The campaign pays back when the actual CPM is below the line."""
    v = np.linspace(1, value_max, 150)
    f = lambda inc: inc * v / impressions * 1000
    fig = go.Figure()
    fig.add_scatter(x=np.concatenate([v, v[::-1]]), y=np.concatenate([f(incr_high), f(incr_low)[::-1]]),
                    fill="toself", fillcolor="rgba(42,120,214,0.12)", line=dict(width=0), hoverinfo="skip",
                    name="95% CI")
    fig.add_scatter(x=v, y=f(incr_point), mode="lines", line=dict(color=BLUE, width=2), name="Breakeven CPM",
                    hovertemplate="Value/conversion &#36;%{x:.0f}<br>Breakeven CPM &#36;%{y:.2f}<extra></extra>")
    be = incr_point * value_selected / impressions * 1000
    fig.add_scatter(x=[value_selected], y=[be], mode="markers+text", marker=dict(color=BLUE, size=11,
                    line=dict(color=SURFACE, width=2)), text=[esc(f"${value_selected:.0f} → ${be:.2f} CPM")],
                    textposition="top left", textfont=dict(color=INK), hoverinfo="skip", name="Selected")
    if cpm_actual is not None:
        fig.add_hline(y=cpm_actual, line=dict(color=ORANGE, width=1.5))
        fig.add_annotation(x=value_max, y=cpm_actual, text=esc(f"your CPM ${cpm_actual:.2f}"), showarrow=False,
                           xanchor="right", yanchor="bottom", font=dict(size=11, color=ORANGE))
    _layout(fig, title, subtitle, height=height, xaxis_title="Value per conversion (USD, assumption)",
            yaxis_title="Breakeven CPM (USD per 1,000 impressions)", legend=False)
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_dose_response(tab: pd.DataFrame, title: str, subtitle: str | None = None, height: int = 420) -> go.Figure:
    """Conversion rate by exposure bucket, per arm (from segment_lifts on exposure_bucket)."""
    return fig_rates_by_segment(tab, "exposure_bucket", title, subtitle, seg_title="Total ads seen (bucket)",
                                height=height)


# ================================================================== retention
def fig_funnel(funnel: pd.DataFrame, title: str, subtitle: str | None = None, height: int = 360) -> go.Figure:
    f = funnel.copy()
    fig = go.Figure()
    fig.add_bar(y=f["step"], x=f["share_of_installs"] * 100, orientation="h",
                marker=dict(color=[BLUE] * len(f), cornerradius=4),
                text=[f"{s*100:.1f}%  ({p:,})" for s, p in zip(f["share_of_installs"], f["players"])],
                textposition="outside", cliponaxis=False, textfont=dict(color=INK),
                customdata=np.stack([f["players"], f["step_conversion"].fillna(1) * 100], axis=1),
                hovertemplate="%{y}<br>%{x:.1f}% of installs (%{customdata[0]:,} players)"
                              "<br>%{customdata[1]:.1f}% of previous step<extra></extra>")
    _layout(fig, title, subtitle, height=height, xaxis_title="Share of installs (%)", legend=False)
    fig.update_yaxes(categoryorder="array", categoryarray=f["step"].tolist()[::-1], showgrid=False)
    fig.update_xaxes(range=[0, 118], showgrid=True, gridcolor=GRID)
    fig.update_layout(margin=dict(l=210))
    return fig


def fig_engagement_curve(curve: pd.DataFrame, title: str, subtitle: str | None = None,
                         gates=(30, 40), height: int = 400) -> go.Figure:
    """Share of players who played at least k rounds."""
    fig = go.Figure()
    for name, g in curve.groupby("group", sort=False):
        color = ARM_COLORS.get(name, BLUE)
        fig.add_scatter(x=g["rounds_at_least"], y=g["share_of_players"] * 100, mode="lines",
                        name=ARM_NAMES.get(name, name), line=dict(color=color, width=2),
                        hovertemplate=ARM_NAMES.get(name, name) + "<br>≥ %{x} rounds: %{y:.1f}% of players<extra></extra>")
    for gte in gates:
        fig.add_vline(x=gte, line=dict(color=INK_2, width=1, dash="dot"))
        fig.add_annotation(x=gte, y=1, yref="paper", text=f"gate {gte}", showarrow=False, yanchor="bottom",
                           font=dict(size=11, color=INK_2))
    _layout(fig, title, subtitle, height=height, xaxis_title="Game rounds played in first 14 days (at least)",
            yaxis_title="Share of players (%)")
    fig.update_yaxes(range=[0, 101])
    return fig


def fig_retention_by_segment(rates: pd.DataFrame, seg_col: str, title: str, subtitle: str | None = None,
                             metrics=("retention_1", "retention_7"), seg_title: str = "",
                             height: int = 420, show_n: bool = True) -> go.Figure:
    """D1 / D7 retention per segment with Wilson CIs."""
    fig = go.Figure()
    x = rates[seg_col].astype(str)
    if show_n:
        x = [f"{s}<br><span style='font-size:10px'>n={n:,}</span>" for s, n in zip(x, rates["players"])]
    for m in metrics:
        r = rates[m].to_numpy()
        fig.add_bar(x=x, y=r * 100, name=METRIC_NAMES[m], marker=dict(color=METRIC_COLORS[m], cornerradius=3),
                    error_y=dict(type="data", symmetric=False, array=(rates[f"{m}_ci_high"] - r) * 100,
                                 arrayminus=(r - rates[f"{m}_ci_low"]) * 100, color=INK_2, thickness=1.2, width=3),
                    customdata=np.stack([rates["players"], rates[f"{m}_ci_low"] * 100,
                                         rates[f"{m}_ci_high"] * 100], axis=1),
                    hovertemplate="%{x}<br>" + METRIC_NAMES[m] + " %{y:.1f}% (95% CI %{customdata[1]:.1f}"
                                  " to %{customdata[2]:.1f})<br>Players %{customdata[0]:,}<extra></extra>")
    _layout(fig, title, subtitle, height=height, xaxis_title=seg_title, yaxis_title="Players retained (%)")
    fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_retention_by_rounds(by_rounds: pd.DataFrame, title: str, subtitle: str | None = None,
                            gates=(30, 40), height: int = 400) -> go.Figure:
    fig = go.Figure()
    for m in ("retention_1", "retention_7"):
        fig.add_scatter(x=by_rounds["rounds_mid"], y=by_rounds[m] * 100, mode="lines+markers",
                        name=METRIC_NAMES[m], line=dict(color=METRIC_COLORS[m], width=2),
                        marker=dict(size=6), customdata=by_rounds["players"],
                        hovertemplate="~%{x:.0f} rounds<br>" + METRIC_NAMES[m] + " %{y:.1f}%<br>"
                                      "Players in bin %{customdata:,}<extra></extra>")
    for gte in gates:
        fig.add_vline(x=gte, line=dict(color=INK_2, width=1, dash="dot"))
        fig.add_annotation(x=gte, y=1, yref="paper", text=f"gate {gte}", showarrow=False, yanchor="bottom",
                           font=dict(size=11, color=INK_2))
    _layout(fig, title, subtitle, height=height, xaxis_title="Game rounds played in first 14 days (bin median)",
            yaxis_title="Players retained (%)")
    fig.update_yaxes(range=[0, 101])
    return fig


def fig_gate_rates(gate: dict, title: str, subtitle: str | None = None, height: int = 400) -> go.Figure:
    """D1 and D7 retention by version, side by side, with Wilson CIs."""
    fig = go.Figure()
    for arm in ("gate_30", "gate_40"):
        xs, ys, lo, hi, ns = [], [], [], [], []
        for m in ("retention_1", "retention_7"):
            g = gate[m]
            k, n = (g["conv_t"], g["n_t"]) if arm == "gate_40" else (g["conv_c"], g["n_c"])
            a, b = S.wilson_ci(k, n)
            xs.append(METRIC_NAMES[m]); ys.append(k / n * 100); lo.append(a * 100); hi.append(b * 100); ns.append(n)
        ys, lo, hi = np.array(ys), np.array(lo), np.array(hi)
        fig.add_bar(x=xs, y=ys, name=ARM_NAMES[arm], marker=dict(color=ARM_COLORS[arm], cornerradius=3),
                    error_y=dict(type="data", symmetric=False, array=hi - ys, arrayminus=ys - lo, color=INK_2,
                                 thickness=1.2, width=4),
                    text=[f"{y:.1f}%" for y in ys], textposition="outside", cliponaxis=False,
                    textfont=dict(color=INK),
                    customdata=np.stack([lo, hi, ns], axis=1),
                    hovertemplate="%{x}<br>" + ARM_NAMES[arm] + " %{y:.2f}% (95% CI %{customdata[0]:.2f}"
                                  " to %{customdata[1]:.2f})<br>Players %{customdata[2]:,}<extra></extra>")
    _layout(fig, title, subtitle, height=height, yaxis_title="Players retained (%)")
    fig.update_yaxes(rangemode="tozero")
    return fig


def fig_gate_bootstrap(boot: pd.DataFrame, gate: dict, title: str, subtitle: str | None = None,
                       height: int = 380) -> go.Figure:
    """Overlaid bootstrap distributions of the gate_40 − gate_30 difference for D1 and D7."""
    fig = go.Figure()
    for m in ("retention_1", "retention_7"):
        d = boot.loc[boot["metric"] == m, "abs_lift"] * 100
        fig.add_histogram(x=d, nbinsx=70, name=METRIC_NAMES[m], opacity=0.6,
                          marker=dict(color=METRIC_COLORS[m], line=dict(color=SURFACE, width=0.5)),
                          hovertemplate=METRIC_NAMES[m] + ": %{x:.2f} pp<br>%{y} draws<extra></extra>")
    fig.add_vline(x=0, line=dict(color=INK_2, width=1.5))
    fig.add_annotation(x=0, y=1, yref="paper", text="no difference", showarrow=False, yanchor="bottom",
                       xanchor="left", xshift=4, font=dict(size=11, color=INK_2))
    _layout(fig, title, subtitle, height=height, xaxis_title="gate_40 − gate_30 retention (pp)",
            yaxis_title="Bootstrap draws (count)")
    fig.update_layout(barmode="overlay")
    return fig


def fig_effect_by_stratum(rows: pd.DataFrame, title: str, subtitle: str | None = None,
                          xtitle: str = "gate_40 − gate_30 D7 retention (pp)", height: int = 340) -> go.Figure:
    """Dot + 95% CI for an effect estimated in several strata.
    rows columns: label, abs_lift, abs_ci_low, abs_ci_high, n_t, n_c, rate_t, rate_c, p_value, role
    (role 'main' = blue filled, 'control' = grey hollow, 'other' = blue hollow)."""
    fig = go.Figure()
    styles = {"main": (BLUE, "circle"), "control": (GREY, "diamond-open"), "other": (BLUE, "circle-open")}
    for _, r in rows.iterrows():
        color, symbol = styles.get(r["role"], (BLUE, "circle"))
        fig.add_scatter(
            x=[r["abs_lift"] * 100], y=[r["label"]], mode="markers", name=r["label"], showlegend=False,
            marker=dict(color=color, size=11, symbol=symbol, line=dict(width=2, color=color)),
            error_x=dict(type="data", symmetric=False, array=[(r["abs_ci_high"] - r["abs_lift"]) * 100],
                         arrayminus=[(r["abs_lift"] - r["abs_ci_low"]) * 100], color=color, thickness=1.5, width=0),
            customdata=[[r["rate_t"] * 100, r["rate_c"] * 100, r["n_t"], r["n_c"], r["p_value"],
                         r["abs_ci_low"] * 100, r["abs_ci_high"] * 100]],
            hovertemplate="<b>%{y}</b><br>Difference %{x:.2f} pp (95% CI %{customdata[5]:.2f} to %{customdata[6]:.2f})"
                          "<br>gate_40 %{customdata[0]:.2f}% (n=%{customdata[2]:,.0f})"
                          "<br>gate_30 %{customdata[1]:.2f}% (n=%{customdata[3]:,.0f})"
                          "<br>p = %{customdata[4]:.3f}<extra></extra>")
    fig.add_vline(x=0, line=dict(color=INK_2, width=1))
    _layout(fig, title, subtitle, height=height, xaxis_title=xtitle, legend=False)
    fig.update_yaxes(categoryorder="array", categoryarray=rows["label"].tolist()[::-1], showgrid=False, type="category")
    fig.update_xaxes(showgrid=True, gridcolor=GRID)
    fig.update_layout(margin=dict(l=260))
    return fig


def fig_gap_by_dimension(gaps: pd.DataFrame, title: str, subtitle: str | None = None, height: int = 300) -> go.Figure:
    g = gaps.sort_values("gap_pp")
    fig = go.Figure()
    fig.add_bar(y=g["dimension"], x=g["gap_pp"], orientation="h", marker=dict(color=BLUE, cornerradius=4),
                text=[f"{x:.1f} pp" for x in g["gap_pp"]], textposition="outside", cliponaxis=False,
                textfont=dict(color=INK),
                customdata=np.stack([g["best_segment"], g["best_rate"] * 100, g["worst_segment"],
                                     g["worst_rate"] * 100], axis=1),
                hovertemplate="%{y}<br>Best: %{customdata[0]} (%{customdata[1]:.1f}%)<br>"
                              "Worst: %{customdata[2]} (%{customdata[3]:.1f}%)<extra></extra>")
    _layout(fig, title, subtitle, height=height, xaxis_title="D7 retention gap, best − worst segment (pp)",
            legend=False)
    fig.update_xaxes(range=[0, max(g["gap_pp"]) * 1.18], showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(margin=dict(l=240))
    return fig
