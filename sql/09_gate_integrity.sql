-- =============================================================================
-- sql/09_gate_integrity.sql
--
-- Purpose : The integrity checks behind the Cookie Cats gate readout. Its 50/50
--           SRM check returns a WARNING (03_srm_check.sql), so the naive D7 gap
--           (07_gate_experiment.sql) is reported, not certified. Six steps, on
--           bands of rounds played (play before level 30 is identical in both
--           versions, and rounds >= levels):
--             1. Assignment by rounds band (raw counts): where gate_40's net
--                excess of installs sits.
--             2. D7 and D1 by band and version. Players with < 30 rounds never
--                met a gate, so with sound assignment their retention should not
--                differ (negative control).
--             3. Decomposition of the naive D7 and D1 gaps into player mix, the
--                gap among players who never met a gate, and the part the gate
--                could explain (players with 30+ rounds).
--             4. Best case for gate_40: the D7 gap if every one of gate_40's
--                extra installs never returned.
--             5. Play: pre-gate rounds, and rounds among players with 30+ rounds
--                (the engagement guardrail where the gate can act).
--             6. Re-test sizing at a D7 change fixed in advance.
-- Input   : data/raw/cookie_cats.csv - one row per player. Step 1 counts every
--           assigned player (as 03_srm_check.sql); steps 2-6 use the analysis
--           population (outlier excluded, as 05_stg_cookie_cats.sql and 07).
-- Output  : 23 rows - grain: (section, population, measure).
--             section          'assignment' (step 1) | 'retention' (steps 2-3) |
--                              'best case for gate_40' (step 4) | 'play' (step 5) |
--                              're-test sizing' (step 6)
--             population       'All players' | 'Rounds < 15' | 'Rounds 15-29' | 'Rounds < 30' |
--                              'Rounds >= 30' | 'Rounds < 30, net excess removed' |
--                              'All players, extra installs removed'
--             measure          'assigned players' | 'D7' | 'D1' |
--                              'pre-gate rounds (capped at 29), mean' | 'rounds, median' |
--                              'rounds, mean' | 'share with 40+ rounds' | 'D7 change to detect'
--             reading          how to read the row
--             n_gate_40, n_gate_30          players per arm (step 1: assigned players, raw file)
--             k_gate_40, k_gate_30          players with the outcome (back on day 7 / day 1, or
--                                           40+ rounds); NULL when the measure is not a share
--             value_gate_40, value_gate_30  the measure per arm: k / n for shares, the median or
--                                           mean for rounds, n for 'assigned players'. Step 6:
--                                           gate_30's D7 (baseline) and the baseline minus the change
--             difference                    value_gate_40 - value_gate_30 (shares: proportion,
--                                           x100 = pp). Step 1: gate_40's net excess of players
--             z_stat                        shares: pooled two-proportion z statistic. Step 1:
--                                           (n_gate_40 - n_gate_30) / SQRT(n_gate_40 + n_gate_30),
--                                           whose square is the 50/50 SRM chi-square
--             ci95_low, ci95_high           shares: 95% Newcombe (hybrid score) CI for difference,
--                                           the interval in results.json
--           Step 3 - decomposition, on the 'retention' rows ('Rounds < 30' and
--           'Rounds >= 30' split every player exactly once; the 'All players' row
--           holds their sums):
--             share_of_arm_gate_40, _gate_30  players in the band / players in the arm
--             within_term                   average share x difference: the band's part of the
--                                           gap with the player mix held equal
--             within_ci95_low, _high        average share x the CI (the share is treated as fixed)
--             composition_term              (share_gate_40 - share_gate_30) x average rate: the
--                                           part due to a different player mix
--           Step 6 - sizing, on the 're-test sizing' rows:
--             players_needed_5050           players (both arms) needed to detect difference with
--                                           80% power at two-sided alpha = 0.05, split 50/50
--             installs_needed_5050          installs that yield that many players
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/09_gate_integrity.sql   (print this result)
--             python -m src.sql_check                             (run every file + reconcile)
--             duckdb -c ".read sql/09_gate_integrity.sql"         (DuckDB CLI)
-- Notes   : - Why rounds can define bands here: rounds are counted after
--             assignment, but below level 30 both versions are identical and
--             rounds >= levels, so whether a player ever plays 30 rounds cannot
--             depend on the gate; it behaves like a pre-treatment trait. (Total ads
--             in the ad experiment cannot be used this way: ads can change how long
--             a user stays.) 'Rounds >= 30' means "could have reached level 30":
--             the file has no level field.
--           - The bands are an approximation near the line: a gate_30 player who
--             meets the gate after a flawless 29 rounds and stops stays below 30
--             rounds. That pushes in the opposite direction to the observed gaps,
--             and it is why the 'Rounds >= 30' within term is called "the part the
--             gate could explain", never an estimate of the gate's effect.
--           - Step 1: the bands were chosen after seeing the overall SRM result,
--             to localize it, and they are nested (All > rounds < 30 > rounds < 15).
--             Their p-values are descriptive, so these rows carry no SRM status
--             label. A net excess is a difference in counts, not a set of
--             identified players.
--           - Step 2: 'Rounds < 15' and 'Rounds 15-29' split 'Rounds < 30'.
--             'Rounds < 30, net excess removed' drops gate_40's net excess of
--             < 15-round players (step 1) and assumes none of them came back.
--           - Step 3: for each of the two partition bands, within = average share
--             x rate gap and composition = share gap x average rate. This symmetric
--             form leaves no residual, so the parts add up to the naive gap exactly.
--             Player mix and the never-met-a-gate part sit where the gate cannot
--             act. Read the 'Rounds >= 30' within term next to the 'Rounds 15-29'
--             rows: those players never met a gate either.
--           - Step 4: the reading most favourable to gate_40 (every extra install
--             a junk install that never came back). Extra installs here = gate_40
--             minus gate_30 players in the analysis population: one more than in
--             the raw counts, because the excluded outlier is a gate_30 player.
--           - Step 5: the all-player rounds difference carries the same imbalance
--             as D7, so the engagement guardrail is read among players with 30+
--             rounds. The Mann-Whitney tests and the bootstrap CI of the mean
--             difference are Python-only (src/analysis.py -> results.json).
--           - Step 6: sized at a change fixed in advance, never at the observed
--             effect. smallest_d7_change (params) mirrors config.yaml
--             gate_smallest_d7_change_pp, a per-install placeholder to agree with the
--             Game PM. Among players with 30+ rounds the same per-install change is
--             change / average share. Both rows are sized for a drop, as
--             src/analysis.py does. Closed form on Cohen's h: per arm
--             n = 2 x ((z_0.975 + z_0.80) / h)^2, total = 2n rounded up. src/stats.py
--             solves the exact two-sided power equation instead; the extra tail
--             moves the total by less than one player here, so after rounding up
--             the totals equal results.json, and src/sql_check.py checks that they
--             stay equal.
--           - DuckDB has no normal CDF: src/sql_check.py turns z_stat into a
--             two-sided p-value and compares it with results.json.
--           - Newcombe CI: built from each arm's Wilson score interval (Newcombe
--             1998, method 10), the formula behind statsmodels'
--             confint_proportions_2indep(method="newcomb") in src/stats.py.
--             07_gate_experiment.sql shows the Wald CI of the naive gap instead.
-- =============================================================================

