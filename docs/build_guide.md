# HimalWatch — Step-by-Step Build Guide

Each task is labelled **[MANUAL]** (you do it) or **[CLAUDE CODE]** (paste the prompt into Claude Code).
Run them in order. Don't skip ahead — each step assumes the previous one is done.

---

## PHASE 0 — Accounts & Repo Skeleton

### Step 0.1 [MANUAL] — Create the GitHub repo
Go to github.com → New repository → name: `himalwatch` → Public → Add README → License: Apache 2.0.
Clone locally: `git clone https://github.com/YOUR_USERNAME/himalwatch.git && cd himalwatch`

### Step 0.2 [MANUAL] — Sign up for Google Earth Engine
Go to `code.earthengine.google.com` → Sign in with Google → Request access for non-commercial research.
In the project description write: "Open data platform for glacial lake monitoring in the Nepal Himalaya using Sentinel-2 and Landsat imagery. All outputs published under Creative Commons license."
Approval takes 1–3 days. Continue with other steps while waiting.

### Step 0.3 [MANUAL] — Create Cloudflare R2 bucket
- Sign up at cloudflare.com (free)
- Go to R2 → Create bucket → name: `himalwatch-data` → Location: Auto
- Under bucket settings → enable public access → note the public URL (format: `pub-XXXXX.r2.dev`)
- Go to R2 → Manage R2 API tokens → Create token with Edit permissions → save the Access Key ID and Secret Access Key

### Step 0.4 [MANUAL] — Create Vercel account
- Sign up at vercel.com with GitHub
- Import your `himalwatch` repo
- Deploy as-is (just the README) → your site will be live at `himalwatch.vercel.app` (or similar)

### Step 0.5 [CLAUDE CODE] — Scaffold the repo structure

```
Create the following directory and file structure in the current directory (a git repo called himalwatch). 
Do not write any real code yet — just create the folders and placeholder files with brief comments 
explaining what each will contain.

Structure:
pipeline/
  gee/
    lake_detection.js        ← Google Earth Engine script (JavaScript, runs in GEE Code Editor)
    lake_detection.py        ← Python port using geemap
    cloud_masking.py         ← Cloud masking utilities for Sentinel-2
    export_to_r2.py          ← Writes GeoJSON/Parquet output to Cloudflare R2
  requirements.txt           ← Python dependencies for pipeline
dbt/
  dbt_project.yml
  profiles.yml.example       ← Template (never commit real credentials)
  models/
    staging/
      stg_lake_detections.sql
    marts/
      mart_lake_inventory.sql
      mart_change_alerts.sql
api/
  main.py                    ← FastAPI app
  requirements.txt
  Dockerfile
dashboard/
  index.html                 ← Single-file DuckDB-Wasm dashboard
  app.js
  style.css
docs/
  methodology.md             ← Data methodology documentation
  data_dictionary.md         ← Column definitions
.github/
  workflows/
    pipeline.yml             ← GitHub Actions scheduled pipeline
.gitignore                   ← Python, Node, secrets
README.md                    ← Already exists, leave it

After creating the structure, print a tree of what was created.
```

---

## PHASE 1 — GEE Spike (do this after GEE account is approved)

### Step 1.1 [CLAUDE CODE] — Write the GEE JavaScript lake detection script

```
Write the Google Earth Engine JavaScript script for pipeline/gee/lake_detection.js.

This script runs in the GEE Code Editor (code.earthengine.google.com) — it uses the 
GEE JavaScript API, not Python.

The script should:

1. Define a test area of interest — bounding box around the Bali Pass / upper Tons river basin 
   in Uttarakhand, India (approximately: lon 78.2–78.6, lat 30.9–31.2)

2. Load Sentinel-2 Surface Reflectance imagery (COPERNICUS/S2_SR_HARMONIZED) for the 
   most recent complete summer season (June–September of the most recent year)

3. Apply basic cloud masking using the QA60 band — mask pixels where cloud or cirrus bits are set

4. Calculate NDWI (Normalized Difference Water Index) using:
   NDWI = (Green - NIR) / (Green + NIR)
   For Sentinel-2: Green = B3, NIR = B8

5. Create a median composite of the cloud-masked, NDWI-calculated imagery

6. Load SRTM DEM (USGS/SRTMGL1_003) and create an elevation mask for pixels above 3500m

7. Apply both masks: NDWI > 0.3 AND elevation > 3500m to identify glacial lake candidates

8. Convert the water mask to vectors (polygons)

9. Filter out very small features — minimum area 10,000 sqm (1 hectare)

10. Add the following to the map for visual inspection:
    - The Sentinel-2 RGB composite
    - The NDWI layer
    - The detected water body polygons (in blue)
    - The DEM for context

11. Print the count of detected features to the console

12. Export the detected polygons as a GeoJSON asset and also to Google Drive

Add detailed comments throughout explaining each step and the reasoning.
Include a comment block at the top with: purpose, data sources, expected output, 
and instructions for running it.
```

