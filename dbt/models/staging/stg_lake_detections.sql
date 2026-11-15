-- HimalWatch staging model
-- Reads the linked detections written by pipeline/link_lakes.py: one row per
-- (lake_id, detection_year), with lake_id stable across years.
-- (The raw per-run files carry a fresh random id each run, so they cannot be
-- used for trends directly.)

{{
  config(materialized='view')
}}

select
    lake_id,
    tile,
    geometry_wkt,

    cast(area_sqm       as double) as area_sqm,
    cast(area_ha        as double) as area_ha,
    cast(centroid_lat   as double) as centroid_lat,
    cast(centroid_lon   as double) as centroid_lon,
    cast(mean_elevation as double) as mean_elevation,
    cast(mean_ndwi      as double) as mean_ndwi,
    cast(mean_ndsi      as double) as mean_ndsi,
    cast(volume_m3      as double) as volume_m3,
    cast(volume_mcm     as double) as volume_mcm,

    -- detection_date = last day of the compositing season
    cast(season_end as date)        as detection_date,
    cast(detection_year as integer) as detection_year,

    season_start,
    season_end,
    detected_at,

    -- false for lakes on the Tibetan side of the border (tracked, never alerted)
    cast(in_nepal as boolean) as in_nepal,
    -- 'Nepal' | 'India' | 'China', from the lake's newest centroid
    cast(country   as varchar) as country,

    -- OpenStreetMap name, or for unnamed lakes a hint like '3.2 km NE of Imja Tsho'
    cast(name      as varchar) as name,
    cast(name_hint as varchar) as name_hint,

    -- ICIMOD/UNDP 2020 potentially dangerous glacial lake: id, rank (I/II/III), reason
    cast(icimod_id   as varchar) as icimod_id,
    cast(icimod_rank as varchar) as icimod_rank,
    cast(icimod_note as varchar) as icimod_note,

    -- set when an alert on this lake was checked by hand and rejected
    cast(review_note as varchar) as review_note,

    current_timestamp as loaded_at

from read_parquet(
    's3://{{ env_var("R2_BUCKET_NAME", "himalwatch-data") }}/linked/lake_detections.parquet'
)

where
    lake_id          is not null
    and geometry_wkt is not null
    and centroid_lat is not null
    and centroid_lon is not null
    and area_sqm >= 10000
