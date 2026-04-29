# HimalWatch Plan Review — GLOF Detection & Alerts

A critical review of the build plan against three goals: **scalability**, **free hosting**, and **actual GLOF detection/alerting** (not just lake inventory).

---

## TL;DR — The big picture

**What the current plan delivers**: A glacial lake **inventory** with **change monitoring** — lakes detected from Sentinel-2 NDWI, area trended over time, alerts when lakes grow >15%.

**What it does NOT deliver**: A GLOF early-warning system. The methodology section even admits this: *"This is a monitoring system, not a GLOF early warning system — it detects slow lake growth, not rapid drainage events."*

That's a gap between the project name (suggested in chat as GLOF detection) and what's being built. You have two options:

1. **Reframe** as "Glacial Lake Change Monitoring" — honest, achievable, useful for ICIMOD as a complement to HI-CAP.
2. **Extend** the plan toward genuine GLOF risk assessment — adds Sentinel-1 SAR, DEM-based downstream analysis, dam-type classification, and volume estimation.

This review covers both paths and flags concrete issues in the existing plan.

---

## Part 1 — Free-tier risks in the current stack

| Component | Free tier | Risk | Mitigation |
|---|---|---|---|
| GEE non-commercial | Free with quotas | Memory/timeout on full Nepal AOI in one pass | Tile the AOI into ~10 sub-regions, process in parallel jobs |
| Cloudflare R2 | 10 GB storage, 1M Class A ops/mo, 10M Class B ops/mo, **egress free** | Browser dashboard fetching full Parquet on every page view eats Class B ops | Pre-aggregate to small tiles; use `Cache-Control` headers; consider tile-based fetching |
| GitHub Actions | Unlimited minutes for public repos | None for public repo | Keep repo public ✓ |
| Vercel Hobby | 100 GB bandwidth/mo, no commercial use | If platform gets cited and traffic spikes | Move dashboard to **Cloudflare Pages** (unlimited bandwidth, same R2 origin = zero-egress) |
| **Render free tier** | **750 hrs/mo, spins down after 15 min idle, ~50s cold start** | **Bad UX for a public research API. Cold starts will frustrate every researcher.** | **Drop Render. See alternatives below.** |
| GEE service account | Free | Service-account quotas differ from user accounts; some collections need explicit access | Test early; document in setup guide |

### Recommended substitutions

1. **Replace Render with Cloudflare Workers + R2** — same data, no cold starts, 100k req/day free, runs at the edge near R2. Workers can use `@duckdb/duckdb-wasm` or just stream Parquet partitions directly.
2. **Replace Vercel with Cloudflare Pages** — keeps everything on Cloudflare, R2 egress to Pages is free and direct.
3. **Even better: skip the API entirely.** The dashboard already uses DuckDB-Wasm to query R2 directly. The only reasons to keep an API are: (a) a stable URL for citations, (b) rate limiting, (c) machine consumers that can't run WASM. For (a) Cloudflare Workers handle this in 50 lines; for (b) Cloudflare's built-in rate limiting; for (c) Workers serve the same Parquet with redirects.

---

## Part 2 — Issues in the detection methodology

### 2.1 Critical: this is not GLOF detection
GLOF risk is a function of:
- **Lake volume** (not just area) — 1 ha at 5 m depth ≠ 1 ha at 30 m
- **Dam type** — moraine-dammed lakes >> ice-dammed >> bedrock-dammed in failure probability
- **Trigger conditions** — calving from glacier terminus, ice avalanches, seismic events, heavy rainfall
- **Downstream exposure** — population, infrastructure in the runout path

The current plan captures none of these. Lake area growth is one input to GLOF risk, not the whole picture.

### 2.2 NDWI threshold is too rigid
Single threshold (0.3) for the whole Nepal Himalaya across all seasons is fragile:
- Turbid lakes (suspended sediment from glacier melt) have **lower** NDWI
- Frozen lake surface in shoulder seasons can drop NDWI below 0.3
- Better: use Otsu's method or a region-specific threshold calibrated against ICIMOD HI-CAP

### 2.3 lake_id by centroid hash is brittle
Hashing centroid rounded to 4 dp (~11 m) means a lake that shifts one pixel between years gets a new ID. This breaks all the change-detection logic. Fixes:
- **Spatial join with persistent ID master**: maintain a `lakes_master.parquet` that gets updated only when new lakes appear; assign IDs by spatial overlap with previous master
- **DBSCAN clustering** across years to merge detections of the same lake even with centroid drift
- Use ICIMOD HI-CAP IDs as the canonical source for known lakes, generate new IDs only for novel detections

### 2.4 Snow exclusion will miss ice-fed lakes
The plan excludes SCL class 11 (snow) entirely. But many glacial lakes have partial ice cover or are surrounded by snow. Better: use NDSI to discriminate snow from water at the **pixel** level, not exclude entire SCL classes.

### 2.5 No Sentinel-1 SAR fallback
Monsoon (June–September) — the period of highest melt, highest GLOF risk, and the build plan's chosen detection window — is also the cloudiest. Sentinel-2 will have weeks of unusable imagery. **Sentinel-1 C-band SAR penetrates clouds**. For a serious monitoring system this is essential, not optional. GEE has `COPERNICUS/S1_GRD`. Adds complexity (speckle filtering, water = low backscatter).

