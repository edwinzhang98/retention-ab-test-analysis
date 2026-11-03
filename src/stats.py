"""Reusable experiment statistics.

Every function works on counts (conversions, users) so the same code runs on
raw user tables, on the dashboard's aggregated cache, and inside the notebooks.
Convention: "t" = treatment (ad / gate_40), "c" = control (psa / gate_30).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.contingency_tables import StratifiedTable
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportion_confint,
    proportion_effectsize,
    proportions_ztest,
)


# ------------------------------------------------------------------ basics
def wilson_ci(k: float, n: float, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a single proportion."""
    lo, hi = proportion_confint(k, n, alpha=alpha, method="wilson")
    return float(lo), float(hi)


@dataclass
class TwoPropResult:
    n_t: int
    n_c: int
    conv_t: int
    conv_c: int
    rate_t: float
    rate_c: float
    abs_lift: float          # rate_t - rate_c (proportion, not pp)
    abs_ci_low: float        # Newcombe hybrid score interval
    abs_ci_high: float
    rel_lift: float          # rate_t / rate_c - 1
    rel_ci_low: float        # log-risk-ratio (Katz) interval
    rel_ci_high: float
    z: float
    p_value: float           # two-sided pooled z-test
    alpha: float

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def significant(self) -> bool:
        return self.p_value < self.alpha


def two_prop_test(conv_t, n_t, conv_c, n_c, alpha: float = 0.05) -> TwoPropResult:
    """Two-proportion z-test with a Newcombe CI for the difference and a
    log-RR CI for the relative lift."""
    conv_t, n_t, conv_c, n_c = int(conv_t), int(n_t), int(conv_c), int(n_c)
    p_t, p_c = conv_t / n_t, conv_c / n_c
    if conv_t + conv_c == 0 or conv_t + conv_c == n_t + n_c:
        z, p = 0.0, 1.0
    else:
        z, p = proportions_ztest([conv_t, conv_c], [n_t, n_c], alternative="two-sided")
    lo, hi = confint_proportions_2indep(conv_t, n_t, conv_c, n_c, method="newcomb", compare="diff", alpha=alpha)
    if conv_t > 0 and conv_c > 0:
        log_rr = np.log(p_t / p_c)
        se = np.sqrt(1 / conv_t - 1 / n_t + 1 / conv_c - 1 / n_c)
        zc = stats.norm.ppf(1 - alpha / 2)
        rlo, rhi = np.exp(log_rr - zc * se) - 1, np.exp(log_rr + zc * se) - 1
        rel = p_t / p_c - 1
    else:
        rel, rlo, rhi = np.nan, np.nan, np.nan
    return TwoPropResult(n_t, n_c, conv_t, conv_c, p_t, p_c, p_t - p_c, float(lo), float(hi),
                         float(rel), float(rlo), float(rhi), float(z), float(p), alpha)


def wald_diff_ci(conv_t, n_t, conv_c, n_c, alpha: float = 0.05) -> tuple[float, float]:
    """Plain Wald (unpooled) interval for the difference. Shown for comparison only."""
    p_t, p_c = conv_t / n_t, conv_c / n_c
    se = np.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
    zc = stats.norm.ppf(1 - alpha / 2)
    d = p_t - p_c
    return float(d - zc * se), float(d + zc * se)


# ------------------------------------------------------------------ bootstrap
def bootstrap_two_prop(conv_t, n_t, conv_c, n_c, n_boot: int = 10_000, seed: int = 0) -> pd.DataFrame:
    """Non-parametric bootstrap of a difference in proportions.

    Resampling n Bernoulli outcomes with replacement is exactly a draw from
    Binomial(n, p_hat), so we draw from counts directly. This is identical to
    resampling the user-level table but takes milliseconds.
    """
    rng = np.random.default_rng(seed)
    bt = rng.binomial(int(n_t), conv_t / n_t, size=n_boot) / n_t
    bc = rng.binomial(int(n_c), conv_c / n_c, size=n_boot) / n_c
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(bc > 0, bt / bc - 1, np.nan)
    return pd.DataFrame({"rate_t": bt, "rate_c": bc, "abs_lift": bt - bc, "rel_lift": rel})


def bootstrap_mean_diff(x_t, x_c, n_boot: int = 2_000, seed: int = 0) -> np.ndarray:
    """User-level bootstrap of a difference in means (treatment - control).
    Used for heavy-tailed metrics (rounds played), where it adds something over
    a normal approximation."""
    rng = np.random.default_rng(seed)
    x_t, x_c = np.asarray(x_t, dtype=float), np.asarray(x_c, dtype=float)
    out = np.empty(n_boot)
    for b in range(n_boot):
        out[b] = x_t[rng.integers(0, len(x_t), len(x_t))].mean() - x_c[rng.integers(0, len(x_c), len(x_c))].mean()
    return out


def percentile_ci(x, alpha: float = 0.05) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(np.quantile(x, alpha / 2)), float(np.quantile(x, 1 - alpha / 2))


