# 02 — Metric Definitions

**Owner:** Product Analyst, Growth · **Readers:** Growth PM, Game PM, Onboarding PM, media buyer, Analytics Eng · **Version:** 3.0 · **Date:** 2026-11-03

These definitions exist so that everyone computes each number the same way. Version 1.0 (M1–M16) was written before the analysis. Version 2.0 added methods checks (M17–M21) and sharpened M5, M12, M14, M15 and M16. Version 3.0 adds M4a (where the incremental conversions sit), M22 (engagement where the gate can act) and M23 (the early-churn segment and the R6 test size); it takes the status labels off the M19 subsets, adds the D1 decomposition to M20, sizes the gate re-test at a change fixed in advance (M14) and makes the M17 point estimate the raw difference. Everything added after the first results had been seen is a diagnostic, not a pre-registered test (S7).

The "Current value" rows come from the pipeline output: `reports/results.json` (JSON path in brackets) and `reports/tables/*.csv`. If a deliverable disagrees with those two files, the deliverable is wrong. Every number that the SQL files reproduce matches the Python pipeline; the check-by-check comparison is in `reports/tables/sql_reconciliation.csv`.

Assumptions are referenced by ID (A1, B1, C1, S1, …) and live in [`assumptions.md`](assumptions.md). Row counts, nulls and outliers are in [`03_data_quality_checks.md`](03_data_quality_checks.md). R1–R6 are the recommendations in [`readout.md`](readout.md).

---

## 1. Conventions

| Topic | Convention |
|---|---|
| Arms | Treatment = `ad` (ad experiment) and `gate_40` (gate experiment). Control = `psa` and `gate_30`. Every difference is **treatment − control**. |
| Units | Rates are stored as proportions (0–1) and shown as % with 2 decimals. A difference between two rates is in **percentage points (pp)**, 2 decimals. Relative changes are in %, with 1 decimal here and whole numbers in the PM readout. Counts use thousands separators. Money is written as "USD". Negative numbers in prose use a true minus sign (−). |
| Rounding | `results.json` stores 8 decimals. Every value here is rounded from those, never from a rounded intermediate, so a difference can disagree with the rounded rates in its last digit. Example: 2.55% − 1.79% is shown as +0.77 pp, because the unrounded rates are 2.5547% and 1.7854%. |
| Intervals | 95%, two-sided (α = 0.05) unless stated otherwise. Each metric names its interval method. |
| p-values | Never shown as zero. Two significant digits (p = 0.0086, 0.013, 0.18), four decimals between 0.0001 and 0.001 (p = 0.0002), "p > 0.99" near 1 and "p < 0.0001" below 0.0001 in tables and summaries; technical text may use scientific notation (1.7 × 10⁻¹³). The PM readout uses no p-values at all. |
| Power | MDE and sample sizes use 80% power and two-sided α = 0.05 (S1). Power is evaluated at effect sizes fixed in advance (the smallest lift or change worth acting on: B7, B10, B11) and never at the observed effect (M14). MDE and power describe the design, so they are never compared with an observed estimate. |
| SRM status | PASS / WARNING / FAIL, from the two-level rule in M12 (S2), for the two experiment-level checks only. The rounds-band subsets in M19 were chosen after the gate WARNING was seen, so their p-values are descriptive and they carry no status. |
| Causal wording | Randomized comparisons that pass their checks may use causal verbs ("the ads caused"). The gate comparison is not certified, so gate_40 "shows 0.82 pp lower" D7 and never takes a causal verb. Non-randomized cuts (exposure, peak day, rounds) are "associated with" an outcome. |
| Analysis tables | `fct_ad_exposure_users` has one row per user in the ad experiment. `fct_game_players` has one row per Cookie Cats player. `agg_ad_cells` holds counts by arm × peak day × peak hour × exposure bucket, with the daypart derived from the peak hour. All three are built by `src/data.py`. SQL staging equivalents: `sql/01_stg_marketing_ab.sql`, `sql/05_stg_cookie_cats.sql`. |
| Source of truth | `reports/results.json` holds every headline number. `reports/tables/*.csv` holds the segment tables. `reports/tables/sql_reconciliation.csv` shows that every number the SQL reproduces matches. |

## 2. Populations and filters

### 2.1 Marketing A/B (ad experiment)
- **Unit of analysis:** user (`user id`, renamed to `user_id`). The file has 588,101 rows and 588,101 unique users, with 0 duplicates and 0 nulls in any column.
- **Arms:** `test group` ∈ {`ad`, `psa`}, with 564,577 ad users and 23,524 PSA users.
- **Exclusions:** none. The CSV index column (`Unnamed: 0`) is dropped. The 36 users with more than 1,000 ads (max 2,065) are kept (A12).
- **Who is in the file:** every user saw at least one ad or PSA (`total ads` min = 1). Conversion rates are therefore defined **among users with at least one impression** (an ad in the ad arm, a PSA in the control arm): *served* users, not all *assigned* users (A4).
- **Time window:** the whole experiment flight. The data has no dates (A7).

### 2.2 Cookie Cats (retention analysis and gate experiment)
- **Product:** the company's mobile game, a different product from the app the ads ran in (C1). The Game PM owns the gate decision (R5) and the Onboarding PM the early-churn test (R6).
- **Unit of analysis:** player (`userid`, renamed to `user_id`). The file has 90,189 rows, all unique, with 0 nulls.
- **Raw assignment counts:** 44,700 gate_30 and 45,489 gate_40, so gate_40 has 789 more players in the raw counts. Assignment happens before any cleaning, so the SRM checks (M12, M19) use these counts.
- **Exclusion:** players with `sum_gamerounds` > 10,000 (`config.yaml: gamerounds_outlier_max`). This rule removes exactly one player (`user_id` 6390605, gate_30, 49,854 rounds in 14 days) as a logging error (C4).
- **Analysis population:** **90,188 players**: 44,699 gate_30 and 45,489 gate_40, so gate_40 has 790 more players here. Every retention and effect metric uses this population.
- **Count basis:** say "≈790 extra gate_40 players (789 in the raw counts)" and keep one basis per sentence. The rounds-band net excesses in M19 (+762, +70, −43) are raw counts and add up to 789; they are net differences, not identified players.
- **Sensitivity of the exclusion:** D1 is 44.52% and D7 is 18.61% with or without the excluded player. Mean rounds move from 51.87 to 51.32.
- **Zero-round players:** the 3,994 players with 0 rounds stay in every denominator. They installed the game but never played a round. 87 of them are flagged as returning on Day 1 and 29 on Day 7, so the retention flags mean "came back to the game", not "played a round" (C2). That is about 0.1% of players, and no conclusion depends on it.
- **Time window:** per player, relative to install. D1 and D7 are classic day-N flags: the player came back on day 1 / day 7 after install (M8, M9). Rounds cover the first 14 days. The data has no install dates, so all players form a single install cohort (C6), and nothing can be compared by install date.

### 2.3 Rounds bands (gate experiment)
- **Bands:** fewer than 15 rounds, 15–29 rounds, and 30+ rounds; "fewer than 30" is the first two together. They are cut on `sum_gamerounds` (first 14 days).
- **Meaning:** "30+ rounds" means **"could have reached level 30"**. There is no level field; each level takes at least one round, so rounds ≥ levels and a player with fewer than 30 rounds never reached level 30 (C7). Say "reached level 30" only with that caveat nearby.
- **Why stratifying on rounds is allowed here when stratifying on total ads is not:** ads can change how long a user stays from the first impression, so ad exposure can be caused by treatment (A9). Below level 30 both game versions are identical, so whether a player ever plays 30 rounds cannot depend on the gate, and the bands behave like a pre-treatment trait (C8). The approximation has one known gap: a gate_30 player who clears levels 1–29 in exactly 29 rounds meets the gate below 30 rounds. That pushes in the opposite direction to the observed gaps, and it is why M20 calls its gate part "the part the gate could explain".

## 3. Metric catalogue

