# 03 — Data Quality Checks (DQ log)

**Owner:** Product Analyst, Growth · **Run date:** 2026-11-03 · **Outcome:** no FAIL; 9 WARNING, each handled or carried into the readout as a caveat (EXP-5 and EXP-6 describe the EXP-4 imbalance; they are not separate problems)

**Evidence:** every number below comes from `notebooks/01_eda.ipynb` (rendered: `reports/notebooks/01_eda.html`). The notebook recomputes each check from the raw files, reconciles the results with `reports/results.json` (its section 10), and fails if any number quoted in its text goes stale. The SQL layer in `sql/` (DuckDB) reproduces these checks independently, and every SQL-reproduced number matches (`reports/tables/sql_reconciliation.csv`). Check IDs (MKT-, CC-, EXP-) are the `id` column of the notebook's DQ scorecard. Assumption IDs (A1, C4, S2, ...) refer to [`assumptions.md`](assumptions.md), metric IDs (M1–M23, plus M4a for exposure concentration) to [`02_metric_definitions.md`](02_metric_definitions.md), and R1–R6 to the recommendations in [`readout.md`](readout.md).

## Summary

| Dataset | Rows: file → loaded → analysed | PASS | WARNING | FAIL | Fit for use? |
|---|---|---|---|---|---|
| Marketing A/B (ad vs PSA) | 588,101 → 588,101 → 588,101 | 7 | 3 | 0 | Yes, for the overall ad readout. Its sample-ratio check is uninformative: the split is most likely a fixed quota, a valid design that makes the test pass by construction, so exposure parity carries the integrity case. Day / hour / exposure segments are exploratory only. |
| Cookie Cats (gate_30 vs gate_40) | 90,189 → 90,189 → 90,188 | 7 | 6 | 0 | Yes, for the retention analysis. The gate readout is not certified: gate_40 has a net excess of low-engagement installs, players who never met a gate, and pre-gate play shows the same imbalance. |

**Changes made to the data:** one row dropped (Cookie Cats `userid` 6390605, 49,854 rounds). Everything else is cosmetic: snake_case names, dropping the marketing file's saved index column, and derived buckets (`src/data.py`).

**What every downstream number has to carry:**

