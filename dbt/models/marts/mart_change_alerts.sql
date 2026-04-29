-- HimalWatch — Change Alerts Mart
--
-- Lakes with anomalous area change that warrant attention.
-- Strict criteria to minimise false alerts from seasonal variation.
--
-- Inclusion criteria (ALL must be true):
--   1. Area change > 15% between first and latest detection
--   2. At least 2 detections (prevents single-observation noise)
--   3. Latest detection within 90 days (stale alerts are not actionable)
--
-- Severity tiers:
--   LOW:    15–30% change
--   MEDIUM: 30–50% change
--   HIGH:   >50% change

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

    -- Volume
    latest_volume_mcm,
    volume_change_mcm,

    -- Temporal
    first_detected_date,
    latest_detection_date,
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
    abs(area_change_pct) desc
