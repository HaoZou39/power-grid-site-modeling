import {SiteEdit} from "./site_edit.js";
import type {SearchConfig} from "./site_edit.js";
import type {ParetoChoice} from "./decision_run.js";
import {measuredChoice} from "./decision_run.js";
import type {EvaluationInputs} from "./pose_evaluation.js";
import {evaluationKey} from "./pose_evaluation.js";
import {requireSolutionContext} from "./solution_context.js";
import type {SolutionContext} from "./solution_context.js";
import {mergeDisplayedChoices, visibleAtLevel} from "./solution_diversity.js";
import type {ParetoLayer} from "./solution_diversity.js";

export type PendingReevaluation = {
  format: 2; jobId: string; sceneId: string; context: SolutionContext;
  inputs: SearchConfig & EvaluationInputs; poses: ParetoChoice[];
  diversityLevel: ParetoLayer; selectedId: string | null;
  generation: number; recovered?: boolean;
};

function requireSupportedInputs(inputs: PendingReevaluation["inputs"]): void {
  if (inputs.include_demand !== false || !["allowed", "blocked"].includes(inputs.field_policy) || inputs.field_cost !== 0.5) {
    throw new Error("旧重评任务使用了已停用的需求点比较或农田成本设置。原记录已保留，请查看任务结果；放弃恢复后可按当前设置重新评价。");
  }
}

export function readReevaluation(raw: string): PendingReevaluation {
  const saved = JSON.parse(raw) as PendingReevaluation;
  requireSolutionContext(saved.context, saved.sceneId);
  if (saved.format !== 2 || !saved.jobId || !Array.isArray(saved.poses) || !saved.poses.length
    || !saved.inputs?.scene_revision || saved.inputs.scene_name !== saved.sceneId
    || ![1, 2, 3].includes(saved.diversityLevel)) {
    throw new Error("旧重评记录缺少完整工作区信息，已保留记录，请查看任务结果。");
  }
  requireSupportedInputs(saved.inputs);
  return saved;
}

export function restoreReevaluation(saved: PendingReevaluation): SiteEdit<ParetoChoice> {
  requireSolutionContext(saved.context, saved.sceneId);
  const inputs = saved.inputs;
  requireSupportedInputs(inputs);
  let edit = new SiteEdit<ParetoChoice>(saved.sceneId, inputs.rect_w_m, inputs.rect_h_m)
    .withImportedSiteForm(inputs).withSolutionContext(saved.context)
    .withPoses(saved.poses.filter(pose => visibleAtLevel(pose, saved.diversityLevel)));
  if (edit.poses.some(pose => pose.id === saved.selectedId)) edit = edit.selectPose(saved.selectedId!);
  return edit;
}

export function mergeReevaluation(
  pending: PendingReevaluation,
  data: unknown,
  current: SiteEdit<ParetoChoice>,
  pool: readonly ParetoChoice[],
  latest: {sceneId?: string; dataVersion: EvaluationInputs},
  generation: number,
) {
  const result = data as {coordinate_context: SolutionContext; data_version: {scene_revision: string};
    items: {id: string; metrics: Parameters<typeof measuredChoice>[1]}[]} | undefined;
  requireSolutionContext(result?.coordinate_context, pending.sceneId, pending.context.frame);
  if (latest.sceneId !== pending.sceneId || !result?.data_version?.scene_revision
    || result.data_version.scene_revision !== latest.dataVersion.scene_revision
    || generation !== pending.generation) {
    throw new Error("重评已完成，当前工作区已变化，结果和恢复记录已保留。");
  }
  const inputs = {...current.searchConfig(), ...latest.dataVersion};
  const retained = mergeDisplayedChoices(pool, current.poses);
  const source = pending.recovered && retained.length === 0 ? pending.poses : retained;
  const byId = new Map(source.map(pose => [pose.id, pose]));
  const keyOf = (pose: ParetoChoice) => evaluationKey(pending.sceneId, inputs, pose);
  for (const pose of pending.poses) {
    const live = byId.get(pose.id);
    if (!live || keyOf(live) !== evaluationKey(pending.sceneId, pending.inputs, pose)) {
      throw new Error("方案或参数已变化，结果和恢复记录已保留。");
    }
  }
  if (!Array.isArray(result?.items)) throw new Error("重评结果缺少方案评价。");
  const metrics = new Map(result.items.map(item => [item.id, item.metrics]));
  const merged = source.map(pose => metrics.has(pose.id) ? measuredChoice(pose, metrics.get(pose.id)!, keyOf(pose)) : pose);
  const shown = new Set(current.poses.map(pose => pose.id));
  return {pool: merged, edit: current.withPoses(merged.filter(pose =>
    pending.recovered && shown.size === 0 ? (pose.paretoLayer ?? 1) === 1 : shown.has(pose.id)))};
}
