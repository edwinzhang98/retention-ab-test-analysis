-- =============================================================================
-- sql/01_stg_marketing_ab.sql
--
-- Purpose : Staging model for the ad-vs-PSA experiment. Renames the raw columns
--           to snake_case, casts them to explicit types, drops the unnamed CSV
--           row-index column and adds the exposure bucket used for the
--           dose-response cut. No rows are filtered.
-- Input   : data/raw/marketing_AB.csv - raw Kaggle export, one row per user
--           (symlink to the configured file, created by src.data.link_raw()).
-- Output  : stg_marketing_ab - grain: one row per user (user_id is unique).
--             user_id          BIGINT   user key
--             test_group       VARCHAR  'ad' (treatment) | 'psa' (control: a public
--                                       service announcement shown in the same slots)
--             converted        BOOLEAN  user converted
--             total_ads        INTEGER  ads (or PSAs) the user was shown
--             exposure_bucket  VARCHAR  total_ads band, upper-inclusive: 1-5, 6-10,
--                                       11-20, 21-35, 36-50, 51-100, 101-200,
--                                       200+ (= more than 200)
--             most_ads_day     VARCHAR  weekday on which the user saw the most ads
--             most_ads_hour    INTEGER  hour of day (0-23) in which the user saw the most ads
--           Same columns and values as src.data.clean_marketing().
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/01_stg_marketing_ab.sql   (print this result)
--             python -m src.sql_check                               (run every file + reconcile)
--             duckdb -c ".read sql/01_stg_marketing_ab.sql"         (DuckDB CLI)
-- Notes   : - total_ads, most_ads_day and most_ads_hour are recorded AFTER
--             assignment (they describe what the user was shown), so downstream
--             they are only used for exploratory cuts, never as covariates.
--           - Bucket edges mirror EXPOSURE_BINS / EXPOSURE_LABELS in src/config.py.
-- =============================================================================

WITH source AS (
    SELECT *
    FROM read_csv('data/raw/marketing_AB.csv', header = true)
),

renamed AS (
    SELECT
        CAST("user id"       AS BIGINT)  AS user_id,
        CAST("test group"    AS VARCHAR) AS test_group,
        CAST(converted       AS BOOLEAN) AS converted,
        CAST("total ads"     AS INTEGER) AS total_ads,
        CAST("most ads day"  AS VARCHAR) AS most_ads_day,
        CAST("most ads hour" AS INTEGER) AS most_ads_hour
    FROM source
),

-- Exposure bands as a small lookup table (inclusive bounds on whole ad counts)
exposure_buckets (exposure_bucket, min_ads, max_ads) AS (
    VALUES
        ('1-5',       1,          5),
        ('6-10',      6,         10),
        ('11-20',    11,         20),
        ('21-35',    21,         35),
        ('36-50',    36,         50),
        ('51-100',   51,        100),
        ('101-200', 101,        200),
        ('200+',    201, 1000000000)
),

stg_marketing_ab AS (
    SELECT
        r.user_id,
        r.test_group,
        r.converted,
        r.total_ads,
        b.exposure_bucket,
        r.most_ads_day,
        r.most_ads_hour
    FROM renamed AS r
    LEFT JOIN exposure_buckets AS b       -- LEFT JOIN: an out-of-range value shows up as NULL instead of disappearing
        ON r.total_ads BETWEEN b.min_ads AND b.max_ads
)

SELECT *
FROM stg_marketing_ab
ORDER BY user_id;
