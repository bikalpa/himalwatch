const { useState, useEffect, useRef, useCallback, useMemo } = React;

// ─── Config ───────────────────────────────────────────────────────────────────
const R2_BASE = "https://pub-ebc663fdb5cc4a0ea7bde7330a88bfe2.r2.dev";
const YEARS   = [2018, 2019, 2020, 2021, 2022, 2023, 2024];

// ─── Demo / fallback data (shown while loading or if R2 has no data yet) ──────
const DEMO_LAKES = [
  { id:"lk_7f3a2b", name:"Imja Tsho",           lon:86.916, lat:27.897, elev:5010, area:125.3, chg:+67.2, vol:75.1,  n:8,  sev:"HIGH",   tile:"khumbu",       series:[42,55,68,79,93,110,125] },
  { id:"lk_9e1c4d", name:"Tsho Rolpa",           lon:86.483, lat:27.873, elev:4580, area:173.2, chg:+42.1, vol:103.9, n:10, sev:"MEDIUM", tile:"khumbu",       series:[85,98,112,128,140,158,173] },
  { id:"lk_2a8f1e", name:"Thulagi Glacier",      lon:84.490, lat:28.533, elev:3960, area: 89.4, chg:+21.8, vol:53.6,  n:6,  sev:"LOW",    tile:"annapurna",    series:[55,60,66,71,77,83,89] },
  { id:"lk_5c3b7a", name:"Lower Barun",          lon:87.091, lat:27.784, elev:4740, area:110.7, chg:+55.3, vol:66.4,  n:7,  sev:"HIGH",   tile:"kangchenjunga",series:[38,48,60,72,83,98,111] },
  { id:"lk_8d4e2f", name:"Dig Tsho",             lon:86.583, lat:27.801, elev:4350, area: 42.1, chg:-18.3, vol:25.3,  n:5,  sev:null,     tile:"khumbu",       series:[52,50,49,47,46,44,42] },
  { id:"lk_1b6a9c", name:"Sabai Tsho",           lon:86.712, lat:27.823, elev:4820, area: 67.8, chg:+31.4, vol:40.7,  n:6,  sev:"MEDIUM", tile:"khumbu",       series:[38,42,48,53,58,63,68] },
  { id:"lk_3f2d8b", name:"Chamlang South",       lon:87.188, lat:27.753, elev:5140, area: 28.9, chg:+19.2, vol:17.3,  n:4,  sev:"LOW",    tile:"kangchenjunga",series:[18,20,22,23,25,27,29] },
  { id:"lk_6e7f1a", name:"Dudh Pokhari",         lon:86.621, lat:27.849, elev:4598, area: 93.2, chg:+28.7, vol:55.9,  n:8,  sev:"LOW",    tile:"khumbu",       series:[58,64,70,76,81,87,93] },
  { id:"lk_4c8b3e", name:"Nare Glacier Lake",    lon:86.881, lat:27.921, elev:5380, area: 14.7, chg:+73.1, vol:8.8,   n:3,  sev:"HIGH",   tile:"khumbu",       series:[5,7,8,10,11,13,15] },
  { id:"lk_0a9d7c", name:"Lhotse Glacier Lake",  lon:86.942, lat:27.978, elev:5520, area:  8.3, chg: -5.2, vol:5.0,   n:4,  sev:null,     tile:"khumbu",       series:[9,9,8,9,8,8,8] },
  { id:"lk_2f5e4b", name:"Makalu Base Lake",     lon:87.083, lat:27.851, elev:5020, area: 22.1, chg:+44.4, vol:13.3,  n:5,  sev:"MEDIUM", tile:"kangchenjunga",series:[10,12,14,17,19,21,22] },
  { id:"lk_7a1c6d", name:"Baruntse Tsho",        lon:86.995, lat:27.831, elev:5190, area: 31.4, chg:+61.5, vol:18.8,  n:4,  sev:"HIGH",   tile:"khumbu",       series:[12,15,18,22,26,29,31] },
  { id:"lk_9b3e2f", name:"Rolwaling East",       lon:86.351, lat:27.882, elev:4910, area: 18.6, chg: +8.1, vol:11.2,  n:6,  sev:null,     tile:"langtang",     series:[16,16,17,17,18,18,19] },
  { id:"lk_5d8a1c", name:"Tso Chungpo",          lon:85.912, lat:28.011, elev:4350, area: 54.2, chg:-22.4, vol:32.5,  n:7,  sev:null,     tile:"langtang",     series:[70,68,65,62,59,56,54] },
  { id:"lk_1e4f9b", name:"Khumbu Tsho",          lon:86.812, lat:27.971, elev:4900, area: 37.5, chg:+15.3, vol:22.5,  n:9,  sev:"LOW",    tile:"khumbu",       series:[28,29,31,32,33,35,38] },
  { id:"lk_3a7d5e", name:"Longponga Tsho",       lon:86.748, lat:27.862, elev:5060, area: 19.3, chg:+38.6, vol:11.6,  n:4,  sev:"MEDIUM", tile:"khumbu",       series:[10,12,13,15,16,18,19] },
  { id:"lk_8c2b6f", name:"Kangchung Tsho",       lon:86.871, lat:27.932, elev:5250, area: 11.2, chg:+24.4, vol:6.7,   n:3,  sev:"LOW",    tile:"khumbu",       series:[7,8,8,9,10,10,11] },
  { id:"lk_6f4e3a", name:"Phortse Glacier Lake", lon:86.741, lat:27.881, elev:4730, area: 45.8, chg:+17.1, vol:27.5,  n:7,  sev:"LOW",    tile:"khumbu",       series:[33,35,37,39,41,43,46] },
  { id:"lk_0d1b8c", name:"Menlungtse Tsho",      lon:86.163, lat:28.027, elev:4490, area: 62.3, chg:-31.7, vol:37.4,  n:6,  sev:null,     tile:"langtang",     series:[91,84,78,73,68,64,62] },
  { id:"lk_2e9a4d", name:"Gaurishankar Lake",    lon:86.009, lat:27.951, elev:4210, area: 29.8, chg: +9.3, vol:17.9,  n:5,  sev:null,     tile:"langtang",     series:[25,26,27,27,28,29,30] },
  { id:"lk_4b6c1e", name:"Shorong Tsho",         lon:86.428, lat:27.792, elev:4680, area: 16.4, chg:+51.9, vol:9.8,   n:4,  sev:"HIGH",   tile:"langtang",     series:[7,8,9,11,13,15,16] },
  { id:"lk_7e3d9a", name:"Chukhung Glacier",     lon:86.952, lat:27.904, elev:5140, area: 23.7, chg:+29.9, vol:14.2,  n:5,  sev:"MEDIUM", tile:"khumbu",       series:[14,15,17,19,21,22,24] },
  { id:"lk_1f8b2c", name:"Pokalde Tsho",         lon:86.871, lat:27.897, elev:5190, area:  9.1, chg:+11.0, vol:5.5,   n:4,  sev:null,     tile:"khumbu",       series:[7,8,8,8,9,9,9] },
  { id:"lk_5a2e7f", name:"Ama Dablam Lake",      lon:86.860, lat:27.861, elev:4800, area: 12.8, chg:+28.0, vol:7.7,   n:3,  sev:"LOW",    tile:"khumbu",       series:[8,9,10,10,11,12,13] },
  { id:"lk_3c9d1b", name:"Nuptse Glacier Lake",  lon:86.889, lat:27.964, elev:5380, area:  6.2, chg:+55.0, vol:3.7,   n:3,  sev:"HIGH",   tile:"khumbu",       series:[2,3,4,4,5,6,6] },
];

