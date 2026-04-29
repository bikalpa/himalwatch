/**
 * HimalWatch Dashboard
 *
 * Three views: Map · Lake List · Change Alerts
 * Data loaded directly from Cloudflare R2 via fetch (pre-computed JSON cache).
 * No build step, no framework — vanilla JS.
 */

const CONFIG = {
  r2BaseUrl:    "https://pub-ebc663fdb5cc4a0ea7bde7330a88bfe2.r2.dev",
  mapStyle:     "https://demotiles.maplibre.org/style.json",
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _lakes   = null;  // GeoJSON FeatureCollection
let _alerts  = null;  // { alerts: [...] }
let _map     = null;
let _sortCol = "area_change_pct";
let _sortDir = -1;    // -1 = desc

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  try {
    await loadData();
    hideLoading();
    initMapView();
    initListView();
    initAlertsView();
    updateHeaderStats();
  } catch (err) {
    showError(err.message);
  }
});

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  setLoadingMsg("Loading lake inventory...");
  const [lakesRes, alertsRes] = await Promise.all([
    fetch(`${CONFIG.r2BaseUrl}/cache/lakes.json`),
    fetch(`${CONFIG.r2BaseUrl}/cache/alerts.json`),
  ]);

  if (!lakesRes.ok) throw new Error(
    `Failed to load lake data (${lakesRes.status}). ` +
    `Check that R2 public access is enabled and CORS is configured.`
  );

  _lakes  = await lakesRes.json();
  _alerts = alertsRes.ok ? await alertsRes.json() : { alerts: [] };
}

// ---------------------------------------------------------------------------
// Header stats
// ---------------------------------------------------------------------------

function updateHeaderStats() {
  const count = _lakes.features.length;
  const area  = _lakes.features.reduce(
    (s, f) => s + (f.properties.latest_area_sqm ?? 0), 0
  ) / 1e6;
  const highCount = (_alerts.alerts ?? []).filter(a => a.alert_severity === "HIGH").length;

  document.getElementById("stat-lakes").textContent = count.toLocaleString();
  document.getElementById("stat-area").textContent  = area.toFixed(2);

  const badge = document.getElementById("stat-alerts");
  if (highCount > 0) {
    badge.textContent    = `${highCount} HIGH alert${highCount > 1 ? "s" : ""}`;
    badge.style.display  = "inline-block";
  }
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

function setupTabs() {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`view-${btn.dataset.view}`).classList.add("active");
      if (btn.dataset.view === "map" && _map) _map.resize();
    });
  });
}

// ---------------------------------------------------------------------------
// MAP VIEW
// ---------------------------------------------------------------------------

