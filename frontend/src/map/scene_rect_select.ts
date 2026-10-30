/** Map drag-rectangle to scene-build coordinates: center lng/lat plus square side in UTM metres. */

import { MAX_SIDE_LENGTH_M } from "./scene_build.js";
import { lngLatToUtmM, utmCrsFor, type LngLat } from "./site_frame.js";

export type { LngLat };

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
  const crs = utmCrsFor(lat, lon);
  const [x1, y1] = lngLatToUtmM(crs, a);
  const [x2, y2] = lngLatToUtmM(crs, b);
  const side = Math.max(Math.abs(x1 - x2), Math.abs(y1 - y2));
  if (!Number.isFinite(side) || side < 2) return null;
  // Round the side up to an even metre so the square covers the whole rectangle.
  const even = Math.min(MAX_SIDE_LENGTH_M, 2 * Math.ceil(side / 2));
  if (even < 2) return null;
  return { lat, lon, sideLengthM: even };
}
