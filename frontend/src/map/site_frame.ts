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

export let siteFrame = new SiteFrame(
  13379105.681260297,
  3187189.393928443,
  1.0002501748253902,
  -1.0005819327609302,
  1800,
  1800,
);

/** Scene frames are constructed from the backend's aligned DEM target_transform. */
export type SceneFrameInfo = {
  crs: string;
  transform: [number, number, number, number, number, number];
  width: number;
  height: number;
};

/** Activate a prepared scene before mounting its map and local editing workspace. */
export function siteFrameFromInfo(frame: SceneFrameInfo): SiteFrame {
  const [a, b, c, d, e, f] = frame.transform;
  if (frame.crs !== "EPSG:3857" || [a, b, c, d, e, f, frame.width, frame.height].some((value) => !Number.isFinite(value))) {
    throw new Error("场景坐标必须是有效的 EPSG:3857 投影网格。");
  }
  if (a <= 0 || e >= 0 || Math.abs(b) > 1e-8 || Math.abs(d) > 1e-8 || frame.width <= 0 || frame.height <= 0) {
    throw new Error("当前地图暂不支持旋转或无效的场景栅格。");
  }
  return new SiteFrame(c, f, a, e, frame.width, frame.height);
}

export function activateSiteFrame(frame: SceneFrameInfo): SiteFrame {
  siteFrame = siteFrameFromInfo(frame);
  return siteFrame;
}

export function localToLngLat(point: LocalPoint): LngLat {
  return siteFrame.localToLngLat(point);
}

export function lngLatToLocal(lngLat: LngLat): LocalPoint {
  return siteFrame.lngLatToLocal(lngLat);
}

export function insideSite(point: LocalPoint): boolean {
  return siteFrame.inside(point);
}

function finitePositive(value: number, label: string): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label}必须是大于 0 的有限数。`);
  }
  return value;
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

/** True only when every corner of the rotated rectangle stays in the site. */
export function footprintInsideSite(x: number, y: number, theta: number, width: number, height: number): boolean {
  if (![x, y, theta].every(Number.isFinite)) return false;
  finitePositive(width, "建筑宽度");
  finitePositive(height, "建筑高度");
  const toleranceM = 1e-9;
  return footprintCorners(x, y, theta, width, height).every((point) => (
    point.x >= -toleranceM
    && point.y >= -toleranceM
    && point.x <= siteFrame.widthM + toleranceM
    && point.y <= siteFrame.heightM + toleranceM
  ));
}

/**
 * Clamp the center using the actual rotated corner extents. This keeps the
 * complete rectangle inside the site instead of only clamping its center.
 */
export function clampFootprintCenter(
  x: number,
  y: number,
  theta: number,
  width: number,
  height: number,
): LocalPoint {
  if (![x, y, theta].every(Number.isFinite)) {
    throw new Error("候选方案的位置和角度必须是有限数。");
  }
  finitePositive(width, "建筑宽度");
  finitePositive(height, "建筑高度");
  const offsets = footprintCorners(0, 0, theta, width, height);
  const offsetXs = offsets.map((point) => point.x);
  const offsetYs = offsets.map((point) => point.y);
  const minX = -Math.min(...offsetXs);
  const maxX = siteFrame.widthM - Math.max(...offsetXs);
  const minY = -Math.min(...offsetYs);
  const maxY = siteFrame.heightM - Math.max(...offsetYs);
  if (minX > maxX || minY > maxY) {
    throw new Error("建筑旋转后的尺寸大于当前选址区域。");
  }
  return {
    x: Math.min(maxX, Math.max(minX, x)),
    y: Math.min(maxY, Math.max(minY, y)),
  };
}

export function siteRing(): [number, number][] {
  return siteFrame.ring();
}
