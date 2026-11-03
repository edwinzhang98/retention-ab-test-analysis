-- =============================================================================
-- sql/05_stg_cookie_cats.sql
--
-- Purpose : Staging model for the Cookie Cats players. Renames / casts the raw
--           columns, drops the single logging-error outlier (more than 10,000
--           rounds in 14 days) and adds the segment columns used in the
--           retention analysis.
-- Input   : data/raw/cookie_cats.csv - raw Kaggle export, one row per player
--           (symlink to the configured file, created by src.data.link_raw()).
-- Output  : stg_cookie_cats - grain: one row per player (user_id is unique).
--             user_id          BIGINT   player key
--             version          VARCHAR  'gate_30' (control) | 'gate_40' (treatment)
--             sum_gamerounds   INTEGER  rounds played in the first 14 days after install
--             retention_1      BOOLEAN  came back on day 1 after install (D1)
--             retention_7      BOOLEAN  came back on day 7 after install (D7)
--             rounds_bucket    VARCHAR  0, 1-4, 5-14, 15-29, 30-39, 40-99, 100+
--             d1_status        VARCHAR  'Returned Day 1' | 'Did not return Day 1'
--             reached_gate_30  BOOLEAN  sum_gamerounds >= 30. A proxy only: rounds are
--                                       not levels. Below 30 rounds, level 30 was never
--                                       played; 30 or more does not prove it was.
--           Same columns and values as src.data.clean_cookie().
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/05_stg_cookie_cats.sql   (print this result)
--             python -m src.sql_check                              (run every file + reconcile)
--             duckdb -c ".read sql/05_stg_cookie_cats.sql"         (DuckDB CLI)
-- Notes   : - This is the ANALYSIS population (one outlier excluded). The SRM check
--             (03_srm_check.sql, 09_gate_integrity.sql) counts every assigned player.
--           - The exclusion threshold mirrors gamerounds_outlier_max in config.yaml;
--             08_data_quality_checks.sql shows the count and that excluding it
--             leaves retention unchanged.
--           - D1 / D7 are classic day-N retention (came back on exactly day N after
--             install), not rolling. The file has no install dates, so all players
--             form a single install cohort. A few zero-round players are flagged as
--             retained, so read the flags as "came back to the game" (counts in 08).
--           - Rounds buckets are upper-inclusive, placed around the two gate
--             positions (level 30 / 40), and mirror ROUNDS_BINS in src/config.py.
--           - sum_gamerounds covers the first 14 days, which include day 7, so
--             rounds vs retention is partly definitional (a player who comes back
--             plays more rounds). It sizes the early-churn segment; it is not a
--             Day-0 targeting rule.
-- =============================================================================

WITH source AS (
    SELECT *
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
),

renamed AS (
    SELECT
        CAST(userid         AS BIGINT)  AS user_id,
        CAST(version        AS VARCHAR) AS version,
        CAST(sum_gamerounds AS INTEGER) AS sum_gamerounds,
        CAST(retention_1    AS BOOLEAN) AS retention_1,
        CAST(retention_7    AS BOOLEAN) AS retention_7
    FROM source
),

-- Rounds bands as a small lookup table (inclusive bounds on whole round counts)
rounds_buckets (rounds_bucket, min_rounds, max_rounds) AS (
    VALUES
        ('0',       0,          0),
        ('1-4',     1,          4),
        ('5-14',    5,         14),
        ('15-29',  15,         29),
        ('30-39',  30,         39),
        ('40-99',  40,         99),
        ('100+',  100, 1000000000)
),

stg_cookie_cats AS (
    SELECT
        r.user_id,
        r.version,
        r.sum_gamerounds,
        r.retention_1,
        r.retention_7,
        b.rounds_bucket,
        CASE WHEN r.retention_1 THEN 'Returned Day 1' ELSE 'Did not return Day 1' END AS d1_status,
        r.sum_gamerounds >= 30                                                        AS reached_gate_30
    FROM renamed AS r
    LEFT JOIN rounds_buckets AS b
        ON r.sum_gamerounds BETWEEN b.min_rounds AND b.max_rounds
    WHERE r.sum_gamerounds <= 10000       -- drop the logging-error outlier (see Notes)
)

SELECT *
FROM stg_cookie_cats
ORDER BY user_id;