### 2.6 No volume estimation
Cook & Quincey 2015 give an empirical area-volume relationship for Himalayan glacial lakes:
```
V = 0.104 * A^1.42   (V in m³, A in m²)
```
Easy to add as a derived column. Critical for any actual risk talk with ICIMOD.

### 2.7 Detection year-by-year misses sub-annual change
The plan's mart computes "first vs latest" detection — that's annual or coarser. Real GLOF precursors (sudden drawdown, rapid expansion in a single melt season) need monthly or biweekly composites. With Sentinel-2's 5-day revisit and SAR backup, monthly composites are feasible.

---

## Part 3 — Missing pieces for actual GLOF use case

### 3.1 Downstream catchment analysis (free)
For every detected lake, compute:
- Downstream flow path using SRTM/HMA DEM + a hydrology routing algorithm (`whitebox` Python lib, free)
- Distance to nearest village/settlement (OpenStreetMap data, free)
- Distance to nearest road, hydroelectric facility (OSM)
- Estimated runout volume via Huggel et al 2002 empirical formula

This converts "lake X grew 20%" into "lake X grew 20% and 14,000 people live in its 50 km runout zone." That's the difference between an inventory and an alert.

### 3.2 Dam-type classification
Hard to fully automate but partial signals exist:
- Ice-cored moraine: high elevation gradient at lake outlet, often near glacier terminus
- Bedrock-dammed: surrounded by exposed rock (high SWIR, low NDVI)
- Moraine-dammed: surrounded by debris (intermediate signals)

Even a coarse three-class probabilistic flag adds risk context.

### 3.3 InSAR for moraine deformation
Sentinel-1 InSAR via GEE (`Hyp3` or `MintPy` post-processing) can detect mm-cm scale ground motion of moraine dams. This is the most direct precursor to dam failure and is genuinely free. It's harder to implement but is the single highest-value addition for a real GLOF warning system.

### 3.4 Actual alerting infrastructure
The current plan has "alerts" as a Parquet file. That's not an alert. Real alerts need a delivery mechanism:

| Channel | Free tier | Best for |
|---|---|---|
| **GitHub Issues** auto-created on HIGH severity | Free, public repo | Public/audit trail |
| **RSS/Atom feed** generated as part of pipeline | Free, static file in R2 | Researchers subscribing |
| **Resend** | 100 emails/day, 3000/mo free | Email subscribers |
| **ntfy.sh** | Free, no signup | Mobile push for ops/team |
| **Slack/Discord webhook** | Free | Team coordination |
| **Telegram bot** | Free | Wide reach in Nepal/India |

A simple pattern: pipeline emits `alerts.json`, a follow-up Action step diffs it against previous run and posts new HIGH-severity entries to all configured channels.

### 3.5 Validation against ground truth
No way to know if detections are correct without comparison. Free options:
- **ICIMOD HI-CAP glacial lake inventory** (open data) — compute precision/recall against it
- **GLIMS** (NSIDC) — global glacier inventory
- **HKH Cryosphere Monitoring Programme** field data (request via ICIMOD)

Add a `validation/` folder with notebooks that compute these metrics on every release. Without it, the methodology page is hand-waving.

### 3.6 Data versioning / reproducibility
A weekly rerun overwrites `mart_lake_inventory.parquet`. There's no way to reproduce "what the platform said on date X." Fix:
- Write timestamped snapshots to `marts/snapshots/YYYY-MM-DD/`
- Keep a `marts/latest/` pointer (or symlink-equivalent)
- Add a simple "data version" string the API and dashboard expose

This is essential for citations — researchers need to cite a specific snapshot, not a moving target.

---

## Part 4 — Scalability concerns

### 4.1 GEE compute will hit limits
A single Earth Engine `Export.table` job over the full Nepal Himalaya AOI for a year of S2 imagery often times out. Real fix:
- Tile AOI into ~5–10 sub-regions (by HKH watershed boundary)
- Run them as separate GitHub Action matrix jobs
- Concatenate outputs in a final dbt step

### 4.2 Browser DuckDB-Wasm at scale
At 5,000+ lakes with full attributes + geometry, the Parquet file will exceed ~10 MB. For mobile users on slow connections, that's a multi-second cold load. Mitigation:
- Split into `lakes_summary.parquet` (loaded eagerly, 5 columns × N rows) and `lakes_detail.parquet` (loaded on demand)
- Load alerts from a tiny `alerts.parquet` (the high-traffic case)
- Range queries via HTTP Range requests (DuckDB-Wasm supports this; only the bytes needed are fetched)

### 4.3 Pipeline incrementality
Reprocessing all years every week is wasteful. After year N–1 is complete, only year N changes. dbt incremental materialisation handles this naturally:
```sql
{{ config(materialized='incremental', unique_key='detection_id') }}
```