1. **Gate sample-ratio WARNING, with a net excess of low-engagement installs.** On raw assignment counts, 44,700 vs 45,489 players (gate_30 vs gate_40) against an intended 50/50 give p = 0.0086: below the 0.01 warning line, above the 0.001 failure line. gate_40 has 789 more installs in the raw log. By rounds band (raw counts), the net excess is +762 among players with fewer than 15 rounds (p = 0.0002), +70 at 15–29 rounds (p = 0.56) and −43 at 30+ rounds (p = 0.81); the bands were chosen after seeing the warning, so these p-values are descriptive. Pre-gate play (rounds capped at 29) is lower in gate_40 (p = 0.004), but that is the same imbalance seen as a distribution, not independent evidence: within players with fewer than 30 rounds it is p = 0.07. Both versions are identical below level 30, so the gate cannot have put the extra installs there. The gate readout is not certified: keep gate_30 and fix assignment / logging before any re-test (R5).
2. **The ad test's sample-ratio check is uninformative.** The ad arm's 564,577 users are the nearest whole number to exactly 96% of 588,101: 0.04 users off, where random assignment typically misses by about ±150 users and would land exactly there only 0.27% of the time. The split is most likely a fixed quota (or a trimmed export). Fixed arm sizes are a valid design; they just make the SRM test pass by construction. Exposure parity is the meaningful check: 24.82 vs 24.76 ads per user, with slightly different shapes (KS D = 0.040).
3. **No dates or timestamps in either file.** No claims about novelty effects, test duration, time to convert, seasonality, or whether any gate effect persists after Day 7. Cookie Cats is a single install cohort.
4. **Ad-delivery fields are post-assignment.** `total ads`, `most ads day` and `most ads hour` differ slightly by arm (Cramér's V 0.018–0.022). They are never used as covariates, and segment results on them are exploratory.

## Status legend and thresholds

| Status | Meaning |
|---|---|
| PASS | Result as expected; no action needed |
| WARNING | An issue that is handled (for example, a row dropped) or that limits what we can claim. The analysis continues, and the caveat travels with the numbers |
| FAIL | Blocks the analysis until fixed |

- **Sample ratio mismatch (SRM, M12):** two-level rule in `src/stats.py` (`srm_check`; assumption S2), always on raw assignment counts, because assignment happens before any cleaning. p < 0.001 FAIL (the usual SRM convention, after Kohavi et al.); 0.001 ≤ p < 0.01 WARNING (this project's warning band: the readout can't be certified until assignment is checked); otherwise PASS.
- **Quota exactness:** `quota_exactness` in `src/stats.py`. When the treatment count is the nearest whole number to its exact target, the split is most likely a fixed quota (or a trimmed export). That is a valid design, but the SRM test then passes by construction, so it is reported as uninformative, not as a pass.
- **Net excess by rounds band (M19):** arm sizes within rounds bands that are close to, not exactly, gate-free (fewer than 15, 15–29, 30+ rounds; raw counts; see EXP-5), reported as the net excess in gate_40 with a χ² p-value against 50/50. The bands were chosen after seeing the EXP-4 warning, so these p-values are descriptive: they show where the excess sits, carry no status of their own, and do not change the experiment-level status.
- **Balance of other fields:** judged on Cramér's V (below 0.1 = negligible), not on p-values. With 588K users, any difference is "significant".
- **Outliers:** `config.yaml` → `gamerounds_outlier_max: 10000` (more than 10,000 rounds in 14 days, about 714 a day).

## 1. Marketing A/B (`marketing_AB.csv`)

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| MKT-1 | Row reconciliation: file → loaded → analysed | Data lines counted on the raw bytes (minus header), compared with rows loaded by pandas and rows analysed | 588,101 → 588,101 → 588,101 | PASS | None |
| MKT-2 | Primary key unique | Duplicate `user id` values | 0 duplicates in 588,101 rows | PASS | None |
| MKT-3 | Nulls | Null count per column | 0 nulls in 7 columns | PASS | None |
| MKT-4 | Value domains | `user id` unique; `test group` only ad / psa; `converted` boolean; `total ads` whole number ≥ 1; `most ads day` a weekday name, all 7 present; `most ads hour` 0–23, all 24 present; `Unnamed: 0` equals the row number | 7 of 7 field rules hold | PASS | `Unnamed: 0` is a saved pandas index, dropped in `clean_marketing` |
| MKT-5 | Heavy exposure tail (`total ads`) | Percentiles by arm; headline lift (M2) re-run without the tail (section 4) | Min 1, median 13, p99 202, p99.9 499.9, max 2,065. 36 users above 1,000 ads, all in the ad arm | PASS | Kept (assumption A12). With no dates there is no basis to call heavy exposure an error, and trimming leaves the lift at 0.77 pp. Where the lift sits by exposure is M4a (exposure concentration), an exploratory cut |
| MKT-6 | Time coverage | Column inventory | No date or timestamp; only each user's peak weekday and peak hour (timezone not documented) | WARNING | No novelty or duration claims (section 5; assumptions A7, A11); log timestamps in the next test (R4) |
| MKT-7 | Consistency with published numbers | Compared with the dataset description and public analyses | 588,101 rows; conversion (M1) 2.55% (ad) vs 1.79% (psa) | PASS | None |

## 2. Cookie Cats (`cookie_cats.csv`)

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| CC-1 | Row reconciliation: file → loaded → analysed | Same as MKT-1 | 90,189 → 90,189 → 90,188 | PASS | The one row not analysed is the outlier in CC-5 |
| CC-2 | Primary key unique | Duplicate `userid` values | 0 duplicates in 90,189 rows | PASS | None |
| CC-3 | Nulls | Null count per column | 0 nulls in 5 columns | PASS | None |
| CC-4 | Value domains | `version` only gate_30 / gate_40; `sum_gamerounds` whole number ≥ 0; `retention_1`, `retention_7` boolean; `userid` unique | 4 of 4 field rules hold | PASS | None |
| CC-5 | Outliers in `sum_gamerounds` (M11) | Top-20 players checked against the outlier rule | 1 gate_30 player: 49,854 rounds, about 3,561 a day (2.5 a minute around the clock), 17× the next-highest (2,961). The same row has `retention_1` = False, which contradicts that volume | WARNING | Dropped as a logging error (assumption C4). Sensitivity (section 4): no retention or gate conclusion changes; mean rounds do |
| CC-6 | Players with 0 rounds | Count; share by version (chi-square) | 3,994 players (4.4%); gate_30 4.33% vs gate_40 4.52%, p = 0.17 | PASS | Kept: real installs that left at once. Dropping them would raise D1 from 44.5% to 46.5%. On their own they do not explain EXP-4: gate_40's net excess of zero-round installs is 120, against 789 extra installs overall in the raw log |
| CC-7 | Return flag with 0 rounds | Zero-round players with `retention_1` or `retention_7` = True | 111 players (0.12%): 87 on Day 1, 29 on Day 7 | WARNING | Kept. The flags mean "came back to the game", not "finished a round" (or round logging is incomplete); about 0.1% of players, and no conclusion depends on them. Question for the data owner (assumption C2) |
| CC-8 | Back on Day 7 without Day 1 | `retention_7` = True and `retention_1` = False | 3,598 players in the analysed table (3,599 in the raw file): 4.0% of players, 21% of everyone back on Day 7 | PASS | Kept: plausible behaviour. D7 retention (M9: 18.6%; classic day-7, not rolling) is not a subset of D1 (M8); "back on Day 1 and Day 7" (14.6% of installs) is a separate, stricter metric (`docs/02_metric_definitions.md`) |
| CC-9 | Time coverage | Column inventory | No install date, so the file is a single install cohort; rounds are one 14-day total; retention is two flags (Day 1, Day 7) | WARNING | No claims by install date, season or persistence. The 14-day rounds window includes Day 7, so rounds vs retention is partly definitional (assumption C3) |
| CC-10 | Consistency with published numbers | Compared with the DataCamp project description and widely reported results | 90,189 players; D1 44.8% vs 44.2%, D7 19.0% vs 18.2% (gate_30 vs gate_40) | PASS | None |

## 3. Experiment integrity

| # | Check | Method | Result | Status | Action |
|---|---|---|---|---|---|
| EXP-1 | Sample ratio vs 96/4 (ad test, M12) | Chi-square goodness of fit of arm sizes to 96/4; quota exactness (distance from the exact target vs the spread under random assignment) | 564,577 ad vs 23,524 psa; χ² = 0.00, p = 0.9998. 564,577 is the nearest whole number to exactly 96% (564,576.96): 0.04 users off, against a standard deviation of 150 users under random assignment; probability of landing exactly there 0.27% | WARNING | The split is most likely a fixed quota (or an export trimmed to one). Fixed arm sizes are a valid design; they just make the test pass by construction, so it is reported as uninformative, not as a pass. EXP-2 carries the integrity case. Get the allocation config from the experimentation platform (assumption A1, R4) |
| EXP-2 | Exposure parity (total ads per user, M13) | Mean, median and distribution of `total ads` by arm (ads for the ad arm, PSAs for the control arm); KS distance; bucket shares | Mean 24.82 vs 24.76 (+0.25%); median 13 vs 12; KS D = 0.040. 1–5 ads: 33% of PSA vs 30% of ad users; 11–20 ads: 18% vs 22% | PASS | Both arms got the same volume per user, so the test compares ads with PSAs at equal average exposure. The shapes differ a little, and the data can't say whether PSA delivery or ads changing behaviour causes it, so exposure stays an exploratory cut, never a covariate |
| EXP-3 | Balance of post-assignment fields (day, hour, exposure; M13) | Chi-square and Cramér's V across arms | Peak day V = 0.020 (largest share gap 2.6 pp, Thursday); peak hour V = 0.018 (largest gap 1.2 pp; the smallest hour has 23 PSA users); exposure bucket V = 0.022 (largest gap 4.2 pp, 11–20 bucket). All p < 0.0001 | WARNING | The differences are tiny and detectable only because n is large. These fields are recorded after assignment, so they are never used as covariates. Segment lifts are exploratory: one interaction test per dimension (M16), then segment-vs-rest contrasts (M17) with Holm correction (M15), in `03_ab_test` |
| EXP-4 | Sample ratio vs 50/50 (gate test, M12) | Chi-square goodness of fit of raw assignment counts to 50/50 | 45,489 gate_40 vs 44,700 gate_30; χ² = 6.90, p = 0.0086. gate_40 has 789 more installs in the raw log¹ | WARNING | Below the 0.01 warning line, above the 0.001 failure line (assumption S2). The gate readout can't be certified until assignment is debugged (assumption C5, R5). Keeping gate_30 is the status quo, so that decision doesn't wait on this; shipping gate_40 or re-testing would. EXP-5 locates the excess; EXP-6 shows the same imbalance in pre-gate play |
| EXP-5 | Where the EXP-4 imbalance sits: net excess by rounds band (M19) | Arm sizes within rounds bands that are close to, not exactly, gate-free (raw counts; the three bands add up to the total), with a χ² p-value against 50/50 | Fewer than 15 rounds: 20,782 vs 21,544 (gate_30 vs gate_40), net excess +762, p = 0.0002. 15–29 rounds: 7,262 vs 7,332, net excess +70, p = 0.56. 30+ rounds: 16,656 vs 16,613, net excess −43, p = 0.81. The bands were chosen after seeing the EXP-4 warning, so these p-values are descriptive | WARNING | Both versions are identical below level 30, and a player with fewer than 30 rounds cannot have got past level 30 (rounds ≥ levels; assumption C7), so a gate can move a player between bands only in an edge case (C8): a flawless gate_30 player can already face the gate at exactly 29 rounds. Such players are few (no pile-up at 29 rounds: 302 gate_30 vs 311 gate_40), so the bands are close to, not exactly, gate-free. The net excess sits with players who have fewer than 15 rounds, out of any gate's reach, so most likely assignment or logging added low-engagement installs to gate_40 (or dropped them from gate_30); Engineering confirms the cause. Start the investigation with these installs. The status belongs to the check, as part of the EXP-4 warning; no band gets a status of its own |
| EXP-6 | Pre-gate engagement parity (M21) | Mann-Whitney test of rounds capped at 29 (play before level 30, identical in both versions by design), overall and within players with fewer than 30 rounds; engagement-curve gap chart | Mean 16.66 vs 16.43 rounds, median 17 vs 16 (gate_30 vs gate_40); p = 0.004. Within players with fewer than 30 rounds, p = 0.07. gate_40's engagement curve sits below gate_30's well before round 30 | WARNING | The same imbalance as EXP-4 / EXP-5 seen as a distribution, not independent evidence: gate_40's net excess of low-engagement installs pulls its pre-gate play down |

¹ Cleaned counts: the outlier rule drops one gate_30 player, so the analysed table has 45,489 vs 44,699 players (790 more in gate_40), and `src.stats.srm_check` on those counts gives p = 0.0085, the same verdict. The project uses the raw counts throughout.

**What this means for the gate readout.** EXP-4 to EXP-6 localize the problem; they cannot prove its cause, because rounds are measured after assignment. `03_ab_test` follows up with a negative control (M21): players with fewer than 30 rounds never met a gate, yet their D7 is 0.33 pp lower in gate_40 (p = 0.049), which is borderline on its own. Such gap as there is comes from the 15–29 band (−0.87 pp, p = 0.071, balanced in number) rather than the band with fewer than 15 rounds, where the net excess sits (−0.09 pp, p = 0.53), though the two bands' gaps are not distinguishable from each other (p = 0.12). So the extra installs explain the SRM and the player-mix part of the gap, but not this one. `03_ab_test` also splits the naive −0.82 pp D7 gap (M2, M20): player mix −0.29 + players who never met a gate −0.21 + players who could meet the gate −0.32 pp per install (95% CI −0.71 to +0.07; `reports/results.json` → `cookie.gate.d7_decomposition`). About 60% of the naive gap sits where the gate cannot act. The −0.32 pp is the part the gate could explain, not an estimate of its effect: players with 15–29 rounds, who never met a gate, show a similar D7 gap (−0.87 pp, 95% CI −1.82 to +0.07) to players with 30+ rounds (−0.87 pp, 95% CI −1.94 to +0.20). Decision R5 (keep gate_30) follows from that.

**Not checkable with these files:** balance on pre-assignment fields (signup date, platform, country). Neither dataset has any, so for Cookie Cats the sample ratio and play before the first gate are the only randomization checks available. They should be captured in the next test (R4).

## 4. Outlier treatment and sensitivity

**Cookie Cats: one player dropped.** Key numbers with and without the row:

| Metric | With the outlier (raw file, 90,189) | Without it (analysed, 90,188) |
|---|---|---|
| D1 retention, all players | 44.5210% | 44.5214% |
| D7 retention, all players | 18.6065% | 18.6056% |
| gate_40 − gate_30, D1 (naive) | −0.591 pp (p = 0.0744) | −0.592 pp (p = 0.0739) |
| gate_40 − gate_30, D7 (naive) | −0.820 pp (p = 0.0016) | −0.818 pp (p = 0.0016) |
| Mean rounds, gate_30 | 52.46 | 51.34 |
| Mean rounds, gate_40 − gate_30 | −1.16 | −0.04 |
| Median rounds, gate_30 / gate_40 | 17 / 16 | 17 / 16 |
| Mann-Whitney p, rounds by version | 0.0502 | 0.0509 |

Proportions and their tests do not move at reported precision. Only means move: one row in 90K cannot shift a proportion, but it can shift a mean. This is why rounds are compared on medians and rank tests, never on means alone. The sample-ratio check always uses raw assignment counts (EXP-4), so the outlier rule cannot change it.

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
| `retention_1`, `retention_7` | Two flags: came back to the game on day 1 / day 7 after install (classic day-N, not rolling); no install date |

What that rules out:

| Question | Answerable? | Consequence for the readout |
|---|---|---|
| Is the ad lift stable over the flight, or a novelty spike? | No | Lift is reported as a flight average; novelty effect is listed as a risk |
| How long did the test run? | Partly | At least a week (all weekdays present); total length unknown |
| Was this really last quarter's campaign? | No | The file is treated as the flight the PM asked about, over an unknown window (assumption A7) |
| Time to convert, attribution window | No | `converted` used as the dataset defines it |
| Retention by install date or season | No | The file is a single install cohort; retention is reported for the whole install base only |
| Does any gate effect persist after the first week? | No | Only D1 and D7 flags exist |
| Do rounds cause retention? | No | The 14-day rounds window includes Day 7, so rounds vs retention is partly definitional: rounds size the early-churn segment, they are not a Day-0 targeting rule |

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
| 1 | Find the source of the gate sample-ratio mismatch: assignment and install logs by date, platform and app version, starting with the low-engagement installs (fewer than 15 rounds), where gate_40's net excess of 762 sits | Game PM (Eng + Analytics fix assignment) | Checks EXP-4 to EXP-6; blocks certification of the gate readout (assumption C5, R5) | Open |
| 2 | Get the ad test's allocation config from the experimentation platform and write the intended split into the test plan | Growth PM + Eng | Check EXP-1 passes by construction (most likely a fixed quota), so it can't detect anything (assumption A1) | Open |
| 3 | What counts as a conversion, and over what attribution window? | Marketing data owner | Metric definitions (M1; `docs/02_metric_definitions.md`; assumptions A5, A6) | Open |
| 4 | Timezone of `most ads hour` | Marketing data owner | Any delivery-schedule test (R3) depends on it (assumption A11) | Open |
| 5 | Does a "return" (`retention_1` / `retention_7`) require a finished round? 87 zero-round players are flagged as back on Day 1 (29 on Day 7) | Game data owner | Check CC-7; assumption C2 | Open |
| 6 | Is `userid` 6390605 a test or bot account? | Game data owner | Check CC-5; assumption C4 | Open |
| 7 | Next experiment: log assignment and exposure timestamps, capture pre-assignment fields, document the intended split, and run these checks automatically before any readout (an automatic daily SRM check while the test runs: p < 0.001 hard stop, p < 0.01 warning; flag a split that lands exactly on its target) | Analytics + Eng | Checks MKT-6, CC-9, EXP-1, EXP-4 (R4) | Proposed |

## How to reproduce

From the repo root, the same two commands `run.py` runs for each notebook:

```bash
.venv/bin/python -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=600 --ExecutePreprocessor.kernel_name=python3 notebooks/01_eda.ipynb
.venv/bin/python -m jupyter nbconvert --to html --output-dir reports/notebooks notebooks/01_eda.ipynb
```

`python run.py` runs the same two steps as part of the full pipeline. The notebook stops with an error if its numbers no longer match `reports/results.json` or the numbers quoted in its text. Its charts load plotly.js from a CDN; `reports/report.html` is the fully offline version of the analysis.
