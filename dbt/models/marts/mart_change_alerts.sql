-- HimalWatch — Change Alerts Mart
--
-- Lakes with anomalous area change that warrant attention.
-- Strict criteria to minimise false alerts from seasonal variation.
--
-- A lake is here when it is GROWING — see the rule in mart_lake_inventory:
-- >= 5 seasons, consistent upward trend (Spearman rho >= 0.9), recent
-- seasons >= 10% and >= 1 ha above the earliest seasons.
--
-- Severity by growth (recent vs early): LOW 10–25%, MEDIUM 25–50%, HIGH > 50%.

{{
  config(materialized='table')
}}

select
    lake_id,
    name,
    name_hint,
    tile,
    centroid_lat,
    centroid_lon,
    mean_elevation,
    geometry_wkt,

    -- Area
    first_area_sqm,
    latest_area_sqm,
    area_change_sqm,
    area_change_pct,
    baseline_area_sqm,
    recent_area_sqm,
    trend_rho,
    growth_pct,

    -- Volume
    latest_volume_mcm,
    volume_change_mcm,

    -- Temporal
    first_detected_date,
    latest_detection_date,
    latest_detection_year,
    detection_count,

    -- Severity
    alert_severity,

    -- Days since last confirmed observation
    datediff('day', latest_detection_date, current_date) as days_since_observation,

    mart_updated_at

from {{ ref('mart_lake_inventory') }}

where
    -- Must have alert severity set (covers all three tiers)
    alert_severity is not null

order by
    -- Most severe and largest change first
    case alert_severity
        when 'HIGH'   then 1
        when 'MEDIUM' then 2
        when 'LOW'    then 3
    end,
    growth_pct desc
