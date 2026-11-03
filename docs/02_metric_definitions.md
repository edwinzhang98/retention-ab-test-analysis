# 02 — Metric Definitions

**Owner:** Product Analyst, Growth · **Readers:** Growth PM, Game PM, Onboarding PM, media buyer, Analytics Eng · **Version:** 1.0 · **Date:** 2026-11-03

These definitions were written before the analysis, so that everyone computes each number the same way. The "Current value" rows were filled in afterwards from the pipeline output: `reports/results.json` (JSON path in brackets) and `reports/tables/*.csv`. If a deliverable disagrees with those two files, the deliverable is wrong.

Assumptions are referenced by ID (A1, B1, C1, S1, …) and live in [`assumptions.md`](assumptions.md). Row counts, nulls and outliers are in [`03_data_quality_checks.md`](03_data_quality_checks.md).

---

## 1. Conventions

| Topic | Convention |
|---|---|
| Arms | Treatment = `ad` (ad experiment) and `gate_40` (gate experiment). Control = `psa` and `gate_30`. Every difference is **treatment − control**. |
| Units | Rates are stored as proportions (0–1) and shown as % with 2 decimals. A difference between two rates is in **percentage points (pp)**, 2 decimals. Relative changes are in %, with 1 decimal here and whole numbers in the PM readout. Counts use thousands separators. Money is written as "USD". |
| Rounding | Differences are computed on unrounded rates, so a difference can disagree with the rounded rates in its last digit. Example: 2.55% − 1.79% is shown as +0.77 pp, because the unrounded rates are 2.5547% and 1.7854%. |
| Intervals | 95%, two-sided (α = 0.05) unless stated otherwise. Each metric names its interval method. |
| Power | MDE and sample-size numbers use 80% power and two-sided α = 0.05 (S1). |
| Analysis tables | `fct_ad_exposure_users` has one row per user in the ad experiment. `fct_game_players` has one row per Cookie Cats player. `agg_ad_cells` holds counts by arm × peak day × peak hour × exposure bucket. All three are built by `src/data.py`. SQL staging equivalents: `sql/01_stg_marketing_ab.sql`, `sql/05_stg_cookie_cats.sql`. |
| Source of truth | `reports/results.json` holds every headline number. `reports/tables/*.csv` holds the segment tables. |

## 2. Populations and filters

### 2.1 Marketing A/B (ad experiment)
- **Unit of analysis:** user (`user id`, renamed to `user_id`). The file has 588,101 rows and 588,101 unique users, with 0 duplicates and 0 nulls in any column.
- **Arms:** `test group` ∈ {`ad`, `psa`}, with 564,577 ad users and 23,524 PSA users.
- **Exclusions:** none. The CSV index column (`Unnamed: 0`) is dropped. The 36 users with more than 1,000 ads (max 2,065) are kept (A12).
- **Who is in the file:** every user saw at least one ad or PSA (`total ads` min = 1). The population is therefore *served* users, not all *assigned* users (A4).
- **Time window:** the whole experiment flight. The data has no dates (A7).

### 2.2 Cookie Cats (retention analysis and gate experiment)
- **Unit of analysis:** player (`userid`, renamed to `user_id`). The file has 90,189 rows, all unique, with 0 nulls.
- **Exclusion:** players with `sum_gamerounds` > 10,000 (`config.yaml: gamerounds_outlier_max`). This rule removes exactly one player (`user_id` 6390605, gate_30, 49,854 rounds in 14 days) as a logging error (C4).
- **Analysis population:** **90,188 players**: 44,699 gate_30 and 45,489 gate_40.
- **Sensitivity of the exclusion:** D1 is 44.52% and D7 is 18.61% with or without the excluded player. Mean rounds move from 51.87 to 51.32.
- **Zero-round players:** the 3,994 players with 0 rounds stay in every denominator. They installed the game but never played.
- **Time window:** per player and relative to install date. D1 and D7 are days 1 and 7 after install; rounds cover the first 14 days. The data has no calendar dates.

## 3. Metric catalogue