### Step 1.2 [MANUAL] — Run the GEE script
- Open `code.earthengine.google.com`
- Paste the content of `pipeline/gee/lake_detection.js` into the editor
- Click Run
- Inspect the map output — do the blue polygons correspond to visible lakes?
- Check the console for feature count
- Note any issues (missed lakes, false positives from snowmelt) for the next step

### Step 1.3 [CLAUDE CODE] — Port GEE script to Python using geemap

```
Write the Python port of the GEE lake detection script in pipeline/gee/lake_detection.py.
This uses the geemap and earthengine-api Python libraries.

The script should do exactly what lake_detection.js does but in Python, with these additions:

1. Use argparse to accept:
   --region: bounding box as "min_lon,min_lat,max_lon,max_lat" (default: Bali Pass test area)
   --year: year to process (default: most recent complete year)
   --output-dir: local directory to write outputs (default: ./outputs)
   --export-r2: flag to also upload to R2 (implementation placeholder — we wire this later)

2. After detection, compute for each polygon:
   - area_sqm (square metres)
   - centroid_lat, centroid_lon
   - mean_elevation (from SRTM)
   - mean_ndwi
   - detection_date (the date of the composite)

3. Export two formats to output-dir:
   - lakes_YYYY.geojson
   - lakes_YYYY.csv (flat, no geometry — just centroid + attributes)

4. Print a summary to stdout: region processed, date range, number of lakes detected, 
   total water area in sqkm

Also update pipeline/requirements.txt with all required packages including:
earthengine-api, geemap, geopandas, shapely, pandas, pyarrow, boto3, click, python-dotenv
```

---

## PHASE 2 — Storage & Pipeline

### Step 2.1 [CLAUDE CODE] — R2 export module

```
Write pipeline/gee/export_to_r2.py — a module for uploading pipeline outputs to Cloudflare R2.

Cloudflare R2 is S3-compatible. Use boto3 with endpoint_url pointing to R2.

The module should:

1. Read configuration from environment variables:
   R2_ENDPOINT_URL (format: https://ACCOUNT_ID.r2.cloudflarestorage.com)
   R2_ACCESS_KEY_ID
   R2_SECRET_ACCESS_KEY
   R2_BUCKET_NAME (default: himalwatch-data)

2. Provide these functions:
   
   upload_geojson(local_path, year, region_name)
   → uploads to r2://himalwatch-data/raw/lakes/{region_name}/{year}/lakes.geojson
   
   upload_parquet(local_path, year, region_name)
   → uploads to r2://himalwatch-data/raw/lakes/{region_name}/{year}/lakes.parquet
   
   upload_csv(local_path, year, region_name)
   → uploads to r2://himalwatch-data/raw/lakes/{region_name}/{year}/lakes.csv
   
   list_available_years(region_name)
   → returns list of years for which data exists in R2 for this region

3. Also write a helper function convert_geojson_to_parquet(geojson_path) → parquet_path
   that converts a GeoJSON to Parquet using geopandas + pyarrow before upload.
   Store geometry as WKT string (not binary) so DuckDB can read it later.

4. Add a __main__ block for testing: python export_to_r2.py --test
   This should upload a small test file and verify it can be read back.

Also create a .env.example file in the project root with all required env vars listed 
(no real values) and update .gitignore to include .env
```

### Step 2.2 [CLAUDE CODE] — GitHub Actions pipeline workflow

