# HimalWatch — UI Validation — 2026-04-30

## Scope
- Local browser smoke test at `http://127.0.0.1:3000`
- Codebase checks using bundled Python runtime plus repo `.venv` site-packages
- Source-of-truth docs used during this pass: `AGENTS.md` and `CLAUDE.md`

## Browser Smoke Test
- App loads successfully from local `python -m http.server 3000 --directory dashboard`
- Main nav works: Overview, Map, Lake List, Alerts
- Lake row click opens detail panel
- Theme toggle works (dark ↔ light)
- Map style toggle works (Satellite ↔ Topo)
- Header brand click returns to Overview
- Browser console clean except expected Babel standalone warning from CDN dev setup

## Dashboard Issues Found
1. Detail close button had no accessible name
2. Detail panel stayed mounted in DOM even when "closed" because fallback lake content was always rendered

## Dashboard Fix Applied
- File: `dashboard/App.jsx`
- `DetailPanel` now returns `null` when no lake is selected
- Removed `fallbackLake` behavior so hidden detail content no longer remains in the DOM
- Added `aria-label="Close details"` to the close button
- Added dialog semantics on the open detail panel container

## Code Validation Results
- `compileall pipeline dbt` passed
- `pipeline/gee/lake_detection.py --help` passed when `PYTHONPATH` includes `pipeline`
- `pipeline/gee/export_to_r2.py --help` passed

## Runtime / Environment Caveats
- Repo `.venv` launcher executables are not directly usable in sandbox because they point at host Python path
- Working workaround: bundled runtime at
  `C:\Users\bikal\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
  with `PYTHONPATH` set to repo `.venv\Lib\site-packages`

## dbt Status
- `dbt test` initially blocked until env vars were loaded from repo `.env`
- With env vars present, normal run hit Windows multiprocessing sandbox issue:
  `PermissionError: [WinError 5] Access is denied`
- `dbt test --single-threaded` progressed further but failed with:
  `TransactionContext Error: cannot start a transaction within a transaction`
- Treat dbt test path as still needing follow-up; not yet a clean pass

## Repo Shape Notes
- This checkout does not currently include a local `api/` directory even though top-level docs describe one
- Memory docs and repo docs contain some encoding artifacts from prior saves/reads (`â€”`, `â†’`, etc.)
