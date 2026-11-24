import type { LocalPoint, SiteFrame } from "../map/site_frame.js";
import type { RoutingMapState } from "./routing_layer.js";
import { finiteNumber, formatFinite } from "./routing_result.js";
import type { RoutingSolution } from "./routing_result.js";

type ScreenPoint = { x: number; y: number };
const metric = (label: string, value: unknown, unit: string) => {
  const text = formatFinite(value);
  return text === "" ? "" : `${label} ${text}${unit}`;
};

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
    const spanParts = span ? [metric("水平", span.horizontal_m, " m"), metric("三维", span.length_3d_m, " m"), metric("跨越", span.crossing_3d_m, " m")].filter(Boolean) : [];
    const detail = spanParts.length ? `\n第 ${spanIndex! + 1} 档：${spanParts.join("，")}` : "";
    const bend = finiteNumber(o.bend_sum_rad);
    const objectives = [
      `新增塔 ${finiteNumber(o.tower_count) === null ? "不可用" : formatFinite(o.tower_count, 0)} 座`,
      metric("三维长度", o.length_3d_m, " m") || "三维长度不可用",
      `水平曲折 ${bend === null ? "不可用" : formatFinite(bend * 180 / Math.PI)}°`,
      metric("跨越", o.crossing_3d_m, " m") || "跨越不可用",
      metric("既有线路影响带", route.existing_line_crossing_length_m ?? 0, " m"),
      `既有线路平面交叉 ${route.existing_line_crossing_count ?? 0} 次`,
    ];
    return `${label}${route.is_feasible ? "" : " · 不可行"}\n${objectives[0]} · ${objectives[1]}\n${objectives[2]} · ${objectives[3]}${detail}${stale}`;
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
  const elevation = metric("地面高程", point.z, " m");
  const turn = metric("水平转角", route.turns_deg[index], "°");
  const slope = metric("塔基最大坡度", route.tower_slopes_deg[index], "°");
  const metrics = [elevation, turn, slope].filter(Boolean);
  return `${label} · 塔位 ${index + 1}\n经度 ${location.lng.toFixed(7)}° · 纬度 ${location.lat.toFixed(7)}°${metrics.length ? `\n${metrics.join(" · ")}` : ""}${stale}`;
}
