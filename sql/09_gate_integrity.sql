-- =============================================================================
-- sql/09_gate_integrity.sql
--
-- Purpose : Integrity check of the Cookie Cats gate experiment, whose 50/50 SRM
--           check returns a WARNING (03_srm_check.sql). Where do gate_40's extra
--           players sit, and how much of the naive D7 gap (07_gate_experiment.sql)
--           could the gate itself have caused? Three steps, on strata cut by
--           rounds played (play before level 30 is identical in both versions by
--           design):
--             1. SRM by stratum (raw assignment counts): localize the mismatch.
--             2. D7 by stratum and version. Players who never reached level 30
--                met no gate, so their D7 should not differ (negative control).
--             3. Decompose the naive D7 gap into player mix (composition), the gap
--                among players who met no gate, and the gap among players who
--                could meet the gate. Only the last part can be the gate.
-- Input   : data/raw/cookie_cats.csv - one row per player. Step 1 counts every
--           assigned player (as 03_srm_check.sql); steps 2-3 use the analysis
--           population (outlier excluded, as 05_stg_cookie_cats.sql and 07).
-- Output  : 4 rows - grain: pre-gate stratum.
--             stratum                       'All players' | 'Rounds < 15' | 'Rounds < 30' |
--                                           'Rounds >= 30'
--             stratum_role                  how to read the row: the total, a drill-down
--                                           inside rounds < 30, or one of the two strata
--                                           that partition the players
--           Step 1 - assignment, raw file:
--             assigned_gate_40, _gate_30    assigned players per arm
--             extra_gate_40                 assigned_gate_40 - assigned_gate_30
--             srm_chi2                      Pearson chi-square vs 50/50 (1 df)
--             srm_status                    'PASS' | 'WARNING' | 'FAIL' (thresholds as in 03)
--           Step 2 - D7, analysis population:
--             players_gate_40, _gate_30     players per arm
--             d7_retained_gate_40, _gate_30 players who came back on day 7
--             d7_rate_gate_40, _gate_30     d7_retained / players
--             d7_diff                       d7_rate_gate_40 - d7_rate_gate_30 (proportion; x100 = pp)
--             d7_z                          pooled two-proportion z statistic
--             d7_diff_ci95_low, _high       95% Wald (unpooled) CI for d7_diff
--           Step 3 - decomposition of the naive D7 gap (the two partition rows add
--           up to the 'All players' row; NULL on the drill-down row):
--             share_of_arm_gate_40, _gate_30  players in the stratum / players in the arm
--             d7_within_term                average share x d7_diff: the stratum's part of
--                                           the gap with the player mix held equal
--             d7_within_ci95_low, _high     average share x the d7_diff CI (partition rows)
--             d7_composition_term           (share_gate_40 - share_gate_30) x average D7 rate:
--                                           the part due to a different player mix
--             d7_diff_if_extra_never_returned  d7_diff after removing gate_40's extra players
--                                           (players_gate_40 - players_gate_30), assuming none
--                                           of them came back: the gap the extra players
--                                           cannot explain ('All players' row only)
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/09_gate_integrity.sql   (print this result)
--             python -m src.sql_check                             (run every file + reconcile)
--             duckdb -c ".read sql/09_gate_integrity.sql"         (DuckDB CLI)
-- Notes   : - Why rounds can define strata here: rounds are measured after
--             assignment, but play before level 30 is identical in both versions.
--             With sound assignment each low-rounds stratum should split 50/50, and
--             players who met no gate should have the same D7 in both arms, up to
--             chance. 'Rounds < 15' is far below either gate, so no gate can move a
--             player into or out of it.
--           - Rounds are a proxy for levels: fewer than 30 rounds means level 30 was
--             never played; 30 or more does not prove it was. Near the line the gate
--             itself can move a few players (a gate_30 player who reaches the gate
--             after a flawless 29 rounds and stops stays below 30 rounds). That adds
--             gate_30 players below 30, the opposite of the observed excess.
--           - The strata were chosen after the overall WARNING, to localize it, and
--             they are nested (All > rounds < 30 > rounds < 15). Read their SRM rows
--             as diagnostics, not as independent confirmatory tests.
--           - Decomposition: for each partition stratum, within = average share x
--             rate gap and composition = share gap x average rate. This symmetric
--             form leaves no residual, so within + composition summed over the two
--             strata equals the naive gap exactly. Only the within term of
--             'Rounds >= 30' can be caused by the gate: it is the install-level effect
--             if the gate only affects players who reach it; that row's d7_diff is
--             the effect among those players.
--           - d7_within_ci95_* scales the stratum's Wald CI by the average share;
--             src/stats.py scales the Newcombe CI, which agrees closely at these
--             sample sizes. p-values and the Mann-Whitney test of pre-gate play are
--             in src/stats.py / results.json (cookie.gate): DuckDB has no chi-square
--             or normal CDF, so statuses compare chi2 with critical values, as in 03.
--           - gate_40 has one more extra player in the analysis population than in
--             the raw counts, because the excluded outlier is a gate_30 player.
-- =============================================================================

