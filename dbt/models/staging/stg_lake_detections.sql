-- HimalWatch staging model
-- Reads all raw Parquet files from R2 across all tiles and years.
-- Casts types, derives detection_date, filters junk rows.
-- Materialised as VIEW so dbt always reads the latest R2 data.

{{
  config(materialized='view')
}}

select
    lake_id,
    tile,
    geometry_wkt,

    -- Cast numeric columns explicitly (Parquet may read as object on some versions)
    cast(area_sqm       as double) as area_sqm,
    cast(area_ha        as double) as area_ha,
    cast(centroid_lat   as double) as centroid_lat,
    cast(centroid_lon   as double) as centroid_lon,
    cast(mean_elevation as double) as mean_elevation,
    cast(mean_ndwi      as double) as mean_ndwi,
    cast(mean_ndsi      as double) as mean_ndsi,
    cast(volume_m3      as double) as volume_m3,
    cast(volume_mcm     as double) as volume_mcm,

    -- detection_date = first day of the compositing season
    cast(season_start as date) as detection_date,
    cast(detection_year as integer) as detection_year,

    season_start,
    season_end,
    detected_at,

    -- Record when dbt loaded this row
    current_timestamp as loaded_at

from read_parquet(
    's3://{{ env_var("R2_BUCKET_NAME", "himalwatch-data") }}/raw/lakes/*/*/lakes.parquet',
    hive_partitioning = false,
    union_by_name = true
)

where
    -- Remove rows with missing critical fields
    lake_id        is not null
    and geometry_wkt  is not null
    and centroid_lat  is not null
    and centroid_lon  is not null
    -- Enforce minimum area (belt-and-suspenders — pipeline already filters)
    and area_sqm >= 10000