```
Write .github/workflows/pipeline.yml — a GitHub Actions workflow that runs the lake 
detection pipeline on a schedule.

The workflow should:

1. Trigger:
   - On a cron schedule: weekly, Sundays at 02:00 UTC
   - On manual trigger (workflow_dispatch) with an optional input for year (default: current year)
   - On push to main only if files in pipeline/ directory changed

2. Job: detect-lakes
   Runs on: ubuntu-latest
   
   Steps:
   a. Checkout repo
   b. Set up Python 3.11
   c. Install dependencies from pipeline/requirements.txt
   d. Authenticate to Google Earth Engine using a service account key stored as 
      GitHub secret GEE_SERVICE_ACCOUNT_KEY (JSON, base64-encoded)
   e. Run lake_detection.py for the Nepal Himalaya region 
      (bounding box covering the full Nepal Himalaya: lon 80.0–88.2, lat 27.5–29.5)
   f. Run export_to_r2.py to upload outputs to R2
   g. Print a summary of what was produced

3. Environment variables should come from GitHub secrets:
   GEE_SERVICE_ACCOUNT_KEY, R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

4. Add a step that writes a run_log.json artifact with: 
   timestamp, region, year, lakes_detected_count, total_area_sqkm, status

Also write a companion docs/setup_gee_service_account.md that explains exactly how to:
- Create a GEE service account in Google Cloud Console
- Register it in GEE
- Export the JSON key
- Base64-encode it for the GitHub secret
(Step by step, with exact menu paths)
```

---

## PHASE 3 — dbt Models

### Step 3.1 [CLAUDE CODE] — dbt project setup

```
Set up the dbt project in the dbt/ directory. We use the dbt-duckdb adapter, reading 
Parquet files directly from Cloudflare R2 (S3-compatible).

Create:

1. dbt/dbt_project.yml:
   - project name: himalwatch
   - model paths: [models]
   - profile: himalwatch
   - model configs: staging models materialised as views, mart models as tables

2. dbt/profiles.yml.example (template, never the real file):
   himalwatch:
     target: dev
     outputs:
       dev:
         type: duckdb
         path: ./himalwatch_dev.duckdb
         extensions: [httpfs, spatial]
         settings:
           s3_endpoint: "ACCOUNT_ID.r2.cloudflarestorage.com"
           s3_access_key_id: "YOUR_R2_ACCESS_KEY"
           s3_secret_access_key: "YOUR_R2_SECRET_KEY"
           s3_use_ssl: true
           s3_url_style: path

3. dbt/models/staging/schema.yml:
   Document the source: name it raw_lakes, pointing to the R2 Parquet path pattern
   s3://himalwatch-data/raw/lakes/*/*/lakes.parquet
   
   Document all source columns with descriptions:
   lake_id, geometry_wkt, area_sqm, centroid_lat, centroid_lon, mean_elevation,
   mean_ndwi, detection_date, region_name, year

4. dbt/models/staging/stg_lake_detections.sql:
   - Read from the R2 source
   - Cast types correctly (detection_date as DATE, numeric columns as DOUBLE)
   - Derive lake_id as a hash of (centroid_lat rounded to 4dp, centroid_lon rounded to 4dp) 
     — this creates a stable ID across runs for the same approximate location
   - Add loaded_at timestamp
   - Filter out any rows with null geometry or area < 10000 sqm

5. dbt/models/marts/schema.yml:
   Document both mart models with full column descriptions.

6. dbt/models/marts/mart_lake_inventory.sql:
   - Latest known state of every unique lake (by lake_id)
   - Columns: lake_id, centroid_lat, centroid_lon, mean_elevation, region_name,
     latest_area_sqm, latest_ndwi, first_detected_date, latest_detection_date,
     detection_count, area_change_sqm (latest vs first), area_change_pct

7. dbt/models/marts/mart_change_alerts.sql:
   - Lakes where area has changed by more than 15% between first and latest detection
   - AND latest detection is within the last 90 days
   - AND at least 2 detections exist (prevents single-observation noise)
   - Columns: lake_id, centroid_lat, centroid_lon, region_name, mean_elevation,
     first_area_sqm, latest_area_sqm, area_change_pct, first_detected_date,
     latest_detection_date, alert_severity (LOW: 15-30%, MEDIUM: 30-50%, HIGH: >50%)

Also create dbt/.gitignore to exclude profiles.yml and *.duckdb
```

---

## PHASE 4 — Dashboard

### Step 4.1 [CLAUDE CODE] — Public dashboard (DuckDB-Wasm frontend)

