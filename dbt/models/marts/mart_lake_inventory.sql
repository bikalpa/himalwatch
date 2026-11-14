-- HimalWatch — Lake Inventory Mart
--
-- Latest known state of every unique lake across all tiles and years.
-- One row per lake_id. Includes area trend, volume estimate, and growth alert.
--
-- Growth alert rule (all must hold) — tuned to ignore single bad years, which
-- are common (cloud, early snow, lake ice):
--   1. Lake observed in >= 3 seasons
--   2. Observed in the newest season processed for its tile
--   3. Latest area is a new record: >= 5% above every earlier season
--   4. Latest area >= 15% above the median of earlier seasons (the baseline)
--   5. Absolute gain over baseline >= 1 ha
-- Severity by growth over baseline: LOW 15-30%, MEDIUM 30-50%, HIGH > 50%.

{{
  config(materialized='table')
}}

with detections as (
    select * from {{ ref('stg_lake_detections') }}
),

ranked as (
    select
        *,
        row_number() over (partition by lake_id order by detection_year desc) as rn_desc,
        row_number() over (partition by lake_id order by detection_year asc)  as rn_asc
    from detections
),

bounds as (
    select
        lake_id,
        min(detection_date)  as first_detected_date,
        max(detection_date)  as latest_detection_date,
        max(detection_year)  as latest_detection_year,
        count(*)             as detection_count
    from detections
    group by lake_id
),

latest as (
    select * from ranked where rn_desc = 1
),

earliest as (
    select lake_id, area_sqm as first_area_sqm, volume_m3 as first_volume_m3
    from ranked where rn_asc = 1
),

-- Everything before the latest observation
earlier as (
    select
        lake_id,
        median(area_sqm) as baseline_area_sqm,
        max(area_sqm)    as prior_max_area_sqm
    from ranked
    where rn_desc > 1
    group by lake_id
),

tile_latest as (
    select tile, max(detection_year) as tile_latest_year
    from detections
    group by tile
),

joined as (
    select
        l.lake_id,
        l.tile,
        l.centroid_lat,
        l.centroid_lon,
        l.mean_elevation,
        l.geometry_wkt,

        l.area_sqm   as latest_area_sqm,
        l.area_ha    as latest_area_ha,
        e.first_area_sqm,
        l.area_sqm - e.first_area_sqm                                        as area_change_sqm,
        round((l.area_sqm - e.first_area_sqm) / e.first_area_sqm * 100, 2)   as area_change_pct,

        p.baseline_area_sqm,
        p.prior_max_area_sqm,
        round((l.area_sqm - p.baseline_area_sqm) / p.baseline_area_sqm * 100, 2) as growth_pct,

        l.volume_m3  as latest_volume_m3,
        l.volume_mcm as latest_volume_mcm,
        e.first_volume_m3,
        round(l.volume_mcm - (e.first_volume_m3 / 1e6), 4)                   as volume_change_mcm,

        l.mean_ndwi  as latest_ndwi,
        l.mean_ndsi  as latest_ndsi,

        b.first_detected_date,
        b.latest_detection_date,
        b.latest_detection_year,
        b.detection_count,

        (
            b.detection_count >= 3
            and b.latest_detection_year = t.tile_latest_year
            and l.area_sqm >= 1.05 * p.prior_max_area_sqm
            and l.area_sqm >= 1.15 * p.baseline_area_sqm
            and l.area_sqm - p.baseline_area_sqm >= 10000
        ) as is_growing
    from latest l
    join earliest e    using (lake_id)
    join bounds   b    using (lake_id)
    left join earlier p using (lake_id)
    join tile_latest t on t.tile = l.tile
)

select
    * exclude (is_growing),
    case
        when is_growing and growth_pct > 50 then 'HIGH'
        when is_growing and growth_pct > 30 then 'MEDIUM'
        when is_growing                     then 'LOW'
        else null
    end               as alert_severity,
    current_timestamp as mart_updated_at
from joined
