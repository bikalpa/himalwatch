# Pipeline & Data Status — as of 2026-04-29

## R2 Data Available
| Tile | Year | Status |
|---|---|---|
| khumbu | 2024 | ✅ Real GEE data in R2 (75 detections, 16.4 km² total) |
| langtang | 2024 | ⏳ Demo data only |
| annapurna | 2024 | ⏳ Demo data only |
| far_west | 2024 | ⏳ Demo data only (prior run hit GEE null geometry error) |
| karnali | 2024 | ⏳ Demo data only |
| kangchenjunga | 2024 | ⏳ Demo data only |

## Pipeline Runs Queued (as of 2026-04-29)
| Run ID | Description | Status |
|---|---|---|
| 25122499301 | 2024 all tiles | Queued |
| 25123331999 | 2023 khumbu (multi-year trend) | Queued |
| 25123333001 | 2022 khumbu (multi-year trend) | Queued |

Once these complete:
- All 6 tiles will have 2024 R2 data → proper named lake detection
- Khumbu will have 3 years of detections → `detection_count ≥ 2` → trend chart
  populates → area change % becomes real (not demo 0.0%)
- Alert HIGH count in header (currently 5) will change based on real data

## Known Pipeline Bugs Fixed (already in codebase)
1. **Null geometry after simplify** (`lake_detection.py`): `simplify(20m)` collapsed
   marginal polygons to null/degenerate geometry → "Parameter 'feature' is required
   and may not be null" error on getInfo. Fix: re-compute area_sqm after simplify
   and re-apply `area_sqm >= 10000` filter.

2. **Strip-level resilience** (`lake_detection.py`): wide tiles split into longitude
   strips; now each strip has try/except so one failing strip doesn't abort the tile.

3. **dbt export CI path** (`dbt/export_marts.py`): was hardcoded to
   `himalwatch_dev.duckdb`; fixed to auto-detect `/tmp/himalwatch.duckdb` if present
   (CI writes there), else fall back to dev db.

4. **detection_date** (`dbt/models/staging/stg_lake_detections.sql`): was using
   `season_start`; corrected to `season_end` (imagery window closes at season end,
   so that's the most accurate "observed" date).

## GEE Service Account
- CI uses `GEE_SERVICE_ACCOUNT_KEY` env var (base64-encoded JSON) in GitHub Actions
- Local dev: `earthengine authenticate` with user credentials
- Project: `himalwatch` (set via `GEE_PROJECT` env var or default)
