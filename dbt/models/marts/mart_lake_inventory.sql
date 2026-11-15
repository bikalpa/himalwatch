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
--
-- Sudden-change rule (severity 'SUDDEN', any country). Catches what the
-- growth rule cannot: a lake that changes in one step — a new reservoir, a
-- landslide dam, a rapid expansion — e.g. the Mabja Zangbo dam on the upper
-- Karnali, 9 ha in 2023 and 88 ha in 2024. All must hold:
--   1. There is a season with >= 2 seasons before it and >= 2 from it onward
--   2. Every season from it onward is >= 3x the largest season before it
--   3. ... and at least 5 ha larger
--   4. Observed in one of the two newest seasons processed for its tile
-- Needing two seasons after the jump costs a year, but drops the one-season
-- spikes that cloud, snow and lake ice produce.
--
-- A lake listed in pipeline/utils/alert_review.json (review_note) was checked
-- by hand and raises neither kind of alert.
--
-- alert_reason says in words why a lake is or is not flagged.

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

jump_candidates as (
    select
        lake_id,
        detection_year,
        max(area_sqm) over (partition by lake_id order by detection_year
                            rows between unbounded preceding and 1 preceding) as before_max_sqm,
        min(area_sqm) over (partition by lake_id order by detection_year
                            rows between current row and unbounded following) as after_min_sqm,
        rn_asc - 1     as n_before,
        n - rn_asc + 1 as n_after
    from ranked
),

jumps as (
    -- earliest qualifying jump per lake
    select lake_id,
           detection_year as sudden_year,
           before_max_sqm as sudden_before_sqm,
           after_min_sqm  as sudden_after_sqm
    from jump_candidates
    where n_before >= 2 and n_after >= 2
      and after_min_sqm >= 3 * before_max_sqm
      and after_min_sqm - before_max_sqm >= 50000
    qualify row_number() over (partition by lake_id order by detection_year) = 1
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
        l.country,
        l.name,
        l.name_hint,
        l.icimod_id,
        l.icimod_rank,
        l.icimod_note,
        l.review_note,

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
        t.tile_latest_year,

        j.sudden_year,
        j.sudden_before_sqm,
        j.sudden_after_sqm,
        coalesce(j.sudden_year is not null
                 and l.review_note is null
                 and s.latest_detection_year >= t.tile_latest_year - 1, false) as is_sudden,

        coalesce(
            l.in_nepal
            and l.review_note is null
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
    left join jumps j  using (lake_id)
)

select
    * exclude (is_growing, is_sudden, tile_latest_year),
    case
        when is_growing and growth_pct > 50 then 'HIGH'
        when is_growing and growth_pct > 25 then 'MEDIUM'
        when is_growing                     then 'LOW'
        when is_sudden                      then 'SUDDEN'
        else null
    end               as alert_severity,
    case
        when is_growing then
            'Flagged: grew ' || cast(round(growth_pct) as integer) || '% steadily over '
            || detection_count || ' seasons.'
        when is_sudden then
            'Flagged as a sudden change: jumped from '
            || round(sudden_before_sqm / 1e4, 1) || ' ha to at least '
            || round(sudden_after_sqm / 1e4, 1) || ' ha in ' || sudden_year
            || ' and has stayed that size.'
        when review_note is not null then
            'Not flagged: checked by hand against the imagery — ' || review_note || '.'
        when latest_detection_year < tile_latest_year - 1 then
            'Not flagged: not detected in the last two seasons (last seen '
            || latest_detection_year || ').'
        when detection_count < 5 then
            'Not flagged: seen in only ' || detection_count
            || case when detection_count = 1 then ' season' else ' seasons' end
            || '; a growth alert needs 5.'
        when recent_area_sqm < 1.10 * baseline_area_sqm
             or recent_area_sqm - baseline_area_sqm < 10000 then
            'Not flagged: no meaningful growth (needs at least 10% and 1 ha).'
        when trend_rho is null or trend_rho < 0.9 then
            'Not flagged: its area goes up and down between years instead of rising steadily.'
        when not in_nepal then
            'Not flagged: growing steadily, but more than 5 km outside Nepal.'
        else 'Not flagged: its area does not rise steadily enough from year to year.'
    end               as alert_reason,
    current_timestamp as mart_updated_at
from joined