| ID | Metric | Role | Current value |
|---|---|---|---|
| M1 | Conversion rate | Primary metric (ad) | ad 2.55% vs PSA 1.79% |
| M2 | Absolute lift (pp) | Effect size, primary | ad +0.77 pp (0.59 to 0.94); gate D7 −0.82 pp (−1.33 to −0.31) |
| M3 | Relative lift | Secondary | ad +43.1% (+30.0% to +57.5%) |
| M4 | Incremental conversions | Secondary (business) | 4,343 (3,316 to 5,284) |
| M5 | Share of ad-arm conversions that are incremental | Secondary (business) | 30.1% |
| M6 | Impressions per incremental conversion | Secondary (business) | 3,227 |
| M7 | Breakeven CPM | Decision threshold | USD 15.49 (11.83 to 18.85) at an assumed USD 50 per conversion |
| M8 | D1 retention | Guardrail (gate); descriptive (retention) | 44.52% |
| M9 | D7 retention | Primary metric (gate); headline retention | 18.61% |
| M10 | D7 retention conditional on D1 | Diagnostic (retention) | 32.83% if returned on Day 1 vs 7.19% if not |
| M11 | Rounds played (first 14 days) | Segmentation; guardrail (gate) | median 16, mean 51.32 |
| M12 | Sample ratio mismatch (SRM) | Test health | ad PASS (p = 0.9998); gate WARNING (p = 0.0085) |
| M13 | Exposure parity and balance | Test health (ad) | mean ads per user 24.82 vs 24.76 |
| M14 | MDE / power | Design | ad 0.26 pp at 96/4 (0.10 pp at 50/50) |
| M15 | Adjusted p-values (Holm / BH) | Rule for reading segments | hour: 8 of 24 unadjusted, 1 after Holm |
| M16 | Interaction test | Rule for reading segments | day p = 0.013, hour p = 0.18 |

**Metric roles per experiment**

| Experiment | Primary | Secondary | Guardrails / test health | Guardrails missing from this data |
|---|---|---|---|---|
| Ad vs PSA | M1 conversion rate (effect: M2) | M3, M4, M5, M6, M7 | M12 SRM vs the intended 96/4 split; M13 exposure parity | Unsubscribe / complaint rate, cost per acquisition (CPA), opt-outs, revenue per user |
| Gate 30 vs 40 | M9 D7 retention (effect: M2) | (none) | M8 D1 retention; M11 rounds played; M12 SRM vs 50/50 | In-app purchase revenue, session length |

---

## 4. Metric specs

### M1 · Conversion rate

| Field | Spec |
|---|---|
| Definition | Share of users in an arm who converted during the experiment. |
| Formula | `conversion_rate = users with converted = TRUE / users in the arm`. Numerator: `SUM(converted)`. Denominator: `COUNT(user_id)`. |
| Grain | User (`user_id`), computed per arm (`test_group`). |
| Population & filters | All 588,101 users (§2.1); no exclusions. |
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
| Edge cases | Newcombe stays well-behaved when one arm of a segment has 0 conversions; the Wald interval comes out too narrow there, because a 0% rate has zero estimated variance. If both arms are at 0% or both at 100%, p is set to 1. Small segments give wide intervals, so read the interval, not the point estimate. |
| Computed in | `stats.two_prop_test()` (Newcombe via statsmodels `confint_proportions_2indep(method="newcomb")`), `stats.wald_diff_ci()`, `stats.bootstrap_two_prop()` + `stats.percentile_ci()`. SQL reproduces the point estimate, the pooled z statistic and the Wald interval as a cross-check: `sql/02_conversion_by_group.sql` (ad) and `sql/07_gate_experiment.sql` (gate). The Newcombe interval, the bootstrap and the p-values are Python-only, because DuckDB has no normal CDF. |
| Current value | **Ad** [`ad.test`, `ad.wald_ci`, `ad.bootstrap`]: **+0.77 pp**, 95% CI 0.59 to 0.94. Wald gives 0.60 to 0.94; the bootstrap gives 0.59 to 0.95, with 0 of 10,000 draws ≤ 0. z = 7.37, p < 0.001. **Gate D7** [`cookie.gate.retention_7`]: **−0.82 pp**, 95% CI −1.33 to −0.31 (bootstrap −1.32 to −0.31), p = 0.0016. **Gate D1** [`cookie.gate.retention_1`]: −0.59 pp, 95% CI −1.24 to +0.06 (bootstrap −1.24 to +0.06), p = 0.074. |

