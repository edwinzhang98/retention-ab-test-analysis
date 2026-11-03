"""End-to-end analysis: clean data, run every test, write caches and results.

Outputs
  data/processed/*.parquet   caches read by the dashboard and report (git-ignored)
  reports/tables/*.csv       small result tables (committed, source for README numbers)
  reports/results.json       every headline number, one place
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats as sps

from . import config as C
from . import data as D
from . import retention as R
from . import stats as S

T, CTRL = "ad", "psa"
G_T, G_C = "gate_40", "gate_30"


def _r(x, nd=6):
    """Round floats for JSON readability."""
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if np.isnan(x) else round(float(x), nd)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


# ====================================================================== DQ
def data_quality(m_raw: pd.DataFrame, m: pd.DataFrame, c_raw: pd.DataFrame,
                 c: pd.DataFrame, c_out: pd.DataFrame) -> dict:
    return {
        "marketing": {
            "rows_raw": len(m_raw), "rows_clean": len(m),
            "unique_user_id": int(m["user_id"].nunique()),
            "duplicate_user_id": int(m["user_id"].duplicated().sum()),
            "nulls": {k: int(v) for k, v in m_raw.isna().sum().items()},
            "test_group_values": sorted(m["test_group"].unique().tolist()),
            "converted_values": sorted(map(str, m_raw["converted"].unique().tolist())),
            "total_ads_min": int(m["total_ads"].min()), "total_ads_max": int(m["total_ads"].max()),
            "total_ads_p50": float(m["total_ads"].median()), "total_ads_p99": float(m["total_ads"].quantile(.99)),
            "total_ads_p999": float(m["total_ads"].quantile(.999)),
            "users_over_1000_ads": int((m["total_ads"] > 1000).sum()),
            "most_ads_hour_range": [int(m["most_ads_hour"].min()), int(m["most_ads_hour"].max())],
            "most_ads_day_values": int(m["most_ads_day"].nunique()),
            "index_column_dropped": [col for col in m_raw.columns if col.startswith("Unnamed")],
        },
        "cookie": {
            "rows_raw": len(c_raw), "rows_clean": len(c),
            "unique_user_id": int(c_raw["userid"].nunique()),
            "duplicate_user_id": int(c_raw["userid"].duplicated().sum()),
            "nulls": {k: int(v) for k, v in c_raw.isna().sum().items()},
            "version_values": sorted(c_raw["version"].unique().tolist()),
            "rounds_min": int(c_raw["sum_gamerounds"].min()), "rounds_max_raw": int(c_raw["sum_gamerounds"].max()),
            "rounds_p50": float(c_raw["sum_gamerounds"].median()),
            "rounds_p99": float(c_raw["sum_gamerounds"].quantile(.99)),
            "rounds_p999": float(c_raw["sum_gamerounds"].quantile(.999)),
            "rounds_max_clean": int(c["sum_gamerounds"].max()),
            "zero_round_players": int((c_raw["sum_gamerounds"] == 0).sum()),
            "outliers_dropped": c_out[["user_id", "version", "sum_gamerounds", "retention_1", "retention_7"]]
            .to_dict(orient="records"),
            "d7_without_d1": int((c_raw["retention_7"] & ~c_raw["retention_1"]).sum()),
            # sensitivity: does dropping the outlier change anything?
            "retention_raw": {"d1": float(c_raw["retention_1"].mean()), "d7": float(c_raw["retention_7"].mean())},
            "retention_clean": {"d1": float(c["retention_1"].mean()), "d7": float(c["retention_7"].mean())},
            "mean_rounds_raw": float(c_raw["sum_gamerounds"].mean()),
            "mean_rounds_clean": float(c["sum_gamerounds"].mean()),
        },
    }


# ====================================================================== ad experiment
def ad_experiment(m: pd.DataFrame, cells: pd.DataFrame) -> tuple[dict, dict]:
    tot = m.groupby("test_group").agg(users=("user_id", "size"), conversions=("converted", "sum"),
                                      impressions=("total_ads", "sum"), mean_ads=("total_ads", "mean"),
                                      median_ads=("total_ads", "median"))
    nt, nc = int(tot.loc[T, "users"]), int(tot.loc[CTRL, "users"])
    ct, cc = int(tot.loc[T, "conversions"]), int(tot.loc[CTRL, "conversions"])
    res = S.two_prop_test(ct, nt, cc, nc, alpha=C.ALPHA)
    wald = S.wald_diff_ci(ct, nt, cc, nc, alpha=C.ALPHA)
    boot = S.bootstrap_two_prop(ct, nt, cc, nc, n_boot=C.N_BOOT, seed=C.SEED)
    b_abs, b_rel = S.percentile_ci(boot["abs_lift"], C.ALPHA), S.percentile_ci(boot["rel_lift"], C.ALPHA)
    srm = S.srm_check(nt, nc, C.INTENDED_AD_SHARE)
    chi2 = sps.chi2_contingency([[ct, nt - ct], [cc, nc - cc]], correction=False)

    # balance of post-assignment variables (descriptive, not randomization checks)
    balance = [S.balance_test(m, col, "test_group") for col in ("most_ads_day", "most_ads_hour", "exposure_bucket")]
    mw = sps.mannwhitneyu(m.loc[m.test_group == T, "total_ads"], m.loc[m.test_group == CTRL, "total_ads"])
    ks = sps.ks_2samp(m.loc[m.test_group == T, "total_ads"], m.loc[m.test_group == CTRL, "total_ads"])

    # power
    p_c = cc / nc
    mde_now = S.mde(p_c, nt, nc, C.ALPHA, C.POWER)
    mde_5050 = S.mde(p_c, (nt + nc) // 2, (nt + nc) // 2, C.ALPHA, C.POWER)
    power_obs = S.achieved_power(p_c, ct / nt, nt, nc, C.ALPHA)
    n_needed_9604 = S.required_total_n(p_c, mde_now["mde_abs"], C.INTENDED_AD_SHARE, C.ALPHA, C.POWER)
    n_needed_5050 = S.required_total_n(p_c, mde_now["mde_abs"], 0.5, C.ALPHA, C.POWER)
    # smallest effect of business interest: 10% relative lift
    n_needed_10pct = {s: S.required_total_n(p_c, 0.10 * p_c, s, C.ALPHA, C.POWER) for s in (0.5, 0.8, 0.96)}

    # business translation
    impressions_t = int(tot.loc[T, "impressions"])
    incr = {"point": res.abs_lift * nt, "ci_low": res.abs_ci_low * nt, "ci_high": res.abs_ci_high * nt}
    impr_per_incr = impressions_t / incr["point"]
    v = C.VALUE_PER_CONVERSION
    breakeven_cpm = {k: x * v / impressions_t * 1000 for k, x in incr.items()}
    share_attributable = res.abs_lift / res.rate_t  # share of ad-group conversions that are incremental

    # heterogeneity
    seg = {}
    for dim, order in (("most_ads_day", C.DAY_ORDER), ("most_ads_hour", list(range(24))),
                       ("exposure_bucket", C.EXPOSURE_LABELS)):
        tables = {meth: S.segment_lifts(cells, dim, T, CTRL, alpha=C.ALPHA, method=meth, order=order)
                  for meth in ("none", "bonferroni", "holm", "fdr_bh")}
        holm = tables["holm"]
        seg[dim] = {
            "lrt": S.interaction_lrt(cells, dim),
            "stratified": S.stratified_summary(cells, dim, T, CTRL),
            "n_segments": len(holm),
            "n_sig_unadjusted": int((tables["none"]["p_value"] < C.ALPHA).sum()),
            "n_sig_bonferroni": int(tables["bonferroni"]["significant_adj"].sum()),
            "n_sig_holm": int(holm["significant_adj"].sum()),
            "n_sig_bh": int(tables["fdr_bh"]["significant_adj"].sum()),
            "max_lift_segment": str(holm.loc[holm["abs_lift"].idxmax(), dim]),
            "max_lift_pp": float(holm["abs_lift"].max() * 100),
            "min_lift_segment": str(holm.loc[holm["abs_lift"].idxmin(), dim]),
            "min_lift_pp": float(holm["abs_lift"].min() * 100),
        }
        holm.to_csv(C.TABLES_DIR / f"ad_lift_by_{dim}.csv", index=False)

    out = {
        "groups": {g: {k: (float(v_) if k in ("mean_ads", "median_ads") else int(v_)) for k, v_ in row.items()}
                   for g, row in tot.to_dict(orient="index").items()},
        "test": res.to_dict(),
        "wald_ci": list(wald),
        "chi2_test": {"chi2": float(chi2[0]), "p_value": float(chi2[1])},
        "bootstrap": {"n_boot": C.N_BOOT, "seed": C.SEED, "abs_ci": list(b_abs), "rel_ci": list(b_rel),
                      "share_draws_le_0": float((boot["abs_lift"] <= 0).mean())},
        "srm": srm,
        "balance": balance,
        "total_ads_mannwhitney_p": float(mw.pvalue), "total_ads_ks": {"stat": float(ks.statistic), "p_value": float(ks.pvalue)},
        "power": {"mde_current": mde_now, "mde_if_5050_same_total": mde_5050, "achieved_power_at_observed": power_obs,
                  "total_n_for_current_mde_at_9604": n_needed_9604, "total_n_for_current_mde_at_5050": n_needed_5050,
                  "total_n_for_10pct_rel_lift": {str(k): v_ for k, v_ in n_needed_10pct.items()}},
        "business": {"value_per_conversion_usd": v, "impressions_ad_group": impressions_t,
                     "incremental_conversions": incr, "impressions_per_incremental_conversion": impr_per_incr,
                     "incremental_value_usd": {k: x * v for k, x in incr.items()},
                     "breakeven_cpm_usd": breakeven_cpm, "share_of_ad_conversions_incremental": share_attributable},
        "heterogeneity": seg,
    }
    return out, {"boot": boot}


# ====================================================================== retention + gate
def cookie_analysis(c: pd.DataFrame) -> tuple[dict, dict]:
    overall = R.retention_rates(c).iloc[0].to_dict()
    funnel = R.funnel(c)
    by_rounds = R.retention_rates(c, "rounds_bucket")
    by_d1 = R.retention_rates(c, "d1_status")
    by_version = R.retention_rates(c, "version")
    gaps = R.gap_by_dimension(c, {"rounds_bucket": "Engagement depth (rounds played)",
                                  "d1_status": "Came back on Day 1", "version": "Experiment version"})
    for name, t in (("retention_funnel", funnel), ("retention_by_rounds_bucket", by_rounds),
                    ("retention_by_d1_status", by_d1), ("retention_by_version", by_version),
                    ("retention_gap_by_dimension", gaps)):
        t.to_csv(C.TABLES_DIR / f"{name}.csv", index=False)

    # gate experiment
    v = c.groupby("version").agg(players=("user_id", "size"), r1=("retention_1", "sum"), r7=("retention_7", "sum"))
    nt, nc = int(v.loc[G_T, "players"]), int(v.loc[G_C, "players"])
    gate = {"players": {G_T: nt, G_C: nc}, "srm": S.srm_check(nt, nc, C.INTENDED_GATE40_SHARE)}
    boots = {}
    for key, col in (("retention_1", "r1"), ("retention_7", "r7")):
        res = S.two_prop_test(v.loc[G_T, col], nt, v.loc[G_C, col], nc, alpha=C.ALPHA)
        bt = S.bootstrap_two_prop(v.loc[G_T, col], nt, v.loc[G_C, col], nc, n_boot=C.N_BOOT,
                                  seed=C.SEED + (1 if key == "retention_1" else 7))
        boots[key] = bt
        gate[key] = {**res.to_dict(), "boot_abs_ci": list(S.percentile_ci(bt["abs_lift"], C.ALPHA)),
                     "boot_share_ge_0": float((bt["abs_lift"] >= 0).mean()),
                     "mde": S.mde(res.rate_c, nt, nc, C.ALPHA, C.POWER)}
    rt, rc = c.loc[c.version == G_T, "sum_gamerounds"], c.loc[c.version == G_C, "sum_gamerounds"]
    gate["rounds"] = {"mean_t": float(rt.mean()), "mean_c": float(rc.mean()), "median_t": float(rt.median()),
                      "median_c": float(rc.median()), "mannwhitney_p": float(sps.mannwhitneyu(rt, rc).pvalue)}
    # does the D7 gap sit with players who actually reached level 30? (descriptive)
    gate["d7_by_reached_30"] = (c.groupby(["reached_gate_30", "version"])["retention_7"].agg(["mean", "size"])
                                .reset_index().assign(reached_gate_30=lambda d: d.reached_gate_30.astype(str))
                                .to_dict(orient="records"))
    out = {"overall": overall, "funnel": funnel.to_dict(orient="records"),
           "by_rounds_bucket": by_rounds.assign(rounds_bucket=lambda d: d.rounds_bucket.astype(str)).to_dict(orient="records"),
           "by_d1_status": by_d1.to_dict(orient="records"), "by_version": by_version.to_dict(orient="records"),
           "gap_by_dimension": gaps.to_dict(orient="records"), "gate": gate}
    return out, boots


# ====================================================================== orchestrate
def build_all(verbose: bool = True) -> dict:
    C.ensure_dirs()
    D.link_raw()
    m_raw, c_raw = D.load_marketing_raw(), D.load_cookie_raw()
    m = D.clean_marketing(m_raw)
    c, c_out = D.clean_cookie(c_raw)
    cells = D.aggregate_ad_cells(m)

    # caches for dashboard / report
    cells.to_parquet(C.PROCESSED_DIR / "agg_ad_cells.parquet", index=False)
    m.assign(most_ads_day=m.most_ads_day.astype(str), exposure_bucket=m.exposure_bucket.astype(str)) \
        .to_parquet(C.PROCESSED_DIR / "fct_ad_exposure_users.parquet", index=False)
    c.assign(rounds_bucket=c.rounds_bucket.astype(str)).to_parquet(C.PROCESSED_DIR / "fct_game_players.parquet", index=False)

    results = {"config": {"seed": C.SEED, "alpha": C.ALPHA, "power": C.POWER, "n_bootstrap": C.N_BOOT,
                          "intended_ad_share": C.INTENDED_AD_SHARE, "value_per_conversion_usd": C.VALUE_PER_CONVERSION}}
    results["data_quality"] = data_quality(m_raw, m, c_raw, c, c_out)
    results["ad"], ad_extra = ad_experiment(m, cells)
    results["cookie"], cookie_boots = cookie_analysis(c)

    ad_extra["boot"].to_parquet(C.PROCESSED_DIR / "boot_ad_lift.parquet", index=False)
    pd.concat([b.assign(metric=k) for k, b in cookie_boots.items()]).to_parquet(
        C.PROCESSED_DIR / "boot_gate_lift.parquet", index=False)

    results = _r(results)
    with open(C.RESULTS_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)
    if verbose:
        a = results["ad"]["test"]
        g = results["cookie"]["gate"]
        print(f"[analysis] ad lift {a['abs_lift']*100:.3f}pp (95% CI {a['abs_ci_low']*100:.3f} to "
              f"{a['abs_ci_high']*100:.3f}), rel {a['rel_lift']*100:.1f}%, p={a['p_value']:.2e}")
        print(f"[analysis] gate D7 diff {g['retention_7']['abs_lift']*100:.3f}pp, p={g['retention_7']['p_value']:.4f}; "
              f"SRM p={g['srm']['p_value']:.4f}")
    return results


def load_results() -> dict:
    with open(C.RESULTS_JSON) as f:
        return json.load(f)
