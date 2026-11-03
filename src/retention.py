"""Retention helpers for the Cookie Cats player table."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import wilson_ci

METRICS = {"retention_1": "D1 retention", "retention_7": "D7 retention"}


def retention_rates(df: pd.DataFrame, by: str | list[str] | None = None, alpha: float = 0.05) -> pd.DataFrame:
    """D1 / D7 retention with Wilson CIs, overall or by one or more columns."""
    keys = [by] if isinstance(by, str) else (by or [])
    groups = df.groupby(keys, observed=True) if keys else [((), df)]
    rows = []
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(keys, key))
        n = len(g)
        row["players"] = n
        row["share_of_players"] = n / len(df)
        for m in METRICS:
            k = int(g[m].sum())
            lo, hi = wilson_ci(k, n, alpha)
            row[f"{m}"] = k / n
            row[f"{m}_ci_low"] = lo
            row[f"{m}_ci_high"] = hi
        rows.append(row)
    return pd.DataFrame(rows)


def funnel(df: pd.DataFrame) -> pd.DataFrame:
    """Nested stages: installed -> returned Day 1 -> returned Day 1 and Day 7."""
    n = len(df)
    steps = [
        ("Installed", n),
        ("Returned on Day 1", int(df["retention_1"].sum())),
        ("Returned on Day 1 and Day 7", int((df["retention_1"] & df["retention_7"]).sum())),
    ]
    out = pd.DataFrame(steps, columns=["step", "players"])
    out["share_of_installs"] = out["players"] / n
    out["step_conversion"] = out["players"] / out["players"].shift(1)
    return out


def engagement_curve(df: pd.DataFrame, max_rounds: int = 200, by: str | None = "version") -> pd.DataFrame:
    """Share of players who played at least k rounds, k = 0..max_rounds.
    Read like a survival curve over game progress (not over calendar time)."""
    ks = np.arange(0, max_rounds + 1)
    parts = []
    groups = df.groupby(by) if by else [("All players", df)]
    for name, g in groups:
        r = np.sort(g["sum_gamerounds"].to_numpy())
        share = 1 - np.searchsorted(r, ks, side="left") / len(r)
        parts.append(pd.DataFrame({"rounds_at_least": ks, "share_of_players": share, "group": name}))
    return pd.concat(parts, ignore_index=True)


def retention_by_rounds(df: pd.DataFrame, max_rounds: int = 150, step: int = 5) -> pd.DataFrame:
    """D1 / D7 retention by binned rounds played (for the 'more play, more retention' curve)."""
    edges = list(range(0, max_rounds + step, step)) + [10**9]
    d = df.assign(bin=pd.cut(df["sum_gamerounds"], bins=[-1] + edges[1:], right=False, labels=False))
    g = d.groupby("bin").agg(players=("user_id", "size"), retention_1=("retention_1", "mean"),
                             retention_7=("retention_7", "mean"), rounds_mid=("sum_gamerounds", "median"))
    return g.reset_index(drop=True)


def gap_by_dimension(df: pd.DataFrame, dims: dict[str, str], metric: str = "retention_7",
                     min_players: int = 500) -> pd.DataFrame:
    """For each segmentation dimension, the spread (max - min) in retention
    across its segments (segments with < min_players ignored)."""
    rows = []
    for col, label in dims.items():
        r = retention_rates(df, col)
        r = r[r["players"] >= min_players]
        hi, lo = r.loc[r[metric].idxmax()], r.loc[r[metric].idxmin()]
        rows.append({"dimension": label, "column": col, "metric": metric,
                     "best_segment": str(hi[col]), "best_rate": hi[metric],
                     "worst_segment": str(lo[col]), "worst_rate": lo[metric],
                     "gap_pp": (hi[metric] - lo[metric]) * 100, "n_segments": len(r)})
    return pd.DataFrame(rows).sort_values("gap_pp", ascending=False).reset_index(drop=True)
