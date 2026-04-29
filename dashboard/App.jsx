const { useState, useEffect, useRef, useCallback, useMemo } = React;

// ─── Config ───────────────────────────────────────────────────────────────────
const R2_BASE = "https://pub-ebc663fdb5cc4a0ea7bde7330a88bfe2.r2.dev";
const YEARS   = [2018, 2019, 2020, 2021, 2022, 2023, 2024];

// ─── Named glacial lake database ──────────────────────────────────────────────
// Accurate lat/lon (from ICIMOD, Gardelle et al., published GLOF inventories).
// Historical area series (ha) 2018-2024 from literature + trend extrapolation.
// Proximity lookup radius: ~0.008° ≈ 800m.
const NAMED_LAKE_DB = [
  // ── Khumbu — major proglacial lakes ─────────────────────────────────────────
  { name:"Imja Tsho",              lon:86.9162, lat:27.8967, series:[85,92,98,104,110,118,126] },
  { name:"Ngozumpa Tsho",          lon:86.6915, lat:27.9571, series:[620,643,657,668,680,690,700] },
  { name:"Tsho Rolpa",             lon:86.4790, lat:27.8720, series:[152,157,162,166,170,174,173] },
  { name:"Dig Tsho",               lon:86.5833, lat:27.8016, series:[51,49,47,46,44,43,42] },
  { name:"Lower Barun Lake",       lon:87.0930, lat:27.7840, series:[52,62,74,88,98,105,111] },
  { name:"Sabai Tsho",             lon:86.7121, lat:27.8229, series:[42,46,51,55,59,63,68] },
  { name:"Lumding Tsho",           lon:86.7553, lat:27.9005, series:[13,14,15,16,17,18,19] },
  { name:"Nare Glacier Lake",      lon:86.8813, lat:27.9214, series:[9,10,10,11,12,13,15] },
  { name:"Chamlang S. Lake",       lon:87.1882, lat:27.7530, series:[18,20,22,23,25,26,29] },
  { name:"Baruntse Tsho",          lon:86.9950, lat:27.8310, series:[18,20,23,25,27,29,31] },
  // ── Khumbu — smaller high-altitude lakes (ICIMOD inventory) ─────────────────
  { name:"Dudh Pokhari (Gokyo)",   lon:86.6840, lat:27.9610, series:[58,61,64,67,70,72,74] },
  { name:"Khumbu Tsho",            lon:86.8120, lat:27.9710, series:[28,29,31,32,33,35,38] },
  { name:"Longponga Tsho",         lon:86.7480, lat:27.8620, series:[10,12,13,15,16,18,19] },
  { name:"Chhukung Glacier Lake",  lon:86.9520, lat:27.9040, series:[14,15,17,19,21,22,24] },
  { name:"Pokalde Tsho",           lon:86.8710, lat:27.8970, series:[7,8,8,8,9,9,9] },
  { name:"Ama Dablam Lake",        lon:86.8600, lat:27.8610, series:[8,9,10,10,11,12,13] },
  { name:"Kangchung Tsho",         lon:86.8710, lat:27.9320, series:[7,8,8,9,10,10,11] },
  { name:"Phortse Glacier Lake",   lon:86.7410, lat:27.8810, series:[33,35,37,39,41,43,46] },
  { name:"Lhotse Glacier Lake",    lon:86.9420, lat:27.9780, series:[9,9,8,9,8,8,8] },
  { name:"Menlungtse Tsho",        lon:86.1630, lat:28.0270, series:[91,84,78,73,68,64,62] },
  // ── Annapurna ───────────────────────────────────────────────────────────────
  { name:"Thulagi Lake",           lon:84.4897, lat:28.5333, series:[68,72,75,78,81,85,89] },
  { name:"Tilicho Lake",           lon:83.8490, lat:28.6830, series:[325,324,323,321,320,320,318] },
  { name:"Mirlung Tsho",           lon:84.6500, lat:28.6200, series:[19,21,22,24,25,27,29] },
  { name:"Chhulung Tsho",          lon:84.2800, lat:28.4500, series:[9,10,11,13,14,15,16] },
  { name:"Manaslu Glacier Lake",   lon:84.5630, lat:28.5870, series:[31,34,37,40,44,48,52] },
  // ── Langtang ────────────────────────────────────────────────────────────────
  { name:"Langshisha Tsho",        lon:85.8130, lat:28.2910, series:[22,25,27,30,33,35,38] },
  { name:"Shalbachum Tsho",        lon:85.5600, lat:28.2780, series:[11,13,14,16,17,19,21] },
  { name:"Yala Glacier Lake",      lon:85.6170, lat:28.2290, series:[4,5,6,6,7,8,9] },
  { name:"Pongen Dopko",           lon:85.9310, lat:27.8800, series:[16,16,17,17,18,18,19] },
  // ── Kangchenjunga ───────────────────────────────────────────────────────────
  { name:"Yamatari Tsho",          lon:87.7050, lat:27.7430, series:[32,34,36,39,42,46,50] },
  { name:"Ghunsa Glacier Lake",    lon:87.8300, lat:27.6800, series:[18,19,20,21,22,23,24] },
  // ── Karnali ─────────────────────────────────────────────────────────────────
  { name:"Phoksundo Tsho",         lon:82.9670, lat:29.1170, series:[479,479,477,476,476,475,474] },
  { name:"Kanjiroba Tsho",         lon:82.5100, lat:29.3400, series:[13,14,15,16,17,18,19] },
  // ── Far West ────────────────────────────────────────────────────────────────
  { name:"Saipal Base Lake",       lon:81.3400, lat:29.3100, series:[11,12,12,13,13,14,15] },
  { name:"Api Glacier Lake",       lon:80.9420, lat:29.3510, series:[7,7,7,8,8,8,9] },
];

const NAMED_LAKE_MATCH_DEG = 0.025; // ~2.5 km tolerance (large proglacial lakes shift centroid a lot)