```
Build the public web dashboard in dashboard/. This is a single-page application using 
DuckDB-Wasm to query Parquet files directly from Cloudflare R2 in the browser.
No build step, no framework — plain HTML, CSS, and vanilla JavaScript.

The dashboard should have three views, toggled by a tab bar:
  MAP VIEW | LAKE LIST | CHANGE ALERTS

Design tone: scientific and serious — this is a research/monitoring platform, 
not a consumer app. Dark header, clean sans-serif typography, muted colour palette.
The name "HimalWatch" in the header with a subtitle "Glacial Lake Monitoring · Nepal Himalaya"

--- MAP VIEW ---
Use MapLibre GL JS (CDN) with a free OpenStreetMap-based tile source (use 
https://demotiles.maplibre.org/style.json as the style for now — we can swap later).
Show lake locations as circle markers sized by area_sqm (log scale).
Colour markers by alert status: grey = no alert, yellow = LOW, orange = MEDIUM, red = HIGH.
On marker click: show a popup with lake_id, elevation, latest area, change %, detection dates.
Add a legend explaining marker colours.

--- LAKE LIST VIEW ---
A sortable table showing all lakes from mart_lake_inventory.
Columns: Lake ID (truncated), Region, Elevation (m), Latest Area (ha), 
Area Change (%), First Detected, Latest Detection.
Sort by area change % descending by default.
Clicking a row should show a simple area time series — for now just display 
first and latest values as a two-point mini chart using SVG.

--- CHANGE ALERTS VIEW ---
Cards (not a table) showing only HIGH and MEDIUM severity lakes from mart_change_alerts.
Each card: lake coordinates, elevation, area change %, severity badge, date range.
Cards sorted by severity then by change %.
If no alerts exist, show a "No active alerts" message.

--- DATA LOADING ---
On page load, use DuckDB-Wasm (via CDN: https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm)
to query the R2 Parquet files.
The R2 public bucket URL should be read from a config object at the top of app.js:
  const CONFIG = { r2BaseUrl: "https://pub-PLACEHOLDER.r2.dev" };
(We will replace the placeholder with the real URL.)

Query pattern:
  SELECT * FROM read_parquet('${CONFIG.r2BaseUrl}/marts/mart_lake_inventory.parquet')
  SELECT * FROM read_parquet('${CONFIG.r2BaseUrl}/marts/mart_change_alerts.parquet')

Show a loading spinner while queries are running.
Show a friendly error message if data cannot be loaded (R2 URL not configured, CORS issue, etc.)

--- FOOTER ---
"Data updated weekly from Sentinel-2 (ESA) and Landsat (USGS) imagery · 
Published under CC BY 4.0 · github.com/YOUR_USERNAME/himalwatch"

Put everything in three files: dashboard/index.html, dashboard/app.js, dashboard/style.css
The HTML file should link to the JS and CSS files (not inline them).
```

### Step 4.2 [MANUAL] — Deploy dashboard to Vercel
- `git add dashboard/ && git commit -m "feat: add dashboard" && git push`
- Vercel auto-deploys from main — check the deployment at `himalwatch.vercel.app`
- In Vercel project settings → set the root directory to `dashboard/`
- Update `CONFIG.r2BaseUrl` in `app.js` with your actual R2 public URL
- Also: in Cloudflare R2 bucket settings → add CORS rule allowing GET from `*.vercel.app`

---

## PHASE 5 — FastAPI Backend

### Step 5.1 [CLAUDE CODE] — FastAPI application

