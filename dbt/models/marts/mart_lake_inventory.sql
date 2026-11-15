-- HimalWatch — Lake Inventory Mart
--
-- Latest known state of every unique lake across all tiles and years.
-- One row per lake_id. Includes area trend, volume estimate, and growth alert.
--
-- Growth alert rule (all must hold). Tuned on the 2019–2026 backfill so that
-- steady growers (Imja Tsho, Lower Barun) are flagged and lakes whose area
-- merely jumps around between years (cloud, ice, wet ground) are not:
--   0. Inside Nepal or within ~5 km of its border (in_nepal, from link_lakes.py)
--   1. Observed in >= 5 seasons
--   2. Observed in one of the two newest seasons processed for its tile
--   3. Consistent upward trend: Spearman rank correlation of area vs year >= 0.9
--   4. Recent area >= 10% above early area, where
--        early  = median of the first k seasons, recent = median of the last k,
--        k = min(3, seasons / 2)
--   5. Absolute gain (recent - early) >= 1 ha
-- Severity by growth (recent vs early): LOW 10-25%, MEDIUM 25-50%, HIGH > 50%.

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
        row_number() over (partition by lake_id order by detection_year asc)  as rn_asc,
        rank()       over (partition by lake_id order by area_sqm)            as area_rank,
        count(*)     over (partition by lake_id)                              as n
    from detections
),

stats as (
    select
        lake_id,
        min(detection_date)  as first_detected_date,
        max(detection_date)  as latest_detection_date,
        max(detection_year)  as latest_detection_year,
        count(*)             as detection_count,
        -- Spearman rho: correlation of ranks (years are distinct, so rn_asc is the year rank)
        corr(area_rank, rn_asc)                                             as trend_rho,
        median(area_sqm) filter (where rn_asc  <= least(3, n // 2))         as baseline_area_sqm,
        median(area_sqm) filter (where rn_desc <= least(3, n // 2))         as recent_area_sqm
    from ranked
    group by lake_id
),

latest as (
    select * from ranked where rn_desc = 1
),

earliest as (
    select lake_id, area_sqm as first_area_sqm, volume_m3 as first_volume_m3
    from ranked where rn_asc = 1
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
        l.in_nepal,
        l.name,
        l.name_hint,

        l.area_sqm   as latest_area_sqm,
        l.area_ha    as latest_area_ha,
        e.first_area_sqm,
        l.area_sqm - e.first_area_sqm                                        as area_change_sqm,
        round((l.area_sqm - e.first_area_sqm) / e.first_area_sqm * 100, 2)   as area_change_pct,

        s.baseline_area_sqm,
        s.recent_area_sqm,
        round((s.recent_area_sqm - s.baseline_area_sqm) / s.baseline_area_sqm * 100, 2) as growth_pct,
        round(s.trend_rho, 3)                                                as trend_rho,

        l.volume_m3  as latest_volume_m3,
        l.volume_mcm as latest_volume_mcm,
        e.first_volume_m3,
        round(l.volume_mcm - (e.first_volume_m3 / 1e6), 4)                   as volume_change_mcm,

        l.mean_ndwi  as latest_ndwi,
        l.mean_ndsi  as latest_ndsi,

        s.first_detected_date,
        s.latest_detection_date,
        s.latest_detection_year,
        s.detection_count,

        coalesce(
            l.in_nepal
            and s.detection_count >= 5
            and s.latest_detection_year >= t.tile_latest_year - 1
            and s.trend_rho >= 0.9
            and s.recent_area_sqm >= 1.10 * s.baseline_area_sqm
            and s.recent_area_sqm - s.baseline_area_sqm >= 10000,
            false
        ) as is_growing
    from latest l
    join earliest e    using (lake_id)
    join stats    s    using (lake_id)
    join tile_latest t on t.tile = l.tile
)

select
    * exclude (is_growing),
    case
        when is_growing and growth_pct > 50 then 'HIGH'
        when is_growing and growth_pct > 25 then 'MEDIUM'
        when is_growing                     then 'LOW'
        else null
    end               as alert_severity,
    current_timestamp as mart_updated_at
from joined
