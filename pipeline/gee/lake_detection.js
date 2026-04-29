/**
 * HimalWatch — Glacial Lake Detection
 *
 * PURPOSE:
 *   Detect glacial lake candidates in the Nepal Himalaya using Sentinel-2
 *   NDWI thresholding combined with a DEM elevation filter. Visual spike
 *   for tuning parameters before running the Python production pipeline.
 *
 * DATA SOURCES:
 *   - Sentinel-2 SR Harmonized (COPERNICUS/S2_SR_HARMONIZED), 10m resolution
 *   - SRTM Digital Elevation Model (USGS/SRTMGL1_003), 30m resolution
 *
 * EXPECTED OUTPUT:
 *   - Blue polygons on the map = glacial lake candidates
 *   - Console shows feature count and total water area
 *   - Export tasks created for GDrive and GEE Asset
 *
 * HOW TO RUN:
 *   1. Open code.earthengine.google.com
 *   2. Paste this entire script into the editor
 *   3. Change TILE variable below to focus on a different region if needed
 *   4. Click Run
 *   5. Inspect blue polygons — do they match visible lakes in the RGB layer?
 *   6. Check Console tab for counts
 *   7. Click Tasks tab → Run to start the export jobs
 */

// ============================================================
// CONFIGURATION — adjust as needed
// ============================================================

// Test area: Khumbu (Everest region) — high lake density, good for validation
var TILES = {
  khumbu:        [86.2, 27.5, 87.2, 29.5],
  langtang:      [85.1, 27.5, 86.2, 29.5],
  annapurna:     [83.8, 27.5, 85.1, 29.5],
  karnali:       [82.1, 27.5, 83.8, 29.5],
  far_west:      [80.0, 27.5, 82.1, 29.5],
  kangchenjunga: [87.2, 27.5, 88.2, 29.5],
};

var TILE = 'khumbu';           // Change to any key above
var YEAR = 2024;               // Processing year
var NDWI_THRESHOLD = 0.3;      // Water detection threshold (McFeeters 1996)
var ELEV_MIN_M = 3500;         // Only detect lakes above this elevation (m)
var MIN_AREA_SQM = 10000;      // Minimum lake area = 1 hectare

// Season: post-monsoon shoulder gives clearest lakes (Oct is ideal; Jun-Sep cloudy)
// Use June-September to capture peak melt extent despite cloud challenges
var SEASON_START = YEAR + '-06-01';
var SEASON_END   = YEAR + '-09-30';

// ============================================================
// AREA OF INTEREST
// ============================================================

var bbox = TILES[TILE];
var aoi = ee.Geometry.Rectangle(bbox);
Map.centerObject(aoi, 9);

// ============================================================
// SENTINEL-2 — cloud-masked composite
// ============================================================

/**
 * QA60 cloud mask: bits 10 (cloud) and 11 (cirrus)
 */
function maskQA60(image) {
  var qa = image.select('QA60');
  var cloudBit  = 1 << 10;
  var cirrusBit = 1 << 11;
  var mask = qa.bitwiseAnd(cloudBit).eq(0)
               .and(qa.bitwiseAnd(cirrusBit).eq(0));
  return image.updateMask(mask);
}

/**
 * SCL cloud/shadow mask — more accurate than QA60 at high altitude.
 * Excludes: 3=cloud shadow, 8=cloud med prob, 9=cloud high prob, 10=thin cirrus
 * Keeps class 11 (snow) — we discriminate snow vs water with NDSI per-pixel.
 */
function maskSCL(image) {
  var scl = image.select('SCL');
  var mask = scl.neq(3).and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10));
  return image.updateMask(mask);
}

/**
 * Add NDWI band: (Green - NIR) / (Green + NIR)
 * Sentinel-2: Green=B3, NIR=B8
 */
function addNDWI(image) {
  return image.addBands(
    image.normalizedDifference(['B3', 'B8']).rename('NDWI')
  );
}

/**
 * Add NDSI band: (Green - SWIR) / (Green + SWIR)
 * Sentinel-2: Green=B3, SWIR1=B11
 * Snow: NDSI > 0.4 | Water: NDSI < 0.1
 */
function addNDSI(image) {
  return image.addBands(
    image.normalizedDifference(['B3', 'B11']).rename('NDSI')
  );
}

// Build Sentinel-2 collection
var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(aoi)
  .filterDate(SEASON_START, SEASON_END)
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80))
  .map(maskQA60)
  .map(maskSCL)
  .map(addNDWI)
  .map(addNDSI);

print('Sentinel-2 scenes in collection:', s2.size());

// Median composite — smoothest, handles cloud edge remnants
var composite = s2.median();

// ============================================================
// DEM — elevation filter
// ============================================================

