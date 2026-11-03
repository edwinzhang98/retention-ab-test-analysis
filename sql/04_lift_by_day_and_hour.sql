-- =============================================================================
-- sql/04_lift_by_day_and_hour.sql
--
-- Purpose : Exploratory heterogeneity cuts of the ad experiment, by the user's
--           peak ad day, peak ad hour, daypart (peak hour in 6-hour blocks) and
--           exposure bucket (the cuts on dashboard page 5). Each segment answers
--           two different questions:
--             1. Is there a lift in this segment?                       (z_stat)
--             2. Does this segment's lift differ from the other
--                segments' lift? - the heterogeneity question        (z_vs_rest)
-- Input   : data/raw/marketing_AB.csv - one row per user (rules as in
--           01_stg_marketing_ab.sql).
-- Output  : 1 row per (dimension, segment) - 7 days, 24 hours, 4 dayparts,
--           8 exposure buckets.
--             dimension                     'most_ads_day' | 'most_ads_hour' | 'daypart' |
--                                           'exposure_bucket'
--             segment                       Monday..Sunday | 0..23 | Night (0-5)..Evening (18-23) |
--                                           1-5 .. 200+
--             users_ad, users_psa           users per arm in the segment
--             share_of_arm_ad, _psa         users in the segment / users in the arm: each arm's
--                                           mix across the segments of the dimension
--             conversions_ad, conversions_psa
--             conversion_rate_ad, conversion_rate_psa
--             abs_lift                      rate_ad - rate_psa (proportion; x100 = pp)
--             rel_lift                      rate_ad / rate_psa - 1 (NULL if the PSA cell has 0 conversions)
--             z_stat                        pooled two-proportion z statistic: is the lift != 0 here?
--             lift_significant_unadjusted   |z_stat| > 1.96, with NO multiple-comparison correction
--             incremental_conversions       abs_lift * users_ad: each segment against its own PSA rate
--             lift_rest                     lift among all OTHER segments of the dimension
--             diff_vs_rest                  abs_lift - lift_rest: the raw difference between the
--                                           segment's lift and the other segments' lift (point estimate)
--             diff_vs_rest_ac               the same difference on Agresti-Caffo adjusted proportions
--                                           ((conversions + 1) / (users + 2) in each of the four
--                                           groups): the centre of the CI and of the test
--             diff_vs_rest_ci95_low, _high  95% Agresti-Caffo CI: diff_vs_rest_ac +/- 1.96 x its SE
--             z_vs_rest                     diff_vs_rest_ac / its standard error
--             differs_from_rest_unadjusted  |z_vs_rest| > 1.96, with NO multiple-comparison correction
--             standardized_lift             Mantel-Haenszel weighted average of the segment lifts
--                                           (one value per dimension, repeated on its rows)
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/04_lift_by_day_and_hour.sql   (print this result)
--             python -m src.sql_check                                   (run every file + reconcile)
--             duckdb -c ".read sql/04_lift_by_day_and_hour.sql"         (DuckDB CLI)
-- Notes   : - All four dimensions are recorded after assignment (heavier users see
--             more ads), so these are descriptive cuts, not causal subgroup effects,
--             and never covariates. share_of_arm_* shows that the arms' mixes differ
--             a little: the exposure-parity check the quota-exact SRM pass cannot give.
--           - Two questions, two tests. Because the overall lift is real, most large
--             segments show a lift != 0; how many do mostly measures segment size
--             (power), not heterogeneity. Heterogeneity is z_vs_rest. With m segments
--             at alpha = 0.05 about m x 0.05 contrasts cross 1.96 by chance (0.35 for
--             days, 1.2 for hours), so decide on corrected results: the interaction
--             likelihood-ratio test per dimension, Holm / Bonferroni / BH adjustment
--             and the Newcombe CIs are in src/stats.py and reports/tables/ad_lift_by_*.csv
--             (DuckDB has no normal CDF for p-values).
--           - Point estimate vs interval: diff_vs_rest is the raw difference; its CI
--             and z_vs_rest use the Agresti-Caffo adjustment, which keeps cells with
--             0 PSA conversions (6 hours: 0-2 and 4-6, mostly night) from getting a
--             zero variance and a spurious contrast. In sparse cells the CI is
--             therefore not centred on diff_vs_rest (its centre is diff_vs_rest_ac);
--             in large cells the two differ very little. Same convention as
--             src/stats.py segment_lifts and reports/tables/ad_lift_by_*.csv.
--           - Peak day / hour describe the user's habits, recorded after
--             assignment, not a slot the media plan bought. A pattern here is a
--             hypothesis for a pre-registered test that randomizes the delivery
--             schedule (weekday and time slot), not a reason to re-plan spend.
--           - standardized_lift is a sensitivity check on post-assignment strata:
--             if it stays close to the crude lift in 02_conversion_by_group.sql for
--             every dimension, the segment mix does not explain the headline (no
--             Simpson's reversal).
--           - In exposure buckets, control conversion rises steeply with exposure:
--             exposure tracks how active a user is, so the bucket pattern says where
--             the lift lives, not what an extra ad does (no frequency curve).
--           - Bucket-by-bucket incremental conversions use each bucket's own PSA
--             rate, so their sum differs from the headline incremental_conversions
--             in 02_conversion_by_group.sql, and the lowest buckets can be negative.
--             Pooled, buckets 1-5, 6-10 and 11-20 are the users with 20 ads or
--             fewer (results.json le_20_ads_pooled); that pooled test and its MDE
--             are Python-only.
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

dayparts (daypart, daypart_order, min_hour, max_hour) AS (
    VALUES
        ('Night (0-5)',       1,  0,  5),
        ('Morning (6-11)',    2,  6, 11),
        ('Afternoon (12-17)', 3, 12, 17),
        ('Evening (18-23)',   4, 18, 23)
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

-- Long format: every user appears once per dimension, so one GROUP BY serves all four cuts
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
        'daypart',
        p.daypart,
        p.daypart_order,
        u.test_group,
        u.converted
    FROM stg_marketing_ab AS u
    LEFT JOIN dayparts AS p
        ON u.most_ads_hour BETWEEN p.min_hour AND p.max_hour

    UNION ALL

    SELECT
        4,
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

-- Dimension totals: every user is in exactly one segment per dimension, so
-- "rest" = dimension total minus the segment
segment_vs_rest_counts AS (
    SELECT
        *,
        SUM(users_ad)        OVER dim - users_ad        AS rest_users_ad,
        SUM(users_psa)       OVER dim - users_psa       AS rest_users_psa,
        SUM(conversions_ad)  OVER dim - conversions_ad  AS rest_conversions_ad,
        SUM(conversions_psa) OVER dim - conversions_psa AS rest_conversions_psa,
        users_ad::DOUBLE  / SUM(users_ad)  OVER dim     AS share_of_arm_ad,
        users_psa::DOUBLE / SUM(users_psa) OVER dim     AS share_of_arm_psa
    FROM segment_counts
    WINDOW dim AS (PARTITION BY dimension)
),

segment_rates AS (
    SELECT
        *,
        conversions_ad::DOUBLE  / users_ad                                  AS conversion_rate_ad,
        conversions_psa::DOUBLE / users_psa                                 AS conversion_rate_psa,
        (conversions_ad + conversions_psa)::DOUBLE / (users_ad + users_psa) AS pooled_rate,
        rest_conversions_ad::DOUBLE  / rest_users_ad
          - rest_conversions_psa::DOUBLE / rest_users_psa                   AS lift_rest,
        -- Agresti-Caffo adjusted proportions: add 1 success and 1 failure to each group
        (conversions_ad + 1)::DOUBLE       / (users_ad + 2)                 AS ac_rate_ad,
        (conversions_psa + 1)::DOUBLE      / (users_psa + 2)                AS ac_rate_psa,
        (rest_conversions_ad + 1)::DOUBLE  / (rest_users_ad + 2)            AS ac_rate_rest_ad,
        (rest_conversions_psa + 1)::DOUBLE / (rest_users_psa + 2)           AS ac_rate_rest_psa
    FROM segment_vs_rest_counts
),

segment_stats AS (
    SELECT
        *,
        conversion_rate_ad - conversion_rate_psa                AS abs_lift,
        conversion_rate_ad / NULLIF(conversion_rate_psa, 0) - 1 AS rel_lift,
        (conversion_rate_ad - conversion_rate_psa)
            / SQRT(pooled_rate * (1 - pooled_rate) * (1.0 / users_ad + 1.0 / users_psa)) AS z_stat,
        conversion_rate_ad - conversion_rate_psa - lift_rest                             AS diff_vs_rest,
        (ac_rate_ad - ac_rate_psa) - (ac_rate_rest_ad - ac_rate_rest_psa)                AS diff_vs_rest_ac,
        SQRT(ac_rate_ad       * (1 - ac_rate_ad)       / (users_ad + 2)
           + ac_rate_psa      * (1 - ac_rate_psa)      / (users_psa + 2)
           + ac_rate_rest_ad  * (1 - ac_rate_rest_ad)  / (rest_users_ad + 2)
           + ac_rate_rest_psa * (1 - ac_rate_rest_psa) / (rest_users_psa + 2))           AS se_vs_rest,
        -- Mantel-Haenszel weight of the segment (for standardized_lift)
        users_ad::DOUBLE * users_psa / (users_ad + users_psa)                            AS mh_weight
    FROM segment_rates
)

SELECT
    s.dimension,
    s.segment,
    s.users_ad,
    s.users_psa,
    s.share_of_arm_ad,
    s.share_of_arm_psa,
    s.conversions_ad,
    s.conversions_psa,
    s.conversion_rate_ad,
    s.conversion_rate_psa,
    s.abs_lift,
    s.rel_lift,
    s.z_stat,
    ABS(s.z_stat) > p.z_crit_95                          AS lift_significant_unadjusted,
    s.abs_lift * s.users_ad                              AS incremental_conversions,
    s.lift_rest,
    s.diff_vs_rest,
    s.diff_vs_rest_ac,
    s.diff_vs_rest_ac - p.z_crit_95 * s.se_vs_rest       AS diff_vs_rest_ci95_low,
    s.diff_vs_rest_ac + p.z_crit_95 * s.se_vs_rest       AS diff_vs_rest_ci95_high,
    s.diff_vs_rest_ac / s.se_vs_rest                     AS z_vs_rest,
    ABS(s.diff_vs_rest_ac / s.se_vs_rest) > p.z_crit_95  AS differs_from_rest_unadjusted,
    SUM(s.mh_weight * s.abs_lift) OVER (PARTITION BY s.dimension)
        / SUM(s.mh_weight) OVER (PARTITION BY s.dimension) AS standardized_lift
FROM segment_stats AS s
CROSS JOIN params AS p
ORDER BY s.dimension_order, s.segment_order;