### M3 · Relative lift

| Field | Spec |
|---|---|
| Definition | The treatment rate expressed as a % change on the control rate. |
| Formula | `rel_lift = rate_t / rate_c − 1`. |
| Grain | Arm level. |
| Interval | Log risk-ratio (Katz) interval: `exp(ln(RR) ± 1.96 × SE) − 1`, where `SE = sqrt(1/x_t − 1/n_t + 1/x_c − 1/n_c)` (x = conversions, n = users). The percentile bootstrap is the cross-check. |
| Edge cases | Undefined when the control rate is 0. It is then reported as blank, never as infinite. This happens in 6 of the 24 hourly segments (hours 0, 1, 2, 4, 5 and 6). Always report it next to the absolute lift: on a low base rate a large % can be a small pp change. |
| Computed in | `stats.two_prop_test()`; bootstrap via `stats.bootstrap_two_prop()`. SQL point estimates: `rel_lift` in `sql/02_conversion_by_group.sql`, `rel_diff` in `sql/07_gate_experiment.sql`. |
| Current value | **Ad** [`ad.test.rel_lift`, `ad.bootstrap.rel_ci`]: **+43.1%**, 95% CI +30.0% to +57.5% (bootstrap +30.5% to +58.4%). **Gate D7:** −4.3% (−6.9% to −1.7%). **Gate D1:** −1.3% (−2.7% to +0.1%). |

### M4 · Incremental conversions

| Field | Spec |
|---|---|
| Definition | Conversions in the ad arm that would not have happened without the ads, using the PSA arm's rate as the counterfactual. |
| Formula | `incremental = abs_lift × n_ad = (rate_ad − rate_psa) × users in the ad arm`. Equivalently, `conv_ad − rate_psa × n_ad`. |
| Interval | The M2 Newcombe bounds × `n_ad`. |
| Grain | Experiment total for the ad arm. |
| Population & filters / time window | The 564,577 ad-arm users, over this flight only. |
| Edge cases | Valid only for this population, flight and spend level. It is not a forecast for another budget, audience or season (B4, B6), and it relies on the PSA being a neutral placebo (A10). |
| Computed in | `analysis.ad_experiment()`, in the `business` block; `sql/02_conversion_by_group.sql` (`incremental_conversions`, point estimate only). |
| Current value | [`ad.business.incremental_conversions`] **4,343** (95% CI 3,316 to 5,284). |

### M5 · Share of ad-arm conversions that are incremental

| Field | Spec |
|---|---|
| Definition | The fraction of the ad arm's conversions that the ads caused. |
| Formula | `incremental / conv_ad`, which equals `abs_lift / rate_ad`. |
| Grain | Experiment total for the ad arm. |
| Edge cases | The complement, about 70%, would have converted anyway. This is why counting every conversion by an ad-exposed user as a campaign conversion overstates impact, by about 3.3× here (14,423 / 4,343). |
| Computed in | `analysis.ad_experiment()` (`business.share_of_ad_conversions_incremental`); `sql/02_conversion_by_group.sql` (`incremental_share_of_ad_conversions`). |
| Current value | [`ad.business.share_of_ad_conversions_incremental`] **30.1%** (point estimate). |

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
| Computed in | `analysis.ad_experiment()` (`business.breakeven_cpm_usd`, `business.incremental_value_usd`); `sql/02_conversion_by_group.sql` (`breakeven_cpm_usd`, point estimate at USD 50); chart `figures.fig_breakeven()`. Dashboard page 4 recomputes it for any value per conversion and CPM entered. |
| Current value | [`ad.business`] **USD 15.49** (95% CI USD 11.83 to 18.85). Incremental value: USD 217,149 (USD 165,800 to 264,223). Both are at USD 50 per conversion. |

### M8 · D1 retention