WITH params AS (
    SELECT
        1.959963984540054::DOUBLE  AS z_crit_95,           -- standard normal 97.5th percentile (two-sided alpha = 0.05)
        0.8416212335729143::DOUBLE AS z_power_80,          -- standard normal 80th percentile (power = 0.80)
        0.005::DOUBLE              AS smallest_d7_change   -- per install, as a proportion (0.5 pp); see Notes
),

-- Every assigned player, flagged with the analysis-population rule of 05_stg_cookie_cats.sql
players AS (
    SELECT
        CAST(version        AS VARCHAR) AS version,
        CAST(sum_gamerounds AS INTEGER) AS sum_gamerounds,
        CAST(retention_1    AS BOOLEAN) AS retention_1,
        CAST(retention_7    AS BOOLEAN) AS retention_7,
        sum_gamerounds <= 10000         AS in_analysis
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
),

-- Rounds bands (inclusive bounds on whole rounds). band_role drives step 3: the two
-- 'partition' bands split every player exactly once.
bands (band_order, population, band_role, reading, min_rounds, max_rounds) AS (
    VALUES
        (1, 'All players',  'total',      'every player',                                       0, 1000000000),
        (2, 'Rounds < 15',  'drill-down', 'never met a gate; far below either gate',            0,         14),
        (3, 'Rounds 15-29', 'drill-down', 'never met a gate',                                  15,         29),
        (4, 'Rounds < 30',  'partition',  'never met a gate: the negative control',             0,         29),
        (5, 'Rounds >= 30', 'partition',  'could have reached level 30: could meet the gate', 30, 1000000000)
),

