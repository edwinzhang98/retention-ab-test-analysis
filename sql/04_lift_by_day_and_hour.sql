-- =============================================================================
-- sql/04_lift_by_day_and_hour.sql
--
-- Purpose : Exploratory heterogeneity cuts of the ad experiment: conversion
--           rate per arm and lift (ad - psa) by peak ad day, peak ad hour and
--           exposure bucket of each user (the same three cuts as dashboard page 5).
-- Input   : data/raw/marketing_AB.csv - one row per user (rules as in
--           01_stg_marketing_ab.sql).
-- Output  : 1 row per (dimension, segment) - 7 days, 24 hours, 8 exposure buckets.
--             dimension                'most_ads_day' | 'most_ads_hour' | 'exposure_bucket'
--             segment                  Monday..Sunday | 0..23 | 1-5 .. 200+
--             users_ad, users_psa      users per arm in the segment
--             conversions_ad, conversions_psa
--             conversion_rate_ad, conversion_rate_psa
--             abs_lift                 rate_ad - rate_psa (proportion; x100 = pp)
--             rel_lift                 rate_ad / rate_psa - 1 (NULL if the PSA cell has 0 conversions)
--             z_stat                   pooled two-proportion z statistic
--             significant_unadjusted   |z_stat| > 1.96 with NO multiple-comparison correction
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/04_lift_by_day_and_hour.sql   (print this result)
--             python -m src.sql_check                                   (run every file + reconcile)
--             duckdb -c ".read sql/04_lift_by_day_and_hour.sql"         (DuckDB CLI)
-- Notes   : - All three dimensions are recorded after assignment (heavier users
--             see more ads), so these are descriptive cuts, not causal subgroup
--             effects, and they are never used as covariates.
--           - Testing many segments at alpha = 0.05 produces "significant" cells
--             by chance alone. Holm / Bonferroni / BH adjustment, Newcombe CIs and
--             the interaction likelihood-ratio test live in src/stats.py and
--             reports/tables/ad_lift_by_*.csv; decide on those, not on
--             significant_unadjusted.
--           - Several hour cells have very few PSA users or zero PSA conversions,
--             so per-hour lifts are noisy; a Wald CI would be misleading there and
--             is deliberately not reported.
-- =============================================================================

WITH params AS (
    SELECT 1.959963984540054::DOUBLE AS z_crit_95   -- standard normal 97.5th percentile (two-sided alpha = 0.05)
),

-- Same rules as 01_stg_marketing_ab.sql (repeated so this file runs on its own)
stg_marketing_ab AS (
    SELECT
        CAST("test group"    AS VARCHAR) AS test_group,
        CAST(converted       AS BOOLEAN) AS converted,
        CAST("total ads"     AS INTEGER) AS total_ads,
        CAST("most ads day"  AS VARCHAR) AS most_ads_day,
        CAST("most ads hour" AS INTEGER) AS most_ads_hour
    FROM read_csv('data/raw/marketing_AB.csv', header = true)
),

weekdays (most_ads_day, day_order) AS (
    VALUES
        ('Monday', 1), ('Tuesday', 2), ('Wednesday', 3), ('Thursday', 4),
        ('Friday', 5), ('Saturday', 6), ('Sunday', 7)
),

exposure_buckets (exposure_bucket, bucket_order, min_ads, max_ads) AS (
    VALUES
        ('1-5',     1,   1,          5),
        ('6-10',    2,   6,         10),
        ('11-20',   3,  11,         20),
        ('21-35',   4,  21,         35),
        ('36-50',   5,  36,         50),
        ('51-100',  6,  51,        100),
        ('101-200', 7, 101,        200),
        ('200+',    8, 201, 1000000000)
),

-- Long format: every user appears once per dimension, so one GROUP BY serves all three cuts
user_segments AS (
    SELECT
        1                  AS dimension_order,
        'most_ads_day'     AS dimension,
        u.most_ads_day     AS segment,
        d.day_order        AS segment_order,
        u.test_group,
        u.converted
    FROM stg_marketing_ab AS u
    LEFT JOIN weekdays AS d USING (most_ads_day)

    UNION ALL

    SELECT
        2,
        'most_ads_hour',
        CAST(u.most_ads_hour AS VARCHAR),
        u.most_ads_hour,
        u.test_group,
        u.converted
    FROM stg_marketing_ab AS u

    UNION ALL

    SELECT
        3,
        'exposure_bucket',
        b.exposure_bucket,
        b.bucket_order,
        u.test_group,
        u.converted
    FROM stg_marketing_ab AS u
    LEFT JOIN exposure_buckets AS b
        ON u.total_ads BETWEEN b.min_ads AND b.max_ads
),

segment_counts AS (
    SELECT
        dimension_order,
        dimension,
        segment_order,
        segment,
        COUNT(*) FILTER (WHERE test_group = 'ad')                AS users_ad,
        COUNT(*) FILTER (WHERE test_group = 'psa')               AS users_psa,
        COUNT(*) FILTER (WHERE test_group = 'ad'  AND converted) AS conversions_ad,
        COUNT(*) FILTER (WHERE test_group = 'psa' AND converted) AS conversions_psa
    FROM user_segments
    GROUP BY dimension_order, dimension, segment_order, segment
),

segment_rates AS (
    SELECT
        *,
        conversions_ad::DOUBLE  / users_ad                                  AS conversion_rate_ad,
        conversions_psa::DOUBLE / users_psa                                 AS conversion_rate_psa,
        (conversions_ad + conversions_psa)::DOUBLE / (users_ad + users_psa) AS pooled_rate
    FROM segment_counts
),

segment_stats AS (
    SELECT
        *,
        conversion_rate_ad - conversion_rate_psa                AS abs_lift,
        conversion_rate_ad / NULLIF(conversion_rate_psa, 0) - 1 AS rel_lift,
        (conversion_rate_ad - conversion_rate_psa)
            / SQRT(pooled_rate * (1 - pooled_rate) * (1.0 / users_ad + 1.0 / users_psa)) AS z_stat
    FROM segment_rates
)

SELECT
    s.dimension,
    s.segment,
    s.users_ad,
    s.users_psa,
    s.conversions_ad,
    s.conversions_psa,
    s.conversion_rate_ad,
    s.conversion_rate_psa,
    s.abs_lift,
    s.rel_lift,
    s.z_stat,
    ABS(s.z_stat) > p.z_crit_95 AS significant_unadjusted
FROM segment_stats AS s
CROSS JOIN params AS p
ORDER BY s.dimension_order, s.segment_order;
