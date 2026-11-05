import type { ParetoChoice } from "./decision_run.js";
import type { SiteEdit } from "./site_edit.js";
import { mergeDisplayedChoices } from "./solution_diversity.js";

export type FastSavePose = {
  id: string;
  x: number;
  y: number;
  theta: number;
  manual: boolean;
  paretoLayer: number;
  derivedFrom: string;
};

/** Recorded only after one complete automatic result has loaded. */
export type FastSaveProvenance = {
  sourceExperimentId: string;
  jobId: string;
  sceneId: string;
  frameId: string;
  sceneRevision: string;
  configJson: string;
  poses: FastSavePose[];
};

export type FastSaveScene = {
  sceneId: string;
  frameId: string | null;
  sceneRevision: string | undefined;
};

function stableJson(value: unknown): string {
  const ordered = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(ordered);
    if (item && typeof item === "object") {
      return Object.fromEntries(Object.keys(item).sort().map((key) => [key, ordered((item as Record<string, unknown>)[key])]));
    }
    return item;
  };
  return JSON.stringify(ordered(value));
}

function poseSnapshot(choices: readonly ParetoChoice[]): FastSavePose[] {
  return choices.map((pose) => ({
    id: pose.id,
    x: pose.x,
    y: pose.y,
    theta: pose.theta,
    manual: pose.manual === true,
    paretoLayer: pose.paretoLayer ?? 1,
    derivedFrom: pose.derivedFrom ?? "",
  }));
}

/** Snapshot the full retained set. Display-only actions do not call this. */
export function captureFastSaveProvenance(
  edit: SiteEdit<ParetoChoice>,
  pool: readonly ParetoChoice[],
  source: { experimentId: string; jobId: string; sceneId: string; frameId: string | null; sceneRevision: string | undefined },
): FastSaveProvenance | null {
  if (!source.experimentId || !source.jobId || !source.sceneId || !source.frameId || !source.sceneRevision) return null;
  const choices = mergeDisplayedChoices(pool, edit.poses);
  if (!choices.length || choices.some((pose) => pose.manual || pose.derivedFrom)) return null;
  const poses = poseSnapshot(choices);
  if (new Set(poses.map((pose) => pose.id)).size !== poses.length) return null;
  return {
    sourceExperimentId: source.experimentId,
    jobId: source.jobId,
    sceneId: source.sceneId,
    frameId: source.frameId,
    sceneRevision: source.sceneRevision,
    configJson: stableJson(edit.searchConfig()),
    poses,
  };
}

/** Null unless the retained set and engineering config still match the loaded result. */
export function fastSaveSourceExperimentId(
  provenance: FastSaveProvenance | null,
  edit: SiteEdit<ParetoChoice>,
  pool: readonly ParetoChoice[],
  scene: FastSaveScene,
  landuseBlocked: boolean,
): string | null {
  if (!provenance || landuseBlocked) return null;
  if (scene.sceneId !== provenance.sceneId || scene.frameId !== provenance.frameId || scene.sceneRevision !== provenance.sceneRevision) {
    return null;
  }
  if (stableJson(edit.searchConfig()) !== provenance.configJson) return null;
  const choices = mergeDisplayedChoices(pool, edit.poses);
  const poses = poseSnapshot(choices);
  if (poses.length !== provenance.poses.length) return null;
  const saved = new Map(provenance.poses.map((pose) => [pose.id, pose]));
  for (const pose of poses) {
    const original = saved.get(pose.id);
    if (!original || pose.x !== original.x || pose.y !== original.y || pose.theta !== original.theta
      || pose.manual !== original.manual || pose.paretoLayer !== original.paretoLayer || pose.derivedFrom !== original.derivedFrom) {
      return null;
    }
  }
  return provenance.sourceExperimentId;
}

/** Merge current edits into the retained pool; deleted IDs must already be absent. */
export function experimentSaveBody(
  name: string,
  edit: SiteEdit<ParetoChoice>,
  pool: readonly ParetoChoice[],
  sourceId: string | null,
  fastSaveSourceId: string | null = null,
) {
  const elevationProblem = edit.elevationProblem();
  if (elevationProblem) throw new Error(elevationProblem);
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 120) throw new Error("请输入 1 到 120 个字符的实验名称。");
  const choices = mergeDisplayedChoices(pool, edit.poses);
  if (!choices.length) throw new Error("暂无可保存的方案。");
  return {
    name: trimmed, ...edit.searchConfig(), source_experiment_id: sourceId,
    ...(fastSaveSourceId ? { fast_save_source_experiment_id: fastSaveSourceId } : {}),
    poses: choices.map((pose) => ({
      id: pose.id, x: pose.x, y: pose.y, theta: pose.theta,
      manual: pose.manual === true, pareto_layer: pose.paretoLayer ?? 1,
      ...(pose.derivedFrom ? { derived_from: pose.derivedFrom } : {}),
    })),
  };
}
