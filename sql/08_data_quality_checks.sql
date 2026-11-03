-- =============================================================================
-- sql/08_data_quality_checks.sql
--
-- Purpose : Data quality (sanity) checks on both raw files before any analysis:
--           row counts, key uniqueness, nulls, value domains, distributions and
--           ranges, and the outlier rule used in staging with its sensitivity.
-- Input   : data/raw/marketing_AB.csv, data/raw/cookie_cats.csv (raw, unfiltered).
-- Output  : 1 row per check - grain: (dataset, check_name).
--             check_id        display order
--             dataset         'marketing_ab' | 'cookie_cats'
--             check_name      what is measured
--             observed_value  the measured value
--             rule            'must be 0' | 'must be >= 0' | 'must be >= 1' |
--                             'warn if > 0' | 'info' (context, no pass / fail)
--             status          'pass' | 'FAIL' | 'warn' | 'info'
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/08_data_quality_checks.sql   (print this result)
--             python -m src.sql_check                                  (run every file + reconcile)
--             duckdb -c ".read sql/08_data_quality_checks.sql"         (DuckDB CLI)
-- Notes   : - Neither file has timestamps, so time coverage, test duration and
--             novelty effects cannot be checked (only the weekday / hour of peak
--             ad exposure exist).
--           - Percentiles use linear interpolation (QUANTILE_CONT), the same as
--             the pandas default, so they reconcile with results.json.
--           - players_over_10000_rounds is excluded in staging (threshold =
--             gamerounds_outlier_max in config.yaml); the *_all_rows vs
--             *_after_exclusion rows show the exclusion does not move retention.
--           - d7_without_d1 is expected, not an error: retention_7 means "came back
--             on day 7", which does not require coming back on day 1.
--           - zero_round_players_flagged_d1 / _d7: players with 0 rounds who are
--             still flagged as retained. The flags therefore mean "came back to the
--             game", not "played a round". It is about 0.1% of players and no
--             conclusion depends on it.
-- =============================================================================

WITH marketing AS (
    SELECT *
    FROM read_csv('data/raw/marketing_AB.csv', header = true)
),

cookie AS (
    SELECT *
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
),

marketing_profile AS (
    SELECT
        COUNT(*)                                                       AS n_rows,
        COUNT(DISTINCT "user id")                                      AS n_distinct_users,
        -- COUNT(*) - COUNT(col) = number of NULLs in col
        (COUNT(*) - COUNT("user id"))      + (COUNT(*) - COUNT("test group"))
          + (COUNT(*) - COUNT(converted))  + (COUNT(*) - COUNT("total ads"))
          + (COUNT(*) - COUNT("most ads day")) + (COUNT(*) - COUNT("most ads hour")) AS null_cells,
        COUNT(*) FILTER (WHERE "test group" NOT IN ('ad', 'psa'))     AS invalid_test_group,
        COUNT(*) FILTER (WHERE "most ads day" NOT IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday',
                                                      'Friday', 'Saturday', 'Sunday')) AS invalid_most_ads_day,
        COUNT(*) FILTER (WHERE "most ads hour" NOT BETWEEN 0 AND 23)   AS invalid_most_ads_hour,
        MIN("total ads")                                               AS total_ads_min,
        QUANTILE_CONT("total ads", 0.5)                                AS total_ads_median,
        QUANTILE_CONT("total ads", 0.99)                               AS total_ads_p99,
        QUANTILE_CONT("total ads", 0.999)                              AS total_ads_p999,
        MAX("total ads")                                               AS total_ads_max,
        COUNT(*) FILTER (WHERE "total ads" > 1000)                     AS users_over_1000_ads
    FROM marketing
),

