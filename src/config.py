"""Project paths and settings.

Data paths come from config.yaml and can be overridden by environment
variables (or a .env file at the repo root): MARKETING_AB_CSV, COOKIE_CATS_CSV.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)


def _path(env_var: str, cfg_key: str) -> Path:
    raw = os.environ.get(env_var) or CFG["data"][cfg_key]
    return Path(os.path.expanduser(os.path.expandvars(raw)))


MARKETING_AB_CSV = _path("MARKETING_AB_CSV", "marketing_ab_csv")
COOKIE_CATS_CSV = _path("COOKIE_CATS_CSV", "cookie_cats_csv")

A = CFG["analysis"]
SEED: int = int(A["seed"])
ALPHA: float = float(A["alpha"])
POWER: float = float(A["power"])
N_BOOT: int = int(A["n_bootstrap"])
INTENDED_AD_SHARE: float = float(A["intended_ad_share"])
INTENDED_GATE40_SHARE: float = float(A["intended_gate40_share"])
GAMEROUNDS_OUTLIER_MAX: int = int(A["gamerounds_outlier_max"])
VALUE_PER_CONVERSION: float = float(A["value_per_conversion_usd"])

# Local working folders (git-ignored except reports/)
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # symlinks to the raw CSVs (used by sql/)
PROCESSED_DIR = DATA_DIR / "processed"  # parquet caches read by the dashboard
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"
RESULTS_JSON = REPORTS_DIR / "results.json"

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Exposure (total ads seen) buckets. Upper-inclusive.
EXPOSURE_BINS = [0, 5, 10, 20, 35, 50, 100, 200, 10**9]
EXPOSURE_LABELS = ["1-5", "6-10", "11-20", "21-35", "36-50", "51-100", "101-200", "200+"]
# Game-round buckets chosen around the two gate positions (level 30 / 40)
ROUNDS_BINS = [-1, 0, 4, 14, 29, 39, 99, 10**9]
ROUNDS_LABELS = ["0", "1-4", "5-14", "15-29", "30-39", "40-99", "100+"]


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROCESSED_DIR, FIG_DIR, TABLES_DIR, REPORTS_DIR / "notebooks"):
        d.mkdir(parents=True, exist_ok=True)
