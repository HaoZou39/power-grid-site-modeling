import type { SceneFrameInfo } from "../map/site_frame.js";
import { RoutingEdit } from "./routing_edit.js";
import { parseRoutingResult } from "./routing_result.js";
import { readFilterSnapshot } from "../results/filter_snapshot.js";

/** Parse both artifacts before the workspace replaces its current result. */
export async function readRoutingExperiment(
  record: { artifacts: readonly { name: string; url: string }[] },
  scene: { id: string; frame: SceneFrameInfo | null },
  readText: (url: string) => Promise<string>,
) {
  if (!scene.frame) throw new Error("当前场景没有有效网格。");
  const filterSnapshot = await readFilterSnapshot(record, readText);
  if (filterSnapshot) {
    if (filterSnapshot.problem_type !== "routing" || filterSnapshot.scene_name !== scene.id) throw new Error("筛选案例不属于当前选线场景。");
    const task = filterSnapshot.context.task as Record<string, unknown>;
    if (!task || task.scene_name !== scene.id) throw new Error("筛选案例任务与场景不一致。");
    const bundle = parseRoutingResult(JSON.stringify({ schema_version: 1, problem_type: "routing", scene_name: filterSnapshot.scene_name,
      frame: filterSnapshot.context.frame, data_version: filterSnapshot.scene_version,
      routes: filterSnapshot.candidates.map((item) => ({ ...item.data, number: item.original_number })) }), scene.id, scene.frame);
    return { bundle, task, edit: RoutingEdit.fromTask(task), filterSnapshot };
  }
  const find = (name: string) => record.artifacts.find((item) => item.name === name)?.url;
  const routeUrl = find("routes.json");
  const configUrl = find("resolved_config.json");
  if (!routeUrl || !configUrl) throw new Error("选线产物不完整。");
  const [routeText, configText] = await Promise.all([readText(routeUrl), readText(configUrl)]);
  const bundle = parseRoutingResult(routeText, scene.id, scene.frame);
  const task = JSON.parse(configText) as Record<string, unknown>;
  if (!task || typeof task !== "object" || Array.isArray(task) || task.scene_name !== scene.id) {
    throw new Error("选线配置与当前场景不一致。");
  }
  const edit = RoutingEdit.fromTask(task);
  return { bundle, task, edit, filterSnapshot: null };
}
