-- HimalWatch — Change Alerts Mart
--
-- Lakes with anomalous area change that warrant attention.
-- Strict criteria to minimise false alerts from seasonal variation.
--
-- A lake is here when it is GROWING — see the rule in mart_lake_inventory:
-- seen in >= 3 seasons, seen in the newest season, latest area is a new
-- record (>= 5% above every earlier season), >= 15% and >= 1 ha above the
-- median of earlier seasons.
--
-- Severity by growth over that baseline:
--   LOW:    15–30%
--   MEDIUM: 30–50%
--   HIGH:   >50%

{{
  config(materialized='table')
}}

select
    lake_id,
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
    prior_max_area_sqm,
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