cookie_profile AS (
    SELECT
        COUNT(*)                                                       AS n_rows,
        COUNT(DISTINCT userid)                                         AS n_distinct_users,
        (COUNT(*) - COUNT(userid))           + (COUNT(*) - COUNT(version))
          + (COUNT(*) - COUNT(sum_gamerounds)) + (COUNT(*) - COUNT(retention_1))
          + (COUNT(*) - COUNT(retention_7))                            AS null_cells,
        COUNT(*) FILTER (WHERE version NOT IN ('gate_30', 'gate_40'))  AS invalid_version,
        MIN(sum_gamerounds)                                            AS rounds_min,
        QUANTILE_CONT(sum_gamerounds, 0.5)                             AS rounds_median,
        QUANTILE_CONT(sum_gamerounds, 0.99)                            AS rounds_p99,
        QUANTILE_CONT(sum_gamerounds, 0.999)                           AS rounds_p999,
        MAX(sum_gamerounds)                                            AS rounds_max,
        COUNT(*) FILTER (WHERE sum_gamerounds = 0)                     AS zero_round_players,
        COUNT(*) FILTER (WHERE sum_gamerounds = 0 AND retention_1)     AS zero_round_flagged_d1,
        COUNT(*) FILTER (WHERE sum_gamerounds = 0 AND retention_7)     AS zero_round_flagged_d7,
        COUNT(*) FILTER (WHERE sum_gamerounds > 10000)                 AS players_over_10000_rounds,
        COUNT(*) FILTER (WHERE sum_gamerounds <= 10000)                AS rows_after_exclusion,
        MAX(sum_gamerounds) FILTER (WHERE sum_gamerounds <= 10000)     AS rounds_max_after_exclusion,
        AVG(retention_1::INTEGER)                                      AS d1_rate_all_rows,
        AVG(retention_1::INTEGER) FILTER (WHERE sum_gamerounds <= 10000) AS d1_rate_after_exclusion,
        AVG(retention_7::INTEGER)                                      AS d7_rate_all_rows,
        AVG(retention_7::INTEGER) FILTER (WHERE sum_gamerounds <= 10000) AS d7_rate_after_exclusion,
        AVG(sum_gamerounds)                                            AS mean_rounds_all_rows,
        AVG(sum_gamerounds) FILTER (WHERE sum_gamerounds <= 10000)     AS mean_rounds_after_exclusion,
        COUNT(*) FILTER (WHERE retention_7 AND NOT retention_1)        AS d7_without_d1
    FROM cookie
),

