import type { SearchConfig } from "./site_edit.js";

export const POSE_BATCH_LIMIT = 200;
export type EvaluationInputs = Partial<SearchConfig> & {
  road_product_id?: string;
  farmland_content_sha256?: string;
  landuse_revision?: number;
  frame_id?: string | null;
  scene_revision?: string;
};

const FIELDS = [
  "rect_w_m", "rect_h_m", "mountain_policy", "field_policy", "field_cost",
  "exclusion_zones", "feasible_zones", "road_setback_m", "water_setback_m", "highway_setback_m",
  "origin_x", "origin_y", "diagonal_access", "road_product_id", "farmland_content_sha256",
  "landuse_revision", "frame_id", "scene_revision",
] as const;

export function evaluationKey(sceneId: string, config: EvaluationInputs, pose: { x: number; y: number; theta: number }): string {
  return JSON.stringify([sceneId, ...FIELDS.map((field) => config[field] ?? null), pose.x, pose.y, pose.theta]);
}

export function pendingPoses<P extends { evaluatedFor?: string }>(
  poses: readonly P[], keyOf: (pose: P) => string,
  inFlight: ReadonlySet<string>, failed: ReadonlyMap<string, string>,
): P[] {
  return poses.filter((pose) => {
    const key = keyOf(pose);
    return pose.evaluatedFor !== key && !inFlight.has(key) && !failed.has(key);
  });
}

export function batches<T>(items: readonly T[], size = POSE_BATCH_LIMIT): T[][] {
  if (!Number.isInteger(size) || size < 1) throw new Error("评价批次大小必须是正整数。");
  const result: T[][] = [];
  for (let i = 0; i < items.length; i += size) result.push(items.slice(i, i + size));
  return result;
}