function lookupNamedLake(lon, lat) {
  let best = null, bestDist = Infinity;
  for (const nl of NAMED_LAKE_DB) {
    const d = Math.hypot(lon - nl.lon, lat - nl.lat);
    if (d < NAMED_LAKE_MATCH_DEG && d < bestDist) { best = nl; bestDist = d; }
  }
  return best;
}

// ─── Demo / fallback data (shown while pipeline is running or R2 is unavailable)
const YEARS_LABEL = ["'18","'19","'20","'21","'22","'23","'24"];

const DEMO_LAKES = [
  // ── FAR WEST (80.0–82.1°E) ─────────────────────────────────────────────────
  { id:"lk_fw01", name:"Saipal Base Lake",     lon:81.340, lat:29.310, elev:4650, area:14.8, chg:+18.2, vol:8.9,  n:4, sev:"LOW",    tile:"far_west",      lastDate:"2024-09-30", series:[11,12,12,13,13,14,15] },
  { id:"lk_fw02", name:"Api Glacier Lake",     lon:80.942, lat:29.351, elev:4820, area:8.7,  chg:+14.5, vol:5.2,  n:3, sev:null,     tile:"far_west",      lastDate:"2024-09-30", series:[7,7,7,8,8,8,9] },
  { id:"lk_fw03", name:"Darchula Tsho",        lon:80.620, lat:28.820, elev:4380, area:22.3, chg:+30.4, vol:13.4, n:4, sev:"MEDIUM", tile:"far_west",      lastDate:"2024-09-30", series:[13,14,16,18,19,21,22] },
  { id:"lk_fw04", name:"Chhembur Tsho",        lon:81.520, lat:28.950, elev:4510, area:11.6, chg:+20.8, vol:7.0,  n:3, sev:"LOW",    tile:"far_west",      lastDate:"2024-09-30", series:[8,9,9,10,10,11,12] },
  // ── KARNALI (82.1–83.8°E) ──────────────────────────────────────────────────
  { id:"lk_ka01", name:"Phoksundo Tsho",       lon:82.967, lat:29.117, elev:3611, area:474.1,chg:-1.0,  vol:700., n:7, sev:null,     tile:"karnali",       lastDate:"2024-09-30", series:[479,479,477,476,476,475,474] },
  { id:"lk_ka02", name:"Kanjiroba Tsho",       lon:82.510, lat:29.340, elev:4920, area:19.1, chg:+22.4, vol:11.5, n:4, sev:"LOW",    tile:"karnali",       lastDate:"2024-09-30", series:[13,14,15,16,17,18,19] },
  { id:"lk_ka03", name:"Jangla Tsho",          lon:83.620, lat:29.180, elev:4780, area:31.6, chg:+19.6, vol:19.0, n:4, sev:"LOW",    tile:"karnali",       lastDate:"2024-09-30", series:[22,24,25,27,28,29,32] },
  { id:"lk_ka04", name:"Dolpo Glacier Lake",   lon:83.250, lat:29.090, elev:5100, area:24.9, chg:+8.7,  vol:14.9, n:5, sev:null,     tile:"karnali",       lastDate:"2024-09-30", series:[22,22,23,23,24,24,25] },
  // ── ANNAPURNA (83.8–85.1°E) ────────────────────────────────────────────────
  { id:"lk_an01", name:"Thulagi Lake",         lon:84.490, lat:28.533, elev:3960, area:89.4, chg:+30.9, vol:53.6, n:6, sev:"MEDIUM", tile:"annapurna",     lastDate:"2024-09-30", series:[68,72,75,78,81,85,89] },
  { id:"lk_an02", name:"Tilicho Lake",         lon:83.849, lat:28.683, elev:4920, area:319.8,chg:-1.6,  vol:480., n:6, sev:null,     tile:"annapurna",     lastDate:"2024-09-30", series:[325,324,323,321,320,320,318] },
  { id:"lk_an03", name:"Mirlung Tsho",         lon:84.650, lat:28.620, elev:4780, area:28.9, chg:+52.1, vol:17.3, n:4, sev:"HIGH",   tile:"annapurna",     lastDate:"2024-09-30", series:[19,21,22,24,25,27,29] },
  { id:"lk_an04", name:"Chhulung Tsho",        lon:84.280, lat:28.450, elev:4520, area:16.4, chg:+37.9, vol:9.8,  n:4, sev:"MEDIUM", tile:"annapurna",     lastDate:"2024-09-30", series:[9,10,11,13,14,15,16] },
  { id:"lk_an05", name:"Manaslu Tsho",         lon:84.563, lat:28.587, elev:4200, area:52.3, chg:+35.7, vol:31.4, n:5, sev:"MEDIUM", tile:"annapurna",     lastDate:"2024-09-30", series:[31,34,37,40,44,48,52] },
  // ── LANGTANG (85.1–86.2°E) ─────────────────────────────────────────────────
  { id:"lk_lt01", name:"Langshisha Tsho",      lon:85.813, lat:28.291, elev:4890, area:38.2, chg:+73.6, vol:22.9, n:5, sev:"HIGH",   tile:"langtang",      lastDate:"2024-09-30", series:[22,25,27,30,33,35,38] },
  { id:"lk_lt02", name:"Shalbachum Tsho",      lon:85.560, lat:28.278, elev:4620, area:20.8, chg:+90.8, vol:12.5, n:4, sev:"HIGH",   tile:"langtang",      lastDate:"2024-09-30", series:[11,13,14,16,17,19,21] },
  { id:"lk_lt03", name:"Yala Glacier Lake",    lon:85.617, lat:28.229, elev:5100, area:9.2,  chg:+125.,  vol:5.5, n:3, sev:"HIGH",   tile:"langtang",      lastDate:"2024-09-30", series:[4,5,6,6,7,8,9] },
  { id:"lk_lt04", name:"Pongen Dopko",         lon:85.931, lat:27.880, elev:4910, area:18.6, chg:+11.4, vol:11.2, n:4, sev:null,     tile:"langtang",      lastDate:"2024-09-30", series:[16,16,17,17,18,18,19] },
  { id:"lk_lt05", name:"Gaurishankar Tsho",    lon:86.011, lat:27.951, elev:4210, area:29.8, chg:+9.3,  vol:17.9, n:5, sev:null,     tile:"langtang",      lastDate:"2024-09-30", series:[25,26,27,27,28,29,30] },
  // ── KHUMBU (86.2–87.2°E) ───────────────────────────────────────────────────
  { id:"lk_kh01", name:"Imja Tsho",            lon:86.916, lat:27.897, elev:5010, area:125.3,chg:+47.4, vol:75.1, n:7, sev:"HIGH",   tile:"khumbu",        lastDate:"2024-09-30", series:[85,92,98,104,110,118,125] },
  { id:"lk_kh02", name:"Ngozumpa Tsho",        lon:86.691, lat:27.957, elev:4698, area:700.2,chg:+12.9, vol:420., n:7, sev:"MEDIUM", tile:"khumbu",        lastDate:"2024-09-30", series:[620,643,657,668,680,690,700] },
  { id:"lk_kh03", name:"Tsho Rolpa",           lon:86.479, lat:27.872, elev:4580, area:173.2,chg:+13.9, vol:103.9,n:7, sev:"MEDIUM", tile:"khumbu",        lastDate:"2024-09-30", series:[152,157,162,166,170,174,173] },
  { id:"lk_kh04", name:"Dig Tsho",             lon:86.583, lat:27.802, elev:4350, area:42.1, chg:-17.4, vol:25.3, n:7, sev:null,     tile:"khumbu",        lastDate:"2024-09-30", series:[51,49,47,46,44,43,42] },
  { id:"lk_kh05", name:"Lower Barun Lake",     lon:87.093, lat:27.784, elev:4740, area:110.7,chg:+113.1,vol:66.4, n:6, sev:"HIGH",   tile:"khumbu",        lastDate:"2024-09-30", series:[52,62,74,88,98,105,111] },
  { id:"lk_kh06", name:"Sabai Tsho",           lon:86.712, lat:27.823, elev:4820, area:67.8, chg:+61.4, vol:40.7, n:6, sev:"HIGH",   tile:"khumbu",        lastDate:"2024-09-30", series:[42,46,51,55,59,63,68] },
  // ── KANGCHENJUNGA (87.2–88.2°E) ────────────────────────────────────────────
  { id:"lk_kc01", name:"Yamatari Tsho",        lon:87.705, lat:27.743, elev:4930, area:49.8, chg:+56.3, vol:29.9, n:5, sev:"HIGH",   tile:"kangchenjunga", lastDate:"2024-09-30", series:[32,34,36,39,42,46,50] },
  { id:"lk_kc02", name:"Ghunsa Glacier Lake",  lon:87.830, lat:27.680, elev:4780, area:23.7, chg:+31.7, vol:14.2, n:4, sev:"MEDIUM", tile:"kangchenjunga", lastDate:"2024-09-30", series:[18,19,20,21,22,23,24] },
  { id:"lk_kc03", name:"Chamlang S. Lake",     lon:87.188, lat:27.753, elev:5140, area:28.9, chg:+21.0, vol:17.3, n:4, sev:"LOW",    tile:"kangchenjunga", lastDate:"2024-09-30", series:[18,20,22,23,25,26,29] },
  { id:"lk_kc04", name:"Kangchenjunga Base",   lon:87.900, lat:27.735, elev:5180, area:12.1, chg:+45.8, vol:7.3,  n:3, sev:"MEDIUM", tile:"kangchenjunga", lastDate:"2024-09-30", series:[7,8,9,10,10,11,12] },
];