```
Build the FastAPI application in api/main.py.

The API reads from Cloudflare R2 Parquet files using DuckDB (server-side).
All config from environment variables — use python-dotenv.

Endpoints:

GET /
  Returns: {"name": "HimalWatch API", "version": "0.1.0", "docs": "/docs", 
            "status": "operational", "last_updated": "<date from latest parquet>"}

GET /lakes
  Query params: region (optional), min_elevation (optional, int), 
                min_area_ha (optional, float), limit (default 500, max 2000)
  Returns: GeoJSON FeatureCollection
  Each feature: geometry (Point at centroid), properties matching mart_lake_inventory columns
  
GET /lakes/{lake_id}
  Returns: single lake object with all inventory fields
  404 if not found

GET /lakes/{lake_id}/history
  Returns: list of all detections for this lake_id from stg_lake_detections,
           ordered by detection_date ascending
  Each item: {detection_date, area_sqm, area_ha, mean_ndwi}

GET /alerts
  Query params: severity (optional: LOW/MEDIUM/HIGH), region (optional)
  Returns: list of alert objects from mart_change_alerts, sorted by area_change_pct desc

GET /stats
  Returns aggregate stats:
  {total_lakes, total_water_area_sqkm, lakes_with_alerts, 
   high_severity_count, medium_severity_count, low_severity_count,
   regions_covered, last_pipeline_run}

GET /download/lakes.geojson
  Streams the full lake inventory as a GeoJSON file download (Content-Disposition: attachment)

GET /download/lakes.csv
  Streams the full lake inventory as CSV (no geometry)

Technical requirements:
- Use DuckDB Python to query R2 Parquet — same credentials as dbt via env vars
- Add CORS middleware allowing all origins (this is a public research API)
- Add gzip compression middleware
- Use FastAPI's built-in response models with Pydantic — define proper response schemas
- Rate limiting: use slowapi, max 60 requests/minute per IP
- Add a /health endpoint for Render health checks

Also write:
- api/requirements.txt with all dependencies
- api/Dockerfile (for future containerisation if needed)
- api/.env.example with all required variables listed

Keep the code clean and well-commented — the docstrings become the OpenAPI documentation.
```

### Step 5.2 [MANUAL] — Deploy API to Render
- Sign up at render.com → New Web Service → connect GitHub repo
- Root directory: `api/`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add all env vars from `.env.example` in the Render dashboard
- Note your API URL: `https://himalwatch-api.onrender.com`
- Update the dashboard `CONFIG` in `app.js` to add `apiUrl: "https://himalwatch-api.onrender.com"`

---

## PHASE 6 — Cloud Masking & Quality Improvements

### Step 6.1 [CLAUDE CODE] — Cloud masking module

```
Write pipeline/gee/cloud_masking.py — a proper cloud masking module for Sentinel-2 
high-altitude imagery.

The Himalaya has persistent cloud cover. This module should implement two masking strategies 
that can be combined or used independently:

1. QA60 bit masking (fast, built into Sentinel-2 product):
   mask_qa60(image) → masked image
   Masks pixels where QA60 band bits 10 (cloud) or 11 (cirrus) are set.

2. Scene Classification Layer (SCL) masking (more accurate for high-altitude):
   mask_scl(image, exclude_classes=None) → masked image
   SCL classes to exclude by default: 3 (cloud shadow), 8 (cloud medium prob), 
   9 (cloud high prob), 10 (thin cirrus), 11 (snow) — note: we exclude snow to avoid 
   misidentifying seasonal snowmelt as lakes.
   Allow override via exclude_classes parameter.

3. Temporal composite strategy:
   build_clean_composite(collection, method='median') → composite image
   Builds a cloud-free composite from a collection using:
   - method='median': pixel-wise median (default, smoothest)
   - method='mosaic': most-recent-valid-pixel mosaic (preserves temporal recency)
   - method='percentile_10': 10th percentile — useful for maximising water visibility
   
4. Snow/ice discrimination helper:
   is_likely_snow_not_water(ndwi_value, ndsi_value) → bool
   NDSI = (Green - SWIR) / (Green + SWIR)
   Snow has high NDSI (>0.4) AND high visible reflectance.
   Water has high NDWI but low NDSI.
   This helps distinguish seasonal snowmelt pools from persistent glacial lakes.
   For Sentinel-2: SWIR = B11, Green = B3.

Write full docstrings for each function explaining the science behind each approach.
Include a usage example at the bottom showing how to use these functions with the 
main lake_detection.py script.
```

---

## PHASE 7 — Docs & Open Data

### Step 7.1 [CLAUDE CODE] — Methodology documentation