-- Range join: every player lands in 'All players', in one partition band and in one
-- drill-down band (or none, with 30+ rounds). Counts are never summed across bands.
band_counts AS (
    SELECT
        b.band_order,
        b.population,
        b.band_role,
        b.reading,
        -- step 1: every assigned player (raw file)
        COUNT(*) FILTER (WHERE p.version = 'gate_40')                                     AS assigned_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30')                                     AS assigned_gate_30,
        -- steps 2-6: analysis population
        COUNT(*) FILTER (WHERE p.version = 'gate_40' AND p.in_analysis)                   AS players_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30' AND p.in_analysis)                   AS players_gate_30,
        COUNT(*) FILTER (WHERE p.version = 'gate_40' AND p.in_analysis AND p.retention_7) AS d7_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30' AND p.in_analysis AND p.retention_7) AS d7_gate_30,
        COUNT(*) FILTER (WHERE p.version = 'gate_40' AND p.in_analysis AND p.retention_1) AS d1_gate_40,
        COUNT(*) FILTER (WHERE p.version = 'gate_30' AND p.in_analysis AND p.retention_1) AS d1_gate_30
    FROM players AS p
    JOIN bands AS b
        ON p.sum_gamerounds BETWEEN b.min_rounds AND b.max_rounds
    GROUP BY b.band_order, b.population, b.band_role, b.reading
),

-- gate_40's extra players: net excess among < 15-round players (raw counts, step 1) and
-- over all players in the analysis population (step 4)
excess AS (
    SELECT
        MAX(assigned_gate_40 - assigned_gate_30) FILTER (WHERE population = 'Rounds < 15') AS net_excess_lt_15,
        MAX(players_gate_40 - players_gate_30)   FILTER (WHERE population = 'All players') AS extra_gate_40
    FROM band_counts
),

