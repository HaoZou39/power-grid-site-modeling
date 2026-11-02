import {SiteEdit} from "./site_edit.js";
import type {SearchConfig} from "./site_edit.js";
import type {ParetoChoice} from "./decision_run.js";
import type {EvaluationInputs} from "./pose_evaluation.js";
import {requireSolutionContext} from "./solution_context.js";
import type {SolutionContext} from "./solution_context.js";
import {visibleAtLevel} from "./solution_diversity.js";
import type {ParetoLayer} from "./solution_diversity.js";

export type PendingReevaluation = {
  format: 2; jobId: string; sceneId: string; context: SolutionContext;
  inputs: SearchConfig & EvaluationInputs; poses: ParetoChoice[];
  diversityLevel: ParetoLayer; selectedId: string | null;
  generation: number; recovered?: boolean;
};

export function readReevaluation(raw: string): PendingReevaluation {
  const saved = JSON.parse(raw) as PendingReevaluation;
  requireSolutionContext(saved.context, saved.sceneId);
  if (saved.format !== 2 || !saved.jobId || !Array.isArray(saved.poses) || !saved.poses.length
    || !saved.inputs?.scene_revision || saved.inputs.scene_name !== saved.sceneId
    || ![1, 2, 3].includes(saved.diversityLevel)) {
    throw new Error("旧重评记录缺少完整工作区信息，已保留记录，请查看任务结果。");
  }
  return saved;
}

export function restoreReevaluation(saved: PendingReevaluation): SiteEdit<ParetoChoice> {
  requireSolutionContext(saved.context, saved.sceneId);
  const inputs = saved.inputs;
  let edit = new SiteEdit<ParetoChoice>(saved.sceneId, inputs.rect_w_m, inputs.rect_h_m)
    .withImportedSiteForm(inputs).withSolutionContext(saved.context)
    .withPoses(saved.poses.filter(pose => visibleAtLevel(pose, saved.diversityLevel)));
  if (edit.poses.some(pose => pose.id === saved.selectedId)) edit = edit.selectPose(saved.selectedId!);
  return edit;
}
