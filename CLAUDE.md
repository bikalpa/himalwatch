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
GEE (Sentinel-2) → lake_detection.py → GeoJSON/Parquet → R2 (raw/)
                                                              ↓
                                                   dbt (DuckDB reads R2)
                                                              ↓
                                              R2 (marts/*.parquet)
                                             /                \
                              FastAPI (server-side DuckDB)   Dashboard (DuckDB-Wasm in browser)
```

### Key Design Decisions

**lake_id stability**: Lake IDs are derived by hashing centroid coordinates rounded to 4 decimal places (~11m precision). This creates stable IDs across pipeline runs for the same lake, but can split/merge lakes that shift between seasons — a known limitation.

**Detection thresholds**: NDWI > 0.3 with elevation > 3500m and minimum area 10,000 sqm (1 ha). The 0.3 NDWI threshold is calibrated for high-altitude Himalayan water bodies. Lowering it increases false positives from shadow/snowmelt.

**Snow vs. water discrimination**: `cloud_masking.py` implements NDSI-based discrimination. Snow has NDSI > 0.4; water does not. SCL masking excludes class 11 (snow) by default.

**Storage**: All data lives in Cloudflare R2 (`himalwatch-data` bucket). Raw outputs go to `raw/lakes/{region}/{year}/`. dbt writes marts to `marts/`. Geometry is stored as WKT strings (not binary GeoJSON) so DuckDB can read it without spatial extensions.

**dbt adapter**: Uses `dbt-duckdb` with `httpfs` extension to read Parquet directly from R2 over S3-compatible API. No data warehouse — DuckDB is the query engine both locally (dbt) and in production (FastAPI + DuckDB-Wasm).

### Alert Severity Tiers
- LOW: 15–30% area change
- MEDIUM: 30–50% area change  
- HIGH: >50% area change
- Requires ≥2 detections and latest detection within 90 days

## Environment Variables

All components read from `.env` (local) or platform secrets (CI/deployed). Required variables:

```
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=himalwatch-data
GEE_SERVICE_ACCOUNT_KEY=  # base64-encoded JSON, for CI only
```

## Deployment

| Component | Platform | Trigger |
|-----------|----------|---------|
| Pipeline | GitHub Actions | Weekly cron (Sun 02:00 UTC) + push to `pipeline/` |
| dbt models | GitHub Actions | After pipeline job |
| API | Render | Auto-deploy on push to `main` |
| Dashboard | Vercel | Auto-deploy on push to `main` |

## GEE Notes

- The JavaScript script (`lake_detection.js`) runs in the GEE Code Editor at `code.earthengine.google.com` — it cannot be run from the terminal.
- The Python port (`lake_detection.py`) uses `earthengine-api` + `geemap` and requires prior `earthengine authenticate` or a service account key.
- Summer season (June–September) imagery is used to avoid snow confusion. Cloud cover is highest during monsoon — this is the primary data quality constraint.