-- Step 5 inputs: rounds per arm, analysis population
play AS (
    SELECT
        COUNT(*) FILTER (WHERE version = 'gate_40')                                          AS players_gate_40,
        COUNT(*) FILTER (WHERE version = 'gate_30')                                          AS players_gate_30,
        AVG(LEAST(sum_gamerounds, 29)) FILTER (WHERE version = 'gate_40')                    AS pre_gate_mean_gate_40,
        AVG(LEAST(sum_gamerounds, 29)) FILTER (WHERE version = 'gate_30')                    AS pre_gate_mean_gate_30,
        COUNT(*) FILTER (WHERE version = 'gate_40' AND sum_gamerounds >= 30)                 AS reach_gate_40,
        COUNT(*) FILTER (WHERE version = 'gate_30' AND sum_gamerounds >= 30)                 AS reach_gate_30,
        COUNT(*) FILTER (WHERE version = 'gate_40' AND sum_gamerounds >= 40)                 AS past_40_gate_40,
        COUNT(*) FILTER (WHERE version = 'gate_30' AND sum_gamerounds >= 40)                 AS past_40_gate_30,
        -- QUANTILE_CONT interpolates like the pandas median
        QUANTILE_CONT(sum_gamerounds, 0.5) FILTER (WHERE version = 'gate_40' AND sum_gamerounds >= 30) AS reach_median_gate_40,
        QUANTILE_CONT(sum_gamerounds, 0.5) FILTER (WHERE version = 'gate_30' AND sum_gamerounds >= 30) AS reach_median_gate_30,
        AVG(sum_gamerounds) FILTER (WHERE version = 'gate_40' AND sum_gamerounds >= 30)      AS reach_mean_gate_40,
        AVG(sum_gamerounds) FILTER (WHERE version = 'gate_30' AND sum_gamerounds >= 30)      AS reach_mean_gate_30
    FROM players
    WHERE in_analysis
),

-- Every two-proportion comparison of gate_40 vs gate_30 (steps 2, 4 and 5), one row each
comparisons AS (
    -- step 2: D7 and D1 by band
    SELECT
        2                                                         AS section_order,
        'retention'                                               AS section,
        CASE WHEN band_order = 5 THEN 6 ELSE band_order END       AS row_order,
        population,
        band_role,
        reading,
        'D7'                                                      AS measure,
        players_gate_40                                           AS n_gate_40,
        players_gate_30                                           AS n_gate_30,
        d7_gate_40                                                AS k_gate_40,
        d7_gate_30                                                AS k_gate_30
    FROM band_counts

    UNION ALL

    SELECT 2, 'retention', 6 + band_order, population, band_role, reading, 'D1',
           players_gate_40, players_gate_30, d1_gate_40, d1_gate_30
    FROM band_counts

    UNION ALL

    -- step 2 sensitivity: the negative control without gate_40's net excess of < 15-round players
    SELECT 2, 'retention', 5, 'Rounds < 30, net excess removed', 'sensitivity',
           'net excess of < 15-round gate_40 players removed, assumed never to return', 'D7',
           c.players_gate_40 - e.net_excess_lt_15, c.players_gate_30, c.d7_gate_40, c.d7_gate_30
    FROM band_counts AS c
    CROSS JOIN excess AS e
    WHERE c.population = 'Rounds < 30'

    UNION ALL

    -- step 4: best case for gate_40
    SELECT 4, 'best case for gate_40', 1, 'All players, extra installs removed', 'sensitivity',
           'gate_40''s extra installs removed, assumed never to return: the reading most favourable to gate_40',
           'D7', c.players_gate_40 - e.extra_gate_40, c.players_gate_30, c.d7_gate_40, c.d7_gate_30
    FROM band_counts AS c
    CROSS JOIN excess AS e
    WHERE c.population = 'All players'

    UNION ALL

    -- step 5: share of players with 30+ rounds who go on to 40+ rounds
    SELECT 5, 'play', 4, 'Rounds >= 30', 'partition', 'engagement guardrail where the gate can act',
           'share with 40+ rounds', reach_gate_40, reach_gate_30, past_40_gate_40, past_40_gate_30
    FROM play
),

comparison_rates AS (
    SELECT
        *,
        k_gate_40::DOUBLE / n_gate_40                             AS rate_gate_40,
        k_gate_30::DOUBLE / n_gate_30                             AS rate_gate_30,
        -- common rate if the gate position had no effect (H0); used for the z test
        (k_gate_40 + k_gate_30)::DOUBLE / (n_gate_40 + n_gate_30) AS pooled_rate
    FROM comparisons
),