```
Write docs/methodology.md — the technical methodology documentation for HimalWatch.

This document will be read by glaciologists, ICIMOD researchers, and data scientists 
evaluating whether to use or cite this platform. Write it at that level — rigorous, 
precise, honest about limitations.

Sections:

1. Overview
   What the platform monitors, geographic scope (Nepal Himalaya), update cadence, 
   data sources, and what it does NOT claim to do (it is a monitoring and change 
   detection system, not a GLOF probability model).

2. Satellite Data Sources
   - Sentinel-2 MSI Level-2A (Surface Reflectance), 10m resolution, ~5-day revisit
   - Landsat 8/9 OLI/TIRS Level-2, 30m resolution, 16-day revisit (backup and historical)
   - Both accessed via Google Earth Engine
   - Coverage: Nepal Himalaya bounding box (lon 80.0–88.2, lat 27.5–29.5)
   
3. Lake Detection Algorithm
   - NDWI formula and band selection
   - Threshold value (0.3) and rationale — cite relevant literature showing this threshold 
     performs well for high-altitude Himalayan water bodies
   - Elevation filter (>3500m) and why this cutoff was chosen
   - Minimum area filter (1 hectare / 10,000 sqm) to exclude noise
   - Cloud masking approach
   - Snow/water discrimination using NDSI

4. Change Detection
   - How lake_id is assigned (centroid hash — explain the approach and its limitations)
   - How area change is calculated
   - Alert thresholds (15%, 30%, 50%) and why these were chosen
   - Known sources of false positives (seasonal variation, cloud shadow, snow)
   - Rolling window for change detection

5. Known Limitations
   - Cloud cover in monsoon season significantly reduces summer coverage
   - 10m resolution means very small lakes (<1ha) are likely undercounted
   - lake_id assignment based on centroid proximity may split or merge lakes that 
     shift slightly between seasons
   - NDWI cannot distinguish water depth — area ≠ volume (area-volume relationships 
     from literature used as approximations)
   - This is a monitoring system, not a GLOF early warning system — it detects slow 
     lake growth, not rapid drainage events

6. Comparison with Existing Inventories
   Brief note on how this system relates to ICIMOD HI-CAP glacial lake inventory, 
   DHM monitoring data, and GLIMS (Global Land Ice Measurements from Space).
   The intent is to complement, not replace, these authoritative sources.

7. Data License and Citation
   All data published under Creative Commons Attribution 4.0 (CC BY 4.0).
   Suggested citation format.

Write this as proper technical documentation — use markdown headers, include the 
NDWI and NDSI formulas as proper math notation (use LaTeX-style in backticks), 
be specific about parameters and thresholds throughout.
```

### Step 7.2 [CLAUDE CODE] — Data dictionary

```
Write docs/data_dictionary.md — a complete reference for every dataset the platform produces.

For each dataset, document: what it is, how it's produced, update frequency, 
file location in R2, and a table of all columns with name, type, description, and example value.

Datasets to document:

1. raw/lakes/{region}/{year}/lakes.geojson — raw pipeline output
2. raw/lakes/{region}/{year}/lakes.parquet — same as above, Parquet format
3. marts/mart_lake_inventory.parquet — latest state of all lakes
4. marts/mart_change_alerts.parquet — lakes with anomalous area change

For every column in every dataset, write a precise description.
Do not skip columns or write vague descriptions like "the lake area" — 
write "Surface area of the lake in square metres, derived from the count of 
10m Sentinel-2 pixels classified as water, multiplied by 100."

End with a section: "How to query this data with DuckDB"
Show 5 practical example queries:
1. All lakes above 5000m elevation
2. Lakes that grew more than 20% in the last year
3. Total water area by region
4. Time series of area for a specific lake_id
5. Lakes within 10km of a given coordinate (with the spatial distance formula)
```

---

## WHAT YOU HAVE AFTER ALL STEPS

| Artifact | URL |
|---|---|
| Live dashboard | `himalwatch.vercel.app` |
| Public API | `himalwatch-api.onrender.com/docs` |
| Open data | `pub-XXXX.r2.dev/marts/mart_lake_inventory.parquet` |
| Source code | `github.com/YOUR_USERNAME/himalwatch` |
| Methodology | `github.com/YOUR_USERNAME/himalwatch/blob/main/docs/methodology.md` |

This is what you bring to ICIMOD — not a proposal.

---

## QUICK REFERENCE — Secrets to configure

| Secret name | Where | What |
|---|---|---|
| `GEE_SERVICE_ACCOUNT_KEY` | GitHub Actions | Base64-encoded GEE service account JSON |
| `R2_ENDPOINT_URL` | GitHub Actions + Render | `https://ACCOUNT_ID.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | GitHub Actions + Render | Cloudflare R2 API token |
| `R2_SECRET_ACCESS_KEY` | GitHub Actions + Render | Cloudflare R2 API secret |
| `R2_BUCKET_NAME` | GitHub Actions + Render | `himalwatch-data` |

Never commit any of these to git. Always use `.env` locally (gitignored) and 
platform secrets for deployed environments.
