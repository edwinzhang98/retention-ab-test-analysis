"""Load raw CSVs, clean them, and build the analysis tables.

Table names follow the usual warehouse convention:
  fct_ad_exposure_users   one row per user in the ad experiment
  fct_game_players        one row per player in the Cookie Cats experiment
  agg_ad_cells            ad experiment aggregated to group x day x hour x exposure bucket
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import config as C


def link_raw() -> None:
    """Symlink raw CSVs into data/raw/ so the SQL files can use relative paths."""
    C.ensure_dirs()
    for src, name in ((C.MARKETING_AB_CSV, "marketing_AB.csv"), (C.COOKIE_CATS_CSV, "cookie_cats.csv")):
        if not src.exists():
            raise FileNotFoundError(
                f"Raw file not found: {src}. Set the path in config.yaml or .env (see README)."
            )
        dst = C.RAW_DIR / name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        os.symlink(src, dst)


# ---------------------------------------------------------------- raw loaders
def load_marketing_raw() -> pd.DataFrame:
    return pd.read_csv(C.MARKETING_AB_CSV)


def load_cookie_raw() -> pd.DataFrame:
    return pd.read_csv(C.COOKIE_CATS_CSV)


# ---------------------------------------------------------------- cleaning
def clean_marketing(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename to snake_case, drop the CSV index column, add exposure bucket."""
    df = raw.drop(columns=[c for c in raw.columns if c.startswith("Unnamed")]).rename(
        columns={
            "user id": "user_id",
            "test group": "test_group",
            "converted": "converted",
            "total ads": "total_ads",
            "most ads day": "most_ads_day",
            "most ads hour": "most_ads_hour",
        }
    )
    df["converted"] = df["converted"].astype(bool)
    df["test_group"] = df["test_group"].astype(str)
    df["most_ads_day"] = pd.Categorical(df["most_ads_day"], categories=C.DAY_ORDER, ordered=True)
    df["exposure_bucket"] = pd.cut(
        df["total_ads"], bins=C.EXPOSURE_BINS, labels=C.EXPOSURE_LABELS
    )
    return df[["user_id", "test_group", "converted", "total_ads", "exposure_bucket",
               "most_ads_day", "most_ads_hour"]]


def clean_cookie(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean players, dropped outliers)."""
    df = raw.rename(columns={"userid": "user_id"}).copy()
    df["version"] = df["version"].astype(str)
    df["retention_1"] = df["retention_1"].astype(bool)
    df["retention_7"] = df["retention_7"].astype(bool)
    outliers = df[df["sum_gamerounds"] > C.GAMEROUNDS_OUTLIER_MAX]
    df = df[df["sum_gamerounds"] <= C.GAMEROUNDS_OUTLIER_MAX].copy()
    df["rounds_bucket"] = pd.cut(df["sum_gamerounds"], bins=C.ROUNDS_BINS, labels=C.ROUNDS_LABELS)
    df["d1_status"] = np.where(df["retention_1"], "Returned Day 1", "Did not return Day 1")
    df["reached_gate_30"] = df["sum_gamerounds"] >= 30
    return df.reset_index(drop=True), outliers.reset_index(drop=True)


def aggregate_ad_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Counts by group x day x hour x exposure bucket (the dashboard's cache)."""
    g = (
        df.groupby(["test_group", "most_ads_day", "most_ads_hour", "exposure_bucket"], observed=True)
        .agg(users=("user_id", "size"), conversions=("converted", "sum"), impressions=("total_ads", "sum"))
        .reset_index()
    )
    g["most_ads_day"] = g["most_ads_day"].astype(str)
    g["exposure_bucket"] = g["exposure_bucket"].astype(str)
    return g
