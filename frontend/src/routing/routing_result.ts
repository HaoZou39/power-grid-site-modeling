import type { SceneFrameInfo } from "../map/site_frame.js";

export type RoutingObjectives = { tower_count: number; length_3d_m: number; bend_sum_rad: number; crossing_3d_m: number };
export type RoutingSolution = {
  id: string;
  objectives: RoutingObjectives;
  is_feasible: boolean;
  is_pareto: boolean;
  violations: Record<string, number>;
  points: { x: number; y: number; z: number | null; role: "start" | "tower" | "end" }[];
  spans: { horizontal_m: number | null; length_3d_m: number | null; crossing_3d_m: number | null }[];
  turns_deg: (number | null)[];
  tower_slopes_deg: (number | null)[];
  tortuosity_k?: number | null;
  tortuosity_status?: "ok" | "invalid";
};
export type RoutingBundle = { schema_version: number; problem_type: "routing"; scene_name: string; frame: SceneFrameInfo; routes: RoutingSolution[] };

export type RoutingSortKey = keyof RoutingObjectives | "tortuosity_k";
export type RoutingSort = { objective: RoutingSortKey; direction: "ascending" | "descending" };

export function retainedRoutingChoices(bundle: RoutingBundle | null, summary: Record<string, unknown> | null): RoutingSolution[] {
  if (summary?.is_case === true || summary?.algorithm === "routing_workspace") return bundle?.routes ?? [];
  return bundle?.routes.filter((route) => route.is_pareto && route.is_feasible) ?? [];
}

export function nextRoutingSort(current: RoutingSort | null, objective: RoutingSortKey): RoutingSort {
  return { objective, direction: current?.objective === objective && current.direction === "ascending" ? "descending" : "ascending" };
}

export function sortRoutingSolutions(routes: readonly RoutingSolution[], sort: RoutingSort | null) {
  const rows = routes.map((route, index) => ({ route, index }));
  if (sort) rows.sort((a, b) => {
    const left = sortValue(a.route, sort.objective);
    const right = sortValue(b.route, sort.objective);
    if (left == null || right == null) return left == null && right == null ? a.index - b.index : left == null ? 1 : -1;
    const difference = left - right;
    return (sort.direction === "ascending" ? difference : -difference) || a.index - b.index;
  });
  return rows;
}

function sortValue(route: RoutingSolution, key: RoutingSortKey): number | null {
  if (key === "tortuosity_k") return routeTortuosity(route).k;
  const value = route.objectives[key];
  return Number.isFinite(value) ? value : null;
}

export function parseRoutingResult(text: string, sceneName: string, frame: SceneFrameInfo): RoutingBundle {
  const result = JSON.parse(text) as RoutingBundle;
  if (!result || result.problem_type !== "routing" || result.schema_version !== 1 || result.scene_name !== sceneName || !Array.isArray(result.routes)) {
    throw new Error("这份产物不是当前场景的有效选线结果。");
  }
  const identity = (value: SceneFrameInfo) => JSON.stringify([value.crs, value.transform, value.width, value.height]);
  if (!result.frame || identity(result.frame) !== identity(frame)) throw new Error("历史结果的网格已变化，不能套用当前场景坐标。");
  const ids = new Set<string>();
  for (const route of result.routes) {
    if (!route || typeof route.id !== "string" || !route.id || ids.has(route.id)
      || typeof route.is_feasible !== "boolean" || typeof route.is_pareto !== "boolean"
      || !Array.isArray(route.points) || route.points.length < 2
      || route.points.some((point) => !point || !Number.isFinite(point.x) || !Number.isFinite(point.y))) throw new Error("线路接点数据无效。");
    ids.add(route.id);
    if (route.is_feasible && ["tower_count", "length_3d_m", "bend_sum_rad", "crossing_3d_m"].some(
      (key) => !Number.isFinite(route.objectives?.[key as keyof RoutingObjectives]))) throw new Error("可行线路的目标值无效。");
    normalizeOptionalReport(route);
    if (route.tortuosity_status != null && route.tortuosity_status !== "ok" && route.tortuosity_status !== "invalid") {
      throw new Error("线路曲折系数无效。");
    }
    if (route.tortuosity_status === "invalid" && route.tortuosity_k != null) throw new Error("线路曲折系数无效。");
    if (route.tortuosity_status === "ok" && !Number.isFinite(route.tortuosity_k)) throw new Error("线路曲折系数无效。");
    if (route.tortuosity_k != null && !Number.isFinite(route.tortuosity_k)) throw new Error("线路曲折系数无效。");
    if (route.spans.some((span) => !span || !optionalFinite(span.horizontal_m) || !optionalFinite(span.length_3d_m) || !optionalFinite(span.crossing_3d_m))
      || !route.turns_deg.every(optionalFinite) || !route.tower_slopes_deg.every(optionalFinite)) {
      throw new Error("线路逐档或塔基报告无效。");
    }
  }
  return result;
}

function optionalFinite(value: unknown): boolean {
  return value == null || (typeof value === "number" && Number.isFinite(value));
}

function normalizeOptionalReport(route: RoutingSolution) {
  if (route.spans == null) route.spans = [];
  if (route.turns_deg == null) route.turns_deg = [];
  if (route.tower_slopes_deg == null) route.tower_slopes_deg = [];
  if (!Array.isArray(route.spans) || !Array.isArray(route.turns_deg) || !Array.isArray(route.tower_slopes_deg)) {
    throw new Error("线路逐档或塔基报告无效。");
  }
}

export function horizontalTortuosity(points: readonly { x: number; y: number }[]): number | null {
  if (points.length < 2 || points.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) return null;
  let length = 0;
  for (let index = 1; index < points.length; index += 1) {
    length += Math.hypot(points[index].x - points[index - 1].x, points[index].y - points[index - 1].y);
  }
  const straight = Math.hypot(points[points.length - 1].x - points[0].x, points[points.length - 1].y - points[0].y);
  if (!Number.isFinite(length) || !Number.isFinite(straight) || straight <= 0) return null;
  return length / straight;
}

export function routeTortuosity(route: RoutingSolution): { status: "ok" | "invalid"; k: number | null } {
  if (route.tortuosity_status === "invalid") return { status: "invalid", k: null };
  if (route.tortuosity_status === "ok" && Number.isFinite(route.tortuosity_k)) return { status: "ok", k: route.tortuosity_k ?? null };
  const computed = horizontalTortuosity(route.points);
  return computed == null ? { status: "invalid", k: null } : { status: "ok", k: computed };
}

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatFinite(value: unknown, digits = 1): string {
  const number = finiteNumber(value);
  return number === null ? "" : number.toFixed(digits);
}

export function finiteEntries(values: readonly unknown[]): { index: number; text: string }[] {
  return values.flatMap((value, index) => {
    const text = formatFinite(value);
    return text === "" ? [] : [{ index: index + 1, text }];
  });
}

export const SPAN_COLUMNS = [
  { key: "horizontal_m", label: "水平 m" },
  { key: "length_3d_m", label: "三维 m" },
  { key: "crossing_3d_m", label: "跨越 m" },
] as const;

export function visibleSpanColumns(spans: readonly { horizontal_m?: unknown; length_3d_m?: unknown; crossing_3d_m?: unknown }[]) {
  return SPAN_COLUMNS.filter((column) => spans.some((span) => finiteNumber(span?.[column.key]) !== null));
}
