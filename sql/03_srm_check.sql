-- =============================================================================
-- sql/03_srm_check.sql
--
-- Purpose : Sample Ratio Mismatch (SRM) check for both experiments: are the
--           observed arm sizes consistent with the intended allocation?
--           Pearson chi-square goodness-of-fit test (2 arms -> 1 degree of
--           freedom), plus how far the split is from the target in users
--           ("quota exactness"), which shows when the test cannot detect anything.
-- Input   : data/raw/marketing_AB.csv - ad experiment, every user.
--           data/raw/cookie_cats.csv  - gate experiment, every ASSIGNED player
--                                       (raw counts: the outlier excluded from the
--                                       analysis population in 05_stg_cookie_cats.sql
--                                       was still assigned, so it is counted here).
-- Output  : 1 row per experiment - grain: experiment.
--             experiment                        'marketing_ab' | 'cookie_cats'
--             treatment_arm, control_arm        'ad' / 'psa' | 'gate_40' / 'gate_30'
--             n_treatment, n_control            assigned users (players) per arm
--             intended_treatment_share          design allocation (see Notes)
--             observed_treatment_share          n_treatment / (n_treatment + n_control)
--             expected_treatment, _control      total x intended share
--             deviation_users                   n_treatment - expected_treatment
--             sd_users_under_random_assignment  sqrt(N x share x (1 - share)): the typical size
--                                               of deviation_users if every unit were assigned
--                                               independently at random
--             is_nearest_integer_to_target      n_treatment = ROUND(expected_treatment)
--             prob_exactly_nearest_integer      probability that independent random assignment
--                                               lands exactly on that integer (binomial; NULL
--                                               unless is_nearest_integer_to_target)
--             chi2_stat                         sum over arms of (observed - expected)^2 / expected
--             p_below_0_001                     chi2_stat above the p = 0.001 critical value
--             p_below_0_01                      chi2_stat above the p = 0.01 critical value
--             srm_status                        'PASS' (p >= 0.01) | 'WARNING' (0.001 <= p < 0.01)
--                                               | 'FAIL' (p < 0.001)
--             reading                           what the status means for this experiment
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/03_srm_check.sql   (print this result)
--             python -m src.sql_check                        (run every file + reconcile)
--             duckdb -c ".read sql/03_srm_check.sql"         (DuckDB CLI)
-- Notes   : - Status rule: FAIL below p = 0.001 (the usual SRM hard stop, Kohavi
--             et al.); WARNING from 0.001 to 0.01 (this project's convention: do not
--             certify the readout until assignment is explained); PASS otherwise.
--           - Ad experiment: the intended 96/4 split is not documented; it is
--             inferred from the observed ratio, and n_treatment is the nearest
--             integer to exactly 96%. Independent random assignment typically
--             misses the target by about sd_users_under_random_assignment and
--             rarely lands that close (prob_exactly_nearest_integer), so the split
--             is most likely a fixed quota (or the export was trimmed to it).
--             Fixed arm sizes are a valid design; they just make the SRM test
--             uninformative: it passes by construction and says nothing about
--             assignment. The meaningful check is exposure parity: avg ads per user
--             by arm in 02_conversion_by_group.sql, and each arm's mix across
--             exposure buckets (share_of_arm_*) in 04_lift_by_day_and_hour.sql.
--           - Gate experiment: intended 50/50, tested on raw assignment counts.
--             09_gate_integrity.sql shows where gate_40's net excess of players
--             sits by rounds band. Those bands were chosen after seeing this
--             result, so their p-values are descriptive and carry no status.
--           - With 2 arms, chi2_stat = (deviation_users / sd_users_under_random_assignment)^2:
--             the test asks how many standard deviations the split is from target.
--             Exact p-values come from src/stats.py (DuckDB has no chi-square
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
        0.96::DOUBLE                                 AS intended_treatment_share,   -- inferred, see Notes
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
    FROM read_csv('data/raw/cookie_cats.csv', header = true)   -- no outlier filter: SRM is about assignment
),

expected AS (
    SELECT
        *,
        n_treatment + n_control                                    AS n_total,
        n_treatment::DOUBLE / (n_treatment + n_control)            AS observed_treatment_share,
        (n_treatment + n_control) * intended_treatment_share       AS expected_treatment,
        (n_treatment + n_control) * (1 - intended_treatment_share) AS expected_control
    FROM arm_counts
),

quota_exactness AS (
    SELECT
        *,
        n_treatment - expected_treatment                                          AS deviation_users,
        SQRT(n_total * intended_treatment_share * (1 - intended_treatment_share)) AS sd_users_under_random_assignment,
        n_treatment = ROUND(expected_treatment)                                   AS is_nearest_integer_to_target,
        -- Binomial(n_total, share) probability of exactly n_treatment, computed on the
        -- log scale (LGAMMA) because the factorials overflow a DOUBLE
        EXP(LGAMMA(n_total + 1) - LGAMMA(n_treatment + 1) - LGAMMA(n_control + 1)
            + n_treatment * LN(intended_treatment_share)
            + n_control   * LN(1 - intended_treatment_share))                     AS prob_n_treatment_exactly
    FROM expected
),

chi_square AS (
    SELECT
        *,
        POWER(n_treatment - expected_treatment, 2) / expected_treatment
          + POWER(n_control - expected_control, 2) / expected_control AS chi2_stat
    FROM quota_exactness
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
    c.deviation_users,
    c.sd_users_under_random_assignment,
    c.is_nearest_integer_to_target,
    CASE WHEN c.is_nearest_integer_to_target THEN c.prob_n_treatment_exactly END AS prob_exactly_nearest_integer,
    c.chi2_stat,
    c.chi2_stat > p.chi2_crit_p001 AS p_below_0_001,
    c.chi2_stat > p.chi2_crit_p01  AS p_below_0_01,
    CASE
        WHEN c.chi2_stat > p.chi2_crit_p001 THEN 'FAIL'
        WHEN c.chi2_stat > p.chi2_crit_p01  THEN 'WARNING'
        ELSE 'PASS'
    END AS srm_status,
    CASE
        WHEN c.is_nearest_integer_to_target
            THEN 'uninformative: split exactly on target, most likely a quota; check exposure parity'
        WHEN c.chi2_stat > p.chi2_crit_p001
            THEN 'stop: debug assignment before reading any result'
        WHEN c.chi2_stat > p.chi2_crit_p01
            THEN 'do not certify the readout until the mismatch is explained'
        ELSE 'consistent with the intended split'
    END AS reading
FROM chi_square AS c
CROSS JOIN params AS p
ORDER BY c.experiment DESC;   -- marketing_ab (main experiment) first
