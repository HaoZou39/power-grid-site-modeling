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

export function parseRoutingResult(text: string, sceneName: string, frame: SceneFrameInfo): RoutingBundle {
  const result = JSON.parse(text) as RoutingBundle;
  if (result.problem_type !== "routing" || result.schema_version !== 1 || result.scene_name !== sceneName || !Array.isArray(result.routes)) {
    throw new Error("这份产物不是当前场景的有效选线结果。");
  }
  const identity = (value: SceneFrameInfo) => JSON.stringify([value.crs, value.transform, value.width, value.height]);
  if (!result.frame || identity(result.frame) !== identity(frame)) throw new Error("历史结果的网格已变化，不能套用当前场景坐标。");
  for (const route of result.routes) {
    if (!route.id || !Array.isArray(route.points) || route.points.length < 2
      || route.points.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) throw new Error("线路接点数据无效。");
    if (route.is_feasible && ["tower_count", "length_3d_m", "bend_sum_rad", "crossing_3d_m"].some(
      (key) => !Number.isFinite(route.objectives?.[key as keyof RoutingObjectives]))) throw new Error("可行线路的目标值无效。");
  }
  return result;
}
