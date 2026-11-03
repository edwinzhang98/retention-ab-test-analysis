"""Builds notebooks/03_ab_test.ipynb: the A/B test readout (ad campaign and gate experiment).

How it works
  1. The notebook is declared below as a list of markdown and code cells.
  2. The code cells are executed in-process (charts and display() stubbed out) so that every
     number quoted in the markdown can be computed; quoted numbers are written as placeholders
     and filled from those values.
  3. A final appendix cell re-checks every quoted number when the notebook runs and fails if
     any of them has drifted from reports/results.json or the clean data.
  4. The notebook is written with deterministic cell ids, so rebuilds give readable git diffs.

This script only writes the .ipynb. Execute it and export HTML with
`python run.py --only notebooks` (or run everything with `make notebooks`).

Usage (from anywhere): .venv/bin/python scripts/notebooks/build_03_ab_test.py
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

import nbformat as nbf

REPO = Path(__file__).resolve().parents[2]  # scripts/notebooks/ -> repo root
NB_PATH = REPO / "notebooks" / "03_ab_test.ipynb"

CELLS: list[tuple[str, str]] = []
QUOTED_EXPR: dict[str, str] = {}


def md(text: str) -> None:
    CELLS.append(("markdown", dedent(text).strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", dedent(text).strip("\n")))


def q(**kw: str) -> None:
    for k, v in kw.items():
        if k in QUOTED_EXPR:
            raise KeyError(f"duplicate quoted key {k}")
        QUOTED_EXPR[k] = v


# =====================================================================================
# Quoted numbers: key -> expression evaluated in the executed notebook's namespace
# =====================================================================================
q(
    alpha='format(C.ALPHA, "g")',
    power='format(C.POWER, ".0%")',
    n_boot="num(C.N_BOOT)",
    seed="str(C.SEED)",
    m_rows='num(res["data_quality"]["marketing"]["rows_clean"])',
    c_rows_raw='num(res["data_quality"]["cookie"]["rows_raw"])',
    c_rows_clean='num(res["data_quality"]["cookie"]["rows_clean"])',
    outlier_rounds='num(res["data_quality"]["cookie"]["outliers_dropped"][0]["sum_gamerounds"])',
    # ---- ad experiment: headline test
    ad_rate_t="pct(r_ad.rate_t, 2)",
    ad_rate_c="pct(r_ad.rate_c, 2)",
    ad_lift="pp(r_ad.abs_lift)",
    ad_ci_lo="pp(r_ad.abs_ci_low)",
    ad_ci_hi="pp(r_ad.abs_ci_high)",
    ad_rel="spct(r_ad.rel_lift)",
    ad_rel_lo="spct(r_ad.rel_ci_low)",
    ad_rel_hi="spct(r_ad.rel_ci_high)",
    ad_z='format(r_ad.z, ".2f")',
    ad_p_sci="sci(r_ad.p_value)",
    ad_p_txt="fmt_p(r_ad.p_value)",
    ad_chi2='format(chi2_ad, ".1f")',
    n_t="num(r_ad.n_t)",
    n_c="num(r_ad.n_c)",
    n_t_k='format(r_ad.n_t / 1e3, ".0f") + "K"',
    conv_t="num(r_ad.conv_t)",
    conv_c="num(r_ad.conv_c)",
    n_total="num(r_ad.n_t + r_ad.n_c)",
    n_total_k='format((r_ad.n_t + r_ad.n_c) / 1e3, ".0f") + "K"',
    psa_share='format(r_ad.n_c / (r_ad.n_t + r_ad.n_c), ".0%")',
    var_share_c='format(var_share_c, ".0%")',
    # ---- trust checks: SRM, quota exactness, exposure parity
    srm_ad_p='p_txt(srm_ad["p_value"])',
    srm_ad_status='srm_ad["status"]',
    srm_expected_t='format(srm_ad["expected_t"], ",.2f")',
    srm_fail='format(C.SRM_FAIL_P, "g")',
    srm_warn='format(C.SRM_WARN_P, "g")',
    quota_dev='format(quota["deviation_users"], ".2f")',
    quota_sd='format(quota["sd_users_under_random_assignment"], ".0f")',
    quota_prob='pct(quota["prob_exactly_nearest_integer"], 2)',
    sim_hit="pct(sim_hit, 2)",
    mean_ads_t='format(A["groups"]["ad"]["mean_ads"], ".1f")',
    mean_ads_c='format(A["groups"]["psa"]["mean_ads"], ".1f")',
    median_ads_t='format(A["groups"]["ad"]["median_ads"], ".0f")',
    median_ads_c='format(A["groups"]["psa"]["median_ads"], ".0f")',
    ks_d='format(A["total_ads_ks"]["stat"], ".3f")',
    ks_pp='format(A["total_ads_ks"]["stat"] * 100, ".0f")',
    e15_ad='pct(expo_mix.loc["1-5", "ad"], 0)',
    e15_psa='pct(expo_mix.loc["1-5", "psa"], 0)',
    e1120_ad='pct(expo_mix.loc["11-20", "ad"], 0)',
    e1120_psa='pct(expo_mix.loc["11-20", "psa"], 0)',
    v_day='format(bal.set_index("variable").loc["most_ads_day", "cramers_v"], ".3f")',
    v_hour='format(bal.set_index("variable").loc["most_ads_hour", "cramers_v"], ".3f")',
    v_expo='format(bal.set_index("variable").loc["exposure_bucket", "cramers_v"], ".3f")',
    bal_p_max='fmt_p(bal["p_value"].max())',
    # ---- intervals
    nw_lo="pp(r_ad.abs_ci_low, 3)",
    nw_hi="pp(r_ad.abs_ci_high, 3)",
    wald_lo="pp(wald_ad[0], 3)",
    wald_hi="pp(wald_ad[1], 3)",
    boot_lo="pp(boot_ci_ad[0], 3)",
    boot_hi="pp(boot_ci_ad[1], 3)",
    boot_le0='num((boot_ad["abs_lift"] <= 0).sum())',
    rel_katz='spct(r_ad.rel_ci_low, 1) + " to " + spct(r_ad.rel_ci_high, 1)',
    rel_boot='spct(boot_rel_ci_ad[0], 1) + " to " + spct(boot_rel_ci_ad[1], 1)',
    # ---- power
    sesoi_rel='format(sesoi, ".0%")',
    sesoi_abs="pp(sesoi * p_c)",
    sesoi_conv_r="num(round(sesoi_conv, -2))",
    sesoi_value_k='format(sesoi_conv * C.VALUE_PER_CONVERSION / 1e3, ".0f") + "K"',
    mde_now='pp(pw["mde_current"]["mde_abs"])',
    mde_now_rel='format(pw["mde_current"]["mde_rel"], ".0%")',
    mde_5050='pp(pw["mde_if_5050_same_total"]["mde_abs"])',
    mde_5050_rel='format(pw["mde_if_5050_same_total"]["mde_rel"], ".1%")',
    mde_8020='pp(mde_tab.set_index("split").loc["80 / 20", "mde_abs"])',
    mde_9010='pp(mde_tab.set_index("split").loc["90 / 10", "mde_abs"])',
    pow10_now='pct(pw_at["0.1"]["power_current_split"], 0)',
    pow10_5050='approx_pct(pw_at["0.1"]["power_5050_same_total"])',
    pow10_8020='pct(mde_tab.set_index("split").loc["80 / 20", "power_sesoi"], 0)',
    pow05_now='pct(pw_at["0.05"]["power_current_split"], 0)',
    pow05_5050='pct(pw_at["0.05"]["power_5050_same_total"], 0)',
    n10_50="num(n10[0.5])",
    n10_50_k='format(n10[0.5] / 1e3, ".0f") + "K"',
    n10_80="num(n10[0.8])",
    n10_96="num(n10[C.INTENDED_AD_SHARE])",
    n10_ratio='format(n10[C.INTENDED_AD_SHARE] / n10[0.5], ".1f")',
    forgone_96='num(mde_tab.set_index("split").loc["96 / 4 (actual)", "forgone"])',
    forgone_80='num(mde_tab.set_index("split").loc["80 / 20", "forgone"])',
    forgone_50='num(mde_tab.set_index("split").loc["50 / 50", "forgone"])',
    # ---- business
    inc='num(bz["incremental_conversions"]["point"])',
    inc_r='num(round(bz["incremental_conversions"]["point"], -2))',
    inc_lo_r='num(round(bz["incremental_conversions"]["ci_low"], -2))',
    inc_hi_r='num(round(bz["incremental_conversions"]["ci_high"], -2))',
    impr_m='format(bz["impressions_ad_group"] / 1e6, ".1f")',
    impr_per_inc='num(bz["impressions_per_incremental_conversion"])',
    share_incr='format(bz["share_of_ad_conversions_incremental"], ".0%")',
    share_incr_lo='format(bz["share_of_ad_conversions_incremental_ci"][0], ".0%")',
    share_incr_hi='format(bz["share_of_ad_conversions_incremental_ci"][1], ".0%")',
    overstate='format(bz["last_touch_overstatement_x"], ".1f")',
    overstate_lo='format(bz["last_touch_overstatement_ci"][0], ".1f")',
    overstate_hi='format(bz["last_touch_overstatement_ci"][1], ".1f")',
    value='format(bz["value_per_conversion_usd"], ".0f")',
    be_cpm='format(bz["breakeven_cpm_usd"]["point"], ".2f")',
    be_lo='format(bz["breakeven_cpm_usd"]["ci_low"], ".2f")',
    be_hi='format(bz["breakeven_cpm_usd"]["ci_high"], ".2f")',
    be_per_usd='format(bz["breakeven_cpm_usd"]["point"] / bz["value_per_conversion_usd"], ".2f")',
    inc_value_k='format(bz["incremental_value_usd"]["point"] / 1e3, ".0f") + "K"',
    inc_value_lo_k='format(bz["incremental_value_usd"]["ci_low"] / 1e3, ".0f") + "K"',
    inc_value_hi_k='format(bz["incremental_value_usd"]["ci_high"] / 1e3, ".0f") + "K"',
    holdout_share='format(hold["share"], ".0%")',
    holdout_users_k='format(hold["users_per_588k_flight"] / 1e3, ".1f") + "K"',
    holdout_conv='num(hold["conversions_forgone"])',
    holdout_value_k='format(hold["value_forgone_usd"] / 1e3, ".1f") + "K"',
    asrun_share='format(hold["as_run_control_share"], ".0%")',
    asrun_conv='num(hold["as_run_control_conversions_forgone"])',
    holdout_extra='num(hold["extra_conversions_vs_as_run"])',
    # ---- heterogeneity: interaction tests
    n_dims='str(het["n_dimensions_explored"])',
    lrt_day_p='p_txt(het["most_ads_day"]["lrt"]["p_value"])',
    lrt_day_bonf='fmt_p(het["most_ads_day"]["lrt_p_bonferroni_3_dims"])',
    lrt_hour_p='p_txt(het["most_ads_hour"]["lrt"]["p_value"])',
    lrt_hour_nonight='fmt_p(het["most_ads_hour"]["lrt_excluding_night"]["p_value"])',
    lrt_dp_p='p_txt(het["daypart"]["lrt"]["p_value"])',
    lrt_dp_nonight='fmt_p(het["daypart"]["lrt_excluding_night"]["p_value"])',
    lrt_expo_p='p_txt(het["exposure_bucket"]["lrt"]["p_value"])',
    hour_zero_cells='str(het["most_ads_hour"]["lrt"]["cells_with_zero_conversions"])',
    # ---- heterogeneity: segment-vs-rest contrasts
    n_contrasts="str(sum(len(order) for _, order in DIMS.values()))",
    day_diff_segs='" and ".join(het["most_ads_day"]["segments_differing_holm"])',
    expo_diff_n='str(het["exposure_bucket"]["differs_from_rest"]["holm"])',
    hour_diff_raw='str(het["most_ads_hour"]["differs_from_rest"]["none"])',
    efp_hour='format(24 * C.ALPHA, ".1f")',
    day_max_seg='het["most_ads_day"]["max_lift_segment"]',
    day_max='format(het["most_ads_day"]["max_lift_pp"], ".2f")',
    day_min_seg='het["most_ads_day"]["min_lift_segment"]',
    day_min='format(het["most_ads_day"]["min_lift_pp"], ".2f")',
    tue_vs_rest='spp(day_c.loc["Tuesday", "diff_vs_rest"])',
    tue_vs_rest_lo='spp(day_c.loc["Tuesday", "diff_vs_rest_ci_low"])',
    tue_vs_rest_hi='spp(day_c.loc["Tuesday", "diff_vs_rest_ci_high"])',
    tue_p_holm='fmt_p(day_c.loc["Tuesday", "p_vs_rest_adj"])',
    thu_vs_rest='spp(day_c.loc["Thursday", "diff_vs_rest"])',
    thu_vs_rest_lo='spp(day_c.loc["Thursday", "diff_vs_rest_ci_low"])',
    thu_vs_rest_hi='spp(day_c.loc["Thursday", "diff_vs_rest_ci_high"])',
    thu_p_holm='fmt_p(day_c.loc["Thursday", "p_vs_rest_adj"])',
    tue_n_c='num(day_c.loc["Tuesday", "n_c"])',
    tue_conv_c='num(day_c.loc["Tuesday", "conv_c"])',
    tue_rate_c='pct(day_c.loc["Tuesday", "rate_c"], 2)',
    hour_min_p_rest='fmt_p(seg["most_ads_hour"]["none"]["p_vs_rest"].min())',
    min_c_hour='num(het["most_ads_hour"]["min_control_users"])',
    max_c_hour='num(seg["most_ads_hour"]["holm"]["n_c"].max())',
    hour_zero_n="str(len(hour_zero))",
    hour_zero_list="hour_ranges(hour_zero)",
    night_conv_c='str(het["daypart"]["night_counts"]["psa"]["conversions"])',
    night_n_c='num(het["daypart"]["night_counts"]["psa"]["users"])',
    night_conv_t='num(het["daypart"]["night_counts"]["ad"]["conversions"])',
    night_n_t='num(het["daypart"]["night_counts"]["ad"]["users"])',
    night_vs_rest='spp(dp_c.loc[NIGHT, "diff_vs_rest"])',
    night_vs_rest_lo='spp(dp_c.loc[NIGHT, "diff_vs_rest_ci_low"])',
    night_vs_rest_hi='spp(dp_c.loc[NIGHT, "diff_vs_rest_ci_high"])',
    night_p_holm='fmt_p(dp_c.loc[NIGHT, "p_vs_rest_adj"])',
    night_or='format(dp_or[NIGHT], ".0f")',
    other_or_lo='format(dp_or.drop(NIGHT).min(), ".1f")',
    other_or_hi='format(dp_or.drop(NIGHT).max(), ".1f")',
    mh_min='format(sens_tab["lift (pp)"].iloc[1:].min(), ".2f")',
    mh_max='format(sens_tab["lift (pp)"].iloc[1:].max(), ".2f")',
    # ---- exposure
    share_le20='pct(con["share_users_le_20_ads"], 0)',
    low_lift_min='spp(ex.loc[LIGHT, "abs_lift"].min())',
    low_lift_max='spp(ex.loc[LIGHT, "abs_lift"].max())',
    le20_lift="spp(le20.abs_lift)",
    le20_lo="spp(le20.abs_ci_low)",
    le20_hi="spp(le20.abs_ci_high)",
    b2135_share='pct(con["bucket_21_35"]["share_ad_users"], 0)',
    b2135_lift='spp(ex.loc["21-35", "abs_lift"])',
    b2135_lo='spp(ex.loc["21-35", "abs_ci_low"])',
    b2135_hi='spp(ex.loc["21-35", "abs_ci_high"])',
    lift_36_50='pp(ex.loc["36-50", "abs_lift"], 1)',
    lift_101_200='pp(ex.loc["101-200", "abs_lift"], 1)',
    share_inc_heavy='pct(con["share_incremental_conversions_36_200"], 0)',
    share_users_heavy='pct(con["share_ad_users_36_200"], 0)',
    inc_heavy='num(con["incremental_conversions_36_200"])',
    inc_bucketwise='num(con["incremental_conversions_bucketwise_total"])',
    inc_b15='num(ex.loc["1-5", "incremental"])',
    inc_b610='num(ex.loc["6-10", "incremental"])',
    top_ci_lo='num(con["top_bucket_ci_pp"][0], 1)',
    top_ci_hi='snum(con["top_bucket_ci_pp"][1], 1)',
    n_c_200='num(con["top_bucket_control_users"])',
    psa_rate_low='pct(con["control_rate_lowest_bucket"])',
    psa_rate_high='pct(con["control_rate_highest_bucket"])',
    # ---- gate experiment: SRM
    g_n40_raw='num(G["players_raw"]["gate_40"])',
    g_n30_raw='num(G["players_raw"]["gate_30"])',
    gate_excess_raw='num(G["excess_players_raw"])',
    gate_share='pct(srm_gate["observed_share_t"], 2)',
    gate_srm_p='fmt_p(srm_gate["p_value"])',
    gate_srm_status='srm_gate["status"]',
    g_n40="num(n40)",
    g_n30="num(n30)",
    excess_clean="num(n40 - n30)",
    zero_n="num(len(zero))",
    zero_d1="num(zero_d1)",
    zero_d7="num(zero_d7)",
    zero_share="pct(zero_d1 / len(players))",
    # ---- gate experiment: naive readout
    g7_t='pct(gate_res["retention_7"].rate_t, 2)',
    g7_c='pct(gate_res["retention_7"].rate_c, 2)',
    g7_lift='spp(gate_res["retention_7"].abs_lift)',
    g7_lift_abs='pp(abs(gate_res["retention_7"].abs_lift))',
    g7_lo='spp(gate_res["retention_7"].abs_ci_low)',
    g7_hi='spp(gate_res["retention_7"].abs_ci_high)',
    g7_rel='spct(gate_res["retention_7"].rel_lift, 1)',
    g7_p='fmt_p(gate_res["retention_7"].p_value)',
    g1_t='pct(gate_res["retention_1"].rate_t, 2)',
    g1_c='pct(gate_res["retention_1"].rate_c, 2)',
    g1_lift='spp(gate_res["retention_1"].abs_lift)',
    g1_lo='spp(gate_res["retention_1"].abs_ci_low)',
    g1_hi='spp(gate_res["retention_1"].abs_ci_high)',
    g1_p='fmt_p(gate_res["retention_1"].p_value)',
    g7_boot_below='pct(1 - G["retention_7"]["boot_share_ge_0"])',
    g1_boot_below='pct(1 - G["retention_1"]["boot_share_ge_0"])',
    # ---- gate experiment: where the extra installs are, pre-gate play
    lt15_n40='num(srm_strata.loc["rounds_lt_15", "gate_40"])',
    lt15_n30='num(srm_strata.loc["rounds_lt_15", "gate_30"])',
    excess_lt15='num(G["excess_players_with_lt_15_rounds"])',
    lt15_p='fmt_p(srm_strata.loc["rounds_lt_15", "chi-square p"])',
    b1529_excess='snum(srm_strata.loc["rounds_15_29", "net excess in gate_40"])',
    b1529_srm_p='fmt_p(srm_strata.loc["rounds_15_29", "chi-square p"])',
    ge30_excess='snum(srm_strata.loc["rounds_ge_30", "net excess in gate_40"])',
    ge30_n40='num(srm_strata.loc["rounds_ge_30", "gate_40"])',
    ge30_n30='num(srm_strata.loc["rounds_ge_30", "gate_30"])',
    ge30_p='fmt_p(srm_strata.loc["rounds_ge_30", "chi-square p"])',
    pre_mean40='format(G["pre_gate_engagement"]["mean_capped_29_t"], ".2f")',
    pre_mean30='format(G["pre_gate_engagement"]["mean_capped_29_c"], ".2f")',
    pre_mw_p='fmt_p(G["pre_gate_engagement"]["mannwhitney_p"])',
    pre_mw_p_lt30='fmt_p(G["pre_gate_engagement"]["mannwhitney_p_within_lt_30"])',
    zero40='pct(G["composition"]["zero_round_share"]["gate_40"], 2)',
    zero30='pct(G["composition"]["zero_round_share"]["gate_30"], 2)',
    u30_40='pct(G["composition"]["under_30_share"]["gate_40"])',
    u30_30='pct(G["composition"]["under_30_share"]["gate_30"])',
    # ---- gate experiment: negative control by rounds band
    nc_d7='spp(nc_res[("never_reached_30", "retention_7")].abs_lift)',
    nc_d7_abs='pp(abs(nc_res[("never_reached_30", "retention_7")].abs_lift))',
    nc_d7_lo='spp(nc_res[("never_reached_30", "retention_7")].abs_ci_low)',
    nc_d7_hi='ci_end(nc_res[("never_reached_30", "retention_7")].abs_ci_high)',
    nc_d7_p='fmt_p(nc_res[("never_reached_30", "retention_7")].p_value)',
    b15_d7='spp(nc_res[("rounds_lt_15", "retention_7")].abs_lift)',
    b15_p='fmt_p(nc_res[("rounds_lt_15", "retention_7")].p_value)',
    b1529_d7='spp(nc_res[("rounds_15_29", "retention_7")].abs_lift)',
    b1529_p='fmt_p(nc_res[("rounds_15_29", "retention_7")].p_value)',
    b1529_lo='spp(nc_res[("rounds_15_29", "retention_7")].abs_ci_low)',
    b1529_hi='spp(nc_res[("rounds_15_29", "retention_7")].abs_ci_high)',
    band_gap_p="fmt_p(gap_diff_p)",
    b1528_d7='spp(nc_res[("rounds_15_28", "retention_7")].abs_lift)',
    b1528_lo='spp(nc_res[("rounds_15_28", "retention_7")].abs_ci_low)',
    b1528_hi='spp(nc_res[("rounds_15_28", "retention_7")].abs_ci_high)',
    r29_n40='num(nc_res[("rounds_29", "retention_7")].n_t)',
    r29_n30='num(nc_res[("rounds_29", "retention_7")].n_c)',
    ncx_removed="num(ex15)",
    ncx_d7="spp(nc_removed.abs_lift)",
    ncx_lo="spp(nc_removed.abs_ci_low)",
    ncx_hi="spp(nc_removed.abs_ci_high)",
    ncx_p="fmt_p(nc_removed.p_value)",
    re_d7='spp(nc_res[("reached_30", "retention_7")].abs_lift)',
    re_d7_lo='spp(nc_res[("reached_30", "retention_7")].abs_ci_low)',
    re_d7_hi='spp(nc_res[("reached_30", "retention_7")].abs_ci_high)',
    re_d7_p='fmt_p(nc_res[("reached_30", "retention_7")].p_value)',
    share_reach='pct(dec7["share_reached_30"], 0)',
    # ---- gate experiment: decomposition, best case
    dec_mix='spp(dec7["composition"])',
    dec_never='spp(dec7["within_never_reached_30"])',
    dec_reach='spp(dec7["within_reached_30"])',
    dec_reach_1='spp(dec7["within_reached_30"], 1)',
    dec_reach_lo='spp(dec7["ci"][0])',
    dec_reach_hi='spp(dec7["ci"][1])',
    not_gate_share='format(round(not_gate_share * 10) * 10, ".0f") + "%"',
    per10k="num(abs(per10k[0]))",
    per10k_lo="num(abs(per10k[1]))",
    per10k_hi="num(abs(per10k[2]))",
    best_d7="spp(best.abs_lift)",
    best_lo="spp(best.abs_ci_low)",
    best_hi="spp(best.abs_ci_high)",
    best_p="fmt_p(best.p_value)",
    # ---- gate experiment: guardrails
    d1_mix='spp(dec1["composition"])',
    d1_never='spp(dec1["within_never_reached_30"])',
    d1_reach_pi='spp(dec1["within_reached_30"])',
    d1_reach_pi_lo='spp(dec1["ci"][0])',
    d1_reach_pi_hi='spp(dec1["ci"][1])',
    re_d1='spp(nc_res[("reached_30", "retention_1")].abs_lift)',
    re_d1_lo='spp(nc_res[("reached_30", "retention_1")].abs_ci_low)',
    re_d1_hi='spp(nc_res[("reached_30", "retention_1")].abs_ci_high)',
    rounds_diff='snum(G["rounds"]["mean_diff"], 2)',
    rounds_lo='snum(G["rounds"]["mean_diff_boot_ci"][0], 1)',
    rounds_hi='snum(G["rounds"]["mean_diff_boot_ci"][1], 1)',
    rounds_nboot='num(G["rounds"]["n_boot"])',
    r30_med40='format(rr["median_t"], ".0f")',
    r30_med30='format(rr["median_c"], ".0f")',
    r30_mw_p='fmt_p(rr["mannwhitney_p"])',
    r30_past40_t="pct(past40.rate_t)",
    r30_past40_c="pct(past40.rate_c)",
    r30_past40_diff="spp(past40.abs_lift)",
    r30_past40_lo="spp(past40.abs_ci_low)",
    r30_past40_hi="spp(past40.abs_ci_high)",
    r30_mean_diff='snum(rr["mean_diff"], 1)',
    r30_mean_lo='snum(rr["mean_diff_boot_ci"][0], 1)',
    r30_mean_hi='snum(rr["mean_diff_boot_ci"][1], 1)',
    # ---- gate experiment: MDE as run, re-test sizing
    g7_mde='pp(G["retention_7"]["mde"]["mde_abs"])',
    g7_mde_rel='format(G["retention_7"]["mde"]["mde_rel"], ".1%")',
    g1_mde='pp(G["retention_1"]["mde"]["mde_abs"])',
    gate_sesoi='format(sesoi_g * 100, "g")',
    gate_sesoi_rel="pct(sesoi_g / base_install, 1)",
    g7_base_1="pct(base_install, 1)",
    retest_equiv='pp(rs["equivalent_change_among_reachers"])',
    retest_base_reach='pct(rs["baseline_d7_reachers"], 1)',
    retest_reachers="num(n_reach)",
    retest_reachers_k='format(n_reach / 1e3, ".0f") + "K"',
    retest_reacher_installs="num(n_reach_installs)",
    retest_reacher_installs_k='format(n_reach_installs / 1e3, ".0f") + "K"',
    retest_install="num(n_install)",
    retest_install_k='format(n_install / 1e3, ".0f") + "K"',
    retest_share_reach="pct(w_reach, 1)",
    retest_rise_extra='format(max(n_install_rise / n_install, n_reach_installs_rise / n_reach_installs) - 1, ".0%")',
    retest_install_rise_k='format(n_install_rise / 1e3, ".0f") + "K"',
    retest_reacher_installs_rise_k='format(n_reach_installs_rise / 1e3, ".1f") + "K"',
    # ---- retention (R6), from results.json
    no_d1='pct(1 - res["cookie"]["overall"]["retention_1"])',
    r6_share_lt15='pct(early["share_of_installs"], 0)',
    r6_d7='pct(early["retention_7"])',
    d7_if_d1='pct(early["d7_if_returned_day1"])',
    d7_if_not_d1='pct(early["d7_if_not_returned_day1"])',
    r6_scenario='format(early["d7_if_returned_day1"] - early["d7_if_not_returned_day1"], ".2f")',
    r6_lift='format(C.ONBOARD_LIFT_ABS * 100, "g")',
    r6_players_k='format(early["onboarding_test_sizing"]["players_needed_5050"] / 1e3, ".0f") + "K"',
    r6_installs_k='format(early["onboarding_test_sizing"]["installs_needed_5050"] / 1e3, ".0f") + "K"',
)


def chart(key: str) -> None:
    """A catalog chart; show() prints its takeaway underneath at run time (always current, readable on GitHub)."""
    code(f'show("{key}")')


# =====================================================================================
# Notebook content
# =====================================================================================
md("""
# A/B test readout: ad campaign (ad vs PSA) and progression gate (gate_30 vs gate_40)