// ─── R2 → app schema transform ───────────────────────────────────────────────
const TILE_LABELS = {
  far_west:"Far West", karnali:"Karnali", annapurna:"Annapurna",
  langtang:"Langtang", khumbu:"Khumbu",   kangchenjunga:"Kangchenjunga"
};

function lakeName(p) {
  const prefix = TILE_LABELS[p.tile] || (p.tile || "Lake");
  const short  = (p.lake_id || "").slice(-6);
  return `${prefix} ${short}`;
}

function transformR2Lakes(geojson) {
  if (!geojson?.features?.length) return null;
  return geojson.features.map(f => {
    const p    = f.properties ?? {};
    const area = p.latest_area_ha ?? 0;
    const chg  = p.area_change_pct ?? 0;
    // Reconstruct approximate baseline area from current + change %
    const base = chg !== -100 ? area / (1 + chg / 100) : area;
    return {
      id:      p.lake_id,
      name:    lakeName(p),
      lon:     p.centroid_lon ?? (f.geometry?.coordinates?.[0] ?? 86.5),
      lat:     p.centroid_lat ?? (f.geometry?.coordinates?.[1] ?? 28.0),
      elev:    p.mean_elevation ?? 0,
      area,
      chg,
      vol:     p.latest_volume_mcm ?? 0,
      n:       p.detection_count ?? 1,
      sev:     p.alert_severity || null,
      tile:    p.tile || "",
      series:  [Math.max(0, base), area],
      lastDate: p.latest_detection_date || null,
    };
  });
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

// ─── Mini Icons (pure SVG, no external lib) ───────────────────────────────────
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

// ─── Mini spark line for alert cards ──────────────────────────────────────────
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

// ─── Area Chart (detail panel) ────────────────────────────────────────────────
function AreaChart({ series }) {
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
      <text x="1" y={H-1} fontSize="9" fill="var(--text-dim)" fontFamily="JetBrains Mono, monospace">{min.toFixed(1)}</text>
      <text x={W-1} y={H-1} fontSize="9" fill="var(--text-dim)" fontFamily="JetBrains Mono, monospace" textAnchor="end">{max.toFixed(1)}</text>
    </svg>
  );
}

