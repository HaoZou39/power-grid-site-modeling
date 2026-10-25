import type { ParetoChoice } from "./decision_run.js";
import type { SiteEdit } from "./site_edit.js";
import { mergeDisplayedChoices } from "./solution_diversity.js";

/** Merge current edits into the retained pool; deleted IDs must already be absent. */
export function experimentSaveBody(
  name: string, edit: SiteEdit<ParetoChoice>, pool: readonly ParetoChoice[], sourceId: string | null,
) {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 120) throw new Error("请输入 1 到 120 个字符的实验名称。");
  const choices = mergeDisplayedChoices(pool, edit.poses);
  if (!choices.length) throw new Error("暂无可保存的方案。");
  return {
    name: trimmed, ...edit.searchConfig(), source_experiment_id: sourceId,
    poses: choices.map((pose) => ({
      id: pose.id, x: pose.x, y: pose.y, theta: pose.theta,
      manual: pose.manual === true, pareto_layer: pose.paretoLayer ?? 1,
      ...(pose.derivedFrom ? { derived_from: pose.derivedFrom } : {}),
    })),
  };
}