| Field | Spec |
|---|---|
| Definition | Share of new players who came back and played on day 1 after install. |
| Formula | `SUM(retention_1) / COUNT(user_id)`. |
| Grain | Player. |
| Population & filters | 90,188 players (§2.2), including the 3,994 zero-round players. |
| Time window | Day 1 after install. Whether "day" means a calendar day or a 24-hour window is not documented (C2). |
| Source columns | `retention_1` (boolean). |
| Interval | Wilson score interval for a single rate. Differences between rates use M2. |
| Edge cases | A point-in-time flag. It says nothing about days 2–6. |
| Computed in | `src/retention.py` `retention_rates()` (Wilson interval via `stats.wilson_ci()`) and `retention.funnel()`; `sql/06_retention_by_segment.sql`. The gate comparison is in `sql/07_gate_experiment.sql`. |
| Current value | [`cookie.overall`] **44.52%** (95% CI 44.20% to 44.85%). By version [`cookie.by_version`]: gate_30 44.82%, gate_40 44.23%. |

### M9 · D7 retention

| Field | Spec |
|---|---|
| Definition | Share of new players who played on day 7 after install. |
| Formula | `SUM(retention_7) / COUNT(user_id)`. |
| Grain | Player. |
| Population & filters | 90,188 players (§2.2). |
| Time window | Day 7 after install (C2). |
| Source columns | `retention_7` (boolean). |
| Interval | Wilson score interval. Differences use M2. |
| Edge cases | **Not** "retained through day 7" and not "active on any of days 1–7". In the analysis population, 3,598 players have D7 = TRUE but D1 = FALSE: 7.19% of the 50,035 who skipped Day 1 (3,599 in the raw file). D7 is not cumulative, and 1 − D7 is not a churn rate. |
| Computed in | `retention.retention_rates()`; `sql/06_retention_by_segment.sql`; gate comparison in `sql/07_gate_experiment.sql`. |
| Current value | [`cookie.overall`] **18.61%** (95% CI 18.35% to 18.86%). By version: gate_30 19.02%, gate_40 18.20%. |

### M10 · D7 retention conditional on D1

| Field | Spec |
|---|---|
| Definition | D7 retention among players who returned on Day 1, compared with D7 retention among players who did not. |
| Formula | Returned: `SUM(retention_1 AND retention_7) / SUM(retention_1)`. Did not return: `SUM(NOT retention_1 AND retention_7) / SUM(NOT retention_1)`. |
| Grain | Player. |
| Related funnel | Installs → played ≥ 1 round (`sum_gamerounds > 0`) → returned on Day 1 → returned on Day 1 and Day 7. Each share is a share of installs; step conversion is a step divided by the previous step. |
| Edge cases | Both flags are outcomes for the same players, so this is a descriptive association, not "Day 1 causes Day 7". The 4.6× figure is a ratio of rates. As a pp gap the difference is 25.64 pp. |
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
| Edge cases | Rounds are not levels. `reached_gate_30 = sum_gamerounds ≥ 30` is only a proxy for having reached the level-30 gate (C7). Because the 14-day window contains day 7, rounds and D7 partly measure the same behaviour, so rounds vs retention is correlation, not cause. The distribution is heavy-tailed: compare arms on the median and a rank test, not only the mean. |
| Computed in | `data.clean_cookie()` (bucket, `reached_gate_30`), `retention.engagement_curve()`, `retention.retention_by_rounds()`; the gate guardrail is in `analysis.cookie_analysis()`. SQL: `sql/05_stg_cookie_cats.sql`, `sql/06_retention_by_segment.sql`. |
| Current value | [`data_quality.cookie`, `cookie.by_rounds_bucket`, `cookie.gate.rounds`] Median 16. Mean 51.32 (51.87 before the exclusion). p99 493. Max 2,961 after the exclusion. 3,994 players (4.43%) played 0 rounds. Players with < 15 rounds: 46.93% of installs, with D7 ≤ 3.41%. **Gate guardrail:** mean 51.30 (gate_40) vs 51.34 (gate_30), median 16 vs 17, Mann-Whitney p = 0.051. |

