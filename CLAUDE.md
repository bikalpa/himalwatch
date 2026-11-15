# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HimalWatch is an open-data platform for glacial lake monitoring in the Nepal Himalaya. It detects glacial lakes from Sentinel-2 satellite imagery using Google Earth Engine, stores results in Cloudflare R2, transforms them with dbt, and serves them via a FastAPI backend and a DuckDB-Wasm browser dashboard.

## Repository Structure

```
pipeline/gee/       ← GEE lake detection scripts (JS + Python)
dbt/                ← dbt-duckdb models reading Parquet from R2
api/                ← FastAPI app (served on Render)
dashboard/          ← Static SPA (deployed to Vercel)
docs/               ← methodology.md, data_dictionary.md
.github/workflows/  ← Weekly pipeline.yml (GH Actions)
```

## Commands

### Pipeline (Python)
```bash
cd pipeline
pip install -r requirements.txt

# Authenticate GEE (first time)
earthengine authenticate

# Run lake detection for a region/year
python gee/lake_detection.py --region "80.0,27.5,88.2,29.5" --year 2024 --output-dir ./outputs

# Upload outputs to R2
python gee/export_to_r2.py --test   # smoke test with small file
```

### dbt
```bash
cd dbt
cp profiles.yml.example profiles.yml   # then fill in R2 credentials
pip install dbt-duckdb

dbt run          # run all models
dbt test         # run schema tests
dbt run --select staging    # run only staging models
dbt run --select marts      # run only mart models
```

### API
```bash
cd api
pip install -r requirements.txt
cp .env.example .env   # fill in R2 credentials

uvicorn main:app --reload --port 8000
# Docs available at http://localhost:8000/docs
```

### Dashboard
No build step — open `dashboard/index.html` directly in a browser, or:
```bash
python -m http.server 3000 --directory dashboard
# Then visit http://localhost:3000
```
Update `CONFIG.r2BaseUrl` in `dashboard/app.js` to point to the real R2 public URL before testing data load.

## Architecture

### Data Flow
```
GEE (Sentinel-2) → lake_detection.py → raw/lakes/{tile}/{year}/lakes.parquet (R2)
                                              ↓
                        link_lakes.py → linked/lake_detections.parquet   (stable lake_id)
                                              ↓
                              dbt (DuckDB) → marts/*.parquet
                                              ↓
              lake_gifs.py → media/lakes/{lake_id}/{year}.png + growth.gif
                                              ↓
        export_worker_json.py → cache/*.json (dashboard)   fanout.py → alerts
```

### Key Design Decisions

**Detection rule**: Sep 1 – Oct 31 median composite (post-monsoon: clear, lakes at max extent, not yet frozen), NDWI > 0.2, slope < 20°, elevation > 3500 m, min area 1 ha. Chosen with `pipeline/gee/validate_known_lakes.py` (run the `validate-detection` workflow) against 8 well-known lakes for 2022–2026 — re-run it before changing any threshold. Do NOT add an NDSI "not snow" test: open water has a high NDSI and the old `NDSI < 0.4` test removed nearly every real lake. A NIR cap was also tested and rejected (drops turbid lakes like Imja).

**lake_id stability**: the `lake_id` in raw files is a random per-run UUID and is ignored. `pipeline/link_lakes.py` links polygons across years by overlap (not centroid distance — a growing lake moves its centroid) and derives a deterministic id from the earliest-year centroid. Split/merged lakes are summed per year. Adding an earlier year can change an id.

**Season year**: a season is processed once its window has closed (from 1 Nov). Weekly runs outside Nov re-process the same season and stay silent.

**Storage**: Cloudflare R2 (`himalwatch-data`). Geometry is WKT so DuckDB needs no spatial extension. Per-lake season snapshots (`media/lakes/{id}/{year}.png`) are kept permanently and reused; only the newest season is re-fetched.

### Growth alerts
A lake is flagged GROWING when: it lies inside Nepal or within ~5 km of the border (`in_nepal`, set by `link_lakes.py` from `pipeline/utils/nepal_boundary.geojson`; lakes further into Tibet are tracked but never alerted), seen in ≥ 5 seasons, seen in one of the two newest seasons for its tile, Spearman rank correlation of area vs year ≥ 0.9, and recent area (median of last k seasons) ≥ 10% and ≥ 1 ha above early area (median of first k), k = min(3, n/2). Severity by that growth: LOW 10–25%, MEDIUM 25–50%, HIGH > 50%. Tuned on the 2019–2026 backfill: flags Imja Tsho and Lower Barun, ignores lakes whose area just jumps around. Shrinking lakes are not alerted.

`pipeline/alerts/fanout.py` sends one digest per run for lakes not yet announced at their current severity (state in R2 `alerts/notified.json`): a GitHub issue that @-mentions the repo owner (GitHub emails it), plus an HTML email via Resend if `RESEND_API_KEY` and `ALERT_EMAIL_TO` secrets are set.

## Environment Variables

All components read from `.env` (local) or platform secrets (CI/deployed). Required variables:

```
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=himalwatch-data
GEE_SERVICE_ACCOUNT_KEY=  # base64-encoded JSON, for CI only
RESEND_API_KEY=           # optional — HTML alert email
ALERT_EMAIL_TO=           # optional — comma-separated recipients (keep in secrets, repo is public)
```

## Deployment

| Component | Platform | Trigger |
|-----------|----------|---------|
| Pipeline | GitHub Actions | Weekly cron (Sun 02:00 UTC) or manual dispatch (`years` for backfill, `notify` off for a dry run). A keepalive job re-enables the workflow each run — GitHub disables idle scheduled workflows after 60 days. |
| dbt models | GitHub Actions | After pipeline job |
| API | Render | Auto-deploy on push to `main` |
| Dashboard | Vercel | Auto-deploy on push to `main` |

## GEE Notes

- The JavaScript script (`lake_detection.js`) runs in the GEE Code Editor at `code.earthengine.google.com` — it cannot be run from the terminal.
- The Python port (`lake_detection.py`) uses `earthengine-api` + `geemap` and requires prior `earthengine authenticate` or a service account key.
- Post-monsoon (Sep–Oct) imagery is used: monsoon (Jun–Sep) composites were too cloudy to give repeatable lake areas.