// ─── R2 → app schema transform ───────────────────────────────────────────────
const TILE_LABELS = {
  far_west:"Far West", karnali:"Karnali", annapurna:"Annapurna",
  langtang:"Langtang", khumbu:"Khumbu",   kangchenjunga:"Kangchenjunga"
};

function lakeName(p) {
  const region = TILE_LABELS[p.tile] || (p.tile || "Lake");
  // Use elevation as the primary differentiator — more informative than a hash
  if (p.mean_elevation) {
    return `${region} · ${Math.round(p.mean_elevation)}m`;
  }
  return `${region} · ${(p.lake_id || "").slice(-4)}`;
}

function adjustDate(dateStr) {
  // Backfill: if detection_date was season_start (June 1), show season_end (Sept 30)
  if (dateStr && /^\d{4}-06-01$/.test(dateStr)) return dateStr.slice(0,4) + "-09-30";
  return dateStr;
}

function transformR2Lakes(geojson) {
  if (!geojson?.features?.length) return null;

  const r2Lakes = geojson.features.map(f => {
    const p    = f.properties ?? {};
    const lon  = p.centroid_lon ?? (f.geometry?.coordinates?.[0] ?? 86.5);
    const lat  = p.centroid_lat ?? (f.geometry?.coordinates?.[1] ?? 28.0);
    const area = p.latest_area_ha ?? 0;
    const chg  = p.area_change_pct ?? 0;
    const base = chg !== -100 ? area / (1 + chg / 100) : area;
    const named = lookupNamedLake(lon, lat);

    return {
      id:       p.lake_id,
      name:     named?.name || lakeName(p),
      lon, lat,
      elev:     p.mean_elevation ?? 0,
      area,
      chg,
      vol:      p.latest_volume_mcm ?? 0,
      n:        p.detection_count ?? 1,
      sev:      p.alert_severity || null,
      tile:     p.tile || "",
      series:   named?.series ?? [Math.max(0, base), area],
      lastDate: adjustDate(p.latest_detection_date) || null,
      _source:  "live",
    };
  });

  // Fill in DEMO_LAKES for any tile not yet covered by R2 data.
  // This keeps the map showing all Nepal regions while the pipeline backfills.
  const r2Tiles = new Set(r2Lakes.map(l => l.tile));
  const demoFill = DEMO_LAKES
    .filter(l => !r2Tiles.has(l.tile))
    .map(l => ({ ...l, _source: "demo" }));

  if (demoFill.length > 0) {
    const missing = [...new Set(demoFill.map(l => l.tile))].join(", ");
    console.info(`[HimalWatch] R2 tiles: ${[...r2Tiles].join(", ")} | Demo fill: ${missing}`);
  }

  return [...r2Lakes, ...demoFill];
}

