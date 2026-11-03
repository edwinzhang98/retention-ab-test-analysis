-- =============================================================================
-- sql/07_gate_experiment.sql
--
-- Purpose : Readout of the Cookie Cats gate experiment: does moving the first
--           progression gate from level 30 (control) to level 40 (treatment)
--           change D7 retention (primary metric) or D1 retention (guardrail)?
-- Input   : data/raw/cookie_cats.csv - one row per player (rules as in
--           05_stg_cookie_cats.sql, i.e. the one outlier excluded).
-- Output  : 1 row per metric - grain: metric ('retention_7' = D7, 'retention_1' = D1).
--             metric_role                       'primary' (D7) | 'guardrail' (D1)
--             players_gate_30, players_gate_40  players per arm
--             retained_gate_30, retained_gate_40
--             rate_gate_30, rate_gate_40        retained / players
--             abs_diff                          rate_gate_40 - rate_gate_30 (proportion; x100 = pp)
--             rel_diff                          rate_gate_40 / rate_gate_30 - 1
--             z_stat                            pooled two-proportion z statistic
--             abs_diff_ci95_low, _high          95% Wald (unpooled) CI for abs_diff
--             significant_at_5pct               |z_stat| > 1.96
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/07_gate_experiment.sql   (print this result)
--             python -m src.sql_check                              (run every file + reconcile)
--             duckdb -c ".read sql/07_gate_experiment.sql"         (DuckDB CLI)
-- Notes   : - Read 03_srm_check.sql and 09_gate_integrity.sql first. The 50/50 SRM
--             check on raw assignment counts returns a WARNING; gate_40's net excess
--             of players sits among players with < 15 rounds; and players with
--             < 30 rounds, who never met a gate, show a borderline D7 gap too. So
--             this readout is NOT certified, and the naive abs_diff below is not an
--             estimate of the gate's effect: 09 splits it into player mix, a gap
--             among players who never met a gate, and the part the gate could
--             explain (players with 30+ rounds).
--           - Players per arm are the analysis population (05_stg_cookie_cats.sql:
--             one gate_30 outlier excluded), so players_gate_30 is one lower than
--             the raw count used in the SRM check.
--           - D1 is a guardrail. Like D7, the naive D1 difference carries the
--             assignment imbalance (player mix), so read it with the D1
--             decomposition in 09_gate_integrity.sql, not on its own.
--           - p-values, Newcombe CIs, the bootstrap and the MDE are computed in
--             src/stats.py (DuckDB has no normal CDF).
-- =============================================================================

WITH params AS (
    SELECT 1.959963984540054::DOUBLE AS z_crit_95   -- standard normal 97.5th percentile (two-sided alpha = 0.05)
),

stg_cookie_cats AS (
    -- Same rules as 05_stg_cookie_cats.sql (repeated so this file runs on its own)
    SELECT
        CAST(version     AS VARCHAR) AS version,
        CAST(retention_1 AS BOOLEAN) AS retention_1,
        CAST(retention_7 AS BOOLEAN) AS retention_7
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
    WHERE sum_gamerounds <= 10000
),

-- Long format: one row per player per metric, so D1 and D7 share one calculation
player_metrics AS (
    SELECT 'retention_1' AS metric, version, retention_1 AS retained FROM stg_cookie_cats
    UNION ALL
    SELECT 'retention_7' AS metric, version, retention_7 AS retained FROM stg_cookie_cats
),

arm_counts AS (
    SELECT
        metric,
        COUNT(*) FILTER (WHERE version = 'gate_30')              AS players_gate_30,
        COUNT(*) FILTER (WHERE version = 'gate_40')              AS players_gate_40,
        COUNT(*) FILTER (WHERE version = 'gate_30' AND retained) AS retained_gate_30,
        COUNT(*) FILTER (WHERE version = 'gate_40' AND retained) AS retained_gate_40
    FROM player_metrics
    GROUP BY metric
),

rates AS (
    SELECT
        *,
        retained_gate_30::DOUBLE / players_gate_30 AS rate_gate_30,
        retained_gate_40::DOUBLE / players_gate_40 AS rate_gate_40,
        -- common rate if the gate position had no effect (H0); used for the z test
        (retained_gate_30 + retained_gate_40)::DOUBLE
            / (players_gate_30 + players_gate_40)  AS pooled_rate
    FROM arm_counts
),

standard_errors AS (
    SELECT
        *,
        rate_gate_40 - rate_gate_30 AS abs_diff,
        -- SE assuming H0 (pooled rate) -> z statistic
        SQRT(pooled_rate * (1 - pooled_rate) * (1.0 / players_gate_40 + 1.0 / players_gate_30)) AS se_pooled,
        -- SE without assuming H0 (each arm keeps its own rate) -> confidence interval
        SQRT(rate_gate_40 * (1 - rate_gate_40) / players_gate_40
           + rate_gate_30 * (1 - rate_gate_30) / players_gate_30)                                AS se_unpooled
    FROM rates
)

SELECT
    s.metric,
    CASE s.metric WHEN 'retention_7' THEN 'primary' ELSE 'guardrail' END AS metric_role,
    s.players_gate_30,
    s.players_gate_40,
    s.retained_gate_30,
    s.retained_gate_40,
    s.rate_gate_30,
    s.rate_gate_40,
    s.abs_diff,
    s.rate_gate_40 / s.rate_gate_30 - 1          AS rel_diff,
    s.abs_diff / s.se_pooled                     AS z_stat,
    s.abs_diff - p.z_crit_95 * s.se_unpooled     AS abs_diff_ci95_low,
    s.abs_diff + p.z_crit_95 * s.se_unpooled     AS abs_diff_ci95_high,
    ABS(s.abs_diff / s.se_pooled) > p.z_crit_95  AS significant_at_5pct
FROM standard_errors AS s
CROSS JOIN params AS p
ORDER BY CASE s.metric WHEN 'retention_7' THEN 1 ELSE 2 END;   -- primary metric first
