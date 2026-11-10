import { footprintCorners, type LocalPoint, type SiteFrame } from "./site_frame.js";

function localCoordinate(longitude: string, latitude: string, frame: SiteFrame, outsideMessage: string, current?: LocalPoint): LocalPoint {
  const lng = Number(longitude);
  const lat = Number(latitude);
  if (!longitude.trim() || !latitude.trim() || !Number.isFinite(lng) || !Number.isFinite(lat)
    || Math.abs(lng) > 180 || Math.abs(lat) > 90) {
    throw new Error("请输入有效的经纬度，经度范围为 -180° 至 180°，纬度范围为 -90° 至 90°。");
  }
  const previous = current && frame.localToLngLat(current);
  let point: LocalPoint;
  try {
    // Confirming unchanged values must not move the point through projection round-off.
    point = current && previous?.lng === lng && previous.lat === lat
      ? { x: current.x, y: current.y } : frame.lngLatToLocal({ lng, lat });
  } catch {
    throw new Error("无法将该经纬度转换到当前场景。");
  }
  if (![point.x, point.y].every(Number.isFinite) || !frame.inside(point)) {
    throw new Error(outsideMessage);
  }
  return point;
}

export function originCoordinatePosition(longitude: string, latitude: string, frame: SiteFrame, current?: LocalPoint): LocalPoint {
  return localCoordinate(longitude, latitude, frame, "该位置超出当前场景范围，请输入范围内的坐标。", current);
}

export function coordinatePosition(
  longitude: string, latitude: string, frame: SiteFrame,
  theta: number, width: number, height: number, current?: LocalPoint,
): LocalPoint {
  const outsideMessage = "该位置会让建筑超出选址范围，请输入范围内的坐标。";
  const point = localCoordinate(longitude, latitude, frame, outsideMessage, current);
  const corners = footprintCorners(point.x, point.y, theta, width, height);
  // Origins only need the grid; buildings must fit the same study domain as dragging/rotation.
  if (!corners.every((corner) => frame.insideStudy(corner))) {
    throw new Error(outsideMessage);
  }
  return point;
}