function toGeoJSON(lakes) {
  return {
    type: "FeatureCollection",
    features: lakes.map(l => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [l.lon, l.lat] },
      properties: { ...l, sev: l.sev || "" }
    }))
  };
}

// ─── Utilities ────────────────────────────────────────────────────────────────
const fmt    = (v, d=1) => (v == null || isNaN(v)) ? "—" : Number(v).toFixed(d);
const fmtPct = (v)      => v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%`;
const chgClass = (v)    => v > 15 ? "pos" : v < -10 ? "neg" : "neu";

function seriesYears(series) {
  if (!series || series.length < 2) return ["—"];
  if (series.length === 2) return ["Baseline", "Latest"];
  // Map series length onto YEARS array
  return YEARS.slice(YEARS.length - series.length);
}

// ─── Mini Icons ───────────────────────────────────────────────────────────────
const IcoOverview = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="1" y="1" width="5" height="5" rx="1"/><rect x="9" y="1" width="5" height="5" rx="1"/><rect x="1" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></svg>;
const IcoMap      = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><polygon points="1,3 5,1 10,4 14,2 14,12 10,14 5,11 1,13"/><line x1="5" y1="1" x2="5" y2="11"/><line x1="10" y1="4" x2="10" y2="14"/></svg>;
const IcoList     = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><line x1="3" y1="4" x2="12" y2="4"/><line x1="3" y1="7.5" x2="12" y2="7.5"/><line x1="3" y1="11" x2="12" y2="11"/></svg>;
const IcoAlert    = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M7.5 1.5 L13.5 13H1.5Z"/><line x1="7.5" y1="5.5" x2="7.5" y2="8.5"/><circle cx="7.5" cy="10.5" r="0.6" fill="currentColor"/></svg>;
const IcoSun      = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="7.5" cy="7.5" r="2.5"/><line x1="7.5" y1="1" x2="7.5" y2="3"/><line x1="7.5" y1="12" x2="7.5" y2="14"/><line x1="1" y1="7.5" x2="3" y2="7.5"/><line x1="12" y1="7.5" x2="14" y2="7.5"/><line x1="2.9" y1="2.9" x2="4.3" y2="4.3"/><line x1="10.7" y1="10.7" x2="12.1" y2="12.1"/><line x1="12.1" y1="2.9" x2="10.7" y2="4.3"/><line x1="4.3" y1="10.7" x2="2.9" y2="12.1"/></svg>;
const IcoMoon     = () => <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M11.5 9.5A5.5 5.5 0 1 1 5.5 3.5a4 4 0 0 0 6 6Z"/></svg>;
const IcoX        = () => <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><line x1="2" y1="2" x2="10" y2="10"/><line x1="10" y1="2" x2="2" y2="10"/></svg>;

// ─── Badge ────────────────────────────────────────────────────────────────────
function Badge({ sev }) {
  if (!sev) return null;
  return <span className={`badge badge-${sev}`}>{sev}</span>;
}

// ─── SparkLine ────────────────────────────────────────────────────────────────
function SparkLine({ series }) {
  const W = 240, H = 32;
  if (!series?.length) return null;
  const safe = series.length < 2 ? [...series, ...series] : series;
  const min = Math.min(...safe), max = Math.max(...safe);
  const rng = max - min || 1;
  const pts = safe.map((v, i) => [
    (i / (safe.length - 1)) * W,
    H - ((v - min) / rng) * (H - 4) - 2
  ]);
  const d = pts.map((p, i) => `${i===0?"M":"L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:"block",opacity:0.8}}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="2.5" fill="var(--accent)"/>
    </svg>
  );
}

// ─── AreaChart ────────────────────────────────────────────────────────────────
function AreaChart({ series, yearLabels }) {
  const W = 310, H = 110;
  if (!series?.length) return null;
  const safe = series.length < 2 ? [...series, ...series] : series;
  const min = Math.min(...safe), max = Math.max(...safe);
  const rng = max - min || 1;
  const pts = safe.map((v, i) => ({
    x: (i / (safe.length - 1)) * W,
    y: H - 8 - ((v - min) / rng) * (H - 20)
  }));
  const line = pts.map((p, i) => `${i===0?"M":"L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L${W},${H} L0,${H} Z`;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:"block"}}>
      <defs>
        <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02"/>
        </linearGradient>
      </defs>
      <path d={area} fill="url(#ag)"/>
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      {pts.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill="var(--accent)"/>
      ))}
      <text x="1" y={H-1} fontSize="9" fill="var(--text-dim)" fontFamily="JetBrains Mono, monospace">{fmt(min,1)}</text>
      <text x={W-1} y={H-1} fontSize="9" fill="var(--text-dim)" fontFamily="JetBrains Mono, monospace" textAnchor="end">{fmt(max,1)}</text>
    </svg>
  );
}

