-- =============================================================================
-- sql/03_srm_check.sql
--
-- Purpose : Sample Ratio Mismatch (SRM) check for both experiments: are the
--           observed arm sizes consistent with the intended allocation?
--           Pearson chi-square goodness-of-fit test, 2 arms -> 1 degree of freedom.
-- Input   : data/raw/marketing_AB.csv - ad experiment, every user.
--           data/raw/cookie_cats.csv  - gate experiment, analysis population
--                                       (outlier rule as in 05_stg_cookie_cats.sql).
-- Output  : 1 row per experiment - grain: experiment.
--             experiment                  'marketing_ab' | 'cookie_cats'
--             treatment_arm, control_arm  'ad' / 'psa' | 'gate_40' / 'gate_30'
--             n_treatment, n_control      observed users (players) per arm
--             intended_treatment_share    design allocation (see Notes)
--             observed_treatment_share    n_treatment / (n_treatment + n_control)
--             expected_treatment, _control  total x intended share
--             chi2_stat                   sum over arms of (observed - expected)^2 / expected
--             srm_flag_p_lt_0_001         chi2 above the p = 0.001 critical value
--                                         (the strict SRM threshold used in this project)
--             srm_warning_p_lt_0_01       chi2 above the p = 0.01 critical value
--             srm_status                  PASS / WARNING / FAIL
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/03_srm_check.sql   (print this result)
--             python -m src.sql_check                        (run every file + reconcile)
--             duckdb -c ".read sql/03_srm_check.sql"         (DuckDB CLI)
-- Notes   : - Ad experiment: the intended 96/4 split is not documented; it is
--             inferred from the round observed ratio, so a PASS is weak evidence.
--             Exposure parity (avg ads per user by arm, 02_conversion_by_group.sql)
--             is the stronger sanity check.
--           - Gate experiment: intended 50/50. A WARNING (0.001 <= p < 0.01)
--             does not trip the strict flag, but it blocks certification of the
--             readout until assignment is investigated. Counting the excluded
--             outlier (a gate_30 player) does not change the status.
--           - Exact p-values come from src/stats.py (DuckDB has no chi-square
--             CDF); here the statistic is compared with the critical values.
-- =============================================================================

WITH params AS (
    SELECT
        10.827566170662733::DOUBLE AS chi2_crit_p001,   -- chi-square(1 df) upper 0.1% point: chi2 above it <=> p < 0.001
        6.634896601021215::DOUBLE  AS chi2_crit_p01     -- chi-square(1 df) upper 1% point:   chi2 above it <=> p < 0.01
),

arm_counts AS (
    SELECT
        'marketing_ab'                               AS experiment,
        'ad'                                         AS treatment_arm,
        'psa'                                        AS control_arm,
        0.96::DOUBLE                                 AS intended_treatment_share,   -- assumption, see Notes
        COUNT(*) FILTER (WHERE "test group" = 'ad')  AS n_treatment,
        COUNT(*) FILTER (WHERE "test group" = 'psa') AS n_control
    FROM read_csv('data/raw/marketing_AB.csv', header = true)

    UNION ALL

    SELECT
        'cookie_cats',
        'gate_40',
        'gate_30',
        0.50::DOUBLE,
        COUNT(*) FILTER (WHERE version = 'gate_40'),
        COUNT(*) FILTER (WHERE version = 'gate_30')
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
    WHERE sum_gamerounds <= 10000                 -- analysis population, same rule as 05_stg_cookie_cats.sql
),

expected AS (
    SELECT
        *,
        n_treatment::DOUBLE / (n_treatment + n_control)            AS observed_treatment_share,
        (n_treatment + n_control) * intended_treatment_share       AS expected_treatment,
        (n_treatment + n_control) * (1 - intended_treatment_share) AS expected_control
    FROM arm_counts
),

chi_square AS (
    SELECT
        *,
        POWER(n_treatment - expected_treatment, 2) / expected_treatment
          + POWER(n_control - expected_control, 2) / expected_control AS chi2_stat
    FROM expected
)

SELECT
    c.experiment,
    c.treatment_arm,
    c.control_arm,
    c.n_treatment,
    c.n_control,
    c.intended_treatment_share,
    c.observed_treatment_share,
    c.expected_treatment,
    c.expected_control,
    c.chi2_stat,
    c.chi2_stat > p.chi2_crit_p001 AS srm_flag_p_lt_0_001,
    c.chi2_stat > p.chi2_crit_p01  AS srm_warning_p_lt_0_01,
    CASE
        WHEN c.chi2_stat > p.chi2_crit_p001 THEN 'FAIL: p < 0.001 - stop and debug assignment'
        WHEN c.chi2_stat > p.chi2_crit_p01  THEN 'WARNING: 0.001 <= p < 0.01 - do not certify until assignment is checked'
        ELSE 'PASS: p >= 0.01'
    END AS srm_status
FROM chi_square AS c
CROSS JOIN params AS p
ORDER BY c.experiment DESC;   -- marketing_ab (main experiment) first
