"""Run the DuckDB SQL in sql/ and reconcile it with the Python pipeline.

Every sql/NN_*.sql file is self-contained: it reads the raw CSVs through the
repo-relative symlinks in data/raw/ and ends in a single SELECT. This module runs
each file in a fresh in-memory DuckDB connection with the repo root as working
directory (so no file can silently depend on another), then compares the key
outputs with reports/results.json, reports/tables/*.csv and a pandas
re-computation from src.data. SQL and pandas are two independent implementations
of the same metric definitions, so agreement is evidence that both are right.

DuckDB has no normal or chi-square CDF, so the SQL stops at test statistics. This
module turns the SQL z statistics into two-sided p-values: for the heterogeneity
decisions it then applies the same multiple-comparison corrections as the pipeline
(src.stats) and checks that the resulting counts match results.json; for the gate
integrity checks (sql/09) it compares the p-values with results.json directly.

Output
  reports/tables/sql_reconciliation.csv, one row per check:
    check, sql_value, python_value, abs_diff, match, tolerance, sql_file, python_source
  Numbers must agree within the tolerance; labels (statuses, segment names, row
  keys) must agree exactly. Raises ReconciliationError (after writing the CSV) if any
  check fails, and before that if a SQL file has no reconciler or a reconciled file
  is missing.
  The file is byte-identical from run to run. Each SQL file runs single-threaded:
  with several threads DuckDB may add floating-point values (e.g. a window SUM over
  segments) in a different order on each run, which moves the last digits of the
  result. The CSV also stores sql_value to 12 significant digits and abs_diff to 3;
  match is decided at full precision, before that rounding.

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

# Tolerances. results.json stores floats rounded to 8 decimals (src.analysis._r),
# so a value read from it can differ from the full-precision SQL value by up to
# half a unit in the 8th decimal. Values below 1e-4 in size are stored with 3
# significant digits instead, so for them TOL_JSON widens to 0.5% of the value
# (_json_tol). reports/tables/*.csv and pandas re-computations are full precision.
# Counts, flags and labels must match exactly.
TOL_EXACT = 0.0
TOL_JSON = 5e-9 + 1e-12
TOL_FULL = 1e-9
# Significant digits written to reports/tables/sql_reconciliation.csv (match is decided before rounding)
CSV_SIG_DIGITS = {"sql_value": 12, "abs_diff": 3}

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
# Rounds buckets that make up the early-churn segment (< 15 rounds), as in src.analysis.cookie_analysis
EARLY_CHURN_BUCKETS = ["0", "1-4", "5-14"]

# sql/03_srm_check.sql 'reading' for each SRM outcome (a quota-exact split overrides the status)
SRM_READINGS = {
    "quota": "uninformative: split exactly on target, most likely a quota; check exposure parity",
    "FAIL": "stop: debug assignment before reading any result",
    "WARNING": "do not certify the readout until the mismatch is explained",
    "PASS": "consistent with the intended split",
}

# sql/08_data_quality_checks.sql: the DQ log's status words (docs/03_data_quality_checks.md), and the
# checks whose rule is 'WARNING if > 0'
DQ_STATUS_WORDS = ("PASS", "WARNING", "FAIL", "INFO")
DQ_WARNING_IF_POSITIVE = (("cookie_cats", "zero_round_players_flagged_d1"),
                          ("cookie_cats", "zero_round_players_flagged_d7"),
                          ("cookie_cats", "players_over_10000_rounds"))

# sql/09_gate_integrity.sql. Rounds bands: (population, key in cookie.gate.srm_by_stratum (None = the
# overall srm), paths in cookie.gate to the band's two-proportion results by version). 'Rounds >= 30' is
# stored twice in results.json, so both copies are checked.
GATE_BANDS = (
    ("All players", None, ((),)),
    ("Rounds < 15", "rounds_lt_15", (("retention_by_rounds_band", "rounds_lt_15"),)),
    ("Rounds 15-29", "rounds_15_29", (("retention_by_rounds_band", "rounds_15_29"),)),
    ("Rounds < 30", "rounds_lt_30", (("negative_control", "never_reached_30"),)),
    ("Rounds >= 30", "rounds_ge_30", (("retention_by_rounds_band", "rounds_ge_30"),
                                      ("negative_control", "reached_30"))),
)
# Edge-check bands (retention rows only, not in step 1): 'Rounds 15-29' split at 29 rounds, where a flawless
# gate_30 player can already face the gate. (population, key in cookie.gate.retention_by_rounds_band)
GATE_EDGE_BANDS = (("Rounds 15-28", "rounds_15_28"), ("Rounds 29", "rounds_29"))
# The two bands that split every player once (decomposition), with their key in *_decomposition.detail
GATE_PARTITION = (("Rounds < 30", "never_reached_30"), ("Rounds >= 30", "reached_30"))
# Drill-down and edge-check bands inside rounds < 30, with their inclusive round bounds (for the pandas share check)
GATE_DRILL_DOWN = (("Rounds < 15", 0, 14), ("Rounds 15-29", 15, 29), ("Rounds 15-28", 15, 28), ("Rounds 29", 29, 29))
# The band-gap difference row of sql/09 (step 2): the 15-29 band's D7 gap minus the < 15 band's
GATE_GAP_DIFF = ("retention", "Rounds 15-29 minus Rounds < 15", "D7 gap difference")
# Every row of sql/09_gate_integrity.sql in output order: (section, population, measure)
GATE_ROWS = (
    *(("assignment", band, "assigned players") for band, _, _ in GATE_BANDS),
    *(("retention", band, "D7") for band in ("All players", "Rounds < 15", "Rounds 15-29")),
    GATE_GAP_DIFF,
    *(("retention", band, "D7") for band in ("Rounds 15-28", "Rounds 29", "Rounds < 30")),
    ("retention", "Rounds < 30, net excess removed", "D7"),
    ("retention", "Rounds >= 30", "D7"),
    *(("retention", band, "D1") for band in ("All players", "Rounds < 15", "Rounds 15-29", "Rounds 15-28", "Rounds 29",
                                             "Rounds < 30", "Rounds >= 30")),
    ("best case for gate_40", "All players, extra installs removed", "D7"),
    ("play", "All players", "pre-gate rounds (capped at 29), mean"),
    ("play", "Rounds >= 30", "rounds, median"),
    ("play", "Rounds >= 30", "rounds, mean"),
    ("play", "Rounds >= 30", "share with 40+ rounds"),
    *(("re-test sizing", band, f"D7 {direction} to detect") for band in ("All players", "Rounds >= 30")
      for direction in ("drop", "rise")),
)
# A two-proportion row of sql/09 vs a src.stats.two_prop_test result in results.json:
# (check, SQL column, results.json key, tolerance). The p-value is checked separately (from z_stat).
GATE_TWO_PROP = (
    ("players gate_40", "n_gate_40", "n_t", TOL_EXACT),
    ("players gate_30", "n_gate_30", "n_c", TOL_EXACT),
    ("with the outcome gate_40", "k_gate_40", "conv_t", TOL_EXACT),
    ("with the outcome gate_30", "k_gate_30", "conv_c", TOL_EXACT),
    ("rate gate_40", "value_gate_40", "rate_t", TOL_JSON),
    ("rate gate_30", "value_gate_30", "rate_c", TOL_JSON),
    ("difference (gate_40 - gate_30)", "difference", "abs_lift", TOL_JSON),
    ("pooled z statistic", "z_stat", "z", TOL_JSON),
    ("95% CI low (Newcombe)", "ci95_low", "abs_ci_low", TOL_JSON),
    ("95% CI high (Newcombe)", "ci95_high", "abs_ci_high", TOL_JSON),
)
# SRM status words that must never label the post-hoc rounds bands in sql/09
SRM_STATUS_WORDS = ("PASS", "WARNING", "FAIL")


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
    """Run one SQL file in a fresh in-memory DuckDB, from the repo root, and return its final SELECT.
    Single-threaded, so floating-point sums are added in the same order on every run (see Output)."""
    path = resolve_sql_path(path)
    query = path.read_text(encoding="utf-8")
    try:
        with contextlib.chdir(C.ROOT), duckdb.connect(config={"threads": 1}) as con:
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


def _p1(z) -> float:
    """Two-sided normal p-value for one SQL z statistic."""
    return float(_p_from_z(z))


def _json_tol(value) -> float:
    """TOL_JSON for one results.json value: src.analysis._r keeps values below 1e-4 in size
    to 3 significant digits instead of 8 decimals, a rounding error of up to 0.5% of the value."""
    v = abs(_to_float(value))
    return max(TOL_JSON, 0.005 * v) if 0 < v <= 1e-4 else TOL_JSON


def _dig(d: dict, path: str):
    """d['a']['b'] for path 'a.b'."""
    for k in path.split("."):
        d = d[k]
    return d


class _Checks:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check: str, sql_file: str, sql_value, python_source: str, python_value,
            tol: float = TOL_EXACT) -> None:
        if tol == TOL_JSON:
            tol = _json_tol(python_value)
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


def _round_sig(x, digits: int):
    """A finite non-zero float rounded to `digits` significant digits; any other value unchanged."""
    if isinstance(x, float) and math.isfinite(x) and x != 0:
        return float(f"{x:.{digits}g}")
    return x


def _csv_view(table: pd.DataFrame) -> pd.DataFrame:
    """The reconciliation table as written to CSV: CSV_SIG_DIGITS applied to the numeric display columns."""
    out = table.copy()
    for col, digits in CSV_SIG_DIGITS.items():
        out[col] = out[col].map(lambda x: _round_sig(x, digits))
    return out


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
        ("relative lift 95% CI low (log risk ratio)", "rel_lift_ci95_low", "test.rel_ci_low", t["rel_ci_low"], TOL_JSON),
        ("relative lift 95% CI high (log risk ratio)", "rel_lift_ci95_high", "test.rel_ci_high", t["rel_ci_high"],
         TOL_JSON),
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
        ("incremental share, 95% CI low", "incremental_share_ci95_low",
         "business.share_of_ad_conversions_incremental_ci[0]", b["share_of_ad_conversions_incremental_ci"][0], TOL_JSON),
        ("incremental share, 95% CI high", "incremental_share_ci95_high",
         "business.share_of_ad_conversions_incremental_ci[1]", b["share_of_ad_conversions_incremental_ci"][1], TOL_JSON),
        ("last-touch overstatement (x)", "last_touch_overstatement_x", "business.last_touch_overstatement_x",
         b["last_touch_overstatement_x"], TOL_JSON),
        ("last-touch overstatement, 95% CI low (x)", "last_touch_overstatement_ci95_low",
         "business.last_touch_overstatement_ci[0]", b["last_touch_overstatement_ci"][0], TOL_JSON),
        ("last-touch overstatement, 95% CI high (x)", "last_touch_overstatement_ci95_high",
         "business.last_touch_overstatement_ci[1]", b["last_touch_overstatement_ci"][1], TOL_JSON),
        ("breakeven CPM in USD (assumed value per conversion)", "breakeven_cpm_usd", "business.breakeven_cpm_usd.point",
         b["breakeven_cpm_usd"]["point"], TOL_JSON),
        ("always-on holdout: users", "holdout_users", "business.always_on_holdout_cost.users_per_588k_flight",
         hold["users_per_588k_flight"], TOL_JSON),
        ("always-on holdout: conversions forgone", "holdout_conversions_forgone",
         "business.always_on_holdout_cost.conversions_forgone", hold["conversions_forgone"], TOL_JSON),
        ("always-on holdout: value forgone in USD (assumed value per conversion)", "holdout_value_forgone_usd",
         "business.always_on_holdout_cost.value_forgone_usd", hold["value_forgone_usd"], TOL_JSON),
        ("always-on holdout: PSA share as run", "as_run_control_share",
         "business.always_on_holdout_cost.as_run_control_share", hold["as_run_control_share"], TOL_JSON),
        ("always-on holdout: conversions the as-run PSA arm forgoes", "as_run_conversions_forgone",
         "business.always_on_holdout_cost.as_run_control_conversions_forgone",
         hold["as_run_control_conversions_forgone"], TOL_JSON),
        ("always-on holdout: extra conversions forgone vs the as-run PSA arm", "holdout_extra_conversions_vs_as_run",
         "business.always_on_holdout_cost.extra_conversions_vs_as_run", hold["extra_conversions_vs_as_run"], TOL_JSON),
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
        # the reading: a quota-exact split makes the test uninformative, whatever its status
        ck.add(f"{lbl}: reading", f, r["reading"], qsrc + "is_nearest_integer_to_target, else " + j + "status",
               SRM_READINGS["quota" if q["is_nearest_integer_to_target"] else srm["status"]])


def _segment_lifts(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    het, alpha = py["res"]["ad"]["heterogeneity"], py["res"]["ad"]["test"]["alpha"]
    count_cols = (("users_ad", "n_t"), ("users_psa", "n_c"), ("conversions_ad", "conv_t"), ("conversions_psa", "conv_c"))
    contrast_cols = (("lift_rest", "lift_rest"), ("diff_vs_rest", "diff_vs_rest"), ("diff_vs_rest_ac", "diff_vs_rest_ac"),
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
        ck.add(f"{lbl}: segments with matching contrast vs the other segments (lift_rest, raw diff, "
               "Agresti-Caffo diff, CI)", f,
               sum(all(abs(s.at[k, a] - p.at[k, b]) <= TOL_FULL for a, b in contrast_cols) for k in common), src, len(p))
        # the point estimate is raw; the CI is Agresti-Caffo, so it is centred on the adjusted difference
        # (diff_vs_rest_ac, checked against the table's own column below and against the CI's midpoint here)
        ck.add(f"{lbl}: segments whose CI is centred on the Agresti-Caffo difference (SQL diff_vs_rest_ac)", f,
               sum(abs(s.at[k, "diff_vs_rest_ac"] - (p.at[k, "diff_vs_rest_ci_low"] + p.at[k, "diff_vs_rest_ci_high"]) / 2)
                   <= TOL_FULL for k in common), src + " (diff_vs_rest_ci_low + diff_vs_rest_ci_high) / 2", len(p))
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
            ck.add(f"{lbl} = {k}: lift minus the other segments' lift (raw)", f, s["diff_vs_rest"].get(k), src,
                   p.at[k, "diff_vs_rest"], TOL_FULL)
            ck.add(f"{lbl} = {k}: the same on Agresti-Caffo adjusted proportions (CI centre, diff_vs_rest_ac)", f,
                   s["diff_vs_rest_ac"].get(k), src, p.at[k, "diff_vs_rest_ac"], TOL_FULL)

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
        ("share of ad users with 20 ads or fewer", e.loc[LIGHT_BUCKETS, "users_ad"].sum() / e["users_ad"].sum(),
         "share_ad_users_le_20_ads", TOL_JSON),
        ("share of ad users with 36-200 ads", e.loc[HEAVY_BUCKETS, "users_ad"].sum() / e["users_ad"].sum(),
         "share_ad_users_36_200", TOL_JSON),
        ("bucket-by-bucket incremental conversions, all buckets", e["incremental_conversions"].sum(),
         "incremental_conversions_bucketwise_total", TOL_JSON),
        ("bucket-by-bucket incremental conversions, 36-200 ads", e.loc[HEAVY_BUCKETS, "incremental_conversions"].sum(),
         "incremental_conversions_36_200", TOL_JSON),
        ("share of incremental conversions from 36-200 ads",
         e.loc[HEAVY_BUCKETS, "incremental_conversions"].sum() / e["incremental_conversions"].sum(),
         "share_incremental_conversions_36_200", TOL_JSON),
        ("share of ad users with 21-35 ads", e.at["21-35", "share_of_arm_ad"], "bucket_21_35.share_ad_users", TOL_JSON),
        ("lift with 21-35 ads", e.at["21-35", "abs_lift"], "bucket_21_35.abs_lift", TOL_JSON),
        ("PSA conversion rate in the lowest bucket", e["conversion_rate_psa"].iloc[0], "control_rate_lowest_bucket", TOL_JSON),
        ("PSA conversion rate in the highest bucket", e["conversion_rate_psa"].iloc[-1], "control_rate_highest_bucket", TOL_JSON),
        ("PSA users in the highest bucket", e["users_psa"].iloc[-1], "top_bucket_control_users", TOL_EXACT),
    ):
        ck.add(f"exposure: {check}", f, value, jc + key, _dig(conc, key), tol)
    # Each bucket against its own PSA rate: the bucket-by-bucket incremental conversions
    for bucket, value in conc["incremental_conversions_by_bucket"].items():
        ck.add(f"exposure bucket {bucket}: incremental conversions (bucket's own PSA rate)", f,
               e.at[bucket, "incremental_conversions"], jc + f"incremental_conversions_by_bucket[{bucket}]", value, TOL_JSON)
    # 20 ads or fewer, pooled: the SQL bucket counts must add up to the pandas filter total_ads <= 20.
    # The pooled test, its CI and its MDE are Python-only (src.stats.two_prop_test / mde).
    light, le20, jl = e.loc[LIGHT_BUCKETS], conc["le_20_ads_pooled"], jc + "le_20_ads_pooled."
    n_t, n_c = light["users_ad"].sum(), light["users_psa"].sum()
    k_t, k_c = light["conversions_ad"].sum(), light["conversions_psa"].sum()
    for check, value, key, tol in (
        ("users (ad)", n_t, "n_t", TOL_EXACT),
        ("users (psa)", n_c, "n_c", TOL_EXACT),
        ("conversions (ad)", k_t, "conv_t", TOL_EXACT),
        ("conversions (psa)", k_c, "conv_c", TOL_EXACT),
        ("conversion rate (ad)", k_t / n_t, "rate_t", TOL_JSON),
        ("conversion rate (psa)", k_c / n_c, "rate_c", TOL_JSON),
        ("lift", k_t / n_t - k_c / n_c, "abs_lift", TOL_JSON),
    ):
        ck.add(f"exposure 20 ads or fewer (SQL buckets {', '.join(LIGHT_BUCKETS)} pooled): {check}", f, value,
               jl + key, le20[key], tol)


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

    # The early-churn segment (R6 target): players with < 15 rounds = the SQL buckets 0, 1-4 and 5-14.
    # Its re-engagement test sizing is Python-only (src.stats.required_total_n).
    early, je = cookie["early_churn_segment"], j + "early_churn_segment."
    low = seg.loc["rounds_bucket"].loc[EARLY_CHURN_BUCKETS]
    players = low["players"].sum()
    for check, value, key, tol in (
        ("players", players, "players", TOL_EXACT),
        ("share of installs", players / seg.at[overall, "players"], "share_of_installs", TOL_JSON),
        ("players back on Day 7", low["d7_retained"].sum(), "d7_players", TOL_EXACT),
        ("D7 retention", low["d7_retained"].sum() / players, "retention_7", TOL_JSON),
        ("D1 retention", low["d1_retained"].sum() / players, "retention_1", TOL_JSON),
        ("highest D7 retention in one of its buckets", low["d7_retention_rate"].max(), "max_bucket_retention_7", TOL_JSON),
        ("D7 of players who returned on Day 1 (all players)", seg.at[("d1_status", "Returned Day 1"), "d7_retention_rate"],
         "d7_if_returned_day1", TOL_JSON),
        ("D7 of players who did not return on Day 1 (all players)",
         seg.at[("d1_status", "Did not return Day 1"), "d7_retention_rate"], "d7_if_not_returned_day1", TOL_JSON),
    ):
        ck.add(f"early-churn segment (< 15 rounds = buckets {', '.join(EARLY_CHURN_BUCKETS)}): {check}", f, value,
               je + key, early[key], tol)


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


def _gate_two_prop(ck: _Checks, f: str, lbl: str, r: pd.Series, res: dict, src: str) -> None:
    """One two-proportion row of sql/09 vs a src.stats.two_prop_test result in results.json."""
    for check, col, key, tol in GATE_TWO_PROP:
        ck.add(f"{lbl}: {check}", f, r[col], src + key, res[key], tol)
    ck.add(f"{lbl}: p-value (two-sided, from the SQL z)", f, _p1(r["z_stat"]), src + "p_value", res["p_value"], TOL_JSON)


def _gate_integrity(ck: _Checks, f: str, sql: pd.DataFrame, py: dict) -> None:
    gate, c, j = py["res"]["cookie"]["gate"], py["c_clean"], "results.json cookie.gate."
    keys = list(zip(sql["section"], sql["population"], sql["measure"]))
    ck.add("gate integrity: rows (section | population | measure), in order", f,
           "; ".join(" | ".join(k) for k in keys), "expected: GATE_ROWS in src/sql_check.py",
           "; ".join(" | ".join(k) for k in GATE_ROWS))
    if len(set(keys)) != len(keys):
        raise ReconciliationError(f"{f}: duplicate (section, population, measure) rows")
    rows = sql.set_index(["section", "population", "measure"])

    def row(section: str, population: str, measure: str) -> pd.Series:
        return rows.loc[(section, population, measure)]

    # The rounds bands were chosen after seeing the overall SRM warning: no SRM status label anywhere
    text = sql.select_dtypes(exclude="number").astype(str)
    ck.add("gate integrity: SRM status columns (the bands are post-hoc subsets)", f,
           sum("status" in col for col in sql.columns), "expected: none", 0)
    ck.add(f"gate integrity: cells with an SRM status word ({' / '.join(SRM_STATUS_WORDS)})", f,
           int(text.apply(lambda col: col.str.contains(r"\b(?:" + "|".join(SRM_STATUS_WORDS) + r")\b")).to_numpy().sum()),
           "expected: none", 0)

    # Step 1 - assignment by band, raw counts: net excess and the SRM statistic (p descriptive for the bands)
    for band, srm_key, _ in GATE_BANDS:
        srm, key = (gate["srm"], "srm.") if srm_key is None else (gate["srm_by_stratum"][srm_key],
                                                                  f"srm_by_stratum.{srm_key}.")
        r, lbl = row("assignment", band, "assigned players"), f"gate assignment {band}"
        ck.add(f"{lbl}: assigned gate_40", f, r["n_gate_40"], j + key + "n_t", srm["n_t"])
        ck.add(f"{lbl}: assigned gate_30", f, r["n_gate_30"], j + key + "n_c", srm["n_c"])
        net_key = "excess_players_raw" if srm_key is None else key + "net_excess_t"
        ck.add(f"{lbl}: net excess of gate_40 players", f, r["difference"], j + net_key,
               gate["excess_players_raw"] if srm_key is None else srm["net_excess_t"])
        ck.add(f"{lbl}: SRM chi-square (z_stat squared)", f, r["z_stat"] ** 2, j + key + "chi2", srm["chi2"], TOL_JSON)
        ck.add(f"{lbl}: SRM p-value (from the SQL z)", f, _p1(r["z_stat"]), j + key + "p_value", srm["p_value"],
               TOL_JSON)
    ck.add("gate assignment: net excess of gate_40 players with < 15 rounds", f,
           row("assignment", "Rounds < 15", "assigned players")["difference"], j + "excess_players_with_lt_15_rounds",
           gate["excess_players_with_lt_15_rounds"])

    # Step 2 - D7 and D1 by band and version, analysis population (edge-check bands included)
    retention_bands = (*GATE_BANDS,
                       *((band, None, (("retention_by_rounds_band", key),)) for band, key in GATE_EDGE_BANDS))
    for measure, metric in (("D7", "retention_7"), ("D1", "retention_1")):
        for band, _, paths in retention_bands:
            r = row("retention", band, measure)
            for i, path in enumerate(paths):
                where = ".".join((*path, metric))
                lbl = f"gate {measure} {band}" + (f" (again, as {'.'.join(path)})" if i else "")
                _gate_two_prop(ck, f, lbl, r, _dig(gate, where), j + where + ".")
    # do the 15-29 and < 15 bands' D7 gaps differ? (difference of gaps, unpooled SE; p from the SQL z)
    gd, r_gd = gate["d7_band_gap_difference_15_29_vs_lt_15"], row(*GATE_GAP_DIFF)
    jg = j + "d7_band_gap_difference_15_29_vs_lt_15."
    for check, value, key in (("difference of the two bands' D7 gaps", r_gd["difference"], "diff"),
                              ("standard error (unpooled)", r_gd["std_error"], "se"),
                              ("p-value (two-sided, from the SQL z)", _p1(r_gd["z_stat"]), "p_value")):
        ck.add(f"gate D7 band-gap difference (15-29 minus < 15): {check}", f, value, jg + key, gd[key], TOL_JSON)
    for band, lo, hi in GATE_DRILL_DOWN:   # share of each arm in the drill-down bands (not in results.json)
        sub = c[c["sum_gamerounds"].between(lo, hi)]
        for arm in ("gate_40", "gate_30"):
            ck.add(f"gate D7 {band}: share of {arm} players", f, row("retention", band, "D7")[f"share_of_arm_{arm}"],
                   "pandas: src.data.clean_cookie(raw CSV)", (sub["version"] == arm).sum() / (c["version"] == arm).sum(),
                   TOL_FULL)
    # negative-control sensitivity: gate_40's net excess of < 15-round players removed
    nx, jx = gate["negative_control"]["never_reached_30_excess_removed"], j + "negative_control.never_reached_30_excess_removed."
    r_nx = row("retention", "Rounds < 30, net excess removed", "D7")
    _gate_two_prop(ck, f, "gate D7 Rounds < 30, net excess removed", r_nx, nx["retention_7"], jx + "retention_7.")
    ck.add("gate D7 Rounds < 30, net excess removed: gate_40 players removed", f,
           row("retention", "Rounds < 30", "D7")["n_gate_40"] - r_nx["n_gate_40"], jx + "excess_removed",
           nx["excess_removed"])

    # Step 3 - decomposition of the naive D7 and D1 gaps (columns on the 'retention' rows)
    for measure, dkey in (("D7", "d7_decomposition"), ("D1", "d1_decomposition")):
        dec, jd, lbl = gate[dkey], j + f"{dkey}.", f"gate {measure} decomposition"
        for band, key in GATE_PARTITION:
            r, d = row("retention", band, measure), dec["detail"][key]
            for check, col, k in (("share of gate_40 players", "share_of_arm_gate_40", "w_t"),
                                  ("share of gate_30 players", "share_of_arm_gate_30", "w_c"),
                                  ("rate gate_40", "value_gate_40", "r_t"),
                                  ("rate gate_30", "value_gate_30", "r_c"),
                                  ("within term", "within_term", "within"),
                                  ("composition term", "composition_term", "composition")):
                ck.add(f"{lbl}, {band}: {check}", f, r[col], jd + f"detail.{key}.{k}", d[k], TOL_JSON)
        tot, never = row("retention", "All players", measure), row("retention", "Rounds < 30", measure)
        reach, ci = row("retention", "Rounds >= 30", measure), dec["install_level_effect_ci_if_only_reachers"]
        for check, value, key, value_json in (
            ("naive gap", tot["difference"], "naive_diff", dec["naive_diff"]),
            ("player mix (composition, both bands)", tot["composition_term"], "composition", dec["composition"]),
            ("players who never met a gate (within, rounds < 30)", never["within_term"], "within_never_reached_30",
             dec["within_never_reached_30"]),
            ("players who could meet the gate (within, rounds >= 30)", reach["within_term"], "within_reached_30",
             dec["within_reached_30"]),
            ("within + composition = naive gap (no residual)", tot["within_term"] + tot["composition_term"],
             "naive_diff", dec["naive_diff"]),
            ("average share of players with 30+ rounds",
             (reach["share_of_arm_gate_40"] + reach["share_of_arm_gate_30"]) / 2, "share_reached_30",
             dec["share_reached_30"]),
            ("the part the gate could explain, per install", reach["within_term"],
             "install_level_effect_if_only_reachers", dec["install_level_effect_if_only_reachers"]),
            ("the part the gate could explain, 95% CI low", reach["within_ci95_low"],
             "install_level_effect_ci_if_only_reachers[0]", ci[0]),
            ("the part the gate could explain, 95% CI high", reach["within_ci95_high"],
             "install_level_effect_ci_if_only_reachers[1]", ci[1]),
        ):
            ck.add(f"{lbl}: {check}", f, value, jd + key, value_json, TOL_JSON)
        ck.add(f"{lbl}: within terms of both bands (All players row)", f, tot["within_term"],
               jd + "within_never_reached_30 + within_reached_30",
               dec["within_never_reached_30"] + dec["within_reached_30"], 2 * TOL_JSON)  # sum of two rounded values

    # Step 4 - best case for gate_40: every extra install (analysis population) a junk install that never returned
    bc, jb, lbl = gate["best_case_for_gate_40"], j + "best_case_for_gate_40.", "gate best case for gate_40"
    r_bc, tot7 = row("best case for gate_40", "All players, extra installs removed", "D7"), row("retention", "All players", "D7")
    for check, value, key, value_json, tol in (
        ("extra gate_40 installs removed", tot7["n_gate_40"] - r_bc["n_gate_40"], "excess_players_gate_40",
         bc["excess_players_gate_40"], TOL_EXACT),
        ("D7 gap if they never returned", r_bc["difference"], "d7_diff_if_excess_removed",
         bc["d7_diff_if_excess_removed"], TOL_JSON),
        ("95% CI low (Newcombe)", r_bc["ci95_low"], "ci[0]", bc["ci"][0], TOL_JSON),
        ("95% CI high (Newcombe)", r_bc["ci95_high"], "ci[1]", bc["ci"][1], TOL_JSON),
        ("p-value (two-sided, from the SQL z)", _p1(r_bc["z_stat"]), "p_value", bc["p_value"], TOL_JSON),
    ):
        ck.add(f"{lbl}: {check}", f, value, jb + key, value_json, tol)
    for check, col, key in (("gate_40 players back on Day 7 (all kept)", "k_gate_40", "conv_t"),
                            ("gate_30 players", "n_gate_30", "n_c"),
                            ("gate_30 players back on Day 7", "k_gate_30", "conv_c")):
        ck.add(f"{lbl}: {check}", f, r_bc[col], j + f"retention_7.{key}", gate["retention_7"][key])

    # Step 5 - play: pre-gate rounds (all players) and rounds among players with 30+ rounds
    pg, jp = gate["pre_gate_engagement"], j + "pre_gate_engagement."
    r = row("play", "All players", "pre-gate rounds (capped at 29), mean")
    for arm, col, key in (("gate_40", "value_gate_40", "mean_capped_29_t"), ("gate_30", "value_gate_30", "mean_capped_29_c")):
        ck.add(f"gate play: pre-gate rounds (capped at 29), mean {arm}", f, r[col], jp + key, pg[key], TOL_JSON)
        ck.add(f"gate play: pre-gate rounds, players {arm}", f, r[f"n_{arm}"], j + f"players.{arm}", gate["players"][arm])
    rr, jr, lbl = gate["rounds_among_reachers"], j + "rounds_among_reachers.", "gate play among players with 30+ rounds"
    med, mean = row("play", "Rounds >= 30", "rounds, median"), row("play", "Rounds >= 30", "rounds, mean")
    for check, r_, col, key, tol in (
        ("players gate_40", med, "n_gate_40", "n_t", TOL_EXACT),
        ("players gate_30", med, "n_gate_30", "n_c", TOL_EXACT),
        ("median rounds gate_40", med, "value_gate_40", "median_t", TOL_JSON),
        ("median rounds gate_30", med, "value_gate_30", "median_c", TOL_JSON),
        ("players gate_40 (mean row)", mean, "n_gate_40", "n_t", TOL_EXACT),
        ("players gate_30 (mean row)", mean, "n_gate_30", "n_c", TOL_EXACT),
        ("mean rounds gate_40", mean, "value_gate_40", "mean_t", TOL_JSON),
        ("mean rounds gate_30", mean, "value_gate_30", "mean_c", TOL_JSON),
        ("mean difference", mean, "difference", "mean_diff", TOL_JSON),
    ):
        ck.add(f"{lbl}: {check}", f, r_[col], jr + key, rr[key], tol)
    ck.add(f"{lbl}: median difference", f, med["difference"], jr + "median_t - median_c",
           rr["median_t"] - rr["median_c"], 2 * TOL_JSON)
    _gate_two_prop(ck, f, f"{lbl}: share with 40+ rounds", row("play", "Rounds >= 30", "share with 40+ rounds"),
                   rr["share_past_40_rounds"], jr + "share_past_40_rounds.")

    # Step 6 - re-test sizing at the change fixed in config.yaml (Cohen's h closed form in SQL): sized for a
    # drop (the headline), and for a rise of the same size (results.json *_if_rise)
    rs, js, lbl = gate["retest_sizing"], j + "retest_sizing.", "gate re-test sizing"
    inst, rch = (row("re-test sizing", band, "D7 drop to detect") for band in ("All players", "Rounds >= 30"))
    inst_up, rch_up = (row("re-test sizing", band, "D7 rise to detect") for band in ("All players", "Rounds >= 30"))
    reach7 = row("retention", "Rounds >= 30", "D7")
    for check, value, key, tol in (
        ("smallest D7 change per install (SQL params)", -inst["difference"], "smallest_d7_change_per_install", TOL_JSON),
        ("baseline D7, all installs (gate_30)", inst["value_gate_30"], "baseline_d7_install", TOL_JSON),
        ("installs needed, analysed over all installs (50/50)", inst["installs_needed_5050"],
         "installs_needed_install_level_5050", TOL_EXACT),
        ("players needed, analysed over all installs (50/50)", inst["players_needed_5050"],
         "installs_needed_install_level_5050", TOL_EXACT),
        ("average share of players with 30+ rounds",
         (reach7["share_of_arm_gate_40"] + reach7["share_of_arm_gate_30"]) / 2, "share_reached_30", TOL_JSON),
        ("the same change among players with 30+ rounds", -rch["difference"], "equivalent_change_among_reachers",
         TOL_JSON),
        ("baseline D7 among players with 30+ rounds (gate_30)", rch["value_gate_30"], "baseline_d7_reachers", TOL_JSON),
        ("players with 30+ rounds needed (50/50)", rch["players_needed_5050"], "reachers_needed_5050", TOL_EXACT),
        ("installs needed for the primary analysis among them (50/50)", rch["installs_needed_5050"],
         "installs_needed_reacher_analysis_5050", TOL_EXACT),
        # a rise of the same size
        ("rise: smallest D7 change per install (SQL params)", inst_up["difference"], "smallest_d7_change_per_install",
         TOL_JSON),
        ("rise: baseline D7, all installs (gate_30)", inst_up["value_gate_30"], "baseline_d7_install", TOL_JSON),
        ("rise: installs needed, analysed over all installs (50/50)", inst_up["installs_needed_5050"],
         "installs_needed_install_level_5050_if_rise", TOL_EXACT),
        ("rise: players needed, analysed over all installs (50/50)", inst_up["players_needed_5050"],
         "installs_needed_install_level_5050_if_rise", TOL_EXACT),
        ("rise: the same change among players with 30+ rounds", rch_up["difference"], "equivalent_change_among_reachers",
         TOL_JSON),
        ("rise: baseline D7 among players with 30+ rounds (gate_30)", rch_up["value_gate_30"], "baseline_d7_reachers",
         TOL_JSON),
        ("rise: players with 30+ rounds needed (50/50)", rch_up["players_needed_5050"], "reachers_needed_5050_if_rise",
         TOL_EXACT),
        ("rise: installs needed for the primary analysis among them (50/50)", rch_up["installs_needed_5050"],
         "installs_needed_reacher_analysis_5050_if_rise", TOL_EXACT),
    ):
        ck.add(f"{lbl}: {check}", f, value, js + key, rs[key], tol)
    # the share with 30+ rounds that turns players into installs, shown on both 'Rounds >= 30' sizing rows: the
    # average of the arms is used; gate_30's own share is the cohort figure to re-check before a re-test
    for direction, r_ in (("drop", rch), ("rise", rch_up)):
        for check, value, key in (
            ("average share of players with 30+ rounds", (r_["share_of_arm_gate_40"] + r_["share_of_arm_gate_30"]) / 2,
             "share_reached_30"),
            ("share of gate_30 players with 30+ rounds", r_["share_of_arm_gate_30"], "share_reached_30_gate_30"),
        ):
            ck.add(f"{lbl} ({direction} row): {check}", f, value, js + key, rs[key], TOL_JSON)
    ck.add(f"{lbl}: smallest D7 change (SQL params) matches config.yaml", f, -inst["difference"],
           "results.json config.gate_smallest_d7_change", py["res"]["config"]["gate_smallest_d7_change"], TOL_JSON)


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
    ck.add(f"DQ: statuses other than {' / '.join(DQ_STATUS_WORDS)}", f, int((~sql["status"].isin(DQ_STATUS_WORDS)).sum()),
           "expected: the DQ log's status words (docs/03_data_quality_checks.md)", 0)
    # 'WARNING if > 0' rules: WARNING exactly where the Python value is above 0, in check order
    ck.add("DQ: checks with status WARNING", f, ", ".join(sql.loc[sql["status"] == "WARNING", "check_name"]),
           "expected: the 'WARNING if > 0' checks whose Python value is above 0",
           ", ".join(name for dataset, name, _, value, _ in expected
                     if (dataset, name) in DQ_WARNING_IF_POSITIVE and value > 0))


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
    _csv_view(table).to_csv(RECON_CSV, index=False)

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
