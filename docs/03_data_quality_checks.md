# 03 — Data Quality Checks (DQ log)

**Owner:** Product Analyst, Growth · **Run date:** 2026-11-03 · **Outcome:** no FAIL; 6 WARN, each handled or carried into the readout as a caveat

**Evidence:** every number below comes from `notebooks/01_eda.ipynb` (rendered: `reports/notebooks/01_eda.html`). The notebook recomputes each check from the raw files, reconciles the results with `reports/results.json` (its section 10), and fails if any number quoted in its text goes stale. Check IDs (MKT-, CC-, EXP-) are local to this log. Assumption IDs (A1, C4, S2, ...) refer to [`assumptions.md`](assumptions.md), metric IDs (M1–M16) to [`02_metric_definitions.md`](02_metric_definitions.md), and R1–R6 to the recommendations in [`readout.md`](readout.md).

## Summary

| Dataset | Rows: file → loaded → analysed | PASS | WARN | FAIL | Fit for use? |
|---|---|---|---|---|---|
| Marketing A/B (ad vs PSA) | 588,101 → 588,101 → 588,101 | 8 | 2 | 0 | Yes, for the overall ad readout. Day / hour / exposure segments are exploratory only. |
| Cookie Cats (gate_30 vs gate_40) | 90,189 → 90,189 → 90,188 | 7 | 4 | 0 | Yes, for the retention analysis. The gate readout can't be certified until its sample-ratio warning is explained. |

**Changes made to the data:** one row dropped (Cookie Cats `userid` 6390605, 49,854 rounds). Everything else is cosmetic: snake_case names, dropping the marketing file's saved index column, and derived buckets (`src/data.py`).

**What every downstream number has to carry:**