# ------------------------------------------------------------------ SRM
def srm_check(n_t: int, n_c: int, intended_share_t: float, threshold: float = 0.001,
              warn_threshold: float = 0.01) -> dict:
    """Sample Ratio Mismatch: chi-square goodness of fit of observed arm sizes
    to the intended allocation.

    Two-level rule (see docs/assumptions.md):
      p < threshold (0.001)          -> FAIL: stop, results are not trustworthy
      threshold <= p < warn (0.01)   -> WARN: investigate assignment before certifying results
      p >= warn                      -> PASS
    """
    n = n_t + n_c
    exp = np.array([n * intended_share_t, n * (1 - intended_share_t)])
    chi2, p = stats.chisquare([n_t, n_c], exp)
    status = "FAIL" if p < threshold else ("WARN" if p < warn_threshold else "PASS")
    return {
        "n_t": int(n_t), "n_c": int(n_c),
        "observed_share_t": n_t / n, "intended_share_t": intended_share_t,
        "expected_t": float(exp[0]), "expected_c": float(exp[1]),
        "chi2": float(chi2), "p_value": float(p), "threshold": threshold,
        "warn_threshold": warn_threshold, "status": status,
        "flag": status != "PASS",
    }


def quota_exactness(n_t: int, n_c: int, intended_share_t: float) -> dict:
    """How close is the split to the intended ratio, in users, versus what
    independent random assignment would produce? A split that lands on the
    nearest integer to the target is what a quota (or a trimmed export) looks
    like; an SRM test cannot detect anything in that case."""
    n = n_t + n_c
    expected = n * intended_share_t
    sd = float(np.sqrt(n * intended_share_t * (1 - intended_share_t)))
    nearest = int(round(expected))
    return {"deviation_users": float(n_t - expected), "sd_users_under_random_assignment": sd,
            "is_nearest_integer_to_target": bool(n_t == nearest),
            "prob_exactly_nearest_integer": float(stats.binom.pmf(nearest, n, intended_share_t))}


# ------------------------------------------------------------------ power
def _h_to_p(p_c: float, h: float) -> float:
    """Invert Cohen's h: find p_t with 2asin(sqrt p_t) - 2asin(sqrt p_c) = h."""
    val = np.arcsin(np.sqrt(p_c)) + h / 2
    return float(np.clip(np.sin(val) ** 2, 0, 1))


def mde(p_c: float, n_t: int, n_c: int, alpha: float = 0.05, power: float = 0.8) -> dict:
    """Minimum detectable effect (two-sided) for a given sample, via Cohen's h."""
    h = NormalIndPower().solve_power(effect_size=None, nobs1=n_t, ratio=n_c / n_t, alpha=alpha, power=power)
    p_t = _h_to_p(p_c, h)
    return {"p_c": p_c, "n_t": int(n_t), "n_c": int(n_c), "alpha": alpha, "power": power,
            "cohens_h": float(h), "mde_abs": p_t - p_c, "mde_rel": p_t / p_c - 1}


def achieved_power(p_c: float, p_t: float, n_t: int, n_c: int, alpha: float = 0.05) -> float:
    h = proportion_effectsize(p_t, p_c)
    return float(NormalIndPower().power(effect_size=abs(h), nobs1=n_t, ratio=n_c / n_t, alpha=alpha))