### 4.4 R2 path layout for tile-based fetches
Current path: `marts/mart_lake_inventory.parquet` — one file. For tile-based dashboard fetching, partition:
```
marts/lakes_by_tile/region=khumbu/lakes.parquet
marts/lakes_by_tile/region=langtang/lakes.parquet
```
Dashboard fetches only the visible map tile's region.

---

## Part 5 — What I'd actually build (revised priorities)

If the goal is "scalable, free, GLOF-relevant, deliverable to ICIMOD," I'd reorder the phases:

**Phase A — Foundation (current Phases 0–2)**
Keep mostly as written, with these changes:
- Drop Render. Use Cloudflare Pages + Workers from day one.
- Tile the AOI from the start; don't build single-region then refactor.
- Add Sentinel-1 SAR detection alongside Sentinel-2 NDWI — they share most of the pipeline plumbing.

**Phase B — Honest inventory (current Phase 3)**
- dbt models with **incremental** materialisation
- Snapshot table for reproducibility
- Spatial-join lake_id with a master inventory seeded from ICIMOD HI-CAP

**Phase C — Risk context (NEW, what makes this GLOF-relevant)**
- Volume estimate via Cook & Quincey 2015
- Downstream analysis: settlements within runout zone (OSM)
- Dam-type classification from terrain/spectral signals
- InSAR-derived moraine deformation flag (defer if too hard initially)

**Phase D — Delivery (current Phases 4–5, modified)**
- Static dashboard on Cloudflare Pages (drop Vercel)
- Workers-based API instead of FastAPI/Render (lower complexity, no cold starts)
- Tile-partitioned data for fast dashboard load

**Phase E — Alerts (NEW, the part that justifies the project name)**
- Pipeline emits `alerts.json` with severity, location, downstream exposure
- Follow-up step: diff against previous, post new HIGH alerts to:
  - Auto-created GitHub Issue
  - RSS feed at `alerts.atom`
  - Email via Resend (opt-in subscriber list)
  - Optional: Telegram bot for direct researcher subscription

**Phase F — Validation (NEW, what makes ICIMOD trust it)**
- Notebook: detection precision/recall vs ICIMOD HI-CAP
- Notebook: change detection precision/recall vs published case studies (e.g. Imja, Tsho Rolpa)
- Public report card on the dashboard: "validated against N known lakes; 89% agreement"

**Phase G — Docs (current Phase 7)**
Keep, but reframe explicitly: this is "monitoring + risk-context flags," not GLOF prediction. Be honest about what InSAR/dam-type adds and what it doesn't.

---

## Part 6 — Specific edits to the existing build plan

If you want to keep the current plan structure and just patch it, here are the highest-leverage changes:

1. **Step 2.2 (workflow)**: Switch to a matrix job over AOI tiles. Add a `merge` job that combines tile outputs.
2. **Step 3.1 (dbt)**: Change marts to `incremental`. Add a `snapshots` model. Replace centroid-hash lake_id with spatial-join lookup against a seeded `lakes_master`.
3. **Step 4.2 (deploy)**: Cloudflare Pages instead of Vercel.
4. **Step 5 (API)**: Replace with a Cloudflare Worker — way less code, no cold starts, runs free at scale.
5. **Step 6 (cloud masking)**: Add a `pipeline/gee/sar_detection.py` for Sentinel-1 fallback during cloudy periods.
6. **NEW Step 6.2**: Volume estimate, downstream catchment analysis, dam-type heuristic.
7. **NEW Phase 8 (alerts)**: Notification fan-out (GitHub Issues, RSS, Resend, optional Telegram).
8. **NEW Phase 9 (validation)**: Comparison against ICIMOD HI-CAP with published precision/recall.
9. **Step 7.1 (methodology)**: Reframe as "monitoring + risk-context indicators." Don't claim GLOF prediction.

---

## Part 7 — Honest limits even after all improvements

Even with everything above, some things are out of reach without paid data or field campaigns:
- **Sub-daily monitoring** during a developing GLOF event — needs commercial PlanetScope or in-situ sensors
- **Bathymetry / true volume** — needs field surveys; satellite can only estimate via empirical relations
- **Trigger forecasting** — needs weather/seismic models (free data exists, integration is non-trivial)
- **Real-time** — the lowest-latency workflow described is daily Sentinel-1 + 5-daily Sentinel-2 with ~24h GEE processing lag. That's not "real time."

These are honest limits to disclose to ICIMOD upfront. Saying "weekly monitoring with 24-72h latency, cross-validated against HI-CAP, with downstream-exposure context" is more useful than overpromising.

---

## Bottom line

The current plan builds something **real and useful** but not what the name "GLOF detection" implies. To close that gap on a free stack:

1. Drop Render, move to Cloudflare-first hosting
2. Add Sentinel-1 SAR for monsoon coverage
3. Add volume + downstream-exposure context (free DEMs and OSM)
4. Build actual alert delivery (GH Issues, RSS, email)
5. Validate against ICIMOD HI-CAP and report metrics
6. Be precise in docs: this is monitoring with risk context, not prediction

Each addition is achievable on free tiers. Total effort vs the baseline plan: probably +50% lines of code, +2–3 weeks of work, but it transforms the deliverable from "another lake inventory" into "a defensible monitoring + alert platform you can hand to ICIMOD."