1. **Gate sample-ratio WARN.** 44,699 vs 45,489 players (gate_30 vs gate_40) against an intended 50/50, p = 0.0085: below the 0.01 warning level, above the 0.001 failure level. The gate analysis goes ahead, but the gate readout can't be certified until assignment is checked (R5).
2. **No dates or timestamps in either file.** No claims about novelty effects, test duration, time to convert, seasonality, or whether the gate effect persists after Day 7.
3. **Ad-delivery fields are post-assignment.** `total ads`, `most ads day` and `most ads hour` differ slightly by arm (Cramér's V 0.018–0.022). They are never used as covariates, and segment results on them are exploratory.

## Status legend and thresholds

| Status | Meaning |
|---|---|
| PASS | Result as expected; no action needed |
| WARN | An issue that is handled (for example, a row dropped) or that limits what we can claim. The analysis continues, and the caveat travels with the numbers |
| FAIL | Blocks the analysis until fixed |

- **Sample ratio mismatch (SRM):** two-level rule in `src/stats.py` (`srm_check`; assumption S2): p < 0.001 FAIL, 0.001 ≤ p < 0.01 WARN, otherwise PASS.
- **Balance of other fields:** judged on Cramér's V (below 0.1 = negligible), not on p-values. With 588K users, any difference is "significant".
- **Outliers:** `config.yaml` → `gamerounds_outlier_max: 10000` (more than 10,000 rounds in 14 days, about 714 a day).

## 1. Marketing A/B (`marketing_AB.csv`)

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| MKT-1 | Row reconciliation: file → loaded → analysed | Data lines counted on the raw bytes (minus header), compared with rows loaded by pandas and rows analysed | 588,101 → 588,101 → 588,101 | PASS | None |
| MKT-2 | Primary key unique | Duplicate `user id` values | 0 duplicates in 588,101 rows | PASS | None |
| MKT-3 | Nulls | Null count per column | 0 nulls in 7 columns | PASS | None |
| MKT-4 | Value domains | `test group` only ad / psa; `converted` boolean; `total ads` whole number ≥ 1; `most ads day` a weekday name, all 7 present; `most ads hour` 0–23, all 24 present; `Unnamed: 0` equals the row number | 7 of 7 field rules hold | PASS | `Unnamed: 0` is a saved pandas index, dropped in `clean_marketing` |
| MKT-5 | Heavy exposure tail (`total ads`) | Percentiles by arm; headline lift re-run without the tail (section 4) | Min 1, median 13, p99 202, p99.9 499.9, max 2,065. 36 users above 1,000 ads, all in the ad arm | PASS | Kept. With no dates there is no basis to call heavy exposure an error, and trimming leaves the lift at 0.77 pp |
| MKT-6 | Time coverage | Column inventory | No date or timestamp; only each user's peak weekday and peak hour (timezone not documented) | WARN | No novelty or duration claims (section 5; assumptions A7, A11); log timestamps in the next test (R4) |
| MKT-7 | Consistency with published numbers | Compared with the dataset description and public analyses | 588,101 rows; conversion 2.55% (ad) vs 1.79% (psa) | PASS | None |

## 2. Cookie Cats (`cookie_cats.csv`)

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| CC-1 | Row reconciliation: file → loaded → analysed | Same as MKT-1 | 90,189 → 90,189 → 90,188 | PASS | The one row not analysed is the outlier in CC-5 |
| CC-2 | Primary key unique | Duplicate `userid` values | 0 duplicates in 90,189 rows | PASS | None |
| CC-3 | Nulls | Null count per column | 0 nulls in 5 columns | PASS | None |
| CC-4 | Value domains | `version` only gate_30 / gate_40; `sum_gamerounds` whole number ≥ 0; `retention_1`, `retention_7` boolean | 4 of 4 field rules hold | PASS | None |
| CC-5 | Outliers in `sum_gamerounds` | Top-20 players checked against the outlier rule | 1 gate_30 player: 49,854 rounds, about 3,561 a day (2.5 a minute around the clock), 17× the next-highest (2,961). The same row has `retention_1` = False, which contradicts that volume | WARN | Dropped as a logging error (assumption C4). Sensitivity (section 4): no retention or gate conclusion changes; mean rounds do |
| CC-6 | Players with 0 rounds | Count; share by version (chi-square) | 3,994 players (4.4%); gate_30 4.33% vs gate_40 4.52%, p = 0.17 | PASS | Kept: real installs that left at once. Dropping them would raise D1 from 44.5% to 46.5% |
| CC-7 | Return flag with 0 rounds | Zero-round players with `retention_1` or `retention_7` = True | 111 players (0.12%): 87 on Day 1, 29 on Day 7 | WARN | Kept (immaterial). Question for the data owner: does a "return" need a finished round? |
| CC-8 | Back on Day 7 without Day 1 | `retention_7` = True and `retention_1` = False | 3,598 players in the analysed table (3,599 in the raw file): 4.0% of players, 21% of everyone back on Day 7 | PASS | Kept: plausible behaviour. D7 retention (18.6%) is not a subset of D1; "back on Day 1 and Day 7" (14.6% of installs) is a separate, stricter metric (`docs/02_metric_definitions.md`) |
| CC-9 | Time coverage | Column inventory | No install date; rounds are one 14-day total; retention is two flags (Day 1, Day 7) | WARN | No cohort, seasonality or persistence claims. Rounds vs retention is correlation only, because the 14-day rounds window overlaps D7 (assumption C3) |
| CC-10 | Consistency with published numbers | Compared with the DataCamp project description and widely reported results | 90,189 players; D1 44.8% vs 44.2%, D7 19.0% vs 18.2% (gate_30 vs gate_40) | PASS | None |

## 3. Experiment integrity

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| EXP-1 | Sample ratio vs 96/4 (ad test) | Chi-square goodness of fit of arm sizes to 96/4 | 564,577 ad vs 23,524 psa (96.000% ad); χ² = 0.00, p = 0.9998 | PASS | Weak evidence. The 96/4 target is inferred from the observed share (it is not documented; assumption A1), so the check is close to circular; EXP-2 carries more weight |
| EXP-2 | Exposure parity (total ads per user) | Mean and median `total ads` by arm (ads for the ad arm, PSAs for the control arm); KS distance | Mean 24.82 vs 24.76 (+0.25%); median 13 vs 12; KS D = 0.040 | PASS | Both arms were delivered the same volume, so the test compares ads with PSAs at equal exposure |
| EXP-3 | Balance of post-assignment fields (day, hour, exposure) | Chi-square and Cramér's V across arms | Peak day V = 0.020 (largest share gap 2.6 pp, Thursday); peak hour V = 0.018 (largest gap 1.2 pp); exposure bucket V = 0.022 (largest gap 4.2 pp, 11-20 bucket). All p < 0.001 | WARN | The differences are tiny and detectable only because n is large. These fields are recorded after assignment, so they are never used as covariates; segment lifts are exploratory and tested with an interaction test plus Holm / BH correction |
| EXP-4 | Sample ratio vs 50/50 (gate test) | Chi-square goodness of fit of arm sizes to 50/50 | Analysed table: 45,489 gate_40 vs 44,699 gate_30, χ² = 6.92, p = 0.0085. Raw file: 45,489 vs 44,700, p = 0.0086. gate_40 has 790 more players | WARN | Below the 0.01 warning level, above the 0.001 failure level (assumption S2). The analysis continues, but the gate readout can't be certified until assignment is debugged (assumption C5, R5). Keeping gate_30 is the no-change default, so that decision doesn't wait on this; shipping gate_40 or re-running the test would. First lead: see below the table |

**First lead for the gate investigation.** Players with fewer than 30 rounds are unlikely to have reached either gate, so up to that point both versions offer the same game. Yet that is where gate_40's excess sits: 28,044 gate_30 vs 28,876 gate_40 players under 30 rounds (+832, p = 0.0005 against 50/50), while players with 30+ rounds are balanced (16,655 vs 16,613, p = 0.82). The gate is an unlikely cause of an imbalance among players who never reached it, so this points at assignment or logging, for example extra low-engagement installs recorded in gate_40. Rounds are measured after assignment, so this is a lead, not a finding.

**Not checkable with these files:** balance on pre-assignment fields (signup date, platform, country). Neither dataset has any, so for Cookie Cats the sample ratio is the only randomization check available. They should be captured in the next test (R4).

## 4. Outlier treatment and sensitivity

**Cookie Cats: one player dropped.** Key numbers with and without the row:

| Metric | With the outlier (raw file, 90,189) | Without it (analysed, 90,188) |
|---|---|---|
| D1 retention, all players | 44.5210% | 44.5214% |
| D7 retention, all players | 18.6065% | 18.6056% |
| gate_40 − gate_30, D1 | −0.591 pp (p = 0.0744) | −0.592 pp (p = 0.0739) |
| gate_40 − gate_30, D7 | −0.820 pp (p = 0.0016) | −0.818 pp (p = 0.0016) |
| Sample ratio vs 50/50 | p = 0.0086 (WARN) | p = 0.0085 (WARN) |
| Mean rounds, gate_30 | 52.46 | 51.34 |
| Mean rounds, gate_40 − gate_30 | −1.16 | −0.04 |
| Median rounds, gate_30 / gate_40 | 17 / 16 | 17 / 16 |
| Mann-Whitney p, rounds by version | 0.0502 | 0.0509 |

Proportions and their tests do not move at reported precision. Only means move: one row in 90K cannot shift a proportion, but it can shift a mean. This is why rounds are compared on medians and rank tests, never on means.

**Marketing A/B: no rows dropped, so the heavy-exposure tail is tested instead.**

| Population | Users removed (ad / psa) | Ad rate | PSA rate | Lift (95% CI) | Relative lift |
|---|---|---|---|---|---|
| All users (as analysed) | 0 / 0 | 2.555% | 1.785% | 0.77 pp (0.59 to 0.94) | +43.1% |
| Without users above 1,000 ads | 36 / 0 | 2.553% | 1.785% | 0.77 pp (0.59 to 0.93) | +43.0% |
| Without users above 200 ads | 5,694 / 258 | 2.422% | 1.633% | 0.79 pp (0.61 to 0.95) | +48.3% |

The headline lift does not depend on the tail. Trimming on exposure, a post-assignment variable, is a robustness check only, not a better estimate; the readout uses all users.

## 5. Time coverage

Neither file has a single date. What is available:

| Field | What it gives us |
|---|---|
| `most ads day` | Weekday on which each user saw the most ads. All 7 weekdays appear (13.2%–15.7% of users each), so the flight lasted at least a week |
| `most ads hour` | Hour (0–23) in which each user saw the most ads. 89% of users peak between 09:00 and 22:59; timezone not documented |
| `sum_gamerounds` | One total over the first 14 days after install |
| `retention_1`, `retention_7` | Two flags; no install date |

What that rules out:

| Question | Answerable? | Consequence for the readout |
|---|---|---|
| Is the ad lift stable over the flight, or a novelty spike? | No | Lift is reported as a flight average; novelty effect is listed as a risk |
| How long did the test run? | Partly | At least a week (all weekdays present); total length unknown |
| Was this really last quarter's campaign? | No | The file is treated as the flight the PM asked about, over an unknown window (assumption A7) |
| Time to convert, attribution window | No | `converted` used as the dataset defines it |
| Retention by install cohort or season | No | Retention reported for the whole install base only |
| Does gate_40's D7 effect persist after the first week? | No | Only D1 and D7 flags exist |
| Do rounds cause retention? | No | The 14-day rounds window overlaps D7: correlation only |

## 6. Consistency with published numbers

| Dataset | Number | Published | This run (raw file) | Source | Status |
|---|---|---|---|---|---|
| Marketing A/B | Rows | 588,101 | 588,101 | Kaggle dataset description | PASS |
| Marketing A/B | Conversion rate, ad / psa | 2.55% / 1.79% | 2.55% / 1.79% | Commonly reported in public notebooks | PASS |
| Cookie Cats | Players | 90,189 | 90,189 | Dataset / DataCamp project description | PASS |
| Cookie Cats | D1 retention, gate_30 / gate_40 | 44.8% / 44.2% | 44.8% / 44.2% | Widely reported result | PASS |
| Cookie Cats | D7 retention, gate_30 / gate_40 | 19.0% / 18.2% | 19.0% / 18.2% | Widely reported result | PASS |

These are the same file versions others have analysed, and the loading step does not distort them.

## 7. Open questions and follow-ups

| # | Question or action | Owner | Why | Status |
|---|---|---|---|---|
| 1 | Find the source of the gate sample-ratio mismatch: assignment logs by date, platform and app version, starting with the excess of under-30-round players in gate_40 | Game PM + Eng | Check EXP-4; blocks certification of the gate readout (assumption C5, R5) | Open |
| 2 | Document the intended split of the ad test | Growth PM | Check EXP-1 is close to circular without it (assumption A1) | Open |
| 3 | What counts as a conversion, and over what attribution window? | Marketing data owner | Metric definitions (`docs/02_metric_definitions.md`; assumptions A5, A6) | Open |
| 4 | Timezone of `most ads hour` | Marketing data owner | Any day-parting decision (R3) depends on it (assumption A11) | Open |
| 5 | Does a "return" (`retention_1` / `retention_7`) require a finished round? | Game data owner | Check CC-7; assumption C2 | Open |
| 6 | Is `userid` 6390605 a test or bot account? | Game data owner | Check CC-5; assumption C4 | Open |
| 7 | Next experiment: log assignment and exposure timestamps, capture pre-assignment fields, write the intended split into the brief, and run these checks automatically before any readout (SRM: p < 0.001 hard stop, p < 0.01 warning) | Analytics + Eng | Checks MKT-6, CC-9, EXP-1, EXP-4 (R4) | Proposed |

## How to reproduce

From the repo root:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb
.venv/bin/jupyter nbconvert --to html --output-dir reports/notebooks notebooks/01_eda.ipynb
```

`python run.py` runs the same two steps as part of the full pipeline. The notebook stops with an error if its numbers no longer match `reports/results.json` or the numbers quoted in its text.