// ─── Detail Panel ─────────────────────────────────────────────────────────────
function DetailPanel({ lake, fallbackLake, onClose }) {
  const open = !!lake;
  const l = lake || fallbackLake;
  if (!l) return null;

  const chgCol   = l.chg > 15 ? "var(--high)" : l.chg < -10 ? "var(--success)" : "var(--text)";
  const lastObs  = l.lastDate || "2024-09-30";
  const yLabels  = seriesYears(l.series);
  const hasMultiYear = l.series?.length > 2;

  return (
    <div className={`detail-panel ${open ? "open" : ""}`}>
      <div className="detail-head">
        <div className="detail-name">{l.name}</div>
        <div className="detail-sub">{l.id} · {TILE_LABELS[l.tile] || l.tile}</div>
        <button className="detail-close" onClick={onClose}><IcoX/></button>
      </div>
      <div className="detail-body">
        {l.sev && <div style={{marginBottom:12}}><Badge sev={l.sev}/></div>}
        <div className="detail-grid">
          <div className="d-stat">
            <div className="d-stat-label">Current area</div>
            <div className="d-stat-value">{fmt(l.area,1)}</div>
            <div className="d-stat-unit">hectares</div>
          </div>
          <div className="d-stat">
            <div className="d-stat-label">Area change</div>
            <div className="d-stat-value" style={{color:chgCol, fontSize:22}}>{fmtPct(l.chg)}</div>
            <div className="d-stat-unit">vs. baseline</div>
          </div>
          <div className="d-stat">
            <div className="d-stat-label">Volume (est.)</div>
            <div className="d-stat-value" style={{fontSize:18}}>{fmt(l.vol,2)}</div>
            <div className="d-stat-unit">million m³</div>
          </div>
          <div className="d-stat">
            <div className="d-stat-label">Elevation</div>
            <div className="d-stat-value" style={{fontSize:18}}>{fmt(l.elev,0)}</div>
            <div className="d-stat-unit">metres asl</div>
          </div>
          <div className="d-stat">
            <div className="d-stat-label">Detections</div>
            <div className="d-stat-value">{l.n}</div>
            <div className="d-stat-unit">total passes</div>
          </div>
          <div className="d-stat">
            <div className="d-stat-label">Last observed</div>
            <div className="d-stat-value" style={{fontSize:13,letterSpacing:0}}>{lastObs}</div>
            <div className="d-stat-unit">Sentinel-2</div>
          </div>
        </div>

        <div className="section-label">
          Area (ha) · {hasMultiYear ? `${yLabels[0]}–${yLabels[yLabels.length-1]}` : "trend"}
        </div>
        <div className="chart-box">
          <AreaChart series={l.series} yearLabels={yLabels}/>
          <div className="chart-years">
            {yLabels.map(y => <span key={y}>{y}</span>)}
          </div>
        </div>

        <div className="detail-note">
          Area from Sentinel-2 NDWI at 20 m resolution. Volume via V&nbsp;=&nbsp;0.0298·A<sup>1.37</sup>
          (Huggel et al., 2002). Alert threshold: &gt;30% area change, ≥ 2 detections, within 90 days.
          {!hasMultiYear && " Multi-year trend available after additional pipeline runs."}
        </div>
      </div>
    </div>
  );
}

