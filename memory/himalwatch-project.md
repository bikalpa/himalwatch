# HimalWatch — Project Overview

## What it is
Open-data platform for glacial lake monitoring in the Nepal Himalaya. Detects
glacial lakes from Sentinel-2 satellite imagery via Google Earth Engine, stores
results in Cloudflare R2, transforms with dbt, serves via a FastAPI API and a
DuckDB-Wasm browser dashboard.

## Repo
- Local: `C:\Users\bikal\Code\Github_repos\himalwatch`
- GitHub: `bikalpa/himalwatch`
- Email: bikalpa@gmail.com

## Stack
| Layer | Technology |
|---|---|
| Detection | Python + GEE (`pipeline/gee/lake_detection.py`) |
| Storage | Cloudflare R2 bucket `himalwatch-data` |
| Transform | dbt-duckdb (reads Parquet from R2 via httpfs) |
| API | FastAPI on Render (server-side DuckDB) |
| Dashboard | Static SPA on Vercel (`dashboard/`) — no build step, in-browser Babel |
| Map | MapLibre GL JS v4 — ESRI satellite + topo tiles |
| CI | GitHub Actions — weekly cron (Sun 02:00 UTC) + push to `pipeline/` |

## Deployment
- Dashboard → **Vercel** (auto-deploy on push to main; `vercel.json` in repo root)
  - `outputDirectory: "dashboard"`, `framework: null`, SPA rewrite rule
- API → Render (auto-deploy on push to main)
- Pipeline → GitHub Actions

## R2 Layout
- Public base URL: `https://pub-ebc663fdb5cc4a0ea7bde7330a88bfe2.r2.dev`
- Raw detections: `raw/lakes/{tile}/{year}/lakes.parquet`
- dbt marts: `marts/mart_lake_inventory.parquet`, `marts/mart_change_alerts.parquet`
- Master registry: `lakes_master.parquet`

## GEE Detection Parameters
- NDWI threshold: 0.3 (McFeeters 1996)
- Elevation min: 3500 m (SRTM)
- Min area: 10,000 sqm (1 ha)
- Season: June–September (avoids snow confusion)
- Detection scale: 20 m (4× fewer pixels vs 10 m; same ha-scale accuracy)
- Max strip width: 1.2° (wide tiles split into longitude strips to avoid GEE timeout)

## 6 AOI Tiles
| Tile | Region |
|---|---|
| khumbu | Everest / Khumbu |
| langtang | Langtang |
| annapurna | Annapurna |
| far_west | Far West Nepal |
| karnali | Karnali |
| kangchenjunga | Kangchenjunga |

## Alert Severity Tiers
- LOW: 15–30% area change
- MEDIUM: 30–50% area change
- HIGH: >50% area change
- Requires ≥2 detections and latest detection within 90 days

## Environment Variables (all components)
```
R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME=himalwatch-data
GEE_SERVICE_ACCOUNT_KEY  # base64-encoded JSON, CI only
GEE_PROJECT=himalwatch
```
