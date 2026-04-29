/**
 * HimalWatch — Cloudflare Worker API
 *
 * Reads pre-materialised Parquet files from R2 and serves JSON responses.
 * Zero cold starts, runs at the edge, 100k req/day free.
 *
 * Data is served from R2-bound JSON cache files written by the export step.
 * The Worker itself does not run DuckDB — it serves pre-computed JSON so
 * responses are instant and CPU budget stays well under the 10ms limit.
 *
 * Routes:
 *   GET /              → API info
 *   GET /health        → Health check (for uptime monitors)
 *   GET /stats         → Aggregate stats
 *   GET /lakes         → All lakes (GeoJSON FeatureCollection)
 *   GET /lakes/:id     → Single lake by lake_id
 *   GET /alerts        → Change alerts (filterable: ?severity=HIGH)
 *
 * Cache files written to R2 by export_worker_json.py:
 *   cache/lakes.json
 *   cache/alerts.json
 *   cache/stats.json
 */

const CACHE_TTL = 60 * 60 * 6; // 6 hours — pipeline runs weekly

export default {
  async fetch(request, env) {
    const url    = new URL(request.url);
    const path   = url.pathname.replace(/\/$/, "") || "/";
    const params = url.searchParams;

    // CORS — this is a public research API
    const cors = {
      "Access-Control-Allow-Origin":  "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json({ error: "Method not allowed" }, 405, cors);
    }

    try {
      // --- GET / ---
      if (path === "/") {
        const stats = await readCache(env, "cache/stats.json");
        return json({
          name:         "HimalWatch API",
          version:      "1.0.0",
          docs:         "https://github.com/bikalpa/himalwatch",
          status:       "operational",
          last_updated: stats?.last_pipeline_run ?? null,
        }, 200, cors);
      }

      // --- GET /health ---
      if (path === "/health") {
        return json({ status: "ok" }, 200, cors);
      }

      // --- GET /stats ---
      if (path === "/stats") {
        const stats = await readCache(env, "cache/stats.json");
        if (!stats) return json({ error: "Stats not yet available" }, 503, cors);
        return json(stats, 200, cors, CACHE_TTL);
      }

      // --- GET /lakes ---
      if (path === "/lakes") {
        const lakes = await readCache(env, "cache/lakes.json");
        if (!lakes) return json({ error: "Lake data not yet available" }, 503, cors);

        let features = lakes.features ?? [];

        // Optional filters
        const region     = params.get("region");
        const minElev    = params.get("min_elevation");
        const minAreaHa  = params.get("min_area_ha");
        const limit      = Math.min(parseInt(params.get("limit") ?? "500"), 2000);

        if (region)    features = features.filter(f => f.properties.tile === region);
        if (minElev)   features = features.filter(f => f.properties.mean_elevation >= parseFloat(minElev));
        if (minAreaHa) features = features.filter(f => f.properties.latest_area_ha >= parseFloat(minAreaHa));

        features = features.slice(0, limit);

        return json({ type: "FeatureCollection", features }, 200, cors, CACHE_TTL);
      }

      // --- GET /lakes/:id ---
      const lakeMatch = path.match(/^\/lakes\/([a-f0-9\-]+)$/i);
      if (lakeMatch) {
        const lakes = await readCache(env, "cache/lakes.json");
        const lake  = lakes?.features?.find(f => f.properties.lake_id === lakeMatch[1]);
        if (!lake) return json({ error: "Lake not found" }, 404, cors);
        return json(lake, 200, cors, CACHE_TTL);
      }

      // --- GET /alerts ---
      if (path === "/alerts") {
        const alerts = await readCache(env, "cache/alerts.json");
        if (!alerts) return json({ alerts: [] }, 200, cors);

        let items    = alerts.alerts ?? [];
        const sev    = params.get("severity")?.toUpperCase();
        const region = params.get("region");

        if (sev)    items = items.filter(a => a.alert_severity === sev);
        if (region) items = items.filter(a => a.tile === region);

        return json({ alerts: items, count: items.length }, 200, cors, CACHE_TTL);
      }

      return json({ error: "Not found" }, 404, cors);

    } catch (err) {
      console.error(err);
      return json({ error: "Internal server error" }, 500, cors);
    }
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function readCache(env, key) {
  try {
    const obj = await env.DATA_BUCKET.get(key);
    if (!obj) return null;
    return await obj.json();
  } catch {
    return null;
  }
}

function json(data, status = 200, extraHeaders = {}, cacheSecs = 0) {
  const headers = {
    "Content-Type": "application/json",
    ...extraHeaders,
  };
  if (cacheSecs > 0) {
    headers["Cache-Control"] = `public, max-age=${cacheSecs}`;
  }
  return new Response(JSON.stringify(data), { status, headers });
}