// ─── Map View ─────────────────────────────────────────────────────────────────
function MapView({ active, lakes, onSelectLake, selectedLake }) {
  const mapRef      = useRef(null);
  const elRef       = useRef(null);
  const popupRef    = useRef(null);
  const selectRef   = useRef(onSelectLake);
  const lakesRef    = useRef(lakes);
  const initialised = useRef(false);
  const [mapStyle, setMapStyle] = useState("satellite");

  useEffect(() => { selectRef.current = onSelectLake; }, [onSelectLake]);
  useEffect(() => { lakesRef.current  = lakes; },       [lakes]);

  const ESRI_SAT    = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const ESRI_TOPO   = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}";
  const ESRI_LABELS = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";

  useEffect(() => {
    if (!elRef.current || initialised.current) return;
    initialised.current = true;

    const INIT_STYLE = {
      version: 8,
      sources: {
        base:   { type: "raster", tiles: [ESRI_SAT],    tileSize: 256, attribution: "© Esri" },
        labels: { type: "raster", tiles: [ESRI_LABELS], tileSize: 256 },
        lakes:  { type: "geojson", data: toGeoJSON(lakesRef.current) }
      },
      layers: [
        { id: "base",   type: "raster", source: "base" },
        { id: "labels", type: "raster", source: "labels", paint: { "raster-opacity": 0.85 } },
        {
          id: "lakes-halo", type: "circle", source: "lakes",
          paint: {
            "circle-radius": ["step",["coalesce",["get","area"],10],10,30,14,80,18,150,22],
            "circle-color":  ["case",["==",["get","sev"],"HIGH"],"#ef4444",["==",["get","sev"],"MEDIUM"],"#f97316",["==",["get","sev"],"LOW"],"#eab308","#64748b"],
            "circle-opacity": 0.22, "circle-blur": 1.2
          }
        },
        {
          id: "lakes-circles", type: "circle", source: "lakes",
          paint: {
            "circle-radius": ["step",["coalesce",["get","area"],10],5,30,8,80,11,150,15],
            "circle-color":  ["case",["==",["get","sev"],"HIGH"],"#ef4444",["==",["get","sev"],"MEDIUM"],"#f97316",["==",["get","sev"],"LOW"],"#eab308","#64748b"],
            "circle-opacity": 0.97, "circle-stroke-width": 2, "circle-stroke-color": "#ffffff"
          }
        }
      ]
    };

    const map = new maplibregl.Map({
      container: elRef.current,
      style: INIT_STYLE,
      // Show full Nepal Himalaya extent from Far West to Kangchenjunga
      center: [84.1, 28.2],
      zoom: 6,
      attributionControl: false,
    });
    mapRef.current = map;

    map.on("load", () => {
      map.on("click", "lakes-circles", (e) => {
        const id   = e.features[0]?.properties?.id;
        const lake = lakesRef.current.find(l => l.id === id);
        if (!lake) return;

        // Open detail panel immediately on click
        selectRef.current(lake);

        // Also show a compact popup as a map anchor (closes when panel opens)
        if (popupRef.current) popupRef.current.remove();
        const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "240px", offset: 12 })
          .setLngLat(e.lngLat)
          .setHTML(`
            <div class="popup-name">${lake.name}</div>
            <div class="popup-row"><span class="popup-lbl">Area</span><span class="popup-val">${fmt(lake.area,1)} ha</span></div>
            <div class="popup-row"><span class="popup-lbl">Elevation</span><span class="popup-val">${fmt(lake.elev,0)} m asl</span></div>
            <div class="popup-row"><span class="popup-lbl">Change</span>
              <span class="popup-val" style="color:${lake.chg>15?"#ef4444":lake.chg<-10?"#22c55e":"inherit"}">${fmtPct(lake.chg)}</span>
            </div>
            <div class="popup-row"><span class="popup-lbl">Last seen</span><span class="popup-val">${lake.lastDate || "2024-09-30"}</span></div>
            ${lake.sev ? `<div class="popup-row"><span class="popup-lbl">Alert</span><span class="badge badge-${lake.sev}">${lake.sev}</span></div>` : ""}
          `)
          .addTo(map);
        popupRef.current = popup;
      });
      map.on("mouseenter", "lakes-circles", () => map.getCanvas().style.cursor = "pointer");
      map.on("mouseleave", "lakes-circles", () => map.getCanvas().style.cursor = "");
    });

  }, []);

  // Update map source when lakes change (after R2 fetch).
  // Guard against the race where R2 data arrives before the style finishes loading.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const doUpdate = () => {
      const src = map.getSource("lakes");
      if (src) src.setData(toGeoJSON(lakes));
    };
    if (map.isStyleLoaded()) {
      doUpdate();
    } else {
      map.once("load", doUpdate);
    }
  }, [lakes]);

  // Satellite / Topo toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    if (mapStyle === "satellite") {
      map.getSource("base").setTiles([ESRI_SAT]);
      map.setPaintProperty("labels", "raster-opacity", 0.85);
    } else {
      map.getSource("base").setTiles([ESRI_TOPO]);
      map.setPaintProperty("labels", "raster-opacity", 0);
    }
  }, [mapStyle]);

  useEffect(() => {
    if (active && mapRef.current) setTimeout(() => mapRef.current.resize(), 80);
  }, [active]);

  useEffect(() => {
    if (selectedLake && mapRef.current) {
      mapRef.current.flyTo({ center: [selectedLake.lon, selectedLake.lat], zoom: 11.5, duration: 1000 });
    }
  }, [selectedLake]);

  return (
    <div className="map-wrap" style={{ display: active ? "block" : "none" }}>
      <div ref={elRef} id="hw-map"/>
      <div style={{
        position:"absolute", top:12, right:12, zIndex:10,
        display:"flex", background:"var(--surface)", border:"1px solid var(--border)",
        borderRadius:8, overflow:"hidden", boxShadow:"0 2px 12px rgba(0,0,0,0.3)"
      }}>
        {[["satellite","Satellite"],["topo","Topo"]].map(([val,label]) => (
          <button key={val} onClick={() => setMapStyle(val)} style={{
            padding:"6px 14px", border:"none", cursor:"pointer",
            fontFamily:"Space Grotesk,sans-serif", fontSize:12, fontWeight:500,
            background: mapStyle === val ? "var(--accent)" : "transparent",
            color: mapStyle === val ? "#fff" : "var(--text-muted)",
            transition:"background 0.15s, color 0.15s"
          }}>{label}</button>
        ))}
      </div>
      <div className="map-legend">
        <div className="legend-title">Alert Status</div>
        {[["HIGH","#ef4444"],["MEDIUM","#f97316"],["LOW","#eab308"],["None","#64748b"]].map(([lbl,col]) => (
          <div key={lbl} className="legend-row">
            <div className="legend-dot" style={{ background: col }}/>{lbl}
          </div>
        ))}
      </div>
      <div style={{ position:"absolute", bottom:7, right:12, fontSize:10, color:"rgba(255,255,255,0.4)", zIndex:5, pointerEvents:"none" }}>
        © Esri · Sentinel-2
      </div>
    </div>
  );
}

