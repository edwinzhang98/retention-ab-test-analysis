-- =============================================================================
-- sql/06_retention_by_segment.sql
--
-- Purpose : D1 and D7 retention of new players, overall and by segment:
--           engagement depth (rounds bucket), whether the player came back on
--           Day 1, and experiment version. Answers "which new players leave first?"
-- Input   : data/raw/cookie_cats.csv - one row per player (rules as in
--           05_stg_cookie_cats.sql, i.e. the one outlier excluded).
-- Output  : 1 row per (dimension, segment) - grain: segment.
--             dimension          'overall' | 'rounds_bucket' | 'd1_status' | 'version'
--             segment            segment label ('All players' for overall)
--             players            players (installs) in the segment
--             share_of_players   players / all players in the analysis population
--             d1_retained        players with retention_1 = TRUE
--             d1_retention_rate  d1_retained / players
--             d7_retained        players with retention_7 = TRUE
--             d7_retention_rate  d7_retained / players
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/06_retention_by_segment.sql   (print this result)
--             python -m src.sql_check                                   (run every file + reconcile)
--             duckdb -c ".read sql/06_retention_by_segment.sql"         (DuckDB CLI)
-- Notes   : - DN retention = share of ALL installs in the segment who came back and
--             played on day N after install (denominator = installs, not survivors).
--           - D7 is not conditional on D1: some players skip day 1 and return on
--             day 7. Within d1_status, d7_retention_rate compares D7 for Day-1
--             returners vs non-returners. The install -> Day 1 -> Day 1 and Day 7
--             funnel can be read off the 'overall' and 'd1_status' rows.
--           - rounds_bucket uses rounds over 14 days, which overlap the D7 window:
--             rounds vs retention is a correlation, not a cause.
--           - Wilson CIs for these rates are computed in src/retention.py.
-- =============================================================================

WITH stg_cookie_cats AS (
    -- Same rules as 05_stg_cookie_cats.sql (repeated so this file runs on its own)
    SELECT
        CAST(version        AS VARCHAR) AS version,
        CAST(sum_gamerounds AS INTEGER) AS sum_gamerounds,
        CAST(retention_1    AS BOOLEAN) AS retention_1,
        CAST(retention_7    AS BOOLEAN) AS retention_7
    FROM read_csv('data/raw/cookie_cats.csv', header = true)
    WHERE sum_gamerounds <= 10000
),

rounds_buckets (rounds_bucket, bucket_order, min_rounds, max_rounds) AS (
    VALUES
        ('0',     1,   0,          0),
        ('1-4',   2,   1,          4),
        ('5-14',  3,   5,         14),
        ('15-29', 4,  15,         29),
        ('30-39', 5,  30,         39),
        ('40-99', 6,  40,         99),
        ('100+',  7, 100, 1000000000)
),

-- Long format: every player appears once per dimension, so one GROUP BY serves every cut
player_segments AS (
    SELECT
        1             AS dimension_order,
        'overall'     AS dimension,
        'All players' AS segment,
        1             AS segment_order,
        retention_1,
        retention_7
    FROM stg_cookie_cats

    UNION ALL

    SELECT
        2,
        'rounds_bucket',
        b.rounds_bucket,
        b.bucket_order,
        p.retention_1,
        p.retention_7
    FROM stg_cookie_cats AS p
    LEFT JOIN rounds_buckets AS b
        ON p.sum_gamerounds BETWEEN b.min_rounds AND b.max_rounds

    UNION ALL

    SELECT
        3,
        'd1_status',
        CASE WHEN retention_1 THEN 'Returned Day 1' ELSE 'Did not return Day 1' END,
        CASE WHEN retention_1 THEN 2 ELSE 1 END,
        retention_1,
        retention_7
    FROM stg_cookie_cats

    UNION ALL

    SELECT
        4,
        'version',
        version,
        CASE version WHEN 'gate_30' THEN 1 ELSE 2 END,
        retention_1,
        retention_7
    FROM stg_cookie_cats
),

segment_counts AS (
    SELECT
        dimension_order,
        dimension,
        segment_order,
        segment,
        COUNT(*)                            AS players,
        COUNT(*) FILTER (WHERE retention_1) AS d1_retained,
        COUNT(*) FILTER (WHERE retention_7) AS d7_retained
    FROM player_segments
    GROUP BY dimension_order, dimension, segment_order, segment
)

SELECT
    dimension,
    segment,
    players,
    players::DOUBLE / SUM(players) OVER (PARTITION BY dimension) AS share_of_players,
    d1_retained,
    d1_retained::DOUBLE / players                                AS d1_retention_rate,
    d7_retained,
    d7_retained::DOUBLE / players                                AS d7_retention_rate
FROM segment_counts
ORDER BY dimension_order, segment_order;