WITH params AS (
    SELECT
        10.827566170662733::DOUBLE AS chi2_crit_p001,   -- chi-square(1 df) upper 0.1% point: chi2 above it <=> p < 0.001
        6.634896601021215::DOUBLE  AS chi2_crit_p01,    -- chi-square(1 df) upper 1% point:   chi2 above it <=> p < 0.01
        1.959963984540054::DOUBLE  AS z_crit_95         -- standard normal 97.5th percentile (two-sided alpha = 0.05)
),

-- Every assigned player, flagged with the analysis-population rule of 05_stg_cookie_cats.sql
players AS (
    SELECT
        CAST(version        AS VARCHAR) AS version,
        CAST(sum_gamerounds AS INTEGER) AS sum_gamerounds,
        CAST(retention_7    AS BOOLEAN) AS retention_7,
        sum_gamerounds <= 10000         AS in_analysis
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
),

-- Pre-gate strata (inclusive bounds on whole rounds). row_type drives step 3:
-- the two 'partition' rows split every player exactly once.
strata (stratum_order, stratum, row_type, stratum_role, min_rounds, max_rounds) AS (
    VALUES
        (1, 'All players',  'total',      'total of the two partition rows',             0, 1000000000),
        (2, 'Rounds < 15',  'drill-down', 'inside rounds < 30, far below either gate',   0,         14),
        (3, 'Rounds < 30',  'partition',  'never reached level 30: met no gate',         0,         29),
        (4, 'Rounds >= 30', 'partition',  'reached level 30: could meet the gate',      30, 1000000000)
),

-- Range join: every player lands in 'All players', in one partition row and, with
-- fewer than 15 rounds, in the drill-down row as well. Rows are never summed across strata.
stratum_counts AS (
    SELECT
        s.stratum_order,
        s.stratum,
        s.row_type,
        s.stratum_role,
        -- step 1: every assigned player (raw file)
        COUNT(*) FILTER (WHERE p.version = 'gate_40')                                     AS assigned_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30')                                     AS assigned_gate_30,
        -- steps 2-3: analysis population
        COUNT(*) FILTER (WHERE p.version = 'gate_40' AND p.in_analysis)                   AS players_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30' AND p.in_analysis)                   AS players_gate_30,
        COUNT(*) FILTER (WHERE p.version = 'gate_40' AND p.in_analysis AND p.retention_7) AS d7_retained_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30' AND p.in_analysis AND p.retention_7) AS d7_retained_gate_30
    FROM players AS p
    JOIN strata AS s
        ON p.sum_gamerounds BETWEEN s.min_rounds AND s.max_rounds
    GROUP BY s.stratum_order, s.stratum, s.row_type, s.stratum_role
),

-- Arm sizes in the analysis population: denominators of each stratum's share of its arm
arm_totals AS (
    SELECT
        players_gate_40 AS all_players_gate_40,
        players_gate_30 AS all_players_gate_30
    FROM stratum_counts
    WHERE row_type = 'total'
),

stratum_rates AS (
    SELECT
        c.*,
        c.assigned_gate_40 - c.assigned_gate_30                AS extra_gate_40,
        c.players_gate_40::DOUBLE / t.all_players_gate_40      AS share_of_arm_gate_40,
        c.players_gate_30::DOUBLE / t.all_players_gate_30      AS share_of_arm_gate_30,
        c.d7_retained_gate_40::DOUBLE / c.players_gate_40      AS d7_rate_gate_40,
        c.d7_retained_gate_30::DOUBLE / c.players_gate_30      AS d7_rate_gate_30,
        (c.d7_retained_gate_40 + c.d7_retained_gate_30)::DOUBLE
            / (c.players_gate_40 + c.players_gate_30)          AS d7_pooled_rate
    FROM stratum_counts AS c
    CROSS JOIN arm_totals AS t
),

