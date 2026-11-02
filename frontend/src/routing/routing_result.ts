import type { SceneFrameInfo } from "../map/site_frame.js";

export type RoutingObjectives = { tower_count: number; length_3d_m: number; bend_sum_rad: number; crossing_3d_m: number };
export type RoutingSolution = {
  id: string;
  objectives: RoutingObjectives;
  is_feasible: boolean;
  is_pareto: boolean;
  violations: Record<string, number>;
  points: { x: number; y: number; z: number | null; role: "start" | "tower" | "end" }[];
  spans: { horizontal_m: number; length_3d_m: number; crossing_3d_m: number }[];
  turns_deg: number[];
  tower_slopes_deg: (number | null)[];
};
export type RoutingBundle = { schema_version: number; problem_type: "routing"; scene_name: string; frame: SceneFrameInfo; routes: RoutingSolution[] };

export type RoutingSort = { objective: keyof RoutingObjectives; direction: "ascending" | "descending" };

export function nextRoutingSort(current: RoutingSort | null, objective: keyof RoutingObjectives): RoutingSort {
  return { objective, direction: current?.objective === objective && current.direction === "ascending" ? "descending" : "ascending" };
}

export function sortRoutingSolutions(routes: readonly RoutingSolution[], sort: RoutingSort | null) {
  const rows = routes.map((route, index) => ({ route, index }));
  if (sort) rows.sort((a, b) => {
    const difference = a.route.objectives[sort.objective] - b.route.objectives[sort.objective];
    return (sort.direction === "ascending" ? difference : -difference) || a.index - b.index;
  });
  return rows;
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
    if (route.is_feasible && (!Array.isArray(route.spans) || route.spans.some((span) => !span
      || ![span.horizontal_m, span.length_3d_m, span.crossing_3d_m].every(Number.isFinite))
      || !Array.isArray(route.turns_deg) || !route.turns_deg.every(Number.isFinite)
      || !Array.isArray(route.tower_slopes_deg) || !route.tower_slopes_deg.every((value) => value === null || Number.isFinite(value)))) {
      throw new Error("线路逐档或塔基报告无效。");
    }
  }
  return result;
}