// ─── Detail Panel ─────────────────────────────────────────────────────────────
function DetailPanel({ lake, fallbackLake, onClose }) {
  const open = !!lake;
  const l = lake || fallbackLake;
  if (!l) return null;

  const chgCol  = l.chg > 15 ? "var(--high)" : l.chg < -10 ? "var(--success)" : "var(--text)";
  const lastObs = l.lastDate || "2024-08-12";
  const yearLabels = l.series?.length > 2 ? YEARS.slice(0, l.series.length) : ["Baseline", "Latest"];

  return (
    <div className={`detail-panel ${open ? "open" : ""}`}>
      <div className="detail-head">
        <div className="detail-name">{l.name}</div>
        <div className="detail-sub">{l.id} &nbsp;·&nbsp; {TILE_LABELS[l.tile] || l.tile}</div>
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
            <div className="d-stat-label">Volume</div>
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

        <div className="section-label">Area (ha) · trend</div>
        <div className="chart-box">
          <AreaChart series={l.series}/>
          <div className="chart-years">
            {yearLabels.map(y=><span key={y}>{y}</span>)}
          </div>
        </div>

        <div className="detail-note">
          Area derived from Sentinel-2 NDWI analysis at 10m resolution. Volume estimated
          via the empirical relationship V = 0.0298 · A<sup>1.37</sup> (Huggel et al., 2002).
          Alert threshold: &gt;30% area change with ≥ 2 valid detections within 90 days.
        </div>
      </div>
    </div>
  );
}