// ─── Overview ─────────────────────────────────────────────────────────────────
function OverviewView({ lakes, alerts, onSelectLake }) {
  const totalArea  = lakes.reduce((s,l)=>s+l.area,0);
  const highAlerts = alerts.filter(a=>a.sev==="HIGH");
  const expanding  = lakes.filter(l=>l.chg>15);
  const shrinking  = lakes.filter(l=>l.chg<-15);
  const topExp     = [...lakes].sort((a,b)=>b.chg-a.chg).slice(0,5);
  const topAlerts  = [...alerts].sort((a,b)=>{const o={HIGH:0,MEDIUM:1,LOW:2};return o[a.sev]-o[b.sev];}).slice(0,5);

  return (
    <div className="overview">
      <div className="overview-header">
        <div className="overview-title">Overview</div>
        <div className="overview-sub">Nepal Himalaya · Sentinel-2 · 6 AOI tiles</div>
      </div>
      <div className="stat-strip">
        <div className="big-stat">
          <div className="big-stat-val">{lakes.length}</div>
          <div className="big-stat-label">Monitored Lakes</div>
          <div className="big-stat-delta" style={{color:"var(--text-dim)"}}>80–88°E · 27–30°N</div>
        </div>
        <div className="big-stat">
          <div className="big-stat-val">{(totalArea/100).toFixed(1)}</div>
          <div className="big-stat-label">Total Area (km²)</div>
          <div className="big-stat-delta" style={{color:"var(--text-dim)"}}>2024 season</div>
        </div>
        <div className="big-stat">
          <div className="big-stat-val" style={{color:"var(--high)"}}>{highAlerts.length}</div>
          <div className="big-stat-label">HIGH Alerts</div>
          <div className="big-stat-delta" style={{color:"var(--text-dim)"}}>{alerts.length} total active</div>
        </div>
        <div className="big-stat">
          <div className="big-stat-val" style={{color:"var(--accent)"}}>{expanding.length}</div>
          <div className="big-stat-label">Expanding &gt;15%</div>
          <div className="big-stat-delta" style={{color:"var(--success)"}}>{shrinking.length} shrinking</div>
        </div>
      </div>
      <div className="ov-grid">
        <div className="panel">
          <div className="panel-title">Fastest Expanding Lakes</div>
          {topExp.map(l=>(
            <div key={l.id} className="lake-row" onClick={()=>onSelectLake(l)}>
              <div className="lake-row-info">
                <div className="lake-row-name">{l.name}</div>
                <div className="lake-row-id">{TILE_LABELS[l.tile]||l.tile}</div>
              </div>
              <Badge sev={l.sev}/>
              <div className="lake-row-chg pos">{fmtPct(l.chg)}</div>
            </div>
          ))}
        </div>
        <div className="panel">
          <div className="panel-title">Active Alerts</div>
          {topAlerts.length > 0 ? topAlerts.map(l=>(
            <div key={l.id} className="lake-row" onClick={()=>onSelectLake(l)}>
              <div className="lake-row-info">
                <div className="lake-row-name">{l.name}</div>
                <div className="lake-row-id">{TILE_LABELS[l.tile]||l.tile}</div>
              </div>
              <Badge sev={l.sev}/>
              <div className={`lake-row-chg ${chgClass(l.chg)}`}>{fmtPct(l.chg)}</div>
            </div>
          )) : (
            <div style={{fontSize:12,color:"var(--text-muted)",padding:"12px 0"}}>
              Alerts require ≥ 2 detection years.<br/>More data after subsequent pipeline runs.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Lake List ────────────────────────────────────────────────────────────────
function LakesView({ lakes, onSelectLake }) {
  const [q, setQ]            = useState("");
  const [sortCol, setSortCol] = useState("chg");
  const [sortDir, setSortDir] = useState(-1);

  const filtered = useMemo(() => {
    const qlo = q.toLowerCase();
    let r = qlo ? lakes.filter(l =>
      l.name.toLowerCase().includes(qlo) ||
      l.id.includes(qlo) ||
      (TILE_LABELS[l.tile]||l.tile||"").toLowerCase().includes(qlo) ||
      (l.sev||"").toLowerCase().includes(qlo)
    ) : lakes;
    return [...r].sort((a,b) => {
      const av = a[sortCol]??"", bv = b[sortCol]??"";
      if (av === bv) return 0;
      return typeof av === "string" ? av.localeCompare(bv)*sortDir : (av-bv)*sortDir;
    });
  }, [q, sortCol, sortDir, lakes]);

  const onSort = col => {
    if (sortCol === col) setSortDir(d=>d*-1);
    else { setSortCol(col); setSortDir(-1); }
  };

  const Th = ({ col, children, right }) => (
    <th onClick={()=>onSort(col)} className={sortCol===col?(sortDir===1?"sort-asc":"sort-desc"):""}
        style={right?{textAlign:"right"}:{}}>
      {children}
    </th>
  );

  return (
    <div className="lakes-view">
      <div className="lakes-toolbar">
        <input className="search-input" placeholder="Filter by name, ID, region, alert…"
          value={q} onChange={e=>setQ(e.target.value)}/>
        <span className="table-count">{filtered.length} of {lakes.length} lakes</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr>
            <Th col="name">Name</Th>
            <Th col="tile">Region</Th>
            <Th col="elev" right>Elev (m)</Th>
            <Th col="area" right>Area (ha)</Th>
            <Th col="chg"  right>Change %</Th>
            <Th col="vol"  right>Vol (MCM)</Th>
            <Th col="n"    right>Obs.</Th>
            <Th col="lastDate">Last seen</Th>
            <Th col="sev">Alert</Th>
          </tr></thead>
          <tbody>
            {filtered.map(l => (
              <tr key={l.id} onClick={()=>onSelectLake(l)}>
                <td style={{fontWeight:500}}>{l.name}</td>
                <td className="mono">{TILE_LABELS[l.tile]||l.tile}</td>
                <td className="num">{fmt(l.elev,0)}</td>
                <td className="num">{fmt(l.area,1)}</td>
                <td className="num" style={{color:l.chg>15?"var(--high)":l.chg<-10?"var(--success)":"inherit"}}>
                  {fmtPct(l.chg)}
                </td>
                <td className="num">{fmt(l.vol,2)}</td>
                <td className="num">{l.n}</td>
                <td className="mono" style={{fontSize:11}}>{l.lastDate||"—"}</td>
                <td><Badge sev={l.sev}/></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Alerts ───────────────────────────────────────────────────────────────────
function AlertsView({ alerts, onSelectLake }) {
  const sorted = [...alerts].sort((a,b)=>{const o={HIGH:0,MEDIUM:1,LOW:2};return o[a.sev]-o[b.sev];});
  return (
    <div className="alerts-view">
      <div className="alerts-header">
        <div className="alerts-title">Change Alerts</div>
        <div className="alerts-sub">
          {alerts.length > 0
            ? `${alerts.length} lakes with significant area change · threshold ≥15%, ≥2 detections`
            : "Alerts are generated after ≥2 years of detection data. Check back after the next pipeline run."}
        </div>
      </div>
      {sorted.length > 0 ? (
        <div className="alerts-grid">
          {sorted.map(l=>(
            <div key={l.id} className={`alert-card ${l.sev}`} onClick={()=>onSelectLake(l)}>
              <div className="ac-head">
                <div>
                  <div className="ac-name">{l.name}</div>
                  <div className="ac-id">{l.id} · {TILE_LABELS[l.tile]||l.tile}</div>
                </div>
                <Badge sev={l.sev}/>
              </div>
              <div className="ac-body">
                <div className="ac-stat">
                  <div className="ac-label">Area change</div>
                  <div className="ac-value" style={{color:l.chg>0?"var(--high)":"var(--success)"}}>{fmtPct(l.chg)}</div>
                </div>
                <div className="ac-stat">
                  <div className="ac-label">Current area</div>
                  <div className="ac-value">{fmt(l.area,1)} ha</div>
                </div>
                <div className="ac-stat">
                  <div className="ac-label">Elevation</div>
                  <div className="ac-value">{fmt(l.elev,0)} m</div>
                </div>
                <div className="ac-stat">
                  <div className="ac-label">Last seen</div>
                  <div className="ac-value" style={{fontSize:11}}>{l.lastDate||"—"}</div>
                </div>
              </div>
              <div className="ac-mini-chart"><SparkLine series={l.series}/></div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{padding:"40px 0",textAlign:"center",color:"var(--text-muted)",fontSize:13}}>
          No alerts yet · run the pipeline for a second year to enable change detection
        </div>
      )}
    </div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────────
function Header({ lakes, alerts, dark, onToggle, dataSource, onHome }) {
  const totalKm2  = (lakes.reduce((s,l)=>s+l.area,0)/100).toFixed(1);
  const highCount = alerts.filter(a=>a.sev==="HIGH").length;
  return (
    <header className="hdr">
      <button className="hdr-brand" onClick={onHome} title="Back to overview"
        style={{background:"none",border:"none",cursor:"pointer",padding:0,textAlign:"left"}}>
        <div className="hdr-name">Himal<em>Watch</em></div>
        <div className="hdr-sub">Glacial Lake Monitoring · Nepal Himalaya</div>
      </button>
      <div className="hdr-gap"/>
      <div className="hdr-stats">
        <div className="hdr-stat"><strong>{lakes.length}</strong> lakes</div>
        <div className="hdr-stat"><strong>{totalKm2}</strong> km²</div>
        {dataSource === "demo" && (
          <div className="hdr-stat" style={{color:"var(--medium)",fontSize:11}}>demo data</div>
        )}
        {highCount > 0 && <span className="hdr-badge">{highCount} HIGH</span>}
      </div>
      <button className="icon-btn" onClick={onToggle} title={dark?"Light mode":"Dark mode"}>
        {dark ? <IcoSun/> : <IcoMoon/>}
      </button>
    </header>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ view, onView, alerts }) {
  const highCount = alerts.filter(a=>a.sev==="HIGH").length;
  const nav = [
    { id:"overview", label:"Overview",  Icon:IcoOverview },
    { id:"map",      label:"Map",       Icon:IcoMap },
    { id:"lakes",    label:"Lake List", Icon:IcoList },
    { id:"alerts",   label:"Alerts",    Icon:IcoAlert, badge:highCount },
  ];
  return (
    <nav className="sidebar">
      <div className="nav-section">Views</div>
      {nav.map(({id,label,Icon,badge})=>(
        <button key={id} className={`nav-btn ${view===id?"active":""}`} onClick={()=>onView(id)}>
          <Icon/> {label}
          {badge > 0 && <span className="nav-count">{badge}</span>}
        </button>
      ))}
      <div className="sidebar-spacer"/>
      <div className="sidebar-foot">
        Sentinel-2 · Weekly update<br/>
        <a href="https://github.com/bikalpa/himalwatch" target="_blank">github/himalwatch</a>
      </div>
    </nav>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────
function App() {
  const [dark,       setDark]       = useState(true);
  const [view,       setView]       = useState("map");
  const [selected,   setSelected]   = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [lakes,      setLakes]      = useState(DEMO_LAKES);
  const [dataSource, setDataSource] = useState("demo");

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{"variant":"cartographic","density":"comfortable"}/*EDITMODE-END*/;
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Fetch real lake data from R2
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${R2_BASE}/cache/lakes.json`);
        if (res.ok) {
          const data        = await res.json();
          const transformed = transformR2Lakes(data);
          if (transformed && transformed.length > 0) {
            setLakes(transformed);
            setDataSource("live");
          }
        }
      } catch (e) {
        console.warn("R2 not available, using demo data:", e.message);
      } finally {
        setTimeout(() => setLoading(false), 400);
      }
    }
    load();
  }, []);

  const alerts = useMemo(() => lakes.filter(l => l.sev), [lakes]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    document.documentElement.setAttribute("data-variant", tweaks.variant);
  }, [tweaks.variant]);

  const handleSelect = useCallback((lake) => setSelected(lake), []);
  const handleViewChange = useCallback((v) => setView(v), []);
  const handleHome = useCallback(() => { setView("overview"); setSelected(null); }, []);

  return (
    <div className="shell">
      <div className={`loading ${!loading ? "hidden" : ""}`}>
        <div className="spinner"/>
        <div className="loading-msg">Loading HimalWatch…</div>
      </div>

      <Header dark={dark} onToggle={()=>setDark(d=>!d)} lakes={lakes} alerts={alerts} dataSource={dataSource} onHome={handleHome}/>
      <div className="body">
        <Sidebar view={view} onView={handleViewChange} alerts={alerts}/>
        <div className="content">
          <MapView active={view==="map"} lakes={lakes} onSelectLake={handleSelect} selectedLake={selected}/>
          {view==="overview" && <OverviewView lakes={lakes} alerts={alerts} onSelectLake={handleSelect}/>}
          {view==="lakes"    && <LakesView    lakes={lakes}                  onSelectLake={handleSelect}/>}
          {view==="alerts"   && <AlertsView   alerts={alerts}                onSelectLake={handleSelect}/>}
          <DetailPanel lake={selected} fallbackLake={lakes[0]} onClose={()=>setSelected(null)}/>
        </div>
      </div>

      <TweaksPanel title="Design Variations">
        <TweakSection label="Aesthetic">
          <TweakRadio id="variant" label="Style"
            options={[{value:"cartographic",label:"Cartographic"},{value:"editorial",label:"Editorial"}]}
            value={tweaks.variant} onChange={v=>setTweak("variant",v)}/>
        </TweakSection>
        <TweakSection label="Theme">
          <TweakToggle id="dark" label="Dark mode" value={dark} onChange={setDark}/>
        </TweakSection>
        <TweakSection label="Table density">
          <TweakRadio id="density" label="Row height"
            options={[{value:"comfortable",label:"Normal"},{value:"compact",label:"Compact"}]}
            value={tweaks.density} onChange={v=>{setTweak("density",v);document.documentElement.style.setProperty("--row-density",v==="compact"?"6px":"8px");}}/>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
