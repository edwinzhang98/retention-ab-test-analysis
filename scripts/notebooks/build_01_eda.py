"""Builds notebooks/01_eda.ipynb: data exploration and data-quality checks for both datasets.

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

Usage (from anywhere): .venv/bin/python scripts/notebooks/build_01_eda.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[2]  # scripts/notebooks/ -> repo root
NB_PATH = ROOT / "notebooks" / "01_eda.ipynb"
NB_TITLE = "01 · Data exploration and data-quality checks"

CELLS: list[tuple[str, str]] = []


def md(text: str) -> None:
    CELLS.append(("markdown", dedent(text).strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", dedent(text).strip("\n")))


# =============================================================================== front matter
md("""
# 01 · Data exploration and data-quality checks

*Growth · Product Analytics · notebook 1 of 3 (01 EDA and data quality → 02 retention → 03 A/B tests).*
*Companion log: `docs/03_data_quality_checks.md` (same checks, same IDs, same numbers).*

Every number in this notebook is recomputed from the raw files when it runs, reconciled with `reports/results.json` (section 10), and every number quoted in the text is re-checked in the appendix, so the prose cannot drift from the data.

*Charts are interactive Plotly figures that load plotly.js from a CDN, so they need an internet connection (GitHub's notebook preview does not show them). `reports/report.html` is the fully offline version of the analysis, with plotly.js embedded.*
""")

md("""
## TL;DR

- **Both files load completely and are clean at the key level.** Marketing A/B: [[n_m]] rows in the file, loaded and analysed. Cookie Cats: [[n_c_raw]] rows in the file and loaded, [[n_c]] analysed after dropping one outlier. IDs are unique, there are no nulls, and every value is inside its expected domain.
- **One row is dropped, and no retention or experiment conclusion depends on it.** A Cookie Cats player logged [[out_max]] rounds in 14 days (about [[out_per_day]] a day; the next-highest player has [[second_max]]). Dropping it moves overall D1 and D7 retention by [[ret_shift]] pp and the naive gate D7 difference by [[d7_effect_shift]] pp. It does distort means: it inflates gate_30's mean rounds by [[mean_inflation]].
- **The ad test's sample-ratio check passes, but it carries no information.** The ad arm has [[n_ad]] users, the nearest whole number to exactly 96% of [[n_m]] ([[quota_dev]] users off, where random assignment typically misses by about ±[[quota_sd]] users; landing exactly there has a probability of [[quota_prob]]). The split is most likely a fixed quota (or an export trimmed to one). Fixed arm sizes are a valid design; they just make the SRM test pass by construction, so it says nothing. The meaningful check is exposure parity: [[mean_ads_1dp]] ads per user in both arms, but the shapes differ a little ([[sh15_psa]] of PSA vs [[sh15_ad]] of ad users saw 1–5 ads; KS D = [[ks_d]]). Exposure, peak day and peak hour are recorded after assignment, so they stay exploratory cuts, never covariates.
- **The gate experiment gets a sample-ratio WARNING, and gate_40's net excess of installs sits with low-engagement players.** Raw assignment counts are [[gate_counts]] (gate_30 vs gate_40), p = [[gate_srm_p]] against 50/50: below the 0.01 warning line, above the 0.001 failure line. gate_40 has [[gate_excess_raw]] more installs in the raw log. By rounds played, the net excess is [[ex15_s]] among players with fewer than 15 rounds (p = [[lt15_p]]), [[ex1529_s]] at 15–29 rounds (p = [[b1529_p]]) and [[ex30_s]] at 30+ rounds (p = [[ge30_p]]); these bands were chosen after seeing the warning, so their p-values are descriptive. Pre-gate play (rounds capped at 29) is lower in gate_40 (p = [[pregate_p]]), but that is the same imbalance seen as a distribution, not independent evidence (within players with fewer than 30 rounds, p = [[pregate_lt30_p]]). Both versions are identical below level 30, so the gate cannot have created that imbalance: most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from gate_30); Engineering confirms the cause. The gate readout is not certified.
- **Neither dataset has a date or timestamp.** Novelty effects, test duration and trends over time can't be assessed, and Cookie Cats is a single install cohort. Rounds are counted over the first 14 days, which include Day 7, so rounds vs retention is partly definitional.
""")

md("""
## Question

Before any lift or retention number goes into the readout: **can we trust these two datasets, and what does every downstream number need to account for?**

1. Did every row in the source files reach the analysis tables, at one row per user / player?
2. Are IDs unique, are there nulls, and are values inside their expected domains and ranges?
3. Which outliers or edge cases need a treatment rule, and does any conclusion depend on that rule?
4. Do the experiments look correctly randomized (sample ratio, balance of the fields we have), and if not, where does the imbalance sit?
5. What time coverage do we have, and what does its absence rule out?
""")

md("""
## Data

| | Marketing A/B (ad vs PSA) | Cookie Cats (gate_30 vs gate_40) |
|---|---|---|
| Source | Kaggle `faviovaz/marketing-ab-testing` (2021) | Kaggle / DataCamp Cookie Cats A/B test (2017) |
| Role in this project | Main experiment: did the ad campaign drive conversions? | The company's mobile game, a different product from the app the ads ran in: new-player retention, plus a second experiment (progression gate) |
| Grain | One row per user in the experiment | One row per player who installed during the test |
| Fields | `user id`, `test group` (ad / psa), `converted`, `total ads`, `most ads day`, `most ads hour`, plus an unnamed index column | `userid`, `version` (gate_30 / gate_40), `sum_gamerounds`, `retention_1`, `retention_7` |
| Dates / timestamps | None | None |
| File location | `config.yaml` → `data.marketing_ab_csv` (or `MARKETING_AB_CSV` in `.env`) | `config.yaml` → `data.cookie_cats_csv` (or `COOKIE_CATS_CSV` in `.env`) |

Field meanings, from the dataset descriptions: `converted` = the user bought the product; `total ads` = how many ads (PSAs, in the control group) the user saw; `most ads day` / `most ads hour` = the weekday / hour in which the user saw the most of them; `sum_gamerounds` = rounds played in the first 14 days after install; `retention_1` / `retention_7` = the player came back to the game on day 1 / day 7 after install (classic day-N retention: active on that day, not "at any time within N days"; section 6 shows the flags do not require a finished round). Raw files stay outside the repo and are read through `src/data.py`.
""")

md("""
## Method

The checks use the pipeline's own loading and cleaning functions (`src/data.py`) and tests (`src/stats.py`), so the numbers here are the numbers in `reports/results.json`. Each check gets an ID (shared with `docs/03_data_quality_checks.md`) and a status: **PASS** (as expected), **WARNING** (an issue that is handled, or that limits what we can claim; analysis continues and the caveat travels with the numbers), **FAIL** (blocks the analysis until fixed).

| Check | How | Rule |
|---|---|---|
| Row reconciliation | Count data lines in each file; compare with rows loaded and rows analysed | Every difference must be explained |
| Primary key | Duplicate IDs | 0 duplicates |
| Nulls | Nulls per column | 0 nulls |
| Domains and ranges | Distinct values of categorical fields; percentiles of counts | Every value in its expected set or range |
| Outliers | Inspect the top of each distribution; drop only values that are not humanly plausible | Rule in `config.yaml` (`gamerounds_outlier_max`); key numbers re-run with and without |
| Sample ratio mismatch (SRM) | Chi-square goodness of fit of arm sizes to the intended split, on raw assignment counts (assignment happens before any cleaning) | p < 0.001 FAIL (the usual SRM convention, after Kohavi et al.); 0.001 ≤ p < 0.01 WARNING (this project's warning band: the readout can't be certified until assignment is checked); otherwise PASS |
| Quota exactness | Distance of the treatment count from its exact target, against the standard deviation that random assignment would produce | A count on the nearest whole number to the target most likely comes from a fixed quota (or a trimmed export): a valid design, but the SRM test then passes by construction and says nothing |
| Localizing an imbalance (gate) | Net excess of gate_40 installs by rounds band (fewer than 15, 15–29, 30+ rounds; raw counts), with χ² p-values against 50/50; Mann-Whitney test of rounds capped at 29, overall and within players with fewer than 30 rounds | Both versions are identical below level 30, and a player with fewer than 30 rounds cannot have got past level 30, so the bands are close to, not exactly, gate-free (only a flawless gate_30 player can already face the gate, at exactly 29 rounds): each band should split about 50/50. The bands were chosen after seeing the warning, so their p-values are descriptive and carry no status |
| Balance of other fields | Chi-square and Cramér's V across arms | Judged on size (Cramér's V), not on p: with 588K users even trivial differences are "significant" |
""")

# =============================================================================== results
md("""
## Results

### 0. Setup and load
""")

code('''
import json
import sys
from pathlib import Path

# Repo root = the first folder upwards that holds config.yaml, so this runs from notebooks/ or from the root
ROOT = Path.cwd().resolve()
while not (ROOT / "config.yaml").exists():
    if ROOT.parent == ROOT:
        raise FileNotFoundError("config.yaml not found: run this notebook from inside the project folder")
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from IPython.display import display
from scipy import stats as sps

from src import config as C
from src import data as D
from src import figures as F
from src import stats as S
from src.catalog import build_catalog, load_caches, sgn

# plotly.js loads from a CDN, so the notebook and its HTML export stay small;
# reports/report.html is the offline version (plotly.js embedded once).
pio.renderers.default = "notebook_connected"
pio.renderers["notebook_connected"].config = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}

T, CTRL = "ad", "psa"            # ad experiment: treatment, control
G_T, G_C = "gate_40", "gate_30"  # gate experiment: treatment, control
STATUS_BG = {"PASS": "#e9f4ec", "WARNING": "#fff3d6", "FAIL": "#fde3df"}
STATUS_COLS = ("status", "SRM test")
CHECKS = []  # every check below appends one row; section 10 shows them all as the DQ scorecard


def log_check(check_id: str, dataset: str, check: str, result: str, status: str) -> None:
    """One row of the DQ scorecard; IDs match docs/03_data_quality_checks.md."""
    CHECKS.append({"id": check_id, "dataset": dataset, "check": check, "result": result, "status": status})


def p_txt(p: float, nd: int = 4) -> str:
    """p-value for tables and text: never printed as 0."""
    return "< 0.0001" if p < 0.0001 else f"{p:.{nd}f}"


def p_2sig(p: float) -> str:
    """p-value with two significant digits (0.56, 0.0086), four decimals below 0.001; never printed as 0."""
    if p < 0.0001:
        return "< 0.0001"
    return f"{p:.4f}" if p < 0.001 else ("> 0.99" if p > 0.99 else f"{p:.2g}")


def table(df: pd.DataFrame, fmt: dict | None = None):
    """Show a table without its index, with number formats and coloured PASS / WARNING / FAIL cells."""
    s = df.style.hide(axis="index").format(fmt or {}, na_rep="")
    text_cols = [col for col in df.columns if not pd.api.types.is_numeric_dtype(df[col])]
    if text_cols:
        s = s.set_properties(subset=text_cols, **{"text-align": "left"}).set_table_styles(
            [{"selector": f"th.col{i}", "props": "text-align: left;"}
             for i, col in enumerate(df.columns) if col in text_cols])
    if "id" in df.columns:
        s = s.set_properties(subset=["id"], **{"white-space": "nowrap"})
    for col in STATUS_COLS:
        if col in df.columns:
            s = s.map(lambda v: f"background-color: {STATUS_BG.get(str(v), 'transparent')}", subset=[col])
    return s


def frame(fig: go.Figure, title: str, takeaway: str, **kw) -> go.Figure:
    """Shared chart frame from src/figures.py: bold title with units, one-line takeaway underneath."""
    return F.apply_layout(fig, title, takeaway, **kw)
''')

code('''
m_raw = D.load_marketing_raw()     # Marketing A/B exactly as in the file
c_raw = D.load_cookie_raw()        # Cookie Cats exactly as in the file
m = D.clean_marketing(m_raw)       # snake_case names, index column dropped, exposure bucket added
c, c_out = D.clean_cookie(c_raw)   # outlier rule from config.yaml applied; c_out = the dropped rows
results = json.loads(C.RESULTS_JSON.read_text())  # pipeline output: reconciled in section 10
cat = build_catalog(results, load_caches())       # the dashboard's default charts and takeaways

print(f"Marketing A/B: {len(m_raw):,} rows x {m_raw.shape[1]} columns in the file")
print(f"Cookie Cats:   {len(c_raw):,} rows x {c_raw.shape[1]} columns in the file")
display(m_raw.head(3), c_raw.head(3))
''')

# ------------------------------------------------------------------------------- 1. rows
md("""
### 1. Row reconciliation