| ID | Metric | Role | Current value |
|---|---|---|---|
| M1 | Conversion rate (users with ≥ 1 impression) | Primary metric (ad) | ad 2.55% vs PSA 1.79% |
| M2 | Absolute lift (pp) | Effect size, primary | ad +0.77 pp (0.59 to 0.94); gate D7 −0.82 pp (−1.33 to −0.31), naive and not certified |
| M3 | Relative lift | Secondary | ad +43.1% (+30.0% to +57.5%) |
| M4 | Incremental conversions | Secondary (business) | 4,343 (3,316 to 5,284) |
| M4a | Concentration of incremental conversions by exposure bucket | Exploratory (ad; post-assignment) | 36–200 ads: 17.5% of ad users and 98.5% of the bucket-by-bucket total (4,396 of 4,465); ≤ 20 ads: 66.0% of all users, −0.02 pp |
| M5 | Share of ad-arm conversions that are incremental; last-touch overstatement | Secondary (business) | 30.1% (23.1% to 36.5%); last-touch would overstate the campaign 3.3× (2.7× to 4.3×) |
| M6 | Impressions per incremental conversion | Secondary (business) | 3,227 |
| M7 | Breakeven CPM | Decision threshold | USD 15.49 (11.83 to 18.85) at an assumed USD 50 per conversion |
| M8 | D1 retention | Guardrail (gate); descriptive (retention) | 44.52% |
| M9 | D7 retention (classic) | Primary metric (gate); headline retention | 18.61% |
| M10 | D7 retention conditional on D1 | Diagnostic (retention) | 32.83% if returned on Day 1 vs 7.19% if not |
| M11 | Rounds played (first 14 days) | Segmentation; descriptive gate comparison | median 16, mean 51.32; all-player gate difference −0.04 rounds (−1.38 to +1.30), not a clean guardrail (M22) |
| M12 | Sample ratio mismatch (SRM), raw assignment counts | Test health | ad PASS but uninformative (quota-exact split); gate WARNING (p = 0.0086) |
| M13 | Exposure parity and balance | Test health (ad) | mean ads per user 24.82 vs 24.76; KS D = 0.040 |
| M14 | MDE / power at the smallest lift worth acting on; re-test sizing | Design | MDE 0.26 pp at 96/4 (0.10 pp at 50/50); power for a 10% lift 50.8% at 96/4 vs ≈100% at 50/50; gate re-test at a pre-registered 0.5 pp: 113,669 installs (reacher analysis) or 191,453 (all installs) |
| M15 | Adjusted p-values (Holm / BH) | Rule for reading segments | segments whose lift differs from the rest after Holm: day 2 of 7, hour 0 of 24, daypart 0 of 4 |
| M16 | Interaction test (odds scale) | Rule for reading segments | day p = 0.013 (0.038 across 3 dimensions); hour p = 0.18; daypart p = 0.013, 0.23 without Night |
| M17 | Segment-vs-rest contrast (pp scale) | Heterogeneity (exploratory) | Tuesday-peak users +0.95 pp vs other days; Thursday-peak −0.74 pp; Night +0.45 pp, not different after Holm |
| M18 | Always-on holdout cost | Decision input (R1) | 5% holdout ≈ 29,405 users ≈ 226 conversions forgone per 588K-user flight; the as-run 4% PSA arm already forgoes ≈ 181 |
| M19 | SRM by rounds band (descriptive) | Test health (gate) | net excess in gate_40: +762 with < 15 rounds (p = 0.0002), +70 at 15–29 (p = 0.56), −43 at 30+ (p = 0.81); no status labels |
| M20 | D7 and D1 gap decomposition | Diagnostic (gate) | D7: naive −0.82 pp = player mix −0.29 + never met a gate −0.21 + could meet the gate −0.32 pp; D1: naive −0.59 pp = −0.42 − 0.20 + 0.03 pp |
| M21 | Negative controls | Test health (gate) | never reached level 30: D7 −0.33 pp (p = 0.049, borderline), located at 15–29 rounds; −0.22 pp after removing the net 762; pre-gate rounds differ (p = 0.004) |
| M22 | Engagement where the gate can act (30+ rounds) | Guardrail (gate) | median 75 vs 72 rounds (p = 0.0001); 83.23% vs 81.45% play ≥ 40 rounds |
| M23 | Early-churn segment and R6 test size | Targeting and design (retention) | < 15 rounds: 46.93% of installs, D7 2.27%; R6 needs 30,809 target players ≈ 65,648 installs at 50/50 |

**Metric roles per analysis**

| Analysis | Primary | Secondary | Guardrails / test health | Guardrails missing from this data |
|---|---|---|---|---|
| Ad vs PSA | M1 conversion rate (effect: M2) | M3, M4, M5, M6, M7; M18 for the holdout decision; M4a (exploratory) | M12 SRM vs the intended 96/4 split (uninformative here, see M12); M13 exposure parity | Unsubscribe / complaint rate, cost per acquisition (CPA), opt-outs, revenue per user |
| Gate 30 vs 40 | M9 D7 retention (effect: M2; the part the gate could explain: M20) | (none) | M8 D1 retention, read among players with 30+ rounds (M20); M22 rounds among players with 30+ rounds; M11 all-player rounds (descriptive only); M12 SRM vs 50/50; M19 rounds bands; M21 negative controls | In-app purchase revenue, session length |
| New-player retention (descriptive) | M9 D7 retention | M8, M10, M11; M23 for the R6 target and size | (not an experiment) | First-day play (the R6 targeting rule), install dates |

