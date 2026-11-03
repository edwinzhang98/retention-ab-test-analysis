-- =============================================================================
-- sql/02_conversion_by_group.sql
--
-- Purpose : Primary readout of the ad experiment. Users, conversions and
--           conversion rate per arm; absolute and relative lift (ad vs PSA);
--           pooled two-proportion z statistic; 95% Wald CI for the difference;
--           the exposure-parity check; and the business translation
--           (incremental conversions, what last-touch attribution would claim,
--           breakeven CPM at an assumed value, cost of an always-on holdout).
-- Input   : data/raw/marketing_AB.csv - one row per user (rules as in
--           01_stg_marketing_ab.sql).
-- Output  : 1 row - grain: the experiment (ad = treatment, psa = control).
--             users_ad, users_psa                   users per arm
--             conversions_ad, conversions_psa       converted users per arm
--             conversion_rate_ad, _psa              conversions / users (proportion)
--             abs_lift                              rate_ad - rate_psa (proportion; x100 = pp)
--             rel_lift                              rate_ad / rate_psa - 1
--             z_stat                                pooled two-proportion z statistic
--             abs_lift_ci95_low, _high              95% Wald (unpooled) CI for abs_lift
--             significant_at_5pct                   |z_stat| > 1.96
--             avg_ads_per_user_ad, _psa             exposure parity: ads (or PSAs) per user
--             impressions_ad                        total ads shown to the ad arm
--             incremental_conversions               abs_lift * users_ad
--             incremental_share_of_ad_conversions   incremental_conversions / conversions_ad
--                                                   (= 1 - 1 / relative risk): the share of the
--                                                   ad arm's conversions the ads actually caused
--             last_touch_overstatement_x            conversions_ad / incremental_conversions: how many
--                                                   times last-touch attribution (every ad-arm
--                                                   conversion credited to the ad) overstates the campaign
--             breakeven_cpm_usd                     cost per 1,000 impressions at which the
--                                                   incremental value just covers media cost
--             holdout_users                         users a proposed always-on PSA holdout would
--                                                   take from a flight of this size (holdout_share)
--             holdout_conversions_forgone           holdout_users * abs_lift: the holdout's cost
--             holdout_value_forgone_usd             the same at the assumed value per conversion
-- Run     : from the repo root, one of
--             python -m src.sql_check sql/02_conversion_by_group.sql   (print this result)
--             python -m src.sql_check                                  (run every file + reconcile)
--             duckdb -c ".read sql/02_conversion_by_group.sql"         (DuckDB CLI)
-- Notes   : - Conversion is user-level and binary (a user counts once), so the
--             denominator is users, not impressions.
--           - The headline interval in the report is the Newcombe CI. It, the
--             bootstrap CI and the p-value come from src/stats.py (DuckDB has no
--             normal CDF); at this sample size the Wald CI computed here is close to it.
--             Reports print a p-value this small as "p < 0.0001", never as 0.
--           - Read 03_srm_check.sql with this file: the 96/4 split passes the SRM
--             test by construction, so exposure parity (avg_ads_per_user_*, and the
--             bucket shares in 04_lift_by_day_and_hour.sql) is the meaningful check.
--           - value_per_conversion_usd = 50 is an ILLUSTRATIVE assumption
--             (config.yaml); the data has no revenue or cost fields. Treat
--             breakeven_cpm_usd as "what CPM could we afford IF a conversion is
--             worth USD 50", to be checked against the CPM Finance actually pays.
--           - holdout_share = 0.05 is the proposed always-on holdout (config.yaml).
--             Its cost assumes the measured average lift also holds for the users
--             held out.
-- =============================================================================

WITH params AS (
    SELECT
        1.959963984540054::DOUBLE AS z_crit_95,                 -- standard normal 97.5th percentile (two-sided alpha = 0.05)
        50::DOUBLE                AS value_per_conversion_usd,  -- ILLUSTRATIVE assumption, see Notes
        0.05::DOUBLE              AS holdout_share              -- proposed always-on PSA holdout, see Notes
),