-- Wilson score interval for each arm's rate: centre +/- half-width
wilson AS (
    SELECT
        c.*,
        (c.rate_gate_40 + POWER(p.z_crit_95, 2) / (2 * c.n_gate_40))
            / (1 + POWER(p.z_crit_95, 2) / c.n_gate_40)                                        AS wilson_centre_40,
        p.z_crit_95 * SQRT(c.rate_gate_40 * (1 - c.rate_gate_40) / c.n_gate_40
                           + POWER(p.z_crit_95, 2) / (4 * POWER(c.n_gate_40, 2)))
            / (1 + POWER(p.z_crit_95, 2) / c.n_gate_40)                                        AS wilson_half_40,
        (c.rate_gate_30 + POWER(p.z_crit_95, 2) / (2 * c.n_gate_30))
            / (1 + POWER(p.z_crit_95, 2) / c.n_gate_30)                                        AS wilson_centre_30,
        p.z_crit_95 * SQRT(c.rate_gate_30 * (1 - c.rate_gate_30) / c.n_gate_30
                           + POWER(p.z_crit_95, 2) / (4 * POWER(c.n_gate_30, 2)))
            / (1 + POWER(p.z_crit_95, 2) / c.n_gate_30)                                        AS wilson_half_30
    FROM comparison_rates AS c
    CROSS JOIN params AS p
),

-- Pooled z statistic and Newcombe hybrid score CI:
--   low  = diff - SQRT((rate_40 - wilson_low_40)^2 + (wilson_high_30 - rate_30)^2)
--   high = diff + SQRT((rate_30 - wilson_low_30)^2 + (wilson_high_40 - rate_40)^2)
comparison_stats AS (
    SELECT
        *,
        rate_gate_40 - rate_gate_30                                                       AS difference,
        (rate_gate_40 - rate_gate_30)
            / SQRT(pooled_rate * (1 - pooled_rate) * (1.0 / n_gate_40 + 1.0 / n_gate_30)) AS z_stat,
        (rate_gate_40 - rate_gate_30)
            - SQRT(POWER(rate_gate_40 - (wilson_centre_40 - wilson_half_40), 2)
                 + POWER((wilson_centre_30 + wilson_half_30) - rate_gate_30, 2))          AS ci95_low,
        (rate_gate_40 - rate_gate_30)
            + SQRT(POWER(rate_gate_30 - (wilson_centre_30 - wilson_half_30), 2)
                 + POWER((wilson_centre_40 + wilson_half_40) - rate_gate_40, 2))          AS ci95_high
    FROM wilson
),

-- Arm sizes in the analysis population: denominators of each band's share of its arm
arm_totals AS (
    SELECT
        players_gate_40 AS all_players_gate_40,
        players_gate_30 AS all_players_gate_30
    FROM band_counts
    WHERE band_role = 'total'
),

-- Step 3: symmetric decomposition over the two partition bands (no residual):
--   naive gap = sum over bands of  average share x rate gap   (within)
--                                + share gap x average rate   (composition)
retention_terms AS (
    SELECT
        s.*,
        s.n_gate_40::DOUBLE / t.all_players_gate_40                                 AS share_of_arm_gate_40,
        s.n_gate_30::DOUBLE / t.all_players_gate_30                                 AS share_of_arm_gate_30,
        (s.n_gate_40::DOUBLE / t.all_players_gate_40
         + s.n_gate_30::DOUBLE / t.all_players_gate_30) / 2                         AS avg_share,
        CASE WHEN s.band_role = 'partition'
             THEN (s.n_gate_40::DOUBLE / t.all_players_gate_40
                   + s.n_gate_30::DOUBLE / t.all_players_gate_30) / 2 * s.difference END  AS within_part,
        CASE WHEN s.band_role = 'partition'
             THEN (s.n_gate_40::DOUBLE / t.all_players_gate_40
                   - s.n_gate_30::DOUBLE / t.all_players_gate_30)
                  * (s.rate_gate_40 + s.rate_gate_30) / 2 END                       AS composition_part
    FROM comparison_stats AS s
    CROSS JOIN arm_totals AS t
    WHERE s.section = 'retention'
),

