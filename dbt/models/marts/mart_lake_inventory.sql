-- HimalWatch — Lake Inventory Mart
--
-- Latest known state of every unique lake across all tiles and years.
-- One row per lake_id. Includes area trend, volume estimate, and alert flag.
-- Materialised as TABLE and refreshed on every pipeline run.

{{
  config(materialized='table')
}}

with detections as (
    select * from {{ ref('stg_lake_detections') }}
),

-- First and latest detection per lake
bounds as (
    select
        lake_id,
        min(detection_date)  as first_detected_date,
        max(detection_date)  as latest_detection_date,
        count(*)             as detection_count
    from detections
    group by lake_id
),

-- Latest detection row (area, geometry, ndwi at most recent observation)
latest as (
    select distinct on (d.lake_id)
        d.lake_id,
        d.tile,
        d.geometry_wkt,
        d.centroid_lat,
        d.centroid_lon,
        d.mean_elevation,
        d.mean_ndwi         as latest_ndwi,
        d.mean_ndsi         as latest_ndsi,
        d.area_sqm          as latest_area_sqm,
        d.area_ha           as latest_area_ha,
        d.volume_m3         as latest_volume_m3,
        d.volume_mcm        as latest_volume_mcm,
        d.detection_date    as latest_detection_date
    from detections d
    order by d.lake_id, d.detection_date desc
),

-- Earliest detection row (for area change baseline)
earliest as (
    select distinct on (d.lake_id)
        d.lake_id,
        d.area_sqm  as first_area_sqm,
        d.volume_m3 as first_volume_m3
    from detections d
    order by d.lake_id, d.detection_date asc
)

select
    l.lake_id,
    l.tile,
    l.centroid_lat,
    l.centroid_lon,
    l.mean_elevation,
    l.geometry_wkt,

    -- Area
    l.latest_area_sqm,
    l.latest_area_ha,
    e.first_area_sqm,
    l.latest_area_sqm - e.first_area_sqm                          as area_change_sqm,
    round(
        (l.latest_area_sqm - e.first_area_sqm) / e.first_area_sqm * 100,
        2
    )                                                              as area_change_pct,

    -- Volume (Cook & Quincey 2015)
    l.latest_volume_m3,
    l.latest_volume_mcm,
    e.first_volume_m3,
    round(l.latest_volume_mcm - (e.first_volume_m3 / 1e6), 4)    as volume_change_mcm,

    -- Spectral
    l.latest_ndwi,
    l.latest_ndsi,

    -- Temporal
    b.first_detected_date,
    b.latest_detection_date,
    b.detection_count,

    -- Alert flag (convenience for dashboard — full logic in mart_change_alerts)
    case
        when b.detection_count >= 2
             and abs((l.latest_area_sqm - e.first_area_sqm) / e.first_area_sqm * 100) > 50
             and b.latest_detection_date >= current_date - interval '90 days'
        then 'HIGH'
        when b.detection_count >= 2
             and abs((l.latest_area_sqm - e.first_area_sqm) / e.first_area_sqm * 100) > 30
             and b.latest_detection_date >= current_date - interval '90 days'
        then 'MEDIUM'
        when b.detection_count >= 2
             and abs((l.latest_area_sqm - e.first_area_sqm) / e.first_area_sqm * 100) > 15
             and b.latest_detection_date >= current_date - interval '90 days'
        then 'LOW'
        else null
    end                                                            as alert_severity,

    current_timestamp                                              as mart_updated_at

from latest l
join earliest e using (lake_id)
join bounds  b using (lake_id)