stratum_stats AS (
    SELECT
        *,
        -- Pearson chi-square against 50/50 simplifies to (n_40 - n_30)^2 / (n_40 + n_30)
        POWER(extra_gate_40, 2) / (assigned_gate_40 + assigned_gate_30)  AS srm_chi2,
        d7_rate_gate_40 - d7_rate_gate_30                                AS d7_diff,
        -- SE assuming no difference (pooled rate) -> z statistic
        SQRT(d7_pooled_rate * (1 - d7_pooled_rate)
             * (1.0 / players_gate_40 + 1.0 / players_gate_30))          AS d7_se_pooled,
        -- SE without that assumption (each arm keeps its own rate) -> confidence interval
        SQRT(d7_rate_gate_40 * (1 - d7_rate_gate_40) / players_gate_40
           + d7_rate_gate_30 * (1 - d7_rate_gate_30) / players_gate_30)  AS d7_se_unpooled,
        (share_of_arm_gate_40 + share_of_arm_gate_30) / 2                AS avg_share,
        (d7_rate_gate_40 + d7_rate_gate_30) / 2                          AS avg_d7_rate
    FROM stratum_rates
),

-- Symmetric decomposition over the two partition rows (no residual):
--   naive gap = sum over strata of  avg share x rate gap   (within)
--                                 + share gap x avg rate   (composition)
partition_terms AS (
    SELECT
        *,
        CASE WHEN row_type = 'partition'
             THEN avg_share * d7_diff END                                          AS within_term,
        CASE WHEN row_type = 'partition'
             THEN (share_of_arm_gate_40 - share_of_arm_gate_30) * avg_d7_rate END  AS composition_term
    FROM stratum_stats
)

SELECT
    t.stratum,
    t.stratum_role,
    -- step 1: where are gate_40's extra players? (raw assignment counts)
    t.assigned_gate_40,
    t.assigned_gate_30,
    t.extra_gate_40,
    t.srm_chi2,
    CASE
        WHEN t.srm_chi2 > p.chi2_crit_p001 THEN 'FAIL'
        WHEN t.srm_chi2 > p.chi2_crit_p01  THEN 'WARNING'
        ELSE 'PASS'
    END                                                                AS srm_status,
    -- step 2: D7 by stratum and version (analysis population)
    t.players_gate_40,
    t.players_gate_30,
    t.d7_retained_gate_40,
    t.d7_retained_gate_30,
    t.d7_rate_gate_40,
    t.d7_rate_gate_30,
    t.d7_diff,
    t.d7_diff / t.d7_se_pooled                                         AS d7_z,
    t.d7_diff - p.z_crit_95 * t.d7_se_unpooled                         AS d7_diff_ci95_low,
    t.d7_diff + p.z_crit_95 * t.d7_se_unpooled                         AS d7_diff_ci95_high,
    -- step 3: decomposition of the naive D7 gap
    t.share_of_arm_gate_40,
    t.share_of_arm_gate_30,
    CASE t.row_type
        WHEN 'partition' THEN t.within_term
        WHEN 'total'     THEN SUM(t.within_term) OVER ()
    END                                                                AS d7_within_term,
    CASE WHEN t.row_type = 'partition'
         THEN t.avg_share * (t.d7_diff - p.z_crit_95 * t.d7_se_unpooled) END AS d7_within_ci95_low,
    CASE WHEN t.row_type = 'partition'
         THEN t.avg_share * (t.d7_diff + p.z_crit_95 * t.d7_se_unpooled) END AS d7_within_ci95_high,
    CASE t.row_type
        WHEN 'partition' THEN t.composition_term
        WHEN 'total'     THEN SUM(t.composition_term) OVER ()
    END                                                                AS d7_composition_term,
    -- how big is the gap if gate_40's extra players were all non-returners and are removed?
    CASE WHEN t.row_type = 'total' AND t.players_gate_40 > t.players_gate_30
         THEN (t.d7_retained_gate_40 - t.d7_retained_gate_30)::DOUBLE
              / t.players_gate_30 END                                  AS d7_diff_if_extra_never_returned
FROM partition_terms AS t
CROSS JOIN params AS p
ORDER BY t.stratum_order;