**Notebook 3 of 3** · Product Analyst, Growth · for the Growth PM (ad campaign) and the Game PM (progression gate) · Data quality is covered in `01_eda`, new-player retention in `02_retention`.

Every headline number comes from `reports/results.json` (written by `python run.py`). The cells below recompute the key ones from the cached tables in `data/processed/` and assert that they match, and the appendix re-checks every number quoted in the text. Charts are the same objects the dashboard and `reports/report.html` use (`src.catalog`); each chart's subtitle is its one-sentence takeaway, which is also printed as text below the chart.

**Charts load plotly.js from a CDN.** That keeps this notebook and its HTML export (`reports/notebooks/03_ab_test.html`) small, but the charts need an internet connection and don't render in GitHub's notebook preview. `reports/report.html` is the fully offline version of the same charts.
""")

md("""
## TL;DR

- **The ad campaign drove conversions.** Users shown ads converted at {{ad_rate_t}} vs {{ad_rate_c}} for the PSA control: **+{{ad_lift}} pp (95% CI {{ad_ci_lo}} to {{ad_ci_hi}}, p {{ad_p_txt}})**, a {{ad_rel}} relative lift (CI {{ad_rel_lo}} to {{ad_rel_hi}}). Wald and bootstrap intervals agree. The sample-ratio (SRM) check passes but tells us little: the ad arm is {{quota_dev}} users from exactly 96%, where random assignment typically misses by ±{{quota_sd}} and lands on the nearest whole number only {{quota_prob}} of the time, so the split is most likely a fixed quota. Fixed arm sizes are a valid design; they just make the SRM test uninformative. The meaningful check, exposure parity, holds on average ({{mean_ads_t}} vs {{mean_ads_c}} ads per user).
- **≈{{inc_r}} incremental conversions (95% CI {{inc_lo_r}}–{{inc_hi_r}})**, only {{share_incr}} of the ad arm's conversions (CI {{share_incr_lo}}–{{share_incr_hi}}). Last-touch (any-touch) attribution would credit every ad-arm conversion to the ads and overstate the campaign **{{overstate}}× (95% CI {{overstate_lo}}–{{overstate_hi}}×)**. At an *illustrative* USD {{value}} per conversion (the data has no revenue), the campaign pays back below a **CPM of USD {{be_cpm}}** (CI USD {{be_lo}}–{{be_hi}}).
- **The design was weak for small lifts.** 96/4 had {{power}} power only for lifts ≥ {{mde_now}} pp ({{mde_now_rel}} relative). For the smallest lift worth acting on ({{sesoi_rel}} relative = {{sesoi_abs}} pp, a placeholder in `config.yaml`), power was {{pow10_now}}, vs {{pow10_5050}} had the same users been split 50/50.
- **"Double the budget?" can't be answered from this test**: nobody's budget or frequency was varied. The lift lives in heavy users: the {{share_le20}} of users who saw ≤ 20 ads show no lift we could measure ({{le20_lift}} pp), while the 36–200-ad buckets hold {{share_users_heavy}} of ad users and {{share_inc_heavy}} of the bucket-by-bucket incremental conversions. Exposure tracks how active a user is, so this is a hypothesis for a randomized impressions / frequency-cap test (R2), not a frequency curve.
- **No basis for re-planning spend by day or hour.** Peak day: interaction {{lrt_day_p}} ({{lrt_day_bonf}} allowing for the {{n_dims}} dimensions explored); Tuesday-peak users' lift is {{tue_vs_rest}} pp vs the other days' and Thursday-peak users' {{thu_vs_rest}} pp, both surviving Holm, but peak day is a user habit recorded after assignment, not a slot we buy. Hour: {{lrt_hour_p}}. Dayparts: {{lrt_dp_p}}, driven by Night ({{night_conv_c}} control conversion among {{night_n_c}} users), {{lrt_dp_nonight}} without it. If timing matters, pre-register a test that randomizes the delivery schedule (R3).
- **Gate experiment (Cookie Cats): keep the gate at level 30; the result is not certified.** Naive D7: gate_40 shows {{g7_lift_abs}} pp lower ({{g7_t}} vs {{g7_c}}; 95% CI {{g7_lo}} to {{g7_hi}}), but assignment is unbalanced (SRM p = {{gate_srm_p}}, {{gate_srm_status}}): gate_40 has ≈{{excess_clean}} extra installs, with a net excess of {{excess_lt15}} among players with < 15 rounds. About {{not_gate_share}} of the naive gap sits where the gate cannot act. The rest, {{dec_reach}} pp per install (95% CI {{dec_reach_lo}} to {{dec_reach_hi}}), is the part the gate could explain, not an estimate of its effect, and there is no sign of a retention benefit. Fix assignment first; re-test only if the gate position matters commercially (≈{{retest_reacher_installs_k}} installs at 50/50, pre-registering a {{gate_sesoi}} pp D7 change per install as the smallest worth acting on).
""")

md("""
## 1. Question

The Growth PM asked: *"Did last quarter's ad campaign drive conversions? If so, is it worth doubling the budget?"* (the "which new users leave first?" half of the request is answered in `02_retention`). The analysis questions, as scoped in `docs/01_request_and_scope.md`:

| # | Analysis question | Decision it informs | Owner |
|---|---|---|---|
| Q1 | In the randomized ad-vs-PSA test, is the user-level conversion rate higher with ads, by how much (pp and %, with 95% CIs), and how many conversions are incremental? | Keep or stop the campaign | Growth PM |
| Q2 | At what CPM does the campaign break even, where does the lift come from, and what can this test *not* say about a 2× budget? | Scale 2×, hold, or test first | Growth PM + budget owner |
| Q3 | Does the lift differ by the user's peak ad day / hour (or daypart), tested as an interaction and corrected for multiple comparisons? | Daypart re-allocation | Growth PM + media buyer |
| Q5 | Second experiment: should the first progression gate move from level 30 to 40, and is that experiment trustworthy? | Ship gate_40 or keep gate_30 | Game PM |