retention_rows AS (
    SELECT
        *,
        CASE band_role
            WHEN 'partition' THEN within_part
            WHEN 'total'     THEN SUM(within_part) OVER (PARTITION BY measure)
        END                                                                         AS within_term,
        CASE WHEN band_role = 'partition' THEN avg_share * ci95_low END             AS within_ci95_low,
        CASE WHEN band_role = 'partition' THEN avg_share * ci95_high END            AS within_ci95_high,
        CASE band_role
            WHEN 'partition' THEN composition_part
            WHEN 'total'     THEN SUM(composition_part) OVER (PARTITION BY measure)
        END                                                                         AS composition_term
    FROM retention_terms
),

-- Step 6: the D7 baselines and the change to detect, per install and among players with 30+ rounds
sizing_inputs AS (
    SELECT
        1                                                             AS row_order,
        'All players'                                                 AS population,
        'analysed over all installs'                                  AS reading,
        r.rate_gate_30                                                AS baseline_rate,
        p.smallest_d7_change                                          AS change,
        1.0::DOUBLE                                                   AS share_of_installs
    FROM retention_rows AS r
    CROSS JOIN params AS p
    WHERE r.measure = 'D7' AND r.population = 'All players'

    UNION ALL

    SELECT
        2,
        'Rounds >= 30',
        'primary analysis (pre-registered): players with 30+ rounds',
        r.rate_gate_30,
        p.smallest_d7_change / r.avg_share,   -- the same per-install change, concentrated on these players
        r.avg_share
    FROM retention_rows AS r
    CROSS JOIN params AS p
    WHERE r.measure = 'D7' AND r.population = 'Rounds >= 30'
),

-- Cohen's h for a drop of that size: h = |2 asin(sqrt(p_c - change)) - 2 asin(sqrt(p_c))|
sizing_effect AS (
    SELECT
        s.*,
        ABS(2 * ASIN(SQRT(s.baseline_rate - s.change)) - 2 * ASIN(SQRT(s.baseline_rate))) AS cohens_h,
        p.z_crit_95,
        p.z_power_80
    FROM sizing_inputs AS s
    CROSS JOIN params AS p
),

-- 50/50: per arm n = 2 x ((z_0.975 + z_0.80) / h)^2; total = 2n, rounded up to whole players
sizing AS (
    SELECT
        *,
        CAST(CEIL(4 * POWER((z_crit_95 + z_power_80) / cohens_h, 2)) AS BIGINT) AS players_needed_5050
    FROM sizing_effect
),

