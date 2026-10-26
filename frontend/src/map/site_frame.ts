import proj4, { type Converter } from "proj4";

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
  private readonly projection: Converter;
  constructor(
    readonly originX: number,
    readonly originY: number,
    readonly xScale: number,
    readonly yScale: number,
    readonly widthM: number,
    readonly heightM: number,
    readonly crs = "EPSG:3857",
    readonly displayFrame?: SceneFrameInfo,
  ) {
    const utm = /^EPSG:(326|327)([0-9]{2})$/.exec(crs);
    if (utm) {
      proj4.defs(crs, `+proj=utm +zone=${Number(utm[2])} ${utm[1] === "327" ? "+south" : ""} +datum=WGS84 +units=m +no_defs`);
    }
    this.projection = proj4(crs, "EPSG:4326");
  }

  localToLngLat(point: LocalPoint): LngLat {
    const [lng, lat] = this.projection.forward([
      this.originX + point.x * this.xScale,
      this.originY + point.y * this.yScale,
    ]);
    return { lng, lat };
  }

  lngLatToLocal(lngLat: LngLat): LocalPoint {
    const [x, y] = this.projection.inverse([lngLat.lng, lngLat.lat]);
    return {
      x: (x - this.originX) / this.xScale,
      y: (y - this.originY) / this.yScale,
    };
  }

  /** Bearing of the local width axis, clockwise from true north. */
  widthBearing(theta: number, point: LocalPoint): number {
    return ((theta - this.northTheta(point)) * 180 / Math.PI % 360 + 360) % 360;
  }

  thetaFromBearing(bearing: number, point: LocalPoint): number {
    return bearing * Math.PI / 180 + this.northTheta(point);
  }

  private northTheta(point: LocalPoint): number {
    if (this.crs === "EPSG:3857") return -Math.PI / 2;
    const ll = this.localToLngLat(point);
    const north = this.lngLatToLocal({ lng: ll.lng, lat: ll.lat + 1e-5 });
    return Math.atan2(north.y - point.y, north.x - point.x);
  }

  imageRing(): [number, number][] {
    return this.displayFrame ? siteFrameFromInfo(this.displayFrame).ring() : this.ring();
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
  display_frame?: SceneFrameInfo;
  frame_id?: string;
  scene_revision?: string;
  units?: string;
};

/** Activate a prepared scene before mounting its map and local editing workspace. */
export function siteFrameFromInfo(frame: SceneFrameInfo): SiteFrame {
  const [a, b, c, d, e, f] = frame.transform;
  const validCrs = frame.crs === "EPSG:3857" || /^EPSG:(326|327)(0[1-9]|[1-5][0-9]|60)$/.test(frame.crs);
  if (!validCrs || [a, b, c, d, e, f, frame.width, frame.height].some((value) => !Number.isFinite(value))) {
    throw new Error("场景坐标必须是有效的 EPSG:3857 或 WGS84 UTM 投影网格。");
  }
  if (a <= 0 || e >= 0 || Math.abs(b) > 1e-8 || Math.abs(d) > 1e-8 || frame.width <= 0 || frame.height <= 0) {
    throw new Error("当前地图暂不支持旋转或无效的场景栅格。");
  }
  return new SiteFrame(c, f, a, e, frame.width, frame.height, frame.crs, frame.display_frame);
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
