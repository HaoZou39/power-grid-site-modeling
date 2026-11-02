/** Map drag-rectangle to scene-build coordinates: center lng/lat plus square side in UTM metres. */

import { MAX_SIDE_LENGTH_M } from "./scene_build.js";
import { lngLatToUtmM, utmCrsFor, utmMToLngLat, type LngLat } from "./site_frame.js";

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

/**
 * Closed WGS84 ring of the UTM square `metric_grid` would build.
 * Northing is +y. Returns null when the centre or even side is out of range.
 */
export function sceneSquareRing(
  lat: number,
  lon: number,
  sideLengthM: number,
): [number, number][] | null {
  if (!Number.isFinite(lat) || lat < -80 || lat > 84) return null;
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) return null;
  if (!Number.isInteger(sideLengthM) || sideLengthM < 2 || sideLengthM > MAX_SIDE_LENGTH_M || sideLengthM % 2 !== 0) return null;
  const crs = utmCrsFor(lat, lon);
  const [x, y] = lngLatToUtmM(crs, { lng: lon, lat });
  const half = sideLengthM / 2;
  const ring = [
    [x - half, y + half],
    [x + half, y + half],
    [x + half, y - half],
    [x - half, y - half],
  ].map(([mx, my]) => {
    const point = utmMToLngLat(crs, mx, my);
    return [point.lng, point.lat] as [number, number];
  });
  ring.push(ring[0]);
  return ring;
}