var dem = ee.Image('USGS/SRTMGL1_003').select('elevation');
var elevMask = dem.gt(ELEV_MIN_M);

// ============================================================
// WATER DETECTION
// ============================================================

var ndwi  = composite.select('NDWI');
var ndsi  = composite.select('NDSI');

// Water mask: NDWI > threshold AND not snow (NDSI < 0.4) AND above elevation
var waterMask = ndwi.gt(NDWI_THRESHOLD)
                    .and(ndsi.lt(0.4))      // exclude snow/ice pixels
                    .and(elevMask)           // high-altitude only
                    .selfMask();

// ============================================================
// VECTORISE — convert raster mask to polygons
// ============================================================

var lakes = waterMask.reduceToVectors({
  geometry: aoi,
  scale: 10,
  geometryType: 'polygon',
  eightConnected: false,   // 4-connected avoids diagonal pixel merging
  maxPixels: 1e10,
  bestEffort: true,
});

// Filter minimum area (1 hectare = 10,000 sqm)
lakes = lakes.map(function(f) {
  return f.set('area_sqm', f.geometry().area(1));
}).filter(ee.Filter.gte('area_sqm', MIN_AREA_SQM));

// Add attributes for each lake
lakes = lakes.map(function(f) {
  var geom    = f.geometry();
  var centroid = geom.centroid(1);
  var meanElev = dem.reduceRegion({
    reducer: ee.Reducer.mean(), geometry: geom, scale: 30, maxPixels: 1e6
  }).get('elevation');
  var meanNDWI = ndwi.reduceRegion({
    reducer: ee.Reducer.mean(), geometry: geom, scale: 10, maxPixels: 1e6
  }).get('NDWI');
  var meanNDSI = ndsi.reduceRegion({
    reducer: ee.Reducer.mean(), geometry: geom, scale: 10, maxPixels: 1e6
  }).get('NDSI');

  return f.set({
    area_sqm:       f.getNumber('area_sqm'),
    area_ha:        f.getNumber('area_sqm').divide(10000),
    centroid_lon:   centroid.coordinates().get(0),
    centroid_lat:   centroid.coordinates().get(1),
    mean_elevation: meanElev,
    mean_ndwi:      meanNDWI,
    mean_ndsi:      meanNDSI,
    detection_year: YEAR,
    tile:           TILE,
    season_start:   SEASON_START,
    season_end:     SEASON_END,
  });
});

// ============================================================
// CONSOLE SUMMARY
// ============================================================

print('=== HimalWatch Detection Summary ===');
print('Tile:', TILE);
print('Season:', SEASON_START, '→', SEASON_END);
print('NDWI threshold:', NDWI_THRESHOLD);
print('Elevation filter: >', ELEV_MIN_M, 'm');
print('Min area:', MIN_AREA_SQM, 'sqm');
print('Lakes detected:', lakes.size());

var totalArea = lakes.aggregate_sum('area_sqm');
print('Total water area (sqm):', totalArea);
print('Total water area (sqkm):', ee.Number(totalArea).divide(1e6));

// ============================================================
// MAP VISUALISATION
// ============================================================

// RGB composite
Map.addLayer(
  composite.select(['B4', 'B3', 'B2']),
  { min: 0, max: 3000, gamma: 1.4 },
  'Sentinel-2 RGB'
);

// NDWI
Map.addLayer(
  ndwi,
  { min: -0.5, max: 0.5, palette: ['brown', 'white', 'blue'] },
  'NDWI',
  false   // off by default — toggle on to inspect
);

// DEM
Map.addLayer(
  dem,
  { min: 3000, max: 6000, palette: ['green', 'white', 'grey'] },
  'Elevation (m)',
  false
);

// Detected lakes — blue fill, darker blue outline
Map.addLayer(
  ee.Image().paint(lakes, 1, 2),
  { palette: ['0044cc'] },
  'Lake outlines'
);

Map.addLayer(
  lakes,
  { color: '0066ff' },
  'Lake polygons'
);

// ============================================================
// EXPORTS
// ============================================================

// Export to Google Drive (GeoJSON)
Export.table.toDrive({
  collection: lakes,
  description: 'himalwatch_lakes_' + TILE + '_' + YEAR,
  folder: 'himalwatch',
  fileNamePrefix: 'lakes_' + TILE + '_' + YEAR,
  fileFormat: 'GeoJSON',
});

// Export to GEE Asset (for use in follow-up scripts)
Export.table.toAsset({
  collection: lakes,
  description: 'himalwatch_lakes_asset_' + TILE + '_' + YEAR,
  assetId: 'projects/himalwatch/assets/lakes_' + TILE + '_' + YEAR,
});

print('Export tasks created — click Tasks tab → Run to start exports.');