// ─── Map View ─────────────────────────────────────────────────────────────────
function MapView({ active, dark, lakes, onSelectLake, selectedLake }) {
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

  // Init map once — include initial lakes in style
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
            "circle-radius": ["step",["coalesce",["get","area"],10],10,30,15,80,19,150,24],
            "circle-color": ["case",["==",["get","sev"],"HIGH"],"#ef4444",["==",["get","sev"],"MEDIUM"],"#f97316",["==",["get","sev"],"LOW"],"#eab308","#64748b"],
            "circle-opacity": 0.22, "circle-blur": 1.2
          }
        },
        {
          id: "lakes-circles", type: "circle", source: "lakes",
          paint: {
            "circle-radius": ["step",["coalesce",["get","area"],10],6,30,9,80,12,150,16],
            "circle-color": ["case",["==",["get","sev"],"HIGH"],"#ef4444",["==",["get","sev"],"MEDIUM"],"#f97316",["==",["get","sev"],"LOW"],"#eab308","#64748b"],
            "circle-opacity": 0.97, "circle-stroke-width": 2.5, "circle-stroke-color": "#ffffff"
          }
        }
      ]
    };

    const map = new maplibregl.Map({
      container: elRef.current,
      style: INIT_STYLE,
      center: [86.0, 28.3],
      zoom: 6.5,
      attributionControl: false,
    });
    mapRef.current = map;

    map.on("load", () => {
      map.on("click", "lakes-circles", (e) => {
        const id   = e.features[0]?.properties?.id;
        const lake = lakesRef.current.find(l => l.id === id);
        if (!lake) return;
        if (popupRef.current) popupRef.current.remove();
        const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "270px", offset: 12 })
          .setLngLat(e.lngLat)
          .setHTML(`
            <div class="popup-name">${lake.name}</div>
            <div class="popup-row"><span class="popup-lbl">Elevation</span><span class="popup-val">${fmt(lake.elev,0)} m asl</span></div>
            <div class="popup-row"><span class="popup-lbl">Area</span><span class="popup-val">${fmt(lake.area,1)} ha</span></div>
            <div class="popup-row"><span class="popup-lbl">Volume</span><span class="popup-val">${fmt(lake.vol,2)} MCM</span></div>
            <div class="popup-row"><span class="popup-lbl">Change</span>
              <span class="popup-val" style="color:${lake.chg>15?"#ef4444":lake.chg<-10?"#22c55e":"inherit"}">${fmtPct(lake.chg)}</span>
            </div>
            ${lake.sev ? `<div class="popup-row"><span class="popup-lbl">Alert</span><span class="badge badge-${lake.sev}">${lake.sev}</span></div>` : ""}
            <button class="popup-action" onclick="window.__hw_select('${lake.id}')">Open detail panel →</button>
          `)
          .addTo(map);
        popupRef.current = popup;
      });
      map.on("mouseenter", "lakes-circles", () => map.getCanvas().style.cursor = "pointer");
      map.on("mouseleave", "lakes-circles", () => map.getCanvas().style.cursor = "");
    });

    window.__hw_select = (id) => {
      const lake = lakesRef.current.find(l => l.id === id);
      if (lake) {
        selectRef.current(lake);
        if (popupRef.current) { popupRef.current.remove(); popupRef.current = null; }
      }
    };
  }, []);

  // Update map source when lakes change (e.g., after R2 fetch)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const src = map.getSource("lakes");
    if (src) src.setData(toGeoJSON(lakes));
  }, [lakes]);

  // Swap tiles — no setStyle needed
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
        <div className="overview-sub">Nepal Himalaya · Sentinel-2 · Open data</div>
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
          <div className="big-stat-delta" style={{color:"var(--text-dim)"}}>latest season</div>
        </div>
        <div className="big-stat">
          <div className="big-stat-val" style={{color:"var(--high)"}}>{highAlerts.length}</div>
          <div className="big-stat-label">HIGH Alerts</div>
          <div className="big-stat-delta" style={{color:"var(--text-dim)"}}>{alerts.length} total active alerts</div>
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
                <div className="lake-row-id">{l.id}</div>
              </div>
              <Badge sev={l.sev}/>
              <div className="lake-row-chg pos">{fmtPct(l.chg)}</div>
            </div>
          ))}
        </div>
        <div className="panel">
          <div className="panel-title">Active Alerts</div>
          {topAlerts.map(l=>(
            <div key={l.id} className="lake-row" onClick={()=>onSelectLake(l)}>
              <div className="lake-row-info">
                <div className="lake-row-name">{l.name}</div>
                <div className="lake-row-id">{l.id}</div>
              </div>
              <Badge sev={l.sev}/>
              <div className={`lake-row-chg ${chgClass(l.chg)}`}>{fmtPct(l.chg)}</div>
            </div>
          ))}
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
      (l.tile || "").toLowerCase().includes(qlo) ||
      (l.sev||"").toLowerCase().includes(qlo)
    ) : lakes;
    return [...r].sort((a,b) => {
      const av = a[sortCol]??"", bv = b[sortCol]??"";
      if (av === bv) return 0;
      return typeof av === "string"
        ? av.localeCompare(bv) * sortDir
        : (av - bv) * sortDir;
    });
  }, [q, sortCol, sortDir, lakes]);

  const onSort = (col) => {
    if (sortCol === col) setSortDir(d => d*-1);
    else { setSortCol(col); setSortDir(-1); }
  };

  const Th = ({ col, children, right }) => (
    <th onClick={()=>onSort(col)} className={sortCol===col ? (sortDir===1?"sort-asc":"sort-desc") : ""}
        style={right?{textAlign:"right"}:{}}>
      {children}
    </th>
  );

  return (
    <div className="lakes-view">
      <div className="lakes-toolbar">
        <input className="search-input" placeholder="Filter by name, ID, tile, alert…"
          value={q} onChange={e=>setQ(e.target.value)}/>
        <span className="table-count">{filtered.length} of {lakes.length} lakes</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <Th col="name">Name</Th>
              <Th col="id">Lake ID</Th>
              <Th col="tile">Region</Th>
              <Th col="elev" right>Elev (m)</Th>
              <Th col="area" right>Area (ha)</Th>
              <Th col="chg"  right>Change %</Th>
              <Th col="vol"  right>Vol (MCM)</Th>
              <Th col="n"    right>Detections</Th>
              <Th col="sev">Alert</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(l => (
              <tr key={l.id} onClick={()=>onSelectLake(l)}>
                <td style={{fontWeight:500}}>{l.name}</td>
                <td className="mono">{l.id}</td>
                <td className="mono">{TILE_LABELS[l.tile] || l.tile}</td>
                <td className="num">{fmt(l.elev,0)}</td>
                <td className="num">{fmt(l.area,1)}</td>
                <td className="num" style={{color: l.chg>15?"var(--high)":l.chg<-10?"var(--success)":"inherit"}}>
                  {fmtPct(l.chg)}
                </td>
                <td className="num">{fmt(l.vol,2)}</td>
                <td className="num">{l.n}</td>
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
        <div className="alerts-sub">{alerts.length} lakes with significant area change · threshold ≥15% with ≥2 detections</div>
      </div>
      <div className="alerts-grid">
        {sorted.map(l=>(
          <div key={l.id} className={`alert-card ${l.sev}`} onClick={()=>onSelectLake(l)}>
            <div className="ac-head">
              <div>
                <div className="ac-name">{l.name}</div>
                <div className="ac-id">{l.id} · {TILE_LABELS[l.tile] || l.tile}</div>
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
                <div className="ac-label">Volume</div>
                <div className="ac-value">{fmt(l.vol,2)} MCM</div>
              </div>
            </div>
            <div className="ac-mini-chart">
              <SparkLine series={l.series}/>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────────
function Header({ lakes, alerts, dark, onToggle, dataSource }) {
  const totalKm2  = (lakes.reduce((s,l)=>s+l.area,0)/100).toFixed(1);
  const highCount = alerts.filter(a=>a.sev==="HIGH").length;
  return (
    <header className="hdr">
      <div className="hdr-brand">
        <div className="hdr-name">Himal<em>Watch</em></div>
        <div className="hdr-sub">Glacial Lake Monitoring · Nepal Himalaya</div>
      </div>
      <div className="hdr-gap"/>
      <div className="hdr-stats">
        <div className="hdr-stat"><strong>{lakes.length}</strong> lakes</div>
        <div className="hdr-stat"><strong>{totalKm2}</strong> km²</div>
        {dataSource === "demo" && (
          <div className="hdr-stat" style={{color:"var(--medium)"}}>demo data</div>
        )}
        {highCount > 0 && <span className="hdr-badge">{highCount} HIGH</span>}
      </div>
      <button className="icon-btn" onClick={onToggle} title={dark?"Switch to light":"Switch to dark"}>
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

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "variant": "cartographic",
    "density": "comfortable"
  }/*EDITMODE-END*/;

  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Fetch real lake data from R2 cache
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${R2_BASE}/cache/lakes.json`);
        if (res.ok) {
          const data       = await res.json();
          const transformed = transformR2Lakes(data);
          if (transformed && transformed.length > 0) {
            setLakes(transformed);
            setDataSource("live");
          }
        }
      } catch (e) {
        console.warn("R2 data not available yet, using demo data:", e.message);
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

  const handleSelect = useCallback((lake) => {
    setSelected(lake);
  }, []);

  const handleViewChange = useCallback((v) => {
    setView(v);
  }, []);

  return (
    <div className="shell">
      {/* Loading overlay */}
      <div className={`loading ${!loading ? "hidden" : ""}`}>
        <div className="spinner"/>
        <div className="loading-msg">Loading HimalWatch…</div>
      </div>

      <Header dark={dark} onToggle={()=>setDark(d=>!d)} lakes={lakes} alerts={alerts} dataSource={dataSource}/>
      <div className="body">
        <Sidebar view={view} onView={handleViewChange} alerts={alerts}/>
        <div className="content">
          {/* Map always mounted so state is preserved across tab switches */}
          <MapView
            active={view==="map"}
            dark={dark}
            lakes={lakes}
            onSelectLake={handleSelect}
            selectedLake={selected}
          />
          {view==="overview" && <OverviewView lakes={lakes} alerts={alerts} onSelectLake={handleSelect}/>}
          {view==="lakes"    && <LakesView    lakes={lakes}                  onSelectLake={handleSelect}/>}
          {view==="alerts"   && <AlertsView   alerts={alerts}                onSelectLake={handleSelect}/>}

          {/* Detail panel — available from all views */}
          <DetailPanel
            lake={selected}
            fallbackLake={lakes[0]}
            onClose={()=>setSelected(null)}
          />
        </div>
      </div>

      <TweaksPanel title="Design Variations">
        <TweakSection label="Aesthetic">
          <TweakRadio id="variant" label="Style variant"
            options={[{value:"cartographic",label:"Cartographic"},{value:"editorial",label:"Editorial"}]}
            value={tweaks.variant} onChange={v=>setTweak("variant",v)}/>
        </TweakSection>
        <TweakSection label="Theme">
          <TweakToggle id="dark" label="Dark mode"
            value={dark} onChange={setDark}/>
        </TweakSection>
        <TweakSection label="Data">
          <TweakRadio id="density" label="Row density"
            options={[{value:"comfortable",label:"Normal"},{value:"compact",label:"Compact"}]}
            value={tweaks.density} onChange={v=>{setTweak("density",v);document.documentElement.style.setProperty("--row-density",v==="compact"?"6px":"8px");}}/>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
