/** Map drag-rectangle to scene-build coordinates: center lng/lat plus square side in UTM metres. */

import proj4 from "proj4";
import { MAX_SIDE_LENGTH_M } from "./scene_build.js";

export type LngLat = { lng: number; lat: number };

/** Same UTM zone rule as the backend `data_tools/metric_grid.py` `metric_grid`. */
function utmCrs(lat: number, lon: number): string {
  const zone = Math.min(60, Math.floor((lon + 180) / 6) + 1);
  return `EPSG:${(lat >= 0 ? 32600 : 32700) + zone}`;
}

function ensureUtm(crs: string): void {
  const match = /^EPSG:(326|327)([0-9]{2})$/.exec(crs);
  if (match && !proj4.defs(crs)) {
    proj4.defs(crs, `+proj=utm +zone=${Number(match[2])} ${match[1] === "327" ? "+south" : ""} +datum=WGS84 +units=m +no_defs`);
  }
}

/**
 * Two opposite corners of a drag rectangle to the scene center and even square side.
 * Returns null for a degenerate or out-of-range rectangle. Side uses the same UTM
 * metres as the scene grid, so the built square covers the dragged rectangle.
 */
export function rectToSceneConfig(
  a: LngLat,
  b: LngLat,
): { lat: number; lon: number; sideLengthM: number } | null {
  if (![a.lng, a.lat, b.lng, b.lat].every((value) => Number.isFinite(value))) return null;
  const lat = (a.lat + b.lat) / 2;
  const lon = (a.lng + b.lng) / 2;
  if (lat < -80 || lat > 84 || lon < -180 || lon > 180) return null;
  const crs = utmCrs(lat, lon);
  ensureUtm(crs);
  const [x1, y1] = proj4("EPSG:4326", crs, [a.lng, a.lat]);
  const [x2, y2] = proj4("EPSG:4326", crs, [b.lng, b.lat]);
  const side = Math.max(Math.abs(x1 - x2), Math.abs(y1 - y2));
  if (!Number.isFinite(side) || side < 2) return null;
  // Round the side up to an even metre so the square covers the whole rectangle.
  const even = Math.min(MAX_SIDE_LENGTH_M, 2 * Math.ceil(side / 2));
  if (even < 2) return null;
  return { lat, lon, sideLengthM: even };
}
