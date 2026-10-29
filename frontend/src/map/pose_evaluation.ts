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

const ZONE_FIELDS = new Set<(typeof FIELDS)[number]>(["exclusion_zones", "feasible_zones"]);

/** Imported history has CSV numbers, but they are not an evaluation of the current constraints. */
export const HISTORY_EVALUATION = "history";

export type PoseFreshness = "current" | "zone-stale" | "history-stale" | "revision-stale" | "pending";

export function isAwaitingReview(freshness: PoseFreshness): boolean {
  return freshness === "zone-stale" || freshness === "history-stale" || freshness === "revision-stale";
}

export function evaluationKey(sceneId: string, config: EvaluationInputs, pose: { x: number; y: number; theta: number }): string {
  return JSON.stringify(evaluationParts(sceneId, config, pose));
}

function evaluationParts(sceneId: string, config: EvaluationInputs, pose: { x: number; y: number; theta: number }): unknown[] {
  return [sceneId, ...FIELDS.map((field) => config[field] ?? null), pose.x, pose.y, pose.theta];
}

/** Zone-only drift stays on the map. Pose moves and other inputs stay on the automatic path. */
export function poseFreshness(
  evaluatedFor: string | undefined,
  sceneId: string,
  config: EvaluationInputs,
  pose: { x: number; y: number; theta: number; original?: { x: number; y: number; theta: number } },
): PoseFreshness {
  if (evaluatedFor === HISTORY_EVALUATION) {
    const origin = pose.original;
    const moved = origin !== undefined && (
      origin.x !== pose.x || origin.y !== pose.y || origin.theta !== pose.theta
    );
    return moved ? "pending" : "history-stale";
  }
  if (!evaluatedFor) return "pending";
  const current = evaluationParts(sceneId, config, pose);
  let previous: unknown;
  try {
    previous = JSON.parse(evaluatedFor);
  } catch {
    return "pending";
  }
  if (!Array.isArray(previous) || previous.length !== current.length) return "pending";
  let zonesDiffer = false;
  let revisionDiffer = false;
  for (let index = 0; index < current.length; index += 1) {
    if (JSON.stringify(current[index]) === JSON.stringify(previous[index])) continue;
    const field = FIELDS[index - 1];
    if (field === "scene_revision" || field === "landuse_revision") {
      revisionDiffer = true;
      continue;
    }
    if (field && ZONE_FIELDS.has(field)) {
      zonesDiffer = true;
      continue;
    }
    return "pending";
  }
  if (revisionDiffer) return "revision-stale";
  return zonesDiffer ? "zone-stale" : "current";
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

/** Automatic evaluation. A zone-only mismatch is excluded so it cannot start a request. */
export function autoPendingPoses<P extends { evaluatedFor?: string }>(
  poses: readonly P[],
  keyOf: (pose: P) => string,
  inFlight: ReadonlySet<string>,
  failed: ReadonlyMap<string, string>,
  freshnessOf: (pose: P) => PoseFreshness,
): P[] {
  return pendingPoses(poses, keyOf, inFlight, failed).filter((pose) => !isAwaitingReview(freshnessOf(pose)));
}

export function zoneStalePoses<P>(poses: readonly P[], freshnessOf: (pose: P) => PoseFreshness): P[] {
  return poses.filter((pose) => freshnessOf(pose) === "zone-stale");
}

export function stalePoses<P>(poses: readonly P[], freshnessOf: (pose: P) => PoseFreshness): P[] {
  return poses.filter((pose) => isAwaitingReview(freshnessOf(pose)));
}

export function batches<T>(items: readonly T[], size = POSE_BATCH_LIMIT): T[][] {
  if (!Number.isInteger(size) || size < 1) throw new Error("评价批次大小必须是正整数。");
  const result: T[][] = [];
  for (let i = 0; i < items.length; i += size) result.push(items.slice(i, i + size));
  return result;
}