function initMapView() {
  _map = new maplibregl.Map({
    container: "map",
    style:     CONFIG.mapStyle,
    center:    [84.0, 28.5],  // Centre of Nepal Himalaya
    zoom:      6,
  });

  _map.on("load", () => {
    _map.addSource("lakes", {
      type: "geojson",
      data: _lakes,
    });

    // Circle layer — size by area (log scale), colour by alert severity
    _map.addLayer({
      id:   "lakes-circles",
      type: "circle",
      source: "lakes",
      paint: {
        // Step radius by area: small=4px, medium=7px, large=11px
        "circle-radius": [
          "step",
          ["coalesce", ["get", "latest_area_sqm"], 10000],
          4,
          30000,  6,
          100000, 9,
          500000, 13,
        ],
        "circle-color": [
          "case",
          ["==", ["get", "alert_severity"], "HIGH"],   "#ef4444",
          ["==", ["get", "alert_severity"], "MEDIUM"], "#f97316",
          ["==", ["get", "alert_severity"], "LOW"],    "#eab308",
          "#6b7280",
        ],
        "circle-opacity": 0.85,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff22",
      },
    });

    // Popup on click
    _map.on("click", "lakes-circles", e => {
      const p = e.features[0].properties;
      const changePct = p.area_change_pct != null
        ? `${p.area_change_pct > 0 ? "+" : ""}${Number(p.area_change_pct).toFixed(1)}%`
        : "—";

      new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
        .setLngLat(e.lngLat)
        .setHTML(`
          <div class="popup-title">${p.lake_id}</div>
          <div class="popup-row"><span class="popup-label">Tile</span><span>${p.tile ?? "—"}</span></div>
          <div class="popup-row"><span class="popup-label">Elevation</span><span>${fmt(p.mean_elevation, 0)} m</span></div>
          <div class="popup-row"><span class="popup-label">Area</span><span>${fmt(p.latest_area_ha, 1)} ha</span></div>
          <div class="popup-row"><span class="popup-label">Volume</span><span>${fmt(p.latest_volume_mcm, 3)} MCM</span></div>
          <div class="popup-row"><span class="popup-label">Area change</span><span>${changePct}</span></div>
          <div class="popup-row"><span class="popup-label">Detections</span><span>${p.detection_count ?? "—"}</span></div>
          <div class="popup-row"><span class="popup-label">Last seen</span><span>${p.latest_detection_date?.slice(0,10) ?? "—"}</span></div>
          ${p.alert_severity ? `<div class="popup-row"><span class="popup-label">Alert</span><span class="badge badge-${p.alert_severity}">${p.alert_severity}</span></div>` : ""}
        `)
        .addTo(_map);
    });

    _map.on("mouseenter", "lakes-circles", () => (_map.getCanvas().style.cursor = "pointer"));
    _map.on("mouseleave", "lakes-circles", () => (_map.getCanvas().style.cursor = ""));
  });
}

// ---------------------------------------------------------------------------
// LAKE LIST VIEW
// ---------------------------------------------------------------------------

function initListView() {
  renderTable(_lakes.features);

  // Sort on header click
  document.querySelectorAll("thead th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (_sortCol === col) _sortDir *= -1;
      else { _sortCol = col; _sortDir = -1; }
      document.querySelectorAll("thead th").forEach(h => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(_sortDir === 1 ? "sort-asc" : "sort-desc");
      renderTable(filteredFeatures());
    });
  });

  // Search filter
  document.getElementById("list-search").addEventListener("input", () => {
    renderTable(filteredFeatures());
  });
}

function filteredFeatures() {
  const q = document.getElementById("list-search").value.toLowerCase();
  return _lakes.features.filter(f => {
    if (!q) return true;
    const p = f.properties;
    return (p.lake_id ?? "").toLowerCase().includes(q) ||
           (p.tile    ?? "").toLowerCase().includes(q);
  });
}

function renderTable(features) {
  const sorted = [...features].sort((a, b) => {
    const av = a.properties[_sortCol] ?? 0;
    const bv = b.properties[_sortCol] ?? 0;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return typeof av === "string"
      ? av.localeCompare(bv) * _sortDir
      : (av - bv) * _sortDir;
  });

  document.getElementById("list-count").textContent =
    `${sorted.length.toLocaleString()} lakes`;

  const rows = sorted.map(f => {
    const p = f.properties;
    const chg = p.area_change_pct;
    const chgStr = chg != null
      ? `<span class="${chg > 15 ? "change-pos" : chg < -15 ? "change-neg" : ""}">${chg > 0 ? "+" : ""}${Number(chg).toFixed(1)}%</span>`
      : "—";
    const badge = p.alert_severity
      ? `<span class="badge badge-${p.alert_severity}">${p.alert_severity}</span>`
      : "";
    return `<tr data-id="${p.lake_id}">
      <td class="lake-id">${p.lake_id}</td>
      <td>${p.tile ?? "—"}</td>
      <td class="num">${fmt(p.mean_elevation, 0)}</td>
      <td class="num">${fmt(p.latest_area_ha, 1)}</td>
      <td class="num">${chgStr}</td>
      <td class="num">${fmt(p.latest_volume_mcm, 3)}</td>
      <td>${p.latest_detection_date?.slice(0,10) ?? "—"}</td>
      <td>${badge}</td>
    </tr>`;
  }).join("");

  document.getElementById("lake-tbody").innerHTML = rows;

  // Click row → fly to on map
  document.querySelectorAll("#lake-tbody tr").forEach(row => {
    row.addEventListener("click", () => {
      const f = _lakes.features.find(f => f.properties.lake_id === row.dataset.id);
      if (!f) return;
      // Switch to map tab
      document.querySelector('[data-view="map"]').click();
      _map.flyTo({ center: f.geometry.coordinates, zoom: 12, duration: 800 });
    });
  });
}

