/**
 * Local site frame for the Cangnan 1800 m grid.
 * Origin is the upper-left corner of the EPSG:3857 reference bounds.
 * x increases east, y increases south. Scales come from data_metadata target_transform.
 */

const EARTH_RADIUS_M = 6378137;

export type LngLat = { lng: number; lat: number };
export type LocalPoint = { x: number; y: number };

export function mercatorToLngLat(x: number, y: number): LngLat {
  const lng = (x / EARTH_RADIUS_M) * (180 / Math.PI);
  const lat = (Math.atan(Math.sinh(y / EARTH_RADIUS_M)) * 180) / Math.PI;
  return { lng, lat };
}

export function lngLatToMercator(lng: number, lat: number): { x: number; y: number } {
  const x = lng * Math.PI / 180 * EARTH_RADIUS_M;
  const y = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI / 180) / 2)) * EARTH_RADIUS_M;
  return { x, y };
}

/** One local meter grid. Another region is another instance, not a second set of functions. */
export class SiteFrame {
  constructor(
    readonly originX: number,
    readonly originY: number,
    readonly xScale: number,
    readonly yScale: number,
    readonly widthM: number,
    readonly heightM: number,
  ) {}

  localToLngLat(point: LocalPoint): LngLat {
    return mercatorToLngLat(
      this.originX + point.x * this.xScale,
      this.originY + point.y * this.yScale,
    );
  }

  lngLatToLocal(lngLat: LngLat): LocalPoint {
    const mercator = lngLatToMercator(lngLat.lng, lngLat.lat);
    return {
      x: (mercator.x - this.originX) / this.xScale,
      y: (mercator.y - this.originY) / this.yScale,
    };
  }

  inside(point: LocalPoint): boolean {
    return point.x >= 0 && point.y >= 0 && point.x <= this.widthM && point.y <= this.heightM;
  }

  ring(): [number, number][] {
    const corners = [
      { x: 0, y: 0 },
      { x: this.widthM, y: 0 },
      { x: this.widthM, y: this.heightM },
      { x: 0, y: this.heightM },
    ];
    const ring = corners.map((corner) => {
      const lngLat = this.localToLngLat(corner);
      return [lngLat.lng, lngLat.lat] as [number, number];
    });
    ring.push(ring[0]);
    return ring;
  }
}

export const siteFrame = new SiteFrame(
  13379105.681260297,
  3187189.393928443,
  1.0002501748253902,
  -1.0005819327609302,
  1800,
  1800,
);

export function localToLngLat(point: LocalPoint): LngLat {
  return siteFrame.localToLngLat(point);
}

export function lngLatToLocal(lngLat: LngLat): LocalPoint {
  return siteFrame.lngLatToLocal(lngLat);
}

export function insideSite(point: LocalPoint): boolean {
  return siteFrame.inside(point);
}

/** Rectangle corners in local meters. Matches `rectangle_corners` in `figures/candidate_maps.py`. */
export function footprintCorners(x: number, y: number, theta: number, width: number, height: number): LocalPoint[] {
  const cosine = Math.cos(theta);
  const sine = Math.sin(theta);
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  return [
    [-halfWidth, -halfHeight],
    [halfWidth, -halfHeight],
    [halfWidth, halfHeight],
    [-halfWidth, halfHeight],
  ].map(([px, py]) => ({
    x: x + px * cosine - py * sine,
    y: y + px * sine + py * cosine,
  }));
}

export function siteRing(): [number, number][] {
  return siteFrame.ring();
}
