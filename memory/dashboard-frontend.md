# HimalWatch Dashboard — Frontend Architecture

## Tech
- React 18, in-browser Babel (no build step) — `dashboard/App.jsx`
- MapLibre GL JS v4
- Dark mode by default; toggleable via `.icon-btn` in header
- `ReactDOM.createRoot` (React 18 API)

## Views
1. **Overview** — stat cards (lakes count, area, HIGH alerts, expanding %), fastest
   expanding table, active alerts list
2. **Map** — MapLibre satellite/topo, lake dots coloured by alert severity, click →
   detail panel
3. **Lake List** — sortable/filterable table across all tiles
4. **Alerts** — cards for all lakes with ≥15% area change

## Key Components / State

### Lake naming (`lakeName()`)
Priority order:
1. NAMED_LAKE_DB proximity match — 35 named lakes, 0.025° (~2.5 km) radius
2. Elevation fallback — `"{TileLabel} · {elevation}m"` (e.g. "Khumbu · 5254m")

NAMED_LAKE_DB includes: Imja Tsho, Phoksundo Tsho (lat 29.210, lon 82.958),
Tilicho Lake (lat 28.683, lon 83.817), Tsho Rolpa (lat 27.860, lon 86.492),
Ngozumpa, Dudh Pokhari, Mirlung Tsho, Langshisha Tsho, Shalbachum Tsho,
Yala Glacier Lake, Yamatari Tsho, Darchula Tsho, Thulagi Lake, Chhulung Tsho,
and ~21 others across all 6 tiles.

### R2 + DEMO blend (`transformR2Lakes()`)
- Fetches mart Parquet from R2 (only Khumbu tile has real 2024 data as of 2026-04-29)
- Missing tiles filled from DEMO_LAKES (hardcoded representative lakes)
- `_source: "demo"` flag on filled entries

### Map race condition fix
`map.isStyleLoaded()` check + `map.once("load", doUpdate)` fallback. Without this,
R2 data arrives before MapLibre style loads → `setData()` silently dropped → map
shows DEMO_LAKES while list shows R2, IDs don't match → map click finds nothing.

### Detail panel
- Slides in from right with CSS transform (translateX 360px = closed, 0 = open)
- Close button class: `.detail-close`
- As of 2026-04-30, only mounted when a lake is selected; close button has an accessible label
- Shows: name, lake_id, tile, area (ha), area change %, volume, elevation, detection
  count, last observed date, 7-year area trend chart (SVG)
- Opened by: clicking a lake row in Lake List, OR clicking a map dot

### Logo / home navigation
- `.hdr-brand` button — `onClick → setView("overview"); setSelected(null)`
- Inline style needed to preserve text color in dark mode:
  `color:"inherit", fontFamily:"inherit"` (browsers strip color from button elements)

## Known Issues / Decisions
- Small unnamed Khumbu ponds show elevation fallback names — expected; ~75 real
  detections from GEE are genuinely unnamed glacial ponds 1–8 ha
- Phoksundo Tsho NAMED_LAKE_DB coords: lat 29.210, lon 82.958 (centroid, not tip)
  Will self-correct once GEE runs for far_west tile populate R2
- In-browser Babel warning is expected in local/dev because the dashboard is a no-build SPA

## Files
- `dashboard/App.jsx` — entire React app (single file)
- `dashboard/index.html` — CDN imports (React, Babel, MapLibre, DuckDB-Wasm)
- `dashboard/app.css` — theme variables, layout
- `vercel.json` — `outputDirectory:"dashboard"`, SPA rewrite, no framework/build