def required_total_n(p_c: float, abs_effect: float, share_t: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Total users needed to detect abs_effect with a share_t / (1-share_t) split."""
    h = proportion_effectsize(p_c + abs_effect, p_c)
    n_t = NormalIndPower().solve_power(effect_size=abs(h), nobs1=None, ratio=(1 - share_t) / share_t,
                                       alpha=alpha, power=power)
    return int(np.ceil(n_t / share_t))


# ------------------------------------------------------------------ segments
def adjust_pvalues(p, method: str = "holm") -> np.ndarray:
    """method: 'none' | 'bonferroni' | 'holm' | 'fdr_bh'."""
    p = np.asarray(p, dtype=float)
    if method == "none":
        return p
    return multipletests(p, method=method)[1]


def segment_lifts(cells: pd.DataFrame, by: str, t_label: str, c_label: str,
                  group_col: str = "test_group", users_col: str = "users",
                  conv_col: str = "conversions", alpha: float = 0.05,
                  method: str = "holm", order=None) -> pd.DataFrame:
    """Per-segment results, two different questions, both with the chosen
    multiple-comparison adjustment across segments:

    1. "Is there a lift in this segment?"  -> p_value / p_adj / significant_adj
       (two-proportion test of treatment vs control inside the segment).
    2. "Is this segment's lift different from the other segments'?"  -> diff_vs_rest,
       p_vs_rest / p_vs_rest_adj / differs_adj. This is the heterogeneity question.
       Difference-in-differences (segment lift minus lift in all other segments)
       with Agresti-Caffo adjusted proportions (+1 success, +1 failure per group),
       so cells with 0 control conversions don't produce a zero variance.
    """
    piv = cells.groupby([by, group_col], observed=True)[[users_col, conv_col]].sum().unstack(group_col)
    tot = piv.sum()
    zc = stats.norm.ppf(1 - alpha / 2)
    rows = []
    for seg, r in piv.iterrows():
        kt, nt = r[(conv_col, t_label)], r[(users_col, t_label)]
        kc, nc = r[(conv_col, c_label)], r[(users_col, c_label)]
        res = two_prop_test(kt, nt, kc, nc, alpha=alpha)
        d = res.to_dict()
        d[by] = seg
        groups = [(kt, nt), (kc, nc), (tot[(conv_col, t_label)] - kt, tot[(users_col, t_label)] - nt),
                  (tot[(conv_col, c_label)] - kc, tot[(users_col, c_label)] - nc)]
        ac = [((k + 1) / (n + 2), n + 2) for k, n in groups]
        diff = (ac[0][0] - ac[1][0]) - (ac[2][0] - ac[3][0])
        se = float(np.sqrt(sum(p_ * (1 - p_) / n_ for p_, n_ in ac)))
        rest_t, rest_c = groups[2][0] / groups[2][1], groups[3][0] / groups[3][1]
        d["lift_rest"] = rest_t - rest_c
        d["diff_vs_rest"] = float(diff)
        d["diff_vs_rest_ci_low"] = float(diff - zc * se)
        d["diff_vs_rest_ci_high"] = float(diff + zc * se)
        d["p_vs_rest"] = float(2 * stats.norm.sf(abs(diff / se)))
        rows.append(d)
    out = pd.DataFrame(rows)
    out["p_adj"] = adjust_pvalues(out["p_value"], method)
    out["significant_adj"] = out["p_adj"] < alpha
    out["p_vs_rest_adj"] = adjust_pvalues(out["p_vs_rest"], method)
    out["differs_adj"] = out["p_vs_rest_adj"] < alpha
    out["correction"] = method
    if order is not None:
        out[by] = pd.Categorical(out[by], categories=order, ordered=True)
        out = out.sort_values(by)
    cols = [by] + [c for c in out.columns if c != by]
    return out[cols].reset_index(drop=True)


def interaction_lrt(cells: pd.DataFrame, by: str, group_col: str = "test_group",
                    users_col: str = "users", conv_col: str = "conversions") -> dict:
    """Does the treatment effect differ across segments? Likelihood-ratio test of
    logit(conv) ~ group * segment vs group + segment (binomial GLM on counts).
    With one cell per group x segment the interaction model is saturated, so the
    LR statistic equals the deviance of the additive model (df = segments - 1).
    One test per dimension; with several dimensions explored, compare the
    p-values against an adjusted threshold (we explore 3: day, hour, exposure)."""
    g = cells.groupby([by, group_col], observed=True)[[users_col, conv_col]].sum().reset_index()
    g[by] = g[by].astype(str)
    g["fail"] = g[users_col] - g[conv_col]
    endog = g[[conv_col, "fail"]].to_numpy()
    X = pd.get_dummies(g[[group_col, by]], drop_first=True).astype(float)
    m = sm.GLM(endog, sm.add_constant(X), family=sm.families.Binomial()).fit()
    lr, df = float(m.deviance), int(round(m.df_resid))
    sparse = int((g[conv_col] == 0).sum())
    return {"dimension": by, "lr_stat": lr, "df": df, "p_value": float(stats.chi2.sf(lr, df)),
            "cells_with_zero_conversions": sparse}


def stratified_summary(cells: pd.DataFrame, by: str, t_label: str, c_label: str,
                       group_col: str = "test_group", users_col: str = "users",
                       conv_col: str = "conversions") -> dict:
    """Cochran-Mantel-Haenszel pooled odds ratio + Breslow-Day homogeneity test,
    and a Mantel-Haenszel weighted risk difference, stratified on `by`."""
    piv = cells.groupby([by, group_col], observed=True)[[users_col, conv_col]].sum().unstack(group_col)
    tables, num, den = [], 0.0, 0.0
    for _, r in piv.iterrows():
        a, n1 = r[(conv_col, t_label)], r[(users_col, t_label)]
        c, n0 = r[(conv_col, c_label)], r[(users_col, c_label)]
        tables.append(np.array([[a, n1 - a], [c, n0 - c]], dtype=float))
        w = n1 * n0 / (n1 + n0)
        num += w * (a / n1 - c / n0)
        den += w
    st = StratifiedTable(tables)
    t = st.test_null_odds()
    bd = st.test_equal_odds()
    lo, hi = st.oddsratio_pooled_confint()
    return {"dimension": by, "pooled_or": float(st.oddsratio_pooled), "or_ci_low": float(lo),
            "or_ci_high": float(hi), "cmh_p_value": float(t.pvalue),
            "breslow_day_p_value": float(bd.pvalue), "mh_risk_diff": float(num / den)}


def balance_test(df: pd.DataFrame, col: str, group_col: str) -> dict:
    """Chi-square test of a categorical variable's distribution across arms,
    plus Cramer's V so a 'significant' result can be judged for size."""
    ct = pd.crosstab(df[col], df[group_col])
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    v = np.sqrt(chi2 / (ct.to_numpy().sum() * (min(ct.shape) - 1)))
    return {"variable": col, "chi2": float(chi2), "df": int(dof), "p_value": float(p), "cramers_v": float(v)}