checks (check_id, dataset, check_name, observed_value, rule) AS (
    SELECT  1, 'marketing_ab', 'rows',                               n_rows,                     'info'         FROM marketing_profile UNION ALL
    SELECT  2, 'marketing_ab', 'duplicate_user_id',                  n_rows - n_distinct_users,  'must be 0'    FROM marketing_profile UNION ALL
    SELECT  3, 'marketing_ab', 'null_cells',                         null_cells,                 'must be 0'    FROM marketing_profile UNION ALL
    SELECT  4, 'marketing_ab', 'invalid_test_group',                 invalid_test_group,         'must be 0'    FROM marketing_profile UNION ALL
    SELECT  5, 'marketing_ab', 'invalid_most_ads_day',               invalid_most_ads_day,       'must be 0'    FROM marketing_profile UNION ALL
    SELECT  6, 'marketing_ab', 'invalid_most_ads_hour',              invalid_most_ads_hour,      'must be 0'    FROM marketing_profile UNION ALL
    SELECT  7, 'marketing_ab', 'total_ads_min',                      total_ads_min,              'must be >= 1' FROM marketing_profile UNION ALL
    SELECT  8, 'marketing_ab', 'total_ads_median',                   total_ads_median,           'info'         FROM marketing_profile UNION ALL
    SELECT  9, 'marketing_ab', 'total_ads_p99',                      total_ads_p99,              'info'         FROM marketing_profile UNION ALL
    SELECT 10, 'marketing_ab', 'total_ads_p999',                     total_ads_p999,             'info'         FROM marketing_profile UNION ALL
    SELECT 11, 'marketing_ab', 'total_ads_max',                      total_ads_max,              'info'         FROM marketing_profile UNION ALL
    SELECT 12, 'marketing_ab', 'users_over_1000_ads',                users_over_1000_ads,        'info'         FROM marketing_profile UNION ALL
    SELECT 13, 'cookie_cats',  'rows',                               n_rows,                     'info'         FROM cookie_profile    UNION ALL
    SELECT 14, 'cookie_cats',  'duplicate_user_id',                  n_rows - n_distinct_users,  'must be 0'    FROM cookie_profile    UNION ALL
    SELECT 15, 'cookie_cats',  'null_cells',                         null_cells,                 'must be 0'    FROM cookie_profile    UNION ALL
    SELECT 16, 'cookie_cats',  'invalid_version',                    invalid_version,            'must be 0'    FROM cookie_profile    UNION ALL
    SELECT 17, 'cookie_cats',  'sum_gamerounds_min',                 rounds_min,                 'must be >= 0' FROM cookie_profile    UNION ALL
    SELECT 18, 'cookie_cats',  'sum_gamerounds_median',              rounds_median,              'info'         FROM cookie_profile    UNION ALL
    SELECT 19, 'cookie_cats',  'sum_gamerounds_p99',                 rounds_p99,                 'info'         FROM cookie_profile    UNION ALL
    SELECT 20, 'cookie_cats',  'sum_gamerounds_p999',                rounds_p999,                'info'         FROM cookie_profile    UNION ALL
    SELECT 21, 'cookie_cats',  'sum_gamerounds_max',                 rounds_max,                 'info'         FROM cookie_profile    UNION ALL
    SELECT 22, 'cookie_cats',  'zero_round_players',                 zero_round_players,         'info'         FROM cookie_profile    UNION ALL
    SELECT 23, 'cookie_cats',  'zero_round_players_flagged_d1',      zero_round_flagged_d1,      'info'         FROM cookie_profile    UNION ALL
    SELECT 24, 'cookie_cats',  'zero_round_players_flagged_d7',      zero_round_flagged_d7,      'info'         FROM cookie_profile    UNION ALL
    SELECT 25, 'cookie_cats',  'players_over_10000_rounds',          players_over_10000_rounds,  'warn if > 0'  FROM cookie_profile    UNION ALL
    SELECT 26, 'cookie_cats',  'rows_after_outlier_exclusion',       rows_after_exclusion,       'info'         FROM cookie_profile    UNION ALL
    SELECT 27, 'cookie_cats',  'sum_gamerounds_max_after_exclusion', rounds_max_after_exclusion, 'info'         FROM cookie_profile    UNION ALL
    SELECT 28, 'cookie_cats',  'd1_retention_all_rows',              d1_rate_all_rows,           'info'         FROM cookie_profile    UNION ALL
    SELECT 29, 'cookie_cats',  'd1_retention_after_exclusion',       d1_rate_after_exclusion,    'info'         FROM cookie_profile    UNION ALL
    SELECT 30, 'cookie_cats',  'd7_retention_all_rows',              d7_rate_all_rows,           'info'         FROM cookie_profile    UNION ALL
    SELECT 31, 'cookie_cats',  'd7_retention_after_exclusion',       d7_rate_after_exclusion,    'info'         FROM cookie_profile    UNION ALL
    SELECT 32, 'cookie_cats',  'mean_rounds_all_rows',               mean_rounds_all_rows,       'info'         FROM cookie_profile    UNION ALL
    SELECT 33, 'cookie_cats',  'mean_rounds_after_exclusion',        mean_rounds_after_exclusion,'info'         FROM cookie_profile    UNION ALL
    SELECT 34, 'cookie_cats',  'd7_without_d1',                      d7_without_d1,              'info'         FROM cookie_profile
)

SELECT
    check_id,
    dataset,
    check_name,
    observed_value,
    rule,
    CASE rule
        WHEN 'must be 0'    THEN CASE WHEN observed_value = 0  THEN 'pass' ELSE 'FAIL' END
        WHEN 'must be >= 0' THEN CASE WHEN observed_value >= 0 THEN 'pass' ELSE 'FAIL' END
        WHEN 'must be >= 1' THEN CASE WHEN observed_value >= 1 THEN 'pass' ELSE 'FAIL' END
        WHEN 'warn if > 0'  THEN CASE WHEN observed_value > 0  THEN 'warn' ELSE 'pass' END
        ELSE 'info'
    END AS status
FROM checks
ORDER BY check_id;
