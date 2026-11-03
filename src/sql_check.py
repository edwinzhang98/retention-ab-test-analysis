"""Run the DuckDB SQL in sql/ and reconcile it with the Python pipeline.

Every sql/NN_*.sql file is self-contained: it reads the raw CSVs through the
repo-relative symlinks in data/raw/ and ends in a single SELECT. This module runs
each file in a fresh in-memory DuckDB connection with the repo root as working
directory (so no file can silently depend on another), then compares the key
outputs with reports/results.json, reports/tables/*.csv and a pandas
re-computation from src.data. SQL and pandas are two independent implementations
of the same metric definitions, so agreement is evidence that both are right.

Output
  reports/tables/sql_reconciliation.csv, one row per check:
    check, sql_value, python_value, abs_diff, match, tolerance, sql_file, python_source
  Raises ReconciliationError (after writing the CSV) if any check fails.

Usage, from the repo root
  python -m src.sql_check                                  run every file + reconcile
  python -m src.sql_check sql/02_conversion_by_group.sql   run one file and print its result
  python -m src.sql_check 02 07                            same, by number prefix
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
    "ad_lift_by_exposure_bucket": "exposure_bucket",
    "retention_by_rounds_bucket": "rounds_bucket",
    "retention_by_d1_status": "d1_status",
    "retention_by_version": "version",
}
# Same minimum segment size as src.retention.gap_by_dimension
GAP_MIN_PLAYERS = 500


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


class _Checks:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check: str, sql_file: str, sql_value, python_source: str, python_value,
            tol: float = TOL_EXACT) -> None:
        s, p = _to_float(sql_value), _to_float(python_value)
        if math.isnan(s) and math.isnan(p):
            diff, ok = 0.0, True  # both undefined, e.g. a relative lift on a zero baseline
        else:
            diff = abs(s - p)  # NaN when only one side is missing -> no match
            ok = diff <= tol
        as_count = tol == TOL_EXACT  # exact checks are counts or flags
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
        ("breakeven CPM in USD (assumed value per conversion)", "breakeven_cpm_usd", "business.breakeven_cpm_usd.point",
         b["breakeven_cpm_usd"]["point"], TOL_JSON),
    ]:
        ck.add(f"ad readout: {check}", f, r[col], f"results.json ad.{key}", value, tol)


def _srm(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    rows = sql.set_index("experiment")
    for exp, srm, key in (("marketing_ab", py["res"]["ad"]["srm"], "ad.srm"),
                          ("cookie_cats", py["res"]["cookie"]["gate"]["srm"], "cookie.gate.srm")):
        r, j = rows.loc[exp], f"results.json {key}."
        ck.add(f"SRM {exp}: n treatment", f, r["n_treatment"], j + "n_t", srm["n_t"])
        ck.add(f"SRM {exp}: n control", f, r["n_control"], j + "n_c", srm["n_c"])
        ck.add(f"SRM {exp}: intended treatment share", f, r["intended_treatment_share"], j + "intended_share_t",
               srm["intended_share_t"], TOL_JSON)
        ck.add(f"SRM {exp}: expected treatment", f, r["expected_treatment"], j + "expected_t", srm["expected_t"], TOL_JSON)
        ck.add(f"SRM {exp}: chi-square statistic", f, r["chi2_stat"], j + "chi2", srm["chi2"], TOL_JSON)
        ck.add(f"SRM {exp}: flag (p < 0.001)", f, r["srm_flag_p_lt_0_001"],
               j + f"flag (threshold {srm['threshold']})", srm["flag"])
        warn = srm.get("warn_threshold", 0.01)  # older results.json files have no warn_threshold
        ck.add(f"SRM {exp}: warning (p < 0.01)", f, r["srm_warning_p_lt_0_01"],
               j + f"p_value < warn_threshold ({warn})", srm["p_value"] < warn)


def _segment_lifts(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    het = py["res"]["ad"]["heterogeneity"]
    count_cols = (("users_ad", "n_t"), ("users_psa", "n_c"), ("conversions_ad", "conv_t"), ("conversions_psa", "conv_c"))
    for dim in ("most_ads_day", "most_ads_hour", "exposure_bucket"):
        table = f"ad_lift_by_{dim}"
        s, p = sql[sql["dimension"] == dim].set_index("segment"), py["tables"][table].set_index(dim)
        src, common = f"reports/tables/{table}.csv", p.index.intersection(s.index)
        same_counts = sum(all(s.at[k, a] == p.at[k, b] for a, b in count_cols) for k in common)
        same_z = sum(abs(s.at[k, "z_stat"] - p.at[k, "z"]) <= TOL_FULL for k in common)
        ck.add(f"lift by {dim}: segments", f, len(s), src, len(p))
        ck.add(f"lift by {dim}: segments with identical users and conversions per arm", f, same_counts, src, len(p))
        ck.add(f"lift by {dim}: segments with matching z statistic", f, same_z, src, len(p))
        ck.add(f"lift by {dim}: segments significant at 5% before correction", f,
               int(s["significant_unadjusted"].sum()), f"results.json ad.heterogeneity.{dim}.n_sig_unadjusted",
               het[dim]["n_sig_unadjusted"])
        for k in p.index:
            ck.add(f"lift by {dim} = {k}: absolute lift", f, s["abs_lift"].get(k), src, p.at[k, "abs_lift"], TOL_FULL)


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


def _data_quality(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    dqm, dqc = py["res"]["data_quality"]["marketing"], py["res"]["data_quality"]["cookie"]
    m_raw, c_raw = py["m_raw"], py["c_raw"]
    jm, jc, pdx = "results.json data_quality.marketing.", "results.json data_quality.cookie.", "pandas on the raw CSV"
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
}


def reconcile(outputs: dict[str, pd.DataFrame], py: dict) -> pd.DataFrame:
    missing = [name for name in RECONCILERS if name not in outputs]
    if missing:
        raise ReconciliationError(f"SQL file(s) expected in sql/ but not found: {missing}")
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
    """Print one SQL file's result: one line per column for 1-3 row results, a table otherwise."""
    path = resolve_sql_path(name)
    df = run_sql_file(path)
    print(f"-- {_shown(path)}: {len(df):,} rows x {df.shape[1]} columns")
    if len(df) == 1:
        print(df.T.to_string(header=False))
    elif len(df) <= 3:
        print(df.set_index(df.columns[0]).T.to_string())
    else:
        print(df.to_string(max_rows=max_rows, index=False))
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