### M12 · Sample ratio mismatch (SRM)

| Field | Spec |
|---|---|
| Definition | A test of whether the observed split of units across arms matches the intended allocation. A mismatch means assignment or logging may be broken, and the comparison may be biased. |
| Formula | Pearson χ² goodness of fit, 1 df: `χ² = Σ (O_arm − E_arm)² / E_arm`, where `E_arm = N × intended_share_arm`. |
| Decision rule (S2) | p < 0.001 → **FAIL**: stop, the results are not trustworthy. 0.001 ≤ p < 0.01 → **WARNING**: the results cannot be certified until assignment has been investigated. p ≥ 0.01 → **PASS**. |
| Grain | Unit of randomization (user / player). |
| Population & filters | Ideally every assigned unit, before analysis exclusions. The implementation runs on the analysis tables, which for the gate experiment excludes 1 gate_30 player. On the raw file (44,700 vs 45,489) the status is the same: WARNING. |
| Intended allocation | Ad: 96/4, **inferred, not documented** (A1). Gate: 50/50 (C5). |
| Edge cases | With a huge N the test detects tiny imbalances, and that is intended. A PASS against an allocation inferred from the same data (the ad case) is circular and weak, so pair it with exposure parity (M13). |
| Computed in | `stats.srm_check()`, which returns `p_value`, `threshold` (0.001), `flag` (true only for a hard FAIL) and, in the current code, `warn_threshold` (0.01) and a three-level `status`. `sql/03_srm_check.sql` covers both experiments; it compares χ² with the critical values for p = 0.001 and 0.01 (`srm_status`), because DuckDB has no χ² CDF. |
| Current value | **Ad** [`ad.srm`]: 564,577 vs 23,524 (observed share 96.00% ad), χ² ≈ 0, p = 0.9998 → **PASS**. **Gate** [`cookie.gate.srm`]: 45,489 vs 44,699 (observed share 50.44% gate_40), χ² = 6.92, p = 0.0085 → **WARNING**. That p is below the 0.01 warning level but above the 0.001 hard-fail threshold, so `flag` = false. We treat the WARNING as blocking certification of the gate result. |
| Lead for the investigation | From [`cookie.gate.d7_by_reached_30`] (descriptive): gate_40's extra players are all among players with < 30 rounds (28,876 vs 28,044). Players with ≥ 30 rounds are balanced (16,613 vs 16,655). |

### M13 · Exposure parity and balance of post-assignment fields

| Field | Spec |
|---|---|
| Definition | Whether both arms were served the same volume of ad slots (ads or PSAs) with similar timing. |
| Formula | Mean and median `total ads` per user by arm, plus distribution tests (Kolmogorov–Smirnov, Mann-Whitney). For the categorical fields (`most ads day`, `most ads hour`, exposure bucket): a χ² test of independence, with Cramér's V = `sqrt(χ² / (N × (min(rows, cols) − 1)))` as the effect size. |
| Grain | User. |
| Edge cases | These fields are recorded **during** the experiment, so they are post-assignment (A9). Small differences are expected, and at N = 588,101 they come out "significant"; Cramér's V shows how big they are. They are diagnostics only, never covariates. |
| Computed in | `analysis.ad_experiment()`, `stats.balance_test()`. The exposure-parity means are also in `sql/02_conversion_by_group.sql` (`avg_ads_per_user_ad`, `avg_ads_per_user_psa`); the balance tests are Python-only. |
| Current value | [`ad.groups`, `ad.balance`, `ad.total_ads_ks`] Mean ads per user: 24.82 (ad) vs 24.76 (PSA). Median 13 vs 12. KS D = 0.040. Cramér's V: peak day 0.020, peak hour 0.018, exposure bucket 0.022. All have p < 0.001 because N is huge. |

### M14 · MDE / power