// ---------------------------------------------------------------------------
// CHANGE ALERTS VIEW
// ---------------------------------------------------------------------------

function initAlertsView() {
  const container = document.getElementById("alerts-container");
  const alerts    = (_alerts.alerts ?? []).filter(
    a => a.alert_severity === "HIGH" || a.alert_severity === "MEDIUM"
  );

  if (alerts.length === 0) {
    container.innerHTML = `
      <div class="no-alerts">
        <div class="icon">✓</div>
        <div>No HIGH or MEDIUM severity alerts at this time.</div>
        <div class="muted" style="margin-top:6px;font-size:12px">
          Alerts appear when a lake's area changes by more than 30% with ≥2 detections.
        </div>
      </div>`;
    return;
  }

  container.innerHTML = alerts.map(a => {
    const chg     = Number(a.area_change_pct ?? 0).toFixed(1);
    const isGrow  = a.area_change_pct > 0;
    const volChg  = a.volume_change_mcm != null
      ? `${a.volume_change_mcm > 0 ? "+" : ""}${Number(a.volume_change_mcm).toFixed(3)} MCM`
      : "—";

    return `
    <div class="alert-card ${a.alert_severity}">
      <div class="alert-header">
        <div>
          <span class="badge badge-${a.alert_severity}">${a.alert_severity}</span>
          <div class="alert-id" style="margin-top:4px">${a.lake_id}</div>
        </div>
        <div class="muted" style="font-size:11px;text-align:right">
          ${a.tile ?? ""}<br>
          ${a.days_since_observation ?? "—"}d ago
        </div>
      </div>
      <div class="alert-body">
        <div class="alert-stat">
          <span class="label">Area change</span>
          <span class="value ${isGrow ? "change-pos" : "change-neg"}">${isGrow ? "+" : ""}${chg}%</span>
        </div>
        <div class="alert-stat">
          <span class="label">Volume change</span>
          <span class="value">${volChg}</span>
        </div>
        <div class="alert-stat">
          <span class="label">Elevation</span>
          <span class="value">${fmt(a.mean_elevation, 0)} m</span>
        </div>
        <div class="alert-stat">
          <span class="label">Latest area</span>
          <span class="value">${fmt(a.latest_area_ha ?? (a.latest_area_sqm / 10000), 1)} ha</span>
        </div>
        <div class="alert-stat">
          <span class="label">First detected</span>
          <span class="value">${a.first_detected_date?.slice(0,10) ?? "—"}</span>
        </div>
        <div class="alert-stat">
          <span class="label">Last detected</span>
          <span class="value">${a.latest_detection_date?.slice(0,10) ?? "—"}</span>
        </div>
      </div>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function fmt(v, decimals = 1) {
  if (v == null || isNaN(v)) return "—";
  return Number(v).toFixed(decimals);
}

function setLoadingMsg(msg) {
  document.getElementById("loading-msg").textContent = msg;
}

function hideLoading() {
  document.getElementById("loading-overlay").classList.add("hidden");
}

function showError(msg) {
  document.getElementById("loading-overlay").innerHTML = `
    <div style="max-width:420px;text-align:center;padding:24px">
      <div style="font-size:28px;margin-bottom:12px">⚠</div>
      <div style="font-weight:600;margin-bottom:8px">Could not load data</div>
      <div style="color:var(--text-muted);font-size:13px">${msg}</div>
    </div>`;
}
