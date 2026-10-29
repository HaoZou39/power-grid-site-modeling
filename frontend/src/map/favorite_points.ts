import type { LocalPoint, SiteFrame } from "./site_frame.js";
import { footprintCorners } from "./site_frame.js";

export type FavoritePointRecord = {
  id: string;
  scene_id: string;
  longitude: number;
  latitude: number;
  width_m: number;
  height_m: number;
  bearing_deg: number;
  created_at: string;
  updated_at: string;
};

export type FavoritePointPose = {
  center: LocalPoint;
  theta: number;
  bearingDeg: number;
  widthM: number;
  heightM: number;
};

export type FavoritePointInput = Pick<FavoritePointRecord, "longitude" | "latitude" | "width_m" | "height_m" | "bearing_deg">;

export function favoritePoseSnapshot(center: LocalPoint, theta: number, widthM: number, heightM: number, frame: SiteFrame): FavoritePointInput {
  const { lng, lat } = frame.localToLngLat(center);
  return { longitude: lng, latitude: lat, width_m: widthM, height_m: heightM, bearing_deg: thetaToBearing(theta, widthM, heightM, frame, center) };
}

export function favoriteMatches(favorite: FavoritePointRecord, sceneId: string, pose: FavoritePointInput): boolean {
  const angle = Math.abs(favorite.bearing_deg - pose.bearing_deg);
  return favorite.scene_id === sceneId
    && Math.abs(favorite.longitude - pose.longitude) < 1e-8
    && Math.abs(favorite.latitude - pose.latitude) < 1e-8
    && Math.abs(favorite.width_m - pose.width_m) < 1e-6
    && Math.abs(favorite.height_m - pose.height_m) < 1e-6
    && Math.min(angle, 360 - angle) < 1e-6;
}

export function bearingToTheta(bearingDeg: number, widthM: number, heightM: number, frame?: SiteFrame, center?: LocalPoint): number {
  if (!Number.isFinite(bearingDeg)) throw new Error("方位角必须是有限数字。");
  if (frame && center) return frame.thetaFromBearing(bearingDeg - (widthM >= heightM ? 0 : 90), center);
  const offset = widthM >= heightM ? 90 : 180;
  return normalizeDegrees(bearingDeg - offset) * Math.PI / 180;
}

export function thetaToBearing(theta: number, widthM: number, heightM: number, frame?: SiteFrame, center?: LocalPoint): number {
  if (!Number.isFinite(theta)) throw new Error("旋转角度必须是有限数字。");
  if (frame && center) return normalizeDegrees(frame.widthBearing(theta, center) + (widthM >= heightM ? 0 : 90));
  const offset = widthM >= heightM ? 90 : 180;
  return normalizeDegrees(theta * 180 / Math.PI + offset);
}

export function normalizeDegrees(degrees: number): number {
  if (!Number.isFinite(degrees)) throw new Error("方位角必须是有限数字。");
  return ((degrees % 360) + 360) % 360;
}

export function favoritePointPose(
  favorite: FavoritePointRecord,
  frame: SiteFrame,
): FavoritePointPose {
  const center = frame.lngLatToLocal({ lng: favorite.longitude, lat: favorite.latitude });
  return {
    center,
    theta: bearingToTheta(favorite.bearing_deg, favorite.width_m, favorite.height_m, frame, center),
    bearingDeg: favorite.bearing_deg,
    widthM: favorite.width_m,
    heightM: favorite.height_m,
  };
}

export function favoritePoseInsideFrame(
  center: LocalPoint,
  theta: number,
  widthM: number,
  heightM: number,
  frame: SiteFrame,
): boolean {
  if (![center.x, center.y, theta, widthM, heightM].every(Number.isFinite)) return false;
  if (widthM <= 0 || heightM <= 0) return false;
  return footprintCorners(center.x, center.y, theta, widthM, heightM)
    .every((corner) => frame.insideStudy(corner));
}