**Segment analysis (ad, exploratory):** M16 first (one interaction test per dimension, odds scale), then M17 (which segments' lift differs from the rest, pp scale), with the M15 adjustment. Per-segment lifts are descriptive. M4a says where the incremental conversions sit by exposure; it is not a frequency curve.

---

## 4. Metric specs

### M1 · Conversion rate

| Field | Spec |
|---|---|
| Definition | Share of users in an arm who converted during the experiment, among users with at least one impression (an ad in the ad arm, a PSA in the control arm). |
| Formula | `conversion_rate = users with converted = TRUE / users in the arm`. Numerator: `SUM(converted)`. Denominator: `COUNT(user_id)`. |
| Grain | User (`user_id`), computed per arm (`test_group`). |
| Population & filters | All 588,101 users (§2.1); no exclusions. Every user in the file has `total ads` ≥ 1, so the denominator is served users, not assigned users (A4). |
| Time window | The whole flight. The data does not record dates, the conversion event or the attribution window (A5, A6, A7). |
| Source columns | `test group` (renamed `test_group`: `ad` / `psa`) and `converted` (boolean; the raw values are only `True` / `False`). |
| Edge cases | A user counts once, however many ads they saw and however many times they converted. A null `converted` would be a data-quality failure (there are none), never a "no". |
| Computed in | `src/analysis.py` `ad_experiment()` → `src/stats.py` `two_prop_test()`; `sql/02_conversion_by_group.sql`. |
| Current value | [`ad.test`, `ad.groups`] ad **2.55%** (14,423 / 564,577); PSA **1.79%** (420 / 23,524). |

### M2 · Absolute lift (pp)

| Field | Spec |
|---|---|
| Definition | Treatment rate minus control rate. The rate is conversion rate (M1) in the ad experiment and D1 / D7 retention (M8, M9) in the gate experiment. |
| Formula | `abs_lift = rate_t − rate_c`. Stored as a proportion and shown × 100 in pp. |
| Grain | Arm level, computed from user-level counts. |
| Interval & test | **Primary:** the 95% Newcombe hybrid-score interval. **Cross-checks:** the Wald (unpooled) interval and a percentile bootstrap with 10,000 resamples (S4, S5). **p-value:** a two-sided pooled two-proportion z-test, equivalent to Pearson χ² without continuity correction. |
| Population & filters / time window | Same as the underlying rate (M1, M8, M9). |
| Edge cases | Newcombe stays well-behaved when one arm of a segment has 0 conversions; the Wald interval comes out too narrow there, because a 0% rate has zero estimated variance. If both arms are at 0% or both at 100%, p is set to 1. Small segments give wide intervals, so read the interval, not the point estimate. In the gate experiment this is the **naive** comparison of all players: it carries the assignment imbalance (M19) and is not certified; the decomposition is M20. |
| Computed in | `stats.two_prop_test()` (Newcombe via statsmodels `confint_proportions_2indep(method="newcomb")`), `stats.wald_diff_ci()`, `stats.bootstrap_two_prop()` + `stats.percentile_ci()`. SQL reproduces the point estimate, the pooled z statistic and the Wald interval as a cross-check: `sql/02_conversion_by_group.sql` (ad) and `sql/07_gate_experiment.sql` (gate). `sql/09_gate_integrity.sql` also rebuilds the Newcombe interval for the gate comparisons (`ci95_low`, `ci95_high`). The bootstrap and the p-values are Python-only, because DuckDB has no normal CDF. |
| Current value | **Ad** [`ad.test`, `ad.wald_ci`, `ad.bootstrap`]: **+0.77 pp**, 95% CI 0.59 to 0.94. Wald gives 0.60 to 0.94; the bootstrap gives 0.59 to 0.95, with 0 of 10,000 draws ≤ 0. z = 7.37, p = 1.7 × 10⁻¹³ (p < 0.0001). **Gate D7, naive** [`cookie.gate.retention_7`]: **−0.82 pp**, 95% CI −1.33 to −0.31 (bootstrap −1.32 to −0.31), p = 0.0016. Not certified (M12, M19, M21); the part the gate could explain is −0.32 pp per install, and it is not an estimate of the gate's effect (M20). **Gate D1, naive** [`cookie.gate.retention_1`]: −0.59 pp, 95% CI −1.24 to +0.06 (bootstrap −1.24 to +0.06), p = 0.074; among players with 30+ rounds it is +0.08 pp (M20). |

### M3 · Relative lift

| Field | Spec |
|---|---|
| Definition | The treatment rate expressed as a % change on the control rate. |
| Formula | `rel_lift = rate_t / rate_c − 1 = RR − 1`, where `RR` is the risk ratio. |
| Grain | Arm level. |
| Interval | Log risk-ratio (Katz) interval: `exp(ln(RR) ± 1.96 × SE) − 1`, where `SE = sqrt(1/x_t − 1/n_t + 1/x_c − 1/n_c)` (x = conversions, n = users). The percentile bootstrap is the cross-check. |
| Edge cases | Undefined when the control rate is 0. It is then reported as blank, never as infinite. This happens in 6 of the 24 hourly segments (hours 0, 1, 2, 4, 5 and 6). Always report it next to the absolute lift: on a low base rate a large % can be a small pp change. |
| Computed in | `stats.two_prop_test()`; bootstrap via `stats.bootstrap_two_prop()`. SQL: `rel_lift` with its Katz interval (`rel_lift_ci95_low`, `rel_lift_ci95_high`) in `sql/02_conversion_by_group.sql`; `rel_diff` (point estimate) in `sql/07_gate_experiment.sql`. |
| Current value | **Ad** [`ad.test.rel_lift`, `ad.bootstrap.rel_ci`]: **+43.1%**, 95% CI +30.0% to +57.5% (bootstrap +30.5% to +58.4%). **Gate D7 (naive):** −4.3% (−6.9% to −1.7%). **Gate D1 (naive):** −1.3% (−2.7% to +0.1%). |

### M4 · Incremental conversions

| Field | Spec |
|---|---|
| Definition | Conversions in the ad arm that would not have happened without the ads, using the PSA arm's rate as the counterfactual. |
| Formula | `incremental = abs_lift × n_ad = (rate_ad − rate_psa) × users in the ad arm`. Equivalently, `conv_ad − rate_psa × n_ad`. |
| Interval | The M2 Newcombe bounds × `n_ad`. |
| Grain | Experiment total for the ad arm. |
| Population & filters / time window | The 564,577 ad-arm users, over this flight only. |
| Edge cases | Valid only for this population, flight and spend level. It is not a forecast for another budget, audience or season (B4, B6), and it relies on the PSA being a neutral placebo (A10). The bucket-by-bucket total in M4a (4,465) is a different quantity: each bucket uses its own PSA rate. |
| Computed in | `analysis.ad_experiment()`, in the `business` block; `sql/02_conversion_by_group.sql` (`incremental_conversions`, point estimate only). |
| Current value | [`ad.business.incremental_conversions`] **4,343** (95% CI 3,316 to 5,284). |

### M4a · Concentration of incremental conversions by exposure bucket

| Field | Spec |
|---|---|
| Definition | Where the incremental conversions sit across exposure buckets (total ads seen, S8), and what share of users those buckets hold. Answers "where does the lift live?", not "what does an extra ad do?". |
| Formula | Per bucket b: `incremental_b = (rate_ad,b − rate_psa,b) × n_ad,b`. Bucket-by-bucket total: `Σ_b incremental_b`. Share of a set of buckets B: `Σ_(b in B) incremental_b / Σ_b incremental_b`. The ≤ 20-ads group is also compared as one pooled segment with M2, plus its MDE (M14 method) as a design property. |
| Denominators (name them every time) | **≤ 20 ads:** a share of **all users** (both arms): 66.0% (also 66.0% of ad users). **36–200 ads:** a share of **ad users**: 17.5%. **21–35 ads:** a share of ad users: 15.5%. The **98%** is a share of the bucket-by-bucket total (4,465), not of the headline 4,343 (M4) and not of all conversions. |
| Why the total differs from M4 | Each bucket uses its own PSA rate as the counterfactual, and the two arms' mixes across buckets differ slightly (M13), so `Σ_b incremental_b` (4,465) is not `abs_lift × n_ad` (4,343). |
| Edge cases | Buckets 1–5 and 6–10 are slightly negative (−49 and −150), so the 36–200 share (98.5%) is of a total that includes negative terms. Exposure is recorded after assignment and tracks how active a user is (A9, B6): control conversion rises from 0.28% at 1–5 ads to 15.50% at 200+. So this is exploratory: it says the lift lives in heavy users, not that more ads cause more lift, and it is not a frequency curve. The 200+ bucket gives no usable estimate (95% CI −4.93 to +4.10 pp, 258 control users). |
| Grain | Exposure bucket: 1–5, 6–10, 11–20, 21–35, 36–50, 51–100, 101–200, 200+. |
| Computed in | `analysis.ad_experiment()` → `ad.heterogeneity.exposure_bucket.concentration` (`share_users_le_20_ads`, `share_ad_users_le_20_ads`, `share_ad_users_36_200`, `incremental_conversions_by_bucket`, `incremental_conversions_bucketwise_total`, `incremental_conversions_36_200`, `share_incremental_conversions_36_200`, `le_20_ads_pooled`, `bucket_21_35`). Per-bucket point estimates: `incremental_conversions` on the exposure-bucket rows of `sql/04_lift_by_day_and_hour.sql`. |
| Current value | [`ad.heterogeneity.exposure_bucket.concentration`] **36–200 ads:** 17.5% of ad users; 4,396 of the 4,465 bucket-by-bucket incremental conversions (**98.5%**). **≤ 20 ads (pooled):** 66.0% of all users; lift −0.02 pp (95% CI −0.14 to +0.09; p = 0.78) on a 0.51% PSA base; the design could detect 0.18 pp (+35%) with 80% power, so it shows no lift we could measure. **21–35 ads:** 15.5% of ad users; +0.27 pp (95% CI −0.21 to +0.66): inconclusive. Per bucket (1–5 … 200+): −49, −150, +26, +238, +659, +2,586, +1,152, +4. |

### M5 · Share of ad-arm conversions that are incremental, and last-touch overstatement

| Field | Spec |
|---|---|
| Definition | **Share:** the fraction of the ad arm's conversions that the ads caused. **Last-touch overstatement:** how many times a last-touch count, which credits every conversion by an ad-exposed user to the campaign, exceeds the incremental count. |
| Formula | `share = incremental / conv_ad = abs_lift / rate_ad = 1 − 1/RR` (the attributable fraction among the exposed). `overstatement = conv_ad / incremental = 1 / share`. |
| Interval | Share: `1 − 1/(1 + rel_ci_low)` to `1 − 1/(1 + rel_ci_high)`, from the M3 log-RR interval. Overstatement: `1 / share` at the share's bounds. |
| Grain | Experiment total for the ad arm. |
| Edge cases | The complement of the share, about 70%, would have converted anyway. Every ad-arm user saw at least one ad, so last-touch and any-touch attribution coincide here: both would credit all 14,423 ad-arm conversions to the campaign (B9). If other channels take part of that credit, the overstatement is smaller. |
| Computed in | `analysis.ad_experiment()` (`business.share_of_ad_conversions_incremental`, `business.share_of_ad_conversions_incremental_ci`, `business.last_touch_overstatement_x`, `business.last_touch_overstatement_ci`); `sql/02_conversion_by_group.sql` (`incremental_share_of_ad_conversions`, `incremental_share_ci95_low`, `incremental_share_ci95_high`, `last_touch_overstatement_x`, `last_touch_overstatement_ci95_low`, `last_touch_overstatement_ci95_high`). |
| Current value | [`ad.business`] Share **30.1%** (95% CI 23.1% to 36.5%). Last-touch overstatement **3.3×** (95% CI 2.7× to 4.3×): 14,423 credited conversions vs ≈ 4,343 incremental ones. |

### M6 · Impressions per incremental conversion

| Field | Spec |
|---|---|
| Definition | Ad impressions served per incremental conversion. |
| Formula | `SUM(total_ads) over ad-arm users / incremental conversions` = 14,014,701 / 4,343. |
| Grain | Experiment total for the ad arm. |
| Source columns | `total ads` (renamed `total_ads`). In the ad arm this counts ad impressions (A8). The PSA arm's 582,481 impressions are excluded. |
| Edge cases | Point estimate only; no interval is reported. It assumes `total ads` covers the whole flight (A8). |
| Computed in | `analysis.ad_experiment()` (`business.impressions_per_incremental_conversion`). Its inputs `impressions_ad` and `incremental_conversions` are also in `sql/02_conversion_by_group.sql`. |
| Current value | [`ad.business.impressions_per_incremental_conversion`] **≈ 3,227**. |

### M7 · Breakeven CPM

| Field | Spec |
|---|---|
| Definition | The highest price per 1,000 ad impressions at which the value of the incremental conversions still covers the media cost. |
| Formula | `breakeven_CPM = incremental × value_per_conversion / impressions_ad × 1,000`. Also reported: `incremental_value = incremental × value_per_conversion`. |
| Interval | Evaluated at the M4 interval bounds. |
| Inputs that are assumptions | Value per conversion is USD 50, an **illustrative** figure because the data has no revenue (B1). The actual CPM is unknown (B2). Only media cost is counted (B5). |
| Decision rule | The campaign pays back if the actual CPM is below the breakeven CPM. To be safe, compare with the lower bound. |
| Edge cases | The breakeven is linear in the value per conversion: halve the value (USD 25) and the breakeven halves (about USD 7.75). |
| Computed in | `analysis.ad_experiment()` (`business.breakeven_cpm_usd`, `business.incremental_value_usd`); `sql/02_conversion_by_group.sql` (`breakeven_cpm_usd`, point estimate at USD 50); chart `figures.fig_breakeven()`. The dashboard's Experiment Readout page (`/experiment`) recomputes it for any value per conversion and CPM entered. |
| Current value | [`ad.business`] **USD 15.49** (95% CI USD 11.83 to 18.85). Incremental value: USD 217,149 (USD 165,800 to 264,223). Both are at USD 50 per conversion. |

### M8 · D1 retention

| Field | Spec |
|---|---|
| Definition | Share of new players who came back to the game on day 1 after install. |
| Formula | `SUM(retention_1) / COUNT(user_id)`. |
| Grain | Player. |
| Population & filters | 90,188 players (§2.2), including the 3,994 zero-round players. |
| Time window | Day 1 after install. Whether "day" means a calendar day or a 24-hour window is not documented (C2). |
| Source columns | `retention_1` (boolean). |
| Interval | Wilson score interval for a single rate. Differences between rates use M2. |
| Edge cases | A point-in-time flag; it says nothing about days 2–6. A return does not require a finished round: 87 zero-round players have `retention_1` = TRUE (C2). As the gate guardrail, the naive D1 difference carries the same imbalance as D7, so it is read among players with 30+ rounds (M20). |
| Computed in | `src/retention.py` `retention_rates()` (Wilson interval via `stats.wilson_ci()`) and `retention.funnel()`; `sql/06_retention_by_segment.sql`. The gate comparison is in `sql/07_gate_experiment.sql`. |
| Current value | [`cookie.overall`] **44.52%** (95% CI 44.20% to 44.85%). By version [`cookie.by_version`]: gate_30 44.82%, gate_40 44.23%. |

### M9 · D7 retention (classic)

| Field | Spec |
|---|---|
| Definition | Share of new players who came back to the game on day 7 after install. This is **classic** (day-N) retention: activity on day 7 itself. |
| Formula | `SUM(retention_7) / COUNT(user_id)`. |
| Grain | Player. |
| Population & filters | 90,188 players (§2.2). |
| Time window | Day 7 after install (C2). |
| Source columns | `retention_7` (boolean). |
| Interval | Wilson score interval. Differences use M2. |
| Edge cases | **Not** rolling retention (active on day 7 *or later*), **not** "retained through day 7" and **not** "active on any of days 1–7". In the analysis population, 3,598 players have D7 = TRUE but D1 = FALSE: 7.19% of the 50,035 who skipped Day 1 (3,599 in the raw file). 29 zero-round players have D7 = TRUE (C2). D7 is not cumulative, and 1 − D7 is not a churn rate. |
| Computed in | `retention.retention_rates()`; `sql/06_retention_by_segment.sql`; gate comparison in `sql/07_gate_experiment.sql`. |
| Current value | [`cookie.overall`, `cookie.funnel`] **18.61%** (95% CI 18.35% to 18.86%); 14.62% of installs came back on both Day 1 and Day 7. By version: gate_30 19.02%, gate_40 18.20%. |

### M10 · D7 retention conditional on D1

| Field | Spec |
|---|---|
| Definition | D7 retention among players who returned on Day 1, compared with D7 retention among players who did not. |
| Formula | Returned: `SUM(retention_1 AND retention_7) / SUM(retention_1)`. Did not return: `SUM(NOT retention_1 AND retention_7) / SUM(NOT retention_1)`. |
| Grain | Player. |
| Related funnel | Installs → played ≥ 1 round (`sum_gamerounds > 0`) → returned on Day 1 → returned on Day 1 and Day 7. Each share is a share of installs; step conversion is a step divided by the previous step. |
| Edge cases | Both flags are outcomes for the same players, so this is an association: Day-1 return is the earliest strong signal of who stays, not proof that prompting a Day-1 visit lifts D7. The 4.6× figure is a ratio of rates. As a pp gap the difference is 25.64 pp, which is also the R6 ceiling: moving 1 pp of installs to a Day-1 return is worth at most about 0.26 pp of D7, and only if those players then behaved like today's returners (M23). |
| Computed in | `retention.retention_rates(df, "d1_status")` and the last step of `retention.funnel()`; `sql/06_retention_by_segment.sql`. |
| Current value | [`cookie.by_d1_status`, `cookie.funnel`] Returned on Day 1: **32.83%** (13,182 / 40,153). Did not return: **7.19%** (of 50,035). Ratio **4.6×**. Funnel: 95.57% of installs played ≥ 1 round, 44.52% returned on Day 1 and 14.62% returned on both Day 1 and Day 7. |

### M11 · Rounds played (first 14 days)

| Field | Spec |
|---|---|
| Definition | Number of game rounds a player played in the first 14 days after install. |
| Formula | `sum_gamerounds` as delivered (already aggregated per player). Summaries: median, mean, and share playing ≥ k rounds. Buckets: 0 / 1–4 / 5–14 / 15–29 / 30–39 / 40–99 / 100+, cut around the gates at levels 30 and 40 before retention was looked at (S8). |
| Grain | Player. |
| Population & filters | 90,188 players (outlier excluded, §2.2). |
| Time window | First 14 days after install. This **overlaps** the D1 and D7 windows (C3). |
| Source columns | `sum_gamerounds`. |
| Interval (gate comparison) | Difference in means with a user-level percentile bootstrap (2,000 resamples, S4), also on rounds capped at the 99.9th percentile; Mann-Whitney test on the full distribution. |
| Edge cases | Rounds are not levels. `reached_gate_30 = sum_gamerounds ≥ 30` means "could have reached level 30" (§2.3, C7). Because the 14-day window contains day 7, rounds vs retention is partly definitional: it sizes the early-churn segment (M23) and is not a Day-0 targeting rule. The distribution is heavy-tailed: compare arms on the median, a rank test and a bootstrap, not only the mean. **The all-player gate comparison carries the same imbalance as D7** (gate_40 has more low-play installs, M19), so it is descriptive, not a clean guardrail; the engagement guardrail is M22. |
| Computed in | `data.clean_cookie()` (bucket, `reached_gate_30`), `retention.engagement_curve()`, `retention.retention_by_rounds()`; the gate comparison is in `analysis.cookie_analysis()` with `stats.bootstrap_mean_diff()`. SQL: `sql/05_stg_cookie_cats.sql`, `sql/06_retention_by_segment.sql`. |
| Current value | [`data_quality.cookie`, `cookie.by_rounds_bucket`, `cookie.gate.rounds`] Median **16** (half of players play 16 rounds or fewer). Mean 51.32 (51.87 before the exclusion). p99 493. Max 2,961 after the exclusion. 3,994 players (4.43%) played 0 rounds. Players with < 15 rounds: 46.93% of installs, with D7 2.27% (M23). Players with ≥ 30 rounds: 36.89% (33,268), so at most about 37% of installs could have met the level-30 gate. **All-player gate comparison (descriptive):** mean 51.30 (gate_40) vs 51.34 (gate_30), a difference of −0.04 rounds (bootstrap 95% CI −1.38 to +1.30); capped at 1,071 rounds (the 99.9th percentile) −0.07 (−1.31 to +1.25); median 16 vs 17; Mann-Whitney p = 0.051. Not a clean guardrail (see M22). |

### M12 · Sample ratio mismatch (SRM)

| Field | Spec |
|---|---|
| Definition | A test of whether the observed split of units across arms matches the intended allocation. A mismatch means assignment or logging may be broken, and the comparison may be biased. |
| Formula | Pearson χ² goodness of fit, 1 df: `χ² = Σ (O_arm − E_arm)² / E_arm`, where `E_arm = N × intended_share_arm`. |
| Decision rule (S2) | p < 0.001 → **FAIL**: stop, the results are not trustworthy (the threshold follows Kohavi et al.). 0.001 ≤ p < 0.01 → **WARNING**: the results cannot be certified until assignment has been investigated (a project convention). p ≥ 0.01 → **PASS**. The rule applies to the experiment-level check only; subsets chosen after the result (M19) get no status. |
| Grain | Unit of randomization (user / player). |
| Population & filters | **Raw assignment counts**: every assigned unit, before any analysis exclusion, because assignment happens before cleaning, and dropping units after assignment can create or hide a mismatch. Ad: no exclusions, so raw = analysis. Gate: 45,489 vs 44,700, which counts the excluded outlier. |
| Intended allocation | Ad: 96/4, **inferred, not documented** (A1). Gate: 50/50 (C5). |
| Quota-exactness (ad) | `deviation = n_t − N × share_t`, in users, compared with `SD = sqrt(N × share_t × (1 − share_t))`, the spread that independent random assignment would produce. Also the probability that Binomial(N, share_t) lands exactly on the nearest integer to the target. A split on that integer is what a quota or a trimmed export produces: fixed arm sizes are a valid design, but the SRM test then passes by construction and carries no information. |
| Edge cases | With a huge N the test detects tiny imbalances, and that is intended. A PASS on a quota-exact split is uninformative, so the ad check rests on exposure parity (M13). The gate WARNING is localized with M19 and M21. |
| Computed in | `stats.srm_check()` returns `p_value`, `threshold` (0.001), `warn_threshold` (0.01), a three-level `status` and `flag` (true unless PASS). `stats.quota_exactness()` adds `deviation_users`, `sd_users_under_random_assignment`, `is_nearest_integer_to_target` and `prob_exactly_nearest_integer`. Both are called from `analysis.ad_experiment()` / `analysis.cookie_analysis()`. `sql/03_srm_check.sql` reproduces both on raw assignment counts for both experiments, quota columns included (`deviation_users`, `sd_users_under_random_assignment`, `is_nearest_integer_to_target`, `prob_exactly_nearest_integer`); it gets the status by comparing `chi2_stat` with the critical values for p = 0.001 and 0.01, because DuckDB has no χ² CDF. |
| Current value | **Ad** [`ad.srm`]: 564,577 vs 23,524 (observed share 96.00% ad), χ² ≈ 0, p > 0.99 (0.9998) → **PASS** by the rule, but **uninformative**: 564,577 is the nearest integer to 96% of 588,101 (564,576.96), 0.04 users off, against an SD of about 150 users under random assignment. Random assignment lands exactly there with probability 0.27%, so the split is most likely a fixed quota (or a trimmed export). **Gate** [`cookie.gate.srm`]: 45,489 vs 44,700 (observed share 50.44% gate_40), χ² = 6.90, p = 0.0086 → **WARNING** (`flag` = true): below the 0.01 warning line and above the 0.001 hard stop. It blocks certification of the gate result; the decision rests on the status quo (R5). |

### M13 · Exposure parity and balance of post-assignment fields

| Field | Spec |
|---|---|
| Definition | Whether both arms were served the same volume of ad slots (ads or PSAs) with similar timing. |
| Formula | Mean and median `total ads` per user by arm, each arm's share of users by exposure bucket, and distribution tests (Kolmogorov–Smirnov, Mann-Whitney). For the categorical fields (`most ads day`, `most ads hour`, exposure bucket): a χ² test of independence, with Cramér's V = `sqrt(χ² / (N × (min(rows, cols) − 1)))` as the effect size. |
| Grain | User. |
| Edge cases | These fields are recorded **during** the experiment, so they are post-assignment (A9). Small differences are expected, and at N = 588,101 they come out "significant"; Cramér's V and the bucket shares show how big they are. A shape difference can come from PSA delivery or from ads changing behaviour, and this data cannot separate the two. They are diagnostics and exploratory cuts only, never covariates. |
| Computed in | `analysis.ad_experiment()`, `stats.balance_test()`; bucket shares in `ad.heterogeneity.exposure_bucket.arm_shares`. The exposure-parity means are also in `sql/02_conversion_by_group.sql` (`avg_ads_per_user_ad`, `avg_ads_per_user_psa`), and each arm's mix across the segments of all four dimensions (peak day, peak hour, daypart, exposure bucket) is in `sql/04_lift_by_day_and_hour.sql` (`share_of_arm_ad`, `share_of_arm_psa`); the distribution tests are Python-only. |
| Current value | [`ad.groups`, `ad.balance`, `ad.total_ads_ks`, `ad.heterogeneity.exposure_bucket.arm_shares`] Mean ads per user: 24.82 (ad) vs 24.76 (PSA). Median 13 vs 12. The shapes differ a little: 30.1% of ad users vs 33.4% of PSA users saw 1–5 ads; 21.8% vs 17.6% saw 11–20. KS D = 0.040; Mann-Whitney p < 0.0001. Cramér's V: peak day 0.020, peak hour 0.018, exposure bucket 0.022, all with p < 0.0001 because N is huge. |

### M14 · MDE / power at the smallest lift worth acting on, and re-test sizing

| Field | Spec |
|---|---|
| Definition | **MDE:** the smallest true effect the design detects with 80% probability at two-sided α = 0.05. **Power at a stated effect:** the probability that the design detects a true effect of that size. **Required N:** the sample needed to detect a stated effect. The stated effects are fixed in advance: for the ad test, relative lifts of 5%, 10% and 20%, with **10% relative as the smallest lift worth acting on** (B7, `smallest_lift_of_interest_rel`); for a gate re-test, **0.5 pp of D7 per install** (B10); for R6, **+0.5 pp of D7** in the target segment (B11, M23). |
| Formula | Effect size is Cohen's h = `2·asin(sqrt(p_t)) − 2·asin(sqrt(p_c))`. MDE: solve the normal-approximation power equation (`NormalIndPower`) for h, given `n_t`, the ratio `n_c / n_t`, α and power, and convert back with `p_t = sin²(asin(sqrt(p_c)) + h/2)`; then `MDE_abs = p_t − p_c` and `MDE_rel = MDE_abs / p_c`. Power at relative lift r: h between `p_c × (1 + r)` and `p_c`, evaluated for the actual arm sizes and for a 50/50 split of the same total. Required N: solve for `n_t` at a target effect; the total is `n_t / share_t`. **Gate re-test:** install level, `required_total_n(19.02%, −0.5 pp, 0.5)`; reacher analysis, the same change spread over the 36.89% who reach level 30 is `0.5 pp / 0.3689 = 1.36 pp` on their 43.87% D7, so `required_total_n(43.87%, −1.36 pp, 0.5)` reachers, divided by 0.3689 for installs. |
| Inputs | The baseline is the control rate: 1.79% (conversion), 44.82% (D1), 19.02% (D7). The gate re-test also uses D7 among gate_30 players who reached level 30 (43.87%). |
| Not reported: power at the observed effect | Power computed at the *observed* effect is a one-to-one function of the p-value, so it adds no information and is not evidence for or against an effect. It was removed from `results.json` in v2. Power is reported only at effect sizes fixed in advance, which says whether the design could have found the effect that matters. |
| Reading rule | MDE and power describe the design. They are never compared with an observed estimate, for either experiment, and a re-test is never sized at the observed effect. |
| Edge cases | An unbalanced split costs sensitivity because the small arm dominates the variance. The reacher analysis needs fewer installs than the install-level one because it drops the players a gate cannot affect; it must be pre-registered (membership is pre-gate, §2.3). |
| Computed in | `stats.mde()`, `stats.power_at_lift()` (power at a stated effect), `stats.required_total_n()`; `analysis.cookie_analysis()` → `cookie.gate.retest_sizing` and `cookie.early_churn_segment.onboarding_test_sizing`; charts `figures.fig_mde_by_split()` and `figures.fig_power_curve()`, both marking the smallest lift worth acting on (`reference_lift`). Interactive versions: the power panel on the dashboard's Experiment Readout page (`/experiment`) and the sample-size calculator on the Decision page (`/decision`). SQL: the gate re-test sizes only, in `sql/09_gate_integrity.sql` step 6 (`players_needed_5050`, `installs_needed_5050`, closed form on Cohen's h, equal to `results.json` after rounding up); the ad-test MDE and power are Python-only. |
| Current value | **Ad** [`ad.power`]: at 96/4, MDE **0.26 pp** (14.3% relative). The same 588,101 users split 50/50 would detect **0.10 pp** (5.5% relative). **Power for the smallest lift worth acting on** (10% relative = 0.18 pp, about 1,008 conversions per 565K-user ad flight): **50.8% at 96/4 vs ≈100% (99.9%) at 50/50** with the same users. For a 5% lift (0.09 pp): 17.0% vs 72.4%. For a 20% lift (0.36 pp): 97.2% vs ≈100%. Users needed to detect a 10% relative lift: **181,074** at 50/50, 282,928 at 80/20 and **1,178,866** at 96/4. A 50/50 split needs 90,333 users to match the 0.26 pp MDE that 96/4 reaches with 588,101. **Gate, as run** [`cookie.gate.retention_*.mde`]: D1 MDE 0.93 pp (2.1% relative), D7 MDE 0.74 pp (3.9% relative); design quantities only. **Gate re-test** [`cookie.gate.retest_sizing`]: smallest D7 change worth acting on 0.5 pp per install (about 2.6% of gate_30's 19.02%). Analysed over all installs: **191,453** installs at 50/50. Primary analysis among players who reach level 30, pre-registered: 1.36 pp on their 43.87% D7, which needs **41,933** such players, about **113,669** installs at 50/50. **R6:** M23. |

### M15 · Adjusted p-values (Holm / BH)

| Field | Spec |
|---|---|
| Definition | Per-segment p-values adjusted for testing all segments of one dimension at once. Two families per dimension are adjusted separately, because they answer different questions: **(a) segment vs rest** (M17: does this segment's lift differ from the others'? the heterogeneity question) and **(b) per-segment lift** (is the lift in this segment different from 0? descriptive). |
| Family | All segments of one dimension: 7 peak days, 24 peak hours, 4 dayparts or 8 exposure buckets (S6). The interaction tests (M16) are a separate family of 3 explored dimensions. |
| Per-segment test | (a) The M17 contrast (raw point estimate; Agresti–Caffo CI and p). (b) M2 (two-proportion z-test and Newcombe interval) on that segment's users. |
| Methods | **Holm** (step-down; controls the family-wise error rate) is the default and is used in the forest plots. **Benjamini–Hochberg** (controls the false discovery rate) is reported alongside it. **Bonferroni** (p × m, capped at 1) is for reference. "Significant" means adjusted p < 0.05. |
| Reading rule | Run the interaction test (M16) first, then read the segment-vs-rest contrasts (M17). A count of segments whose lift is "significantly different from 0" is **not** evidence of heterogeneity: because the overall lift is real, it mostly reflects each segment's sample size (power). Segment results stay exploratory because the segmenting fields are post-assignment (M13, A9). |
| Edge cases | With no true heterogeneity and no correction, the expected number of false positives among the segment-vs-rest contrasts is m × α: 24 × 0.05 = 1.2 for hours and 7 × 0.05 = 0.35 for days. The contrasts' CI and p use Agresti–Caffo variances, so cells with 0 control conversions do not produce false significance (M17, S10). |
| Computed in | `stats.segment_lifts()`, `stats.adjust_pvalues()` (statsmodels `multipletests` with `holm`, `fdr_bh` or `bonferroni`). Tables: `reports/tables/ad_lift_by_{most_ads_day,most_ads_hour,daypart,exposure_bucket}.csv`, Holm-adjusted (`p_vs_rest_adj`, `differs_adj` for (a); `p_adj`, `significant_adj` for (b)). Counts per method: `ad.heterogeneity.<dimension>.differs_from_rest` and `.lift_positive`. `sql/04_lift_by_day_and_hour.sql` supplies segment counts, rates and the unadjusted flags for both questions (`lift_significant_unadjusted`, `differs_from_rest_unadjusted`) for all four dimensions, daypart included; the adjustment is Python-only. The dashboard's Heterogeneity page (`/heterogeneity`) switches the method live. |
| Current value | **(a) Segments whose lift differs from the rest** [`differs_from_rest`]: day **2 of 7** (Tuesday, Thursday) under every method; hour **0 of 24** under every method, unadjusted included; daypart **0 of 4**; exposure bucket 6 of 8 after Holm (5 Bonferroni, 7 BH, 7 unadjusted). **(b) Segments with a lift ≠ 0, for context only** [`lift_positive`]: day 5 of 7 after Holm and BH (3 Bonferroni); hour 1 of 24 after Holm, BH and Bonferroni (hour 14: +1.25 pp, 95% CI 0.56 to 1.76); daypart 4 of 4; exposure bucket 3 of 8 under every method. |

### M16 · Interaction test

| Field | Spec |
|---|---|
| Definition | A single test per dimension of whether the ad effect differs across that dimension's segments, **on the odds scale**. Because it is one test per dimension, there is no multiple-comparison problem within a dimension. |
| Formula | Binomial GLM (logit link) on segment × arm counts. Additive model: `logit(rate) ~ arm + segment`. Interaction model: `logit(rate) ~ arm × segment`. With one cell per arm × segment the interaction model fits every cell exactly, so the likelihood-ratio statistic equals the **deviance** of the additive model, compared with χ² on (k − 1) df. |
| Multiplicity across dimensions | Three dimensions were explored: peak day, peak hour and exposure bucket (the daypart regroups the hour, so it is not counted again). The day result is also reported Bonferroni-adjusted (p × 3). |
| Scale | Log-odds. A constant odds ratio still produces different pp lifts in segments with different base rates, so M16 (odds scale) and M17 (pp scale) answer slightly different questions and can disagree in sparse or extreme cells. |
| Sensitivity (`sensitivity_stratified`) | The Mantel–Haenszel risk difference stratified on the dimension (a stratum-weighted lift) compared with the crude lift. If they match, the headline is not an artefact of the segment mix (no Simpson reversal). The strata are post-assignment, so this is a sensitivity check, not an adjusted effect (S11). `results.json` also stores the CMH pooled odds ratio and the Breslow–Day test; they are not reported, because a pooled odds ratio over post-assignment strata answers no business question and Breslow–Day repeats the interaction test. |
| Edge cases | `cells_with_zero_conversions` counts arm × segment cells with 0 conversions; by hour there are 6, all of them PSA cells (hours 0, 1, 2, 4, 5 and 6). Sparse cells make the test fragile, so hour and daypart are also tested without Night, hours 0–5 (`lrt_excluding_night`; hour 6 is in Morning, so one zero cell remains in that hour test). The dimensions are post-assignment, so the results are exploratory. |
| Computed in | `stats.interaction_lrt()`, `stats.stratified_summary()`, called from `analysis.ad_experiment()`. The interaction test is Python-only; the stratified lift is also in `sql/04_lift_by_day_and_hour.sql` (`standardized_lift`, one value per dimension, daypart included). |
| Current value | [`ad.heterogeneity.*.lrt`, `.lrt_excluding_night`, `.lrt_p_bonferroni_3_dims`, `.sensitivity_stratified`] **Day:** LR = 16.22, df = 6, p = 0.013; 0.038 after allowing for the 3 dimensions explored. Modest evidence. **Hour:** LR = 29.10, df = 23, p = 0.18; without hours 0–5, p = 0.51 (df = 17). No evidence. **Daypart:** LR = 10.80, df = 3, p = 0.013, driven entirely by Night (0–5), where the PSA arm has 1 conversion among 735 users; without Night, LR = 2.91, df = 2, p = 0.23. No reliable time-of-day pattern. **Exposure bucket:** LR = 43.71, df = 7, p = 2.4 × 10⁻⁷. Strong, but exploratory: exposure is post-assignment and tracks how active a user is (M4a). **Stratified lift (sensitivity):** 0.76 pp by day, 0.77 pp by hour, 0.77 pp by daypart and 0.81 pp by exposure bucket, vs 0.77 pp crude. No Simpson reversal. |

### M17 · Segment-vs-rest contrast

| Field | Spec |
|---|---|
| Definition | How much a segment's lift differs from the lift among all other users of the same dimension, **on the percentage-point scale**. This is the heterogeneity question ("is Tuesday's lift different from the other days'?"), as opposed to the per-segment lift ("is there a lift on Tuesday?"). |
| Formula | Four groups: segment × arm and rest × arm. **Point estimate (raw):** `diff_vs_rest = abs_lift − lift_rest`, from plain proportions, where `lift_rest` is the plain lift among the other segments. **CI and p (Agresti–Caffo):** adjusted proportions `p̃ = (x + 1) / (n + 2)` (one success and one failure added to each group), centre `(p̃_ad,seg − p̃_psa,seg) − (p̃_ad,rest − p̃_psa,rest)`, `SE = sqrt(Σ p̃ (1 − p̃) / (n + 2))` over the four groups; 95% CI = centre ± 1.96 × SE; two-sided z-test p (`p_vs_rest`), adjusted across the dimension's segments (M15). |
| Why Agresti–Caffo for the CI and p | With plain proportions, a cell with 0 control conversions has zero estimated variance, so a small cell can look "significant" by accident. Adding one success and one failure keeps every variance positive (S10). The point estimate stays raw, so it matches `abs_lift − lift_rest` in the tables. |
| Grain | Segment within one dimension. |
| Edge cases | In sparse cells the CI is not centred on the raw point estimate (Night: point +0.45 pp, CI −0.12 to +0.77). In large cells the two centres agree closely: across the 7 peak days they differ by at most 0.03 pp. The segments are post-assignment (A9), so a segment that "differs" is a hypothesis for a randomized test, not a targeting rule. Peak day and peak hour describe the user's habits, recorded after assignment, not a slot that can be bought (A11). Tuesday's contrast partly reflects a low control rate: its PSA arm has 2,907 users and 42 conversions (1.44%, one of the lowest of the week). |
| Computed in | `stats.segment_lifts()` (columns `lift_rest`, `diff_vs_rest`, `diff_vs_rest_ci_low`, `diff_vs_rest_ci_high`, `p_vs_rest`, `p_vs_rest_adj`, `differs_adj`); tables `reports/tables/ad_lift_by_*.csv`; forest plots `figures.fig_lift_forest()` (filled marker = differs from the other segments after Holm). `sql/04_lift_by_day_and_hour.sql` reproduces `lift_rest`, the raw `diff_vs_rest`, the Agresti–Caffo centre `diff_vs_rest_ac` with its 95% CI (`diff_vs_rest_ci95_low`, `diff_vs_rest_ci95_high`) and `z_vs_rest` for all four dimensions; the adjustment is Python-only. |
| Current value | [`reports/tables/ad_lift_by_*.csv`, `ad.heterogeneity.*.segments_differing_holm`] **Day:** Tuesday-peak users' lift is **+0.95 pp** above the other days' (1.60 − 0.65; 95% CI +0.43 to +1.42; Holm-adjusted p = 0.0017); Thursday-peak users' is **−0.74 pp** below (0.14 − 0.88; 95% CI −1.25 to −0.27; Holm-adjusted p = 0.015). Both survive Holm; the other five days do not differ. **Hour:** no hour differs (smallest unadjusted p = 0.12, hour 0). **Daypart:** none differs (Night: +0.45 pp, 95% CI −0.12 to +0.77; Holm-adjusted p = 0.62). **Exposure bucket:** 6 of 8 differ after Holm: 1–5, 6–10, 11–20 and 21–35 ads below the rest; 51–100 and 101–200 above. |

### M18 · Always-on holdout cost

| Field | Spec |
|---|---|
| Definition | The conversions a permanent PSA holdout gives up per flight. It is the price of keeping the campaign's incremental effect measurable after the test (R1). |
| Formula | `held_out_users = N_flight × holdout_share`; `conversions_forgone = held_out_users × abs_lift`; `value_forgone = conversions_forgone × value_per_conversion`. As run: `n_psa × abs_lift`; the step from the as-run share to 5% is the difference. |
| Inputs | `holdout_share` = 5% (B8); `N_flight` = 588,101, this test's size, as the "comparable flight"; `abs_lift` = M2; value per conversion = USD 50, illustrative (B1). |
| Edge cases | Uses the point estimate of the lift. With the M2 interval the cost runs from about 173 to 275 conversions. It assumes the lift carries over to future flights (B4) and ignores the media cost of the PSA impressions. Each figure is against no holdout at all. |
| Computed in | `analysis.ad_experiment()` → `business.always_on_holdout_cost` (`users_per_588k_flight`, `conversions_forgone`, `value_forgone_usd`, `as_run_control_share`, `as_run_control_conversions_forgone`, `extra_conversions_vs_as_run`); `sql/02_conversion_by_group.sql` (`holdout_users`, `holdout_conversions_forgone`, `holdout_value_forgone_usd`, `as_run_control_share`, `as_run_conversions_forgone`, `holdout_extra_conversions_vs_as_run`). |
| Current value | [`ad.business.always_on_holdout_cost`] 5% of 588,101 = **29,405 users**, so ≈ **226 conversions forgone per flight**, ≈ USD 11,310 at an assumed USD 50 per conversion. This test's PSA arm (23,524 users, 4.0%) already forgoes ≈ **181**, so the step from 4% to 5% costs ≈ **45** more. |

### M19 · SRM by rounds band (gate experiment, descriptive)

| Field | Spec |
|---|---|
| Definition | The arm sizes within rounds bands (§2.3), to locate where the gate experiment's imbalance sits. |
| Formula | `net_excess_t = n_gate_40 − n_gate_30` within the band, on raw assignment counts, plus the M12 χ² against 50/50 within the band. |
| Bands | Fewer than 15 rounds, 15–29, fewer than 30 (the first two together) and 30+. Neither gate can change which band below 30 a player falls in (C8). |
| Status | **None.** These subsets were chosen after seeing the experiment-level WARNING, so their p-values are descriptive and never labelled PASS / WARNING / FAIL. The experiment-level status stays the M12 WARNING. |
| Population & filters | Raw assignment counts (the excluded outlier is a gate_30 player with 30+ rounds). The net excesses add up to the raw 789. |
| Related number: best case for gate_40 | `best_case_for_gate_40`: the D7 gap if every one of gate_40's ≈790 extra players (analysis population) never returned and is removed: `rate_7,gate_40 × n_gate_40 / (n_gate_40 − excess) − rate_7,gate_30`, with its M2 interval and p. It is the reading **most favourable** to gate_40. |
| Wording | Say "a net excess of 762 among players with < 15 rounds": it is a difference in counts, not a set of identified players. |
| Computed in | `analysis.cookie_analysis()` → `cookie.gate.srm_by_stratum` (`rounds_lt_15`, `rounds_15_29`, `rounds_lt_30`, `rounds_ge_30`, each with `net_excess_t`), `cookie.gate.excess_players_raw`, `cookie.gate.excess_players_with_lt_15_rounds`, `cookie.gate.best_case_for_gate_40`. SQL: `sql/09_gate_integrity.sql` step 1, the "assigned players" rows for all players and every band (`n_gate_40`, `n_gate_30`, the net excess as `difference`, and `z_stat`, whose square is the χ²), with no status column; step 4 is the best case (population "All players, extra installs removed"). |
| Current value | [`cookie.gate.srm_by_stratum`] **< 15 rounds:** 21,544 gate_40 vs 20,782 gate_30, net **+762**, p = 0.0002. **15–29:** 7,332 vs 7,262, net +70, p = 0.56. **< 30:** 28,876 vs 28,044, net +832, p = 0.0005. **30+:** 16,613 vs 16,656, net −43, p = 0.81 (balanced). **Best case for gate_40** [`cookie.gate.best_case_for_gate_40`]: even if none of the 790 extra gate_40 players came back on Day 7, the D7 gap would still be −0.50 pp (95% CI −1.01 to +0.02, p = 0.057); its interval includes 0. |

### M20 · D7 and D1 gap decomposition (gate experiment)

| Field | Spec |
|---|---|
| Definition | Splits the naive difference (M2) into a part from the player mix and parts from the differences within two strata: players who never reached level 30 and players who could have met the gate. Done for D7 (primary) and D1 (guardrail). |
| Strata | `never_reached_30` (rounds < 30) and `reached_30` (rounds ≥ 30, "could have reached level 30", §2.3), analysis population. |
| Formula | For stratum s and arm a: `w_a,s` = share of arm a's players in s; `r_a,s` = rate of arm a in s. `naive = Σ_s (w_t,s r_t,s − w_c,s r_c,s) = Σ_s within_s + Σ_s composition_s`, with **symmetric weights**: `within_s = (w_t,s + w_c,s)/2 × (r_t,s − r_c,s)` and `composition_s = (w_t,s − w_c,s) × (r_t,s + r_c,s)/2`. The split is exact (no residual), and neither arm is treated as the reference (S12). |
| Reading | The composition part and the never-reached part cannot be gate effects (C8): together they are the share of the naive gap that **sits where the gate cannot act**. `within_reached_30` is **the part the gate could explain, not an estimate of the gate's effect**: it equals the reachers' difference × the average share reaching 30, i.e. the install-level effect if the gate acted only on players who reach it (C9). Its CI is the reachers' M2 interval × that share (the share is treated as fixed). |
| Edge cases | Descriptive accounting, not a causal model. Players with 15–29 rounds never met a gate, yet show the same −0.87 pp D7 gap as players with 30+ rounds (M21), so even the could-be-gate part may not be the gate. "Reached 30" is a rounds proxy (C7); its one known gap (a perfect 29-round gate_30 player who meets the gate) pushes in the opposite direction to the observed gaps. With either arm's shares as weights instead, the parts move by less than 0.01 pp (S12). The 60% says where that part of the gap sits, not what the extra installs account for: even removing all 790 leaves −0.50 pp (M19). Scale the could-be-gate part per 10,000 installs only. |
| Computed in | `analysis.cookie_analysis()` → `cookie.gate.d7_decomposition`, `cookie.gate.d1_decomposition` (`naive_diff`, `composition`, `within_never_reached_30`, `within_reached_30`, `share_reached_30`, `install_level_effect_ci_if_only_reachers`, `detail`); chart `figures.fig_gap_decomposition()`. SQL: `sql/09_gate_integrity.sql` step 3, for D7 and D1 (`share_of_arm_gate_40`, `share_of_arm_gate_30`, `within_term`, `within_ci95_low`, `within_ci95_high`, `composition_term`; the interval scales the band's Newcombe CI). |
| Current value | **D7** [`cookie.gate.d7_decomposition`]: naive **−0.82 pp** = player mix **−0.29** + never met a gate **−0.21** + could meet the gate **−0.32 pp per install** (95% CI −0.71 to +0.07). About 60% of the naive gap (mix + never met a gate) sits where the gate cannot act. The mix part is −0.32 pp from the reached stratum and +0.03 pp from the never-reached one. Stratum shares: 63.48% of gate_40 vs 62.74% of gate_30 never reached 30; on average 36.89% reached it. D7 within strata: never reached 3.93% vs 4.26%; reached 43.00% vs 43.87%, a difference of **−0.87 pp** among reachers (95% CI −1.94 to +0.20). Per 10,000 installs the could-be-gate part is about 32 fewer D7 players (95% CI 71 fewer to 7 more). **D1** [`cookie.gate.d1_decomposition`]: naive −0.59 pp = player mix −0.42 + never met a gate −0.20 + could meet the gate **+0.03 pp per install** (95% CI −0.29 to +0.35). Among reachers D1 is +0.08 pp (95% CI −0.78 to +0.94): no D1 effect where the gate can act; the naive D1 gap is mostly player mix. |

### M21 · Negative controls (gate experiment)

| Field | Spec |
|---|---|
| Definition | Comparisons where the gate cannot have had any effect, so a fair split should show no difference. **(a) Never-reached retention:** D1 and D7 among players with < 30 rounds, who never reached level 30 and so met no gate in either version, also split into < 15 and 15–29 rounds. **(b) Pre-gate engagement:** rounds capped at 29, `min(sum_gamerounds, 29)`, which only counts play before any gate could appear. |
| Formula | (a) M2 within the band; plus the < 30 D7 comparison with gate_40's net excess of < 15-round players removed (assumed never to return, the reading most favourable to "the excess explains it"). (b) Mean of the capped rounds by arm, with a two-sided Mann-Whitney test, for all players and within < 30 rounds. |
| Logic | The two versions are identical until level 30, and a player cannot reach level 30 in fewer than 30 rounds (C7, C8). A difference here means the arms differed for reasons other than the gate. |
| Edge cases | The < 30 D7 control is **borderline on its own** (p = 0.049); it carries weight only because it points the same way as the excess of low-engagement installs (M19). The gap sits with players who played **15–29 rounds**, who are balanced in number, not with the < 15 band that holds the excess; removing the net 762 moves it only to −0.22 pp. So the extra installs explain the SRM and the player-mix part, but not this gap. (b) is the same imbalance seen as a distribution, not independent evidence: within < 30 rounds it is p = 0.073. The D1 control is not out of line (p = 0.36). If players could see the gate's position before reaching it, the controls would be weaker (C8). |
| Computed in | `analysis.cookie_analysis()` → `cookie.gate.negative_control` (`never_reached_30`, `reached_30`, `never_reached_30_excess_removed`), `cookie.gate.retention_by_rounds_band` (`rounds_lt_15`, `rounds_15_29`, `rounds_ge_30`), `cookie.gate.pre_gate_engagement` (`mannwhitney_p`, `mannwhitney_p_within_lt_30`); charts `figures.fig_effect_by_stratum()` and `figures.fig_engagement_gap()`. SQL: `sql/09_gate_integrity.sql` step 2 reproduces (a) for D7 and D1 in every band, the excess-removed comparison included (`value_gate_40`, `value_gate_30`, `difference`, `z_stat`, `ci95_low`, `ci95_high`), and step 5 the capped pre-gate means of (b); the Mann-Whitney tests are Python-only. |
| Current value | **(a)** [`cookie.gate.negative_control.never_reached_30`] 28,876 gate_40 vs 28,044 gate_30 players. D7 3.93% vs 4.26%: **−0.33 pp** (95% CI −0.65 to −0.001, just below 0; p = 0.049). D1 23.54% vs 23.87%: −0.32 pp (−1.02 to +0.37; p = 0.36). By band [`cookie.gate.retention_by_rounds_band`]: **< 15 rounds** D7 −0.09 pp (−0.38 to +0.19; p = 0.53), D1 +0.22 pp (−0.45 to +0.89; p = 0.52); **15–29** D7 **−0.87 pp** (−1.82 to +0.07; p = 0.071), D1 −1.21 pp (−2.83 to +0.42; p = 0.15); **30+** D7 −0.87 pp (−1.94 to +0.20; p = 0.11), D1 +0.08 pp (−0.78 to +0.94; p = 0.85). **Excess removed** [`cookie.gate.negative_control.never_reached_30_excess_removed`]: without the net 762 extra < 15-round players, the < 30 D7 gap is −0.22 pp (−0.55 to +0.11; p = 0.19). **(b)** [`cookie.gate.pre_gate_engagement`] mean capped rounds 16.43 (gate_40) vs 16.66 (gate_30); Mann-Whitney **p = 0.004**; within < 30 rounds p = 0.073. |

### M22 · Engagement where the gate can act (gate guardrail)

| Field | Spec |
|---|---|
| Definition | Rounds played (first 14 days) among players with 30+ rounds: the band that could meet the gate and that is balanced in number (M19). It replaces the all-player comparison (M11) as the gate's engagement guardrail, because that comparison carries the same imbalance as D7. |
| Formula | Median and mean of `sum_gamerounds` by arm within `sum_gamerounds ≥ 30`; a two-sided Mann-Whitney test; the share with ≥ 40 rounds (`share_past_40_rounds`) compared with M2; the difference in means with a user-level percentile bootstrap (2,000 resamples, S4, S5). |
| Population | Analysis population with ≥ 30 rounds: 16,613 gate_40 vs 16,655 gate_30. |
| Edge cases | ≥ 30 rounds means "could have reached level 30" (C7). Past level 30 the versions differ by design (gate_40 players meet their first gate at level 40), so this measures what the later gate does to play, not a balance check. Heavy tail: read the median, the rank test and the ≥ 40 share; the mean is too noisy to read. It says nothing about retention: these players' D7 is −0.87 pp (M20). So the gate shows no sign of a retention benefit, while the extra play is a benefit the Game PM may value (R5). |
| Computed in | `analysis.cookie_analysis()` → `cookie.gate.rounds_among_reachers` (`median_t`, `median_c`, `mannwhitney_p`, `share_past_40_rounds`, `mean_diff`, `mean_diff_boot_ci`), bootstrap seed + 16. SQL: `sql/09_gate_integrity.sql` step 5 (the median, the mean and the share with 40+ rounds among players with 30+ rounds, as `value_gate_40`, `value_gate_30` and `difference`); the Mann-Whitney test and the bootstrap CI are Python-only. |
| Current value | [`cookie.gate.rounds_among_reachers`] Median **75** (gate_40) vs **72** (gate_30); Mann-Whitney p = 0.0001. ≥ 40 rounds: **83.23% vs 81.45%**, +1.78 pp (95% CI +0.96 to +2.60; p < 0.0001). Mean 124.47 vs 122.09: +2.37 rounds (bootstrap 95% CI −0.71 to +5.33), too noisy to read. The later gate buys some extra play, but these players' D7 is not higher. |

### M23 · Early-churn segment and R6 test size

| Field | Spec |
|---|---|
| Definition | Players with fewer than 15 rounds in their first 14 days, the segment that R6 targets: its share of installs, its D1 and D7, and the 50/50 sample size for the R6 test. |
| Formula | `share = players with sum_gamerounds < 15 / all players`; D1 and D7 as in M8 and M9, within the segment; `max_bucket_retention_7` = the highest D7 among its three buckets (0, 1–4, 5–14). R6 size: `required_total_n(segment D7, +0.5 pp, 0.5)` target players (M14 method); installs = target players / share. |
| Inputs | Target lift +0.5 pp of D7 on the segment's own 2.27% (`onboarding_target_lift_pp`, a placeholder to agree with the Onboarding PM, B11); 80% power, α = 0.05 (S1). Sizing on all installs' 18.61% instead would understate the sample. |
| Edge cases | Rounds are counted over 14 days and overlap D7 (C3), so this sizes the segment; it is not a Day-0 targeting rule. The real test must target on first-day play, which this data lacks, so the segment and its base rate will change. The Day-1 ceiling (M10) is an association and a ceiling, not a forecast. The game's segment sizes will not transfer one-for-one to the app (C1). |
| Computed in | `analysis.cookie_analysis()` → `cookie.early_churn_segment` (`players`, `share_of_installs`, `retention_1`, `retention_7`, `d7_players`, `max_bucket_retention_7`, `d7_if_returned_day1`, `d7_if_not_returned_day1`, `onboarding_test_sizing`). The bucket rates are in `reports/tables/retention_by_rounds_bucket.csv` and `sql/06_retention_by_segment.sql`. |
| Current value | [`cookie.early_churn_segment`] **42,326 players = 46.93% of installs.** D1 14.62%; D7 **2.27%** (962 players), at most 3.41% in any of its buckets. Ceiling: 32.83% vs 7.19% D7 by Day-1 return, so at most about 0.26 pp of D7 per 1 pp of installs moved to a Day-1 return. **R6 test** [`cookie.early_churn_segment.onboarding_test_sizing`]: **30,809** target players at 50/50, about **65,648** installs. |

---

## 5. Common mistakes we avoid

1. **Writing % when we mean pp.** Going from 1.79% to 2.55% is **+0.77 pp**, which is a **+43.1%** relative lift. "Conversion up 0.77%" and "up 43 points" are both wrong. We always report both measures, absolute first.
2. **Using `total ads` (or peak day / hour) as a covariate or as a targeting rule.** These fields are measured during the experiment and differ slightly by arm (33.4% of PSA vs 30.1% of ad users saw 1–5 ads; Cramér's V 0.018–0.022). Adjusting for a post-assignment variable can bias the effect. They are used only for exploratory cuts, and stratified results are sensitivity checks (S11). The headline is the plain randomized comparison. Rounds bands in the gate test are different: below level 30 both versions are identical, so whether a player reaches 30 rounds cannot depend on the gate (§2.3, C8).
3. **Counting "significant" segments as evidence that the effect varies.** Because the overall lift is real, a test of "lift ≠ 0" inside each segment mostly measures segment size: big segments come out significant and small ones don't, whether or not the effect varies. Heterogeneity is answered by the interaction test (M16) and the segment-vs-rest contrasts (M17). For hours: p = 0.18, and no hour differs from the rest, even before correction. The m × α arithmetic (1.2 false positives expected among 24 hours) applies to those contrasts.
4. **Taking the biggest segment for the best segment.** The largest hourly lift (hour 6, +2.32 pp) rests on 83 control users with 0 conversions. The daypart pattern rests on a Night cell with 1 control conversion among 735 users. Small cells produce extreme estimates, so read the interval.
5. **Treating D7 as "retained through day 7" or as rolling retention.** `retention_7` means the player came back on day 7 itself. 3,598 players have D7 = TRUE with D1 = FALSE. D7 is not cumulative, and 1 − D7 is not a churn rate.
6. **Treating rounds → retention as causal, or as a Day-0 targeting rule.** Rounds are counted over 14 days, which include day 7, so the link is partly definitional. It sizes the early-churn segment (M23); it does not say who to target on day 0, or that more rounds *cause* retention (R6 must be an experiment).
7. **Calling every ad-arm conversion a campaign conversion.** Only 30.1% are incremental (95% CI 23.1% to 36.5%). Last-touch counting would overstate the campaign 3.3× (95% CI 2.7× to 4.3×).
8. **Reading a naive guardrail as clean, or "not significant" as "no effect".** The naive gate D1 gap (−0.59 pp, 95% CI −1.24 to +0.06) is neither evidence of no effect nor a clean read: it carries the same imbalance as D7 (player mix −0.42 pp). Read D1 where the gate can act: among players with 30+ rounds it is +0.08 pp (−0.78 to +0.94; M20). The same goes for rounds played (M11 vs M22).
9. **Reading a quota-exact split's SRM pass as reassurance.** The ad split lands on the nearest whole number to 96%, 0.04 users off where random assignment would typically miss by about 150. Random assignment lands there with probability 0.27%, so the split was most likely set by a quota or the file was trimmed, and the SRM test passes by construction. Exposure parity (M13) and the allocation config carry the check.
10. **Quoting dollars as results.** The USD figures depend on an illustrative USD 50 per conversion and an unknown CPM. The headline business number is incremental conversions.
11. **Reporting power at the observed effect.** It is a restatement of the p-value, so we do not compute it. Power and MDE are design quantities: what a test *could* detect, judged at the smallest lift worth acting on (M14), and how to size the next test.
12. **Changing denominators silently.** Retention denominators are all installs, including the 3,994 zero-round players, not only "players who played". Conversion denominators are all served users in the arm. M4a names its two denominators every time (all users for ≤ 20 ads, ad users for 36–200 ads).
13. **Extrapolating the measured lift to another budget.** The test compared current spend with no ads. It says nothing direct about 2× spend (B6, R2).
14. **Running the SRM check on post-cleaning counts.** Assignment happens before cleaning, and dropping units after assignment can create or hide an imbalance. The gate check uses the raw counts, 45,489 vs 44,700 (p = 0.0086). Footnote on cleaned counts: the v1 tables used the post-cleaning 44,699 (p = 0.0085); the status is the same here, but it need not be in general.
15. **Reading the naive gate gap as the gate's effect.** Of the −0.82 pp, −0.29 pp comes from the player mix and −0.21 pp from players who never met a gate: about 60% of the naive gap sits where the gate cannot act. That 60% is a location, not what the extra installs account for: even removing all 790 leaves −0.50 pp (M19). The remaining −0.32 pp per install is the part the gate could explain, not an estimate of its effect, and its 95% CI includes 0 (M20).
16. **Reading the exposure pattern as a frequency curve.** Exposure tracks how active a user is: PSA conversion rises from 0.28% at 1–5 ads to 15.50% at 200+. The 66% of users with ≤ 20 ads show no lift we could measure (−0.02 pp; a true lift of 0.18 pp would have been detected with 80% power), 21–35 ads are inconclusive, 36–200 ads show 1.73 to 7.04 pp and hold 98.5% of the bucket-by-bucket incremental conversions (M4a), and there is no usable estimate past 200 ads (CI −4.93 to +4.10 pp, 258 control users). That says "the lift lives in heavy users", not that the lift stops growing past some number of ads. A frequency cap needs its own test (R2).
17. **Printing a p-value of zero.** The main ad test has p = 1.7 × 10⁻¹³, shown as p < 0.0001, never as zero.
18. **Comparing an MDE with an estimate.** MDE and power describe the design (M14). Setting an observed estimate against the MDE says nothing about the effect; read the estimate's CI.
19. **Labelling subsets chosen after the result PASS / WARNING / FAIL.** The M19 rounds bands were chosen after the overall SRM WARNING, so their p-values are descriptive and carry no status.
20. **Mixing count bases.** gate_40 has 789 extra players in the raw counts and 790 in the analysis population; the rounds-band figures are raw net differences, not identified players. Write "a net excess of 762 among players with < 15 rounds", and keep one basis per sentence (§2.2).
21. **Sizing a re-test at the observed effect.** Size it at a change fixed in advance (B10: 0.5 pp of D7 per install), never at the gap just seen (M14).

## 6. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-03 | First version. Definitions fixed before the analysis; current values filled in from `reports/results.json`. |
| 2.0 | 2026-11-03 | Migrated to analysis core v2 (added methods checks). SRM on raw assignment counts (gate: 44,700 vs 45,489, p = 0.0086, WARNING) and a quota-exactness check for the ad split (M12). Segment-vs-rest contrasts (M17) separated from per-segment lift (M15); daypart added to M15–M17; the interaction test documented as deviance-based, with stratified results as a sensitivity check (M16). Power at the smallest lift worth acting on; power at the observed effect removed (M14). Interval for the incremental share (M5). New M18–M21: holdout cost, SRM by pre-gate stratum, D7 gap decomposition, negative controls. Classic D7 and "came back to the game" wording (M8, M9). Every current value refreshed from `results.json`. |
| 3.0 | 2026-11-03 | Migrated to analysis core v3 (further methods checks). New M4a (concentration of incremental conversions, with both denominators named), M22 (rounds among players with 30+ rounds as the gate's engagement guardrail) and M23 (early-churn segment and the R6 test size). M19: rounds bands < 15, 15–29, < 30 and 30+ with `net_excess_t`, no status labels, and the bound renamed "best case for gate_40". M20: D1 decomposition added; −0.32 pp described as the part the gate could explain, not an estimate. M21: borderline reading, the 15–29 location and the excess-removed comparison. M14: gate re-test sized at a pre-registered 0.5 pp of D7 per install; `stats.power_at_lift()`. M17: raw point estimate with Agresti–Caffo CI and p (Tuesday +0.95 pp, Thursday −0.74 pp, Night +0.45 pp). M5: interval for the last-touch overstatement. M18: the as-run PSA arm's share of the holdout cost. New §2.3 on rounds bands; conventions for p-value digits, causal wording and count bases. SQL references updated for the daypart, segment-vs-rest and standardized-lift columns (`sql/04_lift_by_day_and_hour.sql`), the quota columns (`sql/03_srm_check.sql`), the interval and holdout columns (`sql/02_conversion_by_group.sql`) and the six gate integrity steps (`sql/09_gate_integrity.sql`). |
