import type { LocalPoint, SiteFrame } from "../map/site_frame.js";
import type { RoutingMapState } from "./routing_layer.js";
import type { RoutingSolution } from "./routing_result.js";

type ScreenPoint = { x: number; y: number };

/** Match the closest displayed segment in screen pixels; the report keeps the saved values. */
export function nearestRoutingSpan(route: RoutingSolution, cursor: ScreenPoint, project: (point: LocalPoint) => ScreenPoint): number | null {
  if (route.spans.length !== route.points.length - 1) return null;
  let nearest = -1, distance = Infinity;
  for (let i = 0; i < route.points.length - 1; i += 1) {
    const a = project(route.points[i]), b = project(route.points[i + 1]);
    const dx = b.x - a.x, dy = b.y - a.y, length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((cursor.x - a.x) * dx + (cursor.y - a.y) * dy) / length)) : 0;
    const gap = (cursor.x - a.x - t * dx) ** 2 + (cursor.y - a.y - t * dy) ** 2;
    if (gap < distance) { nearest = i; distance = gap; }
  }
  return nearest < 0 ? null : nearest;
}

export function routingHoverText(properties: Record<string, unknown>, state: RoutingMapState, frame: SiteFrame, spanIndex: number | null = null): string | null {
  const route = state.routes.find((item) => item.id === properties.route_id);
  const label = route && state.routeNumbers?.[route.id] ? `线路 ${state.routeNumbers[route.id]}` : "线路";
  const stale = state.resultStale ? "\n线路指标属于修改前的配置" : "";
  if (properties.kind === "route" && route) {
    const o = route.objectives;
    const span = spanIndex !== null ? route.spans[spanIndex] : undefined;
    const detail = span ? `\n第 ${spanIndex! + 1} 档：水平 ${span.horizontal_m.toFixed(1)} m，三维 ${span.length_3d_m.toFixed(1)} m，跨越 ${span.crossing_3d_m.toFixed(1)} m` : "";
    return `${label}\n新增塔 ${o.tower_count} 座 · 三维长度 ${o.length_3d_m.toFixed(1)} m\n水平曲折 ${(o.bend_sum_rad * 180 / Math.PI).toFixed(1)}° · 跨越 ${o.crossing_3d_m.toFixed(1)} m${detail}${stale}\n净空未校核`;
  }
  if (properties.kind === "endpoint" && (properties.endpoint === "start" || properties.endpoint === "end")) {
    const point = state[properties.endpoint];
    if (!point) return null;
    const location = frame.localToLngLat(point);
    return `${properties.endpoint === "start" ? "起点" : "终点"}（当前接入点）\n经度 ${location.lng.toFixed(7)}° · 纬度 ${location.lat.toFixed(7)}°`;
  }
  if (properties.kind !== "tower" || !route || typeof properties.point_index !== "number") return null;
  const point = route.points[properties.point_index];
  if (!point || point.role !== "tower") return null;
  const index = route.points.slice(0, properties.point_index).filter((item) => item.role === "tower").length;
  const location = frame.localToLngLat(point);
  const elevation = typeof point.z === "number" && Number.isFinite(point.z) ? `${point.z.toFixed(1)} m` : "无数据";
  const turn = route.turns_deg[index], slope = route.tower_slopes_deg[index];
  return `${label} · 塔位 ${index + 1}\n经度 ${location.lng.toFixed(7)}° · 纬度 ${location.lat.toFixed(7)}°\n地面高程 ${elevation}\n水平转角 ${Number.isFinite(turn) ? `${turn.toFixed(1)}°` : "无数据"} · 塔基最大坡度 ${typeof slope === "number" && Number.isFinite(slope) ? `${slope.toFixed(1)}°` : "无数据"}${stale}`;
}