**What would change the decision.** A lift CI that includes 0, or a failed sanity check (exposure parity; an SRM test can't fail on a quota-exact split): we can't claim the campaign worked. A breakeven CPM below what we actually pay: the campaign loses money even with a real lift. A day / hour difference that doesn't survive an interaction test and correction, or that describes users rather than something we can buy: no re-allocation. For the gate: a D7 drop with trustworthy assignment would certify "don't ship gate_40"; an SRM warning or a negative control that doesn't hold means the size of the effect can't be certified.
""")

md("""
## 2. Data

| | Ad experiment (main story) | Gate experiment (second case) |
|---|---|---|
| Source | Marketing A/B test (Kaggle, 2021): the app the ads ran in | Cookie Cats (Kaggle, 2017 install cohort): the company's mobile game, a different product from the app the ads ran in |
| Unit of randomization and analysis | user | player, assigned at install |
| Arms | `ad` (treatment) vs `psa` (public-service ad, control) | `gate_40` (treatment) vs `gate_30` (control) |
| Rows used | {{m_rows}} users, none dropped | {{c_rows_clean}} players: {{c_rows_raw}} minus 1 logging error ({{outlier_rounds}} rounds in 14 days). The SRM check uses all {{c_rows_raw}} assignments |
| Outcomes | `converted` (bool, per user) | `retention_1`, `retention_7`: played on day 1 / day 7 after install (classic, not rolling); `sum_gamerounds`: rounds in the first 14 days, so it overlaps the D7 window |
| Other fields | `total_ads`, `most_ads_day`, `most_ads_hour`: all recorded **after** assignment | none; no install dates, so all players form a single install cohort |
| Caches read here | `fct_ad_exposure_users`, `agg_ad_cells` (arm × day × hour × exposure bucket), `boot_ad_lift` | `fct_game_players`, `boot_gate_lift` |

Row reconciliation, key uniqueness, nulls, value ranges and the outlier's sensitivity are in `01_eda` and `docs/03_data_quality_checks.md`. Neither dataset has timestamps, revenue or cost; that limits what we can say about novelty effects and ROI (section 5).
""")

code('''
# Setup: make `src` importable from wherever the notebook runs (walk up to the folder with config.yaml)
import sys
from pathlib import Path

ROOT = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / "config.yaml").exists()), None)
if ROOT is None:
    raise FileNotFoundError("config.yaml not found above the working directory: run from inside the project.")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import plotly.io as pio
from IPython.display import HTML, Markdown, display
from scipy import stats as sps

from src import config as C
from src import stats as S
from src.analysis import load_results
from src.catalog import build_catalog, hour_ranges, load_caches
from src.catalog import fmt_p as p_txt   # "p = 0.013", "p < 0.0001", "p > 0.99": the chart takeaways' format

# Charts load plotly.js from a CDN, so this notebook and its HTML export stay small;
# reports/report.html is the fully offline version of the same charts.
pio.renderers.default = "notebook_connected"
pio.renderers["notebook_connected"].config = {"displaylogo": False, "typesetMath": False,
                                              "modeBarButtonsToRemove": ["lasso2d", "select2d"]}

res = load_results()               # every headline number (reports/results.json)
caches = load_caches()             # parquet caches in data/processed/
cat = build_catalog(res, caches)   # shared charts + takeaways: the same objects as the dashboard and report.html
A, G = res["ad"], res["cookie"]["gate"]
users, cells, players = caches["users"], caches["cells"], caches["players"]


def show(key: str) -> None:
    """Display a chart from the shared catalog, then its one-sentence takeaway as text: the same sentence as the
    chart's subtitle, readable where charts don't render (e.g. GitHub's preview)."""
    cat[key].fig.show()
    display(Markdown(f"**Takeaway:** {cat[key].takeaway}"))


def _m(s: str) -> str:
    """Negative numbers in text and tables get a true minus sign."""
    return s.replace("-", "\\u2212")


def table(df: pd.DataFrame, fmt: dict | None = None, bold_below: list[str] | None = None,
          index: bool = False) -> None:
    """Display a DataFrame with per-column formats (true minus signs); optionally bold p-values below alpha."""
    def wrap(f):
        return f if callable(f) else (lambda x, f=f: _m(f.format(x)))
    sty = df.style.format({k: wrap(v) for k, v in (fmt or {}).items() if k in df.columns}, na_rep="n/a")
    if bold_below:
        sty = sty.map(lambda v: "font-weight: 700" if isinstance(v, float) and v < C.ALPHA else "",
                      subset=bold_below)
    display(HTML((sty if index else sty.hide(axis="index")).to_html()))


def same(x, y) -> bool:
    """Equal up to results.json's rounding: 8 decimals, or 3 significant digits below 1e-4."""
    x, y = float(x), float(y)
    if 0 < abs(y) < 1e-4:
        return abs(x / y - 1) < 5e-3
    return abs(x - y) <= 1e-6


def pp(x, nd=2):
    """Proportion -> percentage points, no unit (0.0077 -> '0.77')."""
    return _m(f"{x * 100:.{nd}f}")


def spp(x, nd=2):
    """Signed percentage points: +0.77 / −0.82."""
    return _m(f"{x * 100:+.{nd}f}")


def pct(x, nd=1):
    return _m(f"{x * 100:.{nd}f}%")


def spct(x, nd=0):
    """Signed percent: +43% / −4.3%."""
    return _m(f"{x * 100:+.{nd}f}%")


def num(x, nd=0):
    return _m(f"{x:,.{nd}f}")


def snum(x, nd=0):
    return _m(f"{x:+,.{nd}f}")


def ci_txt(lo, hi, nd=2):
    """A CI in signed percentage points: '+0.43 to +1.42'."""
    return f"{spp(lo, nd)} to {spp(hi, nd)}"


def approx_pct(x):
    """Shares that round to 100% are shown as '≈100%'."""
    return "≈100%" if x >= 0.995 else f"{x:.0%}"


def power_fmt(x):
    """Power in tables, one decimal; values that round to 100.0% are shown as '≈100%'."""
    return "≈100%" if x >= 0.9995 else f"{x:.1%}"


def fmt_p(p):
    """p-value without the 'p': 2 significant digits like the chart takeaways ('0.013', '< 0.0001'); never 0."""
    return p_txt(p).removeprefix("p = ").removeprefix("p ")


def sci(x, nd=1):
    """Scientific notation for tiny p-values: 1.71e-13 -> '1.7 × 10⁻¹³'."""
    mantissa, exponent = f"{x:.{nd}e}".split("e")
    return f"{mantissa} × 10{str(int(exponent)).translate(str.maketrans('-0123456789', '⁻⁰¹²³⁴⁵⁶⁷⁸⁹'))}"


def ci_end(x):
    """Upper CI bound in pp; a bound that rounds to −0.00 is written as 'just below 0'."""
    return "just below 0" if -0.005 < x * 100 < 0 else spp(x)


print(f"{len(users):,} ad-experiment users · {len(players):,} Cookie Cats players · {len(cat)} shared charts")
''')

code('''
# Arm sizes and raw outcomes, straight from the user-level caches
arm_summary = (users.groupby("test_group")
               .agg(users=("user_id", "size"), conversions=("converted", "sum"),
                    impressions=("total_ads", "sum"), mean_ads=("total_ads", "mean"),
                    median_ads=("total_ads", "median"))
               .loc[["psa", "ad"]].reset_index())
arm_summary["share_of_users"] = arm_summary["users"] / arm_summary["users"].sum()
arm_summary["conversion_rate"] = arm_summary["conversions"] / arm_summary["users"]
table(arm_summary, {"users": "{:,}", "conversions": "{:,}", "impressions": "{:,}", "mean_ads": "{:.2f}",
                    "median_ads": "{:.0f}", "share_of_users": "{:.2%}", "conversion_rate": "{:.3%}"})

version_summary = (players.groupby("version")
                   .agg(players=("user_id", "size"), d1_retained=("retention_1", "sum"),
                        d7_retained=("retention_7", "sum"), median_rounds=("sum_gamerounds", "median"))
                   .reset_index())
table(version_summary, {"players": "{:,}", "d1_retained": "{:,}", "d7_retained": "{:,}", "median_rounds": "{:.0f}"})

assert len(users) == res["data_quality"]["marketing"]["rows_clean"]
assert len(players) == res["data_quality"]["cookie"]["rows_clean"]
''')

md("""
## 3. Method

| Step | What | Why |
|---|---|---|
| Hypothesis | Two-sided test of H0: p(ad) = p(psa) at α = {{alpha}} | Ads could also *hurt* conversion; a one-sided test would hide that |
| Primary test | Pooled two-proportion z-test; chi-square test on the 2×2 table as a cross-check (identical for two arms) | Standard for a binary user-level metric with large n |
| Intervals | Newcombe (hybrid score) CI for the difference; Wald CI and a {{n_boot}}-draw bootstrap for comparison; log risk-ratio CI for the relative lift | Report a range, not just a p-value. Newcombe keeps its coverage when one arm is small (PSA has {{conv_c}} conversions) |
| Trust checks | SRM: chi-square goodness of fit vs the intended split (FAIL if p < {{srm_fail}}, the Kohavi et al. convention; WARNING if p < {{srm_warn}}, this project's convention), plus how exactly the split hits its target; exposure parity; size of post-assignment differences (Cramér's V) | A broken split or unequal delivery invalidates the comparison |
| Power | Minimum detectable effect (MDE) at {{power}} power via Cohen's h; power at the smallest lift worth acting on ({{sesoi_rel}} relative, a placeholder in `config.yaml`), never at the observed effect; sample size by split | What the design could detect, and what the next test needs. An MDE describes the design; it is never compared with an observed estimate |
| Business | Incremental conversions; share of ad-arm conversions that are incremental (1 − 1/risk ratio) and the last-touch overstatement it implies, with its CI; breakeven CPM; cost of an always-on holdout | No revenue or cost in the data, so value per conversion is an explicit assumption |
| Heterogeneity | One interaction likelihood-ratio test per dimension (odds scale); then each segment's lift vs the other segments' (percentage-point scale: raw difference, Agresti–Caffo CI and p), Holm-corrected; per-segment "lift ≠ 0" tests as description only; a standardized (Mantel–Haenszel) lift as a sensitivity check | Asks "does the lift *differ*?", controls false positives, and checks that small arm imbalances don't drive the headline |
| Gate integrity | SRM on the raw assignment log; where the extra installs sit by rounds played (descriptive); pre-gate play; an approximate negative control (players with fewer than 30 rounds, almost none of whom can have met a gate); a decomposition of the D7 and D1 gaps; a best-case bound for gate_40; guardrails among players who could meet the gate | Separates the part of the gap the gate could explain from what the unbalanced assignment produced |

All statistics come from `src/stats.py`; every bootstrap uses seed {{seed}}.
""")

# --------------------------------------------------------------------------- Results A
md("""
## 4. Results

### Part A: Ad campaign (ad vs PSA)

#### A1. Hypothesis

- **H0:** showing the campaign's ads does not change the share of users who convert: p(ad) = p(psa).
- **H1:** it changes it, in either direction: p(ad) ≠ p(psa). Two-sided, α = {{alpha}}.
- The control arm saw public-service ads instead of the campaign's ads, about as many per user (A4), so the comparison isolates the effect of the ad content, not of being shown something at all.
- **Decision rule:** keep the campaign if the 95% CI for the lift excludes 0, the sanity checks hold, and the breakeven CPM is above what we actually pay.
""")

md("""
#### A2. Metrics

| Role | Metric | Definition | Why this one |
|---|---|---|---|
| **Primary** | Conversion rate | users with `converted = True` ÷ users in the arm; each user counted once | Same unit as the randomization, so observations are independent; answers "did ads drive conversions?" directly |
| Secondary | Relative lift | p(ad) ÷ p(psa) − 1 | How PMs usually quote lift; imprecise here because the control is small |
| Secondary | Incremental conversions | (p(ad) − p(psa)) × ad-arm users | Turns the lift into a count the business can value |
| Secondary | Share of ad-arm conversions that are incremental | (p(ad) − p(psa)) ÷ p(ad) = 1 − 1 / risk ratio | Shows how far last-touch attribution would overstate the campaign |
| Secondary | Impressions per incremental conversion; breakeven CPM | ad-arm impressions ÷ incremental conversions; incremental conversions × value ÷ impressions × 1,000 | Turns the lift into a price rule for "is it worth the money?" |
| Guardrail | Sample ratio (SRM) | observed vs intended 96/4 split | Detects broken assignment or logging (here it can't, see A4) |
| Guardrail | Exposure parity | mean / median `total_ads` per arm, and the shape of its distribution | Both arms should be served alike, so we compare creatives, not delivery volume |
| *Wanted, not in the data* | Ad hides / complaints / unsubscribes; churn or uninstalls; actual spend and CPA; revenue and refunds per converter; conversion timestamps | n/a | Before scaling spend: is the lift bought with annoyance, low-value conversions, or a short-lived novelty effect? |

Not used: impression-level conversion rates (impressions aren't independent, and heavy users dominate them) and any metric conditioned on `total_ads` (post-assignment, see A3).
""")

md("""
#### A3. Design critique: what this experiment can and cannot tell us

1. **The 96/4 split.** Putting 96% of users in the ad arm maximizes reach during the test, but the {{psa_share}} control ({{n_c}} users, {{conv_c}} conversions) dominates the uncertainty: about {{var_share_c}} of the variance of the difference comes from the PSA arm (unpooled variances, as in the CI; cell below). The design had little power for lifts of the size we'd still act on (A9).
2. **Post-assignment fields.** `total_ads`, `most_ads_day` (the weekday on which the user saw the most ads) and `most_ads_hour` are recorded *during* the campaign, after assignment, and the treatment can change them (for example, a user who converts may browse differently afterwards). Conditioning on them can bias the treatment effect, so they are **never used as covariates**; segment cuts on them are exploratory.
3. **No pre-assignment covariates** (country, device, signup date), so a classic covariate-balance check isn't possible. We rely on exposure parity instead.
4. **No timestamps or flight dates**, so we can't look at lift over time (novelty effect), test duration, or whether anyone peeked.
5. **The split is most likely a fixed quota.** The intended 96/4 is undocumented and inferred from the observed share, and the ad arm is the nearest whole number to exactly 96% of users (A4): most likely a fixed quota (or an export trimmed to the target). Fixed arm sizes are a valid design; they just make the SRM test uninformative, so exposure parity carries the weight.
""")

code('''
t = A["test"]
rate_t, rate_c = t["conv_t"] / t["n_t"], t["conv_c"] / t["n_c"]   # exact rates from the counts
var_t = rate_t * (1 - rate_t) / t["n_t"]                          # sampling variance of each arm's rate,
var_c = rate_c * (1 - rate_c) / t["n_c"]                          # unpooled, as in the CI of the difference
var_share_c = var_c / (var_t + var_c)
print(f"PSA arm: {t['n_c'] / (t['n_t'] + t['n_c']):.1%} of users, "
      f"{var_share_c:.0%} of the variance of the difference (unpooled variances, as in the CI)")
''')

md("""
#### A4. SRM, quota exactness and exposure parity

**Sample ratio mismatch (SRM):** if assignment and logging work, the observed split should match the intended one up to chance. A chi-square goodness-of-fit test asks how surprising the observed counts are under the intended split. That logic needs chance: if the arm sizes were *fixed* in advance to hit the target, the test has nothing to detect. So we also check how close to the target the split is, compared with what independent random assignment would produce.
""")

code('''
srm_ad = S.srm_check(t["n_t"], t["n_c"], C.INTENDED_AD_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)
quota = S.quota_exactness(t["n_t"], t["n_c"], C.INTENDED_AD_SHARE)
ref = A["srm"]
assert srm_ad["status"] == ref["status"] and same(srm_ad["p_value"], ref["p_value"]) and same(srm_ad["chi2"], ref["chi2"])
assert quota["is_nearest_integer_to_target"] == ref["is_nearest_integer_to_target"]
assert all(same(quota[k], ref[k]) for k in
           ("deviation_users", "sd_users_under_random_assignment", "prob_exactly_nearest_integer"))
table(pd.DataFrame({
    "arm": ["ad", "psa"],
    "users": [srm_ad["n_t"], srm_ad["n_c"]],
    "expected at exactly 96 / 4": [srm_ad["expected_t"], srm_ad["expected_c"]],
    "observed share": [srm_ad["observed_share_t"], 1 - srm_ad["observed_share_t"]],
}), {"users": "{:,}", "expected at exactly 96 / 4": "{:,.2f}", "observed share": "{:.4%}"})
print(f"SRM: chi2 = {srm_ad['chi2']:.2g}, {p_txt(srm_ad['p_value'])} -> {srm_ad['status']} "
      f"(FAIL if p < {srm_ad['threshold']:g}, WARNING if p < {srm_ad['warn_threshold']:g})")

# How exact is the split? Under independent random assignment the ad-arm count is Binomial(n, 0.96).
n_all = t["n_t"] + t["n_c"]
nearest = round(srm_ad["expected_t"])
table(pd.DataFrame([{
    "ad users, observed": t["n_t"], "ad users at exactly 96%": srm_ad["expected_t"],
    "deviation (users)": quota["deviation_users"],
    "SD under random assignment (users)": quota["sd_users_under_random_assignment"],
    "P(count = nearest whole number)": quota["prob_exactly_nearest_integer"],
}]), {"ad users, observed": "{:,}", "ad users at exactly 96%": "{:,.2f}", "deviation (users)": "{:+.2f}",
      "SD under random assignment (users)": "{:.0f}", "P(count = nearest whole number)": "{:.2%}"})
sim = np.random.default_rng(C.SEED).binomial(n_all, C.INTENDED_AD_SHARE, size=200_000)
sim_hit = (sim == nearest).mean()
print(f"Check by simulation, 200,000 random assignments of {n_all:,} users: SD {sim.std():.0f} users, "
      f"{sim_hit:.2%} land exactly on {nearest:,}")

# Exposure parity: were both arms served the same number of ads per user, in the same way?
grp = A["groups"]
table(pd.DataFrame({"arm": ["ad", "psa"],
                    "impressions": [grp["ad"]["impressions"], grp["psa"]["impressions"]],
                    "mean ads per user": [grp["ad"]["mean_ads"], grp["psa"]["mean_ads"]],
                    "median ads per user": [grp["ad"]["median_ads"], grp["psa"]["median_ads"]]}),
      {"impressions": "{:,}", "mean ads per user": "{:.2f}", "median ads per user": "{:.0f}"})
ks = sps.ks_2samp(users.loc[users["test_group"] == "ad", "total_ads"], users.loc[users["test_group"] == "psa", "total_ads"])
assert same(ks.statistic, A["total_ads_ks"]["stat"])
print(f"Shape of the ads-per-user distribution: KS D = {ks.statistic:.3f} "
      f"(largest gap between the two cumulative distributions, as a share of users)")
''')

md("""
**Reading.** The SRM test returns {{srm_ad_p}} (status {{srm_ad_status}}), but that pass is **uninformative**. Exactly 96% of {{n_total}} users is {{srm_expected_t}}; the ad arm has {{n_t}}, {{quota_dev}} users off. Independent random assignment would typically miss the target by about ±{{quota_sd}} users and lands on the nearest whole number only {{quota_prob}} of the time ({{sim_hit}} in the simulation). So the split is *most likely* a fixed quota (or an export trimmed to the target). Fixed arm sizes are a valid design; they just make the SRM test uninformative, because it passes by construction. In a real company the first step would be to pull the allocation config from the experimentation platform.

**Exposure parity is the meaningful check.** Both arms were served about the same number of ads per user (mean {{mean_ads_t}} vs {{mean_ads_c}}, median {{median_ads_t}} vs {{median_ads_c}}), consistent with one delivery system serving both arms and only the creative differing. The shapes differ a little (KS D = {{ks_d}}: the cumulative distributions differ by at most {{ks_pp}} pp of users): {{e15_psa}} of PSA vs {{e15_ad}} of ad users saw 1–5 ads, {{e1120_psa}} vs {{e1120_ad}} saw 11–20 (A5). We can't tell whether that comes from PSA delivery or from the ads changing behaviour, so exposure stays an exploratory cut, never a covariate.
""")

md("""
#### A5. Balance of post-assignment fields (Cramér's V)

With {{n_total_k}} users almost any difference is "significant", so we judge **size**: Cramér's V is 0 for identical distributions and 1 for complete separation; below 0.1 is conventionally negligible.
""")

code('''
bal = pd.DataFrame([S.balance_test(users, col, "test_group")
                    for col in ("most_ads_day", "most_ads_hour", "exposure_bucket")])
for row, ref in zip(bal.to_dict("records"), A["balance"]):
    assert same(row["chi2"], ref["chi2"]) and same(row["cramers_v"], ref["cramers_v"])
assert bal["p_value"].max() < 1e-4   # claim the text relies on: all three differ "with p < 0.0001"
table(bal, {"chi2": "{:.1f}", "p_value": fmt_p, "cramers_v": "{:.3f}"})


def arm_mix(col, order):
    """Share of each arm's users in each category."""
    return pd.crosstab(users[col], users["test_group"], normalize="columns").reindex(order)[["psa", "ad"]]


expo_mix = arm_mix("exposure_bucket", C.EXPOSURE_LABELS)
shares_ref = A["heterogeneity"]["exposure_bucket"]["arm_shares"]
assert all(same(expo_mix.loc[b, arm], shares_ref[b][arm]) for b in C.EXPOSURE_LABELS for arm in ("ad", "psa"))
table(expo_mix.rename(columns={"psa": "share of PSA users", "ad": "share of ad users"}).rename_axis("total ads seen"),
      {"share of PSA users": "{:.1%}", "share of ad users": "{:.1%}"}, index=True)
''')

md("""
All three fields differ by arm with p {{bal_p_max}} but small effect sizes (V = {{v_day}} for peak day, {{v_hour}} for peak hour, {{v_expo}} for exposure bucket). That is what you'd expect from fields recorded after assignment: the treatment itself can shift when and how many ads a user ends up seeing. Two consequences: they can't be used to "adjust" the estimate, and every segment result in A11–A13 is exploratory.
""")

chart("ad_balance_day")
chart("ad_balance_exposure")

md("""
#### A6. The test: recomputed from the user-level table

One row per user, so the counts below are built from scratch and compared with `results.json`. The chi-square test on the same 2×2 table must agree with the z-test (for two arms, chi-square = z²).
""")

code('''
by_arm = users.groupby("test_group").agg(n=("user_id", "size"), conv=("converted", "sum"))
r_ad = S.two_prop_test(by_arm.loc["ad", "conv"], by_arm.loc["ad", "n"],
                       by_arm.loc["psa", "conv"], by_arm.loc["psa", "n"], alpha=C.ALPHA)

# 1) identical to results.json
mismatch = [k for k, v in A["test"].items() if not same(getattr(r_ad, k), v)]
assert not mismatch, f"user-level recompute differs from results.json: {mismatch}"

# 2) chi-square (no continuity correction) agrees with the z-test
chi2_ad, p_chi2_ad, _, _ = sps.chi2_contingency(
    [[r_ad.conv_t, r_ad.n_t - r_ad.conv_t], [r_ad.conv_c, r_ad.n_c - r_ad.conv_c]], correction=False)
assert np.isclose(chi2_ad, r_ad.z ** 2) and np.isclose(p_chi2_ad, r_ad.p_value, rtol=1e-6, atol=0)
assert same(chi2_ad, A["chi2_test"]["chi2"])

ci_t, ci_c = S.wilson_ci(r_ad.conv_t, r_ad.n_t), S.wilson_ci(r_ad.conv_c, r_ad.n_c)
table(pd.DataFrame([
    {"arm": "PSA (control)", "users": r_ad.n_c, "conversions": r_ad.conv_c, "conversion rate": r_ad.rate_c,
     "95% CI (Wilson)": f"{pct(ci_c[0], 3)} to {pct(ci_c[1], 3)}"},
    {"arm": "Ad (treatment)", "users": r_ad.n_t, "conversions": r_ad.conv_t, "conversion rate": r_ad.rate_t,
     "95% CI (Wilson)": f"{pct(ci_t[0], 3)} to {pct(ci_t[1], 3)}"},
]), {"users": "{:,}", "conversions": "{:,}", "conversion rate": "{:.3%}"})
table(pd.DataFrame([{
    "absolute lift (pp)": r_ad.abs_lift * 100,
    "95% CI, Newcombe (pp)": f"{pp(r_ad.abs_ci_low, 3)} to {pp(r_ad.abs_ci_high, 3)}",
    "relative lift": r_ad.rel_lift,
    "95% CI, log risk ratio": f"{spct(r_ad.rel_ci_low, 1)} to {spct(r_ad.rel_ci_high, 1)}",
    "z": r_ad.z, "p (z-test)": sci(r_ad.p_value),
    "chi-square": chi2_ad, "p (chi-square)": sci(p_chi2_ad),
}]), {"absolute lift (pp)": "{:+.3f}", "relative lift": "{:+.1%}", "z": "{:.2f}", "chi-square": "{:.2f}"})
print("User-level recompute matches results.json; chi-square = z^2 and the p-values agree.")
''')

md("""
**Result.** Conversion is {{ad_rate_t}} with ads ({{conv_t}} of {{n_t}} users) vs {{ad_rate_c}} with PSA ({{conv_c}} of {{n_c}}): **+{{ad_lift}} pp, 95% CI {{ad_ci_lo}} to {{ad_ci_hi}} pp** (z = {{ad_z}}, p = {{ad_p_sci}}, i.e. p {{ad_p_txt}}; chi-square {{ad_chi2}}, same p). We reject H0. Read the CI, not the p-value: the true lift is plausibly anywhere from {{ad_ci_lo}} to {{ad_ci_hi}} pp, i.e. ≈{{inc_lo_r}} to {{inc_hi_r}} incremental conversions (A10).
""")

chart("ad_rates")

md("""
#### A7. Confidence interval three ways: Newcombe, Wald, bootstrap

- **Wald:** lift ± 1.96 × standard error. Simple, but it can under-cover when a rate is near 0 or an arm is small.
- **Newcombe (hybrid score):** built from each arm's Wilson score interval; stays close to 95% coverage with small rates and unbalanced arms. Project default.
- **Bootstrap (percentile):** resample each arm's users with replacement, recompute the lift, repeat {{n_boot}} times, read off the 2.5th and 97.5th percentiles. No formula for the standard error needed.

**The count-level bootstrap is an exact Bernoulli resample.** Resampling n users with replacement from an arm with k converters means n independent draws that each convert with probability k/n, so the resampled number of converters is exactly Binomial(n, k/n). `src.stats.bootstrap_two_prop` draws that count directly: the same distribution as resampling the 588K-row table, in milliseconds. The second table checks this against a (slower, smaller) user-level resample.
""")

code('''
wald_ad = S.wald_diff_ci(r_ad.conv_t, r_ad.n_t, r_ad.conv_c, r_ad.n_c, C.ALPHA)
boot_ad = caches["boot_ad"]
boot_ci_ad = S.percentile_ci(boot_ad["abs_lift"], C.ALPHA)
assert np.allclose(wald_ad, A["wald_ci"], atol=1e-6) and np.allclose(boot_ci_ad, A["bootstrap"]["abs_ci"], atol=1e-6)

ci_methods = pd.DataFrame([
    {"method": "Newcombe (hybrid score)", "low (pp)": r_ad.abs_ci_low, "high (pp)": r_ad.abs_ci_high},
    {"method": "Wald", "low (pp)": wald_ad[0], "high (pp)": wald_ad[1]},
    {"method": f"Bootstrap percentile ({len(boot_ad):,} draws)", "low (pp)": boot_ci_ad[0], "high (pp)": boot_ci_ad[1]},
])
ci_methods[["low (pp)", "high (pp)"]] *= 100
ci_methods["width (pp)"] = ci_methods["high (pp)"] - ci_methods["low (pp)"]
table(ci_methods, {"low (pp)": "{:.3f}", "high (pp)": "{:.3f}", "width (pp)": "{:.3f}"})

# User-level resample of the real table (400 draws; ~1,000x slower) vs the count-level draws used everywhere
rng = np.random.default_rng(C.SEED)
y_t = users.loc[users["test_group"] == "ad", "converted"].to_numpy()
y_c = users.loc[users["test_group"] == "psa", "converted"].to_numpy()
user_level = np.array([y_t[rng.integers(0, y_t.size, y_t.size)].mean() - y_c[rng.integers(0, y_c.size, y_c.size)].mean()
                       for _ in range(400)])
se_formula = np.sqrt(var_t + var_c)
resample_check = pd.DataFrame([
    {"method": "user-level resample (rows with replacement)", "draws": user_level.size,
     "mean lift (pp)": user_level.mean() * 100, "standard error (pp)": user_level.std(ddof=1) * 100},
    {"method": "count-level resample (binomial counts)", "draws": len(boot_ad),
     "mean lift (pp)": boot_ad["abs_lift"].mean() * 100, "standard error (pp)": boot_ad["abs_lift"].std(ddof=1) * 100},
    {"method": "analytic (unpooled) standard error", "draws": np.nan,
     "mean lift (pp)": r_ad.abs_lift * 100, "standard error (pp)": se_formula * 100},
])
table(resample_check, {"draws": "{:,.0f}", "mean lift (pp)": "{:.3f}", "standard error (pp)": "{:.4f}"})
# 400 draws estimate a standard error to within a few percent; 15% is a loose sanity bound
assert abs(user_level.std(ddof=1) / boot_ad["abs_lift"].std(ddof=1) - 1) < 0.15
''')

md("""
**Reading.** The three 95% intervals are practically identical: {{nw_lo}}–{{nw_hi}} pp (Newcombe), {{wald_lo}}–{{wald_hi}} pp (Wald) and {{boot_lo}}–{{boot_hi}} pp (bootstrap); {{boot_le0}} of {{n_boot}} bootstrap draws reach zero. With {{conv_c}} control conversions we are far from the small-sample regime where Wald breaks down, so the choice of method doesn't change the conclusion. The user-level and count-level resamples give the same spread, as the binomial argument says they must.
""")

chart("ad_bootstrap")

md("""
#### A8. Relative lift and its CI
""")

code('''
boot_rel_ci_ad = S.percentile_ci(boot_ad["rel_lift"], C.ALPHA)
assert np.allclose(boot_rel_ci_ad, A["bootstrap"]["rel_ci"], atol=1e-6)
table(pd.DataFrame([
    {"method": "log risk ratio (Katz)", "relative lift": r_ad.rel_lift, "low": r_ad.rel_ci_low, "high": r_ad.rel_ci_high},
    {"method": "bootstrap percentile", "relative lift": r_ad.rel_lift, "low": boot_rel_ci_ad[0], "high": boot_rel_ci_ad[1]},
]), {"relative lift": "{:+.1%}", "low": "{:+.1%}", "high": "{:+.1%}"})
''')

md("""
**Reading.** A {{ad_rel}} relative lift sounds precise; it isn't. The CI is {{rel_katz}} (log risk ratio) or {{rel_boot}} (bootstrap), and it is asymmetric because a ratio's uncertainty is symmetric on the log scale, not the percentage scale. The width comes from the denominator: the control rate rests on {{conv_c}} conversions. Use the absolute lift (pp) and incremental conversions for sizing, and always quote the relative lift with its range.
""")

md("""
#### A9. Power: what could this design detect?

Power is a property of the design, so we evaluate it at lifts we'd care about, never at the observed lift: "power at the observed effect" only restates the p-value. The reference point is the **smallest lift worth acting on**: a {{sesoi_rel}} relative lift ({{sesoi_abs}} pp at the PSA rate). It is a **placeholder assumption in `config.yaml`**; in practice the PM and Finance agree it before launch. At this test's scale it is ≈{{sesoi_conv_r}} conversions per {{n_t_k}}-user ad flight, ≈USD {{sesoi_value_k}} at the assumed USD {{value}} per conversion. The **MDE** (minimum detectable effect) is the smallest true lift the design detects {{power}} of the time at α = {{alpha}}. Like power, it describes the design and is never compared with an observed estimate.
""")

code('''
pw = A["power"]
sesoi = pw["smallest_lift_of_interest_rel"]        # smallest relative lift worth acting on: a placeholder in config.yaml
assert sesoi == C.SESOI_REL
p_c, n_total = r_ad.rate_c, r_ad.n_t + r_ad.n_c
half = n_total // 2
sesoi_conv = sesoi * p_c * r_ad.n_t                # what that lift means in conversions for a flight of this size
print(f"Smallest lift worth acting on: {sesoi:.0%} relative = {pp(sesoi * p_c)} pp = {sesoi_conv:,.0f} conversions per "
      f"{r_ad.n_t:,}-user ad flight (USD {sesoi_conv * C.VALUE_PER_CONVERSION:,.0f} at USD {C.VALUE_PER_CONVERSION:.0f})")

# 1) Power at a few true relative lifts: the actual 96/4 split vs a 50/50 split of the same users
pw_at = pw["power_at_relative_lift"]
pow_rows = []
for ref in pw_at.values():
    p_t = p_c * (1 + ref["rel"])
    now = S.power_at_lift(p_c, p_t, r_ad.n_t, r_ad.n_c, C.ALPHA)
    alt = S.power_at_lift(p_c, p_t, half, half, C.ALPHA)
    assert same(p_t - p_c, ref["abs"]) and same(now, ref["power_current_split"]) and same(alt, ref["power_5050_same_total"])
    pow_rows.append({"true relative lift": ref["rel"], "true lift (pp)": (p_t - p_c) * 100,
                     "power at 96 / 4 (actual)": now, "power at 50 / 50, same users": alt})
table(pd.DataFrame(pow_rows), {"true relative lift": "{:.0%}", "true lift (pp)": "{:.3f}",
                               "power at 96 / 4 (actual)": power_fmt, "power at 50 / 50, same users": power_fmt})

# 2) Minimum detectable lift by split, for the same total number of users
splits = [("50 / 50", half, half), ("80 / 20", int(n_total * 0.8), n_total - int(n_total * 0.8)),
          ("90 / 10", int(n_total * 0.9), n_total - int(n_total * 0.9)), ("96 / 4 (actual)", r_ad.n_t, r_ad.n_c)]
mde_rows = []
for name, n_t_, n_c_ in splits:
    m = S.mde(p_c, n_t_, n_c_, C.ALPHA, C.POWER)
    mde_rows.append({"split": name, "ad users": n_t_, "PSA users": n_c_, "mde_abs": m["mde_abs"],
                     "mde_rel": m["mde_rel"], "power_sesoi": S.power_at_lift(p_c, p_c * (1 + sesoi), n_t_, n_c_, C.ALPHA),
                     "forgone": n_c_ * r_ad.abs_lift})   # conversions the control arm doesn't get, at the observed lift
mde_tab = pd.DataFrame(mde_rows)
assert same(mde_tab.iloc[-1]["mde_abs"], pw["mde_current"]["mde_abs"])
assert same(mde_tab.iloc[0]["mde_abs"], pw["mde_if_5050_same_total"]["mde_abs"])
assert same(mde_tab.iloc[-1]["power_sesoi"], pw_at[str(sesoi)]["power_current_split"])
table(mde_tab.assign(mde_abs=mde_tab["mde_abs"] * 100).rename(columns={
    "mde_abs": f"MDE at {C.POWER:.0%} power (pp)", "mde_rel": "MDE (relative)",
    "power_sesoi": f"power for a {sesoi:.0%} lift", "forgone": "control-arm conversions forgone"}),
    {"ad users": "{:,}", "PSA users": "{:,}", f"MDE at {C.POWER:.0%} power (pp)": "{:.3f}", "MDE (relative)": "{:.1%}",
     f"power for a {sesoi:.0%} lift": power_fmt, "control-arm conversions forgone": "{:,.0f}"})

# 3) Users needed to detect the smallest lift worth acting on, by split
n10 = {s: S.required_total_n(p_c, sesoi * p_c, s, C.ALPHA, C.POWER) for s in (0.5, 0.8, C.INTENDED_AD_SHARE)}
assert all(n10[s] == pw["total_n_for_10pct_rel_lift"][str(s)] for s in n10)
# claims the text relies on: the actual design was underpowered for the smallest lift worth acting on; 50/50 was not
assert pw_at[str(sesoi)]["power_current_split"] < C.POWER < pw_at[str(sesoi)]["power_5050_same_total"]
table(pd.DataFrame([{"split": f"{s:.0%} / {1 - s:.0%}", f"users needed for a {sesoi:.0%} lift": n,
                     "vs 50 / 50": n / n10[0.5]} for s, n in n10.items()]),
      {f"users needed for a {sesoi:.0%} lift": "{:,}", "vs 50 / 50": "{:.1f}×"})
''')

md("""
**Reading.** At 96/4 the test had {{power}} power only for lifts ≥ {{mde_now}} pp ({{mde_now_rel}} relative); the same {{n_total}} users split 50/50 would detect {{mde_5050}} pp ({{mde_5050_rel}}). For the smallest lift worth acting on, power was **{{pow10_now}} at 96/4 vs {{pow10_5050}} at 50/50**; for a 5% lift, {{pow05_now}} vs {{pow05_5050}}. Had the true lift been 10%, this design would have missed it about half the time, so a "not significant" result from it would have meant little. This readout's CI excludes 0, so low power did not decide *this* conclusion, but it decides the next design. The MDE grows slowly with the treatment share and then steeply ({{mde_5050}} pp at 50/50, {{mde_8020}} at 80/20, {{mde_9010}} at 90/10, {{mde_now}} at 96/4), and 80/20 still has {{pow10_8020}} power for a {{sesoi_rel}} lift. Detecting a {{sesoi_rel}} lift at {{power}} power takes {{n10_50}} users at 50/50, {{n10_80}} at 80/20 and {{n10_96}} at 96/4 ({{n10_ratio}}× more). The price of a bigger control arm is conversions forgone during the test (at the observed lift ≈{{forgone_96}} at 96/4, {{forgone_80}} at 80/20 and {{forgone_50}} at 50/50 for a test of this size); 80/20 is the usual compromise.
""")

chart("ad_mde_split")
chart("ad_power_curve")

md("""
#### A10. Business translation

- **Incremental conversions** = lift × users who saw ads: conversions that would not have happened without the campaign.
- **Share of ad-arm conversions that are incremental** = lift ÷ ad-arm rate = 1 − 1 / risk ratio. The other conversions in the ad arm would have happened anyway (at the PSA rate).
- **Last-touch overstatement** = ad-arm conversions ÷ incremental conversions = 1 ÷ that share. Last-touch attribution credits *every* ad-arm conversion to the ads. Every ad-arm user saw at least one ad, so last-touch and any-touch attribution coincide here. Its CI follows from the risk-ratio CI.
- **Breakeven CPM** = the price per 1,000 impressions at which the value of the incremental conversions equals the media cost. The campaign pays back if the actual CPM is below it.
- **Holdout cost** = holdout share × users × lift: the conversions a permanent PSA holdout gives up, versus no holdout, so that incrementality stays measurable. This test's own PSA arm is already a holdout of the same kind.
- **Value per conversion is an assumption.** The data has no revenue, so USD {{value}} is illustrative (`config.yaml`). Breakeven CPM scales linearly with it: USD {{be_per_usd}} of CPM per USD 1 of value. The CIs below carry the sampling uncertainty of the lift only, not uncertainty about the value.
""")

code('''
bz = A["business"]
inc_now = {"point": r_ad.abs_lift * r_ad.n_t, "ci_low": r_ad.abs_ci_low * r_ad.n_t, "ci_high": r_ad.abs_ci_high * r_ad.n_t}
impr = bz["impressions_ad_group"]
assert impr == int(users.loc[users["test_group"] == "ad", "total_ads"].sum())
assert all(same(inc_now[k], bz["incremental_conversions"][k]) for k in inc_now)

share_incr_now = r_ad.abs_lift / r_ad.rate_t                                        # = 1 - 1/RR
share_incr_ci = [1 - 1 / (1 + r_ad.rel_ci_low), 1 - 1 / (1 + r_ad.rel_ci_high)]     # from the risk-ratio CI
overstate_now = r_ad.conv_t / inc_now["point"]                                      # last-touch credits every ad-arm conversion
overstate_ci = [1 / share_incr_ci[1], 1 / share_incr_ci[0]]
assert same(share_incr_now, bz["share_of_ad_conversions_incremental"])
assert np.allclose(share_incr_ci, bz["share_of_ad_conversions_incremental_ci"], atol=1e-6)
assert same(overstate_now, bz["last_touch_overstatement_x"])
assert np.allclose(overstate_ci, bz["last_touch_overstatement_ci"], atol=1e-6)
assert same(impr / inc_now["point"], bz["impressions_per_incremental_conversion"])
# claim the text relies on: every ad-arm user saw at least one ad, so last-touch = any-touch here
assert users.loc[users["test_group"] == "ad", "total_ads"].min() >= 1


def breakeven_cpm(value_usd):
    """USD per 1,000 impressions at which incremental value = media cost."""
    return {k: v * value_usd / impr * 1000 for k, v in inc_now.items()}


assert all(same(breakeven_cpm(bz["value_per_conversion_usd"])[k], bz["breakeven_cpm_usd"][k]) for k in inc_now)

hold = bz["always_on_holdout_cost"]
hold_users = n_total * C.HOLDOUT_SHARE
hold_conv = hold_users * r_ad.abs_lift                                              # forgone per flight vs no holdout
asrun_conv = r_ad.n_c * r_ad.abs_lift                                               # what this test's PSA arm forgoes
assert hold["share"] == C.HOLDOUT_SHARE and same(hold_users, hold["users_per_588k_flight"])
assert same(hold_conv, hold["conversions_forgone"])
assert same(hold_conv * bz["value_per_conversion_usd"], hold["value_forgone_usd"])
assert same(r_ad.n_c / n_total, hold["as_run_control_share"]) and same(asrun_conv, hold["as_run_control_conversions_forgone"])
assert same(hold_conv - asrun_conv, hold["extra_conversions_vs_as_run"])

table(pd.DataFrame([
    {"metric": "Incremental conversions (lift × ad-arm users)", "estimate": num(inc_now["point"]),
     "95% CI": f"{num(inc_now['ci_low'])} to {num(inc_now['ci_high'])}"},
    {"metric": "Share of ad-arm conversions that are incremental (1 − 1/RR)", "estimate": pct(share_incr_now, 0),
     "95% CI": f"{pct(share_incr_ci[0], 0)} to {pct(share_incr_ci[1], 0)}"},
    {"metric": f"Last-touch (any-touch) overstatement ({num(r_ad.conv_t)} ad-arm conversions ÷ incremental)",
     "estimate": f"{overstate_now:.1f}×", "95% CI": f"{overstate_ci[0]:.1f}× to {overstate_ci[1]:.1f}×"},
    {"metric": "Ad-arm impressions", "estimate": num(impr), "95% CI": ""},
    {"metric": "Impressions per incremental conversion", "estimate": num(impr / inc_now["point"]), "95% CI": ""},
    {"metric": f"Always-on {C.HOLDOUT_SHARE:.0%} PSA holdout: users per {n_total / 1e3:.0f}K-user flight",
     "estimate": num(hold_users), "95% CI": ""},
    {"metric": "... conversions forgone per flight vs no holdout, at the observed lift", "estimate": num(hold_conv),
     "95% CI": ""},
    {"metric": f"This test's {r_ad.n_c / n_total:.0%} PSA arm: conversions already forgone", "estimate": num(asrun_conv),
     "95% CI": ""},
    {"metric": f"Step from {r_ad.n_c / n_total:.0%} to {C.HOLDOUT_SHARE:.0%}: extra conversions forgone per flight",
     "estimate": num(hold_conv - asrun_conv), "95% CI": ""},
]))

value_now = bz["value_per_conversion_usd"]
sens = pd.DataFrame([{"value per conversion (USD, assumption)": v, "breakeven CPM (USD)": breakeven_cpm(v)["point"],
                      "95% CI low": breakeven_cpm(v)["ci_low"], "95% CI high": breakeven_cpm(v)["ci_high"],
                      "incremental value (USD K)": inc_now["point"] * v / 1e3,
                      "holdout cost per flight (USD K)": hold_conv * v / 1e3}
                     for v in (value_now / 2, value_now, value_now * 2)])
table(sens, {"value per conversion (USD, assumption)": "{:.0f}", "breakeven CPM (USD)": "{:.2f}",
             "95% CI low": "{:.2f}", "95% CI high": "{:.2f}", "incremental value (USD K)": "{:,.0f}",
             "holdout cost per flight (USD K)": "{:,.1f}"})
''')

md("""
**Reading.** ≈{{inc_r}} incremental conversions (95% CI {{inc_lo_r}}–{{inc_hi_r}}) from {{impr_m}}M ad-arm impressions, one per ≈{{impr_per_inc}} impressions. Only {{share_incr}} of the ad arm's {{conv_t}} conversions are incremental (CI {{share_incr_lo}}–{{share_incr_hi}}): the rest would have happened at the PSA rate anyway. Last-touch (any-touch) attribution would credit every ad-arm conversion to the ads and overstate the campaign **{{overstate}}× (95% CI {{overstate_lo}}–{{overstate_hi}}×)**. At the illustrative USD {{value}} per conversion that is ≈USD {{inc_value_k}} of incremental value (CI USD {{inc_value_lo_k}}–{{inc_value_hi_k}}), and the campaign breaks even at a **CPM of USD {{be_cpm}} (CI USD {{be_lo}}–{{be_hi}})**. A {{holdout_share}} always-on PSA holdout to keep measuring this forgoes ≈{{holdout_conv}} conversions per {{n_total_k}}-user flight (≈{{holdout_users_k}} users; ≈USD {{holdout_value_k}} at USD {{value}}) versus no holdout. This test's {{asrun_share}} PSA arm already forgoes ≈{{asrun_conv}}, so the step from {{asrun_share}} to {{holdout_share}} costs ≈{{holdout_extra}} more: a small price for measuring incrementality instead of trusting last-touch. The headline business number is the incremental conversion count; the dollar figures move one-for-one with the assumed value.
""")

chart("ad_breakeven")

md("""
#### A11. Heterogeneity: does the lift differ by day, hour or exposure?

Two questions that often get mixed up:

1. **Does the lift *differ* across segments?** This is the heterogeneity question behind "should we move budget to Tuesdays?".
   - **Step 1, interaction test (odds scale):** one likelihood-ratio test (LRT) per dimension, `converted ~ arm × segment` against `converted ~ arm + segment` (binomial GLM). It asks whether the ad-vs-PSA *odds ratio* differs across segments.
   - **Step 2, segment-vs-rest contrasts (percentage-point scale):** each segment's lift against the lift in all *other* segments, Holm-corrected across the dimension's segments. The point estimate is the raw difference (segment lift − lift in the other segments). Its 95% CI and p-value use Agresti–Caffo adjusted rates (+1 conversion and +1 non-conversion per arm and group), so a cell with zero control conversions can't produce a zero variance and a fake "significant" difference. In sparse cells that CI is therefore not centred on the point estimate.
   - Because the two steps use different scales, they can disagree: a segment with a tiny control rate can have a very large odds ratio but an ordinary difference in pp (Night, below).
2. **Is there a lift *inside* segment X?** One test of lift ≠ 0 per segment. Because the overall lift is real, these tests mostly measure how many users a segment has (its power), not whether it responds differently, so they are descriptive only.

Bonferroni (p × {{n_dims}}) covers the three original interaction tests (peak day, peak hour, exposure bucket). The daypart cut and the Night-exclusion check were added later as descriptive diagnostics and are not covered by this adjustment. All of these fields are recorded after assignment (A3, A5): even a real interaction describes *which users* respond more, not a lever we control. Everything in A11–A13 is exploratory.
""")

code('''
het = A["heterogeneity"]
DIMS = {"most_ads_day": ("peak ad day", C.DAY_ORDER), "most_ads_hour": ("peak ad hour", list(range(24))),
        "daypart": ("daypart of the peak hour", C.DAYPART_ORDER), "exposure_bucket": ("total ads seen", C.EXPOSURE_LABELS)}
METHODS = {"none": "unadjusted", "bonferroni": "Bonferroni", "holm": "Holm", "fdr_bh": "BH"}
seg = {dim: {m: S.segment_lifts(cells, dim, "ad", "psa", alpha=C.ALPHA, method=m, order=order) for m in METHODS}
       for dim, (_, order) in DIMS.items()}

# Step 1: one interaction test per dimension (+ the hour-based ones without the night hours 0-5)
no_night = cells[cells["daypart"] != C.DAYPART_ORDER[0]]
lrt_rows = []
for dim, (label, order) in DIMS.items():
    lrt, ref = S.interaction_lrt(cells, dim), het[dim]["lrt"]
    assert same(lrt["lr_stat"], ref["lr_stat"]) and same(lrt["p_value"], ref["p_value"])
    assert lrt["df"] == ref["df"] and lrt["cells_with_zero_conversions"] == ref["cells_with_zero_conversions"]
    row = {"dimension": label, "segments": len(order), "LR statistic": lrt["lr_stat"], "df": lrt["df"],
           "interaction p": lrt["p_value"],
           "p × 3 dimensions (Bonferroni)": np.nan if dim == "daypart" else min(1.0, 3 * lrt["p_value"]),
           "arm × segment cells with 0 conversions": lrt["cells_with_zero_conversions"],
           "p without night hours (0-5)": np.nan}
    if "lrt_excluding_night" in het[dim]:
        ex_n = S.interaction_lrt(no_night, dim)
        assert same(ex_n["p_value"], het[dim]["lrt_excluding_night"]["p_value"])
        row["p without night hours (0-5)"] = ex_n["p_value"]
    lrt_rows.append(row)
assert het["n_dimensions_explored"] == 3
assert same(lrt_rows[0]["p × 3 dimensions (Bonferroni)"], het["most_ads_day"]["lrt_p_bonferroni_3_dims"])
table(pd.DataFrame(lrt_rows), {"LR statistic": "{:.1f}", "interaction p": fmt_p, "p × 3 dimensions (Bonferroni)": fmt_p,
                               "p without night hours (0-5)": fmt_p})
print("Bonferroni covers the three original interaction tests; the later daypart and Night-exclusion diagnostics are not covered.")
''')

md("""
**Reading.** Peak day: {{lrt_day_p}}, {{lrt_day_bonf}} after a Bonferroni allowance for the {{n_dims}} dimensions explored: modest evidence that the lift differs by day. Peak hour: {{lrt_hour_p}}, no evidence; {{hour_zero_cells}} hour × arm cells have zero conversions, and without the night hours (0–5) p = {{lrt_hour_nonight}}. Daypart: {{lrt_dp_p}}, but {{lrt_dp_nonight}} without the night block (see below). Exposure: {{lrt_expo_p}}, strong evidence, but exposure tracks how active a user is (A13).

Step 2 asks *which* segments differ. With n contrasts per dimension, about n × α of them would come out "significant" by chance if no segment differed, hence the corrections.
""")

code('''
count_rows = []
for dim, (label, order) in DIMS.items():
    h = het[dim]
    differs = {m: int(seg[dim][m]["differs_adj"].sum()) for m in METHODS}
    lift_ne0 = {m: int(seg[dim][m]["significant_adj"].sum()) for m in METHODS}
    holm_tab = seg[dim]["holm"]
    differing = holm_tab.loc[holm_tab["differs_adj"], dim].astype(str).tolist()
    assert differs == h["differs_from_rest"] and lift_ne0 == h["lift_positive"]
    assert differing == h["segments_differing_holm"] and len(order) == h["n_segments"]
    # the contrast's point estimate is the raw difference: segment lift minus the lift in all other segments;
    # its CI is centred on the Agresti-Caffo difference (diff_vs_rest_ac), shown as "CI centre (adjusted)"
    assert np.allclose(holm_tab["diff_vs_rest"], holm_tab["abs_lift"] - holm_tab["lift_rest"], rtol=0, atol=1e-12)
    assert np.allclose((holm_tab["diff_vs_rest_ci_low"] + holm_tab["diff_vs_rest_ci_high"]) / 2, holm_tab["diff_vs_rest_ac"],
                       rtol=0, atol=1e-12)
    count_rows.append({"dimension": label, "segments": len(order),
                       **{f"differ from rest, {name}": differs[m] for m, name in METHODS.items()},
                       "expected by chance if none differed (n × α)": len(order) * C.ALPHA,
                       "segments that differ (Holm)": ", ".join(differing) or "none",
                       "lift ≠ 0 after Holm (descriptive)": lift_ne0["holm"]})
table(pd.DataFrame(count_rows), {"expected by chance if none differed (n × α)": "{:.2f}"})


def contrasts(dim: str) -> pd.DataFrame:
    """Each segment's own lift next to its contrast with all other segments (Holm across the dimension)."""
    d = seg[dim]["holm"]
    return pd.DataFrame({
        DIMS[dim][0]: d[dim].astype(str).to_numpy(), "ad users": d["n_t"].to_numpy(), "PSA users": d["n_c"].to_numpy(),
        "PSA conversions": d["conv_c"].to_numpy(), "PSA rate": d["rate_c"].to_numpy(),
        "lift (pp)": d["abs_lift"].to_numpy() * 100,
        "lift 95% CI (pp)": [ci_txt(lo, hi) for lo, hi in zip(d["abs_ci_low"], d["abs_ci_high"])],
        "lift in other segments (pp)": d["lift_rest"].to_numpy() * 100,
        "difference vs rest (pp, raw)": d["diff_vs_rest"].to_numpy() * 100,
        "CI centre (adjusted)": d["diff_vs_rest_ac"].to_numpy() * 100,
        "difference 95% CI (pp, Agresti–Caffo)": [ci_txt(lo, hi) for lo, hi in
                                                  zip(d["diff_vs_rest_ci_low"], d["diff_vs_rest_ci_high"])],
        "p vs rest": d["p_vs_rest"].to_numpy(), "p vs rest, Holm": d["p_vs_rest_adj"].to_numpy(),
    })


C_FMT = {"ad users": "{:,}", "PSA users": "{:,}", "PSA conversions": "{:,}", "PSA rate": "{:.2%}", "lift (pp)": "{:+.2f}",
         "lift in other segments (pp)": "{:+.2f}", "difference vs rest (pp, raw)": "{:+.2f}",
         "CI centre (adjusted)": "{:+.2f}", "p vs rest": fmt_p, "p vs rest, Holm": fmt_p}
day_c = seg["most_ads_day"]["holm"].assign(most_ads_day=lambda d: d["most_ads_day"].astype(str)).set_index("most_ads_day")
table(contrasts("most_ads_day"), C_FMT, bold_below=["p vs rest, Holm"])
# claims the text relies on: Tuesday above and Thursday below the other days, both surviving Holm; no hour or daypart
# differs; Tuesday's PSA rate is one of the two lowest of the week
assert day_c.loc["Tuesday", "diff_vs_rest"] > 0 > day_c.loc["Thursday", "diff_vs_rest"]
assert het["most_ads_day"]["segments_differing_holm"] == ["Tuesday", "Thursday"]
assert het["most_ads_hour"]["differs_from_rest"]["none"] == 0 and het["daypart"]["differs_from_rest"]["holm"] == 0
assert day_c["rate_c"].rank().loc["Tuesday"] <= 2
print("Difference vs rest: the point estimate is the raw difference (lift minus the lift in the other segments); its CI "
      "and p use Agresti-Caffo adjusted rates, so in sparse cells the CI is not centred on the point. CIs are per "
      "segment, not simultaneous. 'CI centre (adjusted)' is the Agresti-Caffo difference the CI and p are about.")
''')

md("""
**Reading.** Only peak day and exposure have segments whose lift differs from the rest after Holm (day: {{day_diff_segs}}; exposure: {{expo_diff_n}} of 8 buckets). No hour differs from the other hours, even before correction ({{hour_diff_raw}} of 24 contrasts, against ≈{{efp_hour}} expected by chance alone), and no daypart does either. The last column counts segments whose lift is ≠ 0 after Holm: it shows where the data are rich enough to confirm the overall lift, not where the lift is different.

**Peak day.** Lift ranges from {{day_min}} pp ({{day_min_seg}}) to {{day_max}} pp ({{day_max_seg}}). Tuesday-peak users' lift is {{tue_vs_rest}} pp vs the other days' (95% CI {{tue_vs_rest_lo}} to {{tue_vs_rest_hi}}; Holm p = {{tue_p_holm}}) and Thursday-peak users' is {{thu_vs_rest}} pp (CI {{thu_vs_rest_lo}} to {{thu_vs_rest_hi}}; Holm p = {{thu_p_holm}}), so the day pattern is probably not pure noise. Part of Tuesday's lift is a low control rate: its PSA arm has {{tue_n_c}} users and {{tue_conv_c}} conversions ({{tue_rate_c}}, one of the lowest control rates of the week). And "peak day" is a user habit recorded after assignment (the weekday on which a *user* happened to see the most ads), not a slot we buy. Moving budget to Tuesdays is a different intervention; if timing matters, the way to learn its effect is a pre-registered test that randomizes the delivery schedule (R3).
""")

chart("het_day")

code('''
hour_tab = seg["most_ads_hour"]["holm"]
hour_zero = hour_tab.loc[hour_tab["conv_c"] == 0, "most_ads_hour"].astype(int).tolist()
assert len(hour_zero) == het["most_ads_hour"]["segments_with_zero_control_conversions"]
assert hour_tab["n_c"].min() == het["most_ads_hour"]["min_control_users"]
# claims the text relies on: the zero-control hours are mostly night (0-5), and hour 6 belongs to Morning (6-11)
assert sum(C.DAYPART_OF_HOUR[h] == C.DAYPART_ORDER[0] for h in hour_zero) > len(hour_zero) / 2
assert 6 in hour_zero and C.DAYPART_OF_HOUR[6] == C.DAYPART_ORDER[1]
print(f"PSA users per peak hour: {hour_tab['n_c'].min():,} to {hour_tab['n_c'].max():,}; "
      f"hours with zero PSA conversions: {hour_ranges(hour_zero)}")
print("The five hours whose lift looks most different from the other hours':")
table(contrasts("most_ads_hour").sort_values("p vs rest").head(5), C_FMT, bold_below=["p vs rest, Holm"])
''')

md("""
**Peak hour.** No evidence the lift differs by hour ({{lrt_hour_p}}), and no hour's lift differs from the other hours' even before correction (smallest unadjusted p = {{hour_min_p_rest}}). The hourly estimates are noisy: PSA users per hour range from {{min_c_hour}} to {{max_c_hour}}, and {{hour_zero_n}} hours ({{hour_zero_list}}, mostly night) have zero control conversions; hour 6 belongs to Morning (6–11).
""")

chart("het_hour")

code('''
night = het["daypart"]["night_counts"]
NIGHT = C.DAYPART_ORDER[0]
night_now = cells[cells["daypart"] == NIGHT].groupby("test_group")[["users", "conversions"]].sum()
assert all(int(night_now.loc[g, k]) == night[g][k] for g in ("ad", "psa") for k in ("users", "conversions"))
dp_c = seg["daypart"]["holm"].assign(daypart=lambda d: d["daypart"].astype(str)).set_index("daypart")
# Odds ratio ad vs PSA per daypart: the scale the interaction test works on
dp_or = (dp_c["conv_t"] / (dp_c["n_t"] - dp_c["conv_t"])) / (dp_c["conv_c"] / (dp_c["n_c"] - dp_c["conv_c"]))
# claims the text relies on: Night's odds ratio stands out, its pp contrast does not survive Holm, and its
# Agresti-Caffo interval is not centred on the raw difference
assert dp_or[NIGHT] > 2 * dp_or.drop(NIGHT).max() and not dp_c.loc[NIGHT, "differs_adj"]
assert abs((dp_c.loc[NIGHT, "diff_vs_rest_ci_low"] + dp_c.loc[NIGHT, "diff_vs_rest_ci_high"]) / 2
           - dp_c.loc[NIGHT, "diff_vs_rest"]) > 0.0005
table(contrasts("daypart").assign(**{"odds ratio, ad vs PSA": dp_or.to_numpy()}),
      {**C_FMT, "odds ratio, ad vs PSA": "{:.1f}"}, bold_below=["p vs rest, Holm"])
''')

md("""
**Daypart.** The interaction test gives {{lrt_dp_p}}, but it is driven by Night (0–5), where the control arm has {{night_conv_c}} conversion among {{night_n_c}} users (ad arm: {{night_conv_t}} among {{night_n_t}}). Without Night, p = {{lrt_dp_nonight}}. On the odds scale that single control conversion makes Night stand out (odds ratio ≈{{night_or}} vs {{other_or_lo}}–{{other_or_hi}} in the other dayparts). On the percentage-point scale Night's lift is {{night_vs_rest}} pp vs the other dayparts' (95% CI {{night_vs_rest_lo}} to {{night_vs_rest_hi}}; Holm p = {{night_p_holm}}): not different after Holm. That interval is not centred on {{night_vs_rest}} pp because the Agresti–Caffo adjustment adds one conversion to a control cell that has only one, which doubles its rate. There is no reliable time-of-day pattern to buy into.
""")

chart("het_daypart")

md("""
#### A12. Sensitivity: standardized lift

The arms differ slightly in all of these fields (A5). Could that imbalance have produced the headline lift (a Simpson's-paradox check)? Standardize the lift over each field's strata (Mantel–Haenszel weighted risk difference) and compare it with the crude lift. This is a sensitivity analysis, not an adjusted estimate: the fields are post-assignment, so the crude lift stays the estimate.
""")

code('''
def mh_risk_diff(dim: str) -> float:
    """Mantel-Haenszel weighted risk difference, stratified on `dim` (weights n_t * n_c / (n_t + n_c))."""
    g = cells.groupby([dim, "test_group"], observed=True)[["users", "conversions"]].sum().unstack("test_group")
    n1, n0 = g[("users", "ad")], g[("users", "psa")]
    w = n1 * n0 / (n1 + n0)
    return float((w * (g[("conversions", "ad")] / n1 - g[("conversions", "psa")] / n0)).sum() / w.sum())


sens_rows = [{"standardized over": "nothing (crude lift)", "lift (pp)": r_ad.abs_lift * 100}]
for dim, (label, _) in DIMS.items():
    mh = mh_risk_diff(dim)
    assert same(mh, het[dim]["sensitivity_stratified"]["mh_risk_diff"])
    sens_rows.append({"standardized over": label, "lift (pp)": mh * 100})
sens_tab = pd.DataFrame(sens_rows)
sens_tab["difference vs crude (pp)"] = sens_tab["lift (pp)"] - r_ad.abs_lift * 100
table(sens_tab, {"lift (pp)": "{:.3f}", "difference vs crude (pp)": "{:+.3f}"})
''')

md("""
**Reading.** Standardized over peak day, peak hour, daypart or exposure bucket, the lift is {{mh_min}}–{{mh_max}} pp against {{ad_lift}} pp crude: no Simpson reversal, and the small imbalances in these fields don't drive the result.
""")

md("""
#### A13. Where the lift comes from: exposure, and what it means for "double the budget?"
""")

code('''
ex = seg["exposure_bucket"]["holm"].assign(exposure_bucket=lambda d: d["exposure_bucket"].astype(str)).set_index("exposure_bucket")
ex["incremental"] = ex["abs_lift"] * ex["n_t"]       # bucket-by-bucket: each bucket against its own PSA rate
LIGHT, HEAVY = ["1-5", "6-10", "11-20"], ["36-50", "51-100", "101-200"]
con = het["exposure_bucket"]["concentration"]
con_now = {"share_users_le_20_ads": (users["total_ads"] <= 20).mean(),
           "share_ad_users_le_20_ads": (users.loc[users["test_group"] == "ad", "total_ads"] <= 20).mean(),
           "share_ad_users_36_200": ex.loc[HEAVY, "n_t"].sum() / ex["n_t"].sum(),
           "incremental_conversions_bucketwise_total": ex["incremental"].sum(),
           "incremental_conversions_36_200": ex.loc[HEAVY, "incremental"].sum(),
           "share_incremental_conversions_36_200": ex.loc[HEAVY, "incremental"].sum() / ex["incremental"].sum(),
           "control_rate_lowest_bucket": ex["rate_c"].iloc[0], "control_rate_highest_bucket": ex["rate_c"].iloc[-1],
           "top_bucket_control_users": ex["n_c"].iloc[-1]}
assert all(same(v, con[k]) for k, v in con_now.items())
assert all(same(ex.loc[b, "incremental"], v) for b, v in con["incremental_conversions_by_bucket"].items())
assert np.allclose([ex["abs_ci_low"].iloc[-1] * 100, ex["abs_ci_high"].iloc[-1] * 100], con["top_bucket_ci_pp"], atol=1e-5)
b2135 = con["bucket_21_35"]
assert all(same(ex.loc["21-35", k], b2135[k]) for k in ("abs_lift", "abs_ci_low", "abs_ci_high"))
assert same(ex.loc["21-35", "n_t"] / ex["n_t"].sum(), b2135["share_ad_users"])

# Users with <= 20 ads, pooled: their lift, and what this design could have detected among them
le20_n = users[users["total_ads"] <= 20].groupby("test_group")["converted"].agg(["sum", "size"])
le20 = S.two_prop_test(le20_n.loc["ad", "sum"], le20_n.loc["ad", "size"], le20_n.loc["psa", "sum"], le20_n.loc["psa", "size"],
                       alpha=C.ALPHA)
le20_mde = S.mde(le20.rate_c, le20.n_t, le20.n_c, C.ALPHA, C.POWER)
le20_ref = con["le_20_ads_pooled"]
assert not [k for k in le20.to_dict() if not same(getattr(le20, k), le20_ref[k])]
assert same(le20_mde["mde_abs"], le20_ref["mde_abs"]) and same(le20_mde["mde_rel"], le20_ref["mde_rel"])

table(pd.DataFrame({
    "total ads seen": ex.index, "ad users": ex["n_t"].to_numpy(), "PSA users": ex["n_c"].to_numpy(),
    "share of ad users": (ex["n_t"] / ex["n_t"].sum()).to_numpy(),
    "PSA rate": ex["rate_c"].to_numpy(), "ad rate": ex["rate_t"].to_numpy(), "lift (pp)": ex["abs_lift"].to_numpy() * 100,
    "lift 95% CI (pp)": [ci_txt(lo, hi) for lo, hi in zip(ex["abs_ci_low"], ex["abs_ci_high"])],
    "differs from rest (Holm)": np.where(ex["differs_adj"], "yes", "no"),
    "incremental conversions (bucket by bucket)": ex["incremental"].to_numpy(),
    "share of the bucket-by-bucket total": (ex["incremental"] / ex["incremental"].sum()).to_numpy(),
}), {"ad users": "{:,}", "PSA users": "{:,}", "share of ad users": "{:.1%}", "PSA rate": "{:.2%}", "ad rate": "{:.2%}",
     "lift (pp)": "{:+.2f}", "incremental conversions (bucket by bucket)": "{:,.0f}",
     "share of the bucket-by-bucket total": "{:.1%}"})
table(pd.DataFrame([
    {"group": "≤ 20 ads, pooled", "share of ad users": con["share_ad_users_le_20_ads"], "lift (pp)": le20.abs_lift * 100,
     "lift 95% CI (pp)": ci_txt(le20.abs_ci_low, le20.abs_ci_high), "PSA rate": le20.rate_c,
     f"MDE at {C.POWER:.0%} power (pp)": le20_mde["mde_abs"] * 100, "MDE (relative)": le20_mde["mde_rel"]},
    {"group": "21-35 ads", "share of ad users": b2135["share_ad_users"], "lift (pp)": ex.loc["21-35", "abs_lift"] * 100,
     "lift 95% CI (pp)": ci_txt(ex.loc["21-35", "abs_ci_low"], ex.loc["21-35", "abs_ci_high"]),
     "PSA rate": ex.loc["21-35", "rate_c"], f"MDE at {C.POWER:.0%} power (pp)": np.nan, "MDE (relative)": np.nan},
]), {"share of ad users": "{:.1%}", "lift (pp)": "{:+.2f}", "PSA rate": "{:.2%}", f"MDE at {C.POWER:.0%} power (pp)": "{:.2f}",
     "MDE (relative)": "{:+.0%}"})
# claims the text relies on: no detectable lift up to 20 ads (bucket by bucket even unadjusted, and pooled); 21-35 is
# inconclusive; a lift in every bucket from 36 to 200 ads; buckets 1-5 and 6-10 are slightly negative
assert not seg["exposure_bucket"]["none"].set_index(ex.index)["significant_adj"].loc[LIGHT].any()
assert le20.abs_ci_low < 0 < le20.abs_ci_high and ex.loc["21-35", "abs_ci_low"] < 0 < ex.loc["21-35", "abs_ci_high"]
assert ex.loc[HEAVY, "significant_adj"].all() and (ex.loc[["1-5", "6-10"], "incremental"] < 0).all()
print(f"Incremental conversions summed bucket by bucket: {ex['incremental'].sum():,.0f} (each bucket against its own "
      f"PSA rate; the headline estimate is {r_ad.abs_lift * r_ad.n_t:,.0f}). Shares are of the bucket-by-bucket total.")
''')

md("""
**Reading.** Up to 20 ads the bucket lifts are {{low_lift_min}} to {{low_lift_max}} pp, none distinguishable from zero even before correction. Pooled, the {{share_le20}} of users who saw ≤ 20 ads show no lift we could measure: {{le20_lift}} pp (95% CI {{le20_lo}} to {{le20_hi}}). The next {{b2135_share}} of ad users (21–35 ads) are inconclusive: {{b2135_lift}} pp (95% CI {{b2135_lo}} to {{b2135_hi}}). The three buckets from 36 to 200 ads (lifts {{lift_36_50}}–{{lift_101_200}} pp) hold {{share_users_heavy}} of ad users but {{share_inc_heavy}} of the *bucket-by-bucket* incremental conversions ({{inc_heavy}} of {{inc_bucketwise}}). Each bucket is compared with its own PSA rate, so that total differs from the headline {{inc}}, and buckets 1–5 and 6–10 are slightly negative ({{inc_b15}} and {{inc_b610}}). The PSA columns show the confounder: PSA conversion rises from {{psa_rate_low}} at 1–5 ads to {{psa_rate_high}} at 200+, without a single campaign ad, so users who see more ads are simply more active.
""")

chart("het_exposure")
chart("het_exposure_forest")

md("""
**Why this is "the lift lives in heavy users", not a frequency curve.** Exposure isn't randomized: users who browse more see more ads *and* convert more anyway. Comparing ad vs PSA within a bucket holds the number of ad slots fixed, which helps, but bucket membership is post-assignment (A5), and heavy users differ from light users in ways this dataset can't show. So the data can't separate "more ads per user cause more lift" from "active users respond to ads", and the 200+ bucket is too small to say anything (CI {{top_ci_lo}} to {{top_ci_hi}} pp from {{n_c_200}} PSA users).

**What it means for "double the budget?".** The test varied *which* ad users saw, not *how many*, so it can't say what an extra dollar buys: more impressions for heavy users, or new reach among light users who show no lift we could measure today. The way to answer the PM's question is a randomized test (R2): a user-level test where one arm gets up to 2× today's impressions per user (the closest stand-in for 2× budget) or a frequency cap, 50/50 or 80/20, with users tiered by activity measured *before* the test, measuring **incremental conversions per extra USD 1K spent**. A true budget test needs a geo split.
""")

md("""
#### A14. Novelty effect, duration and multiple comparisons

- **Novelty effect.** New ads often get a burst of attention that fades (ad fatigue, wear-out). Without timestamps we can't tell whether +{{ad_lift}} pp is a steady state or an early peak, so the incremental conversions are for *this flight*, not a run-rate. An always-on PSA holdout (R1) would show whether lift decays.
- **Duration.** Flight dates aren't in the data. All seven weekdays appear, but we can't confirm the test covered whole weeks, or that it wasn't stopped early after a peek. Next test: a fixed duration of at least two full weeks, set up front.
- **Multiple comparisons.** One primary comparison (conversion rate, analysed before any segment) carries the decision. The three original interaction tests (peak day, peak hour and exposure bucket) use a Bonferroni adjustment, and the {{n_contrasts}} segment-vs-rest contrasts in A11–A13 use Holm within each dimension. The later daypart and Night-exclusion checks are descriptive and not covered by the Bonferroni adjustment; anything interesting there gets its own pre-registered test.
- **Interference.** PSA users may still see the brand's ads in other channels, so the lift is "this campaign vs a public-service ad in the same slots". If anything, that understates the effect of advertising vs no advertising at all.
""")

# --------------------------------------------------------------------------- Results B
md("""
### Part B: Gate experiment (Cookie Cats)

#### B1. Setup

Cookie Cats is the company's mobile game, a different product from the app the ads ran in; this decision belongs to the Game PM. Players were randomized at install to the first progression gate at level 30 (`gate_30`, control) or level 40 (`gate_40`, treatment). A gate makes the player wait, or pay, before progressing.

- **H0:** D7 retention is the same in both versions. **H1:** it differs (two-sided, α = {{alpha}}).
- **Primary metric: D7 retention** = share of players who played on day 7 after install (classic day-7 retention, not "day 7 or later"). **Guardrails:** D1 retention (played on day 1 after install), and game rounds in the first 14 days (engagement shouldn't fall).
- Unit: player. All installs form one install cohort (no install dates). {{c_rows_clean}} players after removing one logging error; the SRM check uses all {{c_rows_raw}} assignments, because assignment happens before any cleaning.
""")

code('''
# Data note: players with zero rounds who are still flagged as retained
zero = players[players["sum_gamerounds"] == 0]
zero_d1, zero_d7 = int(zero["retention_1"].sum()), int(zero["retention_7"].sum())
assert len(zero) == res["data_quality"]["cookie"]["zero_round_players"]
print(f"{len(zero):,} players with 0 rounds: {zero_d1} flagged D1-retained, {zero_d7} D7-retained "
      f"({zero_d1 / len(players):.2%} of all players)")
''')

md("""
**Data note.** {{zero_d1}} of the {{zero_n}} players with zero rounds are flagged as D1-retained ({{zero_d7}} as D7-retained), so the flags mean "came back to the game", not "played a round". That is about {{zero_share}} of players; no conclusion depends on it.

#### B2. SRM check
""")

code('''
raw_n = G["players_raw"]
srm_gate = S.srm_check(raw_n["gate_40"], raw_n["gate_30"], C.INTENDED_GATE40_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)
assert srm_gate["status"] == G["srm"]["status"] and same(srm_gate["p_value"], G["srm"]["p_value"])
assert raw_n["gate_40"] - raw_n["gate_30"] == G["excess_players_raw"]

# The raw assignment log = the cleaned player table + the one dropped logging error
dropped = pd.DataFrame(res["data_quality"]["cookie"]["outliers_dropped"])
log = pd.concat([players[["version", "sum_gamerounds"]], dropped[["version", "sum_gamerounds"]]], ignore_index=True)
assert log["version"].value_counts().to_dict() == raw_n

n40, n30 = G["players"]["gate_40"], G["players"]["gate_30"]
srm_gate_clean = S.srm_check(n40, n30, C.INTENDED_GATE40_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)
table(pd.DataFrame([
    {"population": f"assignment log ({len(log):,} players): the check", **srm_gate},
    {"population": f"after removing the 1 logging error ({n40 + n30:,} players): reference only", **srm_gate_clean},
])[["population", "n_c", "n_t", "observed_share_t", "chi2", "p_value", "status"]].rename(columns={
    "n_c": "gate_30", "n_t": "gate_40", "observed_share_t": "gate_40 share", "p_value": "p"}),
    {"gate_30": "{:,}", "gate_40": "{:,}", "gate_40 share": "{:.2%}", "chi2": "{:.2f}", "p": fmt_p})
print(f"Rule: FAIL if p < {C.SRM_FAIL_P:g} (Kohavi et al. convention), WARNING if p < {C.SRM_WARN_P:g} "
      f"(project convention), otherwise PASS")
''')

md("""
**Reading.** The assignment log has {{g_n40_raw}} gate_40 and {{g_n30_raw}} gate_30 players: gate_40 has {{gate_excess_raw}} more in the raw log, {{gate_share}} vs an intended 50%. The chi-square p-value is **{{gate_srm_p}}**: below the 0.01 warning line, above the 0.001 hard-stop line, so the status is **{{gate_srm_status}}**. An imbalance this large happens by chance less than 1% of the time, and its usual causes (an assignment bug, one version logging installs differently, bot filtering) can also bias the retention comparison. The naive results below are reported but **not certified**; B4 checks where the imbalance sits and which part of the D7 gap the gate could explain. The cleaned player table (one gate_30 logging error removed) has {{g_n40}} vs {{g_n30}} players, so there gate_40 has {{excess_clean}} extra installs.

#### B3. Naive readout: D1 and D7, recomputed from the player table
""")

code('''
by_v = players.groupby("version").agg(n=("user_id", "size"), r1=("retention_1", "sum"), r7=("retention_7", "sum"))
gate_res = {}
for metric, col in (("retention_1", "r1"), ("retention_7", "r7")):
    r = S.two_prop_test(by_v.loc["gate_40", col], by_v.loc["gate_40", "n"],
                        by_v.loc["gate_30", col], by_v.loc["gate_30", "n"], alpha=C.ALPHA)
    mismatch = [k for k in r.to_dict() if not same(getattr(r, k), G[metric][k])]
    assert not mismatch, f"{metric}: recompute differs from results.json: {mismatch}"
    gate_res[metric] = r

table(pd.DataFrame([{
    "metric": {"retention_1": "D1 retention (guardrail)", "retention_7": "D7 retention (primary)"}[m],
    "gate_30": r.rate_c, "gate_40": r.rate_t, "difference (pp)": r.abs_lift * 100,
    "95% CI (pp)": ci_txt(r.abs_ci_low, r.abs_ci_high), "relative": r.rel_lift, "p": r.p_value,
    "bootstrap 95% CI (pp)": ci_txt(*G[m]["boot_abs_ci"]),
} for m, r in gate_res.items()]), {"gate_30": "{:.2%}", "gate_40": "{:.2%}", "difference (pp)": "{:+.2f}",
                                  "relative": "{:+.1%}", "p": fmt_p}, bold_below=["p"])

boot_gate = caches["boot_gate"]
for m in ("retention_1", "retention_7"):
    d = boot_gate.loc[boot_gate["metric"] == m, "abs_lift"]
    assert np.allclose(S.percentile_ci(d, C.ALPHA), G[m]["boot_abs_ci"], atol=1e-6)
    assert same((d >= 0).mean(), G[m]["boot_share_ge_0"])
    print(f"{m}: {(d < 0).mean():.1%} of {len(d):,} bootstrap draws put gate_40 below gate_30")
''')

md("""
**Result (naive, not certified).** D7: {{g7_t}} (gate_40) vs {{g7_c}} (gate_30), so gate_40 shows **{{g7_lift_abs}} pp lower D7 ({{g7_lift}} pp, 95% CI {{g7_lo}} to {{g7_hi}})**, {{g7_rel}} relative, p = {{g7_p}}; {{g7_boot_below}} of the bootstrap draws fall below zero. D1: {{g1_t}} vs {{g1_c}}, {{g1_lift}} pp (CI {{g1_lo}} to {{g1_hi}}, p = {{g1_p}}; {{g1_boot_below}} of draws below zero). Taken at face value, gate_40 shows lower D7; B4 asks how much of that gap the gate could explain.
""")

chart("gate_rates")
chart("gate_bootstrap")

md("""
#### B4. Integrity checks: which part of the gap could the gate explain?

**What "30+ rounds" means.** Each level takes at least one round (rounds ≥ levels), so a player with fewer than 30 rounds can't have got past level 30. There is no level field, so "30+ rounds" is our definition of "could have reached level 30", and players with < 30 rounds are treated as never having met a gate (one edge case below).

**Why stratifying on rounds is allowed here when stratifying on total ads (A3) is not.** Ads can change how long a user stays from the first impression, so exposure can be caused by the treatment. Below level 30 the two game versions are identical, so whether a player ever plays 30 rounds cannot depend on the gate (given rounds ≥ levels): it behaves like a pre-treatment trait. It is an approximation: a gate_30 player who cleared 29 levels in exactly 29 rounds would already face the gate while counted below 30. Such players are few (no pile-up at 29 rounds: {{r29_n40}} gate_40 vs {{r29_n30}} gate_30 players), and leaving out everyone with exactly 29 rounds, the 15–28 band still shows {{b1528_d7}} pp D7 (95% CI {{b1528_lo}} to {{b1528_hi}}; B4.3). The strata are close to, not exactly, gate-free. That is why the gate's share of the gap is called "the part the gate could explain" (B4.4), never an estimate of its effect.

Players with fewer than 30 rounds form an approximate negative control: almost none can have met a gate (the exception is a flawless 29-round gate_30 player), so their numbers and their retention should approximately match by version. That gives three approximate checks, then a decomposition of the D7 gap.

**B4.1 Where are the extra installs?** Arm sizes by rounds played, raw assignment log.
""")

code('''
STRATA = {"rounds_lt_15": ("fewer than 15 rounds", log["sum_gamerounds"] < 15),
          "rounds_15_29": ("15–29 rounds (almost none could have met a gate)", log["sum_gamerounds"].between(15, 29)),
          "rounds_lt_30": ("fewer than 30 rounds (the two bands above)", log["sum_gamerounds"] < 30),
          "rounds_ge_30": ("30+ rounds (could meet the gate)", log["sum_gamerounds"] >= 30)}
srm_rows = []
for key, (label, mask) in STRATA.items():
    sub = log[mask]
    n_t_, n_c_ = int((sub["version"] == "gate_40").sum()), int((sub["version"] == "gate_30").sum())
    s = S.srm_check(n_t_, n_c_, C.INTENDED_GATE40_SHARE)
    ref = G["srm_by_stratum"][key]
    assert (n_t_, n_c_, n_t_ - n_c_) == (ref["n_t"], ref["n_c"], ref["net_excess_t"]) and same(s["p_value"], ref["p_value"])
    srm_rows.append({"key": key, "rounds played (raw log)": label, "gate_30": n_c_, "gate_40": n_t_,
                     "net excess in gate_40": n_t_ - n_c_, "gate_40 share": s["observed_share_t"],
                     "chi-square p": s["p_value"]})
srm_rows.append({"key": "all", "rounds played (raw log)": "all players: the SRM check itself (B2)",
                 "gate_30": srm_gate["n_c"], "gate_40": srm_gate["n_t"], "net excess in gate_40": srm_gate["n_t"] - srm_gate["n_c"],
                 "gate_40 share": srm_gate["observed_share_t"], "chi-square p": srm_gate["p_value"]})
srm_strata = pd.DataFrame(srm_rows).set_index("key")
assert srm_strata.loc["rounds_lt_15", "net excess in gate_40"] == G["excess_players_with_lt_15_rounds"]
table(srm_strata, {"gate_30": "{:,}", "gate_40": "{:,}", "net excess in gate_40": "{:+,}", "gate_40 share": "{:.2%}",
                   "chi-square p": fmt_p})
print("The bands were chosen after seeing the overall warning, so their p-values are descriptive and carry no "
      "PASS / WARNING / FAIL label.")
''')

md("""
**Reading.** The excess sits among short sessions: a net excess of {{excess_lt15}} among players with < 15 rounds ({{lt15_n40}} vs {{lt15_n30}}, p = {{lt15_p}}), {{b1529_excess}} at 15–29 rounds (p = {{b1529_srm_p}}) and {{ge30_excess}} at 30+ rounds ({{ge30_n40}} vs {{ge30_n30}}, p = {{ge30_p}}). These bands were chosen after seeing the warning, so their p-values are descriptive. A gate nobody in the band has reached can't create extra installs, so most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from gate_30), for example one version logging extra installs, or bot traffic. Engineering confirms the cause; short sessions are the first lead.

**B4.2 Pre-gate play.** Before level 30 the versions are identical, so play capped at 29 rounds should look the same in both.
""")

code('''
rt = players.loc[players["version"] == "gate_40", "sum_gamerounds"]
rc = players.loc[players["version"] == "gate_30", "sum_gamerounds"]
mw_pre = sps.mannwhitneyu(rt.clip(upper=29), rc.clip(upper=29))   # play before level 30: the same game in both versions
mw_pre_lt30 = sps.mannwhitneyu(rt[rt < 30], rc[rc < 30])           # the same comparison within players with < 30 rounds
pg = G["pre_gate_engagement"]
assert same(rt.clip(upper=29).mean(), pg["mean_capped_29_t"]) and same(rc.clip(upper=29).mean(), pg["mean_capped_29_c"])
assert same(mw_pre.pvalue, pg["mannwhitney_p"]) and same(mw_pre_lt30.pvalue, pg["mannwhitney_p_within_lt_30"])
comp = G["composition"]
for v, x in (("gate_40", rt), ("gate_30", rc)):
    assert same((x == 0).mean(), comp["zero_round_share"][v]) and same((x < 30).mean(), comp["under_30_share"][v])
table(pd.DataFrame([{"version": v, "players": len(x), "mean rounds, capped at 29": x.clip(upper=29).mean(),
                     "share with 0 rounds": (x == 0).mean(), "share with < 15 rounds": (x < 15).mean(),
                     "share with < 30 rounds": (x < 30).mean()} for v, x in (("gate_30", rc), ("gate_40", rt))]),
      {"players": "{:,}", "mean rounds, capped at 29": "{:.2f}", "share with 0 rounds": "{:.2%}",
       "share with < 15 rounds": "{:.2%}", "share with < 30 rounds": "{:.2%}"})
print(f"Mann-Whitney test of rounds capped at 29, gate_40 vs gate_30: {p_txt(mw_pre.pvalue)}; "
      f"within players with < 30 rounds: {p_txt(mw_pre_lt30.pvalue)}")
''')

md("""
**Reading.** Play before level 30 is lower in gate_40 although the game is identical there: mean {{pre_mean40}} (gate_40) vs {{pre_mean30}} (gate_30) rounds capped at 29, Mann–Whitney p = {{pre_mw_p}}. This is the same imbalance seen as a distribution, not independent evidence: gate_40 has more zero-round players ({{zero40}} vs {{zero30}}) and more players below 30 rounds ({{u30_40}} vs {{u30_30}}), and within players with < 30 rounds the difference is p = {{pre_mw_p_lt30}}.
""")

chart("gate_engagement_gap")

md("""
**B4.3 Negative control, by rounds band.** Players with fewer than 30 rounds form an approximate negative control: almost none can have met a gate (the exception is a flawless 29-round gate_30 player), so their retention should approximately match by version.
""")

code('''
GROUPS = {"never_reached_30": players["sum_gamerounds"] < 30, "rounds_lt_15": players["sum_gamerounds"] < 15,
          "rounds_15_29": players["sum_gamerounds"].between(15, 29), "reached_30": players["sum_gamerounds"] >= 30,
          # edge case: at exactly 29 rounds a gate_30 player may already face the gate
          "rounds_15_28": players["sum_gamerounds"].between(15, 28), "rounds_29": players["sum_gamerounds"] == 29}


def by_version(mask, metric, drop_t=0):
    """gate_40 vs gate_30 inside a group of players; drop_t removes that many gate_40 players who never returned."""
    a = players[mask].groupby("version")[metric].agg(["sum", "size"])
    return S.two_prop_test(a.loc["gate_40", "sum"], a.loc["gate_40", "size"] - drop_t,
                           a.loc["gate_30", "sum"], a.loc["gate_30", "size"], alpha=C.ALPHA)


nc_res = {}
for key, mask in GROUPS.items():
    refs = [G["negative_control"].get(key), G["retention_by_rounds_band"].get({"reached_30": "rounds_ge_30"}.get(key, key))]
    for m in ("retention_1", "retention_7"):
        r = by_version(mask, m)
        for ref in (x[m] for x in refs if x):
            mismatch = [k for k, v in ref.items() if not same(getattr(r, k), v)]
            assert not mismatch, f"{key} / {m}: recompute differs from results.json: {mismatch}"
        nc_res[(key, m)] = r

# The negative control once gate_40's net excess of < 15-round installs is removed (as if none of them ever returned)
ex15 = G["excess_players_with_lt_15_rounds"]
nc_removed = by_version(GROUPS["never_reached_30"], "retention_7", drop_t=ex15)
ref = G["negative_control"]["never_reached_30_excess_removed"]
assert ref["excess_removed"] == ex15
assert not [k for k, v in ref["retention_7"].items() if not same(getattr(nc_removed, k), v)]

nc7, b15, b1529, b30 = (nc_res[(k, "retention_7")] for k in ("never_reached_30", "rounds_lt_15", "rounds_15_29", "reached_30"))
b1528, r29 = nc_res[("rounds_15_28", "retention_7")], nc_res[("rounds_29", "retention_7")]


# Do the 15-29 and < 15 bands' D7 gaps differ from each other? (independent bands, unpooled standard errors)
def gap_se(r):
    return np.sqrt(r.rate_t * (1 - r.rate_t) / r.n_t + r.rate_c * (1 - r.rate_c) / r.n_c)


gap_diff, gap_diff_se = b1529.abs_lift - b15.abs_lift, np.hypot(gap_se(b1529), gap_se(b15))
gap_diff_p = 2 * sps.norm.sf(abs(gap_diff / gap_diff_se))
ref = G["d7_band_gap_difference_15_29_vs_lt_15"]
assert same(gap_diff, ref["diff"]) and same(gap_diff_se, ref["se"]) and same(gap_diff_p, ref["p_value"])

# claims the text relies on: the negative control is borderline (just under alpha); such gap as there is comes from
# 15-29 rounds rather than < 15, though the two bands' gaps are not distinguishable; 15-29 and 30+ show a similar
# (negative) gap; removing the excess leaves no clear gap; the 29-round edge case is small and balanced in number, and
# without it 15-28 still shows a negative gap
assert 0.01 < nc7.p_value < C.ALPHA and abs(b15.abs_lift) < abs(b1529.abs_lift) and b15.p_value > C.ALPHA
assert gap_diff_p > C.ALPHA
assert b1529.abs_lift < 0 and b30.abs_lift < 0 and abs(b1529.abs_lift - b30.abs_lift) < 0.005
assert nc_removed.p_value > C.ALPHA
assert r29.n_t + r29.n_c < 0.05 * (b1529.n_t + b1529.n_c)
assert S.srm_check(r29.n_t, r29.n_c, C.INTENDED_GATE40_SHARE)["p_value"] > C.ALPHA and b1528.abs_lift < 0
table(pd.DataFrame([{
    "players": label, "gate_30 / gate_40 players": f"{r.n_c:,} / {r.n_t:,}", "D7 gate_30": r.rate_c, "D7 gate_40": r.rate_t,
    "difference (pp)": r.abs_lift * 100, "95% CI (pp)": ci_txt(r.abs_ci_low, r.abs_ci_high, 3), "p": r.p_value,
} for label, r in (("< 30 rounds: approximately gate-free (negative control)", nc7),
                   ("... of which < 15 rounds (where the net excess sits)", b15),
                   ("... of which 15-29 rounds (balanced in number)", b1529),
                   ("... 15-29 without the 29-round edge case (15-28 rounds)", b1528),
                   (f"< 30 rounds, without gate_40's net excess of {ex15:,} < 15-round installs", nc_removed),
                   ("30+ rounds: could meet the gate", b30))]),
      {"D7 gate_30": "{:.2%}", "D7 gate_40": "{:.2%}", "difference (pp)": "{:+.2f}", "p": fmt_p}, bold_below=["p"])
''')

md("""
**Reading.** Players with fewer than 30 rounds form an approximate negative control: almost none can have met a gate (the exception is a flawless 29-round gate_30 player). D7 is {{nc_d7_abs}} pp lower in gate_40 ({{nc_d7}} pp, 95% CI {{nc_d7_lo}} to {{nc_d7_hi}}, p = {{nc_d7_p}}). That is **borderline on its own**; it carries weight only because the sample-ratio warning independently says the arms are not comparable. Such gap as there is comes from the 15–29 band ({{b1529_d7}} pp, p = {{b1529_p}}, balanced in number) rather than the < 15 band where the net excess sits ({{b15_d7}} pp, p = {{b15_p}}), though the two bands' gaps are not distinguishable from each other (p = {{band_gap_p}}). Removing the net {{ncx_removed}} extra < 15-round installs (as if none of them ever returned) moves it only to {{ncx_d7}} pp (95% CI {{ncx_lo}} to {{ncx_hi}}, p = {{ncx_p}}). So the extra installs explain the SRM and the player-mix part of the gap, but not this one. Players with 30+ rounds, who could meet the gate, show {{re_d7}} pp (95% CI {{re_d7_lo}} to {{re_d7_hi}}, p = {{re_d7_p}}): a similar gap to players with 15–29 rounds, almost none of whom can have met a gate ({{b1529_d7}} pp, 95% CI {{b1529_lo}} to {{b1529_hi}}).
""")

chart("gate_negative_control")

md("""
**B4.4 Decomposition of the D7 gap.** With two strata (< 30 rounds: never met a gate / 30+ rounds: could meet it), the naive gap splits exactly into three parts:

- **player mix** = sum over strata of (gate_40's share of players in the stratum − gate_30's share) × the stratum's average D7 rate: the effect of gate_40 simply having more low-engagement players;
- **within players who never met a gate** = their average share × their D7 gap: the gate cannot act here;
- **within players who could meet the gate** = their average share × their D7 gap: the part the gate could explain, expressed per install. It is not an estimate of the gate's effect (B4.3).

D1 splits the same way (B5).
""")

code('''
is40 = players["version"] == "gate_40"


def decompose(metric: str) -> dict:
    """Split the naive gap into player mix + within never-met-a-gate + within could-meet-the-gate (exact)."""
    parts = {}
    for key in ("never_reached_30", "reached_30"):
        mask = GROUPS[key]
        w_t, w_c = mask[is40].mean(), mask[~is40].mean()                   # share of each version's players
        r_t, r_c = players.loc[mask & is40, metric].mean(), players.loc[mask & ~is40, metric].mean()
        parts[key] = {"w_t": w_t, "w_c": w_c, "r_t": r_t, "r_c": r_c,
                      "within": (w_t + w_c) / 2 * (r_t - r_c), "composition": (w_t - w_c) * (r_t + r_c) / 2}
    reach = nc_res[("reached_30", metric)]
    w_reach = (parts["reached_30"]["w_t"] + parts["reached_30"]["w_c"]) / 2
    out = {"naive_diff": gate_res[metric].abs_lift,
           "composition": parts["never_reached_30"]["composition"] + parts["reached_30"]["composition"],
           "within_never_reached_30": parts["never_reached_30"]["within"],
           "within_reached_30": parts["reached_30"]["within"], "share_reached_30": w_reach,
           "ci": (w_reach * reach.abs_ci_low, w_reach * reach.abs_ci_high)}   # CI of the reachers' gap, per install
    assert np.isclose(out["composition"] + out["within_never_reached_30"] + out["within_reached_30"], out["naive_diff"],
                      rtol=0, atol=1e-12)
    ref = G[{"retention_7": "d7_decomposition", "retention_1": "d1_decomposition"}[metric]]
    assert all(same(out[k], ref[k]) for k in ("naive_diff", "composition", "within_never_reached_30",
                                              "within_reached_30", "share_reached_30"))
    assert np.allclose(out["ci"], ref["install_level_effect_ci_if_only_reachers"], atol=1e-6)
    assert all(same(v, ref["detail"][key][k]) for key in parts for k, v in parts[key].items())
    return out


dec7, dec1 = decompose("retention_7"), decompose("retention_1")
table(pd.DataFrame([
    {"part of the D7 gap": "naive gap, all players", "pp of installs": dec7["naive_diff"] * 100,
     "95% CI": ci_txt(gate_res["retention_7"].abs_ci_low, gate_res["retention_7"].abs_ci_high),
     "where it sits": "all installs"},
    {"part of the D7 gap": "player mix (gate_40 has more low-engagement players)", "pp of installs": dec7["composition"] * 100,
     "95% CI": "", "where it sits": "where the gate cannot act (imbalance)"},
    {"part of the D7 gap": "within players who never met a gate (< 30 rounds)",
     "pp of installs": dec7["within_never_reached_30"] * 100, "95% CI": "", "where it sits": "where the gate cannot act"},
    {"part of the D7 gap": "within players who could meet the gate (30+ rounds)",
     "pp of installs": dec7["within_reached_30"] * 100, "95% CI": ci_txt(*dec7["ci"]),
     "where it sits": "the part the gate could explain (not an estimate of its effect)"},
]), {"pp of installs": "{:+.2f}"})

not_gate_share = (dec7["composition"] + dec7["within_never_reached_30"]) / dec7["naive_diff"]
per10k = [x * 10_000 for x in (dec7["within_reached_30"], *dec7["ci"])]   # Day-7 players per 10,000 installs
# claims the text relies on: the part the gate could explain is negative, its CI runs from "fewer" to "more"
assert per10k[1] < per10k[0] < 0 < per10k[2]
print(f"Where the gate cannot act (player mix + never met a gate): {not_gate_share:.1%} of the naive gap. "
      f"The part the gate could explain, per 10,000 installs: {snum(per10k[0])} Day-7 players "
      f"(95% CI {snum(per10k[1])} to {snum(per10k[2])}).")
''')

md("""
**Reading.** The naive {{g7_lift}} pp splits exactly into player mix {{dec_mix}} pp + players who never met a gate {{dec_never}} pp + players who could meet the gate {{dec_reach}} pp per install (95% CI {{dec_reach_lo}} to {{dec_reach_hi}}). About {{not_gate_share}} of the naive gap (mix + never met a gate) **sits where the gate cannot act**. The remaining {{dec_reach}} pp per install ({{re_d7}} pp among the {{share_reach}} of installs with 30+ rounds) is **the part the gate could explain, not an estimate of the gate's effect**: players with 15–29 rounds, almost none of whom can have met a gate, show a similar gap ({{b1529_d7}} pp, 95% CI {{b1529_lo}} to {{b1529_hi}}) to players with 30+ rounds ({{re_d7}} pp, 95% CI {{re_d7_lo}} to {{re_d7_hi}}), so even this part may not be the gate. Per 10,000 installs it is ≈{{per10k}} fewer Day-7 players (95% CI {{per10k_lo}} fewer to {{per10k_hi}} more).
""")

chart("gate_decomposition")

md("""
**B4.5 Best case for gate_40.** Suppose every one of gate_40's {{excess_clean}} extra installs in the cleaned table was a junk install that never returned: the reading most favourable to gate_40. Remove them and compare again.
""")

code('''
excess = n40 - n30                    # extra gate_40 installs in the cleaned table
r7 = gate_res["retention_7"]
best = S.two_prop_test(r7.conv_t, r7.n_t - excess, r7.conv_c, r7.n_c, alpha=C.ALPHA)
bc = G["best_case_for_gate_40"]
assert excess == bc["excess_players_gate_40"] and same(best.abs_lift, bc["d7_diff_if_excess_removed"])
assert np.allclose([best.abs_ci_low, best.abs_ci_high], bc["ci"], atol=1e-6) and same(best.p_value, bc["p_value"])
# claim the text relies on: even then the gap stays negative, and its interval includes 0
assert best.abs_ci_low < best.abs_lift < 0 < best.abs_ci_high
print(f"Best case for gate_40: without {excess:,} non-returning gate_40 installs the D7 gap would be "
      f"{spp(best.abs_lift)} pp (95% CI {ci_txt(best.abs_ci_low, best.abs_ci_high)}, {p_txt(best.p_value)})")
''')

md("""
**Reading.** Even then gate_40 would still show {{best_d7}} pp D7 (95% CI {{best_lo}} to {{best_hi}}, p = {{best_p}}); the interval includes 0. So the extra installs alone don't account for the whole naive gap, and what remains is not clearly different from 0 either.

#### B5. Guardrails: D1 and engagement
""")

code('''
# D1: the naive gap carries the same imbalance; split it like D7
r1 = gate_res["retention_1"]
re1 = nc_res[("reached_30", "retention_1")]
table(pd.DataFrame([
    {"D1 comparison": "naive gap, all players", "pp": r1.abs_lift * 100, "95% CI (pp)": ci_txt(r1.abs_ci_low, r1.abs_ci_high)},
    {"D1 comparison": "... player mix (part of the naive gap)", "pp": dec1["composition"] * 100, "95% CI (pp)": ""},
    {"D1 comparison": "... within players who never met a gate (per install)", "pp": dec1["within_never_reached_30"] * 100,
     "95% CI (pp)": ""},
    {"D1 comparison": "... within players who could meet the gate (per install)", "pp": dec1["within_reached_30"] * 100,
     "95% CI (pp)": ci_txt(*dec1["ci"])},
    {"D1 comparison": "players with 30+ rounds, their own D1 gap", "pp": re1.abs_lift * 100,
     "95% CI (pp)": ci_txt(re1.abs_ci_low, re1.abs_ci_high)},
]), {"pp": "{:+.2f}"})
# claims the text relies on: the player mix is most of the naive D1 gap; no sign of a D1 effect: the part the gate
# could explain (per install) has a CI that spans 0, and so does the (diluted) 30+ band's own gap
assert abs(dec1["composition"]) > abs(r1.abs_lift) / 2 and dec1["ci"][0] < 0 < dec1["ci"][1]
assert re1.abs_ci_low < 0 < re1.abs_ci_high

# Rounds in the first 14 days, all players: heavy-tailed, so a user-level bootstrap of the mean difference
rg = G["rounds"]
boot_rounds = S.bootstrap_mean_diff(rt, rc, rg["n_boot"], C.SEED + 14)
mw = sps.mannwhitneyu(rt, rc)
assert same(rt.mean() - rc.mean(), rg["mean_diff"]) and np.allclose(S.percentile_ci(boot_rounds), rg["mean_diff_boot_ci"], atol=1e-6)
assert same(mw.pvalue, rg["mannwhitney_p"]) and (rt.median(), rc.median()) == (rg["median_t"], rg["median_c"])

# ... and among players with 30+ rounds (balanced in number), who could meet the gate
rr = G["rounds_among_reachers"]
r30t, r30c = rt[rt >= 30], rc[rc >= 30]
boot_r30 = S.bootstrap_mean_diff(r30t, r30c, C.N_BOOT_MEANS, C.SEED + 16)
mw30 = sps.mannwhitneyu(r30t, r30c)
past40 = S.two_prop_test(int((r30t >= 40).sum()), len(r30t), int((r30c >= 40).sum()), len(r30c), alpha=C.ALPHA)
assert (len(r30t), len(r30c), r30t.median(), r30c.median()) == (rr["n_t"], rr["n_c"], rr["median_t"], rr["median_c"])
assert same(r30t.mean() - r30c.mean(), rr["mean_diff"]) and np.allclose(S.percentile_ci(boot_r30), rr["mean_diff_boot_ci"], atol=1e-6)
assert same(mw30.pvalue, rr["mannwhitney_p"])
assert not [k for k, v in rr["share_past_40_rounds"].items() if not same(getattr(past40, k), v)]
# claims the text relies on: the all-player mean difference is indistinguishable from 0; among players with 30+ rounds
# gate_40 plays a little more (median, at least 40 rounds) while the mean difference is too noisy, and D7 is not higher
assert rg["mean_diff_boot_ci"][0] < 0 < rg["mean_diff_boot_ci"][1]
assert mw30.pvalue < C.ALPHA and past40.abs_ci_low > 0 and rr["mean_diff_boot_ci"][0] < 0 < rr["mean_diff_boot_ci"][1]
assert nc_res[("reached_30", "retention_7")].abs_lift < 0
table(pd.DataFrame([{"players": who, "version": v, "players (n)": len(x), "median rounds": x.median(),
                     "mean rounds": x.mean(), "share with at least 40 rounds": (x >= 40).mean()}
                    for who, pair in (("all players", (("gate_30", rc), ("gate_40", rt))),
                                      ("30+ rounds (could meet the gate)", (("gate_30", r30c), ("gate_40", r30t))))
                    for v, x in pair]),
      {"players (n)": "{:,}", "median rounds": "{:.0f}", "mean rounds": "{:.2f}", "share with at least 40 rounds": "{:.1%}"})
lo, hi = S.percentile_ci(boot_rounds)
lo30, hi30 = S.percentile_ci(boot_r30)
print(f"All players, mean difference gate_40 - gate_30: {snum(rt.mean() - rc.mean(), 2)} rounds (bootstrap 95% CI "
      f"{snum(lo, 2)} to {snum(hi, 2)}, {len(boot_rounds):,} draws); Mann-Whitney {p_txt(mw.pvalue)}")
print(f"30+ rounds, mean difference: {snum(r30t.mean() - r30c.mean(), 2)} rounds (bootstrap 95% CI {snum(lo30, 2)} to "
      f"{snum(hi30, 2)}); Mann-Whitney {p_txt(mw30.pvalue)}; at least 40 rounds {spp(past40.abs_lift)} pp "
      f"(95% CI {ci_txt(past40.abs_ci_low, past40.abs_ci_high)})")
''')

md("""
**D1.** The naive D1 {{g1_lift}} pp (95% CI {{g1_lo}} to {{g1_hi}}, p = {{g1_p}}) carries the same imbalance: the player mix alone accounts for {{d1_mix}} pp of it, and players who never met a gate for {{d1_never}} pp. The part the gate could explain is {{d1_reach_pi}} pp per install (95% CI {{d1_reach_pi_lo}} to {{d1_reach_pi_hi}}): no sign of a D1 effect. Among players with 30+ rounds the D1 gap is {{re_d1}} pp (95% CI {{re_d1_lo}} to {{re_d1_hi}}), but that band figure is diluted: the gate can change Day 1 only for players who reached level 30 on the install day, and the data cannot single them out.

**Engagement.** The all-player mean difference ({{rounds_diff}} rounds, bootstrap 95% CI {{rounds_lo}} to {{rounds_hi}}, {{rounds_nboot}} draws) carries the same imbalance as D7, so it is not a clean guardrail. Among players with 30+ rounds (balanced in number), gate_40 players play a little more: median {{r30_med40}} vs {{r30_med30}} rounds (Mann–Whitney p = {{r30_mw_p}}), and {{r30_past40_t}} vs {{r30_past40_c}} played at least 40 rounds ({{r30_past40_diff}} pp, 95% CI {{r30_past40_lo}} to {{r30_past40_hi}}). The mean difference ({{r30_mean_diff}} rounds, 95% CI {{r30_mean_lo}} to {{r30_mean_hi}}) is too noisy to read. It is a descriptive difference: assignment is uncertified and the group is defined by rounds played, so it does not show that gate_40 causes more play. These players' D7 is not higher ({{re_d7}} pp, 95% CI {{re_d7_lo}} to {{re_d7_hi}}): no sign of a retention benefit. Total rounds over 14 days is itself shaped by the gate past level 30, so it is a guardrail, not a covariate; only the 30-round threshold is used to stratify (B4).

#### B6. MDE as run, and re-test sizing
""")

code('''
# MDE as run: a property of the design, never compared with an estimate
table(pd.DataFrame([{"metric": {"retention_7": "D7 (primary)", "retention_1": "D1 (guardrail)"}[m],
                     "baseline (gate_30)": G[m]["mde"]["p_c"], f"MDE at {C.POWER:.0%} power (pp)": G[m]["mde"]["mde_abs"] * 100,
                     "MDE (relative)": G[m]["mde"]["mde_rel"]} for m in ("retention_7", "retention_1")]),
      {"baseline (gate_30)": "{:.2%}", f"MDE at {C.POWER:.0%} power (pp)": "{:.2f}", "MDE (relative)": "{:.1%}"})

# Re-test sizing at a change fixed in advance (config.yaml), never at the observed effect
rs = G["retest_sizing"]
sesoi_g = C.GATE_SESOI_ABS                    # smallest D7 change per install worth acting on (placeholder)
base_install = gate_res["retention_7"].rate_c
reach7, w_reach = nc_res[("reached_30", "retention_7")], dec7["share_reached_30"]
n_install = S.required_total_n(base_install, -sesoi_g, 0.5, C.ALPHA, C.POWER)              # analysed over all installs
n_reach = S.required_total_n(reach7.rate_c, -sesoi_g / w_reach, 0.5, C.ALPHA, C.POWER)     # among players who reach 30
n_reach_installs = int(np.ceil(n_reach / w_reach))
assert same(sesoi_g, rs["smallest_d7_change_per_install"]) and same(base_install, rs["baseline_d7_install"])
assert same(w_reach, rs["share_reached_30"]) and same(sesoi_g / w_reach, rs["equivalent_change_among_reachers"])
assert same(reach7.rate_c, rs["baseline_d7_reachers"])
assert (n_install, n_reach, n_reach_installs) == (rs["installs_needed_install_level_5050"], rs["reachers_needed_5050"],
                                                  rs["installs_needed_reacher_analysis_5050"])
# The sizes above detect a drop of that size; the same change as a rise needs slightly more (higher variance)
n_install_rise = S.required_total_n(base_install, sesoi_g, 0.5, C.ALPHA, C.POWER)
n_reach_rise = S.required_total_n(reach7.rate_c, sesoi_g / w_reach, 0.5, C.ALPHA, C.POWER)
n_reach_installs_rise = int(np.ceil(n_reach_rise / w_reach))
assert (n_install_rise, n_reach_rise, n_reach_installs_rise) == (
    rs["installs_needed_install_level_5050_if_rise"], rs["reachers_needed_5050_if_rise"],
    rs["installs_needed_reacher_analysis_5050_if_rise"])
assert n_install < n_install_rise and n_reach_installs < n_reach_installs_rise
table(pd.DataFrame([
    {"primary analysis": "among players who reach level 30 (pre-registered)", "D7 change to detect (pp)": sesoi_g / w_reach * 100,
     "baseline D7": reach7.rate_c, "players analysed": n_reach, "installs needed at 50 / 50": n_reach_installs,
     "... if the change is a rise": n_reach_installs_rise},
    {"primary analysis": "over all installs", "D7 change to detect (pp)": sesoi_g * 100, "baseline D7": base_install,
     "players analysed": n_install, "installs needed at 50 / 50": n_install, "... if the change is a rise": n_install_rise},
]), {"D7 change to detect (pp)": "{:.2f}", "baseline D7": "{:.1%}", "players analysed": "{:,}",
     "installs needed at 50 / 50": "{:,}", "... if the change is a rise": "{:,}"})
print(f"Smallest D7 change worth acting on: {sesoi_g * 100:g} pp per install ({sesoi_g / base_install:.1%} of gate_30's "
      f"{base_install:.1%}); {C.POWER:.0%} power, two-sided alpha = {C.ALPHA:g}")
''')

md("""
**MDE as run.** With ~45K players per arm the test could detect D7 changes of {{g7_mde}} pp ({{g7_mde_rel}} relative) and D1 changes of {{g1_mde}} pp at {{power}} power. These numbers describe the design; they are never compared with an estimate.

**Re-test sizing, never at the observed effect.** Pre-register the smallest D7 change worth acting on: **{{gate_sesoi}} pp per install**, a placeholder in `config.yaml` to agree with the Game PM (≈{{gate_sesoi_rel}} of gate_30's {{g7_base_1}} D7). If the true effect is smaller than that, it would not change the decision. Whether a player reaches level 30 is fixed before the gate, so the primary analysis can be pre-registered among those players: {{gate_sesoi}} pp per install is {{retest_equiv}} pp among them (on a {{retest_base_reach}} base), which needs ≈{{retest_reachers_k}} such players ({{retest_reachers}}), i.e. **≈{{retest_reacher_installs_k}} installs at 50/50** ({{retest_reacher_installs}}). Analysed over all installs it needs ≈{{retest_install_k}} ({{retest_install}}). These are sized to detect a {{gate_sesoi}} pp drop; a rise of the same size needs up to ≈{{retest_rise_extra}} more (≈{{retest_install_rise_k}} install-level, ≈{{retest_reacher_installs_rise_k}} for the reacher analysis). The reacher figure uses this cohort's {{retest_share_reach}} reaching level 30; re-check with the new cohort's share before launch. Add a daily 50/50 group-size check so an imbalance like this one is caught within days.
""")

md("""
#### B7. Decision: keep the gate at level 30 (not certified)

| | |
|---|---|
| **Decision** | **Keep gate_30, the status quo; don't ship gate_40.** Owner: Game PM. |
| **Why** | No sign of a retention benefit. The naive D7 gap is {{g7_lift}} pp, but about {{not_gate_share}} of it sits where the gate cannot act; the part the gate could explain is about {{dec_reach_1}} pp per install (95% CI {{dec_reach_lo}} to {{dec_reach_hi}}; ≈{{per10k}} fewer Day-7 players per 10,000 installs), possibly zero, and even that may not be the gate. D1 shows no sign of an effect (the part the gate could explain is {{d1_reach_pi}} pp per install, 95% CI {{d1_reach_pi_lo}} to {{d1_reach_pi_hi}}). Among players with 30+ rounds (who could have reached level 30), gate_40 players played a little more (median {{r30_med40}} vs {{r30_med30}} rounds; descriptive). Assignment is uncertified and the group is defined by rounds played, so it does not show that gate_40 causes more play, so if the Game PM values that, a clean re-test is the way to decide. |
| **Confidence** | **Not certified.** SRM {{gate_srm_status}} (p = {{gate_srm_p}}): gate_40 received ≈{{excess_clean}} extra installs, with a net excess of {{excess_lt15}} among players with < 15 rounds; pre-gate play differs (the same imbalance, p = {{pre_mw_p}}) and the negative control is borderline (p = {{nc_d7_p}}). Quoting the raw {{g7_lift}} pp would overstate the effect. Keeping gate_30 is the safe default, so the decision doesn't hinge on the SRM; the size of the effect does. |
| **Next** | Engineering + Analytics fix assignment and install logging by version first, starting with short sessions (< 15 rounds). Re-test only if the gate position matters commercially: pre-register a {{gate_sesoi}} pp D7 change per install as the smallest worth acting on; ≈{{retest_reacher_installs_k}} installs at 50/50 with the primary analysis among players who reach level 30 (≈{{retest_reachers_k}} of them), ≈{{retest_install_k}} if analysed over all installs; daily 50/50 group-size check; D7 primary, D1 and rounds among players with 30+ rounds as guardrails. |
""")

# --------------------------------------------------------------------------- Limitations / Recommendations
code('''
# R6 inputs (the retention analysis itself is in 02_retention): the early-churn segment and the onboarding test size
early = res["cookie"]["early_churn_segment"]
low = players[players["sum_gamerounds"] < 15]
d7_by_d1 = players.groupby("d1_status")["retention_7"].mean()
assert len(low) == early["players"] and same(len(low) / len(players), early["share_of_installs"])
assert same(low["retention_7"].mean(), early["retention_7"]) and int(low["retention_7"].sum()) == early["d7_players"]
assert same(d7_by_d1["Returned Day 1"], early["d7_if_returned_day1"])
assert same(d7_by_d1["Did not return Day 1"], early["d7_if_not_returned_day1"])
assert same(players["retention_1"].mean(), res["cookie"]["overall"]["retention_1"])
n_r6 = S.required_total_n(low["retention_7"].mean(), C.ONBOARD_LIFT_ABS, 0.5, C.ALPHA, C.POWER)
sizing = early["onboarding_test_sizing"]
assert same(C.ONBOARD_LIFT_ABS, sizing["target_lift_abs"]) and n_r6 == sizing["players_needed_5050"]
assert int(np.ceil(n_r6 / (len(low) / len(players)))) == sizing["installs_needed_5050"]
print(f"Players with < 15 rounds: {len(low) / len(players):.1%} of installs, D7 {low['retention_7'].mean():.2%}; "
      f"+{C.ONBOARD_LIFT_ABS * 100:g} pp D7 among them needs {n_r6:,} target players "
      f"({sizing['installs_needed_5050']:,} installs) at 50/50")
''')

md("""
## 5. Limitations

- **No revenue, cost or CPM** in the ad data: dollar figures use an illustrative USD {{value}} per conversion. The robust output is incremental conversions.
- **No timestamps:** no view of novelty decay, test duration, time-to-convert or peeking.
- **Only post-assignment fields** to segment on: day, hour and exposure describe *who* responded, not *what to change*; the exposure pattern is confounded by user activity.
- **Fixed arm sizes:** the ad split is most likely a fixed quota, so the SRM test can't detect broken assignment in the ad experiment; exposure parity carries the weight, and its shapes differ a little.
- **Unbalanced design:** the {{psa_share}} control makes the relative lift imprecise ({{ad_rel_lo}} to {{ad_rel_hi}}) and segment cuts noisy: as few as {{min_c_hour}} PSA users in one peak hour, and {{hour_zero_n}} hours ({{hour_zero_list}}, mostly night) with zero control conversions.
- **Gate experiment:** the SRM warning and the borderline negative control are unresolved. The decomposition assumes rounds are logged correctly and that players don't anticipate a gate. Players with fewer than 30 rounds form an approximate negative control: almost none can have met a gate (the exception is a flawless 29-round gate_30 player; rounds ≥ levels and there is no level field). `sum_gamerounds` overlaps the D7 window.
- **Two products:** Cookie Cats is the company's mobile game, a different product from the app the ads ran in (no shared users), so segment sizes will not transfer one-for-one.
- **External validity:** the ad data covers one 2021 flight and the game data one 2017 install cohort; other products and periods need their own tests.
""")

md("""
## 6. Recommendations

| # | Owner | What | Expected impact | How we'll measure | Main risk |
|---|---|---|---|---|---|
| R1 | Growth PM | **Keep the campaign at the current budget, with an always-on {{holdout_share}} PSA holdout.** | ≈{{inc_r}} incremental conversions per comparable flight (95% CI {{inc_lo_r}}–{{inc_hi_r}}). The holdout forgoes ≈{{holdout_conv}} conversions per {{n_total_k}}-user flight (≈USD {{holdout_value_k}} at USD {{value}}) vs. no holdout; this test's {{asrun_share}} PSA arm already forgoes ≈{{asrun_conv}}. Keeps the real effect measured: last-touch would overstate it {{overstate}}× (95% CI {{overstate_lo}}–{{overstate_hi}}×). | Incremental conversions and cost per incremental conversion vs. the holdout, per flight and at least quarterly. | Value per conversion and CPM are unknown: Finance confirms actual CPM < USD {{be_cpm}} (USD {{be_lo}} at the pessimistic end). One flight's holdout read is about as precise as this test; judge trends over several flights. |
| R2 | Growth PM + media buyer | **Don't double blindly; test it.** A user-level test where one arm gets up to 2× today's impressions per user (the closest stand-in for 2× budget) or a frequency cap; 50/50 or 80/20; users tiered by activity measured *before* the test. A true budget test needs a geo split. | Learn the marginal return before committing ≈2× spend. Today's lift sits in the {{share_users_heavy}} of ad users who saw 36–200 ads, so the average return may not hold at 2×. | Incremental conversions per extra USD 1K spent. | The marginal lift of extra impressions may be smaller than the ad-vs-PSA lift. Size this test on a pre-agreed smallest marginal lift worth paying for; the {{n10_50_k}} users of the ad-vs-PSA design is a benchmark, not this test's sample size. Heavy users may tire of more ads (not measurable here). |
| R3 | Media buyer | **Don't re-plan spend by day or hour.** If timing matters, pre-register a test that randomizes the delivery schedule (weekday and time slot, e.g. Tuesday vs. Thursday delivery). | Avoids moving money on a pattern that describes users' habits, not slots we buy. | Difference in lift between randomized delivery slots, with its 95% CI. | Missing a small real timing effect. |
| R4 | Analytics + Eng | **Fix the next test's design:** 50/50 or 80/20 split (96/4 had {{pow10_now}} power for a {{sesoi_rel}} lift); log assignment timestamps; pre-register the primary metric, the smallest lift worth acting on, and guardrails (unsubscribe / complaint rate, cost per acquisition); automatic daily SRM check. | The same users at 50/50 have {{pow10_5050}} power for a {{sesoi_rel}} lift and an MDE of {{mde_5050}} pp instead of {{mde_now}} pp; timestamps show whether the effect fades. | Power / MDE reviewed at design time; daily SRM check. | A bigger control group means more users miss the ads during the test; logging work for Eng. |
| R5 | Game PM (Eng + Analytics fix assignment) | **Keep the first gate at level 30 (no change).** Fix assignment / logging first (gate_40 received ≈{{excess_clean}} extra installs, with a net excess of {{excess_lt15}} among players with < 15 rounds). Re-test only if the gate position matters commercially. | Avoids a change with no sign of a retention benefit. The part of the D7 gap the gate could explain is ≈{{dec_reach_1}} pp per install (95% CI {{dec_reach_lo}} to {{dec_reach_hi}}; ≈{{per10k}} fewer Day-7 players per 10,000 installs), and even that may not be the gate. Among players with 30+ rounds (who could have reached level 30), gate_40 players played a little more (median {{r30_med40}} vs. {{r30_med30}} rounds; descriptive). Assignment is uncertified and the group is defined by rounds played, so it does not show that gate_40 causes more play. | Any re-test: pre-register a {{gate_sesoi}} pp D7 change per install as the smallest change worth acting on (agree with the Game PM); ≈{{retest_reacher_installs_k}} installs at 50/50 with the primary analysis among players who reach level 30 (≈{{retest_reachers_k}} of them), ≈{{retest_install_k}} if analysed over all installs; daily 50/50 group-size check. | Quoting the raw {{g7_lift}} pp would overstate the effect; missing a small real effect either way. |
| R6 | Onboarding PM (with CRM) | **Focus retention work on the Day-1 return:** a randomized Day-1 re-engagement test for new players who play little on their first day, D7 primary (details in `02_retention`). | Targets the biggest drop: {{no_d1}} of installs don't return on Day 1; {{r6_share_lt15}} play < 15 rounds and only {{r6_d7}} of them play on Day 7. Illustrative scenario, not a forecast or an upper bound: shifting 1 pp of installs from the non-returners' {{d7_if_not_d1}} D7 to the Day-1 returners' {{d7_if_d1}} would add about {{r6_scenario}} pp of D7; R6's real impact must be measured. | D7 among targeted players (primary), D1 (secondary). Sizing: +{{r6_lift}} pp D7 on the {{r6_d7}} base (placeholder target) needs ≈{{r6_players_k}} target players (≈{{r6_installs_k}} installs) at 50/50. | Rounds here are counted over 14 days and overlap Day 7, so the real targeting rule must use first-day play; the play–retention link may not be causal; notification fatigue. |
""")


# =====================================================================================
# Build machinery
# =====================================================================================
def run_code_cells() -> dict:
    """Pass 1: execute the code cells in-process with display and charts suppressed."""
    import IPython.display as ipd
    import plotly.basedatatypes as pbt

    ipd.display = lambda *a, **k: None
    pbt.BaseFigure.show = lambda *a, **k: None
    cwd = os.getcwd()
    os.chdir(REPO / "notebooks")
    ns: dict = {"__name__": "__main__"}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for i, (kind, src) in enumerate(CELLS):
                if kind == "code":
                    try:
                        exec(compile(src, f"<cell {i}>", "exec"), ns)
                    except Exception:
                        print(f"--- pass 1 failed in cell {i}:\n{src[:400]}", file=sys.stderr)
                        raise
    finally:
        os.chdir(cwd)
    return ns


def build() -> nbf.NotebookNode:
    ns = run_code_cells()
    vals = {}
    for k, expr in QUOTED_EXPR.items():
        try:
            vals[k] = str(eval(expr, ns))
        except Exception as e:
            raise RuntimeError(f"quoted number {k!r} = {expr!r} failed: {e}") from e
    used: list[str] = []

    def fill(text: str) -> str:
        def rep(m: re.Match) -> str:
            key = m.group(1)
            if key not in vals:
                raise KeyError(f"placeholder {{{{{key}}}}} has no QUOTED_EXPR entry")
            if key not in used:
                used.append(key)
            return vals[key]
        return re.sub(r"\{\{(\w+)\}\}", rep, text)

    nb = nbf.v4.new_notebook()
    for i, (kind, src) in enumerate(CELLS):
        if kind == "markdown":
            text = fill(src)
            for bad in ("$", "\\(", "\\["):
                if bad in text:
                    raise ValueError(f"{bad!r} in markdown cell {i} (MathJax would treat it as math): use USD")
            # house rule: a true minus in prose. A hyphen directly before a digit is a stray minus sign
            # (ranges such as 15-29 inside code spans or labels are written with an en dash in prose).
            stray = re.findall(r"(?<![\w`])-\d", text)
            if stray:
                raise ValueError(f"hyphen-minus before a number in markdown cell {i}: {stray[:5]}")
            cell = nbf.v4.new_markdown_cell(text)
        else:
            if "{{" in src:
                raise ValueError(f"placeholder in code cell {i}")
            cell = nbf.v4.new_code_cell(src)
        cell.id = f"c{i:03d}"
        nb.cells.append(cell)

    unused = [k for k in QUOTED_EXPR if k not in used]
    if unused:
        raise ValueError(f"QUOTED_EXPR entries never used in the text: {unused}")

    # appendix: re-check every quoted number at run time, plus a negative test of the check itself
    nb.cells.append(nbf.v4.new_markdown_cell(dedent("""
        ## Appendix: are the numbers in the text still current?

        The markdown above quotes numbers as text. So that the prose can't silently go stale when the pipeline is
        re-run, the cell below recomputes every quoted number from `results.json`, the caches and the cells above,
        and fails if any of them no longer matches what the text says. It also tests itself: a simulated drift of
        one unit in a quoted number must be caught, so the check can't pass vacuously.
        The check is long and mechanical, so the HTML export shows only its result; the code is in the `.ipynb`.
        """).strip("\n")))
    nb.cells[-1].id = "c900"
    lines = ["# id: (as quoted in the text, how it is recomputed now)", "QUOTED = {"]
    for k in used:
        lines.append(f"    {k!r}: ({vals[k]!r}, lambda: {QUOTED_EXPR[k]}),")
    lines += [
        "}",
        "",
        "",
        "def stale_values(quoted: dict) -> pd.DataFrame:",
        '    """The quoted numbers whose text no longer matches the value recomputed now."""',
        "    check = pd.DataFrame([(k, text, str(recompute())) for k, (text, recompute) in quoted.items()],",
        '                         columns=["id", "quoted in text", "recomputed now"])',
        '    return check[check["quoted in text"] != check["recomputed now"]]',
        "",
        "",
        "stale = stale_values(QUOTED)",
        'assert stale.empty, f"Text is out of date for {len(stale)} value(s); rebuild the notebook:\\n{stale}"',
        "",
        "# Negative test: simulate a re-run in which the headline lift moved by 0.01 pp (one unit of the quoted",
        "# precision) and check that exactly that number is flagged.",
        'drifted = {**QUOTED, "ad_lift": (QUOTED["ad_lift"][0], lambda: pp(r_ad.abs_lift + 0.0001))}',
        'assert stale_values(drifted)["id"].tolist() == ["ad_lift"], "the staleness check missed a simulated drift"',
        'print(f"All {len(QUOTED)} numbers quoted in the text match results.json and the recomputed values; "',
        '      "a simulated 0.01 pp drift in the headline lift is caught.")',
    ]
    nb.cells.append(nbf.v4.new_code_cell("\n".join(lines)))
    nb.cells[-1].id = "c901"
    nb.cells[-1].metadata["jupyter"] = {"source_hidden": True}  # long and mechanical: collapsed in JupyterLab
    nb.cells[-1].metadata["transient"] = {"remove_source": True}  # ... and left out of the HTML export (nbconvert)

    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3 (ipykernel)", "language": "python"}
    nb.metadata["language_info"] = {"name": "python"}
    nb.metadata["title"] = "03 · A/B test readout: ad campaign and gate experiment"
    nbf.validate(nb)
    print(f"built {len(nb.cells)} cells, {len(used)} quoted values")
    return nb


def main() -> None:
    nb = build()
    NB_PATH.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, NB_PATH)
    print(f"wrote {NB_PATH}")


if __name__ == "__main__":
    main()