-- Same rules as 01_stg_marketing_ab.sql (repeated so this file runs on its own)
stg_marketing_ab AS (
    SELECT
        CAST("test group" AS VARCHAR) AS test_group,
        CAST(converted    AS BOOLEAN) AS converted,
        CAST("total ads"  AS INTEGER) AS total_ads
    FROM read_csv('data/raw/marketing_AB.csv', header = true)
),

arm_totals AS (
    SELECT
        test_group,
        COUNT(*)                          AS users,
        COUNT(*) FILTER (WHERE converted) AS conversions,   -- same as SUM(CASE WHEN converted THEN 1 ELSE 0 END)
        CAST(SUM(total_ads) AS BIGINT)    AS impressions
    FROM stg_marketing_ab
    GROUP BY test_group
),

-- Treatment and control side by side in one row
ad_vs_psa AS (
    SELECT
        ad.users                            AS users_ad,
        psa.users                           AS users_psa,
        ad.conversions                      AS conversions_ad,
        psa.conversions                     AS conversions_psa,
        ad.impressions                      AS impressions_ad,
        psa.impressions                     AS impressions_psa,
        -- cast before dividing: INT / INT truncates to 0 in Postgres / Redshift
        ad.conversions::DOUBLE  / ad.users  AS conversion_rate_ad,
        psa.conversions::DOUBLE / psa.users AS conversion_rate_psa
    FROM arm_totals AS ad
    CROSS JOIN arm_totals AS psa
    WHERE ad.test_group = 'ad'
      AND psa.test_group = 'psa'
),

lift AS (
    SELECT
        *,
        conversion_rate_ad - conversion_rate_psa                             AS abs_lift,
        conversion_rate_ad / conversion_rate_psa - 1                         AS rel_lift,
        -- common rate if the ad had no effect (H0); used for the z test
        (conversions_ad + conversions_psa)::DOUBLE / (users_ad + users_psa) AS pooled_rate
    FROM ad_vs_psa
),

standard_errors AS (
    SELECT
        *,
        -- SE assuming H0 (pooled rate) -> z statistic
        SQRT(pooled_rate * (1 - pooled_rate) * (1.0 / users_ad + 1.0 / users_psa)) AS se_pooled,
        -- SE without assuming H0 (each arm keeps its own rate) -> confidence interval
        SQRT(conversion_rate_ad  * (1 - conversion_rate_ad)  / users_ad
           + conversion_rate_psa * (1 - conversion_rate_psa) / users_psa)          AS se_unpooled
    FROM lift
)

SELECT
    s.users_ad,
    s.users_psa,
    s.conversions_ad,
    s.conversions_psa,
    s.conversion_rate_ad,
    s.conversion_rate_psa,
    s.abs_lift,
    s.rel_lift,
    s.abs_lift / s.se_pooled                     AS z_stat,
    s.abs_lift - p.z_crit_95 * s.se_unpooled     AS abs_lift_ci95_low,
    s.abs_lift + p.z_crit_95 * s.se_unpooled     AS abs_lift_ci95_high,
    ABS(s.abs_lift / s.se_pooled) > p.z_crit_95  AS significant_at_5pct,
    s.impressions_ad::DOUBLE  / s.users_ad       AS avg_ads_per_user_ad,
    s.impressions_psa::DOUBLE / s.users_psa      AS avg_ads_per_user_psa,
    s.impressions_ad,
    s.abs_lift * s.users_ad                      AS incremental_conversions,
    s.abs_lift * s.users_ad / s.conversions_ad   AS incremental_share_of_ad_conversions,
    s.conversions_ad / (s.abs_lift * s.users_ad) AS last_touch_overstatement_x,
    s.abs_lift * s.users_ad * p.value_per_conversion_usd
        / s.impressions_ad * 1000                AS breakeven_cpm_usd,
    (s.users_ad + s.users_psa) * p.holdout_share AS holdout_users,
    (s.users_ad + s.users_psa) * p.holdout_share
        * s.abs_lift                             AS holdout_conversions_forgone,
    (s.users_ad + s.users_psa) * p.holdout_share
        * s.abs_lift * p.value_per_conversion_usd AS holdout_value_forgone_usd
FROM standard_errors AS s
CROSS JOIN params AS p;