| Field | Spec |
|---|---|
| Definition | **MDE:** the smallest true effect the design detects with 80% probability at two-sided α = 0.05. **Power:** the probability of detecting a given true effect. |
| Formula | Effect size is Cohen's h = `2·asin(sqrt(p_t)) − 2·asin(sqrt(p_c))`. Solve the normal-approximation power equation (`NormalIndPower`) for h, given `n_t`, the ratio `n_c / n_t`, α and power. Convert back with `p_t = sin²(asin(sqrt(p_c)) + h/2)`. Then `MDE_abs = p_t − p_c` and `MDE_rel = MDE_abs / p_c`. For required N, solve for `n_t` at a target effect; the total is `n_t / share_t`. |
| Inputs | The baseline is the control rate: 1.79% (conversion), 44.82% (D1), 19.02% (D7). |
| Edge cases | MDE is a design-time quantity. "Observed power" computed from the observed effect adds no information and is not used as evidence; it is stored in `results.json` only for completeness. An unbalanced split costs sensitivity because the small arm dominates the variance. |
| Computed in | `stats.mde()`, `stats.required_total_n()`, `stats.achieved_power()`; charts `figures.fig_mde_by_split()` and `figures.fig_power_curve()`. Interactive versions: dashboard page 4 (power panel) and page 7 (sample-size calculator). No SQL. |
| Current value | **Ad** [`ad.power`]: at 96/4, MDE **0.26 pp** (14.3% relative). The same 588,101 users split 50/50 would detect **0.10 pp** (5.5% relative). A 50/50 split needs 90,333 users to match the 0.26 pp MDE that 96/4 reaches with 588,101. Detecting a 10% relative lift (1.79% → 1.96%) needs **181,074** users at 50/50, 282,928 at 80/20 and **1,178,866** at 96/4. **Gate** [`cookie.gate.retention_*.mde`]: D1 MDE 0.93 pp (2.1% relative), D7 MDE 0.74 pp (3.9% relative). |

### M15 · Adjusted p-values (Holm / BH)

| Field | Spec |
|---|---|
| Definition | Per-segment p-values adjusted for testing many segments of one dimension at the same time. |
| Family | All segments of one dimension: 7 peak days, 24 peak hours or 8 exposure buckets (S6). |
| Per-segment test | M2 (two-proportion z-test and Newcombe interval) on that segment's users. |
| Methods | **Holm** (step-down; controls the family-wise error rate) is the default and is used in the forest plots. **Benjamini–Hochberg** (controls the false discovery rate) is reported alongside it. **Bonferroni** (p × m, capped at 1) is for reference. "Significant" means adjusted p < 0.05. |
| Reading rule | Run the interaction test (M16) first. Only if it is convincing, look at which segments differ. Segment results stay exploratory because the segmenting fields are post-assignment (M13, A9). |
| Edge cases | Some segments have 0 control conversions. Without correction, the expected number of false positives is m × α: 24 × 0.05 = 1.2 for hours and 7 × 0.05 = 0.35 for days. |
| Computed in | `stats.segment_lifts()`, `stats.adjust_pvalues()` (statsmodels `multipletests` with `holm`, `fdr_bh` or `bonferroni`). Tables: `reports/tables/ad_lift_by_*.csv`, where the columns `p_adj` and `significant_adj` are Holm-adjusted. `sql/04_lift_by_day_and_hour.sql` supplies segment counts and rates; the adjustment is Python-only. Dashboard page 5 switches the method live. |
| Current value | [`ad.heterogeneity`] **Hour:** 8 of 24 significant unadjusted, 1 after Holm, BH and Bonferroni. The survivor is hour 14: +1.25 pp, 95% CI 0.56 to 1.76. **Day:** 5 of 7 unadjusted; 5 after Holm, 5 after BH, 3 after Bonferroni. **Exposure bucket:** 3 of 8 under every method. |

### M16 · Interaction test