all_rows AS (
    -- step 1: assignment by band, raw counts (no status label: see Notes)
    SELECT
        1                                                              AS section_order,
        band_order                                                     AS row_order,
        'assignment'                                                   AS section,
        population,
        'assigned players'                                             AS measure,
        CASE WHEN band_role = 'total'
             THEN 'every assigned player; overall SRM status in 03_srm_check.sql'
             ELSE 'subset chosen after the overall warning: p descriptive, no status' END AS reading,
        assigned_gate_40                                               AS n_gate_40,
        assigned_gate_30                                               AS n_gate_30,
        NULL::BIGINT                                                   AS k_gate_40,
        NULL::BIGINT                                                   AS k_gate_30,
        assigned_gate_40::DOUBLE                                       AS value_gate_40,
        assigned_gate_30::DOUBLE                                       AS value_gate_30,
        (assigned_gate_40 - assigned_gate_30)::DOUBLE                  AS difference,
        (assigned_gate_40 - assigned_gate_30)
            / SQRT(assigned_gate_40 + assigned_gate_30)                AS z_stat,
        NULL::DOUBLE                                                   AS ci95_low,
        NULL::DOUBLE                                                   AS ci95_high,
        NULL::DOUBLE                                                   AS share_of_arm_gate_40,
        NULL::DOUBLE                                                   AS share_of_arm_gate_30,
        NULL::DOUBLE                                                   AS within_term,
        NULL::DOUBLE                                                   AS within_ci95_low,
        NULL::DOUBLE                                                   AS within_ci95_high,
        NULL::DOUBLE                                                   AS composition_term,
        NULL::BIGINT                                                   AS players_needed_5050,
        NULL::BIGINT                                                   AS installs_needed_5050
    FROM band_counts

    UNION ALL

    -- steps 2-3: D7 and D1 by band, with the decomposition columns
    SELECT
        section_order, row_order, section, population, measure,
        CASE WHEN band_role = 'total' THEN 'naive comparison, not certified' ELSE reading END,
        n_gate_40, n_gate_30, k_gate_40, k_gate_30,
        rate_gate_40, rate_gate_30, difference, z_stat, ci95_low, ci95_high,
        CASE WHEN band_role <> 'sensitivity' THEN share_of_arm_gate_40 END,
        CASE WHEN band_role <> 'sensitivity' THEN share_of_arm_gate_30 END,
        within_term, within_ci95_low, within_ci95_high, composition_term,
        NULL, NULL
    FROM retention_rows

    UNION ALL

    -- step 4: best case for gate_40; step 5: share with 40+ rounds
    SELECT
        section_order, row_order, section, population, measure, reading,
        n_gate_40, n_gate_30, k_gate_40, k_gate_30,
        rate_gate_40, rate_gate_30, difference, z_stat, ci95_low, ci95_high,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    FROM comparison_stats
    WHERE section <> 'retention'

    UNION ALL

    -- step 5: rounds per arm (tests and CIs for these are Python-only, see Notes)
    SELECT 5, 1, 'play', 'All players', 'pre-gate rounds (capped at 29), mean',
           'play before the first gate: identical in both versions by design',
           players_gate_40, players_gate_30, NULL, NULL,
           pre_gate_mean_gate_40, pre_gate_mean_gate_30, pre_gate_mean_gate_40 - pre_gate_mean_gate_30,
           NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    FROM play

    UNION ALL

    SELECT 5, 2, 'play', 'Rounds >= 30', 'rounds, median', 'Mann-Whitney test in src/analysis.py',
           reach_gate_40, reach_gate_30, NULL, NULL,
           reach_median_gate_40, reach_median_gate_30, reach_median_gate_40 - reach_median_gate_30,
           NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    FROM play

    UNION ALL

    SELECT 5, 3, 'play', 'Rounds >= 30', 'rounds, mean', 'bootstrap CI in src/analysis.py',
           reach_gate_40, reach_gate_30, NULL, NULL,
           reach_mean_gate_40, reach_mean_gate_30, reach_mean_gate_40 - reach_mean_gate_30,
           NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    FROM play

    UNION ALL

    -- step 6: re-test sizing
    SELECT 6, row_order, 're-test sizing', population, 'D7 change to detect', reading,
           NULL, NULL, NULL, NULL,
           baseline_rate - change, baseline_rate, -change,
           NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
           players_needed_5050,
           CAST(CEIL(players_needed_5050 / share_of_installs) AS BIGINT)
    FROM sizing
)

SELECT
    section,
    population,
    measure,
    reading,
    n_gate_40,
    n_gate_30,
    k_gate_40,
    k_gate_30,
    value_gate_40,
    value_gate_30,
    difference,
    z_stat,
    ci95_low,
    ci95_high,
    share_of_arm_gate_40,
    share_of_arm_gate_30,
    within_term,
    within_ci95_low,
    within_ci95_high,
    composition_term,
    players_needed_5050,
    installs_needed_5050
FROM all_rows
ORDER BY section_order, row_order;