Data lines are counted on the raw bytes (independently of pandas), then compared with the rows pandas loaded and the rows that reach the analysis tables.
""")

code('''
def data_lines(path: Path) -> int:
    """Data rows in a CSV: lines in the file minus the header, counted on the raw bytes."""
    with open(path, "rb") as f:
        return sum(1 for _ in f) - 1


recon = pd.DataFrame([
    {"dataset": "Marketing A/B", "file": C.MARKETING_AB_CSV.name, "rows in file": data_lines(C.MARKETING_AB_CSV),
     "rows loaded": len(m_raw), "rows analysed": len(m)},
    {"dataset": "Cookie Cats", "file": C.COOKIE_CATS_CSV.name, "rows in file": data_lines(C.COOKIE_CATS_CSV),
     "rows loaded": len(c_raw), "rows analysed": len(c)},
])
recon["rows dropped"] = recon["rows loaded"] - recon["rows analysed"]
recon["explanation"] = ["no rows dropped",
                        f"{len(c_out)} player above the {C.GAMEROUNDS_OUTLIER_MAX:,}-round outlier rule (section 5)"]
assert (recon["rows in file"] == recon["rows loaded"]).all(), "pandas did not load every line"
assert recon["rows dropped"].sum() == len(c_out), "rows lost in cleaning without an explanation"

for check_id, (_, r) in zip(("MKT-1", "CC-1"), recon.iterrows()):
    log_check(check_id, r["dataset"], "Row reconciliation: file → loaded → analysed",
              f"{r['rows in file']:,} → {r['rows loaded']:,} → {r['rows analysed']:,}", "PASS")
table(recon, {k: "{:,}" for k in ("rows in file", "rows loaded", "rows analysed", "rows dropped")})
''')

md("""
**Conclusion:** every line of both files is loaded, and the only row not analysed is explained: one Cookie Cats player removed by the outlier rule (section 5).
""")

# ------------------------------------------------------------------------------- 2. keys
md("""
### 2. Keys, nulls and value domains
""")

code('''
def profile(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """One row per column: type, nulls, distinct values, and the range (or the values, when there are few)."""
    rows = []
    for col in df.columns:
        s = df[col]
        is_count = pd.api.types.is_integer_dtype(s)
        rows.append({"dataset": dataset, "column": col, "type": str(s.dtype), "nulls": int(s.isna().sum()),
                     "distinct": int(s.nunique()),
                     "min": s.min() if is_count else np.nan, "max": s.max() if is_count else np.nan,
                     "values": ", ".join(sorted(map(str, s.unique()))) if s.nunique() <= 7 else ""})
    return pd.DataFrame(rows)


table(pd.concat([profile(m_raw, "Marketing A/B"), profile(c_raw, "Cookie Cats")], ignore_index=True),
      {"nulls": "{:,}", "distinct": "{:,}", "min": "{:,.0f}", "max": "{:,.0f}"})
''')

code('''
dup_m = int(m_raw["user id"].duplicated().sum())
dup_c = int(c_raw["userid"].duplicated().sum())
index_is_row_number = bool((m_raw["Unnamed: 0"].to_numpy() == np.arange(len(m_raw))).all())
shared_ids = len(set(m_raw["user id"]) & set(c_raw["userid"]))
is_int, is_bool = pd.api.types.is_integer_dtype, pd.api.types.is_bool_dtype

rules = pd.DataFrame([
    ("Marketing A/B", "user id", "unique: one row per user", dup_m == 0),
    ("Marketing A/B", "Unnamed: 0", "equals the row number 0 … n−1 (a saved pandas index, safe to drop)", index_is_row_number),
    ("Marketing A/B", "test group", "only 'ad' or 'psa'", set(m_raw["test group"]) == {T, CTRL}),
    ("Marketing A/B", "converted", "boolean", is_bool(m_raw["converted"])),
    ("Marketing A/B", "total ads", "whole number ≥ 1", is_int(m_raw["total ads"]) and m_raw["total ads"].min() >= 1),
    ("Marketing A/B", "most ads day", "a weekday name; all 7 present", set(m_raw["most ads day"]) == set(C.DAY_ORDER)),
    ("Marketing A/B", "most ads hour", "whole number 0–23; all 24 present", set(m_raw["most ads hour"]) == set(range(24))),
    ("Cookie Cats", "userid", "unique: one row per player", dup_c == 0),
    ("Cookie Cats", "version", "only 'gate_30' or 'gate_40'", set(c_raw["version"]) == {G_C, G_T}),
    ("Cookie Cats", "sum_gamerounds", "whole number ≥ 0",
     is_int(c_raw["sum_gamerounds"]) and c_raw["sum_gamerounds"].min() >= 0),
    ("Cookie Cats", "retention_1, retention_7", "boolean", is_bool(c_raw["retention_1"]) and is_bool(c_raw["retention_7"])),
], columns=["dataset", "column", "expected", "ok"])
rules["status"] = np.where(rules["ok"], "PASS", "FAIL")

for ids, name, df, dups in ((("MKT-2", "MKT-3", "MKT-4"), "Marketing A/B", m_raw, dup_m),
                            (("CC-2", "CC-3", "CC-4"), "Cookie Cats", c_raw, dup_c)):
    nulls, r = int(df.isna().sum().sum()), rules[rules["dataset"] == name]
    log_check(ids[0], name, "Primary key unique", f"{dups} duplicate IDs in {len(df):,} rows", "PASS" if dups == 0 else "FAIL")
    log_check(ids[1], name, "Nulls", f"{nulls} nulls in {df.shape[1]} columns", "PASS" if nulls == 0 else "FAIL")
    log_check(ids[2], name, "Value domains", f"{r['ok'].sum()} of {len(r)} field rules hold",
              "PASS" if r["ok"].all() else "FAIL")
print(f"IDs that appear in both files: {shared_ids:,} (different products of the company; the files are never joined)")
table(rules.drop(columns="ok"))
''')

md("""
**Conclusion:** IDs are unique, nothing is null, and every value is in its expected set; the unnamed first column is a saved row number, so dropping it loses nothing. The two files come from different products (the app the ads ran in, and the company's mobile game): [[shared_ids]] IDs happen to appear in both, a numbering coincidence, so the datasets are never joined.
""")

# ------------------------------------------------------------------------------- 3. marketing distributions
md("""
### 3. Marketing A/B: ads seen, peak day and peak hour

`total ads`, `most ads day` and `most ads hour` describe ad delivery, which happens *after* a user is assigned to an arm. The charts compare each arm's distribution: a randomized test should show similar shapes, but because these fields are post-assignment, a difference is a reason for caution rather than proof of broken randomization. The first two charts are the dashboard's default views (`src/catalog.py`), with the same takeaways.
""")

code('''
PCTS = [.25, .5, .75, .9, .99, .999]


def spread(values: pd.Series, groups: pd.Series, labels: dict | None = None) -> pd.DataFrame:
    """Count, mean, percentiles and max, per group and for everyone."""
    out = values.groupby(groups).describe(percentiles=PCTS).rename(index=labels or {})
    out.loc["all"] = values.describe(percentiles=PCTS)
    return out.drop(columns="std").reset_index(names="group").rename(columns={"count": "n"})


ads_spread = spread(m["total_ads"], m["test_group"], {T: "ad (treatment)", CTRL: "psa (control)"})
table(ads_spread, {col: "{:,.0f}" for col in ads_spread.columns[1:]} | {"mean": "{:.2f}", "99.9%": "{:,.1f}"})
''')

code('''
bal = {b["variable"]: b for b in (S.balance_test(m, col, "test_group")
                                  for col in ("most_ads_day", "most_ads_hour", "exposure_bucket"))}


def arm_shares(col: str) -> pd.DataFrame:
    """Share (%) of each arm's users in each category of col."""
    return pd.crosstab(m[col], m["test_group"], normalize="columns") * 100


mean_ads = m.groupby("test_group")["total_ads"].mean()
share_e = arm_shares("exposure_bucket")
egap = (share_e[T] - share_e[CTRL]).abs()
cat["ad_balance_exposure"].fig.show()
''')

md("""
**Conclusion:** exposure is heavily right-skewed (median [[med_ads]] ads, 99th percentile [[p99_ads]], maximum [[max_ads]]) and both arms received the same volume per user; the bucket shapes differ by up to [[egap]] pp (PSA users sit more often in the [[egap_psa]] bucket, ad users in the [[egap_ad]] bucket), one reason exposure is never used as a covariate.
""")

code('''
day_share = m["most_ads_day"].value_counts(normalize=True) * 100
dgap = arm_shares("most_ads_day").pipe(lambda s: (s[T] - s[CTRL]).abs())
cat["ad_balance_day"].fig.show()
''')

md("""
**Conclusion:** every weekday is the peak day for [[day_share_min]]%–[[day_share_max]]% of users, so the campaign ran for at least a week, but its total length is unknown; the arms' day mix differs by up to [[dgap]] pp ([[dgap_day]]), which is why day-level lift results are labelled exploratory.
""")

code('''
hour = m["most_ads_hour"]
core_share = hour.between(9, 22).mean() * 100    # 09:00-22:59
night_share = hour.between(3, 6).mean() * 100    # 03:00-06:59
hgap = arm_shares("most_ads_hour").pipe(lambda s: (s[T] - s[CTRL]).abs())
ctrl_by_hour = m.loc[m["test_group"] == CTRL, "most_ads_hour"].value_counts()
fig = F.fig_balance(
    m, "most_ads_hour", "Peak ad hour: share of each arm's users (%)",
    f"{core_share:.0f}% of users peak between 09:00 and 22:59 and only {night_share:.1f}% between 03:00 and 06:59 "
    f"(timezone not documented). No hour's share differs between the arms by more than {hgap.max():.1f} pp "
    f"(Cramér's V {bal['most_ads_hour']['cramers_v']:.3f}); the hour is recorded after assignment, so hourly results "
    f"are exploratory.",
    order=list(range(24)), xtitle="Hour with most ads (0–23)")
fig.show()
''')

md("""
**Conclusion:** peak exposure follows a normal daily activity curve and the arms differ by at most [[hgap]] pp in any hour. Hourly segments are thin in the control arm (the smallest hour has [[min_ctrl_hour]] PSA users), so the heterogeneity analysis in `03_ab_test` runs one interaction test per dimension, then segment-vs-rest contrasts with multiple-comparison correction, and also groups hours into four dayparts.
""")

# ------------------------------------------------------------------------------- 4. cookie distributions
md("""
### 4. Cookie Cats: play depth

Percentiles are shown on the raw file, before the outlier rule, so the maximum shows the problem row.
""")

code('''
rounds_spread = spread(c_raw["sum_gamerounds"], c_raw["version"])
table(rounds_spread, {col: "{:,.0f}" for col in rounds_spread.columns[1:]} | {"mean": "{:.2f}", "99.9%": "{:,.1f}"})
''')

code('''
CAP = 100  # rounds shown on the chart; the tail beyond it is summarised in the takeaway
counts = c["sum_gamerounds"].value_counts().reindex(range(CAP + 1), fill_value=0)
above = c["sum_gamerounds"] > CAP
above_share = above.mean() * 100
rounds_above_share = c.loc[above, "sum_gamerounds"].sum() / c["sum_gamerounds"].sum() * 100
zero_share = (c["sum_gamerounds"] == 0).mean() * 100

fig = go.Figure()
fig.add_bar(x=counts.index, y=counts / len(c) * 100, customdata=counts.to_numpy(), name="Players",
            marker=dict(color=F.BLUE), hovertemplate="%{x} rounds<br>%{y:.2f}% of players (%{customdata:,})<extra></extra>")
frame(fig, f"Players by rounds played in first 14 days (% of players, 0–{CAP} rounds shown)",
      f"The most common outcome is {c['sum_gamerounds'].mode().iloc[0]} round; {zero_share:.1f}% never play one and half "
      f"play {c['sum_gamerounds'].median():.0f} or fewer. The {above_share:.1f}% who play more than {CAP} rounds (off the "
      f"chart) account for {rounds_above_share:.0f}% of all rounds played.",
      xaxis_title="Rounds played in first 14 days", yaxis_title="Share of players (%)", legend=False)
fig.update_layout(bargap=0.15)
fig.show()
''')

md("""
**Conclusion:** play depth is extremely skewed: half of players play [[med_rounds]] rounds or fewer, while the [[above_share]]% of players beyond 100 rounds generate [[rounds_above_share]]% of all play, so means of rounds are fragile and rounds comparisons should use medians or rank tests.
""")

# ------------------------------------------------------------------------------- 5. outliers
md("""
### 5. Outliers and their treatment

**Rule** (`config.yaml` → `gamerounds_outlier_max`): drop a player only if the round count is not humanly plausible, defined as more than [[rule]] rounds in 14 days (about [[rule_per_day]] a day). Marketing exposure has no drop rule: without dates there is no basis to call any exposure count impossible, so it gets a sensitivity check instead.
""")

code('''
top = c_raw.nlargest(20, "sum_gamerounds").reset_index(drop=True)
top["rank"] = top.index + 1
top["dropped"] = top["sum_gamerounds"] > C.GAMEROUNDS_OUTLIER_MAX
out_max, second_max = int(top.loc[0, "sum_gamerounds"]), int(top.loc[1, "sum_gamerounds"])
yes_no = {True: "yes", False: "no"}

fig = go.Figure()
for dropped, name, color in ((False, "Kept", F.GREY), (True, "Dropped by the rule", F.ORANGE)):
    d = top[top["dropped"] == dropped]
    fig.add_scatter(
        x=d["rank"], y=d["sum_gamerounds"], mode="markers", name=name,
        marker=dict(color=color, size=11, line=dict(color=F.SURFACE, width=1)),
        customdata=np.column_stack([d["version"], d["sum_gamerounds"] / 14,
                                    d["retention_1"].map(yes_no), d["retention_7"].map(yes_no)]),
        hovertemplate="Rank %{x}: %{y:,} rounds (about %{customdata[1]:,.0f} a day)<br>%{customdata[0]}"
                      " · back on Day 1: %{customdata[2]} · Day 7: %{customdata[3]}<extra></extra>")
fig.add_hline(y=C.GAMEROUNDS_OUTLIER_MAX, line=dict(color=F.INK_2, width=1, dash="dot"))
fig.add_annotation(x=20, y=np.log10(C.GAMEROUNDS_OUTLIER_MAX), text=f"drop rule: more than {C.GAMEROUNDS_OUTLIER_MAX:,} rounds",
                   showarrow=False, xanchor="right", yanchor="bottom", font=dict(size=11, color=F.INK_2))
frame(fig, "Top 20 players by rounds played in first 14 days (rounds, log scale)",
      f"One {top.loc[0, 'version']} player logged {out_max:,} rounds, {out_max / second_max:.0f}× the next-highest "
      f"({second_max:,}) and about {out_max / 14:,.0f} a day; it is the only player above the rule and is dropped.",
      xaxis_title="Rank (1 = most rounds)", yaxis_title="Rounds played (log scale)")
fig.update_yaxes(type="log", tickvals=[1_000, 2_000, 5_000, 10_000, 20_000, 50_000], tickformat=",")
fig.update_xaxes(range=[0.3, 20.7], tickvals=[1, 5, 10, 15, 20])
fig.show()
''')

md("""
**Conclusion:** [[out_max]] rounds in 14 days is about [[out_per_min]] rounds a minute around the clock, and the same row has `retention_1` = [[out_d1]] (not back on Day 1), which contradicts that volume; it is treated as a logging error and dropped, while the next-highest players (at most about [[second_per_day]] rounds a day) are heavy but plausible and are kept.
""")

code('''
def gate_summary(df: pd.DataFrame) -> dict:
    """Headline Cookie Cats numbers, to compare with and without the outlier."""
    v = df.groupby("version").agg(n=("version", "size"), d1=("retention_1", "sum"), d7=("retention_7", "sum"),
                                  mean_rounds=("sum_gamerounds", "mean"), median_rounds=("sum_gamerounds", "median"))
    d1 = S.two_prop_test(v.loc[G_T, "d1"], v.loc[G_T, "n"], v.loc[G_C, "d1"], v.loc[G_C, "n"], alpha=C.ALPHA)
    d7 = S.two_prop_test(v.loc[G_T, "d7"], v.loc[G_T, "n"], v.loc[G_C, "d7"], v.loc[G_C, "n"], alpha=C.ALPHA)
    mw = sps.mannwhitneyu(df.loc[df["version"] == G_T, "sum_gamerounds"], df.loc[df["version"] == G_C, "sum_gamerounds"])
    return {"players": len(df), "d1": df["retention_1"].mean(), "d7": df["retention_7"].mean(),
            "d1_diff": d1.abs_lift, "d1_p": d1.p_value, "d7_diff": d7.abs_lift, "d7_p": d7.p_value,
            "mean_c": v.loc[G_C, "mean_rounds"], "mean_diff": v.loc[G_T, "mean_rounds"] - v.loc[G_C, "mean_rounds"],
            "median_c": v.loc[G_C, "median_rounds"], "median_t": v.loc[G_T, "median_rounds"], "mw_p": mw.pvalue}


raw_s, clean_s = gate_summary(c_raw), gate_summary(c)
rows = {
    "Players": lambda s: f"{s['players']:,}",
    "D1 retention, all players": lambda s: f"{s['d1'] * 100:.4f}%",
    "D7 retention, all players": lambda s: f"{s['d7'] * 100:.4f}%",
    "gate_40 − gate_30, D1 (naive)": lambda s: f"{sgn(s['d1_diff'] * 100, 3)} pp (p = {s['d1_p']:.4f})",
    "gate_40 − gate_30, D7 (naive)": lambda s: f"{sgn(s['d7_diff'] * 100, 3)} pp (p = {s['d7_p']:.4f})",
    "Mean rounds, gate_30": lambda s: f"{s['mean_c']:.2f}",
    "Mean rounds, gate_40 − gate_30": lambda s: sgn(s["mean_diff"], 2),
    "Median rounds, gate_30 / gate_40": lambda s: f"{s['median_c']:.0f} / {s['median_t']:.0f}",
    "Mann-Whitney p, rounds by version": lambda s: f"{s['mw_p']:.4f}",
}
sens = pd.DataFrame([{"metric": k, "with the outlier (raw file)": f(raw_s), "without it (analysed)": f(clean_s)}
                     for k, f in rows.items()])

ret_shift = max(abs(raw_s["d1"] - clean_s["d1"]), abs(raw_s["d7"] - clean_s["d7"])) * 100
d7_effect_shift = abs(raw_s["d7_diff"] - clean_s["d7_diff"]) * 100
log_check("CC-5", "Cookie Cats", "Outliers in sum_gamerounds",
          f"1 player at {out_max:,} rounds (next: {second_max:,}), dropped; retention and naive gate differences unchanged "
          f"(D7 difference moves {d7_effect_shift:.3f} pp), gate_30 mean rounds {raw_s['mean_c']:.2f} → {clean_s['mean_c']:.2f}",
          "WARNING")
table(sens)
''')

md("""
**Conclusion:** retention rates, both naive gate differences and their p-values are the same at reported precision with or without the row (overall D1 and D7 move by [[ret_shift]] pp, the D7 difference by [[d7_effect_shift]] pp). Only means move: gate_30's mean rounds fall from [[mean30_raw]] to [[mean30_clean]], and the mean-rounds gap between versions shrinks from [[meandiff_raw]] to [[meandiff_clean]]. One row in 90K cannot move a proportion but can move a mean, which is why rounds are compared on medians and rank tests. The sample-ratio check always uses raw assignment counts (section 8), so the rule cannot affect it.
""")

code('''
def ad_lift(df: pd.DataFrame):
    g = df.groupby("test_group").agg(n=("user_id", "size"), k=("converted", "sum"))
    return S.two_prop_test(g.loc[T, "k"], g.loc[T, "n"], g.loc[CTRL, "k"], g.loc[CTRL, "n"], alpha=C.ALPHA)


tail_rows = []
for label, keep in (("All users (as analysed)", m["total_ads"] >= 1),
                    ("Without users above 1,000 ads", m["total_ads"] <= 1000),
                    ("Without users above 200 ads", m["total_ads"] <= 200)):
    r = ad_lift(m[keep])
    removed = m.loc[~keep, "test_group"].value_counts().reindex([T, CTRL], fill_value=0)
    tail_rows.append({"population": label, "users removed (ad / psa)": f"{removed[T]:,} / {removed[CTRL]:,}",
                      "ad rate (%)": r.rate_t * 100, "psa rate (%)": r.rate_c * 100, "lift (pp)": r.abs_lift * 100,
                      "95% CI (pp)": f"{r.abs_ci_low * 100:.2f} to {r.abs_ci_high * 100:.2f}",
                      "relative lift (%)": r.rel_lift * 100})
tail = pd.DataFrame(tail_rows)

log_check("MKT-5", "Marketing A/B", "Heavy exposure tail (total ads)",
          f"max {m['total_ads'].max():,} ads, kept; lift {tail.loc[0, 'lift (pp)']:.2f} pp → {tail.loc[1, 'lift (pp)']:.2f} pp "
          f"without the {(m['total_ads'] > 1000).sum()} users above 1,000 ads", "PASS")
table(tail, {"ad rate (%)": "{:.3f}", "psa rate (%)": "{:.3f}", "lift (pp)": "{:.2f}", "relative lift (%)": "{:.1f}"})
''')

md("""
**Conclusion:** the exposure tail is long ([[over1000]] users saw more than 1,000 ads, up to [[max_ads]]), but trimming it hardly moves the headline lift: [[lift_all]] pp for everyone, [[lift_1000]] pp without those users, [[lift_200]] pp without the [[over200]] users above 200 ads. All of the users above 1,000 ads are in the ad arm (removed ad / psa: [[removed_1000]]), which is unremarkable when only 4% of users are in PSA. With no dates there is no basis to call heavy exposure an error, so nobody is dropped. Trimming on exposure, a post-assignment variable, is a robustness check here, not a better estimate.
""")

# ------------------------------------------------------------------------------- 6. edge cases
md("""
### 6. Edge cases kept in the data
""")

code('''
zero = c[c["sum_gamerounds"] == 0]
zero_by_v = c.assign(zero=c["sum_gamerounds"] == 0).groupby("version")["zero"].agg(["sum", "mean"])
p_zero = sps.chi2_contingency(pd.crosstab(c["version"], c["sum_gamerounds"] == 0))[1]
flag_no_rounds = zero[zero["retention_1"] | zero["retention_7"]]
d7_wo_d1 = int((c["retention_7"] & ~c["retention_1"]).sum())
d1_without_zero = c.loc[c["sum_gamerounds"] > 0, "retention_1"].mean() * 100

edge = pd.DataFrame([
    {"case": "Installed but played 0 rounds", "players": len(zero),
     "treatment": f"Kept: real installs that left at once. Dropping them would lift D1 from "
                  f"{c['retention_1'].mean() * 100:.1f}% to {d1_without_zero:.1f}%."},
    {"case": "0 rounds, but flagged as back on Day 1 or Day 7", "players": len(flag_no_rounds),
     "treatment": f"Kept ({flag_no_rounds['retention_1'].sum()} on Day 1, {flag_no_rounds['retention_7'].sum()} on Day 7). "
                  "The flags seem to mean 'came back to the game', not 'finished a round' (or round logging is "
                  "incomplete). No conclusion depends on them; question sent to the data owner."},
    {"case": "Back on Day 7 but not on Day 1", "players": d7_wo_d1,
     "treatment": "Kept: plausible behaviour. D7 retention counts these players, so D7 is not a subset of D1."},
])
edge["share of players"] = edge["players"] / len(c)

log_check("CC-6", "Cookie Cats", "Players with 0 rounds", f"{len(zero):,} ({len(zero) / len(c):.1%}), kept", "PASS")
log_check("CC-7", "Cookie Cats", "Return flag with 0 rounds",
          f"{len(flag_no_rounds)} players ({len(flag_no_rounds) / len(c):.2%}): {flag_no_rounds['retention_1'].sum()} on "
          f"Day 1, {flag_no_rounds['retention_7'].sum()} on Day 7; kept, the flags mean 'came back to the game'", "WARNING")
log_check("CC-8", "Cookie Cats", "Back on Day 7 without Day 1",
          f"{d7_wo_d1:,} players ({d7_wo_d1 / len(c):.1%}), plausible, kept", "PASS")
display(table(edge[["case", "players", "share of players", "treatment"]], {"players": "{:,}", "share of players": "{:.2%}"}))

labels_1 = {True: "Back on Day 1", False: "Not back on Day 1"}
labels_7 = {True: "Back on Day 7", False: "Not back on Day 7"}
flags = pd.crosstab(c["retention_1"].map(labels_1), c["retention_7"].map(labels_7), margins=True, margins_name="All players")
flags.map(lambda x: f"{x:,}") + (flags / len(c) * 100).map(lambda p: f" ({p:.1f}%)")
''')

md("""
**Conclusion:** none of these is an error to fix, but they shape the metric definitions. Retention denominators include zero-round installs. The [[zero_d1]] zero-round players flagged as back on Day 1 ([[zero_d7]] on Day 7; [[zero_d1_share]]% of players) show that a "return" means coming back to the game, not finishing a round. D7 retention ([[d7_overall]]%) counts the [[d7_wo_d1]] players who skipped Day 1 ([[d7_wo_d1_share]]% of everyone back on Day 7), so "back on Day 1 and Day 7" ([[d1_and_d7]]% of installs) is a different, stricter metric. Zero-round players are not significantly more common in gate_40 (gate_30 [[zero_g30]]% vs gate_40 [[zero_g40]]%, p = [[p_zero]]), and on their own they could not explain the sample-ratio warning: gate_40's net excess of zero-round players is [[zero_excess]], against [[gate_excess_raw]] extra installs overall in the raw log (section 8).
""")

# ------------------------------------------------------------------------------- 7. time
md("""
### 7. Time coverage
""")

code('''
for check_id, name, df in (("MKT-6", "Marketing A/B", m_raw), ("CC-9", "Cookie Cats", c_raw)):
    print(f"{name} columns: {', '.join(df.columns)}")
    log_check(check_id, name, "Time coverage", "no date or timestamp column", "WARNING")

table(pd.DataFrame([
    ("Marketing A/B", "most ads day", "Weekday on which the user saw the most ads",
     f"{m['most_ads_day'].nunique()} weekdays, no calendar date"),
    ("Marketing A/B", "most ads hour", "Hour in which the user saw the most ads",
     f"{m['most_ads_hour'].nunique()} hours (0–23), timezone not documented"),
    ("Cookie Cats", "sum_gamerounds", "Rounds played in the first 14 days after install", "one 14-day total per player"),
    ("Cookie Cats", "retention_1, retention_7", "Came back to the game on day 1 / day 7 after install (classic day-N)",
     "two flags, no install date"),
], columns=["dataset", "field", "what it measures", "time detail available"]))
''')

md("""
Neither file has a single date. What that rules out:

| Question someone will ask | Answerable? | Why |
|---|---|---|
| Is the ad lift stable over the flight, or a novelty spike that fades? | No | No exposure or conversion dates, so lift can't be tracked over time |
| How long did the test run, and did it cover full weekly cycles? | Partly | Every weekday is someone's peak day, so it ran at least a week; the total length is unknown |
| Was this really last quarter's campaign? | No | No dates; the file is treated as the flight the PM asked about, over an unknown window (assumption A7 in `docs/assumptions.md`) |
| How soon after exposure do users convert, and in what attribution window? | No | No timestamps; `converted` is used as the dataset defines it |
| Do D1 / D7 differ by install date or season? | No | No install date: the file is a single install cohort |
| Does any gate effect persist after the first week? | No | Only D1 and D7 flags; no D14 / D30 |
| Do more rounds cause higher retention? | No | Rounds are counted over the first 14 days, which include Day 7: a player who returns on Day 7 has more days to play, so the rounds–retention link is partly definitional (and players who like the game both play more and come back) |

**Consequence for the readout:** the ad lift is reported as an average over the whole flight; novelty, duration and long-term effects are explicitly out of scope, and the next experiment should log assignment and exposure timestamps (recommendation R4).
""")

# ------------------------------------------------------------------------------- 8. integrity
md("""
### 8. Experiment integrity

Two questions per experiment: do the arm sizes match the split the experiment was supposed to have (sample ratio mismatch, SRM), and do the arms look alike on what we can measure?
""")

code('''
n_ad, n_gate_raw, n_gate = m["test_group"].value_counts(), c_raw["version"].value_counts(), c["version"].value_counts()
srm_ad = S.srm_check(n_ad[T], n_ad[CTRL], C.INTENDED_AD_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)
srm_gate = S.srm_check(n_gate_raw[G_T], n_gate_raw[G_C], C.INTENDED_GATE40_SHARE, C.SRM_FAIL_P, C.SRM_WARN_P)
quota = S.quota_exactness(n_ad[T], n_ad[CTRL], C.INTENDED_AD_SHARE)

srm_tab = pd.DataFrame([
    {"experiment": name, "counts": counts, "treatment": r["n_t"], "control": r["n_c"],
     "intended treatment share": r["intended_share_t"], "observed treatment share": r["observed_share_t"],
     "chi-square": r["chi2"], "p-value": p_txt(r["p_value"]), "SRM test": status, "reading": reading}
    for name, counts, r, status, reading in (
        ("Ad vs PSA", "users in the file", srm_ad,
         f"{srm_ad['status']} (uninformative)" if quota["is_nearest_integer_to_target"] else srm_ad["status"],
         "passes by construction: the split is most likely a fixed quota (next table)"),
        ("gate_40 vs gate_30", "raw assignment counts", srm_gate, srm_gate["status"],
         "can't certify the gate readout until assignment is checked"))])
print(f"SRM rule: p < {C.SRM_FAIL_P} FAIL · p < {C.SRM_WARN_P} WARNING · otherwise PASS")
display(table(srm_tab, {"treatment": "{:,}", "control": "{:,}", "intended treatment share": "{:.0%}",
                        "observed treatment share": "{:.3%}", "chi-square": "{:.2f}"}))

exact_t = (n_ad[T] + n_ad[CTRL]) * C.INTENDED_AD_SHARE
table(pd.DataFrame([
    ("Exactly 96% of all users", f"{exact_t:,.2f}"),
    ("Users in the ad arm", f"{n_ad[T]:,} ({'the' if quota['is_nearest_integer_to_target'] else 'not the'} nearest whole number)"),
    ("Distance from the exact target", f"{quota['deviation_users']:.2f} users"),
    ("Standard deviation of the ad-arm count under random assignment", f"{quota['sd_users_under_random_assignment']:.1f} users"),
    ("Probability of landing exactly on the nearest whole number", f"{quota['prob_exactly_nearest_integer']:.2%}"),
], columns=["Ad vs PSA: how exact is the split?", "value"]))
''')

md("""
**Reading (ad vs PSA):** the SRM test passes (p = [[ad_srm_p]]), but it could not have done anything else. The ad arm holds [[n_ad]] users, the nearest whole number to exactly 96% of the [[n_m]] users, [[quota_dev]] users away. Random assignment would scatter that count with a standard deviation of about [[quota_sd]] users, and would land exactly on the nearest whole number only [[quota_prob]] of the time. So the split is most likely a fixed quota (or the public file was trimmed to one). Fixed arm sizes are a valid design; they just make the SRM test pass by construction, so it is reported as **uninformative**, not as a pass. The allocation config from the experimentation platform would settle it; here, the meaningful check is exposure parity.
""")

code('''
by_arm = m.groupby("test_group")["total_ads"]
parity = (pd.DataFrame({"users": by_arm.size(), "mean ads per user": by_arm.mean(),
                        "median ads per user": by_arm.median(), "total ads": by_arm.sum()})
          .loc[[T, CTRL]].reset_index(names="arm"))
ks = sps.ks_2samp(m.loc[m["test_group"] == T, "total_ads"], m.loc[m["test_group"] == CTRL, "total_ads"])
mean_gap = parity.loc[0, "mean ads per user"] / parity.loc[1, "mean ads per user"] - 1
print(f"Mean ads per user, ad vs psa: {mean_gap:+.2%} · KS distance between the two distributions: {ks.statistic:.3f}")
display(table(parity, {"users": "{:,}", "mean ads per user": "{:.2f}", "median ads per user": "{:.0f}", "total ads": "{:,}"}))

shape = share_e[[CTRL, T]].rename(columns={CTRL: "psa (% of arm)", T: "ad (% of arm)"})
shape["ad − psa (pp)"] = shape["ad (% of arm)"] - shape["psa (% of arm)"]
display(table(shape.reset_index(names="total ads seen"),
              {"psa (% of arm)": "{:.1f}", "ad (% of arm)": "{:.1f}", "ad − psa (pp)": lambda v: sgn(v, 1)}))

bal_tab = pd.DataFrame(bal.values())[["variable", "chi2", "df", "p_value", "cramers_v"]]
bal_tab["status"] = np.where(bal_tab["p_value"] >= C.ALPHA, "PASS", np.where(bal_tab["cramers_v"] < 0.1, "WARNING", "FAIL"))
bal_tab["reading"] = np.where(bal_tab["cramers_v"] < 0.1, "tiny difference, detectable only because n is large",
                              "material imbalance")
bal_tab["p_value"] = bal_tab["p_value"].map(p_txt)
bal_status = "FAIL" if (bal_tab["status"] == "FAIL").any() else ("WARNING" if (bal_tab["status"] == "WARNING").any() else "PASS")

log_check("EXP-1", "Marketing A/B", "Sample ratio vs 96/4",
          f"p = {srm_ad['p_value']:.4f}, but the ad arm is the nearest whole number to exactly 96% "
          f"({quota['deviation_users']:.2f} users off; SD under random assignment {quota['sd_users_under_random_assignment']:.0f}; "
          f"probability {quota['prob_exactly_nearest_integer']:.2%}): most likely a fixed quota, a valid design that makes "
          "the test pass by construction, so it is uninformative", "WARNING")
log_check("EXP-2", "Marketing A/B", "Exposure parity (total ads per user)",
          f"mean {parity.loc[0, 'mean ads per user']:.2f} vs {parity.loc[1, 'mean ads per user']:.2f} ({mean_gap:+.2%}); "
          f"shapes differ a little (KS D = {ks.statistic:.3f}, see EXP-3)", "PASS" if abs(mean_gap) < 0.01 else "WARNING")
log_check("EXP-3", "Marketing A/B", "Balance of post-assignment fields (day, hour, exposure)",
          f"Cramér's V {bal_tab['cramers_v'].min():.3f}–{bal_tab['cramers_v'].max():.3f}; segment results exploratory", bal_status)
table(bal_tab, {"chi2": "{:.1f}", "cramers_v": "{:.3f}"})
''')

md("""
**Reading (exposure parity):** both arms received the same delivery volume (mean [[mean_ads_2dp]] ads per user, ad vs psa; medians [[median_ads]]), so the experiment compares ads with PSAs at equal average exposure. The shapes differ a little (KS D = [[ks_d]]): [[sh15_psa]] of PSA users vs [[sh15_ad]] of ad users saw 1–5 ads, and [[sh1120_psa]] vs [[sh1120_ad]] saw 11–20. Peak day, peak hour and exposure bucket all differ significantly but tinily (Cramér's V [[v_range]], far below the 0.1 that usually marks even a small effect). These fields describe delivery after assignment, and the data cannot say whether the differences come from PSA delivery or from ads changing behaviour, so they are never used as covariates and segment results on them are exploratory.

**Gate (gate_40 vs gate_30): where does the net excess sit?** On raw assignment counts gate_40 has [[gate_excess_raw]] more installs than gate_30. (The outlier rule drops one gate_30 player, so in the analysed table the gap is [[gate_excess_clean]].) Both versions are identical below level 30, and a player with fewer than 30 rounds cannot have got past level 30 (rounds ≥ levels; the data has no level field), so a gate can move a player from one rounds band to another only in an edge case: a flawless gate_30 player can already face the gate at exactly 29 rounds. Such players are few (no pile-up at 29 rounds: [[n29_c]] gate_30 vs [[n29_t]] gate_40 players), so the bands are close to, not exactly, gate-free, and each should split about 50/50. The table shows the net excess in gate_40 (gate_40 minus gate_30) in three bands that add up to the total. The bands were chosen after seeing the warning, so their p-values are descriptive: they show where the net excess sits, they are not new tests, and they carry no status.
""")

code('''
raw_rounds = c_raw["sum_gamerounds"]
# Disjoint rounds bands that add up to all players (raw assignment counts, before the outlier rule).
# "fewer than 30 rounds" (the first two bands together: almost none can have met a gate) is kept only
# for the reconciliation with reports/results.json in section 10.
BANDS = {"fewer than 15 rounds": raw_rounds < 15, "15–29 rounds": raw_rounds.between(15, 29),
         "30 or more rounds": raw_rounds >= 30}
band_counts = {}
for name, mask in {**BANDS, "fewer than 30 rounds": raw_rounds < 30}.items():
    v = c_raw.loc[mask, "version"].value_counts()
    chk = S.srm_check(v[G_T], v[G_C], C.INTENDED_GATE40_SHARE)  # used for chi2 and p only: no status for a band
    band_counts[name] = {"n_t": int(v[G_T]), "n_c": int(v[G_C]), "net_excess_t": int(v[G_T] - v[G_C]),
                         "share_t": chk["observed_share_t"], "p_value": chk["p_value"]}
excess_raw = int(n_gate_raw[G_T] - n_gate_raw[G_C])
excess_lt15 = band_counts["fewer than 15 rounds"]["net_excess_t"]
assert sum(band_counts[b]["net_excess_t"] for b in BANDS) == excess_raw, "the bands must add up to the total"
zero_raw = c_raw.loc[raw_rounds == 0, "version"].value_counts()

strat = pd.DataFrame(
    [{"players": "all players (the SRM test, EXP-4)", G_C: srm_gate["n_c"], G_T: srm_gate["n_t"],
      "net excess in gate_40": excess_raw, "gate_40 share": srm_gate["observed_share_t"],
      "p vs 50/50": p_2sig(srm_gate["p_value"])}]
    + [{"players": f"… with {name}", G_C: r["n_c"], G_T: r["n_t"], "net excess in gate_40": r["net_excess_t"],
        "gate_40 share": r["share_t"], "p vs 50/50": f"{p_2sig(r['p_value'])} (descriptive)"}
       for name, r in band_counts.items() if name in BANDS])

log_check("EXP-4", "Cookie Cats", "Sample ratio vs 50/50 (raw assignment counts)",
          f"{n_gate_raw[G_C]:,} vs {n_gate_raw[G_T]:,}, p = {srm_gate['p_value']:.4f}; gate_40 has {excess_raw} more "
          "installs in the raw log; gate readout not certified until assignment is checked", srm_gate["status"])
log_check("EXP-5", "Cookie Cats", "Where the EXP-4 imbalance sits: net excess by rounds band (descriptive)",
          "net excess in gate_40, raw counts: " + ", ".join(
              f"{sgn(r['net_excess_t'], 0)} with {name} (p = {p_2sig(r['p_value'])})"
              for name, r in band_counts.items() if name in BANDS)
          + "; the bands were chosen after seeing the EXP-4 warning, so these p-values are descriptive", "WARNING")
# The one edge case for "gate-free" bands: a flawless gate_30 player can already face the gate at exactly 29 rounds
at29 = c_raw.loc[raw_rounds == 29, "version"].value_counts()
print(f"Players with exactly 29 rounds: {at29[G_C]:,} gate_30 vs {at29[G_T]:,} gate_40 (no pile-up in gate_30)")
table(strat, {G_C: "{:,}", G_T: "{:,}", "net excess in gate_40": lambda v: f"{v:+,}".replace("-", "−"),
              "gate_40 share": "{:.2%}"})
''')

code('''
pre = c.assign(rounds_capped_29=c["sum_gamerounds"].clip(upper=29))
pre_tab = (pre.groupby("version")["rounds_capped_29"].agg(players="size", mean="mean", median="median")
           .loc[[G_C, G_T]].reset_index())
mw_pre = sps.mannwhitneyu(pre.loc[pre["version"] == G_T, "rounds_capped_29"],
                          pre.loc[pre["version"] == G_C, "rounds_capped_29"])
# The same comparison among players with fewer than 30 rounds only (the 30+ players, all capped at 29, removed)
lt30 = c["sum_gamerounds"] < 30
mw_lt30 = sps.mannwhitneyu(c.loc[lt30 & (c["version"] == G_T), "sum_gamerounds"],
                           c.loc[lt30 & (c["version"] == G_C), "sum_gamerounds"])
print(f"Rounds capped at 29 (play before level 30), gate_40 vs gate_30: Mann-Whitney p = {mw_pre.pvalue:.3f}; "
      f"within players with fewer than 30 rounds: p = {mw_lt30.pvalue:.2f}")
log_check("EXP-6", "Cookie Cats", "Pre-gate engagement parity (rounds capped at 29)",
          f"mean {pre_tab.loc[0, 'mean']:.2f} vs {pre_tab.loc[1, 'mean']:.2f} rounds (gate_30 vs gate_40), "
          f"Mann-Whitney p = {mw_pre.pvalue:.3f}: the same imbalance as EXP-4 / EXP-5 seen as a distribution, not "
          f"independent evidence (within fewer than 30 rounds: p = {mw_lt30.pvalue:.2f})", "WARNING")
display(table(pre_tab.rename(columns={"mean": "mean rounds, capped at 29", "median": "median, capped at 29"}),
              {"players": "{:,}", "mean rounds, capped at 29": "{:.2f}", "median, capped at 29": "{:.0f}"}))
cat["gate_engagement_gap"].fig.show()
''')

md("""
**Reading (gate):** the raw assignment counts, [[gate_counts]] (gate_30 vs gate_40), give p = [[gate_srm_p]] against 50/50: below the 0.01 warning line, above the 0.001 failure line, so the status is **WARNING**. The rounds bands locate the [[gate_excess_raw]] extra installs in the raw log: a net excess of [[excess_lt15]] among players with fewer than 15 rounds ([[lt15_counts]], p = [[lt15_p]]), [[ex1529_s]] at 15–29 rounds (p = [[b1529_p]], balanced in number) and [[ex30_s]] at 30+ rounds ([[ge30_counts]], p = [[ge30_p]]). These p-values are descriptive, because the bands were chosen after seeing the warning: they say where the net excess sits, not that each band passed or failed a test. Play before level 30 tells the same story from another angle: rounds capped at 29 average [[pregate_means]] (gate_30 vs gate_40; Mann-Whitney p = [[pregate_p]]), and the chart shows gate_40's curve below gate_30's well before the first gate. That is the same imbalance seen as a distribution, not independent evidence: among players with fewer than 30 rounds alone, the difference is p = [[pregate_lt30_p]]. The gate cannot act on players with fewer than 15 rounds, where the net excess sits, so most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from gate_30); Engineering confirms the cause. Rounds are measured after assignment, so this localizes the problem rather than proving its cause.

**What this means for the gate readout:** it is not certified. Players with fewer than 30 rounds form an approximate negative control: almost none can have met a gate (the exception is a flawless 29-round gate_30 player). `03_ab_test` follows up with their D7 and splits the naive D7 gap into the part the gate could explain and the parts it cannot (recommendation R5). Cookie Cats has no pre-assignment fields, so the sample ratio and play before the first gate are the only randomization checks available.
""")

# ------------------------------------------------------------------------------- 9. published
md("""
### 9. Consistency with published numbers
""")

code('''
def rate(df: pd.DataFrame, metric: str, by: str, group: str) -> float:
    return df.loc[df[by] == group, metric].mean() * 100


published = pd.DataFrame([
    ("Marketing A/B", "Rows", "588,101", f"{len(m_raw):,}", "Kaggle dataset description"),
    ("Marketing A/B", "Conversion rate, ad / psa", "2.55% / 1.79%",
     f"{rate(m_raw, 'converted', 'test group', T):.2f}% / {rate(m_raw, 'converted', 'test group', CTRL):.2f}%",
     "Commonly reported in public notebooks"),
    ("Cookie Cats", "Players", "90,189", f"{len(c_raw):,}", "Dataset / DataCamp project description"),
    ("Cookie Cats", "D1 retention, gate_30 / gate_40", "44.8% / 44.2%",
     f"{rate(c_raw, 'retention_1', 'version', G_C):.1f}% / {rate(c_raw, 'retention_1', 'version', G_T):.1f}%",
     "Widely reported result"),
    ("Cookie Cats", "D7 retention, gate_30 / gate_40", "19.0% / 18.2%",
     f"{rate(c_raw, 'retention_7', 'version', G_C):.1f}% / {rate(c_raw, 'retention_7', 'version', G_T):.1f}%",
     "Widely reported result"),
], columns=["dataset", "number", "published", "this run (raw file)", "source"])
published["status"] = np.where(published["published"] == published["this run (raw file)"], "PASS", "FAIL")
for check_id, name in (("MKT-7", "Marketing A/B"), ("CC-10", "Cookie Cats")):
    p = published[published["dataset"] == name]
    log_check(check_id, name, "Consistency with published numbers", f"{(p['status'] == 'PASS').sum()} of {len(p)} match",
              "PASS" if (p["status"] == "PASS").all() else "FAIL")
table(published)
''')

md("""
**Conclusion:** every number that can be compared with a public source matches at the precision it is usually published, so these are the same file versions others have analysed and our loading does not distort them.
""")

# ------------------------------------------------------------------------------- 10. scorecard
md("""
### 10. DQ scorecard and reconciliation with the pipeline

All checks from sections 1–9 in one place, with the IDs used in `docs/03_data_quality_checks.md`.
""")

code('''
ID_ORDER = [f"MKT-{i}" for i in range(1, 8)] + [f"CC-{i}" for i in range(1, 11)] + [f"EXP-{i}" for i in range(1, 7)]
scorecard = pd.DataFrame(CHECKS).set_index("id").loc[ID_ORDER].reset_index()
assert scorecard["id"].is_unique and len(scorecard) == len(CHECKS), "every check must be logged exactly once"
display(scorecard.groupby(["dataset", "status"]).size().unstack(fill_value=0)
        .reindex(columns=["PASS", "WARNING", "FAIL"], fill_value=0))
table(scorecard)
''')

code('''
dq_m, dq_c = results["data_quality"]["marketing"], results["data_quality"]["cookie"]
ad_json, gate_json = results["ad"], results["cookie"]["gate"]
v_json = {b["variable"]: b["cramers_v"] for b in ad_json["balance"]}
sh_json = ad_json["heterogeneity"]["exposure_bucket"]["arm_shares"]
strata_json = gate_json["srm_by_stratum"]
pg_json = gate_json["pre_gate_engagement"]
dims = ("most_ads_day", "most_ads_hour", "exposure_bucket")
STRATA_KEYS = {"fewer than 15 rounds": "rounds_lt_15", "15–29 rounds": "rounds_15_29",
               "30 or more rounds": "rounds_ge_30", "fewer than 30 rounds": "rounds_lt_30"}
pairs = [
    ("Marketing rows, raw / clean", f"{len(m_raw):,} / {len(m):,}", f"{dq_m['rows_raw']:,} / {dq_m['rows_clean']:,}"),
    ("Cookie Cats rows, raw / clean", f"{len(c_raw):,} / {len(c):,}", f"{dq_c['rows_raw']:,} / {dq_c['rows_clean']:,}"),
    ("Duplicate IDs, marketing / Cookie Cats", f"{dup_m} / {dup_c}",
     f"{dq_m['duplicate_user_id']} / {dq_c['duplicate_user_id']}"),
    ("Total ads p50 / p99 / p99.9",
     " / ".join(f"{m['total_ads'].quantile(q):.1f}" for q in (.5, .99, .999)),
     f"{dq_m['total_ads_p50']:.1f} / {dq_m['total_ads_p99']:.1f} / {dq_m['total_ads_p999']:.1f}"),
    ("Users with more than 1,000 ads", f"{(m['total_ads'] > 1000).sum()}", f"{dq_m['users_over_1000_ads']}"),
    ("Max rounds, raw / clean", f"{c_raw['sum_gamerounds'].max():,} / {c['sum_gamerounds'].max():,}",
     f"{dq_c['rounds_max_raw']:,} / {dq_c['rounds_max_clean']:,}"),
    ("Zero-round players (raw file)", f"{(c_raw['sum_gamerounds'] == 0).sum():,}", f"{dq_c['zero_round_players']:,}"),
    ("Back on Day 7 without Day 1 (raw file)", f"{(c_raw['retention_7'] & ~c_raw['retention_1']).sum():,}",
     f"{dq_c['d7_without_d1']:,}"),
    ("D1 / D7 retention, analysed (%)", f"{c['retention_1'].mean() * 100:.3f} / {c['retention_7'].mean() * 100:.3f}",
     f"{dq_c['retention_clean']['d1'] * 100:.3f} / {dq_c['retention_clean']['d7'] * 100:.3f}"),
    ("Ad SRM: p-value / status", f"{srm_ad['p_value']:.4f} / {srm_ad['status']}",
     f"{ad_json['srm']['p_value']:.4f} / {ad_json['srm']['status']}"),
    ("Ad split: users off exact 96% / SD under random assignment / P(nearest whole number)",
     f"{quota['deviation_users']:.2f} / {quota['sd_users_under_random_assignment']:.1f} / "
     f"{quota['prob_exactly_nearest_integer']:.2%}",
     f"{ad_json['srm']['deviation_users']:.2f} / {ad_json['srm']['sd_users_under_random_assignment']:.1f} / "
     f"{ad_json['srm']['prob_exactly_nearest_integer']:.2%}"),
    ("Mean ads per user, ad / psa", f"{mean_ads[T]:.2f} / {mean_ads[CTRL]:.2f}",
     f"{ad_json['groups'][T]['mean_ads']:.2f} / {ad_json['groups'][CTRL]['mean_ads']:.2f}"),
    ("KS distance, total ads ad vs psa", f"{ks.statistic:.4f}", f"{ad_json['total_ads_ks']['stat']:.4f}"),
    ("Share with 1–5 / 11–20 ads, psa vs ad (%)",
     f"{share_e.loc['1-5', CTRL]:.1f} vs {share_e.loc['1-5', T]:.1f} / {share_e.loc['11-20', CTRL]:.1f} vs "
     f"{share_e.loc['11-20', T]:.1f}",
     f"{sh_json['1-5']['psa'] * 100:.1f} vs {sh_json['1-5']['ad'] * 100:.1f} / {sh_json['11-20']['psa'] * 100:.1f} vs "
     f"{sh_json['11-20']['ad'] * 100:.1f}"),
    ("Cramér's V, day / hour / exposure", " / ".join(f"{bal[d]['cramers_v']:.3f}" for d in dims),
     " / ".join(f"{v_json[d]:.3f}" for d in dims)),
    ("Gate SRM, raw counts: gate_30 / gate_40 / p / status",
     f"{srm_gate['n_c']:,} / {srm_gate['n_t']:,} / {srm_gate['p_value']:.4f} / {srm_gate['status']}",
     f"{gate_json['srm']['n_c']:,} / {gate_json['srm']['n_t']:,} / {gate_json['srm']['p_value']:.4f} / "
     f"{gate_json['srm']['status']}"),
    ("Gate: extra gate_40 installs in the raw log", f"{excess_raw:,}", f"{gate_json['excess_players_raw']:,}"),
    ("Gate players by rounds band, gate_30 / gate_40: < 15 · 15–29 · 30+ · < 30 rounds",
     " · ".join(f"{band_counts[k]['n_c']:,} / {band_counts[k]['n_t']:,}" for k in STRATA_KEYS),
     " · ".join(f"{strata_json[j]['n_c']:,} / {strata_json[j]['n_t']:,}" for j in STRATA_KEYS.values())),
    ("Gate net excess by rounds band: < 15 · 15–29 · 30+ · < 30 rounds",
     " · ".join(sgn(band_counts[k]["net_excess_t"], 0) for k in STRATA_KEYS),
     " · ".join(sgn(strata_json[j]["net_excess_t"], 0) for j in STRATA_KEYS.values())),
    ("Gate p vs 50/50 by rounds band (descriptive): < 15 · 15–29 · 30+ · < 30 rounds",
     " · ".join(f"{band_counts[k]['p_value']:.4f}" for k in STRATA_KEYS),
     " · ".join(f"{strata_json[j]['p_value']:.4f}" for j in STRATA_KEYS.values())),
    ("Net excess of gate_40 installs with < 15 rounds", f"{excess_lt15:,}",
     f"{gate_json['excess_players_with_lt_15_rounds']:,}"),
    ("Gate players with exactly 29 rounds, gate_30 / gate_40 (raw = analysed)", f"{at29[G_C]:,} / {at29[G_T]:,}",
     " / ".join(f"{gate_json['retention_by_rounds_band']['rounds_29']['retention_7'][k]:,}" for k in ("n_c", "n_t"))),
    ("Pre-gate rounds (capped at 29): mean gate_30 / gate_40 / Mann-Whitney p / p within < 30 rounds",
     f"{pre_tab.loc[0, 'mean']:.3f} / {pre_tab.loc[1, 'mean']:.3f} / {mw_pre.pvalue:.4f} / {mw_lt30.pvalue:.4f}",
     f"{pg_json['mean_capped_29_c']:.3f} / {pg_json['mean_capped_29_t']:.3f} / {pg_json['mannwhitney_p']:.4f} / "
     f"{pg_json['mannwhitney_p_within_lt_30']:.4f}"),
]
rec = pd.DataFrame(pairs, columns=["number", "this notebook", "reports/results.json"])
rec["status"] = np.where(rec["this notebook"] == rec["reports/results.json"], "PASS", "FAIL")
assert (rec["status"] == "PASS").all(), "notebook and reports/results.json disagree: re-run `python run.py --only analysis`"
table(rec)
''')

md("""
**Conclusion:** no check fails. The WARNINGs are handled (outlier dropped, definition question raised) or carried into the readout as caveats: the ad test's sample-ratio check is uninformative, the gate's sample-ratio warning comes with a net excess of low-engagement installs in gate_40 (EXP-5; EXP-6 is the same imbalance seen in pre-gate play, not a separate finding), delivery fields are post-assignment, and there are no dates. The numbers here match `reports/results.json` exactly.
""")

# =============================================================================== limitations / recs
md("""
## Limitations

- **Definitions come from one-line dataset descriptions.** What counts as a conversion, the attribution window, and what exactly a "return" requires are not documented (section 6 suggests a return does not need a finished round). Metrics use the descriptions as written (`docs/02_metric_definitions.md`, `docs/assumptions.md`).
- **The ad test's split is most likely a fixed quota**, a valid design that leaves its SRM test unable to detect anything. Exposure parity is the meaningful check, and exposure is itself recorded after assignment.
- **No pre-assignment covariates.** Balance can only be checked on fields recorded after assignment (ad test) or, for Cookie Cats, on the sample ratio and on play before the first gate.
- **No dates or timestamps**, so novelty effects, test duration, time to convert and seasonality are out of reach, Cookie Cats is a single install cohort, and `most ads hour` has no documented timezone.
- **The outlier rule is a judgment call.** It changes no retention or experiment conclusion (section 5) but does change mean rounds, so rounds are compared on medians and rank tests.
- **Static public extracts.** These checks show internal consistency and agreement with published numbers; they cannot prove the logging behind the files was right. The gate imbalance most likely comes from assignment or logging (low-engagement installs added to gate_40, or dropped from gate_30); these files cannot say which, and Engineering confirms the cause.
""")

md("""
## Recommendations / next steps

| # | Who | What | Why (evidence in this notebook) | How we'll know it's done |
|---|---|---|---|---|
| 1 | Analytics | Proceed on the analysed tables ([[n_m]] users; [[n_c]] players). Report day / hour / exposure cuts as exploratory and never use them as covariates. | No check fails; the three delivery fields differ slightly by arm (sections 3, 8) | Notebooks 02–03 and the readout label segment results as exploratory |
| 2 | Game PM (Eng + Analytics fix assignment); R5 | Keep the first gate at level 30 and don't certify the gate readout: pull assignment and install logs by date, platform and app version, starting with low-engagement installs (fewer than 15 rounds), where gate_40's net excess of [[excess_lt15]] sits. Re-test only if the gate position matters commercially. | Sample-ratio WARNING, p = [[gate_srm_p]]; the net excess sits with players who never met a gate, and pre-gate play shows the same imbalance (section 8) | Root cause found; any re-test passes the SRM check, with a daily 50/50 group-size check while it runs |
| 3 | Analytics + Eng; R4 | For the next ad test: take the allocation from the experimentation platform's config and write it into the test plan, log assignment and exposure timestamps, capture pre-assignment fields (signup date, platform, country), and run an automatic daily SRM check. The split choice (50/50 or 80/20 instead of 96/4) is argued on power in `03_ab_test`. | The 96/4 split is most likely a fixed quota, so its SRM test passes by construction; no dates; no pre-assignment fields (sections 7, 8) | The next test's DQ log has a documented split, a date range and a balance table on pre-assignment fields |
| 4 | Analytics | Run these checks automatically before every readout: row reconciliation, key uniqueness, nulls, SRM (p < 0.001 hard stop, p < 0.01 warning), and a flag when a split lands exactly on its target. | Cheap, and they caught the issues here (outlier, gate SRM, an ad split that lands exactly on its target) | A failing check blocks the readout in the pipeline |
| 5 | Data owners | Answer the open definition questions: what counts as a conversion and over what window; the timezone of `most ads hour`; whether a return needs a finished round ([[zero_d1]] zero-round players are flagged as back on Day 1); whether the [[out_max]]-round player is a test or bot account. | Sections 2, 5, 6 | Answers recorded in `docs/assumptions.md` |
""")

md("""
## Appendix: numbers quoted in the text, recomputed

Every number written in the text above is recomputed from this run; the cell fails if the text has gone stale.
""")

# =============================================================================== quoted numbers
# key: (label, expression evaluated in the notebook namespace after all cells above have run)
MINUS = '.replace("-", "−")'
QUOTES: dict[str, tuple[str, str]] = {
    "n_m": ("Marketing A/B rows (file = loaded = analysed)",
            "f\"{len(m):,}\" if recon.loc[0, ['rows in file', 'rows loaded', 'rows analysed']].nunique() == 1 else 'mismatch'"),
    "n_c_raw": ("Cookie Cats rows in the file and loaded",
                "f\"{len(c_raw):,}\" if recon.loc[1, 'rows in file'] == len(c_raw) else 'mismatch'"),
    "n_c": ("Cookie Cats rows analysed", "f\"{len(c):,}\""),
    "out_max": ("Outlier: rounds in 14 days", "f\"{out_max:,}\""),
    "out_per_day": ("Outlier: rounds per day", "f\"{out_max / 14:,.0f}\""),
    "out_per_min": ("Outlier: rounds per minute, around the clock", "f\"{out_max / 14 / 24 / 60:.1f}\""),
    "out_d1": ("Outlier: retention_1 flag", "str(bool(c_out.loc[0, 'retention_1']))"),
    "second_max": ("Next-highest player: rounds", "f\"{second_max:,}\""),
    "second_per_day": ("Next-highest player: rounds per day", "f\"{second_max / 14:.0f}\""),
    "rule": ("Outlier rule: rounds", "f\"{C.GAMEROUNDS_OUTLIER_MAX:,}\""),
    "rule_per_day": ("Outlier rule: rounds per day", "f\"{C.GAMEROUNDS_OUTLIER_MAX / 14:.0f}\""),
    "ret_shift": ("Largest move in overall D1 / D7 retention from the drop (pp)",
                  "'less than 0.001' if ret_shift < 0.001 else f\"{ret_shift:.4f}\""),
    "d7_effect_shift": ("Move in the naive gate D7 difference from the drop (pp)", "f\"{d7_effect_shift:.3f}\""),
    "mean_inflation": ("Outlier's inflation of gate_30 mean rounds", "f\"{raw_s['mean_c'] - clean_s['mean_c']:.1f}\""),
    "mean30_raw": ("gate_30 mean rounds, with the outlier", "f\"{raw_s['mean_c']:.2f}\""),
    "mean30_clean": ("gate_30 mean rounds, without it", "f\"{clean_s['mean_c']:.2f}\""),
    "meandiff_raw": ("Mean-rounds gap gate_40 − gate_30, with the outlier", "f\"{raw_s['mean_diff']:+.2f}\"" + MINUS),
    "meandiff_clean": ("Mean-rounds gap gate_40 − gate_30, without it", "f\"{clean_s['mean_diff']:+.2f}\"" + MINUS),
    "n_ad": ("Ad arm users", "f\"{n_ad[T]:,}\""),
    "ad_srm_p": ("Ad SRM p-value", "f\"{srm_ad['p_value']:.4f}\""),
    "quota_dev": ("Ad arm: distance from exactly 96% (users)", "f\"{quota['deviation_users']:.2f}\""),
    "quota_sd": ("Ad arm: SD of the count under random assignment (users)",
                 "f\"{quota['sd_users_under_random_assignment']:.0f}\""),
    "quota_prob": ("Probability of landing exactly on the nearest whole number",
                   "f\"{quota['prob_exactly_nearest_integer']:.2%}\""),
    "mean_ads_1dp": ("Mean ads per user (TL;DR: the same in both arms)",
                     "f\"{mean_ads[T]:.1f}\" if f\"{mean_ads[T]:.1f}\" == f\"{mean_ads[CTRL]:.1f}\" else 'differs'"),
    "mean_ads_2dp": ("Mean ads per user, ad vs psa", "f\"{mean_ads[T]:.2f} vs {mean_ads[CTRL]:.2f}\""),
    "median_ads": ("Median ads per user, ad vs psa",
                   "f\"{parity.loc[0, 'median ads per user']:.0f} vs {parity.loc[1, 'median ads per user']:.0f}\""),
    "sh15_psa": ("Share of PSA users with 1–5 ads", "f\"{share_e.loc['1-5', CTRL]:.0f}%\""),
    "sh15_ad": ("Share of ad users with 1–5 ads", "f\"{share_e.loc['1-5', T]:.0f}%\""),
    "sh1120_psa": ("Share of PSA users with 11–20 ads", "f\"{share_e.loc['11-20', CTRL]:.0f}%\""),
    "sh1120_ad": ("Share of ad users with 11–20 ads", "f\"{share_e.loc['11-20', T]:.0f}%\""),
    "ks_d": ("KS distance, total ads by arm", "f\"{ks.statistic:.3f}\""),
    "v_range": ("Cramér's V range, post-assignment fields",
                "f\"{bal_tab['cramers_v'].min():.3f}–{bal_tab['cramers_v'].max():.3f}\""),
    "gate_counts": ("Gate players, gate_30 vs gate_40 (raw assignment counts)",
                    "f\"{n_gate_raw[G_C]:,} vs {n_gate_raw[G_T]:,}\""),
    "gate_srm_p": ("Gate SRM p-value (raw assignment counts)", "f\"{srm_gate['p_value']:.4f}\""),
    "gate_excess_raw": ("Extra installs in gate_40 vs gate_30, raw log", "f\"{excess_raw:,}\""),
    "gate_excess_clean": ("Extra installs in gate_40 vs gate_30, analysed table", "f\"{n_gate[G_T] - n_gate[G_C]:,}\""),
    "excess_lt15": ("Net excess of gate_40 installs with fewer than 15 rounds", "f\"{excess_lt15:,}\""),
    "ex15_s": ("Net excess, fewer than 15 rounds (signed)", "sgn(excess_lt15, 0)"),
    "ex1529_s": ("Net excess, 15–29 rounds (signed)", "sgn(band_counts['15–29 rounds']['net_excess_t'], 0)"),
    "ex30_s": ("Net excess, 30+ rounds (signed)", "sgn(band_counts['30 or more rounds']['net_excess_t'], 0)"),
    "lt15_counts": ("Players with < 15 rounds, gate_30 vs gate_40",
                    "f\"{band_counts['fewer than 15 rounds']['n_c']:,} vs {band_counts['fewer than 15 rounds']['n_t']:,}\""),
    "lt15_p": ("p vs 50/50, players with < 15 rounds (descriptive)",
               "f\"{band_counts['fewer than 15 rounds']['p_value']:.4f}\""),
    "b1529_p": ("p vs 50/50, players with 15–29 rounds (descriptive)",
                "f\"{band_counts['15–29 rounds']['p_value']:.2f}\""),
    "n29_c": ("Players with exactly 29 rounds, gate_30 (raw counts)", "f\"{at29[G_C]:,}\""),
    "n29_t": ("Players with exactly 29 rounds, gate_40 (raw counts)", "f\"{at29[G_T]:,}\""),
    "ge30_counts": ("Players with 30+ rounds, gate_30 vs gate_40",
                    "f\"{band_counts['30 or more rounds']['n_c']:,} vs {band_counts['30 or more rounds']['n_t']:,}\""),
    "ge30_p": ("p vs 50/50, players with 30+ rounds (descriptive)",
               "f\"{band_counts['30 or more rounds']['p_value']:.2f}\""),
    "pregate_means": ("Mean rounds capped at 29, gate_30 vs gate_40",
                      "f\"{pre_tab.loc[0, 'mean']:.2f} vs {pre_tab.loc[1, 'mean']:.2f}\""),
    "pregate_p": ("Mann-Whitney p, rounds capped at 29", "f\"{mw_pre.pvalue:.3f}\""),
    "pregate_lt30_p": ("Mann-Whitney p, rounds among players with fewer than 30 rounds", "f\"{mw_lt30.pvalue:.2f}\""),
    "zero_excess": ("Net excess of gate_40 installs with 0 rounds (raw counts)", "f\"{zero_raw[G_T] - zero_raw[G_C]:,}\""),
    "shared_ids": ("IDs that appear in both files", "f\"{shared_ids:,}\""),
    "med_ads": ("Median ads per user", "f\"{m['total_ads'].median():.0f}\""),
    "p99_ads": ("99th percentile of ads per user", "f\"{m['total_ads'].quantile(.99):.0f}\""),
    "max_ads": ("Maximum ads per user", "f\"{m['total_ads'].max():,}\""),
    "egap": ("Largest arm gap in exposure-bucket share (pp)", "f\"{egap.max():.1f}\""),
    "egap_psa": ("Bucket where PSA users are over-represented most",
                 "str((share_e[CTRL] - share_e[T]).idxmax()).replace('-', '–')"),
    "egap_ad": ("Bucket where ad users are over-represented most",
                "str((share_e[T] - share_e[CTRL]).idxmax()).replace('-', '–')"),
    "day_share_min": ("Smallest share of users peaking on one weekday (%)", "f\"{day_share.min():.1f}\""),
    "day_share_max": ("Largest share of users peaking on one weekday (%)", "f\"{day_share.max():.1f}\""),
    "dgap": ("Largest arm gap in peak-day share (pp)", "f\"{dgap.max():.1f}\""),
    "dgap_day": ("Day with the largest arm gap", "str(dgap.idxmax())"),
    "hgap": ("Largest arm gap in peak-hour share (pp)", "f\"{hgap.max():.1f}\""),
    "min_ctrl_hour": ("Fewest PSA users in one peak hour", "f\"{ctrl_by_hour.min():,}\""),
    "med_rounds": ("Median rounds (analysed)", "f\"{c['sum_gamerounds'].median():.0f}\""),
    "above_share": ("Share of players above 100 rounds (%)", "f\"{above_share:.1f}\""),
    "rounds_above_share": ("Share of all rounds played by them (%)", "f\"{rounds_above_share:.0f}\""),
    "over1000": ("Users above 1,000 ads", "f\"{(m['total_ads'] > 1000).sum():,}\""),
    "over200": ("Users above 200 ads", "f\"{(m['total_ads'] > 200).sum():,}\""),
    "lift_all": ("Lift, all users (pp)", "f\"{tail.loc[0, 'lift (pp)']:.2f}\""),
    "lift_1000": ("Lift without users above 1,000 ads (pp)", "f\"{tail.loc[1, 'lift (pp)']:.2f}\""),
    "lift_200": ("Lift without users above 200 ads (pp)", "f\"{tail.loc[2, 'lift (pp)']:.2f}\""),
    "removed_1000": ("Users above 1,000 ads, ad / psa", "tail.loc[1, 'users removed (ad / psa)']"),
    "zero_d1": ("Zero-round players flagged back on Day 1", "f\"{flag_no_rounds['retention_1'].sum():,}\""),
    "zero_d7": ("Zero-round players flagged back on Day 7", "f\"{flag_no_rounds['retention_7'].sum():,}\""),
    "zero_d1_share": ("Their share of all players (%)", "f\"{flag_no_rounds['retention_1'].sum() / len(c) * 100:.1f}\""),
    "d7_overall": ("D7 retention, analysed (%)", "f\"{c['retention_7'].mean() * 100:.1f}\""),
    "d7_wo_d1": ("Back on Day 7 without Day 1 (analysed)", "f\"{d7_wo_d1:,}\""),
    "d7_wo_d1_share": ("Their share of everyone back on Day 7 (%)", "f\"{d7_wo_d1 / c['retention_7'].sum() * 100:.0f}\""),
    "d1_and_d7": ("Back on Day 1 and Day 7 (% of installs)",
                  "f\"{(c['retention_1'] & c['retention_7']).mean() * 100:.1f}\""),
    "zero_g30": ("Zero-round share, gate_30 (%)", "f\"{zero_by_v.loc[G_C, 'mean'] * 100:.2f}\""),
    "zero_g40": ("Zero-round share, gate_40 (%)", "f\"{zero_by_v.loc[G_T, 'mean'] * 100:.2f}\""),
    "p_zero": ("p-value, zero-round share by version", "f\"{p_zero:.2f}\""),
}


# =============================================================================== build
def section_of_placeholders() -> dict[str, str]:
    """First markdown section (## / ###) in which each placeholder appears, in document order."""
    where, current = {}, ""
    for kind, src in CELLS:
        if kind != "markdown":
            continue
        for line in src.splitlines():
            h = re.match(r"^#{2,3} (.+)$", line)
            if h:
                current = h.group(1).strip()
            for key in re.findall(r"\[\[(\w+)\]\]", line):
                where.setdefault(key, current)
    return where  # dicts keep insertion order = order of first appearance


def compute_facts() -> dict[str, str]:
    """Run the code cells in-process (charts and displays stubbed) and evaluate every quoted expression."""
    import plotly.graph_objects as go
    go.Figure.show = lambda self, *a, **k: None
    os.chdir(ROOT / "notebooks")
    ns: dict = {"__name__": "__main__"}
    for i, (kind, src) in enumerate(CELLS):
        if kind == "code":
            exec(compile(src, f"<cell {i}>", "exec"), ns)
            ns["display"] = lambda *a, **k: None
    return {k: str(eval(expr, ns)) for k, (_, expr) in QUOTES.items()}


def build() -> None:
    where = section_of_placeholders()
    missing = set(where) - set(QUOTES)
    unused = set(QUOTES) - set(where)
    assert not missing, f"placeholders without a QUOTES entry: {missing}"
    assert not unused, f"QUOTES entries not used in the text: {unused}"
    facts = compute_facts()

    q = lambda text: json.dumps(text, ensure_ascii=False)
    rows = []
    for key in where:  # document order
        label, expr = QUOTES[key]
        rows.append(f"    ({q(where[key])}, {q(label)}, {q(facts[key])},\n     {expr}),")
    check_cell = (
        "quoted = [  # (section, number, as written in the text, recomputed now)\n"
        + "\n".join(rows)
        + "\n]\n"
        "check = pd.DataFrame(quoted, columns=[\"section\", \"number\", \"as written\", \"recomputed\"])\n"
        "check[\"status\"] = np.where(check[\"as written\"] == check[\"recomputed\"], \"PASS\", \"FAIL\")\n"
        "assert (check[\"status\"] == \"PASS\").all(), \"text is out of date: update the numbers marked FAIL\"\n"
        "table(check)"
    )

    nb = nbf.v4.new_notebook()
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "title": NB_TITLE,
    }
    cells = []
    for kind, src in CELLS + [("code", check_cell)]:
        if kind == "markdown":
            src = re.sub(r"\[\[(\w+)\]\]", lambda mt: facts[mt.group(1)], src)
            cells.append(nbf.v4.new_markdown_cell(src))
        else:
            cells.append(nbf.v4.new_code_cell(src))
    for i, cell in enumerate(cells):
        cell["id"] = f"eda-{i:02d}"
    nb.cells = cells
    nbf.validate(nb)
    NB_PATH.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, NB_PATH)
    print(f"wrote {NB_PATH} ({len(cells)} cells)")
    for k, v in facts.items():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    build()
