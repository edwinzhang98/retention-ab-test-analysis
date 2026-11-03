"""Run the DuckDB SQL in sql/ and reconcile it with the Python pipeline.

Every sql/NN_*.sql file is self-contained: it reads the raw CSVs through the
repo-relative symlinks in data/raw/ and ends in a single SELECT. This module runs
each file in a fresh in-memory DuckDB connection with the repo root as working
directory (so no file can silently depend on another), then compares the key
outputs with reports/results.json, reports/tables/*.csv and a pandas
re-computation from src.data. SQL and pandas are two independent implementations
of the same metric definitions, so agreement is evidence that both are right.

DuckDB has no normal or chi-square CDF, so the SQL stops at test statistics. For
the heterogeneity decisions, this module turns the SQL z statistics into p-values,
applies the same multiple-comparison corrections as the pipeline (src.stats) and
checks that the resulting counts match results.json.

Output
  reports/tables/sql_reconciliation.csv, one row per check:
    check, sql_value, python_value, abs_diff, match, tolerance, sql_file, python_source
  Numbers must agree within the tolerance; labels (statuses, segment names) must
  agree exactly. Raises ReconciliationError (after writing the CSV) if any check
  fails, and before that if a SQL file has no reconciler or a reconciled file is missing.

Usage, from the repo root
  python -m src.sql_check                                  run every file + reconcile
  python -m src.sql_check sql/02_conversion_by_group.sql   run one file and print its result
  python -m src.sql_check 02 09                            same, by number prefix
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import time
from collections.abc import Callable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from scipy import stats as sps

from . import config as C
from . import data as D
from . import stats as S

SQL_DIR = C.ROOT / "sql"
RECON_CSV = C.TABLES_DIR / "sql_reconciliation.csv"

# Tolerances. results.json stores floats rounded to 6 decimals (src.analysis._r),
# so a value read from it can differ from the full-precision SQL value by up to
# half a unit in the 6th decimal. reports/tables/*.csv and pandas re-computations
# are full precision. Counts, flags and labels must match exactly.
TOL_EXACT = 0.0
TOL_JSON = 5e-7 + 1e-9
TOL_FULL = 1e-9

# Python result tables used for segment-level checks, with their segment column
TABLE_KEYS = {
    "ad_lift_by_most_ads_day": "most_ads_day",
    "ad_lift_by_most_ads_hour": "most_ads_hour",
    "ad_lift_by_daypart": "daypart",
    "ad_lift_by_exposure_bucket": "exposure_bucket",
    "retention_by_rounds_bucket": "rounds_bucket",
    "retention_by_d1_status": "d1_status",
    "retention_by_version": "version",
}
HET_DIMS = ("most_ads_day", "most_ads_hour", "daypart", "exposure_bucket")
# Multiple-comparison methods in results.json, with the names used in check labels
ADJ_METHODS = {"none": "unadjusted", "bonferroni": "Bonferroni", "holm": "Holm", "fdr_bh": "BH"}
# Exposure buckets behind the concentration figures, as in src.analysis.ad_experiment
LIGHT_BUCKETS = ["1-5", "6-10", "11-20"]       # 20 ads or fewer
HEAVY_BUCKETS = ["36-50", "51-100", "101-200"]
# Same minimum segment size as src.retention.gap_by_dimension
GAP_MIN_PLAYERS = 500
# Rows of sql/09_gate_integrity.sql: (stratum, key in cookie.gate.srm_by_stratum,
# key in cookie.gate.negative_control and d7_decomposition.detail)
GATE_STRATA = (
    ("All players", None, None),
    ("Rounds < 15", "rounds_lt_15", None),
    ("Rounds < 30", "rounds_lt_30", "never_reached_30"),
    ("Rounds >= 30", "rounds_ge_30", "reached_30"),
)


class ReconciliationError(RuntimeError):
    """SQL output disagrees with the Python pipeline."""


# =============================================================== running SQL
def _shown(path: Path) -> str:
    """Repo-relative path for messages (absolute if the file is outside the repo)."""
    return str(path.relative_to(C.ROOT)) if path.is_relative_to(C.ROOT) else str(path)


def sql_files() -> list[Path]:
    return sorted(SQL_DIR.glob("[0-9][0-9]_*.sql"))


def resolve_sql_path(name: str | Path) -> Path:
    """Accept a path (relative to cwd or repo root), a file name in sql/, or a number prefix like '02'."""
    p = Path(name)
    for cand in (p, C.ROOT / p, SQL_DIR / p, SQL_DIR / f"{p}.sql"):
        if cand.is_file() and cand.suffix == ".sql":
            return cand.resolve()
    if not p.is_absolute():
        matches = sorted(SQL_DIR.glob(f"{p}_*.sql"))
        if len(matches) == 1:
            return matches[0].resolve()
    raise FileNotFoundError(f"SQL file not found: {name} (looked in sql/)")


def ensure_raw_links() -> None:
    """Make sure data/raw/ symlinks point at the configured raw files; (re)create them
    with src.data.link_raw() only when they are missing or stale."""
    wanted = {C.RAW_DIR / "marketing_AB.csv": C.MARKETING_AB_CSV,
              C.RAW_DIR / "cookie_cats.csv": C.COOKIE_CATS_CSV}
    if not all(link.exists() and link.resolve() == src.resolve() for link, src in wanted.items()):
        D.link_raw()


def run_sql_file(path: str | Path) -> pd.DataFrame:
    """Run one SQL file in a fresh in-memory DuckDB, from the repo root, and return its final SELECT."""
    path = resolve_sql_path(path)
    query = path.read_text(encoding="utf-8")
    try:
        with contextlib.chdir(C.ROOT), duckdb.connect() as con:
            rel = con.sql(query)
            if rel is None:
                raise ValueError("the file must end with a SELECT statement")
            return rel.df()
    except (duckdb.Error, ValueError) as e:
        raise RuntimeError(f"{path.name} failed: {e}") from e


def run_all() -> dict[str, pd.DataFrame]:
    files = sql_files()
    if not files:
        raise FileNotFoundError(f"No NN_*.sql files found in {SQL_DIR}")
    return {p.name: run_sql_file(p) for p in files}


# =============================================================== check collector
def _to_float(x) -> float:
    try:
        return float(x)  # bools become 0.0 / 1.0
    except (TypeError, ValueError):
        return math.nan  # None / pd.NA / missing


def _plain(x, as_count: bool = False):
    """numpy scalar -> Python scalar, so the CSV shows 564577 / True rather than np.int64(...).
    Counts that arrive as floats (e.g. a DOUBLE column) are shown as integers."""
    x = x.item() if isinstance(x, np.generic) else x
    if as_count and isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _p_from_z(z) -> np.ndarray:
    """Two-sided normal p-values for z statistics computed in SQL."""
    return 2 * sps.norm.sf(np.abs(np.asarray(z, dtype=float)))


class _Checks:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check: str, sql_file: str, sql_value, python_source: str, python_value,
            tol: float = TOL_EXACT) -> None:
        if isinstance(sql_value, str) or isinstance(python_value, str):
            ok = str(sql_value) == str(python_value)  # labels: exact text match
            diff = 0.0 if ok else math.nan
        else:
            s, p = _to_float(sql_value), _to_float(python_value)
            if math.isnan(s) and math.isnan(p):
                diff, ok = 0.0, True  # both undefined, e.g. a relative lift on a zero baseline
            else:
                diff = abs(s - p)  # NaN when only one side is missing -> no match
                ok = diff <= tol
        as_count = tol == TOL_EXACT  # exact checks are counts, flags or labels
        self.rows.append({"check": check, "sql_value": _plain(sql_value, as_count),
                          "python_value": _plain(python_value, as_count),
                          "abs_diff": diff, "match": bool(ok), "tolerance": tol,
                          "sql_file": sql_file, "python_source": python_source})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _identical_rows(sql: pd.DataFrame, py: pd.DataFrame, key: str) -> int:
    """Rows (matched on `key`) where every column of the Python table has the same value in SQL."""
    cols = [c for c in py.columns if c != key]
    if any(c not in sql.columns for c in cols):
        return 0
    m = py.merge(sql[[key, *cols]], on=key, how="inner", suffixes=("_py", "_sql"))
    same = np.ones(len(m), dtype=bool)
    for c in cols:
        a, b = m[f"{c}_py"], m[f"{c}_sql"]
        if is_numeric_dtype(a) and is_numeric_dtype(b):
            same &= a.to_numpy() == b.to_numpy()
        else:  # labels (pandas categoricals vs SQL VARCHAR)
            same &= a.astype(str).to_numpy() == b.astype(str).to_numpy()
    return int(same.sum())


# =============================================================== Python side
def load_python_side() -> dict:
    """results.json, the segment tables, and the raw + cleaned tables re-built in pandas."""
    needed = [C.RESULTS_JSON, *(C.TABLES_DIR / f"{t}.csv" for t in TABLE_KEYS)]
    missing = [_shown(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Python outputs missing: {missing}. Run `python run.py --only analysis` first.")
    m_raw, c_raw = D.load_marketing_raw(), D.load_cookie_raw()
    return {
        "res": json.loads(C.RESULTS_JSON.read_text()),
        "tables": {t: pd.read_csv(C.TABLES_DIR / f"{t}.csv", dtype={k: str}) for t, k in TABLE_KEYS.items()},
        "m_raw": m_raw,
        "m_clean": D.clean_marketing(m_raw),
        "c_raw": c_raw,
        "c_clean": D.clean_cookie(c_raw)[0],
    }


# =============================================================== one reconciler per SQL file
def _stg_marketing(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    m, dq = py["m_clean"], py["res"]["data_quality"]["marketing"]
    src = "pandas: src.data.clean_marketing(raw CSV)"
    ck.add("stg_marketing_ab: rows", f, len(sql), src, len(m))
    ck.add("stg_marketing_ab: distinct user_id", f, sql["user_id"].nunique(),
           "results.json data_quality.marketing.unique_user_id", dq["unique_user_id"])
    ck.add(f"stg_marketing_ab: rows identical to pandas on all {m.shape[1]} columns", f,
           _identical_rows(sql, m, "user_id"), src, len(m))


def _conversion(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    r, a = sql.iloc[0], py["res"]["ad"]
    t, b = a["test"], a["business"]
    hold = b["always_on_holdout_cost"]
    for check, col, key, value, tol in [
        ("users (ad)", "users_ad", "test.n_t", t["n_t"], TOL_EXACT),
        ("users (psa)", "users_psa", "test.n_c", t["n_c"], TOL_EXACT),
        ("conversions (ad)", "conversions_ad", "test.conv_t", t["conv_t"], TOL_EXACT),
        ("conversions (psa)", "conversions_psa", "test.conv_c", t["conv_c"], TOL_EXACT),
        ("conversion rate (ad)", "conversion_rate_ad", "test.rate_t", t["rate_t"], TOL_JSON),
        ("conversion rate (psa)", "conversion_rate_psa", "test.rate_c", t["rate_c"], TOL_JSON),
        ("absolute lift", "abs_lift", "test.abs_lift", t["abs_lift"], TOL_JSON),
        ("relative lift", "rel_lift", "test.rel_lift", t["rel_lift"], TOL_JSON),
        ("pooled z statistic", "z_stat", "test.z", t["z"], TOL_JSON),
        ("95% Wald CI low", "abs_lift_ci95_low", "wald_ci[0]", a["wald_ci"][0], TOL_JSON),
        ("95% Wald CI high", "abs_lift_ci95_high", "wald_ci[1]", a["wald_ci"][1], TOL_JSON),
        ("significant at 5%", "significant_at_5pct", "test.p_value < test.alpha", t["p_value"] < t["alpha"], TOL_EXACT),
        ("avg ads per user (ad)", "avg_ads_per_user_ad", "groups.ad.mean_ads", a["groups"]["ad"]["mean_ads"], TOL_JSON),
        ("avg ads per user (psa)", "avg_ads_per_user_psa", "groups.psa.mean_ads", a["groups"]["psa"]["mean_ads"], TOL_JSON),
        ("impressions (ad)", "impressions_ad", "business.impressions_ad_group", b["impressions_ad_group"], TOL_EXACT),
        ("incremental conversions", "incremental_conversions", "business.incremental_conversions.point",
         b["incremental_conversions"]["point"], TOL_JSON),
        ("incremental share of ad conversions", "incremental_share_of_ad_conversions",
         "business.share_of_ad_conversions_incremental", b["share_of_ad_conversions_incremental"], TOL_JSON),
        ("last-touch overstatement (x)", "last_touch_overstatement_x", "business.last_touch_overstatement_x",
         b["last_touch_overstatement_x"], TOL_JSON),
        ("breakeven CPM in USD (assumed value per conversion)", "breakeven_cpm_usd", "business.breakeven_cpm_usd.point",
         b["breakeven_cpm_usd"]["point"], TOL_JSON),
        ("always-on holdout: users", "holdout_users", "business.always_on_holdout_cost.users_per_588k_flight",
         hold["users_per_588k_flight"], TOL_JSON),
        ("always-on holdout: conversions forgone", "holdout_conversions_forgone",
         "business.always_on_holdout_cost.conversions_forgone", hold["conversions_forgone"], TOL_JSON),
        ("always-on holdout: value forgone in USD (assumed value per conversion)", "holdout_value_forgone_usd",
         "business.always_on_holdout_cost.value_forgone_usd", hold["value_forgone_usd"], TOL_JSON),
    ]:
        ck.add(f"ad readout: {check}", f, r[col], f"results.json ad.{key}", value, tol)


def _srm(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    rows = sql.set_index("experiment")
    for exp, srm, key in (("marketing_ab", py["res"]["ad"]["srm"], "ad.srm"),
                          ("cookie_cats", py["res"]["cookie"]["gate"]["srm"], "cookie.gate.srm")):
        r, j, lbl = rows.loc[exp], f"results.json {key}.", f"SRM {exp}"
        ck.add(f"{lbl}: n treatment", f, r["n_treatment"], j + "n_t", srm["n_t"])
        ck.add(f"{lbl}: n control", f, r["n_control"], j + "n_c", srm["n_c"])
        ck.add(f"{lbl}: intended treatment share", f, r["intended_treatment_share"], j + "intended_share_t",
               srm["intended_share_t"], TOL_JSON)
        ck.add(f"{lbl}: observed treatment share", f, r["observed_treatment_share"], j + "observed_share_t",
               srm["observed_share_t"], TOL_JSON)
        ck.add(f"{lbl}: expected treatment", f, r["expected_treatment"], j + "expected_t", srm["expected_t"], TOL_JSON)
        ck.add(f"{lbl}: chi-square statistic", f, r["chi2_stat"], j + "chi2", srm["chi2"], TOL_JSON)
        ck.add(f"{lbl}: p < 0.001", f, r["p_below_0_001"],
               j + f"p_value < threshold ({srm['threshold']})", srm["p_value"] < srm["threshold"])
        ck.add(f"{lbl}: p < 0.01", f, r["p_below_0_01"],
               j + f"p_value < warn_threshold ({srm['warn_threshold']})", srm["p_value"] < srm["warn_threshold"])
        ck.add(f"{lbl}: status", f, r["srm_status"], j + "status", srm["status"])

        # Quota exactness: results.json stores it for the ad split; for the gate split,
        # recompute it with the pipeline's function on the results.json counts.
        if "deviation_users" in srm:
            q, qsrc = srm, j
        else:
            q = S.quota_exactness(srm["n_t"], srm["n_c"], srm["intended_share_t"])
            qsrc = "src.stats.quota_exactness on the results.json counts: "
        ck.add(f"{lbl}: deviation from target (users)", f, r["deviation_users"], qsrc + "deviation_users",
               q["deviation_users"], TOL_JSON)
        ck.add(f"{lbl}: SD of the deviation under random assignment (users)", f,
               r["sd_users_under_random_assignment"], qsrc + "sd_users_under_random_assignment",
               q["sd_users_under_random_assignment"], TOL_JSON)
        ck.add(f"{lbl}: split is the nearest integer to target", f, r["is_nearest_integer_to_target"],
               qsrc + "is_nearest_integer_to_target", q["is_nearest_integer_to_target"])
        if q["is_nearest_integer_to_target"]:
            ck.add(f"{lbl}: probability random assignment lands exactly there", f,
                   r["prob_exactly_nearest_integer"], qsrc + "prob_exactly_nearest_integer",
                   q["prob_exactly_nearest_integer"], TOL_JSON)
        else:
            ck.add(f"{lbl}: probability column is NULL (split not on target)", f,
                   r["prob_exactly_nearest_integer"], "expected: NULL", None)


def _segment_lifts(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    het, alpha = py["res"]["ad"]["heterogeneity"], py["res"]["ad"]["test"]["alpha"]
    count_cols = (("users_ad", "n_t"), ("users_psa", "n_c"), ("conversions_ad", "conv_t"), ("conversions_psa", "conv_c"))
    contrast_cols = (("lift_rest", "lift_rest"), ("diff_vs_rest", "diff_vs_rest"),
                     ("diff_vs_rest_ci95_low", "diff_vs_rest_ci_low"), ("diff_vs_rest_ci95_high", "diff_vs_rest_ci_high"))
    for dim in HET_DIMS:
        table = f"ad_lift_by_{dim}"
        s, p = sql[sql["dimension"] == dim].set_index("segment"), py["tables"][table].set_index(dim)
        h, jh, lbl = het[dim], f"results.json ad.heterogeneity.{dim}.", f"lift by {dim}"
        src, common = f"reports/tables/{table}.csv", p.index.intersection(s.index)
        p_lift = pd.Series(_p_from_z(s["z_stat"]), index=s.index)
        p_rest = pd.Series(_p_from_z(s["z_vs_rest"]), index=s.index)

        # segment-level agreement with the Python table
        ck.add(f"{lbl}: segments", f, len(s), jh + "n_segments", h["n_segments"])
        ck.add(f"{lbl}: segments with identical users and conversions per arm", f,
               sum(all(s.at[k, a] == p.at[k, b] for a, b in count_cols) for k in common), src, len(p))
        ck.add(f"{lbl}: segments with matching z statistic (lift != 0)", f,
               sum(abs(s.at[k, "z_stat"] - p.at[k, "z"]) <= TOL_FULL for k in common), src, len(p))
        ck.add(f"{lbl}: segments with matching contrast vs the other segments (lift_rest, diff, CI)", f,
               sum(all(abs(s.at[k, a] - p.at[k, b]) <= TOL_FULL for a, b in contrast_cols) for k in common), src, len(p))
        ck.add(f"{lbl}: segments with matching p-value vs the other segments (from SQL z_vs_rest)", f,
               sum(abs(p_rest[k] - p.at[k, "p_vs_rest"]) <= TOL_FULL for k in common), src + " p_vs_rest", len(p))

        # decisions: unadjusted flags straight from SQL; corrected ones = SQL z -> src.stats.adjust_pvalues
        for method, name in ADJ_METHODS.items():
            if method == "none":
                n_lift = int(s["lift_significant_unadjusted"].sum())
                n_diff = int(s["differs_from_rest_unadjusted"].sum())
            else:
                n_lift = int((S.adjust_pvalues(p_lift, method) < alpha).sum())
                n_diff = int((S.adjust_pvalues(p_rest, method) < alpha).sum())
            ck.add(f"{lbl}: segments with lift != 0, {name}", f, n_lift,
                   jh + f"lift_positive.{method}", h["lift_positive"][method])
            ck.add(f"{lbl}: segments whose lift differs from the other segments, {name}", f, n_diff,
                   jh + f"differs_from_rest.{method}", h["differs_from_rest"][method])
        differs_holm = S.adjust_pvalues(p_rest, "holm") < alpha
        ck.add(f"{lbl}: segments that differ from the other segments after Holm", f,
               ", ".join(s.index[differs_holm]), jh + "segments_differing_holm", ", ".join(h["segments_differing_holm"]))

        # descriptive extremes, sparsity and the stratified sensitivity check
        ck.add(f"{lbl}: segment with the largest lift", f, str(s["abs_lift"].idxmax()), jh + "max_lift_segment",
               h["max_lift_segment"])
        ck.add(f"{lbl}: largest lift (pp)", f, s["abs_lift"].max() * 100, jh + "max_lift_pp", h["max_lift_pp"], TOL_JSON)
        ck.add(f"{lbl}: segment with the smallest lift", f, str(s["abs_lift"].idxmin()), jh + "min_lift_segment",
               h["min_lift_segment"])
        ck.add(f"{lbl}: smallest lift (pp)", f, s["abs_lift"].min() * 100, jh + "min_lift_pp", h["min_lift_pp"], TOL_JSON)
        ck.add(f"{lbl}: fewest PSA users in a segment", f, int(s["users_psa"].min()), jh + "min_control_users",
               h["min_control_users"])
        ck.add(f"{lbl}: segments with 0 PSA conversions", f, int((s["conversions_psa"] == 0).sum()),
               jh + "segments_with_zero_control_conversions", h["segments_with_zero_control_conversions"])
        ck.add(f"{lbl}: one standardized lift per dimension", f, s["standardized_lift"].nunique(),
               "expected: the same value on every row", 1)
        ck.add(f"{lbl}: standardized (Mantel-Haenszel) lift", f, s["standardized_lift"].iloc[0],
               jh + "sensitivity_stratified.mh_risk_diff", h["sensitivity_stratified"]["mh_risk_diff"], TOL_JSON)
        for k in p.index:
            ck.add(f"{lbl} = {k}: absolute lift", f, s["abs_lift"].get(k), src, p.at[k, "abs_lift"], TOL_FULL)
            ck.add(f"{lbl} = {k}: lift minus the other segments' lift", f, s["diff_vs_rest"].get(k), src,
                   p.at[k, "diff_vs_rest"], TOL_FULL)

    # daypart: the Night cell behind the daypart interaction test
    night = sql[(sql["dimension"] == "daypart") & (sql["segment"] == C.DAYPART_ORDER[0])].iloc[0]
    jn = "results.json ad.heterogeneity.daypart.night_counts."
    for arm, col_arm in (("ad", "ad"), ("psa", "psa")):
        for key, col in (("users", f"users_{col_arm}"), ("conversions", f"conversions_{col_arm}")):
            ck.add(f"daypart {C.DAYPART_ORDER[0]}: {key} ({arm})", f, night[col], jn + f"{arm}.{key}",
                   het["daypart"]["night_counts"][arm][key])

    # exposure: each arm's mix across buckets (exposure parity) and where the lift lives
    e, je = sql[sql["dimension"] == "exposure_bucket"].set_index("segment"), "results.json ad.heterogeneity.exposure_bucket."
    for bucket, share in het["exposure_bucket"]["arm_shares"].items():
        ck.add(f"exposure bucket {bucket}: share of ad users", f, e.at[bucket, "share_of_arm_ad"],
               je + f"arm_shares[{bucket}].ad", share["ad"], TOL_JSON)
        ck.add(f"exposure bucket {bucket}: share of PSA users", f, e.at[bucket, "share_of_arm_psa"],
               je + f"arm_shares[{bucket}].psa", share["psa"], TOL_JSON)
    conc, jc = het["exposure_bucket"]["concentration"], je + "concentration."
    users = e["users_ad"] + e["users_psa"]
    for check, value, key, tol in (
        ("share of users with 20 ads or fewer", users[LIGHT_BUCKETS].sum() / users.sum(), "share_users_le_20_ads", TOL_JSON),
        ("share of ad users with 36-200 ads", e.loc[HEAVY_BUCKETS, "users_ad"].sum() / e["users_ad"].sum(),
         "share_ad_users_36_200", TOL_JSON),
        ("share of incremental conversions from 36-200 ads",
         e.loc[HEAVY_BUCKETS, "incremental_conversions"].sum() / e["incremental_conversions"].sum(),
         "share_incremental_conversions_36_200", TOL_JSON),
        ("PSA conversion rate in the lowest bucket", e["conversion_rate_psa"].iloc[0], "control_rate_lowest_bucket", TOL_JSON),
        ("PSA conversion rate in the highest bucket", e["conversion_rate_psa"].iloc[-1], "control_rate_highest_bucket", TOL_JSON),
        ("PSA users in the highest bucket", e["users_psa"].iloc[-1], "top_bucket_control_users", TOL_EXACT),
    ):
        ck.add(f"exposure: {check}", f, value, jc + key, conc[key], tol)


def _stg_cookie(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    c, dq = py["c_clean"], py["res"]["data_quality"]["cookie"]
    src = "pandas: src.data.clean_cookie(raw CSV)"
    ck.add("stg_cookie_cats: rows (outlier excluded)", f, len(sql), "results.json data_quality.cookie.rows_clean",
           dq["rows_clean"])
    ck.add("stg_cookie_cats: distinct user_id", f, sql["user_id"].nunique(), src, c["user_id"].nunique())
    ck.add(f"stg_cookie_cats: rows identical to pandas on all {c.shape[1]} columns", f,
           _identical_rows(sql, c, "user_id"), src, len(c))


def _retention(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    cookie, j = py["res"]["cookie"], "results.json cookie."
    seg = sql.set_index(["dimension", "segment"])
    overall = ("overall", "All players")
    ck.add("retention overall: players", f, seg.at[overall, "players"], j + "overall.players",
           int(cookie["overall"]["players"]))
    ck.add("retention overall: D1 retention", f, seg.at[overall, "d1_retention_rate"], j + "overall.retention_1",
           cookie["overall"]["retention_1"], TOL_JSON)
    ck.add("retention overall: D7 retention", f, seg.at[overall, "d7_retention_rate"], j + "overall.retention_7",
           cookie["overall"]["retention_7"], TOL_JSON)

    for dim in ("rounds_bucket", "d1_status", "version"):
        table = f"retention_by_{dim}"
        s, p = sql[sql["dimension"] == dim].set_index("segment"), py["tables"][table].set_index(dim)
        src, common = f"reports/tables/{table}.csv", p.index.intersection(s.index)
        ck.add(f"retention by {dim}: segments with identical player counts", f,
               sum(s.at[k, "players"] == p.at[k, "players"] for k in common), src, len(p))
        for k in p.index:
            ck.add(f"retention by {dim} = {k}: D1 retention", f, s["d1_retention_rate"].get(k), src,
                   p.at[k, "retention_1"], TOL_FULL)
            ck.add(f"retention by {dim} = {k}: D7 retention", f, s["d7_retention_rate"].get(k), src,
                   p.at[k, "retention_7"], TOL_FULL)

    # The install -> Day 1 -> Day 1 and Day 7 funnel, read off the segment rows
    funnel = {step["step"]: step["players"] for step in cookie["funnel"]}
    for step, value in (
        ("Played at least 1 round", seg.at[overall, "players"] - seg.at[("rounds_bucket", "0"), "players"]),
        ("Returned on Day 1", seg.at[overall, "d1_retained"]),
        ("Returned on Day 1 and Day 7", seg.at[("d1_status", "Returned Day 1"), "d7_retained"]),
    ):
        ck.add(f"funnel: {step}", f, value, j + f"funnel[{step}].players", funnel[step])

    # D7 spread across segments, the "which dimension separates players most" headline
    for gap in cookie["gap_by_dimension"]:
        d = sql[(sql["dimension"] == gap["column"]) & (sql["players"] >= GAP_MIN_PLAYERS)]
        ck.add(f"D7 gap across {gap['column']} segments (pp)", f,
               (d["d7_retention_rate"].max() - d["d7_retention_rate"].min()) * 100,
               j + f"gap_by_dimension[{gap['column']}].gap_pp", gap["gap_pp"], TOL_JSON)


def _gate(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    gate, rows = py["res"]["cookie"]["gate"], sql.set_index("metric")
    for metric, label in (("retention_7", "D7"), ("retention_1", "D1")):
        r, g, j = rows.loc[metric], gate[metric], f"results.json cookie.gate.{metric}."
        for check, col, key, value, tol in [
            ("players gate_40", "players_gate_40", "n_t", g["n_t"], TOL_EXACT),
            ("players gate_30", "players_gate_30", "n_c", g["n_c"], TOL_EXACT),
            ("retained gate_40", "retained_gate_40", "conv_t", g["conv_t"], TOL_EXACT),
            ("retained gate_30", "retained_gate_30", "conv_c", g["conv_c"], TOL_EXACT),
            ("rate gate_40", "rate_gate_40", "rate_t", g["rate_t"], TOL_JSON),
            ("rate gate_30", "rate_gate_30", "rate_c", g["rate_c"], TOL_JSON),
            ("absolute diff (gate_40 - gate_30)", "abs_diff", "abs_lift", g["abs_lift"], TOL_JSON),
            ("relative diff", "rel_diff", "rel_lift", g["rel_lift"], TOL_JSON),
            ("pooled z statistic", "z_stat", "z", g["z"], TOL_JSON),
            ("significant at 5%", "significant_at_5pct", "p_value < alpha", g["p_value"] < g["alpha"], TOL_EXACT),
        ]:
            ck.add(f"gate {label}: {check}", f, r[col], j + key, value, tol)
        lo, hi = S.wald_diff_ci(g["conv_t"], g["n_t"], g["conv_c"], g["n_c"], alpha=C.ALPHA)
        src = "src.stats.wald_diff_ci on the results.json counts"
        ck.add(f"gate {label}: 95% Wald CI low", f, r["abs_diff_ci95_low"], src, lo, TOL_FULL)
        ck.add(f"gate {label}: 95% Wald CI high", f, r["abs_diff_ci95_high"], src, hi, TOL_FULL)


def _gate_integrity(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    gate, c = py["res"]["cookie"]["gate"], py["c_clean"]
    rows, j = sql.set_index("stratum"), "results.json cookie.gate."
    ck.add("gate integrity: rows (all players + 3 pre-gate strata)", f, len(rows), "expected", len(GATE_STRATA))

    # Step 1 - SRM by stratum, raw assignment counts
    for stratum, srm_key, _ in GATE_STRATA:
        srm, key = (gate["srm"], "srm") if srm_key is None else (gate["srm_by_stratum"][srm_key],
                                                                  f"srm_by_stratum.{srm_key}")
        r, lbl = rows.loc[stratum], f"gate integrity {stratum}"
        ck.add(f"{lbl}: assigned gate_40", f, r["assigned_gate_40"], j + f"{key}.n_t", srm["n_t"])
        ck.add(f"{lbl}: assigned gate_30", f, r["assigned_gate_30"], j + f"{key}.n_c", srm["n_c"])
        ck.add(f"{lbl}: SRM chi-square", f, r["srm_chi2"], j + f"{key}.chi2", srm["chi2"], TOL_JSON)
        ck.add(f"{lbl}: SRM status", f, r["srm_status"], j + f"{key}.status", srm["status"])
    ck.add("gate integrity: extra gate_40 players with < 15 rounds", f, rows.at["Rounds < 15", "extra_gate_40"],
           j + "excess_players_with_lt_15_rounds", gate["excess_players_with_lt_15_rounds"])

    # Step 2 - D7 by stratum and version, analysis population
    d7 = {"All players": ("retention_7", gate["retention_7"])}
    for stratum, _, nc_key in GATE_STRATA:
        if nc_key:
            d7[stratum] = (f"negative_control.{nc_key}.retention_7", gate["negative_control"][nc_key]["retention_7"])
    for stratum, (key, g) in d7.items():
        r, lbl, src = rows.loc[stratum], f"gate integrity {stratum}", j + f"{key}."
        for check, col, k, tol in (
            ("players gate_40", "players_gate_40", "n_t", TOL_EXACT),
            ("players gate_30", "players_gate_30", "n_c", TOL_EXACT),
            ("D7 retained gate_40", "d7_retained_gate_40", "conv_t", TOL_EXACT),
            ("D7 retained gate_30", "d7_retained_gate_30", "conv_c", TOL_EXACT),
            ("D7 rate gate_40", "d7_rate_gate_40", "rate_t", TOL_JSON),
            ("D7 rate gate_30", "d7_rate_gate_30", "rate_c", TOL_JSON),
            ("D7 difference", "d7_diff", "abs_lift", TOL_JSON),
            ("D7 pooled z statistic", "d7_z", "z", TOL_JSON),
        ):
            ck.add(f"{lbl}: {check}", f, r[col], src + k, g[k], tol)
        lo, hi = S.wald_diff_ci(g["conv_t"], g["n_t"], g["conv_c"], g["n_c"], alpha=C.ALPHA)
        wsrc = "src.stats.wald_diff_ci on the results.json counts"
        ck.add(f"{lbl}: D7 95% Wald CI low", f, r["d7_diff_ci95_low"], wsrc, lo, TOL_FULL)
        ck.add(f"{lbl}: D7 95% Wald CI high", f, r["d7_diff_ci95_high"], wsrc, hi, TOL_FULL)
    # the drill-down row is not in results.json: re-compute it in pandas
    low, psrc = c[c["sum_gamerounds"] < 15], "pandas: src.data.clean_cookie(raw CSV), rounds < 15"
    for arm in ("gate_40", "gate_30"):
        a = low[low["version"] == arm]
        ck.add(f"gate integrity Rounds < 15: players {arm}", f, rows.at["Rounds < 15", f"players_{arm}"], psrc, len(a))
        ck.add(f"gate integrity Rounds < 15: D7 retained {arm}", f, rows.at["Rounds < 15", f"d7_retained_{arm}"],
               psrc, int(a["retention_7"].sum()))
        ck.add(f"gate integrity Rounds < 15: share of {arm} players", f, rows.at["Rounds < 15", f"share_of_arm_{arm}"],
               psrc, len(a) / int((c["version"] == arm).sum()), TOL_FULL)

    # Step 3 - decomposition of the naive D7 gap
    dec, jd = gate["d7_decomposition"], j + "d7_decomposition."
    for stratum, _, key in GATE_STRATA:
        if key is None:
            continue
        d, r, lbl = dec["detail"][key], rows.loc[stratum], f"gate integrity {stratum}"
        for check, col, k in (("share of gate_40 players", "share_of_arm_gate_40", "w_t"),
                              ("share of gate_30 players", "share_of_arm_gate_30", "w_c"),
                              ("D7 gap within term", "d7_within_term", "within"),
                              ("D7 gap composition term", "d7_composition_term", "composition")):
            ck.add(f"{lbl}: {check}", f, r[col], jd + f"detail.{key}.{k}", d[k], TOL_JSON)
    tot, reach = rows.loc["All players"], rows.loc["Rounds >= 30"]
    ck.add("gate integrity: naive D7 gap", f, tot["d7_diff"], jd + "naive_diff", dec["naive_diff"], TOL_JSON)
    ck.add("gate integrity: D7 gap from player mix (composition)", f, tot["d7_composition_term"], jd + "composition",
           dec["composition"], TOL_JSON)
    ck.add("gate integrity: D7 gap within strata (both strata)", f, tot["d7_within_term"],
           jd + "within_never_reached_30 + within_reached_30",
           dec["within_never_reached_30"] + dec["within_reached_30"], 2 * TOL_JSON)  # sum of two rounded values
    ck.add("gate integrity: within + composition = naive D7 gap", f,
           tot["d7_within_term"] + tot["d7_composition_term"], jd + "naive_diff", dec["naive_diff"], TOL_JSON)
    ck.add("gate integrity: average share of players who reached level 30", f,
           (reach["share_of_arm_gate_40"] + reach["share_of_arm_gate_30"]) / 2, jd + "share_reached_30",
           dec["share_reached_30"], TOL_JSON)
    ck.add("gate integrity: install-level effect if only players who reach the gate are affected", f,
           reach["d7_within_term"], jd + "install_level_effect_if_only_reachers",
           dec["install_level_effect_if_only_reachers"], TOL_JSON)
    # results.json scales the Newcombe CI; the SQL scales the Wald CI -> compare with the same formula
    g = gate["negative_control"]["reached_30"]["retention_7"]
    w = (g["n_t"] / gate["players"]["gate_40"] + g["n_c"] / gate["players"]["gate_30"]) / 2
    lo, hi = S.wald_diff_ci(g["conv_t"], g["n_t"], g["conv_c"], g["n_c"], alpha=C.ALPHA)
    wsrc = "average share x src.stats.wald_diff_ci on the results.json counts"
    ck.add("gate integrity: install-level effect, 95% CI low", f, reach["d7_within_ci95_low"], wsrc, w * lo, TOL_FULL)
    ck.add("gate integrity: install-level effect, 95% CI high", f, reach["d7_within_ci95_high"], wsrc, w * hi, TOL_FULL)

    # Worst case for the SRM: gate_40's extra players all never returned
    wc, jw = gate["worst_case_bound"], j + "worst_case_bound."
    ck.add("gate integrity: extra gate_40 players (analysis population)", f,
           tot["players_gate_40"] - tot["players_gate_30"], jw + "excess_players_gate_40", wc["excess_players_gate_40"])
    ck.add("gate integrity: D7 gap if the extra gate_40 players never returned", f,
           tot["d7_diff_if_extra_never_returned"], jw + "d7_diff_if_excess_removed", wc["d7_diff_if_excess_removed"],
           TOL_JSON)


def _data_quality(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    dqm, dqc = py["res"]["data_quality"]["marketing"], py["res"]["data_quality"]["cookie"]
    m_raw, c_raw = py["m_raw"], py["c_raw"]
    jm, jc, pdx = "results.json data_quality.marketing.", "results.json data_quality.cookie.", "pandas on the raw CSV"
    zero = py["tables"]["retention_by_rounds_bucket"].set_index("rounds_bucket").loc["0"]
    jz = "reports/tables/retention_by_rounds_bucket.csv: players x "
    observed = sql.set_index(["dataset", "check_name"])["observed_value"]
    expected = [
        ("marketing_ab", "rows", jm + "rows_raw", dqm["rows_raw"], TOL_EXACT),
        ("marketing_ab", "duplicate_user_id", jm + "duplicate_user_id", dqm["duplicate_user_id"], TOL_EXACT),
        ("marketing_ab", "null_cells", jm + "nulls (sum over the 6 data columns)",
         sum(v for k, v in dqm["nulls"].items() if not k.startswith("Unnamed")), TOL_EXACT),
        ("marketing_ab", "invalid_test_group", pdx, int((~m_raw["test group"].isin(["ad", "psa"])).sum()), TOL_EXACT),
        ("marketing_ab", "invalid_most_ads_day", pdx, int((~m_raw["most ads day"].isin(C.DAY_ORDER)).sum()), TOL_EXACT),
        ("marketing_ab", "invalid_most_ads_hour", pdx, int((~m_raw["most ads hour"].between(0, 23)).sum()), TOL_EXACT),
        ("marketing_ab", "total_ads_min", jm + "total_ads_min", dqm["total_ads_min"], TOL_EXACT),
        ("marketing_ab", "total_ads_median", jm + "total_ads_p50", dqm["total_ads_p50"], TOL_JSON),
        ("marketing_ab", "total_ads_p99", jm + "total_ads_p99", dqm["total_ads_p99"], TOL_JSON),
        ("marketing_ab", "total_ads_p999", jm + "total_ads_p999", dqm["total_ads_p999"], TOL_JSON),
        ("marketing_ab", "total_ads_max", jm + "total_ads_max", dqm["total_ads_max"], TOL_EXACT),
        ("marketing_ab", "users_over_1000_ads", jm + "users_over_1000_ads", dqm["users_over_1000_ads"], TOL_EXACT),
        ("cookie_cats", "rows", jc + "rows_raw", dqc["rows_raw"], TOL_EXACT),
        ("cookie_cats", "duplicate_user_id", jc + "duplicate_user_id", dqc["duplicate_user_id"], TOL_EXACT),
        ("cookie_cats", "null_cells", jc + "nulls (sum over all columns)", sum(dqc["nulls"].values()), TOL_EXACT),
        ("cookie_cats", "invalid_version", pdx, int((~c_raw["version"].isin(["gate_30", "gate_40"])).sum()), TOL_EXACT),
        ("cookie_cats", "sum_gamerounds_min", jc + "rounds_min", dqc["rounds_min"], TOL_EXACT),
        ("cookie_cats", "sum_gamerounds_median", jc + "rounds_p50", dqc["rounds_p50"], TOL_JSON),
        ("cookie_cats", "sum_gamerounds_p99", jc + "rounds_p99", dqc["rounds_p99"], TOL_JSON),
        ("cookie_cats", "sum_gamerounds_p999", jc + "rounds_p999", dqc["rounds_p999"], TOL_JSON),
        ("cookie_cats", "sum_gamerounds_max", jc + "rounds_max_raw", dqc["rounds_max_raw"], TOL_EXACT),
        ("cookie_cats", "zero_round_players", jc + "zero_round_players", dqc["zero_round_players"], TOL_EXACT),
        ("cookie_cats", "zero_round_players_flagged_d1", jz + "retention_1 (bucket 0)",
         int(round(zero["players"] * zero["retention_1"])), TOL_EXACT),
        ("cookie_cats", "zero_round_players_flagged_d7", jz + "retention_7 (bucket 0)",
         int(round(zero["players"] * zero["retention_7"])), TOL_EXACT),
        ("cookie_cats", "players_over_10000_rounds", jc + "outliers_dropped (count)", len(dqc["outliers_dropped"]),
         TOL_EXACT),
        ("cookie_cats", "rows_after_outlier_exclusion", jc + "rows_clean", dqc["rows_clean"], TOL_EXACT),
        ("cookie_cats", "sum_gamerounds_max_after_exclusion", jc + "rounds_max_clean", dqc["rounds_max_clean"],
         TOL_EXACT),
        ("cookie_cats", "d1_retention_all_rows", jc + "retention_raw.d1", dqc["retention_raw"]["d1"], TOL_JSON),
        ("cookie_cats", "d1_retention_after_exclusion", jc + "retention_clean.d1", dqc["retention_clean"]["d1"], TOL_JSON),
        ("cookie_cats", "d7_retention_all_rows", jc + "retention_raw.d7", dqc["retention_raw"]["d7"], TOL_JSON),
        ("cookie_cats", "d7_retention_after_exclusion", jc + "retention_clean.d7", dqc["retention_clean"]["d7"], TOL_JSON),
        ("cookie_cats", "mean_rounds_all_rows", jc + "mean_rounds_raw", dqc["mean_rounds_raw"], TOL_JSON),
        ("cookie_cats", "mean_rounds_after_exclusion", jc + "mean_rounds_clean", dqc["mean_rounds_clean"], TOL_JSON),
        ("cookie_cats", "d7_without_d1", jc + "d7_without_d1", dqc["d7_without_d1"], TOL_EXACT),
    ]
    for dataset, name, src, value, tol in expected:
        ck.add(f"DQ {dataset}: {name}", f, observed.get((dataset, name)), src, value, tol)
    ck.add("DQ: checks with status FAIL", f, int((sql["status"] == "FAIL").sum()),
           "expected: every hard DQ rule passes", 0)


RECONCILERS: dict[str, Callable[[_Checks, str, pd.DataFrame, dict], None]] = {
    "01_stg_marketing_ab.sql": _stg_marketing,
    "02_conversion_by_group.sql": _conversion,
    "03_srm_check.sql": _srm,
    "04_lift_by_day_and_hour.sql": _segment_lifts,
    "05_stg_cookie_cats.sql": _stg_cookie,
    "06_retention_by_segment.sql": _retention,
    "07_gate_experiment.sql": _gate,
    "08_data_quality_checks.sql": _data_quality,
    "09_gate_integrity.sql": _gate_integrity,
}


def reconcile(outputs: dict[str, pd.DataFrame], py: dict) -> pd.DataFrame:
    missing = [name for name in RECONCILERS if name not in outputs]
    if missing:
        raise ReconciliationError(f"SQL file(s) expected in sql/ but not found: {missing}")
    unchecked = [name for name in outputs if name not in RECONCILERS]
    if unchecked:
        raise ReconciliationError(f"SQL file(s) without a reconciler in src/sql_check.py: {unchecked}")
    ck = _Checks()
    for name, check_file in RECONCILERS.items():
        try:
            check_file(ck, name, outputs[name], py)
        except KeyError as e:
            raise ReconciliationError(f"{name}: output is missing an expected column or row: {e}") from e
    return ck.frame()


# =============================================================== entry points
def run_and_reconcile(verbose: bool = True) -> pd.DataFrame:
    """Run every sql/*.sql file, reconcile with the Python pipeline, write
    reports/tables/sql_reconciliation.csv. Raises ReconciliationError on any mismatch."""
    ensure_raw_links()
    t0 = time.time()
    outputs = run_all()
    seconds = time.time() - t0
    table = reconcile(outputs, load_python_side())
    C.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(RECON_CSV, index=False)

    n, n_ok = len(table), int(table["match"].sum())
    out_path = _shown(RECON_CSV)
    if verbose:
        print(f"[sql] {len(outputs)} SQL files ran in {seconds:.1f}s; "
              f"{n_ok}/{n} reconciliation checks match -> {out_path}")
    if n_ok < n:
        failed = table.loc[~table["match"], "check"].tolist()
        raise ReconciliationError(f"{n - n_ok} of {n} SQL reconciliation checks failed "
                                  f"(first: {failed[:5]}); see {out_path}")
    return table


def preview(name: str | Path, max_rows: int = 40) -> None:
    """Print one SQL file's result: one line per column when there are only a few
    rows (e.g. one per experiment or stratum), a table otherwise."""
    path = resolve_sql_path(name)
    df = run_sql_file(path)
    print(f"-- {_shown(path)}: {len(df):,} rows x {df.shape[1]} columns")
    with pd.option_context("display.width", 250):
        if len(df) == 1:
            print(df.T.to_string(header=False, max_colwidth=90))
        elif len(df) <= 6:
            print(df.set_index(df.columns[0]).T.to_string(max_colwidth=90))
        else:
            print(df.to_string(max_rows=max_rows, index=False, max_colwidth=40))
    print()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="python -m src.sql_check",
        description="Run sql/*.sql in DuckDB. Without arguments: run every file and reconcile the "
                    "results with reports/results.json (writes reports/tables/sql_reconciliation.csv).")
    ap.add_argument("files", nargs="*",
                    help="SQL file(s) to run and print instead, e.g. sql/02_conversion_by_group.sql or 02")
    ap.add_argument("--max-rows", type=int, default=40, help="rows to print per file (print mode)")
    args = ap.parse_args(argv)
    if args.files:
        ensure_raw_links()
        for name in args.files:
            preview(name, args.max_rows)
        return
    try:
        run_and_reconcile()
    except ReconciliationError as e:
        raise SystemExit(f"[sql] FAILED: {e}") from e


if __name__ == "__main__":
    main()