| Field | Spec |
|---|---|
| Definition | A single test per dimension of whether the ad effect differs across that dimension's segments. Because it is one test, there is no multiple-comparison problem. |
| Formula | Binomial GLM on segment × arm counts. Reduced model: `logit(rate) ~ arm + segment`. Full model: `logit(rate) ~ arm × segment`. `LR = 2 × (loglik_full − loglik_reduced)`, compared with χ² on (k − 1) df. |
| Scale | Log-odds. A constant odds ratio can still produce different pp lifts in segments with different base rates. |
| Cross-checks | The Breslow–Day test of equal odds ratios. The Cochran–Mantel–Haenszel pooled odds ratio and the Mantel–Haenszel risk difference across strata: if the stratified pooled estimate ≈ the overall lift, the headline is not driven by the day / hour mix. |
| Edge cases | Sparse cells cause harmless convergence warnings: hours 0–6 have at most 1 control conversion each. The dimensions are post-assignment, so the results are exploratory. |
| Computed in | `stats.interaction_lrt()`, `stats.stratified_summary()`. No SQL. |
| Current value | [`ad.heterogeneity.*.lrt`, `.stratified`] **Day:** LR = 16.22, df = 6, p = 0.013 (Breslow–Day p = 0.013). That is weak evidence. **Hour:** LR = 29.10, df = 23, p = 0.18 (Breslow–Day p = 0.52). No evidence. **Exposure bucket:** LR = 43.71, df = 7, p < 0.001. Strong, but exploratory because exposure is post-assignment. The Mantel–Haenszel risk difference is 0.76 pp stratified by day and 0.77 pp stratified by hour, vs 0.77 pp overall. The pooled odds ratio by day is 1.44 (1.30 to 1.59). |

---

## 5. Common mistakes we avoid

1. **Writing % when we mean pp.** Going from 1.79% to 2.55% is **+0.77 pp**, which is a **+43.1%** relative lift. "Conversion up 0.77%" and "up 43 points" are both wrong. We always report both measures, absolute first.
2. **Using `total ads` (or peak day / hour) as a covariate or as a targeting rule.** These fields are measured during the experiment and differ slightly by arm (Cramér's V 0.018–0.022). Adjusting for a post-assignment variable can bias the effect. They are used only for exploratory cuts. The headline is the plain randomized comparison.
3. **Reading 24 hourly p-values one by one.** At α = 0.05, 24 hours of pure noise would produce about 1.2 false positives. Unadjusted, 8 hours look "significant". After Holm only 1 is left, and the interaction test (p = 0.18) finds no evidence that the effect varies by hour. The same logic applies to the 7 days.
4. **Taking the biggest segment for the best segment.** The largest hourly lift (hour 6, +2.32 pp) rests on 83 control users with 0 conversions. Small cells produce extreme estimates, so read the interval.
5. **Treating D7 as "retained through day 7".** `retention_7` means the player played on day 7. 3,598 players have D7 = TRUE with D1 = FALSE. D7 is not cumulative, and 1 − D7 is not a churn rate.
6. **Treating rounds → retention as causal.** Rounds are counted over 14 days, which include day 7, and players who come back naturally play more. The pattern tells us *who* to target, not that more rounds *cause* retention (R6 must be an experiment).
7. **Calling every ad-arm conversion a campaign conversion.** Only 30.1% are incremental. The rest would have happened with a PSA in the slot.
8. **Reading "not significant" as "no effect".** Gate D1 is −0.59 pp, with a 95% CI of −1.24 to +0.06 and an MDE of 0.93 pp. That is inconclusive, not zero.
9. **Taking an SRM pass as proof of clean randomization, or ignoring a warning because the decision feels safe.** The ad SRM is tested against an allocation inferred from the data, so exposure parity is the stronger check. The gate SRM is a WARNING, so the gate result is reported as not certified, even though the decision (keep the gate at 30) is the safe default.
10. **Quoting dollars as results.** The USD figures depend on an illustrative USD 50 per conversion and an unknown CPM. The headline business number is incremental conversions.
11. **Using observed (post-hoc) power as evidence.** Power and MDE are design quantities. We use them to say what a test *could* detect and to size the next test.
12. **Changing denominators silently.** Retention denominators are all installs, including the 3,994 zero-round players, not only "players who played". Conversion denominators are all served users in the arm.
13. **Extrapolating the measured lift to another budget.** The test compared current spend with no ads. It says nothing direct about 2× spend (B6, R2).

## 6. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-03 | First version. Definitions fixed before the analysis; current values filled in from `reports/results.json`. |
